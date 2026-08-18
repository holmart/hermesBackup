#!/usr/bin/env python3
import subprocess, re, time, random
from urllib.parse import quote_plus

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

COMMON_HEADERS = [
    "accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language: es-ES,es;q=0.9,en;q=0.8",
    "cache-control: no-cache",
    "upgrade-insecure-requests: 1",
]

def build_curl(url, cookie_file=None, referer=None, ua=None):
    cmd = ["curl", "-s", "-L", "--max-time", "12", "--compressed"]
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
            ]):
                wait = min(2 ** attempt, 10) + random.uniform(0, 2)
                print(f"  Attempt {attempt}: bot challenge, waiting {wait:.1f}s")
                time.sleep(wait)
                continue
            return html
        except subprocess.CalledProcessError as e:
            wait = min(2 ** attempt, 10) + random.uniform(0, 2)
            print(f"  Attempt {attempt}: curl failed ({e}), retrying in {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url}")

def extract_links_generic(html, engine):
    links = []
    if engine == "bing":
        patterns = [
            r'<li[^>]*class=[\'"]b_algo[\'"][^>]*><h2[^>]*><a[^>]*href=[\'"]?([^\'\" >]+)[\'"]?[^>]*>[^<]*</a></h2>',
            r'<a[^>]*class=[\'"]title[\'"][^>]*href=[\'"]?([^\'\" >]+)[\'"]?[^>]*>[^<]*</a>',
        ]
    elif engine == "yahoo":
        patterns = [
            r'<h3[^>]*class=[\'"]title[\'"][^>]*><a[^>]*href=[\'"]?([^\'\" >]+)[\'"]?[^>]*>[^<]*</a></h3>',
            r'<a[^>]*class=[\'"]td-u[\'"][^>]*href=[\'"]?([^\'\" >]+)[\'"]?[^>]*>[^<]*</a>',
        ]
    else:
        return []
    for pat in patterns:
        matches = re.findall(pat, html, re.IGNORECASE)
        for url in matches:
            if not url.startswith('http'):
                continue
            if engine == "bing" and 'bing.com' in url:
                continue
            if engine == "yahoo" and ('yahoo.com' in url or 'yimg.com' in url):
                continue
            if url.startswith('javascript:'):
                continue
            links.append(url)
        if links:
            break
    seen = set()
    uniq = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

def test_engine(name, url_builder, extractor):
    print(f"\n=== Testing {name} ===")
    query = "control de plagas Colombia"
    url = url_builder(query)
    try:
        html = fetch(url)
        print(f"Fetched length: {len(html)}")
        links = extractor(html)
        print(f"Found {len(links)} links")
        for i, l in enumerate(links[:5], 1):
            print(f"  {i}. {l}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_engine("Bing",
                lambda q: f"https://www.bing.com/search?q={quote_plus(q)}&setlang=es-co",
                lambda html: extract_links_generic(html, "bing"))
    test_engine("Yahoo",
                lambda q: f"https://search.yahoo.com/search?p={quote_plus(q)}&fr=yset_ie_syc_origo&type=E210COar",
                lambda html: extract_links_generic(html, "yahoo"))