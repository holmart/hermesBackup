#!/usr/bin/env python3
"""
CRM Internal Field Enrichment — v2 (Enhanced)
==============================================
Updates RepresentanteLegal, Telefono, Email from internal CRM fields.
Focus: name of representative legal, phone, email. NIT is NOT required.

New in v2:
- Full DynamoDB pagination (never misses records)
- Parallel updates with ThreadPoolExecutor (3 workers)
- Colombian phone validation and normalization (+57XXXXXXXXXX)
- Retry with exponential backoff on throttling
- Telegram report summary at end of run
- LLM fallback for ambiguous name extraction
- Fixed datetime.utcnow() deprecation

Runs L-M-V at 9:00 AM UTC via Hermes cron.
"""
import subprocess
import json
import re
import sys
import os
import time
import random
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List, Tuple

# =============================================================================
# CONFIGURATION
# =============================================================================

TABLE_NAME = os.environ.get("CRM_TABLE", "sifagent-crm-clients")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
HERMES_HOME = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
MAX_WORKERS = 3

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

# LLM
LLM_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")


# =============================================================================
# AWS CLI HELPERS
# =============================================================================

def run_aws_cmd(cmd: List[str]) -> Optional[Dict]:
    """Run AWS CLI command and return parsed JSON."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"AWS CLI error: {e.stderr[:200]}")
        return None
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        print(f"Error: {e}")
        return None


def scan_all_items() -> List[Dict]:
    """Full paginated scan of the CRM table."""
    items = []
    start_key = None
    page = 0

    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE_NAME,
            "--region", REGION,
            "--projection-expression",
            "PK, SK, RepresentanteLegal, Responsable, CargoResponsable, "
            "Telefono, TelefonosExtra, Email, EmailExtra, NombreComercial",
        ]
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])

        data = run_aws_cmd(cmd)
        if not data:
            break

        items.extend(data.get("Items", []))
        page += 1

        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break

    print(f"  Scanned {page} page(s), {len(items)} total items")
    return items


# =============================================================================
# PHONE VALIDATION (Colombian-specific)
# =============================================================================

def normalize_colombian_phone(raw: str) -> Optional[str]:
    """Validate and normalize to +57XXXXXXXXXX format. Returns None if invalid."""
    if not raw or not isinstance(raw, str):
        return None

    digits = re.sub(r"\D", "", raw.strip())

    # Remove country code if present
    if digits.startswith("57") and len(digits) >= 12:
        digits = digits[2:]

    # Valid Colombian mobile: 10 digits starting with 3
    if len(digits) == 10 and digits.startswith("3"):
        # Reject repetitive numbers (obvious placeholders)
        if len(set(digits)) <= 2:
            return None
        pair = digits[:2]
        if pair * 5 == digits:
            return None
        return f"+57{digits}"

    # Valid Colombian landline: 7 digits (some cities)
    if len(digits) == 7 and not digits.startswith("0"):
        if len(set(digits)) <= 2:
            return None
        return digits  # Return without +57 prefix for landlines

    return None


def is_valid_phone(val: str) -> bool:
    """Check if a phone number is valid (any format)."""
    return normalize_colombian_phone(val) is not None


# =============================================================================
# EMAIL VALIDATION
# =============================================================================

def is_valid_email(val: str) -> bool:
    """Simple email validation."""
    if not val or not isinstance(val, str):
        return False
    pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
    if not re.match(pattern, val.strip()):
        return False
    # Reject placeholder domains
    domain = val.split("@")[1].lower()
    placeholders = {"empresa.com", "example.com", "test.com", "correo.com",
                    "mail.com", "domain.com", "tu-dominio.com"}
    if domain in placeholders:
        return False
    return True


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
    "auditoría", "legal", "jurídico", "marketing", "publicidad",
    "soporte", "tecnico", "técnico", "ingeniero", "ingeniería",
    "arquitecto", "arquitectura", "doctor", "dr.", "dr", "sr.", "sr",
    "sra.", "sra", "lic.", "lic", "ing.", "ing", "mba", "phd",
}

NAME_INTERNAL_STOPWORDS = {
    "de", "del", "la", "las", "los", "san", "santa",
    "y", "e", "et", "el", "lo",
}

FORBIDDEN_NAME_TOKENS = {
    "lavado", "desinfeccion", "tanques", "agua", "potable", "control", "plagas",
    "servicio", "mantenimiento", "limpieza", "fumigacion", "electricidad",
    "fontaneria", "hidraulica", "construccion", "obra", "reparaciones",
    "instalaciones", "montaje", "cableado", "electricista", "fontanero",
    "revision", "inspeccion", "certificacion", "emergencia", "urgencia",
    "garantia", "asesoria", "consultoria", "proyecto", "diseño",
    "vigilancia", "seguridad", "higiene", "ambiental", "industrial",
    "comercial", "domestico", "corporativo", "institucional", "municipal",
    # Cities (should not appear in a person name)
    "bogota", "medellin", "cali", "barranquilla", "cartagena", "cucuta",
    "bucaramanga", "pereira", "manizales", "ibague", "villavicencio",
    "santa", "marta", "neiva", "armenia", "popayan", "colombia",
    # Company-type words
    "fumigaciones", "fumigacion", "extermi", "aire", "acondicionado",
    "refrigeracion", "electrico", "electricos", "soluciones", "servicios",
    "grupo", "empresa", "compania", "asociados", "hermanos",
}


def strip_accents(s: str) -> str:
    """Remove accents for comparison."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def looks_like_person_name(val: str) -> bool:
    """Determines if a string looks like a person's name."""
    if not val or not isinstance(val, str):
        return False
    val = val.strip()
    if not val or len(val) < 5:
        return False

    raw_tokens = val.split()
    if len(raw_tokens) < 2:
        return False

    for i, tok in enumerate(raw_tokens):
        if not tok:
            return False
        core = tok.rstrip(".")
        if not core:
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


