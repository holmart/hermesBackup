#!/usr/bin/env python3
"""
CRM Internal Field Enrichment — v2
====================================
Updates RepresentanteLegal, Telefono, Email from internal CRM fields.
Does NOT require external APIs or web scraping.

Improvements over v1:
1. Paginates DynamoDB scan (handles CRM > 1MB)
2. Uses ContactoPrincipal as source for RepresentanteLegal
3. Prioritizes business emails over generic ones
4. Sends Telegram summary with updated companies
5. Normalizes phone format to +57...
6. Better logging

Runs via Hermes cron: Mon/Wed/Fri at 09:00 UTC
"""
import subprocess
import json
import re
import datetime
import sys
import os
import unicodedata


# =============================================================================
# CONFIG
# =============================================================================

TABLE = "sifagent-crm-clients"
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
HERMES_HOME = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")

# =============================================================================
# PHONE / EMAIL VALIDATION
# =============================================================================

def normalize_phone(val: str) -> str:
    """Normalize a Colombian phone to +57XXXXXXXXXX format."""
    if not val:
        return ""
    s = re.sub(r"[\s\-\(\)\.]", "", val.strip())
    if s.startswith("+"):
        s = s[1:]
    # Remove country code if present
    if s.startswith("57") and len(s) == 12:
        digits = s[2:]
    elif len(s) == 10 and s.startswith("3"):
        digits = s
    elif len(s) == 7:  # landline
        return val.strip()  # keep as-is
    else:
        return val.strip()

    if digits.startswith("3") and len(digits) == 10:
        # Reject repetitive
        if len(set(digits)) <= 2:
            return ""
        return f"+57{digits}"
    return val.strip()


def is_valid_phone(val: str) -> bool:
    """Check if phone is valid and non-placeholder."""
    if not val or not isinstance(val, str):
        return False
    s = re.sub(r"[\s\-\(\)\+\.]", "", val.strip())
    if not s.isdigit():
        return False
    if not (7 <= len(s) <= 15):
        return False
    if len(set(s)) <= 2:
        return False
    return True


def is_valid_email(val: str) -> bool:
    """Simple email validation."""
    if not val or not isinstance(val, str):
        return False
    pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
    return re.match(pattern, val.strip()) is not None


# Email priority: lower index = better for prospecting
EMAIL_PRIORITY_PREFIXES = [
    "gerencia", "gerente", "director", "admin", "comercial",
    "contacto", "info", "ventas", "servicio",
]

GENERIC_EMAIL_PREFIXES = {"info", "contacto", "ventas", "servicio", "soporte", "noreply", "no-reply"}


def email_priority_score(email: str) -> int:
    """Lower score = better email for prospecting."""
    if not email:
        return 99
    prefix = email.split("@")[0].lower()
    for i, p in enumerate(EMAIL_PRIORITY_PREFIXES):
        if prefix.startswith(p):
            return i
    return 50  # unknown prefix, middle priority


def is_generic_email(email: str) -> bool:
    """Check if email is a generic role-based address."""
    if not email:
        return True
    prefix = email.split("@")[0].lower()
    return prefix in GENERIC_EMAIL_PREFIXES


# =============================================================================
# NAME VALIDATION
# =============================================================================

CARGO_STOPWORDS = {
    "gerencia", "gerente", "dirección", "director", "presidente",
    "encargado", "jefe", "supervisor", "coordinador", "administrador",
    "administrativo", "asistente", "secretario", "tesorero", "vocero",
    "representante", "contacto", "servicio", "comercial", "ventas",
    "control", "operaciones", "producción", "calidad", "logística",
    "recursos", "talento", "humano", "finanzas", "contabilidad",
    "legal", "jurídico", "marketing", "soporte", "tecnico", "técnico",
    "ingeniero", "doctor", "dr.", "dr", "sr.", "sr", "sra.", "sra",
    "lic.", "lic", "ing.", "ing",
}

NAME_INTERNAL_STOPWORDS = {
    "de", "del", "la", "las", "los", "san", "santa", "y", "e", "el",
}

