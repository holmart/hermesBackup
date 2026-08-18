#!/usr/bin/env python3
"""
RUES-based enrichment for SIF Agent CRM
Updates RepresentanteLegal using RUES query or internal fields fallback.
"""
import subprocess
import json
import re
import time
import datetime
import sys
import os

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
               'encargado', 'supervisor', 'jefe', 'director', 'presidente']
    if val.lower() in generic:
        return True
    return False

def looks_like_person_name(val):
    """Check if value looks like a person's name (at least two words, each starting with uppercase)"""
    if is_empty_or_generic(val):
        return False
    parts = val.strip().split()
    if len(parts) < 2:
        return False
    for p in parts:
        if not p:
            return False
        # Check if first character is uppercase letter (including accented)
        if not (p[0].isalpha() and p[0].isupper()):
            return False
    return True

def normalize_name(name):
    """Normalize name for comparison: remove accents, uppercase, single spaces"""
    if not name:
        return ""
    # Remove accents
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    # Convert to uppercase and collapse whitespace
    return re.sub(r'\s+', ' ', ascii_name).strip().upper()

def query_rues_for_nit(nit):
    """
    Attempt to query RUES for a given NIT and extract representative legal.
    Returns (success, name, source) where source is 'RUES' or 'internal_fallback'
    """
    if not nit:
        return False, None, 'internal_fallback'
    
    # Clean NIT: keep only digits
    nit_digits = re.sub(r'\D', '', nit)
    if len(nit_digits) < 9:
        return False, None, 'internal_fallback'
    
    url = f"https://www.rues.org.co/consulta-publica?nit={nit_digits}"
    # print(f"  Querying RUES for NIT {nit_digits}...")  # reduce noise
    
    # Try to fetch with retries
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            cmd = [
                'curl', '-s', '-L', '--max-time', '20',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--header', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                # print(f"    Attempt {attempt}: curl failed")
                if attempt < max_attempts:
                    time.sleep(2)
                continue
            html = result.stdout
            
            # Check if we got a challenge page
            if "Unfortunately, bots use DuckDuckGo too" in html or "Please complete the following challenge" in html:
                # print(f"    Attempt {attempt}: received bot challenge")
                if attempt < max_attempts:
                    time.sleep(5)
                continue
            
            # Now try to extract representative legal from HTML
            # We'll look for patterns that might indicate the name
            
            # First, let's see if we can find the NIT in the HTML (as a sanity check)
            if nit_digits not in html:
                # Try with formatting: maybe with hyphen
                nit_formatted = nit_digits[:-1] + '-' + nit_digits[-1] if len(nit_digits) > 1 else nit_digits
                if nit_formatted not in html:
                    # print(f"    Warning: NIT {nit_digits} not found in HTML")
                    # We'll still try to extract names, but lower confidence
                    pass
            
            # Extract potential name sequences: two or more words, each starting with uppercase letter
            # We'll look for patterns that might indicate the name
            
            # Look for the label "Representante Legal" and capture text after it
            label_patterns = [
                r'representante\s*legal\s*[:\-]\s*([^<\n\r]+)',
                r'Representante\s*Legal\s*[:\-]\s*([^<\n\r]+)',
                r'>\s*Representante\s*Legal\s*<[^>]*[:\-]\s*([^<\n\r]+)',
            ]
            for pattern in label_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    name_candidate = match.strip()
                    # Clean up: remove extra spaces, HTML tags, etc.
                    name_candidate = re.sub(r'<[^>]+>', '', name_candidate)
                    name_candidate = re.sub(r'\s+', ' ', name_candidate).strip()
                    if name_candidate and len(name_candidate) > 5:  # reasonable length
                        # Additional check: does it look like a person name?
                        if looks_like_person_name(name_candidate):
                            # print(f"    Found via label: '{name_candidate}'")
                            return True, name_candidate, 'RUES'
            
            # If label approach didn't work, try to find any sequence of two or more words
            # where each word starts with uppercase and has at least two letters
            # We'll split by non-letter characters to get words
            words = re.findall(r'[A-Za-zÁÉÍÓÚÜ�������Ñáéíóúüñ]+', html)
            # Group consecutive words
            i = 0
            while i < len(words) - 1:
                w1 = words[i]
                w2 = words[i+1]
                # Skip if too short or common words
                if len(w1) < 2 or len(w2) < 2:
                    i += 1
                    continue
                # Skip common Spanish words that are not part of names
                lower_w1 = w1.lower()
                lower_w2 = w2.lower()
                if lower_w1 in ['el', 'la', 'los', 'las', 'del', 'de', 'y', 'o', 'u', 'por', 'para', 'con', 'sin', 'sobre']:
                    i += 1
                    continue
                if lower_w2 in ['el', 'la', 'los', 'las', 'del', 'de', 'y', 'o', 'u', 'por', 'para', 'con', 'sin', 'sobre']:
                    i += 1
                    continue
                # Check if both start with uppercase letter
                if w1[0].isupper() and w2[0].isupper():
                    candidate = f"{w1} {w2}"
                    # Additional check: avoid known non-person phrases
                    lower_candidate = candidate.lower()
                    if lower_candidate not in ['registro unico', 'empresarial y social', 'camara de comercio', 'confederacion', 'registro unico empresarial']:
                        # Also check if it looks like a person name (should, but double-check)
                        if looks_like_person_name(candidate):
                            # print(f"    Found via word pair: '{candidate}'")
                            return True, candidate, 'RUES'
                i += 1
            
            # If we didn't find a good name, we'll try to fall back to internal fields later
            # print(f"    No suitable representative legal found in RUES HTML for NIT {nit_digits}")
            # We'll still return False so we can fall back to internal fields
            # But let's also check if we can at least get the company name to verify we're on the right page
            # Look for the company name in the title or header
            # Title pattern: <title>.* - RUES</title> or something
            title_match = re.search(r'<title>[^<]*</title>', html, re.IGNORECASE)
            if title_match:
                title = title_match.group(0)
                # Extract text between <title> and </title>
                title_text = re.sub(r'<[^>]+>', '', title)
                title_text = title_text.strip()
                # print(f"    Page title: {title_text}")
                # If the title contains the expected company name, we have some confidence we're on the right page
                # But we'll still fall back to internal if no RepLegal found
            
            # If we got here, we didn't find a good RepLegal from RUES
            # We'll return False to indicate we should fall back to internal fields
            if attempt < max_attempts:
                # print(f"    Waiting before retry...")
                time.sleep(3)
            continue
            
        except subprocess.TimeoutExpired:
            # print(f"    Attempt {attempt}: timeout")
            if attempt < max_attempts:
                time.sleep(3)
            continue
        except Exception as e:
            # print(f"    Attempt {attempt}: error: {e}")
            if attempt < max_attempts:
                time.sleep(3)
            continue
    
    # If we exhausted all attempts
    # print(f"    Failed to fetch RUES for NIT {nit_digits} after {max_attempts} attempts")
    return False, None, 'internal_fallback'

def update_company_replegal(pk, sk, new_rep, source):
    """Update the company's RepresentanteLegal in DynamoDB"""
    # Check if we're in dry run mode
    dry_run = os.environ.get('DRY_RUN', '').lower() == 'true'
    if dry_run:
        print(f"    [DRY RUN] Would update {pk}: RepresentanteLegal='{new_rep}', FuenteRepLegal='{source}'")
        return True
    
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    key = {"PK": {"S": pk}, "SK": {"S": sk}}
    attrs = {
        ":rep": {"S": new_rep},
        ":source": {"S": source},
        ":date": {"S": now}
    }
    cmd = [
        'aws', 'dynamodb', 'update-item',
        '--table-name', 'sifagent-crm-clients',
        '--region', 'us-east-1',
        '--key', json.dumps(key),
        '--update-expression', 'SET RepresentanteLegal = :rep, FuenteRepLegal = :source, FechaActualizacionRepLegal = :date',
        '--expression-attribute-values', json.dumps(attrs),
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
    print("Starting RUES-based representative legal enrichment...")
    print("=" * 60)
    
    # Check for dry run mode
    dry_run = os.environ.get('DRY_RUN', '').lower() == 'true'
    if dry_run:
        print("RUNNING IN DRY-RUN MODE - NO DATABASE CHANGES WILL BE MADE")
    print()
    
    # Scan CRM for companies that need updating
    scan_cmd = [
        'aws', 'dynamodb', 'scan',
        '--table-name', 'sifagent-crm-clients',
        '--region', 'us-east-1',
        '--projection-expression', 'PK, SK, NIT, Website, RepresentanteLegal, Responsable'
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
        nit = get_attr(item, 'NIT')
        website = get_attr(item, 'Website')
        rep = get_attr(item, 'RepresentanteLegal')
        resp = get_attr(item, 'Responsable')
        
        # Skip if NIT is missing or invalid
        if not nit:
            # print(f"Skipping {pk}: missing NIT")
            skipped_count += 1
            continue
        nit_digits = re.sub(r'\D', '', nit)
        if len(nit_digits) < 9:
            # print(f"Skipping {pk}: invalid NIT format ({nit})")
            skipped_count += 1
            continue
        
        # Check if we already have a good person-like RepLegal
        if not is_empty_or_generic(rep) and looks_like_person_name(rep):
            # print(f"Skipping {pk}: already has valid RepLegal ('{rep}')")
            skipped_count += 1
            continue
        
        # This company needs updating
        # print(f"\nProcessing: {pk}")
        # print(f"  NIT: {nit}")
        # print(f"  Website: {website or 'None'}")
        # print(f"  Current RepLegal: '{rep}'")
        # print(f"  Current Responsable: '{resp}'")
        
        # Try to get from RUES
        success, rues_name, source = query_rues_for_nit(nit)
        if success and rues_name:
            # Use the name from RUES
            new_rep = rues_name
            # print(f"  Using RUES result: '{new_rep}'")
        else:
            # Fall back to internal Responsable field if it looks like a person
            if not is_empty_or_generic(resp) and looks_like_person_name(resp):
                new_rep = resp
                source = 'internal_fields'
                # print(f"  Falling back to internal Responsable: '{new_rep}'")
            else:
                # Neither RUES nor internal Responsable gave us a good name
                # We'll skip this company for now
                # print(f"  Skipping: no valid name found from RUES or internal fields")
                skipped_count += 1
                continue
        
        # Update the database (or simulate in dry run)
        if update_company_replegal(pk, sk, new_rep, source):
            updated_count += 1
        else:
            failed_count += 1
        
        # Be nice to RUES: delay between requests
        time.sleep(2)
    
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