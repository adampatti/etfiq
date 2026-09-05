#!/usr/bin/env python3
"""The core index funds: the funds people already hold, on the same fields as the desks.

ETFIQ's three desks cover buffer, option-income and thematic ETFs. The funds those are measured against, and the
funds a reader already owns around them, are the plain index funds: VOO, SPY, QQQ, SCHD, AGG and the rest. Their
holdings books are already built by books.py for the Portfolio desk, so this adds the missing half: prices, returns
against the S&P 500 and the Nasdaq-100, drawdown, fee, and the overlap the themes desk computes.

Writes site/data/core.json. Prices come from the same Tiingo feed and the same window definitions as the income desk,
so a core fund and a desk fund are measured identically.
"""
import csv
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books as B          # noqa: E402
import holdings as H       # noqa: E402
import income as I         # noqa: E402
import income_universe as iu  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
KIND_LABEL = {'equity': 'Index equity fund', 'bond': 'Bond fund', 'cash': 'Cash and Treasury bills',
              'commodity': 'Commodity fund', 'crypto': 'Digital asset fund'}


def sec_names():
    rows = csv.DictReader(open(iu.sec_file(), encoding='utf-8-sig', errors='replace'))
    out = {}
    for x in rows:
        t = (x.get('Class Ticker') or '').strip().upper()
        n = (x.get('Series Name') or '').strip()
        if t and n and t not in out:
            out[t] = n
    return out


HAND_NAMES = {'SPY': 'SPDR S&P 500 ETF Trust', 'GLD': 'SPDR Gold Shares', 'IAU': 'iShares Gold Trust',
              'SLV': 'iShares Silver Trust', 'IBIT': 'iShares Bitcoin Trust ETF', 'FBTC': 'Fidelity Wise Origin Bitcoin Fund',
              'ETHA': 'iShares Ethereum Trust ETF', 'QQQ': 'Invesco QQQ Trust', 'BIL': 'SPDR Bloomberg 1-3 Month T-Bill ETF',
              'MDY': 'SPDR S&P MidCap 400 ETF Trust'}


ISSUER_WORDS = ['Vanguard', 'iShares', 'SPDR', 'Invesco', 'Schwab', 'Fidelity', 'State Street', 'BlackRock', 'Grayscale', 'VanEck', 'Global X', 'First Trust', 'WisdomTree', 'JPMorgan', 'Dimensional']
ISSUER_FIX = {'SPDR': 'State Street', 'BlackRock': 'iShares'}


def issuer_of(name):
    """The house behind a core fund, from its registered name."""
    for w in ISSUER_WORDS:
        if w.lower() in (name or '').lower():
            return ISSUER_FIX.get(w, w)
    return (name or '').split()[0] if name else 'n/a'