FORBIDDEN_NAME_TOKENS = {
    "lavado", "desinfeccion", "tanques", "agua", "control", "plagas",
    "servicio", "mantenimiento", "limpieza", "fumigacion", "fumigación",
    "sanitizacion", "desratizacion", "certificacion", "seguridad",
    "higiene", "ambiental", "industrial", "comercial", "residencial",
    "domestico", "corporativo", "nacional", "internacional",
    "empresa", "empresas", "colombia", "bogota", "medellin", "cali",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def looks_like_person_name(val: str) -> bool:
    """Determines if a string looks like a person's name."""
    if not val or not isinstance(val, str):
        return False
    val = val.strip()
    if not val or len(val) < 5:
        return False

    raw_tokens = val.split()
    if len(raw_tokens) < 2 or len(raw_tokens) > 5:
        return False

    for i, tok in enumerate(raw_tokens):
        if not tok:
            return False
        core = tok.rstrip(".")
        if not core or not core[0].isalpha():
            return False
        if core[0].isdigit():
            return False

        norm = strip_accents(core.lower())

        if norm in FORBIDDEN_NAME_TOKENS:
            return False
        if norm in NAME_INTERNAL_STOPWORDS:
            if i == 0 or i == len(raw_tokens) - 1:
                return False
            continue
        if norm in CARGO_STOPWORDS:
            return False

        cleaned = re.sub(r"[\.\-\']", "", core)
        if not cleaned.isalpha():
            return False

    return True


def extract_name_from_email(email: str):
    """Attempt to extract a person's name from email local-part."""
    if not email or "@" not in email:
        return None
    local = email.split("@")[0]
    if not local:
        return None
    local = re.sub(r"[._\-]", " ", local)
    parts = [p for p in local.split() if p]
    if not parts or len(parts) < 2:
        return None
    if any(p.isdigit() for p in parts):
        return None
    candidate = " ".join(p.capitalize() for p in parts)
    if looks_like_person_name(candidate):
        return candidate
    return None


# =============================================================================
# DYNAMO HELPERS
# =============================================================================

def get_attr(item, key):
    d = item.get(key, {})
    return d.get("S") if isinstance(d, dict) else None


def scan_all_items():
    """Paginated scan of the full CRM table."""
    items = []
    start_key = None
    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE,
            "--region", REGION,
            "--projection-expression",
            "PK, SK, RepresentanteLegal, Responsable, CargoResponsable, ContactoPrincipal, Telefono, TelefonosExtra, Email, EmailExtra, EmailContacto, NombreComercial",
        ]
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
            data = json.loads(result.stdout)
            items.extend(data.get("Items", []))
            start_key = data.get("LastEvaluatedKey")
            if not start_key:
                break
        except Exception as e:
            print(f"Scan error: {e}")
            break
    return items


