#!/usr/bin/env python3
"""Where the cash came from: issuers' 19a-1 estimates of the sources of each distribution.

Under Rule 19a-1 an issuer that pays out more than its net investment income must tell holders, with each
distribution, how much of it is estimated to be net investment income, realised gains, and return of capital.
The estimates are on a book basis and change at the year-end 1099, and a high return-of-capital share is a tax
characterisation, not by itself a sign that principal is being eroded (the price column measures that).

Sources, one parser per issuer:
  YieldMax    the fund page's distribution table carries a ROC percent for every distribution.
  Global X    the fund page links the latest Form 19a notice as a .docx with current and fiscal-year-to-date sources.
  NEOS        the fund page's 19a-1 tab links a PDF per distribution with the estimated ROC share.
  Defiance    a notices page links a PDF per fund per distribution.

Output site/data/sources.json: ticker -> {issuer, asOf, latest {date, amount, roc, income, gains}, ytd {roc, income, gains},
t12 {roc, n}, url, method}. Percentages are of the distribution. Cached per day in pipeline/cache/sources/.
"""
import datetime
import html as htmlmod
import io
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
CACHE = ROOT / 'pipeline' / 'cache' / 'sources'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cached(key, fn):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f'{key}-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    try:
        out = fn()
    except Exception as e:
        print(f'  {key}: {str(e)[:100]}', file=sys.stderr)
        return None
    if out:
        p.write_text(json.dumps(out))
    time.sleep(0.3)
    return out


def text(s):
    s = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', s, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', ' ', s)))


def pct(x):
    try:
        return round(float(str(x).replace('%', '').replace(',', '').strip()), 2)
    except ValueError:
        return None


def usdate(d):
    for f in ('%m/%d/%Y', '%B %d, %Y', '%B %d %Y', '%m.%d.%y', '%m/%d/%y'):
        try:
            return datetime.datetime.strptime(re.sub(r'(\d)(st|nd|rd|th)', r'\1', d.strip()), f).date().isoformat()
        except ValueError:
            continue
    return None


def pdf_text(data):
    import pypdf
    r = pypdf.PdfReader(io.BytesIO(data))
    return re.sub(r'[ \t]+', ' ', '\n'.join((p.extract_text() or '') for p in r.pages))


def docx_text(data):
    x = zipfile.ZipFile(io.BytesIO(data)).read('word/document.xml').decode('utf-8', 'replace')
    t = re.sub(r'</w:p>', '\n', x)
    return htmlmod.unescape(re.sub(r'<[^>]+>', '', t))


def sources_table(t):
    """Parse a 19a-1 table (current amount, current %, YTD amount, YTD %) for the standard rows. Returns dict of row -> (cur%, ytd%)."""
    out = {}
    labels = {'income': r'Net Investment Income', 'stcg': r'(?:Net Realized )?Short[- ]Term (?:Capital )?Gains?', 'ltcg': r'(?:Net Realized )?Long[- ]Term (?:Capital )?Gains?', 'roc': r'Return of Capital'}
    flat = re.sub(r'\s+', ' ', t)
    for k, lab in labels.items():
        m = re.search(lab + r'\s*\$?\s*([\d.,]+)\s*([\d.]+)\s*%\s*\$?\s*([\d.,]+)\s*([\d.]+)\s*%', flat)
        if m:
            out[k] = (pct(m.group(2)), pct(m.group(4)))
    return out


