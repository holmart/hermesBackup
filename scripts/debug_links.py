import subprocess
import re
from urllib.parse import quote_plus, urlparse

# Copy the relevant functions from the script
def build_curl(url, cookie_file=None, referer=None, ua=None):
    cmd = ["curl", "-s", "-L", "--max-time", "15", "--compressed"]
    if ua:
        cmd.extend(["-A", ua])
    else:
        # We'll hardcode a UA for simplicity
        cmd.extend(["-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"])
    cmd.extend(["-H", "accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"])
    cmd.extend(["-H", "accept-language: es-ES,es;q=0.9,en;q=0.8"])
    cmd.extend(["-H", "cache-control: no-cache"])
    cmd.extend(["-H", "upgrade-insecure-requests: 1"])
    if cookie_file:
        cmd.extend(["--cookie", cookie_file, "--cookie-jar", cookie_file])
    if referer:
        cmd.extend(["-e", referer])
    cmd.append(url)
    return cmd

def fetch(url, max_attempts=3, cookie_file=None, referer=None):
    for attempt in range(1, max_attempts + 1):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        cmd = build_curl(url, cookie_file, referer, ua)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            if attempt == max_attempts:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url} after {max_attempts} attempts")

def extract_links_bing(html):
    links = []
    algo_pattern = r'<li[^>]*class=[\'"]b_algo[\'"][^>]*>.*?<h2[^>]*>.*?<a[^>]*href=[\'"]([^\'"]+)[\'"]'
    matches = re.findall(algo_pattern, html, re.IGNORECASE | re.DOTALL)
    for url in matches:
        if url.startswith('http'):
            links.append(url)
    if len(links) < 3:
        pattern = r'href=[\'"](https?://[^\'">]+)[\'"]'
        matches = re.findall(pattern, html, re.IGNORECASE)
        for url in matches:
            if not url.startswith('http'):
                continue
            if 'bing.com' in url:
                continue
            if url.startswith('javascript:'):
                continue
            links.append(url)
    seen = set()
    uniq = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

BLOCKED_DOMAINS = {
    'bing.com', 'microsoft.com', 'support.microsoft.com', 'reddit.com', 'ebay.com', 
    'wikipedia.org', 'youtube.com', 'facebook.com', 'twitter.com', 'instagram.com',
    'linkedin.com', 'amazon.com', 'mercadolibre.com', 'olx.com', 'eltres.com',
    'semana.com', 'eltiempo.com', 'publimetro.co', 'caracol.com.co', 'rcn.com.co',
    'google.com', 'googlesyndication.com', 'doubleclick.net',
}

COLOMBIAN_TLDS = ['.co', '.com.co', '.org.co', '.net.co', '.edu.co', '.gov.co', '.mil.co', '.arts.co', '.firm.co', '.info.co', '.int.co', '.nom.co', '.rec.co', '.store.co', '.web.co']

def is_relevant_url(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        if any(blocked in domain for blocked in BLOCKED_DOMAINS):
            return False
        for tld in COLOMBIAN_TLDS:
            if domain.endswith(tld):
                return True
        return False
    except Exception:
        return False

# Test with one query
query = "empresa de control de plagas Colombia"
search_url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=es&cc=CO"
print(f"Fetching: {search_url}")
html = fetch(search_url)
print(f"HTML length: {len(html)}")
links = extract_links_bing(html)
print(f"Found {len(links)} raw links")
for i, link in links[:10]:
    print(f"  {i}: {link}")
relevant = [link for link in links if is_relevant_url(link)]
print(f"Relevant Colombian links: {len(relevant)}")
for i, link in relevant[:10]:
    print(f"  {i}: {link}")
# Let's also print the domain of each link to see what we are getting
print("\nDomain analysis:")
for link in links[:20]:
    try:
        domain = urlparse(link).netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        relevant_flag = is_relevant_url(link)
        print(f"  {domain} -> {'RELEVANT' if relevant_flag else 'BLOCKED'}")
    except Exception as e:
        print(f"  {link} -> ERROR: {e}")