---
name: rues-data-enrichment
description: Enrich CRM with official NIT and razón social from RUES.
---
# RUES Data Enrichment Skill

This skill enriches the `sifagent-crm-clients` DynamoDB table with official data from Colombia's Registro Único Empresarial y Social (RUES), specifically the NIT (tax ID) and razón social (legal business name). It uses the RUES internal API endpoint `/api/ConsultasRUES/BusquedaAvanzadaRM` to retrieve structured records for companies matching fumigation and pest control activities.

## When to Use

- When you need to verify, correct, or fill missing NIT values in the CRM
- When you want to ensure the razón social field matches the official legal name from the Registro Mercantil
- As a periodic data quality improvement job (e.g., weekly) to maintain compliance-critical fields
- As a complement to internal field enrichment: run this skill after `crm-internal-field-enrichment` to validate and enrich NIT and razón social with official sources
- When the user prioritizes official government sources for critical identification fields over website scraping
- **Preference**: Use this skill to obtain officially verified NIT and razón social data from RUES for compliance purposes, understanding that it provides authoritative data for these specific fields
- **Preference**: Use this skill to obtain officially verified NIT and razón social data from RUES for compliance purposes, understanding that it provides authoritative data for these specific fields

## Prerequisites

1. AWS CLI configured with permissions to read/write to `sifagent-crm-clients` table
2. Access to the RUES API endpoint (requires specific headers and cookies obtained from a browser session)
3. The target companies must be registered with a Cámara de Comercio and appear in RUES search results for relevant activities (e.g., CIIU 8129 - "Actividades de control de plagas")

## Skill Workflow

### 1. Obtain Official Data from RUES

- Sends a POST request to `https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM` with:
  - Specific headers mimicking a real browser session (User-Agent, Accept, Referer, etc.)
  - Cookies from an authenticated session (obtained by visiting the RUES website)
  - A payload searching for fumigation companies by razón social "control de plagas" (national search across all chambers of commerce, eliminating chamber filters)
- Parses the JSON response containing an array of `registros`
- Each registro includes fields such as:
  - `nit` (with verification digit `dv`)
  - `razon_social`
  - `estado_matricula` (to filter only ACTIVE companies)
  - `id_rm`, `matricula`, `cod_camara`, `nom_camara`, `organizacion_juridica`, `ultimo_ano_renovado`, `categoria`

### 2. Filter for Active Fumigation Companies

- Keep only records where:
  - `estado_matricula` == `"ACTIVA"`
  - `nit` is present and not empty
- Optionally, further filter by `cod_camara` if regional focus is desired (default includes all cameras)

### 3. Prepare Enrichment Data

- For each filtered record, create a data item with:
  - `nit`: the NIT from RUES (to validate/update the CRM's NIT attribute)
  - `razon_social`: the official legal name (to update a field like `RazonSocialLegal` or similar)
  - Other metadata (id_rm, cámara, etc.) for reference/audit

### 4. Update CRM Records

- Match CRM records by NIT (stored as the `SK` attribute and the `NIT` attribute)
- For each matching CRM item:
  - If the CRM's `NIT` attribute differs from the RUES NIT, update it to the official value
  - If a field for official legal name exists (e.g., `RazonSocialLegal`), update it if it differs from the RUES `razon_social`
  - Set `FuenteEnriquecimiento` to `rues_api` (or similar) and update `FechaActualizacion`
- Perform conditional updates only when changes are detected
- If no matching CRM record is found for a RUES NIT, optionally log it for lead generation or manual review

### 5. Handle Non-Matching Records

- RUES records not found in the CRM may represent new prospects.
- These can be fed into a lead generation workflow (e.g., the `fumigation-lead-generation` skill) to discover websites and contact information.
- Alternatively, they can be inserted into the CRM as new records with minimal data (NIT, razón social) for later enrichment.

## Environment Variables

- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)
- `RUES_DATA_BODY`: The encrypted `dataBody` value required by the RUES API (must be kept confidential; treat as secret)
- `RUES_COOKIES`: String of cookies required for authentication (can be provided as a single string or parsed)
- `DRY_RUN`: Set to `"true"` to preview changes without updating the database (default: false)

## Usage

### As a standalone script:

```bash
# Preview changes first
DRY_RUN=true hermes run skill rues-data-enrichment

# Apply changes
DRY_RUN=false hermes run skill rues-data-enrichment
```

### As a cron job (weekly enrichment):

```bash
hermes cronjob create \\
  --name "monthly-rues-enrichment" \\
  --schedule "0 8 * * 1"  # Mondays at 8 AM UTC \\
  --prompt "Enrich CRM with official NIT and razón social from RUES" \\
  --skills rues-data-enrichment
```

## Output Format

The skill returns a JSON summary with:

- `total_processed`: Number of RUES registros evaluated
- `active_with_nit`: Number of records that are ACTIVE and have a NIT
- `matched_in_crm`: Number of those records that found a matching CRM item by NIT
- `updated_nit`: Number of CRM records where the NIT was corrected
- `updated_razon_social`: Number of CRM records where the official legal name was updated
- `details`: Array of per‑result objects, each containing:
    - `nit`: The NIT from RUES
    - `razon_social`: The official legal name
    - `matched`: Boolean indicating if a CRM record was found
    - `action`: One of `"nit_updated"`, `"razon_social_updated"`, `"both_updated"`, `"no_change"`, `"not_found_in_crm"`
    - `changes`: Object listing which fields were modified
    - `timestamp`: UTC timestamp of when the update would be/applied

## Example Output (DRY_RUN=true)

```json
{
  "total_processed": 71,
  "active_with_nit": 20,
  "matched_in_crm": 1,
  "updated_nit": 0,
  "updated_razon_social": 1,
  "details": [
    {
      "nit": "830041100",
      "razon_social": "FUMISERVI FUMIGACION Y SERVICIOS DE CONTROL DE PLAGAS S A S",
      "matched": true,
      "action": "razon_social_updated",
      "changes": {
        "RazonSocialLegal": "FUMISERVI FUMIGACION Y SERVICIOS DE CONTROL DE PLAGAS S A S"
      },
      "timestamp": "2026-08-08T20:30:00Z"
    },
    {
      "nit": "800204301",
      "razon_social": "ACPI SAS ASESORIAS CONTRA PLAGAS E INFESTACIONES",
      "matched": false,
      "action": "not_found_in_crm",
      "changes": {},
      "timestamp": "2026-08-08T20:30:00Z"
    }
    // ... more records
  ]
}
```

## Limitations & Notes

- The RUES API endpoint used requires specific session cookies and headers that may expire or change over time. The skill may need periodic updating of these values.
- The encrypted `dataBody` parameter appears to be static for the observed search but may vary with different search terms or time.
- Currently, the skill does not extract the representative legal name from RUES, as that data is not present in the `BusquedaAvanzadaRM` endpoint. For representative legal enrichment, continue to rely on internal fields (`crm-internal-field-enrichment`) or other sources.
- The skill focuses on enriching NIT and razón social; other fields (address, contacto, etc.) are not extracted from this endpoint but could be added if future API exploration reveals them.
- Updates are conditional and idempotent – safe to run repeatedly.

## References

- See `scripts/rues_fumigacion_enrich.py` for the reference implementation that fetches and filters RUES data.
- See `scripts/rues_update_crm.py` for the reference implementation that updates the CRM based on RUES data.
- See `references/rues_api_details.md` for session-specific details about the RUES API endpoint, headers, cookies, and observed behavior.

## Source

This skill uses only publicly available information from the RUES API, accessed via HTTPS with observed session characteristics. No private or paid data sources are accessed during execution.