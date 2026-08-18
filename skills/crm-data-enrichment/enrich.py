#!/usr/bin/env python3
"""
CRM Data Enrichment Script for SIF Agent - Enhanced Version
Enriches representative legal information in the sifagent-crm-clients DynamoDB table
using internal fields first, then falling back to web scraping for qualifying records
"""

import json
import subprocess
import sys
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

def run_aws_command(cmd: List[str]) -> Dict:
    """Run AWS CLI command and return parsed JSON"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"AWS CLI error: {e.stderr}")
        return {}
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return {}

def scan_crm_table() -> List[Dict]:
    """Scan the CRM table for records with problematic RepresentanteLegal"""
    cmd = [
        'aws', 'dynamodb', 'scan',
        '--table-name', 'sifagent-crm-clients',
        '--region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
        '--projection-expression', 'PK, NIT, RepresentanteLegal, Responsable, CargoResponsable, Email, EmailContacto, Website, Telefono, SK',
        '--filter-expression', 'attribute_not_exists(RepresentanteLegal) OR RepresentanteLegal = :empty OR RepresentanteLegal = :pending OR RepresentanteLegal = :null OR RepresentanteLegal = :contacto OR RepresentanteLegal = :gerencia OR RepresentanteLegal = :servicio OR RepresentanteLegal = :comercial OR RepresentanteLegal = :ventas OR RepresentanteLegal = :determinando',
        '--expression-attribute-values', 
        '{":empty": {"S": ""}, ":pending": {"S": "Por determinar"}, ":null": {"S": "N/A"}, ":contacto": {"S": "Contacto"}, ":gerencia": {"S": "Gerencia"}, ":servicio": {"S": "Servicio al Cliente"}, ":comercial": {"S": "Comercial"}, ":ventas": {"S": "Ventas"}, ":determinando": {"S": "Determinando"}}'
    ]
    
    result = run_aws_command(cmd)
    return result.get('Items', [])

def is_generic_rep_legal(value: str) -> bool:
    """Check if a RepresentanteLegal value is generic/empty and needs enrichment"""
    if not value:
        return True
    value_lower = value.strip().lower()
    generic_values = ['', 'por determinar', 'n/a', 'null', 'contacto', 'gerencia', 'servicio al cliente', 'comercial', 'ventas', 'representante legal']
    return value_lower in generic_values

def looks_like_person_name(text: str) -> bool:
    """Check if a string looks like a person's name"""
    if not text or not text.strip():
        return False
    
    text = text.strip()
    
    # Must contain at least two words
    words = text.split()
    if len(words) < 2:
        return False
    
    # Each word should start with a capital letter (for Spanish names)
    # Allow for common prefixes like "De", "Del", "La", etc. but they should be capitalized
    for word in words:
        if not word[0].isupper():
            return False
    
    # Should not be just an email address
    if '@' in text:
        return False
    
    # Should not contain obvious non-name indicators
    non_name_indicators = ['http', 'www', '.com', '.co', '@', 'empresa', 'servicio', 'contacto', 'informacion', 'sas', 'ltda']
    text_lower = text.lower()
    if any(indicator in text_lower for indicator in non_name_indicators):
        return False
    
    # Should not be just a job title without a name
    job_titles = ['gerente', 'director', 'presidente', 'representante', 'contacto', 'servicio', 'comercial', 'ventas', 'soporte']
    text_lower = text.lower()
    if any(title in text_lower for title in job_titles) and len(words) <= 2:
        # Could be just a job title, be careful
        # If it's exactly a job title, it's probably not a name
        if len(words) == 1 and text_lower in job_titles:
            return False
    
    # Additional check: reasonable length for a person's name
    if len(text) > 50:  # Unusually long for a name
        return False
        
    return True

def extract_potential_rep_legal_from_record(record: Dict) -> Optional[str]:
    """Extract potential representative legal from internal record fields"""
    pk = record.get('PK', {}).get('S', 'N/A')
    
    # Check Responsable field first (most promising based on data inspection)
    responsable = record.get('Responsable', {}).get('S', '')
    if looks_like_person_name(responsable):
        # Additional check: if CargoResponsable says "Representante Legal", this is very likely correct
        cargo_resp = record.get('CargoResponsable', {}).get('S', '')
        if cargo_resp == 'Representante Legal':
            return responsable
        # Even if CargoResponsable is empty or something else, Responsable often contains the name
        return responsable
    
    # Check EmailContacto for name patterns (sometimes emails contain names)
    email_contacto = record.get('EmailContacto', {}).get('S', '')
    if email_contacto and '@' in email_contacto:
        # Extract name part before @
        name_part = email_contacto.split('@')[0]
        # Common patterns: nombre.apellido, nombre_apellido, nombreapellido
        name_part = re.sub(r'[._-]', ' ', name_part)  # Replace separators with spaces
        if looks_like_person_name(name_part):
            return name_part.title()  # Proper case
    
    # Check Email field similarly
    email = record.get('Email', {}).get('S', '')
    if email and '@' in email:
        # Skip obvious generic emails
        if not any(generic in email.lower() for generic in ['no@encontrado', 'contacto@', 'info@', 'servicio@']):
            name_part = email.split('@')[0]
            name_part = re.sub(r'[._-]', ' ', name_part)
            if looks_like_person_name(name_part):
                return name_part.title()
    
    return None

