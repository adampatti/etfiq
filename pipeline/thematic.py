#!/usr/bin/env python3
"""ETFIQ themes desk: what did I actually buy, and is it working?

For every fund in data/thematic_universe.json:
  performance   Tiingo daily prices (the income desk's feed and functions): total return with distributions reinvested
                over 3M, 6M, 1Y, 3Y and since launch, against the S&P 500 (SPY) and the Nasdaq-100 (QQQ), plus the
                drawdown from the fund's own all-time high.
  holdings      the latest public N-PORT filing (holdings.py): holding count, top-ten weight, the top holdings, net
                assets and the filing's as-of date.
  overlap       against the S&P 500 and the Nasdaq-100 (index holdings from IVV and QQQM filings): weight overlap,
                active share, and the share of the fund sitting in names the index holds at all ("in-index weight").
                Also every fund against every other fund, kept as a compact percent matrix for the look-through tool.

Writes site/data/thematic.json and site/data/thematic_meta.json. Set TIINGO_TOKEN and ETFIQ_CONTACT.
"""
import datetime
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import holdings as H  # noqa: E402
import income  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()


def drawdown(rows):
    """Percent below the all-time high on the reinvested series, and the date of that high."""
    hi, hi_date = 0.0, None
    for r in rows:
        if r['adjClose'] and r['adjClose'] > hi:
            hi, hi_date = r['adjClose'], r['date']
    last = rows[-1]['adjClose'] if rows else None
    return (round((last / hi - 1) * 100, 2) if hi and last else None), hi_date