def yieldmax(ticker):
    def fn():
        s = get(f'https://yieldmaxetfs.com/our-etfs/{ticker.lower()}/').decode('utf-8', 'replace')
        rows = []
        for tb in re.findall(r'<table[^>]*>(.*?)</table>', s, re.S):
            if 'ROC' not in tb:
                continue
            for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb, re.S):
                c = [text(x) for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
                if len(c) >= 6 and c[0].startswith('$'):
                    roc = pct(c[5]) if 'nan' not in c[5].lower() else None
                    rows.append({'amount': float(c[0].replace('$', '').replace(',', '')), 'ex': usdate(c[2]), 'pay': usdate(c[4]), 'roc': roc})
            break
        if not rows:
            return None
        latest = rows[0]
        cutoff = (TODAY - datetime.timedelta(days=365)).isoformat()
        t12 = [r for r in rows if r['pay'] and r['pay'] >= cutoff and r['roc'] is not None]
        wsum = sum(r['amount'] for r in t12)
        return {'issuer': 'YieldMax', 'asOf': latest['pay'], 'latest': {'date': latest['pay'], 'amount': latest['amount'], 'roc': latest['roc'], 'income': None if latest['roc'] is None else round(100 - latest['roc'], 2), 'gains': None},
                'ytd': None, 't12': {'roc': round(sum(r['amount'] * r['roc'] for r in t12) / wsum, 1) if wsum else None, 'n': len(t12)},
                'url': f'https://yieldmaxetfs.com/our-etfs/{ticker.lower()}/', 'method': 'issuer distribution table, ROC per distribution'}
    return cached(f'yieldmax-{ticker}', fn)


def globalx(ticker):
    def fn():
        s = get(f'https://www.globalxetfs.com/funds/{ticker.lower()}/').decode('utf-8', 'replace')
        m = re.search(r'href="(https://assets\.globalxetfs\.com/funds/tax_supplements/[^"]*Form-19a[^"]*\.docx)"', s)
        if not m:
            return None
        url = m.group(1)
        t = docx_text(get(url))
        rows = sources_table(t)
        if 'roc' not in rows and 'income' not in rows:
            return None
        pay = re.search(r'Pay Date:\s*([A-Za-z]+ \d+, \d{4})', t)
        amt = re.search(r'Distribution Amount Per Share:\s*\$([\d.]+)', t)
        cur = lambda k: rows[k][0] if k in rows else 0.0
        ytd = lambda k: rows[k][1] if k in rows else 0.0
        return {'issuer': 'Global X', 'asOf': usdate(pay.group(1)) if pay else None,
                'latest': {'date': usdate(pay.group(1)) if pay else None, 'amount': float(amt.group(1)) if amt else None, 'roc': cur('roc'), 'income': cur('income'), 'gains': round(cur('stcg') + cur('ltcg'), 2)},
                'ytd': {'roc': ytd('roc'), 'income': ytd('income'), 'gains': round(ytd('stcg') + ytd('ltcg'), 2)}, 't12': None, 'url': url, 'method': 'Form 19a notice, current and fiscal year to date'}
    return cached(f'globalx-{ticker}', fn)


def parse_notice_pdf(data, issuer, url):
    t = re.sub(r'[\u00b9\u00b2\u00b3\u2070-\u2079]', '', pdf_text(data))  # footnote superscripts
    t = re.sub(r'(Income|Capital|Gains?)\d\b', r'\1', t)  # footnote digits glued to labels
    rows = sources_table(t)
    m = re.search(r'(\d+(?:\.\d+)?)\s*%\s*of such (?:dividend|distribution) will be a\s*return of capital', t, re.I | re.S) or re.search(r'estimates that\s*(\d+(?:\.\d+)?)\s*%\s*is (?:from|a) return of capital', t, re.I | re.S)
    roc = pct(m.group(1)) if m else (rows['roc'][0] if 'roc' in rows else None)
    if roc is None:
        m2 = re.search(r'return of capital[^%]{0,80}?(\d+(?:\.\d+)?)\s*%', t, re.I | re.S)
        roc = pct(m2.group(1)) if m2 else None
    if roc is None:
        return None
    amt = re.search(r'\$([\d.]+)\s*per share', t)
    pay = re.search(r'payable on\s+([A-Za-z]+ \d+(?:st|nd|rd|th)?,? \d{4})', t) or re.search(r'On ([A-Za-z]+ \d+, \d{4}), the Fund paid', t) or re.search(r'Payable Date:.*?(\d{1,2}/\d{1,2}/\d{4})', t, re.S)
    latest = {'date': usdate(pay.group(1)) if pay else None, 'amount': float(amt.group(1)) if amt else None, 'roc': roc,
              'income': rows['income'][0] if 'income' in rows else round(100 - roc, 2), 'gains': round((rows.get('stcg', (0, 0))[0] or 0) + (rows.get('ltcg', (0, 0))[0] or 0), 2) if ('stcg' in rows or 'ltcg' in rows) else None}
    ytd = {'roc': rows['roc'][1], 'income': rows.get('income', (0, 0))[1], 'gains': round((rows.get('stcg', (0, 0))[1] or 0) + (rows.get('ltcg', (0, 0))[1] or 0), 2)} if 'roc' in rows else None
    return {'issuer': issuer, 'asOf': latest['date'], 'latest': latest, 'ytd': ytd, 't12': None, 'url': url, 'method': '19a-1 notice, latest distribution'}


def neos(ticker):
    def fn():
        s = get(f'https://neosfunds.com/{ticker.lower()}/').decode('utf-8', 'replace')
        links = re.findall(r'href="(https://neosfunds\.com/wp-content/uploads/[^"]*19a1[^"]*\.pdf)"', s)
        if not links:
            return None
        def key(u):
            m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', u)
            if not m:
                return ''
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            return f'{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
        url = max(links, key=key)
        return parse_notice_pdf(get(url), 'NEOS', url)
    return cached(f'neos-{ticker}', fn)


_defiance_page = {}


def defiance(ticker):
    def fn():
        if 'html' not in _defiance_page:
            _defiance_page['html'] = get('https://www.defianceetfs.com/19a1-notices/').decode('utf-8', 'replace')
        s = _defiance_page['html']
        links = re.findall(r'href="(https://www\.defianceetfs\.com/wp-content/uploads/funddocs/19a1/' + ticker.upper() + r'/[^"]*\.pdf)"', s)
        if not links:
            return None
        def key(u):
            m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2})', u)
            return f'20{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}' if m else ''
        url = max(links, key=key)
        t = pdf_text(get(url))
        # one Defiance notice covers every fund paying that day; take this ticker's block
        i = t.find(ticker.upper())
        if i < 0:
            return None
        seg = t[i:]
        j = seg.find('Fund Name', 5)
        seg = seg[:j] if j > 0 else seg
        roc = re.search(r'Return of Capital\s*\$([\d.]+)\s*([\d.]+)%', seg)
        inc = re.search(r'Net Investment Income\s*\$([\d.]+)\s*([\d.]+)%', seg)
        tot = re.search(r'Total \(per common share\)\s*\$([\d.]+)', seg)
        pay = re.search(r'payable\s+([A-Za-z]+ \d+, \d{4})', t)
        if not roc:
            return None
        date = usdate(pay.group(1)) if pay else None
        return {'issuer': 'Defiance', 'asOf': date, 'latest': {'date': date, 'amount': float(tot.group(1)) if tot else None, 'roc': pct(roc.group(2)), 'income': pct(inc.group(2)) if inc else round(100 - pct(roc.group(2)), 2), 'gains': None},
                'ytd': None, 't12': None, 'url': url, 'method': '19a-1 notice, latest distribution'}
    return cached(f'defiance-{ticker}', fn)


