import subprocess
import re
from urllib.parse import quote_plus, urlparse

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

query = "empresa de control de plagas Colombia"
search_url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=es&cc=CO"
print(f"Fetching: {search_url}")
html = fetch(search_url)
print(f"HTML length: {len(html)}")

# Look for <a> tags
# Pattern: <a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>
a_pattern = r'<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>'
a_matches = re.findall(a_pattern, html, re.IGNORECASE)
print(f"Found {len(a_matches)} <a> tags with href")
# Let's see first 20
for i, href in enumerate(a_matches[:20]):
    print(f"{i:2}: {href}")

# Now filter to http(s) and not bing.com, not javascript
http_links = []
for href in a_matches:
    if not href.startswith('http'):
        continue
    if 'bing.com' in href:
        continue
    if href.startswith('javascript:'):
        continue
    http_links.append(href)
print(f"\nAfter filtering bing.com and javascript: {len(http_links)} links")
for i, href in enumerate(http_links[:20]):
    print(f"{i:2}: {href}")

# Look for common result containers: <li class="b_algo">, <ol id="b_results">, etc.
# Let's extract the section between <ol id="b_results"> and </ol> maybe
# But we can also look for <h2> tags that are inside results
# Let's try to find all <h2> and see if they have a link
h2_pattern = r'<h2[^>]*>(.*?)</h2>'
h2_matches = re.findall(h2_pattern, html, re.IGNORECASE | re.DOTALL)
print(f"\nFound {len(h2_matches)} <h2> tags")
for i, h2 in enumerate(h2_matches[:10]):
    # Clean up tags inside
    clean = re.sub(r'<[^>]+>', '', h2)
    print(f"{i:2}: {clean.strip()[:80]}")

# Now look for <h2><a href=...>
h2_a_pattern = r'<h2[^>]*>.*?<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>.*?</a>.*?</h2>'
h2_a_matches = re.findall(h2_a_pattern, html, re.IGNORECASE | re.DOTALL)
print(f"\nFound {len(h2_a_matches)} <h2><a> links")
for i, href in enumerate(h2_a_matches[:10]):
    print(f"{i:2}: {href}")

# Also look for <cite> tags which sometimes show the URL
cite_pattern = r'<cite[^>]*>([^<]+)</cite>'
cite_matches = re.findall(cite_pattern, html, re.IGNORECASE)
print(f"\nFound {len(cite_matches)} <cite> tags")
for i, cite in enumerate(cite_matches[:10]):
    print(f"{i:2}: {cite}")

# Let's also look for the main results area by trying to find the id="b_results"
# Extract everything between <ol id="b_results"> and the next </ol> (non-greedy)
b_results_pattern = r'<ol[^>]*id=[\'"]b_results[\'"][^>]*>(.*?)</ol>'
b_results_match = re.search(b_results_pattern, html, re.IGNORECASE | re.DOTALL)
if b_results_match:
    b_results_content = b_results_match.group(1)
    print(f"\nFound b_results content length: {len(b_results_content)}")
    # Now extract links from this content
    links_in_results = re.findall(r'<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>', b_results_content, re.IGNORECASE)
    print(f"Links in b_results: {len(links_in_results)}")
    for i, href in enumerate(links_in_results[:10]):
        print(f"{i:2}: {href}")
else:
    print("\nCould not find <ol id='b_results'>")

# Let's also try to find <li class="b_algo">
b_algo_pattern = r'<li[^>]*class=[\'"]b_algo[\'"][^>]*>(.*?)</li>'
b_algo_matches = re.findall(b_algo_pattern, html, re.IGNORECASE | re.DOTALL)
print(f"\nFound {len(b_algo_matches)} <li class='b_algo'> items")
for i, item in enumerate(b_algo_matches[:5]):
    # Extract href from inside
    link_match = re.search(r'<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>', item, re.IGNORECASE)
    if link_match:
        print(f"{i:2}: {link_match.group(1)}")
    else:
        # Maybe the link is in an h2
        h2_match = re.search(r'<h2[^>]*>.*?<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>.*?</a>.*?</h2>', item, re.IGNORECASE | re.DOTALL)
        if h2_match:
            print(f"{i:2}: {h2_match.group(1)} (via h2)")
        else:
            print(f"{i:2}: No link found")