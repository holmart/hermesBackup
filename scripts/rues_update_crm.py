#!/usr/bin/env python3
"""
Script to update CRM DynamoDB with official data from RUES CSV.
Matches items by NIT (stored as SK and NIT attribute) and updates:
- NIT attribute (to ensure consistency)
- RazonSocialLegal attribute (official legal name from RUES)
Operates in dry-run mode by default; set APPLY_CHANGES=true to apply changes.
"""
import subprocess
import json
import os
import sys
import csv
from urllib.parse import quote_plus

# Configuration
TABLE_NAME = 'sifagent-crm-clients'
REGION = 'us-east-1'
CSV_PATH = '/home/ubuntu/.hermes/leads/rues_fumigacion_enrichment.csv'
# Set to 'true' to actually apply changes (otherwise dry run)
APPLY_CHANGES = os.environ.get('APPLY_CHANGES', '').lower() == 'true'

def run_aws_cmd(cmd):
    """Run AWS CLI command and return parsed JSON or None on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"AWS CLI error: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return None

def scan_items_by_nit(nit):
    """Scan table for items where SK (NIT attribute) equals the given nit."""
    # Use scan with filter expression: SK = :nit
    # We'll retrieve only necessary attributes to minimize data transfer
    cmd = [
        'aws', 'dynamodb', 'scan',
        '--table-name', TABLE_NAME,
        '--region', REGION,
        '--filter-expression', 'SK = :nit',
        '--expression-attribute-values', json.dumps({':nit': {'S': nit}}),
        '--projection-expression', 'PK, SK, NIT, RazonSocialLegal',  # adjust if needed
        '--max-items', '1000'  # paginate internally if needed
    ]
    # Note: AWS CLI scan does not natively paginate with --max-items; we need to handle LastEvaluatedKey.
    # We'll implement pagination manually.
    items = []
    exclusive_start_key = None
    while True:
        if exclusive_start_key:
            cmd_ext = cmd + ['--exclusive-start-key', json.dumps(exclusive_start_key)]
        else:
            cmd_ext = cmd
        result = run_aws_cmd(cmd_ext)
        if result is None:
            return None
        items.extend(result.get('Items', []))
        exclusive_start_key = result.get('LastEvaluatedKey')
        if not exclusive_start_key:
            break
    return items

def update_item(pk, sk, changes):
    """Update an item with given changes (dict of attribute name to new value)."""
    if not changes:
        return True, None
    # Build update expression
    set_clauses = []
    expr_vals = {}
    for i, (attr, val) in enumerate(changes.items()):
        placeholder = f':{attr}{i}'
        set_clauses.append(f'{attr} = {placeholder}')
        expr_vals[placeholder] = {'S': val}
    update_expr = 'SET ' + ', '.join(set_clauses)
    key = {'PK': {'S': pk}, 'SK': {'S': sk}}
    cmd = [
        'aws', 'dynamodb', 'update-item',
        '--table-name', TABLE_NAME,
        '--region', REGION,
        '--key', json.dumps(key),
        '--update-expression', update_expr,
        '--expression-attribute-values', json.dumps(expr_vals),
        '--return-values', 'ALL_NEW'
    ]
    if APPLY_CHANGES:
        result = run_aws_cmd(cmd)
        if result is None:
            return False, "AWS CLI error"
        return True, result.get('Attributes')
    else:
        # Dry run: just show what would be done
        changes_str = ', '.join(f'{k}={v}' for k, v in changes.items())
        print(f"    [DRY RUN] Would update {pk}: {changes_str}")
        return True, None

def main():
    print("=" * 60)
    print("RUES CSV to CRM Update Script")
    print("=" * 60)
    if APPLY_CHANGES:
        print("MODE: APPLYING CHANGES TO DATABASE")
    else:
        print("MODE: DRY RUN (no changes will be made)")
        print("  Set APPLY_CHANGES=true to apply changes")
    print()

    # Load CSV
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: CSV file not found: {CSV_PATH}")
        return 1
    print(f"Loading CSV: {CSV_PATH}")
    try:
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"ERROR reading CSV: {e}")
        return 1

    if not rows:
        print("CSV is empty")
        return 1

    print(f"Loaded {len(rows)} records from CSV")
    # Show first few records
    for i, row in enumerate(rows[:3]):
        print(f"  {i+1}. NIT: {row.get('nit')}, RazonSocial: {row.get('razon_social')}")

    # Process each NIT
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    nit_not_found_count = 0

    for row in rows:
        nit = row.get('nit')
        razon_social = row.get('razon_social')
        if not nit:
            print(f"Skipping row with missing NIT: {row}")
            skipped_count += 0  # not counted as skipped; just ignore
            continue
        # Optionally trim whitespace
        nit = nit.strip()
        razon_social = razon_social.strip() if razon_social else ''

        # Scan for items with this NIT as SK
        items = scan_items_by_nit(nit)
        if items is None:
            print(f"ERROR scanning for NIT {nit}")
            failed_count += 1
            continue

        if not items:
            print(f"NIT {nit}: No matching item found in CRM")
            nit_not_found_count += 1
            continue

        # We expect at most one item per NIT, but handle multiple just in case
        for item in items:
            pk = item.get('PK', {}).get('S')
            sk = item.get('SK', {}).get('S')
            current_nit = item.get('NIT', {}).get('S')
            current_razon = item.get('RazonSocialLegal', {}).get('S')  # may be None

            changes = {}
            # Update NIT attribute if missing or different (should match SK, but ensure)
            if current_nit != nit:
                changes['NIT'] = nit
                print(f"  NIT mismatch: PK={pk}, current NIT attribute={current_nit}, CSV NIT={nit}")
            # Update official name if missing or different
            if current_razon != razon_social:
                changes['RazonSocialLegal'] = razon_social
                if current_razon is None:
                    print(f"  Adding official name: {razon_social}")
                else:
                    print(f"  Updating official name: {current_razon} -> {razon_social}")

            if changes:
                print(f"  Updating item PK={pk}, SK={sk}")
                success, attrs = update_item(pk, sk, changes)
                if success:
                    updated_count += 1
                    if APPLY_CHANGES and attrs:
                        # Optionally show updated attributes
                        pass
                else:
                    failed_count += 1
                    print(f"    ERROR: {attrs}")  # attrs contains error message in dry run? Actually update_item returns (bool, attrs_or_error)
            else:
                # No changes needed
                skipped_count += 1

    print()
    print("=" * 60)
    print("SUMMARY:")
    print(f"  Records processed from CSV: {len(rows)}")
    print(f"  Items updated: {updated_count}")
    print(f"  Items skipped (no changes): {skipped_count}")
    print(f"  NITs not found in CRM: {nit_not_found_count}")
    print(f"  Failed scans/updates: {failed_count}")
    print("=" * 60)

    if APPLY_CHANGES:
        print("Changes have been applied to the database.")
    else:
        print("This was a dry run. To apply changes, set APPLY_CHANGES=true and re-run.")
    return 0 if failed_count == 0 else 1

if __name__ == '__main__':
    sys.exit(main())