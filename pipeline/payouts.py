#!/usr/bin/env python3
"""ETFIQ payout calendar: what is paying, when, and how much.

For every fund on the income desk, assemble the recent and upcoming distribution schedule from two sources and
one projection, and say which is which:

  declared    Nasdaq's dividend history API, which carries declaration, ex, record and pay dates for funds listed
              on Nasdaq. Where it has an upcoming ex-date, that row is the issuer's declared distribution.
  history     the Tiingo price cache (ex-dates and cash amounts), already pulled by income.py.
  estimated   projected from the fund's own cadence (median gap between recent ex-dates) and its last amount,
              with the pay date set by the fund's usual ex-to-pay lag where known, otherwise two days.

Output site/data/payouts.json, one record per fund:
  ticker, frequency, cadenceDays, lagDays, source, last {ex, pay, amount, declared}, next [{ex, pay, amount, status}]
where status is 'declared' or 'estimated'. Horizon: 45 days ahead. Cached per day in pipeline/cache/nasdaq/.
"""
import datetime
import html as htmlmod
import json
import pathlib
import re
import statistics
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
HORIZON = 45
CACHE = ROOT / 'pipeline' / 'cache' / 'nasdaq'
H = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',
     'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'en-US,en;q=0.9', 'Origin': 'https://www.nasdaq.com', 'Referer': 'https://www.nasdaq.com/'}


def text(x):
    return re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', ' ', x))).strip()