def build():
    tok = I.token()
    if not tok:
        sys.exit('No TIINGO_TOKEN.')
    names = sec_names()
    fees = json.loads((ROOT / 'data' / 'fees.json').read_text()) if (ROOT / 'data' / 'fees.json').exists() else {}
    bidx = json.loads((ROOT / 'site' / 'data' / 'books' / 'index.json').read_text())['books']
    spy = I.split_adjust(I.trim_history(I.prices('SPY', tok)))
    qqq = I.split_adjust(I.trim_history(I.prices('QQQ', tok)))
    spy_book = H.index_holdings('SPY')
    qqq_book = H.index_holdings('QQQ')
    out, missing = [], []
    for i, (t, (sid, kind, note)) in enumerate(sorted(B.CORE.items())):
        rows = I.split_adjust(I.trim_history(I.prices(t, tok)))
        if len(rows) < 5:
            missing.append(t)
            continue
        end = rows[0 - 1]
        nm = HAND_NAMES.get(t) or names.get(t) or note
        rec = {'ticker': t, 'name': nm, 'issuer': issuer_of(nm), 'kind': kind, 'kindLabel': KIND_LABEL.get(kind, kind),
               'note': note, 'asOf': end['date'], 'price': end['close'], 'inception': rows[0]['date'],
               'daysSinceInception': (datetime.date.fromisoformat(end['date']) - datetime.date.fromisoformat(rows[0]['date'])).days,
               'expenseRatio': (fees.get(t) or {}).get('expenseRatio'),
               'windows': {}}
        for k, d in I.WINDOWS.items():
            w = I.window(rows, spy, d)
            wq = I.window(rows, qqq, d)
            if w:
                w['benchQ'], w['gapQ'] = (wq['bench'], wq['gap']) if wq else (None, None)
            rec['windows'][k] = w
        s0 = rows[0]
        itd = {'from': s0['date'], 'to': end['date'], 'days': rec['daysSinceInception'],
               'cash': round(sum(r['sdiv'] for r in rows[1:]) / s0['sclose'] * 100, 2),
               'price': round((end['sclose'] / s0['sclose'] - 1) * 100, 2),
               'total': round((end['adjClose'] / s0['adjClose'] - 1) * 100, 2), 'bench': None, 'gap': None, 'benchQ': None, 'gapQ': None}
        for key, gkey, book in (('bench', 'gap', spy), ('benchQ', 'gapQ', qqq)):
            bi, be = I.at_or_before(book, s0['date']), I.at_or_before(book, end['date'])
            if bi is not None and be is not None and book[be]['date'] > book[bi]['date']:
                itd[key] = round((book[be]['adjClose'] / book[bi]['adjClose'] - 1) * 100, 2)
                itd[gkey] = round(itd['total'] - itd[key], 2)
        rec['windows']['ITD'] = itd
        hi, hi_date = 0.0, None
        for r in rows:
            if r['adjClose'] and r['adjClose'] > hi:
                hi, hi_date = r['adjClose'], r['date']
        rec['drawdown'] = round((end['adjClose'] / hi - 1) * 100, 2) if hi else None
        rec['highDate'] = hi_date
        meta = bidx.get(t) or {}
        bp = ROOT / 'site' / 'data' / 'books' / f'{t}.json'
        if bp.exists():
            b = json.loads(bp.read_text())
            h = [{'name': x[0], 'ticker': x[1], 'cusip': x[2], 'weight': x[3]} for x in (b.get('h') or [])]
            rec['holdingsSource'] = b.get('src')
            rec['holdingsAsOf'] = b.get('asOf')
            rec['holdingsCount'] = b.get('n')
            rec['top'] = [{'t': x['ticker'], 'n': x['name'][:48], 'w': round(x['weight'], 2)} for x in h[:10]]
            rec['top10Weight'] = round(sum(x['weight'] for x in h[:10]), 1) if h else None
            if h and kind == 'equity':
                rec['vsSPY'] = H.overlap(h, spy_book['holdings'])
                rec['vsQQQ'] = H.overlap(h, qqq_book['holdings'])
        rec.setdefault('holdingsAsOf', meta.get('asOf'))
        rec.setdefault('holdingsCount', meta.get('n'))
        rec.setdefault('top', [])
        rec.setdefault('top10Weight', None)
        rec.setdefault('vsSPY', None)
        rec.setdefault('vsQQQ', None)
        out.append(rec)
        if (i + 1) % 10 == 0:
            print(f'  {i + 1} of {len(B.CORE)}', file=sys.stderr)
    out.sort(key=lambda r: r['ticker'])
    (ROOT / 'site' / 'data' / 'core.json').write_text(json.dumps(out, separators=(',', ':')))
    meta = {'asOf': max((r['asOf'] for r in out), default=TODAY.isoformat()), 'n': len(out), 'missing': missing,
            'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
    (ROOT / 'site' / 'data' / 'core_meta.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps({'core funds': len(out), 'missing': missing, 'asOf': meta['asOf']}, indent=1))


if __name__ == '__main__':
    build()
