#!/usr/bin/env python3
"""
Enrichment script: updates RepresentanteLegal, Telefono, Email from internal fields when they look valid.
Focus: name of representative legal, phone, email. NIT is NOT required for enrichment.
"""
import subprocess
import json
import re
import datetime
import sys
import os
import unicodedata

def run_aws_cmd(cmd):
    """Run AWS CLI command and return parsed JSON"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"AWS CLI error: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return None

def get_attr(item, key):
    """Extract string value from DynamoDB item attribute"""
    d = item.get(key, {})
    return d.get('S') if isinstance(d, dict) else None

def is_empty_or_generic(val):
    """Check if value is empty, None, or a generic role"""
    if val is None:
        return True
    val = val.strip()
    if val == '' or val.upper() in ['PENDIENTE', 'N/A', 'NULL', '0', '0000000000']:
        return True
    # Generic roles that aren't person names
    generic = ['contacto', 'gerencia', 'servicio al cliente', 'comercial', 'ventas', 
               'representante legal', 'por determinar', 'n/a', 'null', 'servicio al cliente',
               'control de plagas', 'lavado y desinfección', 'gerencia', 'administracion',
               'encargado', 'supervisor', 'jefe', 'director', 'presidente',
               'gerencia administrativa', 'administrativo', 'gerencia de operaciones',
               'direccion', 'dirección', 'coordinacion', 'coordinación']
    if val.lower() in generic:
        return True
    return False

# Stopwords that indicate a cargo, not a name, especially if appearing as first token
CARGO_STOPWORDS = {
    'gerencia', 'gerente', 'dirección', 'director', 'presidente',
    'encargado', 'jefe', 'supervisor', 'coordinador', 'administrador',
    'administrativo', 'asistente', 'secretario', 'tesorero', 'vocero',
    'representante', 'contacto', 'servicio', 'comercial', 'ventas',
    'control', 'operaciones', 'producción', 'calidad', 'logística',
    'recursos', 'talento', 'humano', 'finanzas', 'contabilidad',
    'auditoría', 'legal', 'jurídico', 'marketing', 'publicidad',
    'soporte', 'tecnico', 'técnico', 'ingeniero', 'ingeniería',
    'arquitecto', 'arquitectura', 'doctor', 'dr.', 'dr', 'sr.', 'sr',
    'sra.', 'sra', 'lic.', 'lic', 'ing.', 'ing', 'mba', 'phd'
}

# Internal stopwords that can appear inside a name (e.g., de, del, la, los, y, etc.)
NAME_INTERNAL_STOPWORDS = {
    'de', 'del', 'la', 'las', 'los', 'san', 'santa',
    'y', 'e', 'et', 'el', 'lo', 'los', 'las'
}

# Tokens that are never part of a person's name (service descriptors, etc.)
FORBIDDEN_NAME_TOKENS = {
    'lavado', 'desinfeccion', 'tanques', 'agua', 'potable', 'control', 'plagas',
    'servicio', 'mantenimiento', 'limpieza', 'fumigacion', 'electricidad',
    'fontaneria', 'hidraulica', 'construccion', 'obra', 'reparaciones',
    'instalaciones', 'montaje', 'cableado', 'electricista', 'fontanero',
    'hidraulico', 'constructor', 'obrero', 'tecnico', 'tecnica',
    'revision', 'inspeccion', 'certificacion', 'emergencia', 'urgencia',
    'refacciones', 'refaccion', 'puesto', 'taller', 'cobertura', 'asistencia',
    'garantia', 'gestoria', 'asesoria', 'consultoria', 'projecto', 'proyecto',
    'disenio', 'diseño', 'planificacion', 'ejecucion', 'supervision',
    'vigilancia', 'seguridad', 'higiene', 'salubridad', 'ambiental',
    'ecologico', 'biologico', 'quimico', 'fisico', 'mecanico',
    'industrial', 'comercial', 'residential', 'domestico', 'corporativo',
    'institucional', 'municipal', 'department', 'area', 'zona', 'region',
    'ciudad', 'municipio', 'departamento', 'pais', 'nacional', 'internacional'
}

def strip_accents(s: str) -> str:
    """Remove accents for case-insensitive comparison."""
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def looks_like_person_name(val: str) -> bool:
    """
    Determines if a string looks like a person's name.
    Rules:
    - At least two whitespace-separated tokens.
    - Each token must start with a letter (including accented) or be a known abbreviation with a dot (Ing., Dr.).
    - Internal stopwords (de, del, la, los, y, etc.) are allowed only if not first or last token.
    - First token must NOT be a known cargo stopword (to avoid confusing titles with names).
    - Tokens that are in FORBIDDEN_NAME_TOKENS are never allowed (service descriptors, etc.).
    - Allows hyphens and apostrophes inside tokens (e.g., María-José, D'Angelo).
    - Ignores case for stopword matching.
    """
    if not val or not isinstance(val, str):
        return False
    val = val.strip()
    if not val:
        return False

    # Split by whitespace, keeping tokens with internal hyphens as one token
    raw_tokens = val.split()
    if len(raw_tokens) < 2:
        return False

    for i, tok in enumerate(raw_tokens):
        if not tok:
            return False

        # Allow abbreviations with a dot (Ing., Dr., Sr.)
        # Remove trailing dots for core checking
        core = tok.rstrip('.')
        if not core:
            return False  # token consisted only of dots

        first_char = core[0]
        # First character must be a letter (including accented) or a digit? we'll reject digits for names
        if not (first_char.isalpha() or first_char.isdigit()):
            # Reject if starts with non-letter/non-digit (should not happen)
            return False
        # We do not allow tokens that start with a digit as part of a person's name
        if first_char.isdigit():
            return False

        # Normalize token for stopword checks (lowercase, no accents)
        norm = strip_accents(core.lower())

        # If token is a forbidden token (service descriptor, etc.), reject
        if norm in FORBIDDEN_NAME_TOKENS:
            return False

        # If token is an internal stopword (de, del, la, los, y, etc.), it must not be first or last
        if norm in NAME_INTERNAL_STOPWORDS:
            if i == 0 or i == len(raw_tokens) - 1:
                return False
            # continue checking next token
            continue

        # If token is a cargo stopword, reject (especially if it's the first token)
        if norm in CARGO_STOPWORDS:
            return False

        # After removing dots, hyphens, apostrophes, the remainder should be only letters
        cleaned = re.sub(r"[\.\-\']", "", core)
        if not cleaned.isalpha():
            return False

    # All checks passed
    return True

def extract_name_from_email(email: str) -> str | None:
    """
    Attempt to extract a person's name from the local-part of an email address.
    Handles common separators (dot, underscore, hyphen) and discards obvious generic locals.
    """
    if not email or '@' not in email:
        return None
    local = email.split('@')[0]
    if not local:
        return None

    # Replace separators with space
    local = re.sub(r'[._\-]', ' ', local)
    # Split and filter empty
    parts = [p for p in local.split() if p]
    if not parts:
        return None
    # Discard if any part consists only of digits (unlikely to be a name)
    if any(p.isdigit() for p in parts):
        return None
    # Title-case each part
    titled = [p.capitalize() for p in parts]
    candidate = ' '.join(titled)
    if looks_like_person_name(candidate):
        return candidate
    # Try removing single-letter parts (possible initials) if still >=2 tokens
    if len(parts) >= 2:
        filtered = [p for p in parts if len(p) > 1]  # keep only multi-letter parts
        if len(filtered) >= 2:
            candidate2 = ' '.join([p.capitalize() for p in filtered])
            if looks_like_person_name(candidate2):
                return candidate2
    return None

def is_valid_phone(val: str) -> bool:
    """
    Validate a Colombian phone number.
    Accepts digits only, length 7-15, not all same digit.
    Also tolerates a leading '+', spaces, hyphens, parentheses which are stripped.
    """
    if not val or not isinstance(val, str):
        return False
    # Strip whitespace
    s = val.strip()
    # Allow leading + for country code
    if s.startswith('+'):
        s = s[1:]
    # Remove common formatting characters
    s = re.sub(r'[\s\-\(\)]', '', s)
    if not s.isdigit():
        return False
    if not (7 <= len(s) <= 15):
        return False
    # Reject obvious placeholders like all same digit
    if len(set(s)) == 1:
        return False
    return True

def is_valid_email(val: str) -> bool:
    """Simple email validation (allows subdomains and TLDs of length 2+)."""
    if not val or not isinstance(val, str):
        return False
    # Regex: local-part@domain where domain has at least one dot and TLD >=2 chars
    pattern = r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'
    return re.match(pattern, val) is not None

def build_update_expr(changed):
    """
    Build DynamoDB update expression and attribute values dict.
    changed: dict mapping field name to new value (string)
    Returns (update_expr, expr_attr_vals)
    """
    if not changed:
        return None, None
    set_clauses = []
    expr_vals = {}
    for i, (field, new_val) in enumerate(changed.items()):
        placeholder = f':{field}{i}'
        set_clauses.append(f'{field} = {placeholder}')
        expr_vals[placeholder] = {'S': new_val}
    update_expr = 'SET ' + ', '.join(set_clauses)
    return update_expr, expr_vals

def update_company_fields(pk, sk, changes):
    """Update the company's fields in DynamoDB"""
    dry_run = os.environ.get('DRY_RUN', '').lower() == 'true'
    if dry_run:
        fields_str = ', '.join(f"{k}='{v}'" for k, v in changes.items())
        print(f"    [DRY RUN] Would update {pk}: {fields_str}")
        return True

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    # Always update timestamp for any change
    changes['FechaActualizacion'] = now
    # If we updated RepresentanteLegal, also set source
    if 'RepresentanteLegal' in changes:
        changes['FuenteRepLegal'] = 'internal_fields'

    key = {"PK": {"S": pk}, "SK": {"S": sk}}
    update_expr, expr_vals = build_update_expr(changes)
    if not update_expr:
        return True  # nothing to do

    cmd = [
        'aws', 'dynamodb', 'update-item',
        '--table-name', 'sifagent-crm-clients',
        '--region', 'us-east-1',
        '--key', json.dumps(key),
        '--update-expression', update_expr,
        '--expression-attribute-values', json.dumps(expr_vals),
        '--return-values', 'ALL_NEW'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        # print(f"    Successfully updated {pk}")
        return True
    else:
        # print(f"    Failed to update {pk}: {result.stderr}")
        return False

def main():
    print("Starting internal field enrichment (name, phone, email)...")
    print("=" * 60)
    print("NOTE: This enrichment uses ONLY internal fields (Responsable, TelefonosExtra, EmailExtra, CargoResponsable)")
    print("      and does NOT require NIT, website, or external sources.")
    print("=" * 60)

    # Check for dry run mode
    dry_run = os.environ.get('DRY_RUN', '').lower() == 'true'
    if dry_run:
        print("RUNNING IN DRY-RUN MODE - NO DATABASE CHANGES WILL BE MADE")
    print()

    # Scan CRM for companies - include CargoResponsable for better name detection
    scan_cmd = [
        'aws', 'dynamodb', 'scan',
        '--table-name', 'sifagent-crm-clients',
        '--region', 'us-east-1',
        '--projection-expression', 'PK, SK, RepresentanteLegal, Responsable, CargoResponsable, Telefono, TelefonosExtra, Email, EmailExtra'
    ]
    scan_result = run_aws_cmd(scan_cmd)
    if not scan_result:
        print("Failed to scan CRM")
        return 1

    items = scan_result.get('Items', [])
    print(f"Total companies in CRM: {len(items)}")

    # Process each item
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    for item in items:
        pk = get_attr(item, 'PK')
        sk = get_attr(item, 'SK')
        rep = get_attr(item, 'RepresentanteLegal')
        resp = get_attr(item, 'Responsable')
        cargo = get_attr(item, 'CargoResponsable')
        tel = get_attr(item, 'Telefono')
        tel_extra = get_attr(item, 'TelefonosExtra')
        email = get_attr(item, 'Email')
        email_extra = get_attr(item, 'EmailExtra')

        # Determine what needs update
        changes = {}

        # 1. RepresentanteLegal
        # First, check if CargoResponsable indicates that Responsable is the representative legal
        cargo_val = cargo.strip().lower() if cargo else ''
        if cargo_val == 'representante legal':
            # Strong signal: Responsable should be the person name
            if not is_empty_or_generic(resp) and looks_like_person_name(resp):
                changes['RepresentanteLegal'] = resp
            # else leave as is (cannot improve)
        else:
            # Fallback to previous logic
            if is_empty_or_generic(rep) or not looks_like_person_name(rep):
                # Try Responsable
                if not is_empty_or_generic(resp) and looks_like_person_name(resp):
                    changes['RepresentanteLegal'] = resp
                else:
                    # Try to extract name from email fields
                    name_from_email = extract_name_from_email(email)
                    if not name_from_email:
                        name_from_email = extract_name_from_email(email_extra)
                    if name_from_email:
                        changes['RepresentanteLegal'] = name_from_email
                    # else leave as is (cannot improve)

        # 2. Telefono: try to improve if current invalid
        if not is_valid_phone(tel):
            # Try alternate telephone field
            if is_valid_phone(tel_extra):
                changes['Telefono'] = tel_extra
            # else cannot improve without external source
        # else current phone is valid, keep it

        # 3. Email
        if not is_valid_email(email):
            # Try EmailExtra if main email invalid
            if is_valid_email(email_extra):
                changes['Email'] = email_extra
            # else cannot improve

        # If no changes, skip
        if not changes:
            skipped_count += 1
            continue

        # Update the database (or simulate in dry run)
        if update_company_fields(pk, sk, changes):
            updated_count += 1
        else:
            failed_count += 1

    print("\n" + "=" * 60)
    print("Enrichment completed!")
    print(f"  Updated: {updated_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Failed:  {failed_count}")

    if dry_run:
        print("\nNOTE: This was a dry run. To actually update the database, run without DRY_RUN=true")

    return 0 if failed_count == 0 else 1

if __name__ == '__main__':
    sys.exit(main())