import subprocess
import re
from urllib.parse import quote_plus

ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
query = "empresa de control de plagas Colombia"
url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=es&cc=CO"

cmd = [
    "curl", "-s", "-L", "--max-time", "15",
    "-A", ua,
    "-H", "accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "-H", "accept-language: es-ES,es;q=0.9,en;q=0.8",
    "-H", "cache-control: no-cache",
    "-H", "upgrade-insecure-requests: 1",
    url
]

result = subprocess.run(cmd, capture_output=True, text=True)
html = result.stdout

print(f"HTML length: {len(html)}")

# Save a snippet for inspection
with open('/tmp/bing_sample.html', 'w') as f:
    f.write(html[:10000])
print("Saved first 10000 chars to /tmp/bing_sample.html")

# Look for common patterns in Bing results
# Pattern 1: <h2><a href="URL"> (often in b_algo)
pattern1 = r'<h2[^>]*>.*?<a[^>]*href=[\'"]([^\'"]+)[\'"]'
matches1 = re.findall(pattern1, html, re.IGNORECASE | re.DOTALL)
print(f"Pattern 1 (h2 > a href): {len(matches1)} matches")
for m in matches1[:5]:
    print(f"  {m}")

# Pattern 2: <li class="b_algo"><h2><a href="URL">
pattern2 = r'<li[^>]*class=[\'"]b_algo[\'"][^>]*>.*?<h2[^>]*>.*?<a[^>]*href=[\'"]([^\'"]+)[\'"]'
matches2 = re.findall(pattern2, html, re.IGNORECASE | re.DOTALL)
print(f"Pattern 2 (b_algo > h2 > a href): {len(matches2)} matches")
for m in matches2[:5]:
    print(f"  {m}")

# Pattern 3: cite URL (sometimes shown)
pattern3 = r'<cite[^>]*>([^<]+)</cite>'
matches3 = re.findall(pattern3, html, re.IGNORECASE)
print(f"Pattern 3 (cite): {len(matches3)} matches")
for m in matches3[:5]:
    print(f"  {m}")

# Let's also look for any https link that doesn't point to bing.com or known non-result domains
pattern4 = r'href=[\'"](https?://[^\'">]+)[\'"]'
matches4 = re.findall(pattern4, html, re.IGNORECASE)
print(f"Pattern 4 (all http links): {len(matches4)} matches")
count = 0
for m in matches4:
    if 'bing.com' not in m and not m.startswith('javascript:') and not m.endswith(('.png', '.jpg', '.css', '.js', '.woff', '.woff2', '.svg', '.ico')):
        # Also avoid known social media and document sites if we want, but let's see
        print(f"  {m}")
        count += 1
        if count >= 10:
            break