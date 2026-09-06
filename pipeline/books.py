#!/usr/bin/env python3
"""Books for the Portfolio desk: the filed holdings of every fund a portfolio can contain, one small file per ticker.

Sources, in order: the issuer's daily file where one exists (ARK, First Trust), otherwise the fund's latest public
N-PORT filing. Covered: every income desk fund, every themes desk fund, and the core index funds people hold
(VOO, IVV, VTI, QQQ, the sector SPDRs, dividend and style funds, the big international funds). Bond and commodity
funds are recorded as asset classes without a look-through; buffer funds are represented by their reference index.

A fund whose book is mostly Treasury bills and options (the synthetic income funds) is marked synthetic with its
economic exposure, so the desk can show "T-bills and options on TSLA" rather than a bond position.

Writes site/data/books/<TICKER>.json ({t, asOf, src, kind, n, h: [[name, ticker, cusip, weight], ...]}) and
site/data/books/index.json. Refreshes on Saturdays or with BOOKS_REFRESH=1; otherwise keeps the files as they are.
"""
import datetime
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import holdings as H  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'site' / 'data' / 'books'
TODAY = datetime.date.today()

CORE = {  # ticker: (series id, kind, note)
    'VOO': ('S000002839', 'equity', 'S&P 500'), 'IVV': ('S000004310', 'equity', 'S&P 500'), 'SPY': ('S000004310', 'equity', 'S&P 500, book from IVV'),
    'VTI': ('S000002848', 'equity', 'US total market'), 'QQQ': ('S000069448', 'equity', 'Nasdaq-100, book from QQQM'), 'QQQM': ('S000069448', 'equity', 'Nasdaq-100'),
    'IWM': ('S000004344', 'equity', 'Russell 2000'), 'IJH': ('S000004307', 'equity', 'S&P MidCap 400'), 'MDY': ('S000004307', 'equity', 'S&P MidCap 400, book from IJH'), 'IJR': ('S000004313', 'equity', 'S&P SmallCap 600'),
    'RSP': ('S000060812', 'equity', 'S&P 500 equal weight'), 'XLG': ('S000060793', 'equity', 'S&P 500 top 50'),
    'XLK': ('S000006415', 'equity', 'Technology'), 'XLF': ('S000006411', 'equity', 'Financials'), 'XLE': ('S000006410', 'equity', 'Energy'), 'XLV': ('S000006412', 'equity', 'Health care'),
    'XLY': ('S000006408', 'equity', 'Consumer discretionary'), 'XLP': ('S000006409', 'equity', 'Consumer staples'), 'XLI': ('S000006413', 'equity', 'Industrials'), 'XLU': ('S000006416', 'equity', 'Utilities'),
    'XLB': ('S000006414', 'equity', 'Materials'), 'XLRE': ('S000051152', 'equity', 'Real estate'), 'XLC': ('S000062095', 'equity', 'Communication services'),
    'VEA': ('S000004386', 'equity', 'Developed markets ex US'), 'VWO': ('S000005786', 'equity', 'Emerging markets'), 'EFA': ('S000004351', 'equity', 'Developed markets ex US'), 'EEM': ('S000004266', 'equity', 'Emerging markets'),
    'SCHD': ('S000034163', 'equity', 'US dividend'), 'VYM': ('S000014011', 'equity', 'US high dividend'), 'VIG': ('S000011322', 'equity', 'Dividend growth'), 'DVY': ('S000004334', 'equity', 'US dividend'),
    'VTV': ('S000002840', 'equity', 'US value'), 'VUG': ('S000002842', 'equity', 'US growth'), 'IWF': ('S000004346', 'equity', 'Russell 1000 growth'), 'IWD': ('S000004345', 'equity', 'Russell 1000 value'),
    'VNQ': ('S000002924', 'equity', 'US real estate'), 'VGT': ('S000004452', 'equity', 'Information technology'),
    'AGG': (None, 'bond', 'US aggregate bonds'), 'BND': (None, 'bond', 'US aggregate bonds'), 'TLT': (None, 'bond', '20+ year Treasuries'), 'HYG': (None, 'bond', 'US high yield bonds'), 'LQD': (None, 'bond', 'US investment grade bonds'),
    'BIL': (None, 'cash', '1-3 month T-bills'), 'SGOV': (None, 'cash', '0-3 month T-bills'),
    'GLD': (None, 'commodity', 'Gold'), 'IAU': (None, 'commodity', 'Gold'), 'SLV': (None, 'commodity', 'Silver'), 'IBIT': (None, 'crypto', 'Bitcoin'), 'FBTC': (None, 'crypto', 'Bitcoin'), 'ETHA': (None, 'crypto', 'Ether'),
}
TBILL = re.compile(r'TREASURY BILL|T-BILL|UNITED STATES TREASURY|US TREASURY|U\.?S\.? TREASURY|CASH', re.I)


def load(p, default):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else default


def write(ticker, info, h, kind, note=None, exposure=None):
    tot = sum(x['weight'] for x in h) or 1.0
    rows = [[x['name'][:40], x.get('ticker') or '', x.get('cusip') or '', round(x['weight'] / tot * 100, 3)] for x in h[:300]]
    (OUT / f'{ticker}.json').write_text(json.dumps({'t': ticker, 'asOf': (info or {}).get('period'), 'src': (info or {}).get('source'), 'daily': bool((info or {}).get('daily')), 'kind': kind, 'note': note, 'exposure': exposure, 'n': len(h), 'h': rows}, separators=(',', ':')))


