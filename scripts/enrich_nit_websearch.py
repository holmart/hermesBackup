#!/usr/bin/env python3
"""
NIT Enrichment via Web Search
Busca "Empresa NIT Colombia" en DuckDuckGo y extrae NIT de los resultados.
Actualiza DynamoDB directamente.
"""
import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TABLE_NAME = "sifagent-crm-clients"
REGION = "us-east-1"
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
MAX_LEADS = int(os.environ.get("MAX_LEADS", "20"))
DELAY = 3  # segundos entre búsquedas


def scan_leads_without_nit():
    items = []
    start_key = None
    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE_NAME,
            "--region", REGION,
            "--filter-expression", "attribute_not_exists(NIT) OR NIT = :empty",
            "--expression-attribute-values", json.dumps({":empty": {"S": ""}}),
            "--projection-expression", "PK, SK, NombreComercial, Ciudad, Vertical",
        ]
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"AWS error: {result.stderr[:200]}")
            break
        data = json.loads(result.stdout)
        items.extend(data.get("Items", []))
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break
    return items


def search_nit(company_name, city=""):
    """Search DuckDuckGo for company NIT."""
    query = f"{company_name} NIT Colombia"
    if city:
        query += f" {city}"
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "es-CO,es;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    Search error: {e}")
        return None

    # Extract NIT patterns from results
    # Common patterns in snippets: 900123456, 900.123.456-1, 1234567890
    nits = set()

    # Pattern 1: NIT followed by number
    for match in re.finditer(r"NIT[:\s]*([\d\.\-]{9,12})", html, re.IGNORECASE):
        nits.add(clean_nit(match.group(1)))

    # Pattern 2: taxID in JSON-LD
    for match in re.finditer(r"taxID["\']*\s*[:"]\s*["\'](\d{9,11})["\']", html):
        nits.add(match.group(1))

    # Pattern 3: standalone 9-11 digit numbers (Colombian NIT length)
    for match in re.finditer(r"[^\d](\d{9,10})[^\d]", html):
        n = match.group(1)
        if n.startswith("8") or n.startswith("9") or len(n) == 10:
            nits.add(n)

    # Validate NITs
    valid_nits = [n for n in nits if validate_nit(n)]
    if valid_nits:
        # Return the most common or first one
        return valid_nits[0]
    return None


def clean_nit(raw):
    """Remove dots and dashes from NIT."""
    return re.sub(r"[^\d]", "", raw)


def validate_nit(nit):
    """Basic Colombian NIT validation."""
    if not nit or len(nit) < 9:
        return False
    # NITs typically start with 8 or 9 for companies, or 10 digits for individuals
    if not re.match(r"^\d{9,10}$", nit):
        return False
    return True


def update_nit(pk, sk, nit):
    if DRY_RUN:
        print(f"    [DRY RUN] Update NIT={nit} for {pk}")
        return True
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    key = {"PK": {"S": pk}, "SK": {"S": sk}}
    cmd = [
        "aws", "dynamodb", "update-item",
        "--table-name", TABLE_NAME,
        "--region", REGION,
        "--key", json.dumps(key),
        "--update-expression", "SET NIT = :nit, FechaActualizacion = :now, FuenteEnriquecimiento = :src",
        "--expression-attribute-values", json.dumps({
            ":nit": {"S": nit},
            ":now": {"S": now},
            ":src": {"S": "websearch_nit_v1"},
        }),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return True
    print(f"    Update error: {result.stderr[:200]}")
    return False


def main():
    print("=" * 60)
    print("NIT Enrichment via Web Search")
    print(f"MODE: {'DRY RUN' if DRY_RUN else 'APPLY'}")
    print("=" * 60)

    leads = scan_leads_without_nit()
    print(f"Leads without NIT: {len(leads)}")

    # Prioritize by score (need to fetch full items for score)
    # For now just take first MAX_LEADS
    batch = leads[:MAX_LEADS]

    found = 0
    failed = 0
    not_found = 0

    for i, item in enumerate(batch, 1):
        pk = item.get("PK", {}).get("S", "")
        sk = item.get("SK", {}).get("S", "")
        nombre = item.get("NombreComercial", {}).get("S", pk)
        ciudad = item.get("Ciudad", {}).get("S", "")

        print(f"\n[{i}/{len(batch)}] {nombre}")
        nit = search_nit(nombre, ciudad)

        if nit:
            print(f"    ✅ Found NIT: {nit}")
            if update_nit(pk, sk, nit):
                found += 1
            else:
                failed += 1
        else:
            print(f"    ❌ NIT not found")
            not_found += 1

        time.sleep(DELAY)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  ✅ Found & updated: {found}")
    print(f"  ❌ Update failed: {failed}")
    print(f"  ⚠️ Not found: {not_found}")
    print(f"  ⏳ Remaining without NIT: {len(leads) - found}")


if __name__ == "__main__":
    main()
