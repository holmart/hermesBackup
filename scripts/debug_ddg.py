import subprocess
import re
from urllib.parse import quote_plus

ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
query = "empresa de control de plagas Colombia"
url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=es-es"

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

# Look for result links in DuckDuckGo html
# Pattern: <a class="result__url" href="URL">
pattern1 = r'<a[^>]*class=[\'"]result__url[\'"][^>]*href=[\'"]([^\'"]+)[\'"]'
matches1 = re.findall(pattern1, html, re.IGNORECASE)
print(f"Pattern 1 (result__url): {len(matches1)} matches")
for m in matches1[:3]:
    print(f"  {m}")

# Pattern: <a class="result__snippet" href="URL">
pattern2 = r'<a[^>]*class=[\'"]result__snippet[\'"][^>]*href=[\'"]([^\'"]+)[\'"]'
matches2 = re.findall(pattern2, html, re.IGNORECASE)
print(f"Pattern 2 (result__snippet): {len(matches2)} matches")
for m in matches2[:3]:
    print(f"  {m}")

# Pattern: Look for any https links that aren't to duckduckgo.com or static assets
pattern3 = r'href=[\'"](https?://[^\'">]+)[\'"]'
matches3 = re.findall(pattern3, html, re.IGNORECASE)
print(f"Pattern 3 (all http links): {len(matches3)} matches")
count = 0
for m in matches3:
    if 'duckduckgo.com' not in m and not m.endswith(('.png', '.jpg', '.css', '.js', '.woff', '.woff2', '.svg', '.ico')) and not m.startswith('//duckduckgo'):
        print(f"  {m}")
        count += 1
        if count >= 5:
            break

# Save a snippet for inspection
with open('/tmp/ddg_sample.html', 'w') as f:
    f.write(html[:5000])
print("\\nSaved first 5000 chars to /tmp/ddg_sample.html")