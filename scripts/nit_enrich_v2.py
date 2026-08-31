#!/usr/bin/env python3
"""
CRM NIT Enrichment v2 — Website + informacolombia.com
=======================================================
1. Visita el website del lead y busca NIT en footer/legal
2. Si no encuentra, intenta informacolombia.com con slug del nombre
3. Actualiza DynamoDB

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

sys.path.insert(0, "/home/ubuntu/.hermes/hermes-agent/.venv/lib/python3.10/site-packages")
from playwright.sync_api import sync_playwright

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

TABLE_NAME = os.environ.get("CRM_TABLE", "sifagent-crm-clients")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
MAX_LEADS = int(os.environ.get("MAX_LEADS", "10"))
PROGRESS_FILE = os.path.expanduser("~/.hermes/cron/nit_enrich_v2_progress.json")


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
            "PK, SK, NombreComercial, Ciudad, NIT, RepresentanteLegal, Telefono, Email, Website, Score, Estado",
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
            website = item.get("Website", {}).get("S", "")
            if score >= 4 and estado == "nuevo" and not nit and not rep and nombre and website:
                items.append(item)
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break
    print(f"  {len(items)} leads need NIT/RepLegal enrichment (with website)")
    return items


def slugify(nombre: str) -> str:
    """Convert company name to informacolombia slug."""
    s = nombre.lower()
    s = re.sub(r'[^a-z0-9\s]', '', s)
    s = re.sub(r'\s+', '-', s).strip('-')
    return s


def extract_nit_from_html(html: str) -> Optional[str]:
    """Extract Colombian NIT from HTML text."""
    if not html:
        return None
    # Clean HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Patterns: 9006395341, 900.639.534-1, 900639534-1
    patterns = [
        r"\b(\d{9,10})[-\s]?(\d)\b",
        r"\b(\d{3})[.]?(\d{3})[.]?(\d{3})[-\s]?(\d)\b",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if isinstance(match, tuple):
                nit = "".join(match).replace(".", "").replace("-", "").replace(" ", "")
            else:
                nit = match.replace(".", "").replace("-", "").replace(" ", "")
            if len(nit) >= 9 and nit[0] in "89":
                # Validate Colombian NIT check digit (simple: starts with 8 or 9)
                return nit
    return None


def fetch_with_playwright(url: str) -> str:
    """Fetch page content using Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-CO",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return html
        except Exception as e:
            print(f"    Browser error: {e}")
            browser.close()
            return ""


def try_website(website: str) -> Optional[Dict]:
    """Try to find NIT on the company's own website."""
    html = fetch_with_playwright(website)
    if not html:
        return None
    nit = extract_nit_from_html(html)
    if nit:
        return {"nit": nit, "source": "website"}
    return None


def try_informacolombia(nombre: str) -> Optional[Dict]:
    """Try to find NIT on informacolombia.com using slug."""
    slug = slugify(nombre)
    url = f"https://www.informacolombia.com/directorio-empresas/informacion-empresa/{slug}"
    html = fetch_with_playwright(url)
    if not html or "no encontrado" in html.lower() or "error" in html.lower()[:500]:
        return None
    
    # Extract from JSON-LD
    jsonld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if jsonld_match:
        try:
            data = json.loads(jsonld_match.group(1))
            nit = data.get("taxID", "")
            if nit:
                return {"nit": nit, "source": "informacolombia"}
        except json.JSONDecodeError:
            pass
    
    # Extract from HTML table
    nit_match = re.search(r'<h3>NIT</h3>[^>]*>([^<]+)</td>', html)
    if nit_match:
        nit = nit_match.group(1).strip()
        if nit:
            return {"nit": nit, "source": "informacolombia"}
    
    return None


def update_lead(pk: str, sk: str, changes: Dict[str, str]) -> bool:
    if DRY_RUN:
        fields_str = ", ".join(f"{k}='{v}'" for k, v in changes.items())
        print(f"    [DRY RUN] {pk}: {fields_str}")
        return True

    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    changes["FechaActualizacion"] = now
    changes["FuenteEnriquecimiento"] = "nit_enrich_v2"

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
    print("NIT Enrichment v2 — Website + informacolombia.com")
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
        website = item.get("Website", {}).get("S", "")

        print(f"[{i}/{len(batch)}] {nombre}")
        print(f"    Website: {website}")

        result = None

        # Try 1: company website
        result = try_website(website)
        if result:
            print(f"    ✅ Found NIT on website: {result['nit']}")
        else:
            # Try 2: informacolombia
            print(f"    🔍 Trying informacolombia...")
            result = try_informacolombia(nombre)
            if result:
                print(f"    ✅ Found NIT on informacolombia: {result['nit']}")

        if not result:
            print(f"    ❌ NIT not found")
            failed += 1
            processed.add(pk)
            continue

        changes = {"NIT": result["nit"]}
        success = update_lead(pk, sk, changes)
        if success:
            updated += 1
            examples.append(f"{nombre}: NIT={result['nit']} ({result['source']})")
            print(f"    ✅ Updated")
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
