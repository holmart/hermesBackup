import subprocess
import re
from urllib.parse import quote_plus, urlparse

# Simple fetch function
def fetch(url):
    cmd = [
        "curl", "-s", "-L", "--max-time", "15",
        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "-H", "accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "-H", "accept-language: es-ES,es;q=0.9,en;q=0.8",
        "-H", "cache-control: no-cache",
        "-H", "upgrade-insecure-requests: 1",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

# Test with one query
query = "empresa de control de plagas Colombia"
search_url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=es&cc=CO"
print(f"Fetching: {search_url}")
html = fetch(search_url)
print(f"HTML length: {len(html)}")

# Extract all href attributes
# Pattern: href="..." or href='...'
pattern = r'href=[\'"]([^\'"]+)[\'"]'
matches = re.findall(pattern, html, re.IGNORECASE)
print(f"Found {len(matches)} raw href matches")

# Let's look at the first 20 matches
for i, m in enumerate(matches[:20]):
    print(f"{i:2}: {m}")

# Now filter to only http(s) links
http_links = [m for m in matches if m.startswith('http')]
print(f"\nFound {len(http_links)} http(s) links")

# Look at first 20 http links
for i, link in enumerate(http_links[:20]):
    print(f"{i:2}: {link}")

# Now filter out bing.com and javascript
filtered = []
for link in http_links:
    if 'bing.com' in link:
        continue
    if link.startswith('javascript:'):
        continue
    filtered.append(link)
print(f"\nAfter removing bing.com and javascript: {len(filtered)} links")

# Look at first 20 filtered
for i, link in enumerate(filtered[:20]):
    print(f"{i:2}: {link}")

# Now check for Colombian TLDs
COLOMBIAN_TLDS = ['.co', '.com.co', '.org.co', '.net.co', '.edu.co', '.gov.co', '.mil.co', '.arts.co', '.firm.co', '.info.co', '.int.co', '.nom.co', '.rec.co', '.store.co', '.web.co']
colombian = []
for link in filtered:
    try:
        parsed = urlparse(link)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        for tld in COLOMBIAN_TLDS:
            if domain.endswith(tld):
                colombian.append(link)
                break
    except Exception:
        pass
print(f"\nColombian TLD links: {len(colombian)}")
for i, link in enumerate(colombian[:10]):
    print(f"{i:2}: {link}")

# If still empty, let's see what domains we are getting from the filtered links
print("\nSample domains from filtered links:")
domains_seen = set()
for link in filtered[:50]:
    try:
        parsed = urlparse(link)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        domains_seen.add(domain)
    except Exception:
        pass
for domain in list(domains_seen)[:20]:
    print(f"  {domain}")