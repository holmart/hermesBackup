#!/usr/bin/env python3
"""
Test script to explore RUES endpoints for fumigation companies.
"""
import subprocess
import re
import json
import time
import random
from urllib.parse import quote_plus, urljoin

# User agents pool (realistic)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

# Common headers to mimic a browser
COMMON_HEADERS = [
    "accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language: es-ES,es;q=0.9,en;q=0.8",
    "cache-control: no-cache",
    "pragma: no-cache",
    "upgrade-insecure-requests: 1",
    "sec-ch-ua: \"Chromium\";v=\"124\", \"Not(A:Brand\";v=\"8\", \"Chromium\";v=\"124\"",
    "sec-ch-ua-mobile: ?0",
    "sec-ch-ua-platform: \"Windows\"",
    "sec-fetch-dest: document",
    "sec-fetch-mode: navigate",
    "sec-fetch-site: none",
    "sec-fetch-user: ?1",
]

def build_curl(url, cookie_file=None, referer=None, ua=None):
    """Build curl command with headers."""
    cmd = ["curl", "-s", "-L", "--max-time", "20", "--compressed"]
    if ua:
        cmd.extend(["-A", ua])
    else:
        cmd.extend(["-A", random.choice(USER_AGENTS)])
    for h in COMMON_HEADERS:
        cmd.extend(["-H", h])
    if cookie_file:
        cmd.extend(["--cookie", cookie_file, "--cookie-jar", cookie_file])
    if referer:
        cmd.extend(["-e", referer])
    cmd.append(url)
    return cmd

def fetch(url, max_attempts=3, cookie_file=None, referer=None):
    """Fetch URL with retry and bot challenge detection."""
    for attempt in range(1, max_attempts + 1):
        ua = random.choice(USER_AGENTS)
        cmd = build_curl(url, cookie_file, referer, ua)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            html = result.stdout
            # Check for common bot challenge indicators
            lowered = html.lower()
            if any(txt in lowered for txt in [
                "please complete the following challenge",
                "solving this captcha",
                "unusual traffic",
                "are you a robot",
                "verify you are a human",
                "¿eres un robot?",
                "please enable javascript",
                "access denied",
                "bot detection",
                "cloudflare",
                "checking your browser"
            ]):
                wait = min(2 ** attempt, 10) + random.uniform(0, 2)
                print(f"  Attempt {attempt}: bot challenge detected, waiting {wait:.1f}s...")
                time.sleep(wait)
                continue
            return html
        except subprocess.CalledProcessError as e:
            wait = min(2 ** attempt, 10) + random.uniform(0, 2)
            print(f"  Attempt {attempt}: curl failed ({e}), retrying in {wait:.1f}s...")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url} after {max_attempts} attempts")

