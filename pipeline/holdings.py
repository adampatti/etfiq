#!/usr/bin/env python3
"""Holdings for the themes desk, and the overlap engine.

Fund holdings come from SEC Form N-PORT (public for the last month of each quarter, roughly sixty days after the
period end). For a fund's SEC series id, EDGAR full-text search finds its latest NPORT-P filing; the filing's
primary_doc.xml lists every position with name, CUSIP, ISIN, ticker and percent of net assets.

Index holdings come from the index funds' own daily files: IVV for the S&P 500 (iShares CSV) and QQQ for the
Nasdaq-100 (Invesco CSV). If a daily file cannot be read, the index fund's own N-PORT is used instead.

Overlap between two holdings lists keyed by security: weight overlap = sum of the minimum weights across matched
securities; active share = 1 minus that. "In-index weight" = the fund's weight in securities the index holds at all.
Securities match on CUSIP first, then ticker, then a normalised name.

Everything is cached per day in pipeline/cache/holdings/. Set ETFIQ_CONTACT for the SEC user agent.
"""
import csv
import datetime
import io
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
CACHE = ROOT / 'pipeline' / 'cache' / 'holdings'
CONTACT = os.environ.get('ETFIQ_CONTACT') or 'data@etfiq.com'
UA = f'ETFIQ data pipeline {CONTACT}'
BROWSER = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'


def get(url, headers=None, timeout=60):
    h = {'User-Agent': UA, 'Accept': '*/*'}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def sec_get(url, params=None):
    if params:
        url = url + ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            body = get(url).decode('utf-8', errors='replace')
            time.sleep(0.12)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def latest_nport(series_id):
    """URL of the latest NPORT-P primary document for an SEC series id, or None."""
    p = CACHE / f'nport-index-{series_id}-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    out = None
    try:
        d = json.loads(sec_get('https://efts.sec.gov/LATEST/search-index', {'q': f'"{series_id}"', 'forms': 'NPORT-P', 'dateRange': 'custom',
                                                                                'startdt': (TODAY - datetime.timedelta(days=400)).isoformat(), 'enddt': TODAY.isoformat()}))
        hits = d.get('hits', {}).get('hits', [])
        hits.sort(key=lambda h: h['_source'].get('period_ending') or h['_source'].get('file_date') or '', reverse=True)
        for h in hits:
            src = h['_source']
            acc, fn = h['_id'].split(':')
            c = str(int(src['ciks'][0]))
            out = {'url': f"https://www.sec.gov/Archives/edgar/data/{c}/{acc.replace('-', '')}/{fn}", 'filed': src.get('file_date'), 'period': src.get('period_ending')}
            break
    except Exception as e:
        print(f'  nport search {series_id}: {str(e)[:80]}', file=sys.stderr)
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def parse_nport(xml_text):
    """Holdings and fund facts from an N-PORT primary document."""
    root = ET.fromstring(xml_text)
    ns = {'n': root.tag.split('}')[0].strip('{')} if root.tag.startswith('{') else {}
    def find(el, path):
        return el.find(path, ns) if ns else el.find(path.replace('n:', ''))
    def findall(el, path):
        return el.findall(path, ns) if ns else el.findall(path.replace('n:', ''))
    def txt(el, path):
        x = find(el, path)
        return (x.text or '').strip() if x is not None else ''
    gen = find(root, './/n:genInfo')
    fund = find(root, './/n:fundInfo')
    info = {'seriesId': txt(gen, 'n:seriesId') if gen is not None else '', 'regName': txt(gen, 'n:regName') if gen is not None else '',
            'seriesName': txt(gen, 'n:seriesName') if gen is not None else '', 'period': txt(gen, 'n:repPdDate') if gen is not None else '',
            'netAssets': float(txt(fund, 'n:netAssets') or 0) if fund is not None else None}
    holdings = []
    for sec in findall(root, './/n:invstOrSec'):
        name = txt(sec, 'n:name') or txt(sec, 'n:title')
        cusip = txt(sec, 'n:cusip')
        ticker, isin = '', ''
        ids = find(sec, 'n:identifiers')
        if ids is not None:
            for child in list(ids):
                tag = child.tag.split('}')[-1]
                if tag == 'ticker':
                    ticker = (child.get('value') or '').strip().upper()
                elif tag == 'isin':
                    isin = (child.get('value') or '').strip().upper()
        try:
            pct = float(txt(sec, 'n:pctVal') or 0)
        except ValueError:
            pct = 0.0
        cat = txt(sec, 'n:assetCat')
        if cat in ('STIV', 'RA', 'DFE', 'DFX', 'DIR', 'DE', 'DCO'):  # cash equivalents, repos, derivatives
            continue
        if pct <= 0 or not name:
            continue
        holdings.append({'name': name, 'cusip': cusip if re.fullmatch(r'[0-9A-Z]{9}', cusip or '') else '', 'isin': isin, 'ticker': ticker, 'weight': pct, 'cat': cat, 'country': txt(sec, 'n:invCountry')})
    holdings.sort(key=lambda h: -h['weight'])
    return info, holdings


