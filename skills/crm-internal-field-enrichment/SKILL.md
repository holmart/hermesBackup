---
name: crm-internal-field-enrichment
description: Enrich CRM using internal fields for name, phone, email.
version: 1.2.0
author: Hermes Agent
category: data-enrichment
---
# CRM Internal Field Enrichment Skill

This skill enriches the `sifagent-crm-clients` DynamoDB table with verified representative legal information **exclusively from internal fields** (`Responsable`, `CargoResponsable`, `TelefonosExtra`, `EmailExtra`) and email local parts. It does **not** require NIT, website, or external sources, making it suitable for routine data quality improvement when external scraping is blocked, unavailable, or not desired.

**See also:** `references/external_website_enrichment.md` for the complementary website-scraping approach when internal fields are insufficient.

## When to Use

- When the CRM contains missing, empty, or generic values in the `RepresentanteLegal`, `Telefono`, or `Email` fields
- When you need to improve data quality for compliance, facturación, or operational purposes
- As a periodic data quality improvement job, especially when external web scraping is unreliable due to anti-bot measures or lack of web presence
- **As a first pass before official data verification** (e.g., before running weekly RUES enrichment for NIT and razón social validation)
- When the user prioritizes representative legal name, phone, and email over NIT (as specified by the user)
- **Preference**: Prioritize enrichment using internal fields (`Responsable`, `TelefonosExtra`, `EmailExtra`, `CargoResponsable`) before falling back to website scraping or public registries. This reduces reliance on NIT and external sources for compliance-critical fields.

## Prerequisites

1. AWS CLI configured with permissions to read/write to `sifagent-crm-clients` table
2. No external tools required; enrichment relies solely on internal DynamoDB fields

## Skill Workflow

### 1. Identify Target Records
Scans the DynamoDB table for **all records** (no pre‑filtering by NIT, website, or any other external attribute). For each record, evaluates whether any of the three target fields need improvement:

- **RepresentanteLegal**: missing, empty, or equals a generic role/contact title (see list below)
- **Telefono**: does not look like a valid Colombian phone number (7‑15 digits, not all identical)
- **Email**: does not pass a basic email format validation

Generic roles that are considered insufficient for `RepresentanteLegal` include:
`contacto`, `gerencia`, `servicio al cliente`, `comercial`, `ventas`, `representante legal`, `por determinar`, `n/a`, `null`, `servicio al cliente`, `control de plagas`, `lavado y desinfección`, `gerencia`, `administracion`, `encargado`, `supervisor`, `jefe`, `director`, `presidente`, `gerencia administrativa`, `administrativo`, `gerencia de operaciones`, `direccion`, `dirección`, `coordinacion`, `coordinación`.

### 2. Improve Representative Legal Name
For records where `RepresentanteLegal` is insufficient:

1. **Check CargoResponsable**: If `CargoResponsable` is exactly "Representante Legal" (case‑insensitive), treat `Responsable` as a strong signal for the representative legal name.
2. **Validate Responsable**: If `Responsable` contains a person‑like name (at least two words, each starting with an uppercase letter, not a generic role, and not containing forbidden service descriptors), use it.
3. **Extract from Email**: If the above fails, attempt to extract a name from the email local part:
   - Take the part before `@` in `Email` (or `EmailExtra` if `Email` is invalid)
   - Replace separators `._-` with spaces
   - Convert to title case
   - Validate that the result looks like a person‑like name (same criteria as above)
   - If valid, use it as the new `RepresentanteLegal`
4. If neither source yields a valid name, leave the field unchanged (no update).

### 3. Improve Telefono
For records where `Telefono` is not a valid Colombian phone number:
- If `TelefonosExtra` contains a valid Colombian phone number, copy it to `Telefono`.
- Otherwise, leave `Telefono` unchanged (external lookup would be required for further improvement).

### 4. Improve Email
For records where `Email` does not pass basic email validation:
- If `EmailExtra` contains a valid email address, copy it to `Email`.
- Otherwise, leave `Email` unchanged.

### 5. Update DynamoDB
When any field is determined to be updatable:
- Set the field(s) to the new value(s)
- Set `FuenteRepLegal` to `internal_fields` (if `RepresentanteLegal` changed)
- Set `FechaActualizacion` to the current UTC timestamp (ISO 8601 with Z)
- Perform a conditional update only if the new value differs from the current one (idempotent)

## Environment Variables

- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)
- `DRY_RUN`: Set to `"true"` to preview changes without updating (default: false)

## Usage

### As a standalone script:
```bash
# Preview changes first
DRY_RUN=true hermes run skill crm-internal-field-enrichment

# Apply changes
DRY_RUN=false hermes run skill crm-internal-field-enrichment
```

