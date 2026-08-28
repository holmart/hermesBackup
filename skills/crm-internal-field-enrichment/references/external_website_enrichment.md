# External Website Enrichment for SIF Agent CRM

Session: 2026-08-27
Context: Pipeline v5 leads arrive without internal fields (Responsable, TelefonosExtra, EmailExtra), making internal enrichment ineffective.

## Approach

1. Fetch lead website via urllib (8s delay between requests)
2. Extract text: remove scripts/styles/tags, normalize whitespace
3. Send to LLM with structured prompt requesting NIT, RepLegal, Direccion, Telefonos, Emails
4. Validate outputs with regex patterns
5. Update DynamoDB with `FuenteEnriquecimiento: external_web_v1`

## Observed Coverage

| Field | Coverage | Notes |
|-------|----------|-------|
| Direccion | ~50% | Usually in contact/footer pages |
| Telefono | ~60% | Often better than pipeline-extracted |
| Email | ~50% | Corporate emails, not generic |
| NIT | ~0% | Not published on websites |
| RepresentanteLegal | ~0% | Not published on websites |

## Critical Pitfall: Cron Environment

Scripts run by Hermes cron do NOT inherit `.env` variables. Must explicitly load:

```python
ENV_PATH = os.path.expanduser("~/.hermes/.env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                if key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")
```

## urllib.request Gotcha

`urllib.request.Request()` constructor does NOT accept `timeout`. Pass timeout to `urlopen()`:

```python
req = urllib.request.Request(url, headers={...})
with urllib.request.urlopen(req, timeout=15) as resp:  # timeout HERE
    ...
```

## NIT / RepLegal Sources

- **informacolombia.com**: NIT visible in static HTML (no JS). RepLegal NOT exposed.
- **lasempresas.com.co**: Has RepLegal but SPA/JS-rendered — requires browser automation.
- **einforma.co**: Paywall/WAF blocks scraping.
- **RUES oficial**: CAPTCHA + anti-bot.

**Verdict:** NIT and RepLegal require paid API or manual lookup. Website enrichment only covers contact data (address, phone, email).

## Script Reference

`~/.hermes/scripts/external_enrich.py` — Production script with DRY_RUN support, progress tracking, Telegram reporting, and DynamoDB update with retry logic.
