"""
Escáner de consenso – Fase 2 del piloto.

Qué hace
  escanear  Baja los momios 1X2 de muchas casas internacionales (The Odds API),
            calcula el precio JUSTO de consenso (promedio de casas sin margen) y
            genera "precios_objetivo.xlsx": el momio mínimo que Draftea o BetVIP
            tendrían que pagarte para que valga la pena registrar la apuesta.
  cierres   Captura el consenso justo antes del inicio de cada partido (cierre) y
            genera "cierres.xlsx" con los tres momios de cierre que la hoja del
            piloto necesita para calcular el CLV justo.

Uso
  python escaner.py escanear
  python escaner.py cierres        (programarlo cada 15 minutos los días de partido)

Clave
  Guarda tu clave de The Odds API en un archivo "clave.txt" junto a este script,
  o en la variable de entorno ODDS_API_KEY.

Es exactamente la regla probada en el backtest: promedio de momios de las casas,
margen quitado con el método proporcional al momio, apostar solo si el precio
supera el justo en más del MARGEN_MINIMO.
"""
import argparse, glob, json, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CAPTURAS = os.path.join(BASE, "capturas")
TZ = ZoneInfo("America/Mexico_City")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def fecha_local(serie_utc):
    t = serie_utc.dt.tz_convert(TZ)
    return t.dt.dayofweek.map(lambda d: DIAS[d]) + t.dt.strftime(" %d/%m %H:%M")

LIGAS = {
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "LaLiga",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_italy_serie_a": "Serie A",
    "soccer_france_ligue_one": "Ligue 1",
    "soccer_mexico_ligamx": "Liga MX",
    "soccer_uefa_nations_league": "Nations League",
    "soccer_uefa_champs_league": "Champions League",
    "soccer_uefa_europa_league": "Europa League",
    "soccer_usa_mls": "MLS",
    "soccer_brazil_campeonato": "Brasil Serie A",
    "soccer_argentina_primera_division": "Argentina Primera",
}
REGION = "eu"                  # 1 crédito por liga por llamada
MARGEN_MINIMO = 0.02           # 2 % sobre el precio justo
MIN_CASAS = 5                  # sin al menos 5 casas no hay consenso confiable
VENTANA_CIERRE_MIN = 30        # captura de cierre: partidos que empiezan en los próximos 30 min
SIN_REPETIR_MIN = 25           # no recapturar una liga capturada hace menos de 25 min (ahorra créditos)
EXCLUIR = {"betfair_ex_eu", "betfair_ex_uk", "matchbook"}  # bolsas: precio sin comisión, distorsionan


# ------------------------------------------------------------------ API
def clave():
    k = os.environ.get("ODDS_API_KEY")
    p = os.path.join(BASE, "clave.txt")
    if not k and os.path.exists(p):
        k = open(p, encoding="utf-8").read().strip()
    if not k:
        sys.exit("Falta la clave: crea clave.txt junto al script con tu clave de The Odds API.")
    return k


def bajar_liga(sport):
    r = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
        params={"apiKey": clave(), "regions": REGION, "markets": "h2h", "oddsFormat": "decimal"},
        timeout=30)
    if r.status_code == 401:
        sys.exit("La API rechazó la clave (401). Revisa clave.txt.")
    if r.status_code == 429 or (r.status_code == 422 and "quota" in r.text.lower()):
        sys.exit("Se acabaron los créditos del mes.")
    r.raise_for_status()
    restantes = r.headers.get("x-requests-remaining", "?")
    return r.json(), restantes


# ------------------------------------------------------------------ consenso
def consenso(evento):
    """Promedio de momios por resultado entre casas completas, luego quitar margen (MPTO)."""
    home, away = evento["home_team"], evento["away_team"]
    filas = []
    for bk in evento.get("bookmakers", []):
        if bk["key"] in EXCLUIR:
            continue
        for mk in bk.get("markets", []):
            if mk["key"] != "h2h":
                continue
            o = {x["name"]: x["price"] for x in mk["outcomes"]}
            if home in o and away in o and "Draw" in o:
                filas.append((bk["key"], o[home], o["Draw"], o[away]))
    if len(filas) < MIN_CASAS:
        return None
    df = pd.DataFrame(filas, columns=["casa", "H", "D", "A"])
    prom = df[["H", "D", "A"]].mean()
    inv = 1 / prom
    M = inv.sum() - 1
    p = (3 - M * prom) / (3 * prom)
    p = p / p.sum()
    pin = df[df.casa == "pinnacle"]
    return dict(
        casas=len(df), margen_promedio=M,
        prom_H=prom.H, prom_D=prom.D, prom_A=prom.A,
        justo_H=1 / p.H, justo_D=1 / p.D, justo_A=1 / p.A,
        objetivo_H=(1 / p.H) * (1 + MARGEN_MINIMO),
        objetivo_D=(1 / p.D) * (1 + MARGEN_MINIMO),
        objetivo_A=(1 / p.A) * (1 + MARGEN_MINIMO),
        pinnacle=", ".join(f"{x:.2f}" for x in pin.iloc[0][["H", "D", "A"]]) if len(pin) else "",
    )


