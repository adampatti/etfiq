#!/usr/bin/env python3
"""SEC EDGAR helpers for ETFIQ: the terms table and the history.

Every defined outcome ETF files a 497K summary prospectus at each outcome period reset stating the period dates,
the cap gross and net of fees, and the buffer range. EDGAR keeps every one of those filings since each fund's
inception, so the full history of terms can be rebuilt from here at no cost. Verified 2026-09-04: the full-text
search returned 51 such filings for August 2026 from First Trust Exchange-Traded Fund VIII (CIK 1667919),
PGIM Rock ETF Trust (CIK 1992104) and Innovator ETFs Trust (CIK 1415726).

The SEC asks for a user agent naming the requester. Set ETFIQ_CONTACT to an email address; this module refuses to
run without one so that nobody hits EDGAR anonymously by accident.

Usage:
  python pipeline/edgar.py search --cik 1415726 --start 2026-08-01 --end 2026-09-04
  python pipeline/edgar.py terms https://www.sec.gov/Archives/edgar/data/1415726/000121390026095914/ea0303285-01_497k.htm
  python pipeline/edgar.py universe            # buffer-like series with tickers from the SEC series/class file
"""
import csv
import datetime
import html
import io
import json
import os
import re
import sys
import time

import urllib.parse
import urllib.request

CONTACT = os.environ.get('ETFIQ_CONTACT')
UA = f'ETFIQ-research/0.1 {CONTACT}' if CONTACT else 'ETFIQ-research/0.1'

TRUSTS = {  # registrants that file buffer ETFs, from the 2026 SEC series/class file
    '1415726': 'Innovator ETFs Trust', '1667919': 'First Trust Exchange-Traded Fund VIII', '1797318': 'AIM ETF Products Trust (AllianzIM)',
    '1992104': 'PGIM Rock ETF Trust', '1683471': 'Listed Funds Trust (TrueShares)', '1804196': 'BlackRock ETF Trust II (iShares)',
}


def require_contact():
    if not CONTACT:
        sys.exit('Set ETFIQ_CONTACT=you@example.com before reading EDGAR; the SEC requires a contact in the user agent.')


def get(url, params=None):
    if params:
        url = url + ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'}), timeout=60) as r:
        body = r.read().decode(r.headers.get_content_charset() or 'utf-8', errors='replace')
    time.sleep(0.15)  # the SEC allows ten calls a second; stay well under
    return body


def search(query='"Outcome Period" "Cap"', cik=None, forms='497K', start='2001-01-01', end=None, page_size=100):
    """Full-text search hits, newest first. Each hit carries the filing URL."""
    require_contact()
    end = end or datetime.date.today().isoformat()
    out, frm = [], 0
    while True:
        params = {'q': query, 'forms': forms, 'dateRange': 'custom', 'startdt': start, 'enddt': end, 'from': frm}
        if cik:
            params['ciks'] = str(cik).zfill(10)
        d = json.loads(get('https://efts.sec.gov/LATEST/search-index', params=params))
        hits = d.get('hits', {}).get('hits', [])
        for h in hits:
            src = h['_source']
            acc, fn = h['_id'].split(':')
            c = str(int(src['ciks'][0]))
            out.append({'cik': c, 'entity': src.get('display_names', [''])[0], 'date': src.get('file_date'), 'form': src.get('form'),
                        'url': f"https://www.sec.gov/Archives/edgar/data/{c}/{acc.replace('-', '')}/{fn}"})
        if len(hits) < page_size:
            break
        frm += len(hits)
    return out


def text(s):
    s = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', s, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s)))


def terms(url):
    """Parse the outcome-period terms out of a 497K. Patterns cover Innovator and FT Vest phrasing; extend per issuer."""
    require_contact()
    t = text(get(url))
    g = lambda pat: (re.search(pat, t, re.I) or [None])
    out = {'url': url}
    m = re.search(r'Outcome Period is from ([A-Z][a-z]+ \d{1,2}, \d{4}) (?:through|to) ([A-Z][a-z]+ \d{1,2}, \d{4})', t)
    if not m:
        m = re.search(r'over the period from ([A-Z][a-z]+ \d{1,2}, \d{4}) (?:through|to) ([A-Z][a-z]+ \d{1,2}, \d{4})', t)
    if m:
        out['periodStart'], out['periodEnd'] = [datetime.datetime.strptime(x, '%B %d, %Y').date().isoformat() for x in m.groups()]
    m = re.search(r'Cap is set on the first day of the Outcome Period and is ([\d.]+) ?%', t) or re.search(r'upside cap of ([\d.]+) ?%', t)
    if m:
        out['capGross'] = float(m.group(1))
    m = re.search(r'management fee of ([\d.]+)%[^.]{0,120}?the Cap is ([\d.]+) ?%', t)
    if m:
        out['fee'], out['capNet'] = float(m.group(1)), float(m.group(2))
    m = re.search(r'losses between (-?\d+(?:\.\d+)?)% and (-?\d+(?:\.\d+)?)%', t)
    if m:
        out['bufferStart'], out['bufferEnd'] = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(r'Buffer for (?:the|an) Outcome Period is ([\d.]+) ?%', t) or re.search(r'first ([\d.]+) ?% of (?:Underlying ETF )?losses', t)
        if m:
            out['bufferStart'], out['bufferEnd'] = 0.0, -float(m.group(1))
    m = re.search(r'\b([A-Z]{3,5})\b[^.]{0,40}Cboe BZX', t) or re.search(r'Ticker(?: Symbol)?:?\s*([A-Z]{3,5})\b', t)
    if m:
        out['ticker'] = m.group(1)
    m = re.search(r'(Innovator|FT Vest|AllianzIM|PGIM|TrueShares|Calamos|iShares)[^.]{0,80}?ETF[^.]{0,40}?(?:- [A-Z][a-z]+)?', t)
    if m:
        out['nameGuess'] = m.group(0)[:120]
    return out


def universe(year=None):
    """Buffer-like series with tickers from the SEC investment company series/class file."""
    require_contact()
    year = year or datetime.date.today().year
    url = f'https://www.sec.gov/files/investment/data/other/investment-company-series-class-information/investment-company-series-class-{year}.csv'
    raw = get(url)
    rd = csv.DictReader(io.StringIO(raw.lstrip('﻿')))
    pat = re.compile(r'buffer|defined outcome|target outcome|structured outcome|structured protection|defined protection|max buffer|floor|defined wealth|outcome', re.I)
    rows = []
    for x in rd:
        name, tk = x.get('Series Name') or '', (x.get('Class Ticker') or '').strip()
        if tk and pat.search(name):
            rows.append({'cik': str(int(x['CIK Number'])), 'entity': x['Entity Name'], 'seriesId': x['Series ID'], 'series': name, 'ticker': tk})
    return rows


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('search'); p.add_argument('--cik'); p.add_argument('--start', default='2001-01-01'); p.add_argument('--end'); p.add_argument('--query', default='"Outcome Period" "Cap"')
    p = sub.add_parser('terms'); p.add_argument('url')
    p = sub.add_parser('universe'); p.add_argument('--year', type=int)
    a = ap.parse_args()
    if a.cmd == 'search':
        print(json.dumps(search(a.query, a.cik, start=a.start, end=a.end), indent=1))
    elif a.cmd == 'terms':
        print(json.dumps(terms(a.url), indent=1))
    else:
        print(json.dumps(universe(a.year), indent=1))