def yieldmax():
    """YieldMax publishes declaration, ex and pay dates for the year, per payer group. Dates only; amounts come later."""
    p = CACHE / f'yieldmax-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    out = {'groups': {}, 'weekly': [], 'monthly': [], 'quarterly': []}
    try:
        req = urllib.request.Request('https://www.yieldmaxetfs.com/distribution-schedule/', headers={'User-Agent': H['User-Agent'], 'Accept': 'text/html,*/*'})
        with urllib.request.urlopen(req, timeout=40) as r:
            s = r.read().decode('utf-8', 'replace')
        tables = re.findall(r'<table[^>]*>(.*?)</table>', s, re.S)
        rows = lambda tb: [[text(td) for td in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)] for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb, re.S)]
        schedules = []
        for tb in tables:
            rr = rows(tb)
            if rr and any('Group' in c for c in rr[0]):
                ngroups = max(1, sum(1 for c in rr[0] if 'Group' in c))
                for row in rr[1:]:
                    per = max(1, len(row) // ngroups)
                    for ci, tk in enumerate(row):
                        if re.fullmatch(r'[A-Z]{2,5}', tk):
                            out['groups'][tk] = min(ci // per, ngroups - 1)
                continue
            dated = [x for x in rr if len(x) >= 3 and re.search(r'\d{4}', x[-1])]
            if dated:
                schedules.append(dated)
        def parse(sch):
            o = []
            for row in sch:
                try:
                    d = [datetime.datetime.strptime(c, '%A, %B %d, %Y').date().isoformat() for c in row[-3:]]
                except ValueError:
                    continue
                o.append({'declared': d[0], 'ex': d[1], 'pay': d[2]})
            return o
        out['weekly'] = [parse(x) for x in schedules if len(x) >= 40]
        m = next((x for x in schedules if 10 <= len(x) <= 14 and not x[0][0].startswith('Q')), None)
        q = next((x for x in schedules if x and x[0][0].startswith('Q')), None)
        out['monthly'] = parse(m) if m else []
        out['quarterly'] = parse(q) if q else []
    except Exception:
        pass
    p.write_text(json.dumps(out))
    return out


def us(d):
    """'09/01/2026' -> date, or None."""
    try:
        m, dd, y = d.split('/')
        return datetime.date(int(y), int(m), int(dd))
    except Exception:
        return None


def weekday(d):
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d


def nasdaq(ticker):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f'{ticker}-{TODAY.isoformat()}.json'
    if p.exists():
        return json.loads(p.read_text())
    rows = []
    try:
        req = urllib.request.Request(f'https://api.nasdaq.com/api/quote/{ticker}/dividends?assetclass=etf', headers=H)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode('utf-8', 'replace'))
        for x in (d.get('data') or {}).get('dividends', {}).get('rows') or []:
            ex, pay, dec = us(x.get('exOrEffDate', '')), us(x.get('paymentDate', '')), us(x.get('declarationDate', ''))
            amt = x.get('amount', '').replace('$', '').replace(',', '')
            try:
                amt = float(amt)
            except ValueError:
                continue
            if ex:
                rows.append({'ex': ex.isoformat(), 'pay': pay.isoformat() if pay else None, 'declared': dec.isoformat() if dec else None, 'amount': amt})
    except Exception:
        rows = []
    p.write_text(json.dumps(rows))
    time.sleep(0.4)
    return rows


def history(ticker):
    p = ROOT / 'pipeline' / 'cache' / 'tiingo' / f'{ticker}-{TODAY.isoformat()}.json'
    if not p.exists():
        cands = sorted((ROOT / 'pipeline' / 'cache' / 'tiingo').glob(f'{ticker}-*.json'))
        if not cands:
            return []
        p = cands[-1]
    rows = json.loads(p.read_text())
    return [{'ex': r['date'], 'amount': r['divCash']} for r in rows if r.get('divCash')]


def schedule(ticker, freq, issuer=None, ym=None):
    hist = history(ticker)
    nq = nasdaq(ticker)
    today = TODAY
    # cadence from the last eight ex-dates
    exs = [datetime.date.fromisoformat(h['ex']) for h in hist[-8:]]
    gaps = [(b - a).days for a, b in zip(exs, exs[1:]) if (b - a).days > 0]
    cadence = int(statistics.median(gaps)) if len(gaps) >= 2 else ({'weekly': 7, 'monthly': 30, 'quarterly': 91}.get(freq) or None)
    # ex-to-pay lag from Nasdaq history where available
    past = sorted([r for r in nq if r.get('pay') and r['ex'] <= today.isoformat()], key=lambda r: r['ex'])
    lags = [(datetime.date.fromisoformat(r['pay']) - datetime.date.fromisoformat(r['ex'])).days for r in past[-6:]]
    lags = [x for x in lags if 0 <= x <= 40]
    lag = int(statistics.median(lags)) if lags else (1 if cadence and cadence <= 9 else 2)
    last = hist[-1] if hist else None
    last_nq = next((r for r in sorted(nq, key=lambda r: r['ex']) if r['ex'] <= today.isoformat()), None)
    last_rec = None
    if last:
        pay = next((r['pay'] for r in nq if r['ex'] == last['ex'] and r.get('pay')), None)
        last_rec = {'ex': last['ex'], 'amount': last['amount'], 'pay': pay or weekday(datetime.date.fromisoformat(last['ex']) + datetime.timedelta(days=lag)).isoformat(),
                    'declared': next((r['declared'] for r in nq if r['ex'] == last['ex']), None), 'payKnown': bool(pay)}
    nxt = []
    declared = sorted([r for r in nq if r['ex'] > today.isoformat()], key=lambda r: r['ex'])
    for r in declared:
        nxt.append({'ex': r['ex'], 'pay': r['pay'] or weekday(datetime.date.fromisoformat(r['ex']) + datetime.timedelta(days=lag)).isoformat(), 'amount': r['amount'], 'status': 'declared', 'declaredOn': r.get('declared')})
    # issuer-published dates (YieldMax): dates are official, the amount is the last payment until declared
    if issuer == 'YieldMax' and ym and last:
        sched = None
        if ticker in ym['groups'] and ym['groups'][ticker] < len(ym['weekly']):
            sched = ym['weekly'][ym['groups'][ticker]]
        elif cadence and 25 <= cadence <= 35:
            sched = ym['monthly']
        elif cadence and cadence >= 80:
            sched = ym['quarterly']
        for r in (sched or []):
            if r['ex'] > today.isoformat() and (datetime.date.fromisoformat(r['ex']) - today).days <= HORIZON and not any(abs((datetime.date.fromisoformat(n['ex']) - datetime.date.fromisoformat(r['ex'])).days) <= 2 for n in nxt):
                nxt.append({'ex': r['ex'], 'pay': r['pay'], 'amount': last['amount'], 'status': 'scheduled', 'declaredOn': r['declared']})
        nxt.sort(key=lambda n: n['ex'])
    if cadence and last:
        d = datetime.date.fromisoformat(nxt[-1]['ex'] if nxt else last['ex'])
        amount = nxt[-1]['amount'] if nxt else last['amount']
        while True:
            d = weekday(d + datetime.timedelta(days=cadence))
            if d <= today:
                continue
            if (d - today).days > HORIZON:
                break
            if any(abs((datetime.date.fromisoformat(n['ex']) - d).days) <= 3 for n in nxt):
                continue
            nxt.append({'ex': d.isoformat(), 'pay': weekday(d + datetime.timedelta(days=lag)).isoformat(), 'amount': amount, 'status': 'estimated'})
    nxt.sort(key=lambda n: n['ex'])
    return {'ticker': ticker, 'frequency': freq, 'cadenceDays': cadence, 'lagDays': lag, 'source': 'nasdaq' if nq else ('issuer schedule' if any(x['status'] == 'scheduled' for x in nxt) else 'projection'),
            'last': last_rec, 'next': nxt[:8], 'history': [{'ex': h['ex'], 'amount': h['amount']} for h in hist[-13:]]}


def build():
    income = json.loads((ROOT / 'site' / 'data' / 'income.json').read_text())
    ym = yieldmax()
    print(f"  YieldMax schedule: {len(ym['groups'])} grouped tickers, {len(ym['weekly'])} weekly tables, {len(ym['monthly'])} monthly rows")
    # prefetch Nasdaq history in parallel; the per-day cache makes the sequential pass below instant
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda r: nasdaq(r['ticker']), income))
    print('  nasdaq prefetch done')
    out = []
    for i, r in enumerate(income):
        out.append(schedule(r['ticker'], r.get('payoutFrequency'), r.get('issuer'), ym))
        if (i + 1) % 50 == 0:
            print(f'  {i + 1} of {len(income)}')
    (ROOT / 'site' / 'data' / 'payouts.json').write_text(json.dumps(out, separators=(',', ':')))
    declared = sum(1 for o in out if any(n['status'] in ('declared', 'scheduled') for n in o['next']))
    est = sum(1 for o in out if o['next'] and all(n['status'] == 'estimated' for n in o['next']))
    print(json.dumps({'funds': len(out), 'withDeclared': declared, 'estimatedOnly': est, 'noSchedule': sum(1 for o in out if not o['next']), 'asOf': TODAY.isoformat()}, indent=1))


if __name__ == '__main__':
    build()
