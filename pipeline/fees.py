#!/usr/bin/env python3
"""Expense ratios from the prospectus XBRL every fund files with the SEC.

Each 485BPOS (the annual prospectus update) carries a risk/return summary in XBRL: ExpensesOverAssets is the total
annual fund operating expense ratio and NetExpensesOverAssets the figure after fee waivers, both tagged by share
class (C000... ids that the SEC series and class file maps to tickers). Newer filings use the oef taxonomy, older
ones rr; both are read.

For every trust (CIK) behind the income and themes universes: list its 485BPOS filings from the EDGAR submissions
feed, fetch each filing's XBRL instance, and keep the latest fee per class. Output data/fees.json:
ticker -> {expenseRatio (net of waivers if any, in percent), grossExpenseRatio, filed, source}.

Instances never change, so they are cached for good in pipeline/cache/fees/. Runs weekly (Saturday) in the nightly
job, or on demand with FEES_REFRESH=1. Set ETFIQ_CONTACT for the SEC user agent.
"""
import csv
import datetime
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import holdings as H  # noqa: E402  (sec_get with retries and the SEC user agent)
import income_universe as iu  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
CACHE = ROOT / 'pipeline' / 'cache' / 'fees'
LOOKBACK_DAYS = 480


def submissions(cik):
    p = CACHE / f'sub-{cik}-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    d = json.loads(H.sec_get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'))
    f = d.get('filings', {}).get('recent', {})
    out = [{'form': f['form'][i], 'date': f['filingDate'][i], 'acc': f['accessionNumber'][i], 'doc': f['primaryDocument'][i]} for i in range(len(f.get('form', []))) if f['form'][i] == '485BPOS']
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def instance(cik, acc):
    """The XBRL instance document of a filing, cached for good (None when the filing has no XBRL)."""
    key = acc.replace('-', '')
    p = CACHE / f'inst-{key}.xml'
    if p.exists():
        t = p.read_text()
        return t or None
    idx = json.loads(H.sec_get(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{key}/index.json'))
    names = [it['name'] for it in idx.get('directory', {}).get('item', [])]
    cand = [n for n in names if n.endswith('_htm.xml')] or [n for n in names if n.endswith('.xml') and not re.search(r'_(lab|pre|def|cal)\.xml$|FilingSummary', n)]
    CACHE.mkdir(parents=True, exist_ok=True)
    if not cand:
        p.write_text('')
        return None
    t = H.sec_get(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{key}/{cand[0]}')
    p.write_text(t)
    return t


def parse(xml):
    """class id -> {'gross': pct, 'net': pct or None} from an rr or oef instance."""
    ctx = {}
    for cid, body in re.findall(r'<(?:xbrli:)?context id="([^"]+)">(.*?)</(?:xbrli:)?context>', xml, re.S):
        mem = re.findall(r'explicitMember dimension="([^"]+)">([^<]+)<', body)
        cls = next((re.search(r'(C\d{9})', v).group(1) for d, v in mem if ('ClassAxis' in d or 'ProspectusShareClassAxis' in d) and re.search(r'C\d{9}', v)), None)
        ctx[cid] = cls
    out = {}
    for name, cid, val in re.findall(r'<(?:oef|rr):(ExpensesOverAssets|NetExpensesOverAssets)\b[^>]*contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
        cls = ctx.get(cid)
        if not cls:
            continue
        try:
            v = round(float(val) * 100, 2)
        except ValueError:
            continue
        rec = out.setdefault(cls, {'gross': None, 'net': None})
        rec['net' if name.startswith('Net') else 'gross'] = v
    return out


def build():
    if not (os.environ.get('FEES_REFRESH') == '1' or TODAY.weekday() == 5 or not (ROOT / 'data' / 'fees.json').exists()):
        print('fees: not a refresh day; keeping data/fees.json', file=sys.stderr)
        return
    rows = list(csv.DictReader(open(iu.sec_file(), encoding='utf-8-sig', errors='replace')))
    by_ticker = {}
    for x in rows:
        tk = (x.get('Class Ticker') or '').strip().upper()
        if tk:
            by_ticker[tk] = {'cik': str(int(x['CIK Number'])), 'cls': (x.get('Class ID') or '').strip()}
    wanted = set()
    for fn in ('data/income_universe.json', 'data/thematic_universe.json'):
        p = ROOT / fn
        if p.exists():
            wanted |= {r['ticker'] for r in json.loads(p.read_text()) if r.get('include')}
    ciks = sorted({by_ticker[t]['cik'] for t in wanted if t in by_ticker})
    print(f'  {len(wanted)} tickers, {len(ciks)} trusts', file=sys.stderr)
    cutoff = (TODAY - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    fees = {}  # class id -> {gross, net, filed, source}
    for i, cik in enumerate(ciks):
        try:
            filings = [f for f in submissions(cik) if f['date'] >= cutoff][:40]
        except Exception as e:
            print(f'  submissions {cik}: {str(e)[:80]}', file=sys.stderr)
            continue
        for f in sorted(filings, key=lambda f: f['date']):
            try:
                xml = instance(cik, f['acc'])
            except Exception as e:
                print(f'  filing {f["acc"]}: {str(e)[:80]}', file=sys.stderr)
                continue
            if not xml:
                continue
            for cls, v in parse(xml).items():
                if v['gross'] is None and v['net'] is None:
                    continue
                cur = fees.get(cls)
                if not cur or f['date'] >= cur['filed']:
                    fees[cls] = {'gross': v['gross'], 'net': v['net'], 'filed': f['date'], 'source': f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}/"}
        if (i + 1) % 10 == 0:
            print(f'  {i + 1} of {len(ciks)} trusts, {len(fees)} classes priced', file=sys.stderr)
    out = {}
    for t in sorted(wanted):
        m = by_ticker.get(t)
        if not m or m['cls'] not in fees:
            continue
        v = fees[m['cls']]
        out[t] = {'expenseRatio': v['net'] if v['net'] is not None else v['gross'], 'grossExpenseRatio': v['gross'], 'filed': v['filed'], 'source': v['source']}
    (ROOT / 'data' / 'fees.json').write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({'tickers': len(wanted), 'withFee': len(out), 'trusts': len(ciks), 'asOf': TODAY.isoformat()}, indent=1))


if __name__ == '__main__':
    build()