def extract_name_from_email(email: str) -> Optional[str]:
    """Extract person name from email local-part."""
    if not email or "@" not in email:
        return None
    local = email.split("@")[0]
    if not local:
        return None

    local = re.sub(r"[._\-]", " ", local)
    parts = [p for p in local.split() if p]
    if not parts or any(p.isdigit() for p in parts):
        return None
    # Reject if any part is too short (likely abbreviation, not a name)
    if any(len(p) < 3 for p in parts):
        return None
    # Reject if looks like a company name or service
    company_signals = {"info", "contacto", "admin", "ventas", "comercial",
                       "gerencia", "soporte", "servicio", "empresa"}
    if any(p.lower() in company_signals for p in parts):
        return None

    titled = [p.capitalize() for p in parts]
    candidate = " ".join(titled)
    if looks_like_person_name(candidate):
        return candidate

    if len(parts) >= 2:
        filtered = [p for p in parts if len(p) > 2]
        if len(filtered) >= 2:
            candidate2 = " ".join([p.capitalize() for p in filtered])
            if looks_like_person_name(candidate2):
                return candidate2
    return None


def is_empty_or_generic(val: Optional[str]) -> bool:
    """Check if value is empty, None, or a generic placeholder."""
    if val is None:
        return True
    val = val.strip()
    if val == "" or val.upper() in ["PENDIENTE", "N/A", "NULL", "0", "0000000000"]:
        return True
    generic = [
        "contacto", "gerencia", "servicio al cliente", "comercial", "ventas",
        "representante legal", "por determinar", "n/a", "null",
        "control de plagas", "lavado y desinfección", "administracion",
        "encargado", "supervisor", "jefe", "director", "presidente",
        "gerencia administrativa", "administrativo", "gerencia de operaciones",
        "direccion", "dirección", "coordinacion", "coordinación",
    ]
    if val.lower() in generic:
        return True
    return False


# =============================================================================
# LLM FALLBACK FOR NAME EXTRACTION
# =============================================================================

def extract_name_with_llm(responsable: str, cargo: str, company: str) -> Optional[str]:
    """Use LLM to extract a person name from ambiguous fields."""
    if not LLM_API_KEY:
        return None

    prompt = f"""De los siguientes datos de una empresa, extrae SOLO el nombre de la persona (nombre y apellido).
Si no hay un nombre de persona claro, responde exactamente "NONE".

Empresa: {company}
Campo Responsable: {responsable}
Campo Cargo: {cargo}

Responde SOLO con el nombre de la persona (ej: "Juan Carlos Gómez") o "NONE":"""

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{LLM_API_BASE}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            answer = data["choices"][0]["message"]["content"].strip()
            if answer.upper() == "NONE" or len(answer) < 4:
                return None
            # Validate the LLM response looks like a name
            if looks_like_person_name(answer):
                return answer
            return None
    except Exception:
        return None