def build():
    tok = income.token()
    if not tok:
        sys.exit('No TIINGO_TOKEN.')
    universe = [r for r in json.loads((ROOT / 'data' / 'thematic_universe.json').read_text()) if r.get('include')]
    # holdings change quarterly: refresh them on Saturdays or on demand, otherwise carry the last good book forward
    prev_path = ROOT / 'site' / 'data' / 'thematic.json'
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {'funds': [], 'matrix': None}
    prev_by = {r['ticker']: r for r in prev.get('funds', [])}
    refresh = os.environ.get('HOLDINGS_REFRESH') == '1' or TODAY.weekday() == 5 or not prev_by
    print(f"  holdings: {'refreshing from EDGAR' if refresh else 'carried forward from the last run'}", file=sys.stderr)
    HOLD_KEYS = ('holdingsAsOf', 'holdingsFiled', 'holdingsSource', 'holdingsCount', 'top10Weight', 'assets', 'top', 'vsSPY', 'vsQQQ', 'peers')
    spy = H.index_holdings('SPY') if refresh else None
    qqq = H.index_holdings('QQQ') if refresh else None
    if refresh:
        print(f"  index holdings: S&P 500 {len(spy['holdings'])} as of {spy['asOf']}, Nasdaq-100 {len(qqq['holdings'])} as of {qqq['asOf']}", file=sys.stderr)
    bench = {b: income.split_adjust(income.trim_history(income.prices(b, tok))) for b in ('SPY', 'QQQ')}
    out, missing, no_holdings, held, closed = [], [], [], {}, []
    for i, u in enumerate(universe):
        rows = income.split_adjust(income.trim_history(income.prices(u['ticker'], tok)))
        if len(rows) < 5:
            missing.append(u['ticker'])
            continue
        end = rows[0] and rows[-1]
        if (TODAY - datetime.date.fromisoformat(end['date'])).days > 12:
            closed.append(u['ticker'])  # no trade in twelve days: delisted or closed, kept in the snapshot, off the desk
            continue
        rec = dict(u)
        wins = {}
        for k, d in income.WINDOWS.items():
            w = income.window(rows, bench['SPY'], d)
            if w:
                wq = income.window(rows, bench['QQQ'], d)
                w['benchQ'], w['gapQ'] = (wq['bench'], wq['gap']) if wq else (None, None)
            wins[k] = w
        s = rows[0]
        itd = {'from': s['date'], 'to': end['date'], 'days': (datetime.date.fromisoformat(end['date']) - datetime.date.fromisoformat(s['date'])).days,
               'price': round((end['sclose'] / s['sclose'] - 1) * 100, 2), 'total': round((end['adjClose'] / s['adjClose'] - 1) * 100, 2), 'bench': None, 'gap': None, 'benchQ': None, 'gapQ': None}
        for key, bk in (('bench', 'SPY'), ('benchQ', 'QQQ')):
            br = bench[bk]
            bi, be = income.at_or_before(br, s['date']), income.at_or_before(br, end['date'])
            if bi is not None and be is not None and br[be]['date'] > br[bi]['date']:
                itd[key] = round((br[be]['adjClose'] / br[bi]['adjClose'] - 1) * 100, 2)
                itd['gap' if key == 'bench' else 'gapQ'] = round(itd['total'] - itd[key], 2)
        wins['ITD'] = itd
        dd, hi_date = drawdown(rows)
        rec.update({'asOf': end['date'], 'price': end['close'], 'inception': s['date'], 'daysSinceInception': itd['days'], 'windows': wins, 'drawdown': dd, 'highDate': hi_date})
        # holdings and overlap
        info, h = H.fund_holdings(u.get('seriesId') or '', u['name']) if refresh else (None, [])
        if not h and u['ticker'] in prev_by and prev_by[u['ticker']].get('vsSPY'):
            rec.update({k: prev_by[u['ticker']].get(k) for k in HOLD_KEYS})
            out.append(rec)
            continue
        if h:
            tot = sum(x['weight'] for x in h) or 1.0
            top = h[:10]
            rec.update({'holdingsAsOf': info.get('period'), 'holdingsFiled': info.get('filed'), 'holdingsSource': info.get('source'), 'holdingsCount': len(h),
                        'top10Weight': round(sum(x['weight'] for x in top) / tot * 100, 1), 'assets': info.get('netAssets'),
                        'top': [{'t': x['ticker'], 'n': x['name'][:48], 'w': round(x['weight'] / tot * 100, 2)} for x in top],
                        'vsSPY': H.overlap(h, spy['holdings']), 'vsQQQ': H.overlap(h, qqq['holdings'])})
            held[u['ticker']] = h
        else:
            no_holdings.append(u['ticker'])
            rec.update({'holdingsAsOf': None, 'holdingsCount': None, 'top10Weight': None, 'assets': None, 'top': [], 'vsSPY': None, 'vsQQQ': None})
        out.append(rec)
        if (i + 1) % 25 == 0:
            print(f'  {i + 1} of {len(universe)}', file=sys.stderr)
    # every fund against every other: percent weight overlap, upper triangle in ticker order
    if refresh and held:
        tickers = [r['ticker'] for r in out if r['ticker'] in held]
        pairs = []
        for a in range(len(tickers)):
            row = []
            for b in range(a + 1, len(tickers)):
                row.append(int(round(H.overlap(held[tickers[a]], held[tickers[b]])['overlap'])))
            pairs.append(row)
    else:
        tickers, pairs = ((prev.get('matrix') or {}).get('tickers') or []), ((prev.get('matrix') or {}).get('rows') or [])
    # the closest peers per fund, from the matrix
    for r in out:
        if r['ticker'] not in held:
            if 'peers' not in r:
                r['peers'] = []
            continue
        a = tickers.index(r['ticker'])
        cands = []
        for b, t in enumerate(tickers):
            if b == a:
                continue
            v = pairs[a][b - a - 1] if b > a else pairs[b][a - b - 1]
            cands.append((v, t))
        cands.sort(reverse=True)
        r['peers'] = [{'t': t, 'o': v} for v, t in cands[:5] if v >= 10]
    out.sort(key=lambda r: (r['themeName'], r['ticker']))
    meta = {'asOf': max((r['asOf'] for r in out), default=TODAY.isoformat()), 'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'universe': len(universe), 'shown': len(out), 'withHoldings': sum(1 for r in out if r.get('vsSPY')), 'missingPrices': missing, 'missingHoldings': no_holdings, 'closed': closed,
            'holdingsRefreshed': refresh, 'indexHoldingsAsOf': ({'SPY': spy['asOf'], 'QQQ': qqq['asOf']} if refresh else (json.loads((ROOT / 'site' / 'data' / 'thematic_meta.json').read_text()).get('indexHoldingsAsOf') if (ROOT / 'site' / 'data' / 'thematic_meta.json').exists() else None)),
            'feed': 'Tiingo end-of-day; SEC N-PORT holdings'}
    (ROOT / 'site' / 'data').mkdir(parents=True, exist_ok=True)
    (ROOT / 'site' / 'data' / 'thematic.json').write_text(json.dumps({'funds': out, 'matrix': {'tickers': tickers, 'rows': pairs}}, separators=(',', ':')))
    (ROOT / 'site' / 'data' / 'thematic_meta.json').write_text(json.dumps(meta, indent=1))
    (ROOT / 'data' / 'snapshots').mkdir(parents=True, exist_ok=True)
    (ROOT / 'data' / 'snapshots' / f'thematic-{TODAY.isoformat()}.json').write_text(json.dumps({'meta': meta, 'funds': out}, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k not in ('missingPrices', 'missingHoldings')}, indent=1))
    print('no prices:', missing)
    print('no holdings:', no_holdings)
    print('closed or delisted:', closed)


if __name__ == '__main__':
    build()