def fetch_website_content(url: str) -> Optional[str]:
    """Fetch website content using curl with timeout and user agent"""
    try:
        # Add timeout, follow redirects, and set a realistic user agent
        cmd = [
            'curl', '-s', 
            '--max-time', '15',
            '--location',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Failed to fetch {url}: {e}")
        return None

def extract_representante_legal_from_html(html_content: str, company_name: str) -> Optional[str]:
    """Extract representative legal information from HTML content with improved patterns"""
    if not html_content:
        return None
        
    # Convert to lowercase for easier matching
    content_lower = html_content.lower()
    
    # Patterns to look for - ordered by specificity
    patterns = [
        # Direct mentions with labels
        r'representante\s+legal[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
        r'gerente\s+general[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
        r'director\s+general[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
        r'presidente[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
        # In specific sections
        r'(?:quienes\s+somos|about\s+us|nosotros|equipo|team|leadership|directiva|directivos).*?([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
        # Contact/info sections
        r'(?:contacto|info|informacion).*?([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
        # Look for patterns near common identifiers
        r'(?:nombre\s+completo|nombre\s+del\s+representante|representante\s+legal\s+del\s+representante).*?([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content_lower, re.IGNORECASE | re.DOTALL)
        for match in matches:
            # Clean up the match
            name = match.strip()
            # Basic validation: looks like a person's name (at least 2 words, each starting with capital)
            if len(name.split()) >= 2 and all(part[0].isupper() for part in name.split() if part):
                # Additional filtering: avoid common false positives
                false_positives = ['bogota', 'colombia', 'servicios', 'sas', 'ltda', 'corporativo', 'empresa', 'compañia', 'contacto', 'informacion', 'soporte', 'gerencia', 'ventas']
                if not any(fp in name.lower() for fp in false_positives):
                    # Additional sanity check: reasonable length and not just a title
                    if 5 <= len(name) <= 40 and not any(title in name.lower() for title in ['gerente', 'director', 'presidente']):
                        return name.title()  # Proper case
    
    # If direct patterns didn't work, try to find names near contact info
    # Look for email patterns that might contain names
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, html_content)
    for email in emails:
        # Skip generic emails
        if any(generic in email.lower() for generic in ['@example', 'test@', 'info@', 'contacto@', 'servicio@', 'admin@']):
            continue
            
        name_part = email.split('@')[0]
        # Clean common separators
        name_part = re.sub(r'[._-]', ' ', name_part)
        if looks_like_person_name(name_part):
            return name_part.title()
    
    return None

def update_dynamodb_record(pk: str, sk: str, new_rep_legal: str, source: str) -> bool:
    """Update the DynamoDB record with new representative legal information"""
    timestamp = datetime.utcnow().isoformat() + 'Z'
    
    # Build the key JSON manually to avoid f-string issues
    key_dict = {
        "PK": {"S": pk},
        "SK": {"S": sk}
    }
    
    # Build the expression attribute values manually
    expr_attrs_dict = {
        ":r": {"S": new_rep_legal},
        ":f": {"S": source},
        ":d": {"S": timestamp}
    }
    
    cmd = [
        'aws', 'dynamodb', 'update-item',
        '--table-name', 'sifagent-crm-clients',
        '--region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
        '--key', json.dumps(key_dict),
        '--update-expression', 'SET RepresentanteLegal = :r, FuenteRepLegal = :f, FechaActualizacionRepLegal = :d',
        '--expression-attribute-values', json.dumps(expr_attrs_dict),
        '--return-values', 'ALL_NEW'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Successfully updated {pk}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to update {pk}: {e.stderr}")
        return False

def process_record_internal(record: Dict) -> Tuple[Optional[str], str]:
    """Try to extract representative legal from internal fields"""
    internal_rep_legal = extract_potential_rep_legal_from_record(record)
    if internal_rep_legal:
        return internal_rep_legal, 'internal_fields'
    return None, ''

def process_record_external(record: Dict) -> Tuple[Optional[str], str]:
    """Try to extract representative legal from website scraping"""
    website = record.get('Website', {}).get('S', '')
    if not website or not website.strip():
        return None, 'no_website'
    
    pk = record.get('PK', {}).get('S', 'Unknown')
    print(f"  Attempting website scrape for {pk}: {website}")
    
    # Fetch website content
    html_content = fetch_website_content(website)
    if not html_content:
        return None, 'fetch_failed'
    
    # Extract representative legal
    new_rep_legal = extract_representante_legal_from_html(html_content, pk)
    if new_rep_legal:
        return new_rep_legal, 'website'
    
    return None, 'extraction_failed'

def is_record_valid_for_enrichment(record: Dict) -> bool:
    """Check if record has valid NIT and website for enrichment attempts"""
    pk = record.get('PK', {}).get('S', 'N/A')
    website = record.get('Website', {}).get('S', '')
    nit = record.get('NIT', {}).get('S', '')
    sk = record.get('SK', {}).get('S', '')
    
    # Must have website
    if not website or not website.strip():
        return False
    
    # Must have valid NIT (not empty, not PENDIENTE, 9+ digits)
    if not nit or nit.strip() == '' or nit.strip().upper() in ['PENDIENTE', 'N/A', 'NULL']:
        return False
    
    nit_clean = re.sub(r'[^\d]', '', nit)
    if len(nit_clean) < 9:
        return False
    
    # Should have valid SK (not empty)
    if not sk or sk.strip() == '' or sk.strip().upper() in ['N/A', 'NULL', 'PENDIENTE']:
        # We'll still try but note this might cause update issues
        pass  # Continue anyway, we'll handle SK in update
    
    return True

def process_record(record: Dict, dry_run: bool = False) -> Dict:
    """Process a single record for enrichment"""
    pk = record.get('PK', {}).get('S', 'N/A')
    nit = record.get('NIT', {}).get('S', '')
    website = record.get('Website', {}).get('S', '')
    telefono = record.get('Telefono', {}).get('S', '')
    current_rep_legal = record.get('RepresentanteLegal', {}).get('S', '')
    
    result = {
        'pk': pk,
        'nit': nit,
        'website': website,
        'telefono': telefono,
        'current_rep_legal': current_rep_legal,
        'action': 'skipped',
        'reason': '',
        'new_value': None,
        'source': None,
        'timestamp': None,
        'phase': None
    }
    
    # Skip if current rep legal is already good (shouldn't happen based on filter, but double-check)
    if not is_generic_rep_legal(current_rep_legal):
        result['action'] = 'skipped'
        result['reason'] = 'Current RepresentanteLegal appears valid'
        return result
    
    print(f"Processing {pk}...")
    
    # PHASE 1: Try internal fields first
    internal_name, internal_source = process_record_internal(record)
    if internal_name:
        if dry_run:
            result['action'] = 'would_update'
            result['new_value'] = internal_name
            result['source'] = internal_source
            result['timestamp'] = datetime.utcnow().isoformat() + 'Z'
            result['phase'] = 'internal'
            return result
        
        # We need the SK to update
        sk_candidates = []
        sk_field = record.get('SK', {}).get('S', '')
        if sk_field and sk_field not in ['N/A', ''] and not sk_field.startswith('PENDIENTE'):
            sk_candidates.append(sk_field)
        
        nit_val = record.get('NIT', {}).get('S', '')
        if nit_val and nit_val not in ['N/A', '', 'PENDIENTE'] and len(re.sub(r'[^\d]', '', nit_val)) >= 9:
            sk_candidates.append(nit_val)
        
        # Use the first valid SK candidate
        sk = sk_candidates[0] if sk_candidates else nit_val  # fallback
        
        # Update the record
        if update_dynamodb_record(pk, sk, internal_name, internal_source):
            result['action'] = 'updated'
            result['new_value'] = internal_name
            result['source'] = internal_source
            result['timestamp'] = datetime.utcnow().isoformat() + 'Z'
            result['phase'] = 'internal'
        else:
            result['action'] = 'failed'
            result['reason'] = 'Failed to update DynamoDB (internal)'
        
        return result
    
    # PHASE 2: If internal didn't work, try external (only for records with valid NIT+website)
    if is_record_valid_for_enrichment(record):
        external_name, external_source = process_record_external(record)
        if external_name:
            if dry_run:
                result['action'] = 'would_update'
                result['new_value'] = external_name
                result['source'] = external_source
                result['timestamp'] = datetime.utcnow().isoformat() + 'Z'
                result['phase'] = 'external'
                return result
            
            # We need the SK to update
            sk_candidates = []
            sk_field = record.get('SK', {}).get('S', '')
            if sk_field and sk_field not in ['N/A', ''] and not sk_field.startswith('PENDIENTE'):
                sk_candidates.append(sk_field)
            
            nit_val = record.get('NIT', {}).get('S', '')
            if nit_val and nit_val not in ['N/A', '', 'PENDIENTE'] and len(re.sub(r'[^\d]', '', nit_val)) >= 9:
                sk_candidates.append(nit_val)
            
            # Use the first valid SK candidate
            sk = sk_candidates[0] if sk_candidates else nit_val  # fallback
            
            # Update the record
            if update_dynamodb_record(pk, sk, external_name, external_source):
                result['action'] = 'updated'
                result['new_value'] = external_name
                result['source'] = external_source
                result['timestamp'] = datetime.utcnow().isoformat() + 'Z'
                result['phase'] = 'external'
            else:
                result['action'] = 'failed'
                result['reason'] = 'Failed to update DynamoDB (external)'
            
            return result
        else:
            # External attempt failed
            result['action'] = 'failed'
            result['reason'] = f'External processing failed: {external_source}'
            return result
    else:
        # Record not valid for external processing
        result['action'] = 'skipped'
        if not website or not website.strip():
            result['reason'] = 'Missing or invalid website'
        else:
            nit_val = record.get('NIT', {}).get('S', '')
            if not nit_val or nit_val.strip() == '' or nit_val.strip().upper() in ['PENDIENTE', 'N/A', 'NULL']:
                result['reason'] = 'Missing or invalid NIT'
            else:
                nit_clean = re.sub(r'[^\d]', '', nit_val)
                if len(nit_clean) < 9:
                    result['reason'] = 'NIT too short'
                else:
                    result['reason'] = 'Record does not meet criteria for external processing'
        return result

def main():
    """Main execution function"""
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    
    print(f"Starting CRM data enrichment (DRY_RUN={dry_run})")
    print("Phase 1: Internal field extraction")
    print("Phase 2: External web scraping (for records with valid NIT+website)")
    
    # Scan for problematic records
    records = scan_crm_table()
    print(f"Found {len(records)} records with problematic RepresentanteLegal")
    
    # Process each record
    results = {
        'total_processed': len(records),
        'updated': 0,
        'skipped': 0,
        'failed': 0,
        'details': []
    }
    
    internal_updated = 0
    external_updated = 0
    
    for i, record in enumerate(records):
        # Progress indicator
        if (i + 1) % 20 == 0 or i == len(records) - 1:
            print(f"Progress: {i + 1}/{len(records)} records processed")
        
        result = process_record(record, dry_run=dry_run)
        results['details'].append(result)
        
        if result['action'] == 'updated':
            results['updated'] += 1
            if result['phase'] == 'internal':
                internal_updated += 1
            elif result['phase'] == 'external':
                external_updated += 1
        elif result['action'] == 'would_update':
            results['updated'] += 1  # Count as updated in dry run for reporting
            if result['phase'] == 'internal':
                internal_updated += 1
            elif result['phase'] == 'external':
                external_updated += 1
        elif result['action'] == 'failed':
            results['failed'] += 1
        else:  # skipped
            results['skipped'] += 1
        
        # Be respectful to websites - small delay between external requests
        if result.get('phase') == 'external' and not dry_run:
            time.sleep(0.5)  # 500ms delay between website requests
    
    # Print summary
    print("\n=== ENRICHMENT SUMMARY ===")
    print(f"Total processed: {results['total_processed']}")
    print(f"Updated: {results['updated']} (Internal: {internal_updated}, External: {external_updated})")
    print(f"Failed: {results['failed']}")
    print(f"Skipped: {results['skipped']}")
    
    if results['updated'] > 0:
        print("\n=== UPDATED RECORDS ===")
        internal_details = [d for d in results['details'] if d['action'] in ['updated', 'would_update'] and d.get('phase') == 'internal']
        external_details = [d for d in results['details'] if d['action'] in ['updated', 'would_update'] and d.get('phase') == 'external']
        
        if internal_details:
            print(f"\n--- Internal Field Updates ({len(internal_details)}) ---")
            for detail in internal_details[:10]:  # Show first 10
                print(f"- {detail['pk']}: '{detail['current_rep_legal']}' → '{detail['new_value']}' (source: {detail['source']})")
            if len(internal_details) > 10:
                print(f"  ... and {len(internal_details) - 10} more")
        
        if external_details:
            print(f"\n--- External Website Updates ({len(external_details)}) ---")
            for detail in external_details[:10]:  # Show first 10
                print(f"- {detail['pk']}: '{detail['current_rep_legal']}' → '{detail['new_value']}' (source: {detail['source']})")
            if len(external_details) > 10:
                print(f"  ... and {len(external_details) - 10} more")
    
    # Output JSON for further processing
    print("\n=== JSON OUTPUT ===")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    return 0 if results['failed'] == 0 else 1

if __name__ == '__main__':
    sys.exit(main())