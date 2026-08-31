#!/usr/bin/env python3
"""
CRM NIT + RepLegal Enrichment via Web Search
==============================================
Busca NIT y Representante Legal de empresas colombianas
usando web search (DuckDuckGo) + parsing de snippets.

Fuentes objetivo:
- informacolombia.com (NIT en HTML, no anti-bot)
- empresas.larepublica.co (JSON-LD con taxID)
- datacreditoempresas.com.co (snippet con NIT)
- eInforma.co (requiere más trabajo)
- lasempresas.com.co (a veces tiene RepLegal)

Targets: leads score >= 4, sin NIT, con NombreComercial.
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
import urllib.error
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
MAX_LEADS = int(os.environ.get("MAX_LEADS", "15"))
DELAY = 5  # seconds between searches

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
        print(f"  AWS error: {e}")
        return None


def scan_targets() -> List[Dict]:
    """Leads score>=4, nuevo, sin NIT, con nombre comercial."""
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
            estado = item.get("Estado", {}).get("S", "nuevo")
            nit = item.get("NIT", {}).get("S", "")
            nombre = item.get("NombreComercial", {}).get("S", "")
            if score >= 4 and estado == "nuevo" and not nit and nombre and len(nombre) > 2:
                items.append(item)
        page += 1
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break
    print(f"  Scanned {page} page(s), {len(items)} targets need NIT")
    return items


# =============================================================================
# WEB SEARCH
# =============================================================================

def web_search(query: str) -> List[Tuple[str, str]]:
    """Search DuckDuckGo HTML, return [(title, snippet/url)]."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html",
            "Accept-Language": "es-CO,es;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    Search error: {e}")
        return []

    results = []
    # Extract result blocks
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>'
        r'.*?<a class="result__snippet"[^>]*>([^<]+)</a>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for link, title, snippet in blocks[:8]:
        # Clean snippet HTML entities
        snippet = re.sub(r"<[^>]+>", "", snippet)
        snippet = snippet.replace("&nbsp;", " ").replace("&quot;", '"').strip()
        results.append((title, snippet, link))
    return results


def fetch_informacolombia_nit(url: str) -> Optional[str]:
    """informacolombia.com shows NIT in plain HTML table."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html",
            "Accept-Language": "es-CO,es;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    # Look for NIT in HTML
    m = re.search(r'NIT</h3></th><td>[^<]*<[^>]*>(\d{9,10}(-\d)?)</a>', html, re.IGNORECASE)
    if m:
        return m.group(1)
    # Alternative pattern
    m = re.search(r'taxID["\']?\s*:\s*["\'](\d{9,10})["\']', html)
    if m:
        return m.group(1)
    return None


def fetch_larepublica_data(url: str) -> Dict[str, str]:
    """empresas.larepublica.co has JSON-LD with taxID."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return {}

    out = {}
    # JSON-LD
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            ld = json.loads(m.group(1))
            if "taxID" in ld:
                out["NIT"] = str(ld["taxID"])
            if "telephone" in ld:
                out["Telefono"] = str(ld["telephone"])
            if "address" in ld and isinstance(ld["address"], dict):
                addr = ld["address"]
                parts = [addr.get("streetAddress", ""), addr.get("addressLocality", ""), addr.get("addressRegion", "")]
                out["Direccion"] = ", ".join(p for p in parts if p)
        except Exception:
            pass

    return out


def extract_nit_from_snippets(results: List[Tuple[str, str, str]]) -> Optional[str]:
    """Try to extract NIT from search result snippets."""
    for title, snippet, url in results:
        # informacolombia URL with NIT
        if "informacolombia.com" in url:
            nit = fetch_informacolombia_nit(url)
            if nit:
                return nit
        # larepublica JSON-LD
        if "empresas.larepublica.co" in url:
            data = fetch_larepublica_data(url)
            if data.get("NIT"):
                return data["NIT"]
        # Direct NIT in snippet
        m = re.search(r'\b(\d{9,10}(-\d)?)\b', snippet)
        if m and len(m.group(1)) >= 9:
            return m.group(1)
    return None


