#!/usr/bin/env python3
"""Tell search engines that pages changed (IndexNow: Bing, Yandex, Naver, Seznam; Bing feeds ChatGPT search).

Reads site/sitemap.xml and posts every URL to the IndexNow endpoint with the site's key, which is served from the
site root as <key>.txt. Run after each deploy. Google does not take IndexNow; it reads the sitemap it was given in
Search Console.
"""
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = 'ecd3cb0c19bb9e8f175edefc49f69dc1'
HOST = 'etfiq.com'


def main():
    sm = (ROOT / 'site' / 'sitemap.xml').read_text()
    urls = re.findall(r'<loc>([^<]+)</loc>', sm)
    if not urls:
        sys.exit('no urls in sitemap')
    body = json.dumps({'host': HOST, 'key': KEY, 'keyLocation': f'https://{HOST}/{KEY}.txt', 'urlList': urls[:10000]}).encode()
    req = urllib.request.Request('https://api.indexnow.org/indexnow', data=body, headers={'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'ETFIQ data pipeline'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f'indexnow: {r.status} for {len(urls)} urls')
    except urllib.error.HTTPError as e:
        print(f'indexnow: HTTP {e.code} {e.read()[:200]!r}')
        sys.exit(1)


if __name__ == '__main__':
    main()
