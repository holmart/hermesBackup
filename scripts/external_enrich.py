#!/usr/bin/env python3
"""
CRM External Enrichment — v1
=============================
Enriquece leads del pipeline v5 extrayendo datos desde sus websites.
Usa web scraping + LLM para obtener:
  - NIT
  - RepresentanteLegal
  - Dirección
  - Teléfonos adicionales
  - Emails adicionales

Targets: leads con Score >= 4, Estado='nuevo', sin NIT ni RepLegal, con Website.
Rate-limited: 1 lead cada 8 segundos para no sobrecargar.
DRY_RUN por defecto.

Runs via Hermes cron (suggested: Mon/Wed/Fri 10:00 UTC).
"""
import subprocess
import json
import re
import os
import sys
import time
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

# =============================================================================
# LOAD ENV FROM .env FILE IF AVAILABLE
# =============================================================================

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

# =============================================================================
# CONFIGURATION
# =============================================================================

TABLE_NAME = os.environ.get("CRM_TABLE", "sifagent-crm-clients")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
MAX_LEADS_PER_RUN = int(os.environ.get("MAX_LEADS", "20"))  # conservative batch
DELAY_SECONDS = 8  # between website fetches

# LLM
LLM_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

# Progress file
PROGRESS_FILE = os.path.expanduser("~/.hermes/cron/external_enrich_progress.json")


# =============================================================================
# AWS HELPERS
# =============================================================================

def run_aws_cmd(cmd: List[str]) -> Optional[Dict]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)
    except Exception as e:
        print(f"AWS error: {e}")
        return None


def scan_leads_needing_enrichment() -> List[Dict]:
    """Scan CRM for leads with Score>=4, no NIT, no RepLegal, with Website."""
    items = []
    start_key = None
    page = 0

    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE_NAME,
            "--region", REGION,
            "--projection-expression",
            "PK, SK, NombreComercial, Website, Score, Vertical, Ciudad, Telefono, Email",
        ]
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])

        data = run_aws_cmd(cmd)
        if not data:
            break

        for item in data.get("Items", []):
            score = int(item.get("Score", {}).get("N", "0"))
            estado = item.get("Estado", {}).get("S", "nuevo")
            nit = item.get("NIT", {}).get("S", "")
            rep = item.get("RepresentanteLegal", {}).get("S", "")
            website = item.get("Website", {}).get("S", "")

            if score >= 4 and estado == "nuevo" and not nit and not rep and website:
                items.append(item)

        page += 1
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break

    print(f"  Scanned {page} page(s), {len(items)} leads need enrichment")
    return items


# =============================================================================
# WEB FETCH
# =============================================================================

def fetch_website_text(url: str) -> Tuple[str, bool]:
    """Fetch website and extract text. Returns (text, success)."""
    if not url.startswith("http"):
        url = "https://" + url

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-CO,es;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Simple text extraction: remove scripts, styles, tags
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:12000], True  # limit text length

    except Exception as e:
        print(f"    Error fetching {url}: {e}")
        return "", False


# =============================================================================
# LLM EXTRACTION
# =============================================================================

def extract_data_with_llm(company_name: str, website_text: str, website_url: str) -> Optional[Dict]:
    """Use LLM to extract structured data from website text."""
    if not LLM_API_KEY:
        return None

    prompt = f"""Analiza el siguiente texto extraído del sitio web de una empresa colombiana y extrae los datos solicitados.

Empresa: {company_name}
URL: {website_url}

Texto del sitio web:
---
{website_text[:8000]}
---

Extrae SOLO estos campos en formato JSON. Si un dato no está en el texto, usa null (no inventes):
- nit: número de identificación tributaria (formato: 123456789-0 o 900123456)
- representante_legal: nombre completo de la persona (NO un cargo genérico)
- direccion: dirección completa si aparece
- telefonos_extra: array de teléfonos adicionales encontrados
- emails_extra: array de emails adicionales encontrados
- fuente_datos: de dónde extrajiste los datos (ej: "footer", "página nosotros", "contacto")

Responde SOLO con un JSON válido, sin markdown ni explicaciones:
{{"nit": "...", "representante_legal": "...", "direccion": "...", "telefonos_extra": [...], "emails_extra": [...], "fuente_datos": "..."}}"""

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            answer = data["choices"][0]["message"]["content"].strip()

            # Clean markdown code blocks
            answer = re.sub(r"^```json\s*", "", answer)
            answer = re.sub(r"^```\s*", "", answer)
            answer = re.sub(r"```$", "", answer).strip()

            extracted = json.loads(answer)
            return extracted
    except Exception as e:
        print(f"    LLM error: {e}")
        return None


# =============================================================================
# VALIDATION
# =============================================================================

def validate_nit(nit: Optional[str]) -> Optional[str]:
    if not nit:
        return None
    nit = str(nit).strip().replace(".", "").replace(",", "")
    # Accept formats: 1234567890, 123456789-0, 900123456
    if re.match(r"^\d{9,10}(-\d)?$", nit):
        return nit
    return None


def validate_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    name = str(name).strip()
    if len(name) < 5:
        return None
    # Must be at least 2 words
    parts = name.split()
    if len(parts) < 2:
        return None
    # Reject generic job titles
    generic = {"gerente", "director", "administrador", "contacto", "servicio", "ventas", "representante legal", "n/a", "null"}
    if name.lower() in generic:
        return None
    return name


def validate_phone(phone: str) -> Optional[str]:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("57") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("3"):
        return f"+57{digits}"
    return None