def anonymise_keys():
    """Replace the CUSIP in every published book with an opaque ETFIQ security id.

    CUSIPs are licensed by CUSIP Global Services, so they must not appear in anything published.
    They stay the primary match key inside the pipeline. Slot 2 of a book row is only ever a join
    key, never displayed, so an opaque id preserves look-through and overlap exactly. Ids are
    ordered by name and ticker, both of which we publish anyway, so the id carries no CUSIP
    content and no CUSIP ordering.
    """
    paths = [p for p in sorted(OUT.glob('*.json')) if p.name != 'index.json']
    seen = {}
    for p in paths:
        for r in (json.loads(p.read_text()).get('h') or []):
            if r[2]:
                seen.setdefault(r[2], (r[0] or '', r[1] or ''))
    order = sorted(seen, key=lambda k: (seen[k][0].lower(), seen[k][1], k))
    ids = {k: f'e{i:06d}' for i, k in enumerate(order, 1)}
    for p in paths:
        d = json.loads(p.read_text())
        rows = d.get('h') or []
        if not rows:
            continue
        for r in rows:
            if r[2]:
                r[2] = ids[r[2]]
        p.write_text(json.dumps(d, separators=(',', ':')))
    return len(ids)


def stamp_fees():
    """Write each fund's published expense ratio (data/fees.json, from its own 485BPOS) into its book and the index,
    so the desk can weight fees for core funds that sit on no desk. Runs every night; cheap."""
    fees = load('data/fees.json', {})
    index_p = OUT / 'index.json'
    if not fees or not index_p.exists():
        return
    idx = json.loads(index_p.read_text())
    n = 0
    for t, meta in idx.get('books', {}).items():
        v = fees.get(t, {}).get('expenseRatio')
        if v is None or meta.get('fee') == v:
            continue
        meta['fee'] = v
        bp = OUT / f'{t}.json'
        if bp.exists():
            b = json.loads(bp.read_text()); b['fee'] = v; bp.write_text(json.dumps(b, separators=(',', ':')))
        n += 1
    index_p.write_text(json.dumps(idx, separators=(',', ':')))
    print(f'books: fee stamped on {n} books', file=sys.stderr)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    index_p = OUT / 'index.json'
    stamp_fees()
    refresh = os.environ.get('BOOKS_REFRESH') == '1' or TODAY.weekday() == 5 or not index_p.exists()
    if not refresh:
        print('books: not a refresh day; keeping site/data/books', file=sys.stderr)
        return
    index = {}
    income = load('site/data/income.json', [])
    themes = load('site/data/thematic.json', {'funds': []})['funds']
    iuni = {r['ticker']: r for r in load('data/income_universe.json', [])}
    tuni = {r['ticker']: r for r in load('data/thematic_universe.json', [])}
    done = 0
    # core funds
    for t, (sid, kind, note) in CORE.items():
        if sid:
            info, h = H.fund_holdings(sid)
            if h:
                write(t, info, h, kind, note)
                index[t] = {'asOf': info.get('period'), 'kind': kind, 'n': len(h), 'note': note}
                continue
        index[t] = {'asOf': None, 'kind': kind, 'n': 0, 'note': note}
        (OUT / f'{t}.json').write_text(json.dumps({'t': t, 'asOf': None, 'kind': kind, 'note': note, 'n': 0, 'h': []}))
    # themes desk funds
    for r in themes:
        t = r['ticker']
        u = tuni.get(t, {})
        info, h = H.issuer_daily(t, r.get('issuer'))
        if not h or info.get('partial'):
            info2, h2 = H.fund_holdings(u.get('seriesId') or '', r['name'])
            if h2:
                info, h = info2, h2
        if h and not (info or {}).get('partial'):
            write(t, info, h, 'equity', r.get('themeName'))
            index[t] = {'asOf': info.get('period'), 'kind': 'equity', 'n': len(h)}
            done += 1
    # income desk funds
    for i, r in enumerate(income):
        t = r['ticker']
        u = iuni.get(t, {})
        info, h = H.fund_holdings(u.get('seriesId') or '', r['name'])
        if not h:
            if r.get('benchmark'):
                # no filing yet (a young fund): the stock or index it is built on stands in, and the desk says so
                write(t, None, [], 'proxy', 'no filing yet; the stock or index in the fund name stands in', exposure={'ticker': r.get('benchmark'), 'name': r.get('benchmarkName'), 'kind': r.get('benchmarkKind')})
                index[t] = {'asOf': None, 'kind': 'proxy', 'n': 0, 'exposure': r.get('benchmark')}
                done += 1
            continue
        tb = sum(x['weight'] for x in h if TBILL.search(x['name'])) / (sum(x['weight'] for x in h) or 1.0)
        synthetic = tb >= 0.5 or r.get('strategy', '').startswith('synthetic')
        kind = 'synthetic' if synthetic else 'equity'
        write(t, info, h, kind, r.get('strategy'), exposure={'ticker': r.get('benchmark'), 'name': r.get('benchmarkName'), 'kind': r.get('benchmarkKind')} if synthetic else None)
        index[t] = {'asOf': info.get('period'), 'kind': kind, 'n': len(h), 'exposure': r.get('benchmark') if synthetic else None}
        done += 1
        if (i + 1) % 50 == 0:
            print(f'  income {i + 1} of {len(income)}', file=sys.stderr)
    index_p.write_text(json.dumps({'asOf': TODAY.isoformat(), 'books': index}, separators=(',', ':')))
    n_ids = anonymise_keys()
    print(f'books: {n_ids} securities keyed with opaque ids; no CUSIP published', file=sys.stderr)
    stamp_fees()
    print(json.dumps({'books': len(index), 'withHoldings': sum(1 for v in index.values() if v.get('n')), 'synthetic': sum(1 for v in index.values() if v.get('kind') == 'synthetic'), 'asOf': TODAY.isoformat()}, indent=1))


if __name__ == '__main__':
    build()
