# Piloto: consenso vs BetVIP

Recolecta automáticamente el precio justo de consenso (The Odds API, región EU, mercado 1X2)
para Premier League, LaLiga, Bundesliga, Serie A, Ligue 1 y Liga MX.

- `precios_objetivo.csv/.xlsx`: momio mínimo que una casa debe pagar para registrar la apuesta (justo + 2%).
- `cierres.csv/.xlsx`: promedio de momios de cierre (con margen) para calcular el CLV justo en la hoja del piloto.
- `capturas/`: archivo histórico de cada captura.

Requiere el secreto `ODDS_API_KEY` en Settings → Secrets and variables → Actions.
Para correr a mano: pestaña Actions → "Escaner de consenso" → Run workflow.