### As a cron job (periodic enrichment):
```bash
hermes cronjob create \
  --name "periodic-crm-internal-enrich" \
  --schedule "0 9 * * 1"  # Mondays at 9 AM UTC \
  --prompt "Run CRM internal field enrichment for name, phone, email" \
  --skills crm-internal-field-enrichment
```

## Output Format

The skill returns a JSON summary with:
- `total_processed`: Number of records evaluated
- `updated`: Number of records where at least one field was changed
- `skipped`: Records where no field needed improvement
- `failed`: Records where an update attempt failed (e.g., DynamoDB permission error)
- `details`: Array of per‑result objects, each containing:
    - `pk`: Primary key of the record
    - `action`: `updated`, `skipped`, or `failed`
    - `changes`: Object listing which fields were modified (e.g., `{ \"RepresentanteLegal\": \"New Name\", \"Telefono\": \"3001234567\" }`)
    - `source`: For each changed field, indicates origin (`Responsable`, `CargoResponsable`, `EmailExtra`, `TelefonosExtra`, etc.)
    - `timestamp`: UTC timestamp of when the update would be/applied

## Example Output (DRY_RUN=true)

```json
{
  "total_processed": 258,
  "updated": 5,
  "skipped": 253,
  "failed": 0,
  "details": [
    {
      "pk": "FUMIGACIONES 7 24 SAS",
      "action": "updated",
      "changes": {
        "RepresentanteLegal": "FREDY YOBANNY OLARTE RAMIREZ"
      },
      "source": {
        "RepresentanteLegal": "Responsable (validated via CargoResponsable)"
      },
      "timestamp": "2026-08-08T12:11:54Z"
    },
    {
      "pk": "Siselcom S.A.S",
      "action": "updated",
      "changes": {
        "RepresentanteLegal": "ANDRÉS FELIPE GUZMÁN VILLEGAS"
      },
      "source": {
        "RepresentanteLegal": "Responsable (validated via CargoResponsable)"
      },
      "timestamp": "2026-08-08T12:11:54Z"
    }
  ]
}
```

## Limitations & Notes

- **Pipeline v5 leads have NO internal fields.** Leads generated by the v5 prospecting pipeline (`pipeline_v5_*`) arrive with `NombreComercial`, `Telefono`, `Email`, `Website`, `Ciudad`, and `Vertical` only. They do **not** have `Responsable`, `CargoResponsable`, `TelefonosExtra`, or `EmailExtra`. Running this skill on pipeline v5 leads will process 0 records. Use `crm-web-enrichment` first, then RUES or directory lookups for NIT/RepLegal.
- Relies solely on internal fields; will not improve data that is missing or malformed in those fields.
- Name extraction from email is heuristic and may produce false positives (e.g., `info@` → `Info`). The validation step (person‑like name check) mitigates this.
- Telefono and Email improvements only work if alternate internal fields (`TelefonosExtra`, `EmailExtra`) contain valid data.
- Updates are conditional and idempotent – safe to run repeatedly.
- For cases where internal fields are insufficient, consider integrating with RUES, Cámara de Comercio, or other external sources in a separate enrichment pass.

## Complementary: External Website Enrichment

When internal fields are insufficient (e.g., pipeline v5 leads that arrive without `Responsable`, `TelefonosExtra`, or `EmailExtra`), use **external website enrichment** as a second pass. See `references/external_website_enrichment.md` for full details.

Quick summary:
1. Fetch website → extract text → LLM extraction → validate → update
2. Coverage: Dirección ~50%, Teléfono ~60%, Email ~50%
3. **NIT and RepLegal are NOT available via website scraping** — require RUES or paid APIs

## Troubleshooting

- If no updates occur: Verify that the internal fields (`Responsable`, `CargoResponsable`, `TelefonosExtra`, `EmailExtra`) actually contain usable data for your dataset.
- If updates seem incorrect: Inspect the `details` array to see what values were derived and from which source.
- For persistent failures: Check AWS IAM permissions for the role running the skill; ensure `UpdateItem` on `sifagent-crm-clients` is allowed.
- **Cron pitfall**: Scripts executed by Hermes cron do NOT inherit shell environment variables from `~/.hermes/.env`. Explicitly load the `.env` file in the script before reading API keys or tokens.

## Source

This skill uses only data already present in the `sifagent-crm-clients` DynamoDB table. No external APIs, web scraping, or paid data sources are accessed during execution.

## References

- `scripts/internal_enrich.py` — Reference implementation
- `references/internal_enrichment_notes.md` — Development notes
- `references/external_website_enrichment.md` — Complementary website-scraping approach for when internal fields are insufficient