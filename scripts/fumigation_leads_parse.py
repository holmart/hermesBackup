#!/usr/bin/env python3
import sys
import re

def extract_links_from_bing(html):
    # Find all <a> tags with href starting with http
    # Simple regex: <a[^>]*href="([^"]+)"[^>]*>([^<]*)</a>
    pattern = r'<a[^>]*href="(https?://[^"]+)"[^>]*>([^<]*)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE)
    for url, text in matches:
        if 'bing.com' not in url and not url.startswith('javascript:'):
            # Clean text: replace newlines and multiple spaces
            text = re.sub(r'\s+', ' ', text.strip())
            if text:
                yield url, text
            else:
                yield url, url

if __name__ == '__main__':
    data = sys.stdin.read()
    for url, title in extract_links_from_bing(data):
        print(f'{url}|{title}')