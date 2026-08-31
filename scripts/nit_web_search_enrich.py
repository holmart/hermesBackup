#!/usr/bin/env python3
"""
NIT Web Search Enrichment — Fase 1
====================================
Busca NIT y Representante Legal de empresas colombianas via web search.
Fuentes: informacolombia.com, empresas.larepublica.co, datacreditoempresas.com.co

Targets: leads con Score >= 4, sin NIT, con NombreComercial.
Rate-limited: 1 lead cada 5 segundos para no ser bloqueado.
DRY_RUN por defecto.
"""
import subprocess
import json
import re
import os
import sys
import time
import random
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, List

# =============================================================================
# LOAD ENV
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
# CONFIG
# =============================================================================
TABLE_NAME = os.environ.get("CRM_TABLE", "sifagent-crm-clients")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
MAX_LEADS_PER_RUN = int(os.environ.get("MAX_LEADS", "15"))
DELAY_SECONDS = 5

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

# Progress
PROGRESS_FILE = os.path.expanduser("~/.hermes/cron/nit_enrich_progress.json")


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


def scan_leads_no_nit() -> List[Dict]:
    items = []
    start_key = None
    page = 0
    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE_NAME,
            "--region", REGION,
            "--projection-expression",
            "PK, SK, NombreComercial, Website, Vertical, Ciudad, Telefono, Email",
        ]
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])
        data = run_aws_cmd(cmd)
        if not data:
            break
        for item in data.get("Items", []):
            score = int(item.get("Score", {}).get("N", "0"))
            nit = item.get("NIT", {}).get("S", "")
            nombre = item.get("NombreComercial", {}).get("S", "")
            if score >= 4 and not nit and nombre:
                items.append(item)
        page += 1
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break
    print(f"  Scanned {page} page(s), {len(items)} leads need NIT")
    return items


# =============================================================================
# WEB SEARCH
# =============================================================================