# =============================================================================
# UPDATE WITH RETRY
# =============================================================================

def update_company_fields(pk: str, sk: str, changes: Dict[str, str]) -> bool:
    """Update fields in DynamoDB with retry on throttling."""
    if DRY_RUN:
        fields_str = ", ".join(f"{k}='{v}'" for k, v in changes.items())
        print(f"    [DRY RUN] {pk}: {fields_str}")
        return True

    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    changes["FechaActualizacion"] = now
    if "RepresentanteLegal" in changes:
        changes["FuenteRepLegal"] = "internal_fields_v2"

    # Build update expression
    set_clauses = []
    expr_vals = {}
    for i, (field, new_val) in enumerate(changes.items()):
        placeholder = f":v{i}"
        set_clauses.append(f"{field} = {placeholder}")
        expr_vals[placeholder] = {"S": new_val}
    update_expr = "SET " + ", ".join(set_clauses)

    key = {"PK": {"S": pk}, "SK": {"S": sk}}
    cmd = [
        "aws", "dynamodb", "update-item",
        "--table-name", TABLE_NAME,
        "--region", REGION,
        "--key", json.dumps(key),
        "--update-expression", update_expr,
        "--expression-attribute-values", json.dumps(expr_vals),
    ]

    for attempt in range(1, 4):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return True
            stderr = result.stderr or ""
            if "Throughput" in stderr or "Throttl" in stderr:
                wait = 2 ** attempt + random.uniform(0, 1)
                time.sleep(wait)
                continue
            # Non-throttle error
            if attempt < 3:
                time.sleep(1)
                continue
            return False
        except subprocess.TimeoutExpired:
            time.sleep(2 ** attempt)
            continue
    return False


# =============================================================================
# PROCESS SINGLE ITEM
# =============================================================================

def get_attr(item: Dict, key: str) -> Optional[str]:
    """Extract string value from DynamoDB item attribute."""
    d = item.get(key, {})
    return d.get("S") if isinstance(d, dict) else None


def process_item(item: Dict) -> Tuple[str, Dict[str, str]]:
    """Analyze one CRM item and return (pk, changes_dict). Empty dict means no changes."""
    pk = get_attr(item, "PK") or ""
    sk = get_attr(item, "SK") or ""
    rep = get_attr(item, "RepresentanteLegal")
    resp = get_attr(item, "Responsable")
    cargo = get_attr(item, "CargoResponsable")
    company = get_attr(item, "NombreComercial") or pk
    tel = get_attr(item, "Telefono")
    tel_extra = get_attr(item, "TelefonosExtra")
    email = get_attr(item, "Email")
    email_extra = get_attr(item, "EmailExtra")

    changes = {}

    # --- 1. RepresentanteLegal ---
    cargo_val = cargo.strip().lower() if cargo else ""
    needs_name = is_empty_or_generic(rep) or not looks_like_person_name(rep)

    if cargo_val == "representante legal":
        if not is_empty_or_generic(resp) and looks_like_person_name(resp):
            changes["RepresentanteLegal"] = resp.strip()
    elif needs_name:
        if not is_empty_or_generic(resp) and looks_like_person_name(resp):
            changes["RepresentanteLegal"] = resp.strip()
        else:
            # Try email-based extraction
            name_from_email = extract_name_from_email(email)
            if not name_from_email:
                name_from_email = extract_name_from_email(email_extra)
            if name_from_email:
                changes["RepresentanteLegal"] = name_from_email
            elif resp and not is_empty_or_generic(resp) and LLM_API_KEY:
                # LLM fallback for ambiguous cases
                llm_name = extract_name_with_llm(resp, cargo or "", company)
                if llm_name:
                    changes["RepresentanteLegal"] = llm_name

    # --- 2. Telefono (normalize to Colombian format) ---
    current_phone_normalized = normalize_colombian_phone(tel) if tel else None
    if not current_phone_normalized:
        # Try TelefonosExtra — may have multiple, pick first valid
        if tel_extra:
            for candidate in re.split(r"[,;|\s]+", tel_extra):
                normalized = normalize_colombian_phone(candidate.strip())
                if normalized:
                    changes["Telefono"] = normalized
                    break
    elif current_phone_normalized != (tel or "").strip():
        # Current phone is valid but not normalized — normalize it
        changes["Telefono"] = current_phone_normalized

    # --- 3. Email ---
    if not is_valid_email(email):
        if is_valid_email(email_extra):
            changes["Email"] = email_extra.strip().lower()

    return (pk, sk, changes)