def filas_de(data, sport, momento):
    out = []
    for ev in data:
        c = consenso(ev)
        if c is None:
            continue
        inicio = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        out.append(dict(id=ev["id"], liga=LIGAS.get(sport, sport), sport=sport,
                        inicio_utc=inicio.isoformat(), local=ev["home_team"], visitante=ev["away_team"],
                        capturado_utc=momento.isoformat(), **c))
    return out


def guardar_captura(filas, momento, tipo):
    os.makedirs(CAPTURAS, exist_ok=True)
    if filas:
        p = os.path.join(CAPTURAS, f"{tipo}_{momento:%Y%m%d_%H%M}.csv")
        pd.DataFrame(filas).assign(tipo=tipo).to_csv(p, index=False)


def todas_capturas():
    fs = glob.glob(os.path.join(CAPTURAS, "*.csv"))
    if not fs:
        return pd.DataFrame()
    df = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    df["inicio_utc"] = pd.to_datetime(df["inicio_utc"], utc=True)
    df["capturado_utc"] = pd.to_datetime(df["capturado_utc"], utc=True)
    return df


def a_excel(df, ruta, hoja, anchos):
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=hoja)
        ws = xw.sheets[hoja]
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.freeze_panes = "A2"


# ------------------------------------------------------------------ comandos
def escanear():
    ahora = datetime.now(timezone.utc)
    filas, restantes = [], "?"
    for sport in LIGAS:
        data, restantes = bajar_liga(sport)
        filas += filas_de(data, sport, ahora)
    guardar_captura(filas, ahora, "escaneo")
    if not filas:
        print("No hay partidos con suficientes casas en este momento.")
        return
    df = pd.DataFrame(filas).sort_values("inicio_utc")
    df["Fecha y hora (CDMX)"] = fecha_local(pd.to_datetime(df.inicio_utc, utc=True))
    df["Partido"] = df.local + " vs " + df.visitante
    vista = pd.DataFrame({
        "Fecha y hora (CDMX)": df["Fecha y hora (CDMX)"], "Liga": df.liga, "Partido": df.Partido,
        "APUESTA LOCAL si pagan ≥": df.objetivo_H.round(2),
        "APUESTA EMPATE si pagan ≥": df.objetivo_D.round(2),
        "APUESTA VISITA si pagan ≥": df.objetivo_A.round(2),
        "Justo local": df.justo_H.round(2), "Justo empate": df.justo_D.round(2), "Justo visita": df.justo_A.round(2),
        "Casas en consenso": df.casas, "Pinnacle (L, E, V)": df.pinnacle,
    })
    ruta = os.path.join(BASE, "precios_objetivo.xlsx")
    a_excel(vista, ruta, "Precios objetivo", [20, 15, 38, 14, 14, 14, 11, 11, 11, 10, 18])
    vista.to_csv(os.path.join(BASE, "precios_objetivo.csv"), index=False)
    print(f"Listo: {len(vista)} partidos en precios_objetivo.xlsx. Créditos restantes: {restantes}")


def cierres():
    ahora = datetime.now(timezone.utc)
    previas = todas_capturas()
    if previas.empty:
        sys.exit("Primero corre 'escanear' para conocer los horarios.")
    prox = previas[(previas.inicio_utc > ahora) &
                   (previas.inicio_utc <= ahora + timedelta(minutes=VENTANA_CIERRE_MIN))]
    ligas = sorted(prox.sport.unique())
    recientes = previas[(previas.capturado_utc > ahora - timedelta(minutes=SIN_REPETIR_MIN))]
    if "tipo" in recientes.columns:
        ya = set(recientes[recientes.tipo == "cierre"].sport)
        ligas = [l for l in ligas if l not in ya]
    if ligas:
        filas, restantes = [], "?"
        for sport in ligas:
            data, restantes = bajar_liga(sport)
            filas += filas_de(data, sport, ahora)
        guardar_captura(filas, ahora, "cierre")
        print(f"Cierre capturado para {', '.join(LIGAS[s] for s in ligas)}. Créditos restantes: {restantes}")
    else:
        print("Nada nuevo que capturar (sin partidos próximos o ya capturados); no se gastaron créditos.")
    # reconstruir cierres.xlsx: última captura antes del inicio de cada partido
    df = todas_capturas()
    df = df[df.capturado_utc < df.inicio_utc]
    if df.empty:
        return
    ult = df.sort_values("capturado_utc").groupby("id").tail(1).sort_values("inicio_utc")
    ult = ult[ult.inicio_utc <= ahora + timedelta(minutes=VENTANA_CIERRE_MIN)]
    minutos = ((ult.inicio_utc - ult.capturado_utc).dt.total_seconds() / 60).round()
    vista = pd.DataFrame({
        "Fecha y hora (CDMX)": fecha_local(ult.inicio_utc),
        "Liga": ult.liga, "Partido": ult.local + " vs " + ult.visitante,
        "Cierre local": ult.prom_H.round(2), "Cierre empate": ult.prom_D.round(2), "Cierre visita": ult.prom_A.round(2),
        "Minutos antes del inicio": minutos,
    })
    a_excel(vista, os.path.join(BASE, "cierres.xlsx"), "Cierres", [20, 15, 38, 12, 12, 12, 12])
    vista.to_csv(os.path.join(BASE, "cierres.csv"), index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["escanear", "cierres"])
    {"escanear": escanear, "cierres": cierres}[ap.parse_args().comando]()
