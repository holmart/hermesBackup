#!/usr/bin/env python3
import subprocess, re, csv, os, time, random
from urllib.parse import quote_plus

LEADS_DIR = "/home/ubuntu/.hermes/leads"
LEADS_FILE = os.path.join(LEADS_DIR, "fumigation_leads.csv")
QUERIES = ["empresa fumigacion Colombia"]
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"]
COMMON_HEADERS = [
    "accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language: es-ES,es;q=0.9,en;q=0.8",
    "cache-control: no-cache",
    "upgrade-insecure-requests: 1",
]

def build_curl(url, cookie_file=None, referer=None, ua=None):
    cmd = ["curl", "-s", "-L", "--max-time", "15", "--compressed"]
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
    for attempt in range(1, max_attempts + 1):
        ua = random.choice(USER_AGENTS)
        cmd = build_curl(url, cookie_file, referer, ua)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            html = result.stdout
            lowered = html.lower()
            if any(txt in lowered for txt in ["please complete the following challenge", "solving this captcha", "unusual traffic", "are you a robot", "verify you are a human", "¿eres un robot?", "please enable javascript", "access denied", "bot detection"]):
                wait = min(2 ** attempt, 10) + random.uniform(0, 1)
                print(f"  Attempt {attempt}: bot challenge, waiting {wait:.1f}s")
                time.sleep(wait)
                continue
            return html
        except subprocess.CalledProcessError as e:
            wait = min(2 ** attempt, 10) + random.uniform(0, 1)
            print(f"  Attempt {attempt}: curl failed ({e}), retrying in {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url}")

def extract_links_duckduckgo(html):
    links = []
    pat = r'<a[^>]*class=[\'"][^\'"]*result__[^\'"]*[\'"][^>]*href=[\'"]?([^\'\" >]+)[\'"]?[^>]*>[^<]*</a>'
    matches = re.findall(pat, html, re.IGNORECASE)
    for url in matches:
        if url.startswith('http') and 'duckduckgo.com' not in url and not url.startswith('javascript:'):
            links.append(url)
    # dedupe
    seen = set()
    uniq = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

def main():
    os.makedirs(LEADS_DIR, exist_ok=True)
    cookie_file = os.path.join(LEADS_DIR, "cookies.txt")
    open(cookie_file, 'a').close()
    print("Testing DuckDuckGo...")
    query = QUERIES[0]
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}&kl=es-es"
    try:
        html = fetch(url, cookie_file=cookie_file, referer=url)
        print(f"Fetched length: {len(html)}")
        links = extract_links_duckduckgo(html)
        print(f"Links found: {len(links)}")
        for l in links[:5]:
            print(l)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()