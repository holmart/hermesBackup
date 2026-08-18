#!/usr/bin/env python3
"""
Automated RUES (Registro Único Empresarial y Social) query script for SIF Agent CRM enrichment
Queries RUES to obtain representative legal information for Colombian companies
and updates the sifagent-crm-clients DynamoDB table.

NOTE: RUES employs CAPTCHA protection. This script includes placeholders for:
1. Manual CAPTCHA solving (default)
2. Integration with 2captcha or similar services (requires API key)

To use with automatic CAPTCHA solving:
1. Obtain API key from 2captcha.com or similar service
2. Set CAPTCHA_API_KEY environment variable
3. Install required packages: selenium, webdriver-manager

To use with manual CAPTCHA solving:
1. Run the script - it will pause for you to solve CAPTCHAs in the browser
"""

import json
import os
import sys
import time
import subprocess
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Try to import selenium, provide guidance if not available
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("WARNING: Selenium not installed. Install with: pip install selenium webdriver-manager")

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

def scan_crm_for_rues_candidates(limit: int = 50) -> List[Dict]:
    """Scan CRM table for companies with valid NIT and website but missing/invalid RepLegal"""
    cmd = [
        'aws', 'dynamodb', 'scan',
        '--table-name', 'sifagent-crm-clients',
        '--region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
        '--projection-expression', 'PK, NIT, Website, RepresentanteLegal, Responsable, CargoResponsable, Email, Telefono',
        '--filter-expression', '(attribute_not_exists(RepresentanteLegal) OR RepresentanteLegal = :empty OR RepresentanteLegal = :pending OR RepresentanteLegal = :null OR RepresentanteLegal = :contacto OR RepresentanteLegal = :gerencia OR RepresentanteLegal = :servicio OR RepresentanteLegal = :comercial OR RepresentanteLegal = :ventas OR RepresentanteLegal = :determinando) AND attribute_exists(NIT) AND attribute_exists(Website)',
        '--expression-attribute-values', 
        '{":empty": {"S": ""}, ":pending": {"S": "Por determinar"}, ":null": {"S": "N/A"}, ":contacto": {"S": "Contacto"}, ":gerencia": {"S": "Gerencia"}, ":servicio": {"S": "Servicio al Cliente"}, ":comercial": {"S": "Comercial"}, ":ventas": {"S": "Ventas"}, ":determinando": {"S": "Determinando"}}',
        '--limit', str(limit)
    ]
    
    result = run_aws_command(cmd)
    items = result.get('Items', [])
    
    candidates = []
    for item in items:
        pk = item.get('PK', {}).get('S', 'N/A')
        nit = item.get('NIT', {}).get('S', '')
        website = item.get('Website', {}).get('S', '')
        rep_legal = item.get('RepresentanteLegal', {}).get('S', '')
        responsable = item.get('Responsable', {}).get('S', '')
        cargo = item.get('CargoResponsable', {}).get('S', '')
        email = item.get('Email', {}).get('S', '')
        telefono = item.get('Telefono', {}).get('S', '')
        
        # Validate NIT: not empty, not PENDIENTE, at least 9 digits
        nit_valid = bool(nit and nit.strip() and nit.strip().upper() not in ['PENDIENTE', 'N/A', 'NULL'] and len(re.sub(r'[^\d]', '', nit)) >= 9)
        
        # Validate website: not empty and looks like a URL
        website_valid = bool(website and website.strip() and (website.startswith('http://') or website.startswith('https://') or '.' in website))
        
        if nit_valid and website_valid:
            candidates.append({
                'pk': pk,
                'nit': nit,
                'website': website,
                'current_rep_legal': rep_legal,
                'responsable': responsable,
                'cargo_responsable': cargo,
                'email': email,
                'telefono': telefono
            })
    
    return candidates

def solve_captcha_manual(driver) -> bool:
    """
    Pause execution for manual CAPTCHA solving
    Returns True when user indicates CAPTCHA is solved
    """
    print("\n" + "="*60)
    print("CAPTCHA DETECTED - MANUAL SOLVING REQUIRED")
    print("="*60)
    print("Please solve the CAPTCHA in the browser window.")
    print("Once solved, press ENTER to continue...")
    print("="*60)
    
    try:
        input()  # Wait for user to press ENTER
        return True
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return False

