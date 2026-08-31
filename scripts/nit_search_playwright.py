#!/usr/bin/env python3
"""
CRM NIT Enrichment via Playwright + DuckDuckGo + informacolombia.com
=====================================================================
Usa Playwright para navegar DuckDuckGo, encontrar perfiles de informacolombia.com,
y extraer NIT del HTML plano.

DRY_RUN por defecto.
"""
import subprocess
import json
import re
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List

# Playwright
sys.path.insert(0, "/home/ubuntu/.hermes/hermes-agent/.venv/lib/python3.10/site-packages")
from playwright.sync_api import sync_playwright

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
MAX_LEADS = int(os.environ.get("MAX_LEADS", "10"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

PROGRESS_FILE = os.path.expanduser("~/.hermes/cron/nit_playwright_progress.json")


def run_aws_cmd(cmd: List[str]) -> Optional[Dict]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)
    except Exception as e:
        print(f"AWS error: {e}")
        return None


def scan_leads() -> List[Dict]:
    items = []
    start_key = None
    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE_NAME,
            "--region", REGION,
            "--projection-expression",
            "PK, SK, NombreComercial, Ciudad, NIT, RepresentanteLegal, Telefono, Email, Score, Estado",
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
            if score >= 4 and estado == "nuevo" and not nit and not rep and nombre:
                items.append(item)
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break
    print(f"  {len(items)} leads need NIT/RepLegal enrichment")
    return items


def search_informacolombia(nombre: str, ciudad: str) -> Optional[Dict]:
    """Use Playwright to search DuckDuckGo and find informacolombia profile."""
    query = f"{nombre} informacolombia.com"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-CO",
        )
        page = context.new_page()
        
        try:
            # Search DuckDuckGo
            page.goto(f"https://duckduckgo.com/?q={query.replace(' ', '+')}", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            
            # Find informacolombia links
            links = page.query_selector_all('a[href*="informacolombia.com"]')
            target_url = None
            for link in links:
                href = link.get_attribute("href") or ""
                if "/informacion-empresa/" in href:
                    target_url = href
                    break
            
            if not target_url:
                browser.close()
                return None
            
            print(f"    Found: {target_url}")
            
            # Visit informacolombia page
            page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            
            # Extract NIT from JSON-LD
            result = {"url": target_url}
            jsonld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
            if jsonld_match:
                try:
                    data = json.loads(jsonld_match.group(1))
                    result["nit"] = data.get("taxID", "")
                    result["telefono"] = data.get("telephone", "")
                    addr = data.get("address", {})
                    result["direccion"] = f"{addr.get('streetAddress', '')}, {addr.get('addressLocality', '')}".strip(", ")
                except json.JSONDecodeError:
                    pass
            
            # Fallback: extract from HTML table
            if not result.get("nit"):
                nit_match = re.search(r'<h3>NIT</h3>[^>]*>([^<]+)</td>', html)
                if nit_match:
                    result["nit"] = nit_match.group(1).strip()
            
            return result if result.get("nit") else None
            
        except Exception as e:
            print(f"    Browser error: {e}")
            browser.close()
            return None


def update_lead(pk: str, sk: str, changes: Dict[str, str]) -> bool:
    if DRY_RUN:
        fields_str = ", ".join(f"{k}='{v}'" for k, v in changes.items())
        print(f"    [DRY RUN] {pk}: {fields_str}")
        return True

    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    changes["FechaActualizacion"] = now
    changes["FuenteEnriquecimiento"] = "playwright_informacolombia_v1"

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
        "--table-name", TABLE_NAME, "--region", REGION,
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
                time.sleep(2 ** attempt)
                continue
            return False
        except subprocess.TimeoutExpired:
            time.sleep(2 ** attempt)
    return False


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


def main():
    print("=" * 60)
    print("NIT Enrichment via Playwright + informacolombia.com")
    print("=" * 60)
    print(f"MODE: {'DRY RUN' if DRY_RUN else 'REAL'}")
    print(f"MAX_LEADS: {MAX_LEADS}")
    print()

    progress = load_progress()
    processed = set(progress.get("processed_pks", []))

    leads = scan_leads()
    pending = [l for l in leads if l.get("PK", {}).get("S", "") not in processed]
    print(f"Pending: {len(pending)}")

    batch = pending[:MAX_LEADS]
    print(f"Processing batch of {len(batch)}...\n")

    updated = failed = skipped = 0
    examples = []

    for i, item in enumerate(batch, 1):
        pk = item.get("PK", {}).get("S", "")
        sk = item.get("SK", {}).get("S", "")
        nombre = item.get("NombreComercial", {}).get("S", pk)
        ciudad = item.get("Ciudad", {}).get("S", "")

        print(f"[{i}/{len(batch)}] {nombre}")
        result = search_informacolombia(nombre, ciudad)
        
        if not result:
            print(f"    ❌ No informacolombia profile found")
            failed += 1
            processed.add(pk)
            continue

        changes = {}
        if result.get("nit"):
            changes["NIT"] = result["nit"]
        if result.get("direccion"):
            changes["Direccion"] = result["direccion"]
        if result.get("telefono"):
            changes["Telefono"] = result["telefono"]

        if not changes:
            print(f"    ⏭️ No useful data")
            skipped += 1
            processed.add(pk)
            continue

        success = update_lead(pk, sk, changes)
        if success:
            updated += 1
            changes_str = ", ".join(changes.keys())
            examples.append(f"{nombre}: NIT={result.get('nit', 'N/A')}")
            print(f"    ✅ Updated: {changes_str}")
        else:
            failed += 1
            print(f"    ❌ Update failed")

        processed.add(pk)

    progress["processed_pks"] = list(processed)
    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    print("\n" + "=" * 60)
    print(f"  ✅ Updated: {updated}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏭️ Skipped: {skipped}")
    print(f"  📝 Total processed: {len(processed)}")
    print(f"  ⏳ Remaining: {len(leads) - len(processed)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
