#!/usr/bin/env python3
"""ETFIQ income desk: am I ahead of the benchmark?

For every fund in data/income_universe.json (include = true) and every benchmark it names, pull daily prices
and cash distributions from Tiingo, then compute, for each window:
  cash      distributions received in the window as a percent of the price at the window start
  price     price change over the window
  total     total return with distributions reinvested (Tiingo's adjusted close ratio)
  bench     the benchmark's total return over the same window
  gap       total minus bench, in percentage points: positive means ahead

Also: the last distribution, payout frequency, the annualised distribution rate at today's price, trailing
twelve-month cash, price since inception, and days since inception.

Writes site/data/income.json (the records the page draws) and site/data/income_meta.json.

Feed: Tiingo end-of-day. Set TIINGO_TOKEN in the environment or in pipeline/.env (gitignored). One request per
ticker per run; raw responses are cached per day in pipeline/cache/tiingo/ so a rerun costs nothing.
Docs: https://www.tiingo.com/documentation/end-of-day
"""
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
CACHE = ROOT / 'pipeline' / 'cache' / 'tiingo'
WINDOWS = {'3M': 91, '6M': 182, '1Y': 365, '3Y': 365 * 3}


def token():
    t = os.environ.get('TIINGO_TOKEN')
    env = ROOT / 'pipeline' / '.env'
    if not t and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('TIINGO_TOKEN='):
                t = line.split('=', 1)[1].strip().strip('"').strip("'")
    return t


def prices(ticker, tok, start='2010-01-01'):
    """Daily rows: date, close, adjClose, divCash, splitFactor. Cached per ticker per day."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f'{ticker}-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    url = f'https://api.tiingo.com/tiingo/daily/{urllib.parse.quote(ticker)}/prices?' + urllib.parse.urlencode(
        {'startDate': start, 'format': 'json', 'columns': 'date,close,adjClose,divCash,splitFactor', 'token': tok})
    req = urllib.request.Request(url, headers={'User-Agent': 'ETFIQ-income/0.1', 'Accept': 'application/json'})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                rows = json.loads(r.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                rows = []
                break
            if e.code == 429:
                time.sleep(20 * (i + 1))
                continue
            raise
    else:
        rows = []
    rows = [{'date': x['date'][:10], 'close': x.get('close'), 'adjClose': x.get('adjClose'), 'divCash': x.get('divCash') or 0.0,
             'splitFactor': x.get('splitFactor') or 1.0} for x in rows if x.get('close')]
    p.write_text(json.dumps(rows))
    time.sleep(0.25)
    return rows


def trim_history(rows, max_gap_days=45):
    """Keep only the current security's history. A gap of more than max_gap_days between trading days means the
    ticker was reused or relisted (GLDN carried a dead 2016 stub; GATE carried a SPAC), so everything before the last
    such gap is dropped. Prices below a cent are treated the same way."""
    if not rows:
        return rows
    start = 0
    for i in range(1, len(rows)):
        a, b = datetime.date.fromisoformat(rows[i - 1]['date']), datetime.date.fromisoformat(rows[i]['date'])
        if (b - a).days > max_gap_days or (rows[i - 1]['close'] or 0) < 0.01:
            start = i
    return rows[start:]


def split_adjust(rows):
    """Add sclose (split-adjusted close) and sdiv (split-adjusted cash) so history is on today's share basis."""
    factor = 1.0
    for r in reversed(rows):
        r['sclose'] = r['close'] / factor
        r['sdiv'] = r['divCash'] / factor
        if r.get('splitFactor') and r['splitFactor'] != 1.0:
            factor *= r['splitFactor']
    return rows


def at_or_before(rows, d):
    """Index of the last row on or before date d, or None."""
    lo, hi, best = 0, len(rows) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if rows[mid]['date'] <= d:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def window(rows, brows, days):
    """Return metrics for the trailing window of `days`, or None if the fund is younger than the window."""
    if not rows:
        return None
    end = rows[-1]
    start_date = (datetime.date.fromisoformat(end['date']) - datetime.timedelta(days=days)).isoformat()
    if rows[0]['date'] > start_date:
        return None
    i = at_or_before(rows, start_date)
    if i is None:
        return None
    s = rows[i]
    cash = sum(r['sdiv'] for r in rows[i + 1:])
    out = {'from': s['date'], 'to': end['date'], 'days': days,
           'cash': round(cash / s['sclose'] * 100, 2), 'price': round((end['sclose'] / s['sclose'] - 1) * 100, 2),
           'total': round((end['adjClose'] / s['adjClose'] - 1) * 100, 2), 'bench': None, 'gap': None}
    if brows:
        bi = at_or_before(brows, s['date'])
        be = at_or_before(brows, end['date'])
        if bi is not None and be is not None and brows[be]['date'] > brows[bi]['date']:
            out['bench'] = round((brows[be]['adjClose'] / brows[bi]['adjClose'] - 1) * 100, 2)
            out['gap'] = round(out['total'] - out['bench'], 2)
    return out