def update_item(pk, sk, changes):
    """Update fields in DynamoDB."""
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    changes["FechaActualizacion"] = now
    if "RepresentanteLegal" in changes:
        changes["FuenteRepLegal"] = "internal_fields_v2"

    set_clauses = []
    expr_vals = {}
    for i, (field, val) in enumerate(changes.items()):
        placeholder = f":v{i}"
        set_clauses.append(f"{field} = {placeholder}")
        expr_vals[placeholder] = {"S": val}

    cmd = [
        "aws", "dynamodb", "update-item",
        "--table-name", TABLE,
        "--region", REGION,
        "--key", json.dumps({"PK": {"S": pk}, "SK": {"S": sk}}),
        "--update-expression", "SET " + ", ".join(set_clauses),
        "--expression-attribute-values", json.dumps(expr_vals),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


# =============================================================================
# TELEGRAM
# =============================================================================

def send_telegram_summary(updated_companies, total, skipped, failed):
    """Send a brief Telegram report with enrichment results."""
    env_file = os.path.join(HERMES_HOME, ".env")
    bot_token = ""
    chat_id = ""
    if os.path.isfile(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    bot_token = line.split("=", 1)[1].strip().strip("\"'")
                elif line.startswith("TELEGRAM_ALLOWED_USERS="):
                    chat_id = line.split("=", 1)[1].strip().strip("\"'").split(",")[0]

    if not bot_token or not chat_id:
        return

    header = f"🔄 *Enriquecimiento CRM — {datetime.datetime.utcnow().strftime('%Y-%m-%d')}*\n"
    header += f"📊 Total: {total} | Actualizados: {len(updated_companies)} | Sin cambios: {skipped} | Errores: {failed}\n\n"

    body = ""
    if updated_companies:
        body = "*Empresas actualizadas:*\n"
        for name, fields in updated_companies[:10]:
            body += f"• {name}: {', '.join(fields)}\n"
        if len(updated_companies) > 10:
            body += f"_...y {len(updated_companies) - 10} más_\n"
    else:
        body = "_No hubo registros para actualizar._\n"

    message = header + body
    payload = json.dumps({
        "chat_id": chat_id, "text": message,
        "parse_mode": "Markdown", "disable_web_page_preview": True,
    })
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=15)


# =============================================================================
# MAIN LOGIC
# =============================================================================

def is_empty_or_generic(val):
    if val is None:
        return True
    val = val.strip()
    if not val or val.upper() in ["PENDIENTE", "N/A", "NULL", "0", "0000000000"]:
        return True
    generic = [
        "contacto", "gerencia", "servicio al cliente", "comercial", "ventas",
        "representante legal", "por determinar", "n/a", "null",
        "control de plagas", "lavado y desinfección", "administracion",
        "encargado", "supervisor", "jefe", "director", "presidente",
        "gerencia administrativa", "administrativo", "gerencia de operaciones",
        "direccion", "dirección", "coordinacion", "coordinación",
    ]
    return val.lower() in generic


def main():
    print("Starting internal field enrichment v2 (name, phone, email)...")
    print("=" * 60)
    print("Improvements: pagination, ContactoPrincipal, email priority, Telegram report")
    print("=" * 60)
    print()

    # Scan all items (paginated)
    items = scan_all_items()
    print(f"Total companies in CRM: {len(items)}")

    updated_companies = []  # (name, [fields changed])
    skipped = 0
    failed = 0

    for item in items:
        pk = get_attr(item, "PK")
        sk = get_attr(item, "SK")
        nombre = get_attr(item, "NombreComercial") or pk or "?"

        rep = get_attr(item, "RepresentanteLegal")
        resp = get_attr(item, "Responsable")
        cargo = get_attr(item, "CargoResponsable")
        contacto_principal = get_attr(item, "ContactoPrincipal")
        tel = get_attr(item, "Telefono")
        tel_extra = get_attr(item, "TelefonosExtra")
        email = get_attr(item, "Email")
        email_extra = get_attr(item, "EmailExtra")
        email_contacto = get_attr(item, "EmailContacto")

        changes = {}

        # --- 1. RepresentanteLegal ---
        needs_rep = is_empty_or_generic(rep) or not looks_like_person_name(rep or "")

        if needs_rep:
            # Priority order for name sources:
            candidates = []

            # a) CargoResponsable == "representante legal" → Responsable is the name
            if cargo and cargo.strip().lower() == "representante legal":
                if resp and looks_like_person_name(resp):
                    candidates.append(resp)

            # b) Responsable field directly
            if resp and looks_like_person_name(resp):
                candidates.append(resp)

            # c) ContactoPrincipal (from pipeline v5)
            if contacto_principal and looks_like_person_name(contacto_principal):
                candidates.append(contacto_principal)

            # d) Extract from email
            for em in [email, email_extra, email_contacto]:
                name = extract_name_from_email(em)
                if name:
                    candidates.append(name)

            # Pick first valid candidate
            if candidates:
                changes["RepresentanteLegal"] = candidates[0]

        # --- 2. Telefono ---
        if not is_valid_phone(tel or ""):
            # Try TelefonosExtra
            if tel_extra:
                # May contain multiple, take first valid
                for part in re.split(r"[,;|]", tel_extra):
                    normalized = normalize_phone(part.strip())
                    if is_valid_phone(normalized):
                        changes["Telefono"] = normalized
                        break
        else:
            # Normalize existing phone
            normalized = normalize_phone(tel)
            if normalized != tel and is_valid_phone(normalized):
                changes["Telefono"] = normalized

        # --- 3. Email ---
        # Upgrade generic email if a better one exists
        current_email = email or ""
        all_emails = [e for e in [email, email_extra, email_contacto] if e and is_valid_email(e)]

        if not is_valid_email(current_email):
            # No valid main email — pick best available
            if all_emails:
                best = min(all_emails, key=email_priority_score)
                changes["Email"] = best
        elif is_generic_email(current_email) and len(all_emails) > 1:
            # Main email is generic — is there a better one?
            non_generic = [e for e in all_emails if not is_generic_email(e) and e != current_email]
            if non_generic:
                best = min(non_generic, key=email_priority_score)
                if email_priority_score(best) < email_priority_score(current_email):
                    changes["Email"] = best

        # --- Apply changes ---
        if not changes:
            skipped += 1
            continue

        if update_item(pk, sk, changes):
            updated_companies.append((nombre, list(changes.keys())))
        else:
            failed += 1

    print()
    print("=" * 60)
    print("Enrichment completed!")
    print(f"  Updated: {len(updated_companies)}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")

    # Send Telegram summary
    send_telegram_summary(updated_companies, len(items), skipped, failed)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