def test_search_endpoints():
    """Test various RUES search endpoints."""
    print("=== Testing RUES Search Endpoints ===")
    
    # Test queries
    queries = [
        "fumigacion",
        "control de plagas",
        "plagas",
        "fumigadora"
    ]
    
    # Test endpoints
    endpoints = [
        {
            "name": "Consulta pública por razón social",
            "url": "https://www.rues.org.co/consulta-publica",
            "params": {"razonSocial": "fumigacion"},
            "type": "GET"
        },
        {
            "name": "Consulta pública por CIIU",
            "url": "https://www.rues.org.co/consulta-publica",
            "params": {"ciiu": "8129"},
            "type": "GET"
        },
        {
            "name": "API buscar empresa",
            "url": "https://www.rues.org.co/api/empresa/buscar",
            "params": {"q": "fumigacion", "size": "10"},
            "type": "GET"
        },
        {
            "name": "API buscar por CIIU",
            "url": "https://www.rues.org.co/api/empresa/buscar",
            "params": {"ciiu": "8129", "size": "10"},
            "type": "GET"
        },
        {
            "name": "API autocomplete",
            "url": "https://www.rues.org.co/api/empresa/autocomplete",
            "params": {"q": "fumigacion"},
            "type": "GET"
        }
    ]
    
    cookie_file = "/tmp/rues_cookies.txt"
    open(cookie_file, 'a').close()
    
    for endpoint in endpoints:
        print(f"\n--- Testing: {endpoint['name']} ---")
        try:
            # Build URL with parameters
            if endpoint['params']:
                param_str = "&".join([f"{k}={quote_plus(str(v))}" for k, v in endpoint['params'].items()])
                url = f"{endpoint['url']}?{param_str}"
            else:
                url = endpoint['url']
            
            print(f"URL: {url}")
            
            # Try to get homepage first to establish session
            try:
                fetch("https://www.rues.org.co/", cookie_file=cookie_file, referer="https://www.rues.org.co/")
            except:
                pass  # Continue even if homepage fails
            
            html = fetch(url, cookie_file=cookie_file, referer=url)
            print(f"Response length: {len(html)}")
            
            # Check if we got meaningful data (not just bot challenge or redirect)
            if len(html) < 1000:
                print("  Response too small, likely bot challenge or redirect")
                # Save for inspection
                with open(f"/tmp/rues_{endpoint['name'].replace(' ', '_')}.html", "w") as f:
                    f.write(html)
                continue
                
            # Look for signs of actual data
            if "empresa" in html.lower() or "nit" in html.lower() or "razon social" in html.lower():
                print("  � ✓ Contains business data indicators")
                # Save sample
                with open(f"/tmp/rues_{endpoint['name'].replace(' ', '_')}_sample.html", "w") as f:
                    f.write(html[:2000])
                print(f"  Sample saved to /tmp/rues_{endpoint['name'].replace(' ', '_')}_sample.html")
            else:
                print("  � ✗ No obvious business data found")
                # Save for inspection
                with open(f"/tmp/rues_{endpoint['name'].replace(' ', '_')}.html", "w") as f:
                    f.write(html[:1000])
                    
        except Exception as e:
            print(f"  Error: {e}")

def test_specific_company():
    """Test querying a specific known company by NIT."""
    print("\n=== Testing Specific Company Query (NIT: 9009554608) ===")
    
    nit = "9009554608"
    endpoints = [
        {
            "name": "Consulta pública por NIT",
            "url": f"https://www.rues.org.co/consulta-publica?nit={nit}"
        },
        {
            "name": "API empresa por NIT",
            "url": f"https://www.rues.org.co/api/empresa/{nit}"
        },
        {
            "name": "API empresa detalle",
            "url": f"https://www.rues.org.co/api/empresa/detalle/{nit}"
        }
    ]
    
    cookie_file = "/tmp/rues_cookies_specific.txt"
    open(cookie_file, 'a').close()
    
    for endpoint in endpoints:
        print(f"\n--- Testing: {endpoint['name']} ---")
        print(f"URL: {endpoint['url']}")
        
        try:
            # Try to get homepage first
            try:
                fetch("https://www.rues.org.co/", cookie_file=cookie_file, referer="https://www.rues.org.co/")
            except:
                pass
            
            html = fetch(endpoint['url'], cookie_file=cookie_file, referer=endpoint['url'])
            print(f"Response length: {len(html)}")
            
            # Check for expected data from history
            expected_name = "FREDY YOBANNY OLARTE RAMIREZ"
            if expected_name in html:
                print(f"  � ✓ Found expected representative: {expected_name}")
            elif "nit" in html.lower() and "9009554608" in html:
                print("  � ✓ Found NIT in response")
            
            # Save sample
            with open(f"/tmp/rues_nit_{nit}_{endpoint['name'].replace(' ', '_')}.html", "w") as f:
                f.write(html[:3000])
            print(f"  Sample saved")
            
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    test_search_endpoints()
    test_specific_company()
    print("\n=== Test completed ===")