def frequency(rows):
    divs = [r for r in rows if r['divCash'] > 0]
    if len(divs) < 3:
        return None, divs
    gaps = [(datetime.date.fromisoformat(b['date']) - datetime.date.fromisoformat(a['date'])).days for a, b in zip(divs[-7:-1], divs[-6:])]
    g = sorted(gaps)[len(gaps) // 2]
    return ('weekly' if g <= 9 else 'monthly' if g <= 45 else 'quarterly' if g <= 120 else 'annual'), divs


def build():
    tok = token()
    if not tok:
        sys.exit('No TIINGO_TOKEN. Set it in the environment or in pipeline/.env, then rerun.')
    universe = [r for r in json.loads((ROOT / 'data' / 'income_universe.json').read_text()) if r.get('include')]
    bench_cache, out, missing = {}, [], []
    for i, u in enumerate(universe):
        rows = split_adjust(trim_history(prices(u['ticker'], tok)))
        if len(rows) < 5:
            missing.append(u['ticker'])
            continue
        b = u['benchmark']
        if b not in bench_cache:
            bench_cache[b] = split_adjust(trim_history(prices(b, tok)))
        brows = bench_cache[b]
        freq, divs = frequency(rows)
        last = divs[-1] if divs else None
        per_year = {'weekly': 52, 'monthly': 12, 'quarterly': 4, 'annual': 1}.get(freq, 12)
        end = rows[-1]
        t12 = sum(r['sdiv'] for r in rows if r['date'] > (datetime.date.fromisoformat(end['date']) - datetime.timedelta(days=365)).isoformat())
        rec = dict(u)
        rec.update({
            'asOf': end['date'], 'price': end['close'], 'inception': rows[0]['date'],
            'daysSinceInception': (datetime.date.fromisoformat(end['date']) - datetime.date.fromisoformat(rows[0]['date'])).days,
            'payoutFrequency': freq, 'lastDistribution': ({'date': last['date'], 'amount': last['divCash']} if last else None),
            'distributionRate': (round(last['divCash'] * per_year / end['close'] * 100, 2) if last else None),
            'trailing12mCash': round(t12 / end['close'] * 100, 2),
            'priceSinceInception': round((end['sclose'] / rows[0]['sclose'] - 1) * 100, 2),
            'windows': {k: window(rows, brows, d) for k, d in WINDOWS.items()},
            'distributions': [{'date': r['date'], 'amount': r['divCash']} for r in divs[-13:]],
            'benchAsOf': brows[-1]['date'] if brows else None,
        })
        # since inception window
        s = rows[0]
        itd = {'from': s['date'], 'to': end['date'], 'days': rec['daysSinceInception'], 'cash': round(sum(r['sdiv'] for r in rows[1:]) / s['sclose'] * 100, 2),
               'price': rec['priceSinceInception'], 'total': round((end['adjClose'] / s['adjClose'] - 1) * 100, 2), 'bench': None, 'gap': None}
        if brows:
            bi, be = at_or_before(brows, s['date']), at_or_before(brows, end['date'])
            if bi is not None and be is not None and brows[be]['date'] > brows[bi]['date']:
                itd['bench'] = round((brows[be]['adjClose'] / brows[bi]['adjClose'] - 1) * 100, 2)
                itd['gap'] = round(itd['total'] - itd['bench'], 2)
        rec['windows']['ITD'] = itd
        out.append(rec)
        if (i + 1) % 25 == 0:
            print(f'  {i + 1} of {len(universe)}', file=sys.stderr)
    out.sort(key=lambda r: (r['issuer'], r['ticker']))
    meta = {'asOf': max((r['asOf'] for r in out), default=TODAY.isoformat()), 'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'universe': len(universe), 'shown': len(out), 'missing': missing, 'benchmarks': sorted(bench_cache), 'feed': 'Tiingo end-of-day'}
    (ROOT / 'site' / 'data').mkdir(parents=True, exist_ok=True)
    (ROOT / 'site' / 'data' / 'income.json').write_text(json.dumps(out, separators=(',', ':')))
    (ROOT / 'site' / 'data' / 'income_meta.json').write_text(json.dumps(meta, indent=1))
    (ROOT / 'data' / 'snapshots').mkdir(parents=True, exist_ok=True)
    (ROOT / 'data' / 'snapshots' / f'income-{TODAY.isoformat()}.json').write_text(json.dumps({'meta': meta, 'funds': out}, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == '__main__':
    build()