def validate_email(email: str) -> Optional[str]:
    if not email or "@" not in email:
        return None
    email = email.strip().lower()
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return email
    return None


# =============================================================================
# DYNAMODB UPDATE
# =============================================================================

def update_lead(pk: str, sk: str, changes: Dict[str, str]) -> bool:
    if DRY_RUN:
        fields_str = ", ".join(f"{k}='{v}'" for k, v in changes.items())
        print(f"    [DRY RUN] {pk}: {fields_str}")
        return True

    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    changes["FechaActualizacion"] = now
    changes["FuenteEnriquecimiento"] = "external_web_v1"

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
            if "Throttl" in (result.stderr or ""):
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            print(f"    Update error: {result.stderr[:200]}")
            return False
        except subprocess.TimeoutExpired:
            time.sleep(2 ** attempt)
            continue
    return False


# =============================================================================
# PROGRESS TRACKING
# =============================================================================

def load_progress() -> Dict:
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_pks": [], "last_run": None}


def save_progress(progress: Dict):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# =============================================================================
# TELEGRAM REPORT
# =============================================================================

def send_telegram_report(updated: int, failed: int, skipped: int, examples: List[str]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    msg = f"🔄 *Enriquecimiento Externo CRM*\n"
    msg += f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    msg += f"📊 Resultados:\n"
    msg += f"  ✅ Actualizados: {updated}\n"
    msg += f"  ❌ Fallidos: {failed}\n"
    msg += f"  ⏭️ Saltados: {skipped}\n"
    if DRY_RUN:
        msg += f"\n⚠️ *MODO DRY RUN* — no se aplicaron cambios\n"

    if examples:
        msg += f"\n📝 Ejemplos:\n"
        for ex in examples[:5]:
            msg += f"  • {ex}\n"

    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
    }).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("CRM External Enrichment v1")
    print("=" * 60)
    print(f"MODE: {'DRY RUN' if DRY_RUN else 'APPLYING CHANGES'}")
    print(f"MAX_LEADS_PER_RUN: {MAX_LEADS_PER_RUN}")
    print()

    progress = load_progress()
    processed_pks = set(progress.get("processed_pks", []))

    # 1. Scan leads
    leads = scan_leads_needing_enrichment()
    if not leads:
        print("No leads need enrichment. Exiting.")
        return 0

    # 2. Filter out already processed
    pending = [l for l in leads if l.get("PK", {}).get("S", "") not in processed_pks]
    print(f"Pending (not yet processed): {len(pending)}")

    # 3. Take batch
    batch = pending[:MAX_LEADS_PER_RUN]
    print(f"Processing batch of {len(batch)} leads...\n")

    updated = 0
    failed = 0
    skipped = 0
    examples = []

    for i, item in enumerate(batch, 1):
        pk = item.get("PK", {}).get("S", "")
        sk = item.get("SK", {}).get("S", "")
        nombre = item.get("NombreComercial", {}).get("S", pk)
        website = item.get("Website", {}).get("S", "")

        print(f"[{i}/{len(batch)}] {nombre}")
        print(f"    URL: {website}")

        # Fetch website
        text, success = fetch_website_text(website)
        if not success:
            print(f"    ❌ Failed to fetch website")
            failed += 1
            processed_pks.add(pk)
            time.sleep(DELAY_SECONDS)
            continue

        print(f"    📰 Text extracted: {len(text)} chars")

        # Extract with LLM
        extracted = extract_data_with_llm(nombre, text, website)
        if not extracted:
            print(f"    ❌ LLM extraction failed")
            failed += 1
            processed_pks.add(pk)
            time.sleep(DELAY_SECONDS)
            continue

        print(f"    🤖 LLM extracted: {json.dumps(extracted, ensure_ascii=False)[:200]}")

        # Validate and build changes
        changes = {}

        nit = validate_nit(extracted.get("nit"))
        if nit:
            changes["NIT"] = nit

        rep = validate_name(extracted.get("representante_legal"))
        if rep:
            changes["RepresentanteLegal"] = rep

        direccion = extracted.get("direccion")
        if direccion and len(str(direccion)) > 10:
            changes["Direccion"] = str(direccion).strip()

        for phone in extracted.get("telefonos_extra", []) or []:
            norm = validate_phone(str(phone))
            if norm:
                current = item.get("Telefono", {}).get("S", "")
                if norm != current:
                    changes["Telefono"] = norm
                    break

        for email in extracted.get("emails_extra", []) or []:
            norm = validate_email(str(email))
            if norm:
                current = item.get("Email", {}).get("S", "")
                if norm != current:
                    changes["Email"] = norm
                    break

        if not changes:
            print(f"    ⏭️ No valid data extracted")
            skipped += 1
            processed_pks.add(pk)
            time.sleep(DELAY_SECONDS)
            continue

        # Update
        success = update_lead(pk, sk, changes)
        if success:
            updated += 1
            changes_str = ", ".join(changes.keys())
            examples.append(f"{nombre}: {changes_str}")
            print(f"    ✅ Updated: {changes_str}")
        else:
            failed += 1
            print(f"    ❌ Update failed")

        processed_pks.add(pk)
        time.sleep(DELAY_SECONDS)

    # Save progress
    progress["processed_pks"] = list(processed_pks)
    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    # Report
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  ✅ Updated: {updated}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏭️ Skipped: {skipped}")
    print(f"  📝 Total processed (all time): {len(processed_pks)}")
    print(f"  ⏳ Remaining: {len(leads) - len(processed_pks)}")
    print("=" * 60)

    send_telegram_report(updated, failed, skipped, examples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