def search_representante_legal(nit: str, nombre: str) -> Optional[str]:
    """Search for representative legal using NIT or company name."""
    query = f'"{nit}" representante legal Colombia'
    results = web_search(query)

    for title, snippet, url in results:
        # lasempresas.com sometimes has RepLegal
        if "lasempresas.com.co" in url:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                # Look for person-like names near "representante"
                m = re.search(r'[Rr]epresentante[^<>]*[Ll]egal[^<>]*<[^>]*>([^<]{10,60})</', html)
                if m:
                    candidate = m.group(1).strip()
                    if len(candidate.split()) >= 2:
                        return candidate
            except Exception:
                pass

        # Snippet extraction
        # Pattern: "Representante Legal: Juan Carlos Gomez"
        m = re.search(r'[Rr]epresentante\s+[Ll]egal[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})', snippet)
        if m:
            return m.group(1).strip()

    return None


# =============================================================================
# VALIDATION
# =============================================================================

def validate_nit(nit: Optional[str]) -> Optional[str]:
    if not nit:
        return None
    nit = str(nit).strip().replace(".", "").replace(",", "")
    if re.match(r"^\d{9,10}(-\d)?$", nit):
        return nit
    return None


def validate_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    name = str(name).strip()
    if len(name) < 5 or len(name) > 60:
        return None
    parts = name.split()
    if len(parts) < 2:
        return None
    generic = {"representante", "legal", "gerente", "director", "administrador", "contacto", "servicio", "n/a", "null"}
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
    changes["FuenteEnriquecimiento"] = "nit_web_search_v1"

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
    msg = f"🔍 *NIT Enrichment Report*\n"
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
    print("CRM NIT + RepLegal Enrichment via Web Search")
    print("=" * 60)
    print(f"MODE: {'DRY RUN' if DRY_RUN else 'REAL'}")
    print(f"MAX_LEADS: {MAX_LEADS}")
    print()

    progress = load_progress()
    processed = set(progress.get("processed_pks", []))

    # 1. Scan targets
    targets = scan_targets()
    pending = [t for t in targets if t.get("PK", {}).get("S", "") not in processed]
    print(f"Pending: {len(pending)}")

    batch = pending[:MAX_LEADS]
    print(f"Processing batch: {len(batch)}\n")

    updated = 0
    failed = 0
    skipped = 0
    examples = []

    for i, item in enumerate(batch, 1):
        pk = item.get("PK", {}).get("S", "")
        sk = item.get("SK", {}).get("S", "")
        nombre = item.get("NombreComercial", {}).get("S", pk)

        print(f"[{i}/{len(batch)}] {nombre}")

        # Search 1: NIT
        query = f'"{nombre}" NIT Colombia'
        print(f"    Search: {query}")
        results = web_search(query)
        if not results:
            print(f"    No search results")
            failed += 1
            processed.add(pk)
            time.sleep(DELAY)
            continue

        nit = extract_nit_from_snippets(results)
        if not nit:
            print(f"    No NIT found in snippets")
            skipped += 1
            processed.add(pk)
            time.sleep(DELAY)
            continue

        nit = validate_nit(nit)
        if not nit:
            print(f"    Invalid NIT format")
            skipped += 1
            processed.add(pk)
            time.sleep(DELAY)
            continue

        print(f"    ✅ NIT found: {nit}")

        # Search 2: RepLegal
        rep = search_representante_legal(nit, nombre)
        if rep:
            rep = validate_name(rep)
            if rep:
                print(f"    ✅ RepLegal: {rep}")
            else:
                print(f"    ⚠️ RepLegal invalid format, skipping")
                rep = None
        else:
            print(f"    ⚠️ RepLegal not found")

        # Build changes
        changes = {"NIT": nit}
        if rep:
            changes["RepresentanteLegal"] = rep

        # Update
        success = update_lead(pk, sk, changes)
        if success:
            updated += 1
            example = f"{nombre}: NIT {nit}"
            if rep:
                example += f", RepLegal {rep}"
            examples.append(example)
            print(f"    ✅ Updated")
        else:
            failed += 1
            print(f"    ❌ Update failed")

        processed.add(pk)
        time.sleep(DELAY)

    # Save progress
    progress["processed_pks"] = list(processed)
    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    # Report
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  ✅ Updated: {updated}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏭️ Skipped: {skipped}")
    print(f"  📝 Total processed: {len(processed)}")
    print(f"  ⏳ Remaining: {len(targets) - len(processed)}")
    print("=" * 60)

    send_report(updated, failed, skipped, examples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