def kurv(ticker):
    def fn():
        s = get(f'https://kurvinvest.com/etf/{ticker.lower()}/').decode('utf-8', 'replace')
        links = re.findall(r'href="(https://documents\.services\.kurvinvest\.com/19a1/[^"]*\.pdf)"', s)
        if not links:
            return None
        def key(u):
            m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2})\.pdf', u)
            return f'20{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}' if m else ''
        url = max(links, key=key)
        return parse_notice_pdf(get(urllib.parse.quote(url, safe=':/')), 'Kurv', url)
    return cached(f'kurv-{ticker}', fn)


def rex(ticker):
    def fn():
        s = get(f'https://www.rexshares.com/{ticker.lower()}/').decode('utf-8', 'replace')
        m = re.search(r'href="(https://www\.rexshares\.com/[^"]*19a-1-notice[^"]*\.pdf)"', s)
        if not m:
            return None
        url = m.group(1)
        t = re.sub(r'[\u00b9\u00b2\u00b3\u2070-\u2079]', '', pdf_text(get(url)))
        t = re.sub(r'(Income|Capital|Gains?)\d\b', r'\1', t)
        roc = re.search(r'Return of Capital\s*\$([\d.]+)\s*([\d.]+)%\s*\$([\d.]+)\s*([\d.]+)%', t)
        inc = re.search(r'Net Investment\s*Income\s*\$([\d.]+)\s*([\d.]+)%\s*\$([\d.]+)\s*([\d.]+)%', t)
        pay = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+' + ticker.upper(), t)
        tot = re.search(r'Total[^$]{0,60}\$([\d.]+)', t)
        if not roc:
            return None
        date = usdate(pay.group(1)) if pay else None
        return {'issuer': 'REX', 'asOf': date, 'latest': {'date': date, 'amount': float(tot.group(1)) if tot else None, 'roc': pct(roc.group(2)), 'income': pct(inc.group(2)) if inc else round(100 - pct(roc.group(2)), 2), 'gains': None},
                'ytd': {'roc': pct(roc.group(4)), 'income': pct(inc.group(4)) if inc else None, 'gains': None}, 't12': None, 'url': url, 'method': '19a-1 notice, latest distribution and calendar year to date'}
    return cached(f'rex-{ticker}', fn)


def graniteshares(ticker):
    def fn():
        s = get(f'https://graniteshares.com/institutional/us/en-us/etfs/{ticker.lower()}/').decode('utf-8', 'replace')
        links = re.findall(r'href="(/media/[^"]*19-a-notice[^"]*\.pdf)"', s)
        if not links:
            return None
        def key(u):
            m = re.search(r'(\d{2})(\d{2})(\d{4})\.pdf', u)
            return f'{m.group(3)}-{m.group(1)}-{m.group(2)}' if m else '0'
        url = 'https://graniteshares.com' + max(links, key=key)
        return parse_notice_pdf(get(url), 'GraniteShares', url)
    return cached(f'graniteshares-{ticker}', fn)


PARSERS = {'YieldMax': yieldmax, 'Global X': globalx, 'NEOS': neos, 'Defiance': defiance, 'Kurv': kurv, 'REX': rex, 'GraniteShares': graniteshares}


def build(only=None):
    income = json.loads((ROOT / 'site' / 'data' / 'income.json').read_text())
    out, n = {}, 0
    for r in income:
        fn = PARSERS.get(r['issuer'])
        if not fn or (only and r['ticker'] not in only):
            continue
        d = fn(r['ticker'])
        if d:
            out[r['ticker']] = d
        n += 1
        if n % 20 == 0:
            print(f'  {n} checked, {len(out)} with notices', file=sys.stderr)
    (ROOT / 'site' / 'data' / 'sources.json').write_text(json.dumps(out, separators=(',', ':')))
    by = {}
    for d in out.values():
        by[d['issuer']] = by.get(d['issuer'], 0) + 1
    print(json.dumps({'funds': len(out), 'byIssuer': by, 'asOf': TODAY.isoformat()}, indent=1))
    return out


if __name__ == '__main__':
    build(set(sys.argv[1:]) or None)
