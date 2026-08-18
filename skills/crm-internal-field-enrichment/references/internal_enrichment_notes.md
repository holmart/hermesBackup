# Internal Field Enrichment Notes

This reference documents key observations and decisions made during the development of the `crm-internal-field-enrichment` skill.

## Key Learnings from Session

1. **User Priority**: The user explicitly stated that NIT is not important; focus should be on obtaining a verifiable person's name for `RepresentanteLegal`, plus reliable phone and email.

2. **Internal Fields as Primary Source**: Due to persistent anti-bot measures (CAPTCHA) on public search engines and the JavaScript-heavy nature of official sources like RUES, the most reliable immediate source of data is the existing internal fields in the CRM:
   - `Responsable`: Often contains the representative legal name when it is a person-like value.
   - `TelefonosExtra` and `EmailExtra`: Alternate contact fields that may hold valid data when the primary `Telefono` or `Email` is missing or malformed.

3. **Heuristics for Person Name**:
   - Must be at least two words.
   - Each word must start with an uppercase letter (including accented).
   - Must not match a list of generic roles (e.g., "Gerencia", "Contacto", "Servicio al Cliente").
   - This filter avoids false positives like job titles or department names.

4. **Email-to-Name Extraction**:
   - When `Responsable` is insufficient, the local part of an email address (before `@`) can sometimes yield a name.
   - Common separators (`._-`) are replaced with spaces, and the result is title-cased.
   - The same person-name validation is applied to avoid extracting generic terms like "info" or "contacto".

5. **Field Independence**:
   - The enrichment does not require NIT or website accessibility. This makes it robust for companies with missing or invalid external identifiers.
   - However, if external verification is desired (e.g., for audit), NIT and website can be used in a separate enrichment pass.

6. **Idempotency and Safety**:
   - Updates are conditional: only occur if the new value differs from the current one.
   - A timestamp (`FechaActualizacion`) and source flag (`FuenteRepLegal='internal_fields'`) are always recorded for traceability.
   - Dry-run mode allows previewing changes before applying.

## Performance & Observations

- In a dry-run over 258 records, the script identified a small number of updatable records (e.g., name from `Responsable`, phone/email from `*_Extra` fields).
- The majority of records had no improvement possible via internal fields alone, indicating that external sources may still be needed for significant gaps.
- The script is lightweight and safe to run frequently (e.g., daily or weekly) as a preprocessing step before attempting more costly external enrichment.

## Future Improvements

- If internal enrichment yields insufficient coverage, consider integrating with:
  - **RUES API** (if JavaScript rendering can be bypassed or handled via headless browser).
  - **Cámara de Comercio APIs** (official source for representative legal).
  - **Email validation services** to confirm deliverability of corrected email addresses.
- Periodic review of the generic roles list to avoid over-filtering (e.g., some companies may legitimately have "Gerencia" as a legal representative if it's a sole proprietorship registered that way).

## References

- Script: `scripts/internal_enrich.py`
- DynamoDB table: `sifagent-crm-clients`
- Primary fields: `RepresentanteLegal`, `Telefono`, `Email`
- Secondary fields: `Responsable`, `TelefonosExtra`, `EmailExtra`