#!/usr/bin/env python3
"""
NIT Search Enrichment — v1
============================
Busca NIT y RepLegal via web search para leads sin estos datos.
Fuentes: informacolombia.com, empresas.larepublica.co, einforma.co

Targets: leads con Score >= 4, sin NIT, con NombreComercial.
Rate-limited: 1 lead cada 10 segundos.
DRY_RUN por defecto.

Runs via Hermes cron (suggested: Tue/Thu/Sat 11:00 UTC).
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
from typing import Optional, Dict, List, Tuple

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
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
MAX_LEADS_PER_RUN = int(os.environ.get("MAX_LEADS", "15"))
DELAY_SECONDS = 10

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

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
            "PK, SK, NombreComercial, Website, Ciudad, Vertical, Telefono, Email, NIT, RepresentanteLegal",
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
            nombre = item.get("NombreComercial", {}).get("S", "")

            if score >= 4 and estado == "nuevo" and not nit and nombre:
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

def search_duckduckgo(query: str) -> List[Tuple[str, str]]:
    """Search DuckDuckGo HTML, return [(url, title), ...]"""
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        results = re.findall(
            r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>',
            html,
        )
        return results[:8]
    except Exception as e:
        print(f"    Search error: {e}")
        return []


def fetch_url_text(url: str) -> Tuple[str, bool]:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Accept": "text/html",
                "Accept-Language": "es-CO,es;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:15000], True
    except Exception as e:
        print(f"    Fetch error: {e}")
        return "", False


# =============================================================================
# EXTRACTORS
# =============================================================================

def extract_nit_from_text(text: str, company_name: str) -> Optional[str]:
    """Extract NIT from page text. Multiple strategies."""
    if not text:
        return None

    text_upper = text.upper()

    # Strategy 1: explicit NIT label
    patterns = [
        r'NIT[:\s]*([\d\.\-]{9,12})',
        r'N\.I\.T\.[:\s]*([\d\.\-]{9,12})',
        r'NIT[\s]*([\d]{9,10})(?:[-\s]*(\d))?',
        r'taxID["\']*\s*:\s*["\']*([\d]{9,10})',
        r'"NIT"\s*[,\:]\s*"([^"]{9,12})"',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text_upper, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            nit = re.sub(r"[^\d]", "", match)
            if len(nit) >= 9:
                # Validate: Colombian NIT is 9-10 digits
                return nit

    # Strategy 2: JSON-LD schema
    jsonld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.DOTALL)
    for jtxt in jsonld_matches:
        try:
            jdata = json.loads(jtxt)
            taxid = jdata.get("taxID") or jdata.get("identifier", {}).get("value")
            if taxid and re.match(r"^\d{9,10}$", str(taxid)):
                return str(taxid)
        except Exception:
            pass

    return None


def extract_nit_informacolombia(text: str) -> Optional[str]:
    """informacolombia.com specific extraction."""
    # They have: <tr><th><h3>NIT</h3></th><td>9006395341</td></tr>
    match = re.search(r'<h3>\s*NIT\s*</h3>\s*</th>\s*<td[^>]*>\s*([\d\.\-]+)\s*</td>', text, re.IGNORECASE)
    if match:
        nit = re.sub(r"[^\d]", "", match.group(1))
        if len(nit) >= 9:
            return nit
    return None


def extract_nit_larepublica(text: str) -> Optional[str]:
    """empresas.larepublica.co specific extraction (JSON-LD)."""
    return extract_nit_from_text(text, "")


def extract_nit_einforma(text: str) -> Optional[str]:
    """einforma.co specific extraction."""
    # eInforma has NIT in various places
    match = re.search(r'NIT\s*[:\s]*([\d\.\-]{9,12})', text, re.IGNORECASE)
    if match:
        nit = re.sub(r"[^\d]", "", match.group(1))
        if len(nit) >= 9:
            return nit
    return None


def extract_representante_from_text(text: str) -> Optional[str]:
    """Try to extract representative legal name from page text."""
    if not text:
        return None

    # Common patterns
    patterns = [
        r'[Rr]epresentante\s+[Ll]egal[:\s]*([^\n<]{10,60})',
        r'[Rr]ep\.?\s*[Ll]egal[:\s]*([^\n<]{10,60})',
        r'[Dd]irigida\s+por[:\s]*([^\n<]{10,60})',
        r'[Ff]undador[:\s]*([^\n<]{10,60})',
        r'[Cc][Ee][Oo][:\s]*([^\n<]{10,60})',
        r'[Gg]erente\s+[Gg]eneral[:\s]*([^\n<]{10,60})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            # Clean up: stop at common delimiters
            name = re.split(r'[,;\|•\-\(\)\n]', name)[0].strip()
            # Must look like a name (at least 2 words, mostly letters)
            if len(name.split()) >= 2 and all(p.isalpha() or p in '.- ' for p in name):
                if len(name) > 8:
                    return name

    return None


# =============================================================================
# UPDATE
# =============================================================================

def update_lead(pk: str, sk: str, changes: Dict[str, str]) -> bool:
    if DRY_RUN:
        fields_str = ", ".join(f"{k}='{v}'" for k, v in changes.items())
        print(f"    [DRY RUN] {pk}: {fields_str}")
        return True

    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    changes["FechaActualizacion"] = now
    changes["FuenteEnriquecimiento"] = "nit_search_v1"

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

def send_telegram_report(updated: int, failed: int, skipped: int, examples: List[str]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    msg = f"🔍 *NIT Search Enrichment*\n"
    msg += f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    msg += f"📊 Resultados:\n"
    msg += f"  ✅ NIT encontrado: {updated}\n"
    msg += f"  ❌ Fallidos: {failed}\n"
    msg += f"  ⏭️ Sin datos: {skipped}\n"
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
    print("NIT Search Enrichment v1")
    print("=" * 60)
    print(f"MODE: {'DRY RUN' if DRY_RUN else 'APPLYING CHANGES'}")
    print(f"MAX_LEADS_PER_RUN: {MAX_LEADS_PER_RUN}")
    print()

    progress = load_progress()
    processed_pks = set(progress.get("processed_pks", []))

    leads = scan_leads_no_nit()
    if not leads:
        print("No leads need NIT enrichment.")
        return 0

    pending = [l for l in leads if l.get("PK", {}).get("S", "") not in processed_pks]
    print(f"Pending: {len(pending)}")

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

        # Build search queries
        queries = [
            f'"{nombre}" NIT Colombia',
            f'"{nombre}" empresa Colombia NIT',
        ]
        if website:
            domain = re.sub(r"^https?://", "", website).split("/")[0]
            queries.append(f'"{domain}" NIT Colombia')

        found_nit = None
        found_rep = None
        search_success = False

        for query in queries:
            if found_nit:
                break
            print(f"    🔍 Query: {query[:60]}...")
            results = search_duckduckgo(query)
            if not results:
                continue

            for url, title in results:
                if found_nit:
                    break

                # Skip social media, maps, etc.
                skip_domains = ["facebook.com", "instagram.com", "linkedin.com", "maps.google", "youtube.com"]
                if any(d in url.lower() for d in skip_domains):
                    continue

                print(f"      📄 {url[:70]}...")
                text, success = fetch_url_text(url)
                if not success:
                    continue

                # Try source-specific extractors
                if "informacolombia.com" in url:
                    found_nit = extract_nit_informacolombia(text)
                elif "larepublica.co" in url:
                    found_nit = extract_nit_larepublica(text)
                elif "einforma" in url:
                    found_nit = extract_nit_einforma(text)
                else:
                    found_nit = extract_nit_from_text(text, nombre)

                if found_nit and not found_rep:
                    found_rep = extract_representante_from_text(text)

                if found_nit:
                    search_success = True
                    print(f"      ✅ NIT: {found_nit}")
                    if found_rep:
                        print(f"      ✅ RepLegal: {found_rep}")

        if not found_nit:
            print(f"    ❌ No NIT found")
            skipped += 1
            processed_pks.add(pk)
            time.sleep(DELAY_SECONDS)
            continue

        # Build changes
        changes = {"NIT": found_nit}
        if found_rep:
            changes["RepresentanteLegal"] = found_rep

        success = update_lead(pk, sk, changes)
        if success:
            updated += 1
            rep_str = f" + RepLegal" if found_rep else ""
            examples.append(f"{nombre}: NIT {found_nit}{rep_str}")
            print(f"    ✅ Updated")
        else:
            failed += 1
            print(f"    ❌ Update failed")

        processed_pks.add(pk)
        time.sleep(DELAY_SECONDS)

    # Save progress
    progress["processed_pks"] = list(processed_pks)
    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  ✅ Updated: {updated}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏭️ Skipped: {skipped}")
    print(f"  📝 Total processed: {len(processed_pks)}")
    print(f"  ⏳ Remaining: {len(leads) - len(processed_pks)}")
    print("=" * 60)

    send_telegram_report(updated, failed, skipped, examples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