def fund_holdings(series_id):
    """Latest N-PORT holdings for a series id, cached per day. Returns (info, holdings) or (None, [])."""
    p = CACHE / f'nport-{series_id}-{TODAY.isoformat()}.json'
    if p.exists():
        d = json.loads(p.read_text())
        return d.get('info'), d.get('holdings', [])
    idx = latest_nport(series_id)
    info, holdings = None, []
    if idx and idx.get('url'):
        try:
            info, holdings = parse_nport(sec_get(idx['url']))
            info['filed'] = idx.get('filed')
            info['source'] = idx['url']
        except Exception as e:
            print(f'  nport fetch {series_id}: {str(e)[:80]}', file=sys.stderr)
            return None, []
    if not holdings:
        return info, holdings  # never cache an empty answer; the next run retries
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'info': info, 'holdings': holdings}))
    return info, holdings


def index_holdings(which):
    """Holdings standing in for an index, from the index fund's own N-PORT: IVV for the S&P 500, QQQM for the
    Nasdaq-100. Quarterly and lagged like every N-PORT, which is fine for an index whose weights move slowly; the
    as-of date travels with the data. Cached per day."""
    p = CACHE / f'index-{which}-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    series = {'SPY': 'S000004310', 'QQQ': 'S000069448'}
    info, h = fund_holdings(series[which])
    rows = [{'name': x['name'], 'cusip': x['cusip'], 'isin': x['isin'], 'ticker': x['ticker'], 'weight': x['weight']} for x in h]
    rows.sort(key=lambda r: -r['weight'])
    out = {'asOf': (info or {}).get('period'), 'source': (info or {}).get('source'), 'holdings': rows}
    if len(rows) >= 50:
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out))
    return out


def norm_name(n):
    n = re.sub(r'[^a-z0-9 ]', ' ', (n or '').lower())
    n = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|sa|ag|nv|se|class [abc]|cl [abc]|common|stock|shares?|ordinary|adr|holdings?|group|the|reg|registered)\b', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def keyset(h):
    keys = set()
    if h.get('cusip'):
        keys.add('c:' + h['cusip'])
    if h.get('isin'):
        keys.add('i:' + h['isin'])
        if len(h['isin']) == 12 and h['isin'].startswith('US'):
            keys.add('c:' + h['isin'][2:11])
    if h.get('ticker'):
        keys.add('t:' + re.sub(r'[^A-Z]', '', h['ticker']))
    n = norm_name(h.get('name'))
    if n:
        keys.add('n:' + n)
    return keys


def match(a, b):
    """Pair holdings of a with holdings of b. Returns list of (weight_a, weight_b) for matched, and the matched a-indexes."""
    index = {}
    for j, h in enumerate(b):
        for k in keyset(h):
            index.setdefault(k, j)
    pairs, used_b, matched_a = [], set(), set()
    for i, h in enumerate(a):
        for k in sorted(keyset(h), key=lambda k: {'c': 0, 'i': 1, 't': 2, 'n': 3}[k[0]]):
            j = index.get(k)
            if j is not None and j not in used_b:
                pairs.append((h['weight'], b[j]['weight']))
                used_b.add(j)
                matched_a.add(i)
                break
    return pairs, matched_a


def overlap(a, b):
    """Weight overlap, active share and in-b weight of a, all in percent of a's total equity weight."""
    ta = sum(h['weight'] for h in a) or 1.0
    tb = sum(h['weight'] for h in b) or 1.0
    pairs, matched = match(a, b)
    common = sum(min(wa / ta, wb / tb) for wa, wb in pairs) * 100
    in_b = sum(a[i]['weight'] for i in matched) / ta * 100
    return {'overlap': round(common, 1), 'activeShare': round(100 - common, 1), 'inIndex': round(in_b, 1), 'matched': len(pairs)}


if __name__ == '__main__':
    sid = sys.argv[1] if len(sys.argv) > 1 else 'S000027517'
    info, h = fund_holdings(sid)
    print(json.dumps(info, indent=1))
    for x in h[:10]:
        print(x)
    spy = index_holdings('SPY')
    print('SPY holdings', len(spy['holdings']), 'as of', spy['asOf'], spy['holdings'][:2])
    print('overlap vs SPY', overlap(h, spy['holdings']))
