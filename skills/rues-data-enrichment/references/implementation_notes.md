# RUES Enrichment Implementation Notes

## Current Working Implementation
- Script: `scripts/rues_fumigacion_enrich.py`
- Uses national search by razón social "control de plagas" (no chamber filter)
- Successfully extracts 43 active companies with NIT from various chambers of commerce
- Output CSV: `/home/ubuntu/.hermes/leads/rues_fumigacion_enrichment.csv`

## Key API Details
- Endpoint: `https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM` (POST)
- Required headers:
  - `accept: application/json, text/plain, */*`
  - `accept-language: en-US,en;q=0.9,es-CO;q=0.8,es;q=0.7`
  - `app-name: RuesFront`
  - `referer: https://www.rues.org.co/`
  - `content-type: application/json`
  - `user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36`
- Request body: `{"page":1,"pageSize":100,"texto":"control de plagas"}`

## Chamber Distribution (from latest run)
- BOGOTA: 7 empresas
- BARRANQUILLA: 6 empresas  
- BUCARAMANGA: 5 empresas
- ABURRA SUR: 4 empresas
- MEDELLIN PARA ANTIOQUIA: 4 empresas
- CARTAGENA: 3 empresas
- CALI: 2 empresas
- IBAGUE: 2 empresas
- ARMENIA: 1 empresa
- FACATATIVA: 1 empresa
- Plus others from various chambers

## Data Freshness
- Weekly cron job: `weekly_rues_enrichment` (ID: 4459f0c3c342)
- Schedule: Mondays 08:00 UTC
- Next run: 2026-08-17 08:00 UTC