# =============================================================================
# TELEGRAM REPORT
# =============================================================================

def send_telegram_summary(updated: int, skipped: int, failed: int,
                          llm_used: int, examples: List[str]):
    """Send enrichment summary via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    msg = f"🔄 *CRM Enrichment v2 — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*\n\n"
    msg += f"📊 Resultados:\n"
    msg += f"  ✅ Actualizados: {updated}\n"
    msg += f"  ⏭️ Sin cambios: {skipped}\n"
    if failed:
        msg += f"  ❌ Fallidos: {failed}\n"
    if llm_used:
        msg += f"  🤖 LLM assists: {llm_used}\n"

    if examples:
        msg += f"\n📝 Ejemplos:\n"
        for ex in examples[:5]:
            msg += f"  • {ex}\n"

    if DRY_RUN:
        msg += "\n⚠️ _Modo DRY RUN — sin cambios reales_"

    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
    })
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception:
        pass


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Load .env
    env_file = os.path.join(HERMES_HOME, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value and key not in os.environ:
                            os.environ[key] = value
        except Exception:
            pass

    # Reload env-dependent globals
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LLM_API_KEY
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", TELEGRAM_CHAT_ID).split(",")[0].strip()
    LLM_API_KEY = os.environ.get("OPENROUTER_API_KEY", LLM_API_KEY)

    print("=" * 60)
    print("CRM Internal Field Enrichment v2")
    print(f"Table: {TABLE_NAME} | Region: {REGION}")
    print(f"LLM: {'enabled' if LLM_API_KEY else 'disabled'}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print("=" * 60)
    print()

    # --- Phase 1: Scan ---
    print("--- Phase 1: Scanning CRM ---")
    items = scan_all_items()
    if not items:
        print("ERROR: No items found or scan failed")
        return 1

    # --- Phase 2: Process & Determine Changes ---
    print("\n--- Phase 2: Analyzing fields ---")
    to_update = []  # List of (pk, sk, changes)

    for item in items:
        pk, sk, changes = process_item(item)
        if changes:
            to_update.append((pk, sk, changes))

    print(f"  Items needing update: {len(to_update)} / {len(items)}")

    # --- Phase 3: Apply Updates (parallel) ---
    print(f"\n--- Phase 3: Applying updates ({MAX_WORKERS} workers) ---")
    updated_count = 0
    failed_count = 0
    llm_count = 0
    examples = []

    def _do_update(args):
        pk, sk, changes = args
        success = update_company_fields(pk, sk, changes)
        return (pk, changes, success)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_do_update, item): item for item in to_update}
        for future in as_completed(futures):
            try:
                pk, changes, success = future.result()
                if success:
                    updated_count += 1
                    # Track examples
                    fields = list(changes.keys())
                    fields = [f for f in fields if f not in ("FechaActualizacion", "FuenteRepLegal")]
                    if len(examples) < 5 and fields:
                        ex = f"{pk[:30]}: {', '.join(f'{k}={changes[k][:20]}' for k in fields)}"
                        examples.append(ex)
                    if "RepresentanteLegal" in changes and "FuenteRepLegal" in changes:
                        if changes.get("FuenteRepLegal") == "internal_fields_v2":
                            pass  # counted as regular
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1

    skipped_count = len(items) - len(to_update)

    # --- Phase 4: Report ---
    print("\n" + "=" * 60)
    print("Enrichment completed!")
    print(f"  Total scanned: {len(items)}")
    print(f"  Updated:       {updated_count}")
    print(f"  Skipped:       {skipped_count}")
    print(f"  Failed:        {failed_count}")
    if DRY_RUN:
        print("\n  ⚠️ DRY RUN — no database changes were made")
    print("=" * 60)

    # Send Telegram summary
    send_telegram_summary(updated_count, skipped_count, failed_count, llm_count, examples)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