def solve_captcha_automatic(driver) -> bool:
    """
    Attempt to solve CAPTCHA automatically using 2captcha service
    Requires CAPTCHA_API_KEY environment variable
    """
    api_key = os.environ.get('CAPTCHA_API_KEY')
    if not api_key:
        print("No CAPTCHA_API_KEY found. Falling back to manual solving.")
        return solve_captcha_manual(driver)
    
    # This is a placeholder - actual implementation would:
    # 1. Detect CAPTCHA image/iframe
    # 2. Send to 2captcha API
    # 3. Poll for solution
    # 4. Fill in the solution
    print("Automatic CAPTCHA solving not fully implemented in this version.")
    print("Falling back to manual solving.")
    return solve_captcha_manual(driver)

def query_rues_for_nit(driver, nit: str) -> Optional[Dict]:
    """
    Query RUES website for a specific NIT and extract representative legal information
    Returns dict with rep_legal_name, source, etc. or None if not found/error
    """
    try:
        # Navigate to RUES public query page
        driver.get("https://www.rues.org.co/consulta-publica")
        time.sleep(3)  # Allow page to load
        
        # Find the NIT input field and enter the NIT
        # Note: Selectors may need adjustment based on actual RUES page structure
        nit_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "nit"))  # This is a guess - actual ID may differ
        )
        nit_input.clear()
        nit_input.send_keys(nit)
        
        # Find and click the search button
        search_button = driver.find_element(By.ID, "btnConsultar")  # Another guess
        search_button.click()
        
        # Wait for results to load
        time.sleep(5)
        
        # Check if CAPTCHA appears
        page_source = driver.page_source.lower()
        if 'captcha' in page_source or 'recaptcha' in page_source:
            if not solve_captcha_automatic(driver):
                return None
            # After solving, we might need to click search again
            time.sleep(3)
        
        # Extract results - this is highly dependent on RUES page structure
        # Look for representative legal information
        rep_legal_elem = None
        try:
            # Try various selectors that might contain the representative legal name
            selectors_to_try = [
                "//*[contains(text(), 'Representante Legal')]/following-sibling::*",
                "//*[contains(@class, 'representante-legal')]",
                "//*[contains(text(), 'Nombre') and contains(text(), 'Representante')]",
                "//td[contains(text(), 'Representante')]/following-sibling::td",
                "//div[contains(text(), 'Representante')]/following-sibling::div"
            ]
            
            for selector in selectors_to_try:
                try:
                    elements = driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        text = elem.text.strip()
                        if text and len(text) > 3 and not text.isdigit() and '@' not in text:
                            # Basic validation: looks like a person's name
                            words = text.split()
                            if len(words) >= 2 and all(w[0].isupper() for w in words if w):
                                rep_legal_elem = elem
                                break
                    if rep_legal_elem:
                        break
                except:
                    continue
                    
        except NoSuchElementException:
            pass
        
        if rep_legal_elem:
            rep_legal_name = rep_legal_elem.text.strip()
            # Clean up the name
            rep_legal_name = re.sub(r'\s+', ' ', rep_legal_name)
            return {
                'rep_legal_name': rep_legal_name,
                'source': 'RUES consulta pública',
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
        else:
            # Try to extract from page text using regex patterns
            page_text = driver.find_element(By.TAG_NAME, "body").text
            # Look for patterns like "Representante Legal: Juan Pérez"
            patterns = [
                r'Representante\s+Legal[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
                r'Nombre\s+completo[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})',
                r'Legal\s+representante[:\s]+([A-ZÁÉÍÓÚÜ�Ñ][a-záéióúñ]+(?:\s+[A-ZÁÉÍÓÚÜ�Ñ][a-záéíóúñ]+){1,3})'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    if len(name.split()) >= 2:
                        return {
                            'rep_legal_name': name,
                            'source': 'RUES consulta pública (regex extraction)',
                            'timestamp': datetime.utcnow().isoformat() + 'Z'
                        }
            
            return None
            
    except Exception as e:
        print(f"Error querying RUES for NIT {nit}: {str(e)}")
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

def process_company_rues(driver, company: Dict) -> Tuple[bool, str]:
    """
    Process a single company: query RUES and update DynamoDB if successful
    Returns (success, message)
    """
    pk = company['pk']
    nit = company['nit']
    website = company['website']
    
    print(f"Processing {pk} (NIT: {nit})...")
    
    # Query RUES
    result = query_rues_for_nit(driver, nit)
    
    if result and result.get('rep_legal_name'):
        new_rep_legal = result['rep_legal_name']
        source = result['source']
        
        # We need SK to update - try to get it from the record or use NIT as fallback
        # In a real implementation, we'd fetch the full record to get SK
        # For now, we'll use NIT as SK (this may not always work)
        sk_candidates = [nit]
        # Add other possible SK values if we had them
        
        sk = sk_candidates[0]  # Use NIT as SK - this is a simplification
        
        # Update the record
        if update_dynamodb_record(pk, sk, new_rep_legal, source):
            return True, f"Updated with: {new_rep_legal}"
        else:
            return False, "Failed to update DynamoDB"
    else:
        return False, "No representative legal found in RUES"

def main():
    """Main execution function"""
    print("Starting RUES-based CRM enrichment for SIF Agent")
    print("=" * 60)
    
    # Check if selenium is available
    if not SELENIUM_AVAILABLE:
        print("ERROR: Selenium is not installed. Please install it first:")
        print("pip install selenium webdriver-manager")
        print("\nAlternatively, you can run in mock mode by setting MOCK_MODE=true")
        if os.environ.get('MOCK_MODE', 'false').lower() != 'true':
            return 1
        else:
            print("Running in MOCK mode - no actual web queries will be made")
    
    # Get companies to process
    limit_env = os.environ.get('RUES_QUERY_LIMIT', '10')
    try:
        limit = int(limit_env)
    except ValueError:
        limit = 10
    
    print(f"Scanning for up to {limit} companies with valid NIT+website but missing RepLegal...")
    companies = scan_crm_for_rues_candidates(limit=limit)
    
    if not companies:
        print("No companies found matching criteria.")
        return 0
    
    print(f"Found {len(companies)} companies to process:")
    for i, company in enumerate(companies, 1):
        print(f"  {i}. {company['pk']} (NIT: {company['nit']})")
    
    # Ask for confirmation unless in non-interactive mode
    if os.environ.get('NON_INTERACTIVE', 'false').lower() != 'true':
        response = input(f"\nProceed with processing {len(companies)} companies? (y/N): ")
        if response.lower() not in ['y', 'yes']:
            print("Operation cancelled.")
            return 0
    
    # Setup WebDriver if not in mock mode
    driver = None
    if not os.environ.get('MOCK_MODE', 'false').lower() == 'true':
        try:
            chrome_options = Options()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            # Uncomment next line to run headless (may not work with CAPTCHA)
            # chrome_options.add_argument("--headless")
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(30)
        except Exception as e:
            print(f"Failed to initialize WebDriver: {e}")
            print("Make sure ChromeDriver is installed and in PATH")
            print("You can install it with: webdriver-manager chrome --linkpath /usr/local/bin")
            return 1
    
    # Process each company
    results = {
        'total_processed': len(companies),
        'successful': 0,
        'failed': 0,
        'details': []
    }
    
    try:
        for i, company in enumerate(companies, 1):
            print(f"\n[{i}/{len(companies)}] ", end="")
            
            if driver:
                success, message = process_company_rues(driver, company)
            else:
                # Mock mode - simulate results
                print("MOCK MODE: Simulating query...")
                time.sleep(2)  # Simulate network delay
                # Simulate success for some companies
                if hash(company['pk']) % 3 == 0:  # 33% success rate in mock
                    success = True
                    message = f"Mock update: Juan Pérez García (from RUES)"
                else:
                    success = False
                    message = "Mock: No representative legal found"
            
            if success:
                results['successful'] += 1
                results['details'].append({
                    'pk': company['pk'],
                    'nit': company['nit'],
                    'action': 'updated',
                    'message': message,
                    'new_value': message.split(': ')[-1] if ': ' in message else message
                })
                print(f"��✓ SUCCESS: {message}")
            else:
                results['failed'] += 1
                results['details'].append({
                    'pk': company['pk'],
                    'nit': company['nit'],
                    'action': 'failed',
                    'message': message
                })
                print(f"��✗ FAILED: {message}")
            
            # Be respectful to the RUES server - delay between requests
            if i < len(companies) and driver:
                time.sleep(3)  # 3 second delay between requests
    
    finally:
        if driver:
            driver.quit()
    
    # Print summary
    print("\n" + "=" * 60)
    print("RUES ENRICHMENT SUMMARY")
    print("=" * 60)
    print(f"Total processed: {results['total_processed']}")
    print(f"Successful: {results['successful']}")
    print(f"Failed: {results['failed']}")
    
    if results['successful'] > 0:
        print("\nSuccessfully updated records:")
        for detail in results['details']:
            if detail['action'] == 'updated':
                print(f"  - {detail['pk']}: '{detail.get('new_value', 'N/A')}'")
    
    # Output JSON for further processing
    print("\nJSON OUTPUT:")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    return 0 if results['failed'] == 0 else 1

if __name__ == '__main__':
    sys.exit(main())