def duckduckgo_search(query: str) -> str:
    """Search DuckDuckGo HTML version and return raw HTML."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": random.choice([
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ])
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    Search error: {e}")
        return ""


def extract_nit_from_search(html: str, company_name: str) -> Optional[str]:
    """Extract NIT from DuckDuckGo search results HTML."""
    if not html:
        return None

    # Pattern 1: informacolombia.com NIT in snippet
    # Example: "NIT</h3></th><td>9006395341</a>"
    m = re.search(r'NIT\s*</h?\w+>\s*</th>\s*<td[^>]*>\s*<a[^>]*>(\d{9,10})</a>', html, re.IGNORECASE)
    if m:
        return m.group(1)

    # Pattern 2: JSON-LD taxID from larepublica.co
    # {"taxID":"9006395341"}
    m = re.search(r'"taxID"\s*:\s*"(\d{9,10})"', html)
    if m:
        return m.group(1)

    # Pattern 3: NIT mentioned in result snippets
    # "NIT: 901.356.422-1" or "NIT 900123456"
    patterns = [
        r'NIT[\s:]*([\d\.]{10,14}-?\d?)',
        r'N\.I\.T\.\s*[:\s]*([\d\.]{10,14}-?\d?)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            nit = m.group(1).replace(".", "").replace("-", "").strip()
            if re.match(r'^\d{9,10}$', nit):
                return nit

    # Pattern 4: informacolombia inline NIT
    m = re.search(r'data-norm="[^"]*"[^>]*>\s*(\d{9,10})\s*</a>', html)
    if m:
        return m.group(1)

    return None


def extract_replegal_from_search(html: str) -> Optional[str]:
    """Try to extract RepLegal from search snippets (low success rate)."""
    if not html:
        return None
    # Look for "Representante Legal: Nombre Apellido" in snippets
    m = re.search(r'Representante\s+Legal[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})', html)
    if m:
        name = m.group(1).strip()
        if len(name) > 5 and ' ' in name:
            return name
    return None


def fetch_informacolombia_detail(url: str) -> Dict[str, Optional[str]]:
    """Fetch informacolombia detail page and extract NIT + RepLegal."""
    result = {"nit": None, "replegal": None}
    if not url or "informacolombia.com" not in url:
        return result
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # NIT
        m = re.search(r'<h3>NIT</h3>\s*</th>\s*<td[^>]*>\s*<a[^>]*>(\d{9,10})</a>', html, re.IGNORECASE)
        if m:
            result["nit"] = m.group(1)

        # RepLegal
        m = re.search(r'Representante\s+Legal</h3>\s*</th>\s*<td[^>]*>([^<]+)</td>', html, re.IGNORECASE | re.DOTALL)
        if m:
            name = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if len(name) > 5 and ' ' in name:
                result["replegal"] = name

    except Exception as e:
        print(f"    Detail fetch error: {e}")
    return result


def search_company(company_name: str) -> Dict[str, Optional[str]]:
    """Search for company and return extracted data."""
    result = {"nit": None, "replegal": None, "source": None}

    # Query 1: Company + NIT Colombia
    query = f'"{company_name}" NIT Colombia'
    html = duckduckgo_search(query)

    # Try extract NIT from search results
    nit = extract_nit_from_search(html, company_name)
    if nit:
        result["nit"] = nit
        result["source"] = "duckduckgo_snippet"

    # Try extract RepLegal
    rep = extract_replegal_from_search(html)
    if rep:
        result["replegal"] = rep

    # If no NIT, try fetch informacolombia detail page from results
    if not result["nit"]:
        # Find informacolombia result URLs
        urls = re.findall(r'href="(https://www\.informacolombia\.com/[^"]+)"', html)
        for url in urls[:2]:
            detail = fetch_informacolombia_detail(url)
            if detail["nit"]:
                result["nit"] = detail["nit"]
                result["source"] = "informacolombia_detail"
            if detail["replegal"] and not result["replegal"]:
                result["replegal"] = detail["replegal"]
            if result["nit"]:
                break

    return result


# =============================================================================
# VALIDATION
# =============================================================================

def validate_nit(nit: Optional[str]) -> Optional[str]:
    if not nit:
        return None
    nit = str(nit).strip().replace(".", "").replace(",", "").replace("-", "")
    if re.match(r'^\d{9,10}$', nit):
        return nit
    return None


def validate_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    name = str(name).strip()
    if len(name) < 5 or ' ' not in name:
        return None
    generic = {"representante legal", "gerente", "director", "administrador", "pendiente", "n/a", "null"}
    if name.lower() in generic:
        return None
    return name


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
    changes["FuenteEnriquecimiento"] = "web_search_nit_v1"

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
            return False
        except subprocess.TimeoutExpired:
            time.sleep(2 ** attempt)
            continue
    return False


# =============================================================================
# PROGRESS
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
# TELEGRAM
# =============================================================================

def send_report(updated: int, failed: int, skipped: int, examples: List[str]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = f"🔍 *NIT Web Search Enrichment*\n"
    msg += f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    msg += f"📊 Resultados:\n"
    msg += f"  ✅ Actualizados: {updated}\n"
    msg += f"  ❌ Fallidos: {failed}\n"
    msg += f"  ⏭️ Saltados: {skipped}\n"
    if DRY_RUN:
        msg += f"\n⚠️ *MODO DRY RUN*\n"
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
    print("NIT Web Search Enrichment v1")
    print("=" * 60)
    print(f"MODE: {'DRY RUN' if DRY_RUN else 'APPLYING'}")
    print(f"MAX_LEADS: {MAX_LEADS_PER_RUN}")
    print()

    progress = load_progress()
    processed_pks = set(progress.get("processed_pks", []))

    leads = scan_leads_no_nit()
    if not leads:
        print("No leads need NIT. Exiting.")
        return 0

    pending = [l for l in leads if l.get("PK", {}).get("S", "") not in processed_pks]
    print(f"Pending: {len(pending)}")

    batch = pending[:MAX_LEADS_PER_RUN]
    print(f"Processing batch of {len(batch)}...\n")

    updated = 0
    failed = 0
    skipped = 0
    examples = []

    for i, item in enumerate(batch, 1):
        pk = item.get("PK", {}).get("S", "")
        sk = item.get("SK", {}).get("S", "")
        nombre = item.get("NombreComercial", {}).get("S", pk)

        print(f"[{i}/{len(batch)}] {nombre}")

        result = search_company(nombre)
        print(f"    🔍 Found: NIT={result['nit']}, RepLegal={result['replegal']}, Source={result['source']}")

        changes = {}
        nit = validate_nit(result.get("nit"))
        if nit:
            changes["NIT"] = nit
        rep = validate_name(result.get("replegal"))
        if rep:
            changes["RepresentanteLegal"] = rep

        if not changes:
            print(f"    ⏭️ No valid data")
            skipped += 1
            processed_pks.add(pk)
            time.sleep(DELAY_SECONDS)
            continue

        success = update_lead(pk, sk, changes)
        if success:
            updated += 1
            fields = ", ".join(changes.keys())
            examples.append(f"{nombre}: {fields} ({result['source']})")
            print(f"    ✅ Updated: {fields}")
        else:
            failed += 1
            print(f"    ❌ Update failed")

        processed_pks.add(pk)
        time.sleep(DELAY_SECONDS)

    progress["processed_pks"] = list(processed_pks)
    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  ✅ Updated: {updated}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏭️ Skipped: {skipped}")
    print(f"  📝 Total processed: {len(processed_pks)}")
    print(f"  ⏳ Remaining: {len(leads) - len(processed_pks)}")
    print("=" * 60)

    send_report(updated, failed, skipped, examples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
