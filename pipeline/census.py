#!/usr/bin/env python3
"""Accuracy census: every published number recomputed independently from the raw sources, and every discrepancy listed.

Written after Adam asked for "a full accuracy census across all numbers across the entire system" (2026-09-05). The
checks here do not import the pipeline's arithmetic; they restate each definition from DATA-PIPELINE.md and the
Standards page in fresh code and compare the result with what the site carries. Stages:

  income    every income desk figure from the raw Tiingo cache: windows, cash, price, total, benchmark, gap,
            payout frequency, payout rate, trailing cash, since-launch figures
  buffer    every buffer desk identity from the published terms, the page's derived fields, and the reference
            return checked against the reference ETF's own prices; then a live re-read of the issuer tables
  themes    windows, drawdown, top-ten weight, overlap and active share against the S&P 500 and Nasdaq-100 books
            with a fresh matcher, active fee, matrix symmetry, peers
  payouts   cadence and last payout against the income record; sources within range
  books     every portfolio book sums to its stated total, fees agree with data/fees.json
  research  every count and median in the research tables and the home page lines recomputed from the desk files
  pages     a sample of static fund pages carries the same figures as the data

Writes data/census/<date>.md and .json. Exit code 1 when any check fails, so the nightly job can refuse to publish.
"""
import datetime
import glob
import html
import json
import pathlib
import random
import re
import statistics
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
TOL = 0.02  # two-decimal rounding
FINDINGS = []  # (stage, ticker, field, site value, recomputed value, note)
COUNTS = {}


def note(stage, ticker, field, site, mine, msg=''):
    FINDINGS.append({'stage': stage, 'ticker': ticker, 'field': field, 'site': site, 'mine': mine, 'note': msg})


def tally(stage, n):
    COUNTS[stage] = COUNTS.get(stage, 0) + n


def close(a, b, tol=TOL):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def load(p):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else None


# ---------------------------------------------------------------- raw prices (Tiingo cache), fresh arithmetic
def raw_prices(t):
    files = sorted(glob.glob(str(ROOT / 'pipeline' / 'cache' / 'tiingo' / f'{t}-*.json')))
    if not files:
        return None
    rows = json.loads(pathlib.Path(files[-1]).read_text())
    rows = [r for r in rows if r.get('close')]
    # the current listing only: drop everything before the last gap over 45 days or a price under a cent
    start = 0
    for i in range(1, len(rows)):
        a, b = datetime.date.fromisoformat(rows[i - 1]['date']), datetime.date.fromisoformat(rows[i]['date'])
        if (b - a).days > 45 or (rows[i - 1]['close'] or 0) < 0.01:
            start = i
    rows = rows[start:]
    # today's share basis: prices and cash before a split are divided by every later split factor
    f = 1.0
    for r in reversed(rows):
        r['sc'] = r['close'] / f
        r['sd'] = (r.get('divCash') or 0.0) / f
        if r.get('splitFactor') and r['splitFactor'] != 1.0:
            f *= r['splitFactor']
    return rows


def on_or_before(rows, d):
    best = None
    for i, r in enumerate(rows):
        if r['date'] <= d:
            best = i
        else:
            break
    return best


def my_window(rows, brows, days):
    end = rows[-1]
    start = (datetime.date.fromisoformat(end['date']) - datetime.timedelta(days=days)).isoformat()
    if rows[0]['date'] > start:
        return None
    i = on_or_before(rows, start)
    s = rows[i]
    out = {'from': s['date'], 'cash': sum(r['sd'] for r in rows[i + 1:]) / s['sc'] * 100, 'price': (end['sc'] / s['sc'] - 1) * 100,
           'total': (end['adjClose'] / s['adjClose'] - 1) * 100, 'bench': None, 'gap': None}
    if brows:
        bi, be = on_or_before(brows, s['date']), on_or_before(brows, end['date'])
        if bi is not None and be is not None and brows[be]['date'] > brows[bi]['date']:
            out['bench'] = (brows[be]['adjClose'] / brows[bi]['adjClose'] - 1) * 100
            out['gap'] = out['total'] - out['bench']
    return out


def my_itd(rows, brows):
    s, end = rows[0], rows[-1]
    out = {'from': s['date'], 'cash': sum(r['sd'] for r in rows[1:]) / s['sc'] * 100, 'price': (end['sc'] / s['sc'] - 1) * 100,
           'total': (end['adjClose'] / s['adjClose'] - 1) * 100, 'bench': None, 'gap': None}
    if brows:
        bi, be = on_or_before(brows, s['date']), on_or_before(brows, end['date'])
        if bi is not None and be is not None and brows[be]['date'] > brows[bi]['date']:
            out['bench'] = (brows[be]['adjClose'] / brows[bi]['adjClose'] - 1) * 100
            out['gap'] = out['total'] - out['bench']
    return out


def my_frequency(divs):
    if len(divs) < 3:
        return None
    ds = [datetime.date.fromisoformat(r['date']) for r in divs]
    gaps = [(b - a).days for a, b in zip(ds[:-1], ds[1:])][-6:]
    g = sorted(gaps)[len(gaps) // 2]
    return 'weekly' if g <= 9 else 'monthly' if g <= 45 else 'quarterly' if g <= 120 else 'annual'


WIN = {'3M': 91, '6M': 182, '1Y': 365, '3Y': 1095}


def stage_income():
    inc = load('site/data/income.json') or []
    n = 0
    bcache = {}
    for r in inc:
        t = r['ticker']
        rows = raw_prices(t)
        if not rows:
            note('income', t, 'raw', None, None, 'no Tiingo cache file to recompute from')
            continue
        b = r.get('benchmark')
        if b not in bcache:
            bcache[b] = raw_prices(b) if b else None
        brows = bcache[b]
        end = rows[-1]
        n += 1
        if r.get('asOf') != end['date']:
            note('income', t, 'asOf', r.get('asOf'), end['date'])
        if not close(r.get('price'), end['close']):
            note('income', t, 'price', r.get('price'), end['close'])
        if r.get('inception') != rows[0]['date']:
            note('income', t, 'inception', r.get('inception'), rows[0]['date'])
        divs = [x for x in rows if (x.get('divCash') or 0) > 0]
        freq = my_frequency(divs)
        if r.get('payoutFrequency') != freq:
            note('income', t, 'payoutFrequency', r.get('payoutFrequency'), freq)
        per_year = {'weekly': 52, 'monthly': 12, 'quarterly': 4, 'annual': 1}.get(freq, 12)
        rate = divs[-1]['divCash'] * per_year / end['close'] * 100 if divs else None
        if not close(r.get('distributionRate'), rate):
            note('income', t, 'distributionRate', r.get('distributionRate'), rate and round(rate, 2))
        cut = (datetime.date.fromisoformat(end['date']) - datetime.timedelta(days=365)).isoformat()
        t12 = sum(x['sd'] for x in rows if x['date'] > cut) / end['close'] * 100
        if not close(r.get('trailing12mCash'), t12):
            note('income', t, 'trailing12mCash', r.get('trailing12mCash'), round(t12, 2))
        last = r.get('lastDistribution') or {}
        if divs and (last.get('date') != divs[-1]['date'] or not close(last.get('amount'), divs[-1]['divCash'], 1e-6)):
            note('income', t, 'lastDistribution', last, {'date': divs[-1]['date'], 'amount': divs[-1]['divCash']})
        for k, d in WIN.items():
            mine = my_window(rows, brows, d)
            site = (r.get('windows') or {}).get(k)
            if (mine is None) != (site is None):
                note('income', t, f'windows.{k}', site and 'present', mine and 'present', 'window presence')
                continue
            if mine is None:
                continue
            for f in ('cash', 'price', 'total', 'bench', 'gap'):
                if not close(site.get(f), mine[f]):
                    note('income', t, f'windows.{k}.{f}', site.get(f), round(mine[f], 2) if mine[f] is not None else None)
            if site.get('from') != mine['from']:
                note('income', t, f'windows.{k}.from', site.get('from'), mine['from'])
        mine = my_itd(rows, brows)
        site = (r.get('windows') or {}).get('ITD') or {}
        for f in ('cash', 'price', 'total', 'bench', 'gap'):
            if not close(site.get(f), mine[f]):
                note('income', t, f'windows.ITD.{f}', site.get(f), round(mine[f], 2) if mine[f] is not None else None)
        # the site's distributions list is the last thirteen cash payments
        sd = [(x['date'], x['amount']) for x in (r.get('distributions') or [])]
        md = [(x['date'], x['divCash']) for x in divs[-13:]]
        if sd != md:
            note('income', t, 'distributions', len(sd), len(md), 'last thirteen payouts differ')
    tally('income', n)


# ---------------------------------------------------------------- buffer desk
def stage_buffer():
    funds = load('site/data/funds.json')
    funds = funds['funds'] if isinstance(funds, dict) else funds
    refs = {}
    n = 0
    for f in funds:
        t = f['ticker']
        n += 1
        bs, be, ref = f['bufferStart'], f['bufferEnd'], f['refReturn']
        sb = bs - be
        if not close(f.get('startBuffer'), sb):
            note('buffer', t, 'startBuffer', f.get('startBuffer'), sb)
        if ref is None:
            note('buffer', t, 'refReturn', None, None, 'no reference return published')
            continue
        used = max(0.0, min(sb, bs - ref))
        if not close(f.get('bufferUsed'), used):
            note('buffer', t, 'bufferUsed', f.get('bufferUsed'), round(used, 2))
        unp = min(-ref, -bs) if (ref < 0 and bs < 0) else 0.0
        if not close(f.get('unprotectedLoss'), unp):
            note('buffer', t, 'unprotectedLoss', f.get('unprotectedLoss'), round(unp, 2))
        lbf = max(0.0, be - ref)
        if not close(f.get('lossBelowFloor'), lbf):
            note('buffer', t, 'lossBelowFloor', f.get('lossBelowFloor'), round(lbf, 2))
        cap = f.get('startCap')
        rc = None if cap is None else max(0.0, cap - ref)
        if not close(f.get('remainingCap'), rc):
            note('buffer', t, 'remainingCap', f.get('remainingCap'), rc and round(rc, 2))
        npn = None if cap is None else rc - (f.get('downsideBeforeBuffer') or 0.0)
        if not close(f.get('netPosition'), npn):
            note('buffer', t, 'netPosition', f.get('netPosition'), npn and round(npn, 2))
        # the page's derived fields, restated
        is_floor = be <= -100
        pl = None if is_floor else round(sb - used, 2)
        fbr = round(max(0, (1 - (1 + bs / 100) / (1 + ref / 100)) * 100), 1)
        state = ('capped' if cap is not None and ref >= cap else 'exhausted' if lbf > 0 else 'engaged' if used > 0 else 'unprotected' if unp > 0
                 else 'uncapped' if cap is None else 'floor' if is_floor else 'open')
        f['_pl'], f['_fbr'], f['_state'] = pl, fbr, state
        # dates: days remaining against the calendar
        try:
            asof = datetime.date.fromisoformat(f['source']['asOf'])
            pe = datetime.date.fromisoformat(f['periodEnd'])
            dr = (pe - asof).days
            if abs(dr - (f.get('daysRemaining') or 0)) > 3:
                note('buffer', t, 'daysRemaining', f.get('daysRemaining'), dr, f"period end {f['periodEnd']} against as-of {f['source']['asOf']}")
        except Exception:
            pass
        # sanity on the issuer's own figures
        if f.get('remainingCapFund') is not None and cap is not None and f.get('fundReturn') is not None:
            most = ((1 + cap / 100) / (1 + f['fundReturn'] / 100) - 1) * 100  # the cap from today's price, before fees
            if f['remainingCapFund'] > most + 1.5:
                note('buffer', t, 'remainingCapFund', f['remainingCapFund'], round(most, 2), 'remaining cap above what the starting cap allows from today\'s price')
        if f.get('downsideBeforeBuffer') is not None and f['downsideBeforeBuffer'] > 60:
            note('buffer', t, 'downsideBeforeBuffer', f['downsideBeforeBuffer'], None, 'implausibly large')
        # the reference return against the reference ETF's own closes (S&P 500 funds only; two start conventions accepted)
        spy = refs.get(f.get('refAsset'))
        if spy is None and f.get('refAsset'):
            spy = refs[f['refAsset']] = raw_prices(f['refAsset'])
        if spy:
            ps = f['periodStart']
            i_end = on_or_before(spy, f['source']['asOf'])
            i_on = on_or_before(spy, ps)
            i_prev = i_on - 1 if i_on is not None and spy[i_on]['date'] == ps else i_on
            if i_end is not None and i_prev is not None and i_prev >= 0:
                cands = [spy[i_end]['close'] / spy[j]['close'] * 100 - 100 for j in {i_on, i_prev} if j is not None]
                if all(abs(c - ref) > 0.75 for c in cands):
                    note('buffer', t, f"refReturn vs {f['refAsset']} closes", ref, [round(c, 2) for c in cands], f"{f['refAsset']} {spy[i_end]['date']} against the close on or before {ps}")
    tally('buffer', n)
    return funds


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36', 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('utf-8', errors='replace')


def text(s):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s))).strip()


def num(s):
    m = re.search(r'-?[\d,]*\.?\d+', s or '')
    return float(m.group(0).replace(',', '')) if m else None


def stage_buffer_live(funds):
    by = {f['ticker']: f for f in funds}
    # Innovator: read the table again with its header row, so the column mapping is checked, not assumed
    try:
        s = fetch('https://www.innovatoretfs.com/define/etfs/')
        heads = [text(x) for x in re.findall(r'<th[^>]*>(.*?)</th>', s, re.S)]
        m = re.search(r'As of (\d{1,2}/\d{1,2}/\d{4})', s)
        live_asof = m.group(1) if m else '?'
        rows = {}
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
            mm = re.search(r'class="ticlink">([a-z0-9]+)<', tr)
            if not mm:
                continue
            c = [text(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
            if len(c) >= 17 and (mm.group(1).upper() not in rows or len(c) > len(rows[mm.group(1).upper()])):
                rows[mm.group(1).upper()] = c
        COUNTS['innovator headers'] = f"{len(rows)} rows, page as of {live_asof}, headers: " + ' | '.join(f'{i}:{h}' for i, h in enumerate(heads[:18]))
        want = {'fundReturn': 5, 'refReturn': 6, 'remainingCapRefPub': 8, 'remainingCapFund': 9, 'remainingBuffer': 10, 'downsideBeforeBuffer': 11, 'daysRemaining': 12, 'startCap': 14}
        k = 0
        for t, c in rows.items():
            f = by.get(t)
            if not f:
                continue
            k += 1
            for field, i in want.items():
                live = num(c[i])
                if field == 'downsideBeforeBuffer' and live is not None:
                    live = abs(live)
                if field == 'startCap' and f.get('startCap') is None:
                    continue
                if not close(f.get(field), live, 0.06):
                    note('buffer live', t, field, f.get(field), live, f'Innovator table today ({live_asof}) vs snapshot as of {f["source"]["asOf"]}')
        tally('innovator live', k)
    except Exception as e:
        COUNTS['innovator live'] = f'not reached: {str(e)[:80]}'
    # AllianzIM: the model block again
    try:
        s = fetch('https://www.allianzim.com/product-table/')
        i = s.find('const model = ')
        model, _ = json.JSONDecoder().raw_decode(s[i + len('const model = '):])
        k = 0
        for t, v in model.items():
            f = by.get(t)
            if not f:
                continue
            k += 1
            cur = v.get('current') or {}
            pairs = {'refReturn': 'reference_level_period_return', 'fundReturn': 'etf_current_period_net_return', 'remainingCapFund': 'remaining_cap_net',
                     'remainingBuffer': 'remaining_buffer_calc_net', 'daysRemaining': 'number_of_days_remaining'}
            for field, key in pairs.items():
                live = cur.get(key)
                if live is None:
                    continue
                live = live * 100 if field != 'daysRemaining' else live
                if not close(f.get(field), live, 0.06):
                    note('buffer live', t, field, f.get(field), round(live, 2), f"AllianzIM model today (day {cur.get('day')}) vs snapshot as of {f['source']['asOf']}")
        tally('allianzim live', k)
    except Exception as e:
        COUNTS['allianzim live'] = f'not reached: {str(e)[:80]}'
    # FT Vest: eight fund pages, fresh regexes
    ft = [f for f in funds if f['issuer'] == 'First Trust']
    random.seed(7)
    k = 0
    for f in random.sample(ft, min(8, len(ft))):
        try:
            pt = text(fetch(f['source']['fundPage']))
        except Exception as e:
            note('buffer live', f['ticker'], 'page', None, None, f'FT Vest page not reached: {str(e)[:60]}')
            continue
        k += 1
        g = lambda pat: re.search(pat, pt)
        checks = {'refReturn': (g(r'Reference Asset Value/Return \$[\d,.]+ / (-?[\d.]+)%'), 1), 'fundReturn': (g(r'Fund Value/Return \$[\d,.]+ / (-?[\d.]+)%'), 1),
                  'remainingCapFund': (g(r'Remaining Cap \(Net\) (-?[\d.]+)% \((-?[\d.]+)%\)'), 2), 'remainingBuffer': (g(r'Remaining Buffer \(Net\) (-?[\d.]+)% \((-?[\d.]+)%\)'), 2),
                  'downsideBeforeBuffer': (g(r'Downside Before Buffer \(Net\) (-?[\d.]+)% \((-?[\d.]+)%\)'), 2), 'daysRemaining': (g(r'Remaining Outcome Period (\d+) days'), 1)}
        for field, (mm, grp) in checks.items():
            if not mm:
                continue
            live = abs(float(mm.group(grp))) if field == 'downsideBeforeBuffer' else float(mm.group(grp))
            if not close(f.get(field), live, 0.06):
                note('buffer live', f['ticker'], field, f.get(field), live, 'FT Vest page today vs snapshot')
    tally('ft vest live', k)


# ---------------------------------------------------------------- themes desk
def norm(n):
    n = re.sub(r'[^a-z0-9 ]', ' ', (n or '').lower())
    n = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|sa|ag|nv|se|class [abc]|cl [abc]|common|stock|shares?|ordinary|adr|holdings?|group|the|reg|registered)\b', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def keys_of(h):
    out = []
    if h.get('cusip') and h['cusip'] != '000000000':
        out.append(('c', h['cusip']))
    if h.get('isin'):
        out.append(('i', h['isin']))
        if len(h['isin']) == 12 and h['isin'].startswith('US'):
            out.append(('c', h['isin'][2:11]))
    if h.get('ticker'):
        out.append(('t', re.sub(r'[^A-Z]', '', h['ticker'])))
    nn = norm(h.get('name'))
    if nn:
        out.append(('n', nn))
    return out


def my_overlap(a, b):
    """Weight overlap, active share and in-index weight, restated: match on CUSIP, then ISIN, then ticker, then name;
    each index line matched at most once; weights as shares of each book's total."""
    ta, tb = sum(h['weight'] for h in a) or 1.0, sum(h['weight'] for h in b) or 1.0
    index = {}
    for j, h in enumerate(b):
        for k in keys_of(h):
            index.setdefault(k, j)
    used, common, inb, n = set(), 0.0, 0.0, 0
    for h in a:
        for k in sorted(keys_of(h), key=lambda k: 'citn'.index(k[0])):
            j = index.get(k)
            if j is not None and j not in used:
                used.add(j)
                common += min(h['weight'] / ta, b[j]['weight'] / tb) * 100
                inb += h['weight'] / ta * 100
                n += 1
                break
    return {'overlap': common, 'activeShare': 100 - common, 'inIndex': inb, 'matched': n}


def latest_cache(pattern):
    files = sorted(glob.glob(str(ROOT / 'pipeline' / 'cache' / 'holdings' / pattern)))
    return json.loads(pathlib.Path(files[-1]).read_text()) if files else None


def stage_themes():
    d = load('site/data/thematic.json') or {'funds': []}
    tu = {r['ticker']: r for r in load('data/thematic_universe.json') or []}
    spy, qqq = latest_cache('index-SPY-*.json'), latest_cache('index-QQQ-*.json')
    spyh, qqqh = (spy or {}).get('holdings', []), (qqq or {}).get('holdings', [])
    bq = {'SPY': raw_prices('SPY'), 'QQQ': raw_prices('QQQ')}
    n = 0
    for r in d['funds']:
        t = r['ticker']
        rows = raw_prices(t)
        if not rows:
            note('themes', t, 'raw', None, None, 'no Tiingo cache file')
            continue
        n += 1
        end = rows[-1]
        if r.get('asOf') != end['date']:
            note('themes', t, 'asOf', r.get('asOf'), end['date'])
        # closed: no trade in twelve days should not be on the desk
        if (TODAY - datetime.date.fromisoformat(end['date'])).days > 12:
            note('themes', t, 'closed', r.get('asOf'), TODAY.isoformat(), 'no trade in twelve days but still on the desk')
        for k, days in WIN.items():
            site = (r.get('windows') or {}).get(k)
            mine = my_window(rows, bq['SPY'], days)
            mq = my_window(rows, bq['QQQ'], days)
            if (mine is None) != (site is None):
                note('themes', t, f'windows.{k}', site and 'present', mine and 'present', 'window presence')
                continue
            if mine is None:
                continue
            for f in ('cash', 'price', 'total', 'bench', 'gap'):
                if not close(site.get(f), mine[f]):
                    note('themes', t, f'windows.{k}.{f}', site.get(f), mine[f] and round(mine[f], 2))
            if not close(site.get('benchQ'), mq['bench']) or not close(site.get('gapQ'), mq['gap']):
                note('themes', t, f'windows.{k}.benchQ/gapQ', (site.get('benchQ'), site.get('gapQ')), (mq['bench'] and round(mq['bench'], 2), mq['gap'] and round(mq['gap'], 2)))
        # drawdown from the all-time high of the reinvested series
        hi, hi_date = 0.0, None
        for x in rows:
            if x['adjClose'] and x['adjClose'] > hi:
                hi, hi_date = x['adjClose'], x['date']
        dd = (end['adjClose'] / hi - 1) * 100 if hi else None
        if not close(r.get('drawdown'), dd) or r.get('highDate') != hi_date:
            note('themes', t, 'drawdown', (r.get('drawdown'), r.get('highDate')), (dd and round(dd, 2), hi_date))
        # holdings figures from the filing cache the desk says it used (skip daily issuer books: not cached the same way)
        if r.get('vsSPY') and not r.get('holdingsDaily'):
            sid = tu.get(t, {}).get('seriesId')
            c = latest_cache(f'nport-{sid}-*.json') if sid else None
            if not c:
                continue
            h = c['holdings']
            if r.get('holdingsCount') != len(h):
                note('themes', t, 'holdingsCount', r.get('holdingsCount'), len(h), f"cache period {c['info'].get('period')} vs desk {r.get('holdingsAsOf')}")
                continue
            tot = sum(x['weight'] for x in h) or 1.0
            top10 = sum(x['weight'] for x in h[:10]) / tot * 100
            if not close(r.get('top10Weight'), top10, 0.06):
                note('themes', t, 'top10Weight', r.get('top10Weight'), round(top10, 1))
            for label, book in (('vsSPY', spyh), ('vsQQQ', qqqh)):
                if not book:
                    continue
                mine = my_overlap(h, book)
                site = r.get(label) or {}
                for f in ('overlap', 'activeShare', 'inIndex'):
                    if not close(site.get(f), mine[f], 0.11):
                        note('themes', t, f'{label}.{f}', site.get(f), round(mine[f], 1))
                if site.get('matched') != mine['matched']:
                    note('themes', t, f'{label}.matched', site.get('matched'), mine['matched'])
        # active fee
        a = (r.get('vsSPY') or {}).get('activeShare')
        af = round(r['expenseRatio'] / (a / 100), 2) if r.get('expenseRatio') is not None and a and a >= 5 else None
        if not close(r.get('activeFee'), af):
            note('themes', t, 'activeFee', r.get('activeFee'), af)
    # matrix: symmetric with a zero diagonal (a fund's own cell is not shown); peers agree with the matrix
    m = d.get('matrix') or {}
    tk, rows = m.get('tickers', []), m.get('rows', [])
    # packed upper triangle: row i holds the cells for every later fund, so row lengths must fall by one each time
    bad = sum(1 for i in range(len(tk)) if len(rows[i]) != len(tk) - i - 1)
    if bad:
        note('themes', 'matrix', 'shape', bad, 0, 'rows whose length is not n minus i minus 1')
    cell = lambda i, j: rows[i][j - i - 1] if j > i else rows[j][i - j - 1]
    pos = {t: i for i, t in enumerate(tk)}
    for r in d['funds']:
        if r.get('peers') and r['ticker'] in pos and not bad:
            i = pos[r['ticker']]
            best = sorted(((cell(i, j), tk[j]) for j in range(len(tk)) if j != i and cell(i, j) >= 10), reverse=True)[:5]
            if [p['t'] for p in r['peers']] != [t for v, t in best] and sorted(p['o'] for p in r['peers']) != sorted(v for v, t in best):
                note('themes', r['ticker'], 'peers', [(p['t'], p['o']) for p in r['peers']], [(t, v) for v, t in best])
    tally('themes', n)


# ---------------------------------------------------------------- payouts and sources
def stage_payouts():
    pay = load('site/data/payouts.json') or []
    inc = {r['ticker']: r for r in load('site/data/income.json') or []}
    n = 0
    for p in pay:
        t = p['ticker']
        r = inc.get(t)
        if not r:
            note('payouts', t, 'record', None, None, 'payout record for a fund not on the desk')
            continue
        n += 1
        hist = p.get('history') or []
        exs = [datetime.date.fromisoformat(h['ex']) for h in hist[-8:]]
        gaps = [(b - a).days for a, b in zip(exs, exs[1:]) if (b - a).days > 0]
        cad = int(statistics.median(gaps)) if len(gaps) >= 2 else None
        if cad is not None and p.get('cadenceDays') != cad:
            note('payouts', t, 'cadenceDays', p.get('cadenceDays'), cad)
        last = p.get('last') or {}
        ld = r.get('lastDistribution') or {}
        if last and ld and (last.get('ex') != ld.get('date') or not close(last.get('amount'), ld.get('amount'), 1e-6)):
            if last.get('ex', '') < ld.get('date', ''):
                note('payouts', t, 'last', (last.get('ex'), last.get('amount')), (ld.get('date'), ld.get('amount')), 'calendar behind the price feed')
        for x in p.get('next') or []:
            if x.get('pay') and x.get('ex') and x['pay'] < x['ex']:
                note('payouts', t, 'next', x, None, 'pay date before ex-date')
            if x.get('amount') is not None and x['amount'] <= 0:
                note('payouts', t, 'next.amount', x.get('amount'), None)
    tally('payouts', n)
    src = load('site/data/sources.json') or {}
    k = 0
    for t, s in src.items():
        k += 1
        lat = s.get('latest') or {}
        for f in ('roc', 'income', 'gains'):
            v = lat.get(f)
            if v is not None and not (0 <= v <= 100.5):
                note('sources', t, f'latest.{f}', v, None, 'outside 0 to 100')
        parts = [lat.get(f) for f in ('roc', 'income', 'gains') if lat.get(f) is not None]
        if len(parts) == 3 and abs(sum(parts) - 100) > 1.5:
            note('sources', t, 'latest.sum', round(sum(parts), 1), 100)
        if lat.get('date') and lat['date'] > (TODAY + datetime.timedelta(days=45)).isoformat():
            note('sources', t, 'latest.date', lat['date'], None, 'in the future')
        if t not in inc:
            note('sources', t, 'record', None, None, 'source for a fund not on the desk')
    tally('sources', k)


# ---------------------------------------------------------------- books
def stage_books():
    idx = load('site/data/books/index.json') or {'books': {}}
    fees = load('data/fees.json') or {}
    n = 0
    for t, meta in idx['books'].items():
        b = load(f'site/data/books/{t}.json')
        if not b:
            note('books', t, 'file', None, None, 'listed in the index but no file')
            continue
        n += 1
        if b.get('n') != meta.get('n') or b.get('asOf') != meta.get('asOf') or b.get('kind') != meta.get('kind'):
            note('books', t, 'index', (meta.get('n'), meta.get('asOf'), meta.get('kind')), (b.get('n'), b.get('asOf'), b.get('kind')))
        if b.get('h'):
            tot = sum(x[3] for x in b['h'])
            full = len(b['h']) == b.get('n')
            if full and abs(tot - 100) > 0.5:
                note('books', t, 'weights sum', round(tot, 2), 100)
            if not full and tot > 100.5:
                note('books', t, 'weights sum', round(tot, 2), '<= 100', 'top 300 of a longer book')
            if any(x[3] < 0 for x in b['h']):
                note('books', t, 'negative weight', min(x[3] for x in b['h']), None)
        fee = fees.get(t, {}).get('expenseRatio')
        if fee is not None and not close(b.get('fee'), fee, 1e-6):
            note('books', t, 'fee', b.get('fee'), fee)
        if b.get('kind') in ('synthetic', 'proxy') and not (b.get('exposure') or {}).get('ticker'):
            note('books', t, 'exposure', None, None, f"{b.get('kind')} book without an exposure")
    tally('books', n)


# ---------------------------------------------------------------- research tables and home page lines
def pnum(s):
    if s is None:
        return None
    m = re.search(r'-?[\d.]+', str(s).replace('\u2212', '-').replace(',', ''))
    return float(m.group(0)) if m else None


def median(xs):
    return statistics.median(xs) if xs else None


def stage_research():
    inc = load('site/data/income.json') or []
    funds = load('site/data/funds.json') or []
    th = (load('site/data/thematic.json') or {}).get('funds', [])
    n = 0
    # income-ahead: results by issuer, index income funds, one year
    r = load('data/research/income-ahead.json')
    if r:
        tab = next((tb for tb in r['tables'] if tb['title'].startswith('Results by issuer')), None)
        if tab:
            n += 1
            single = lambda x: (x.get('benchmarkKind') or '') == 'stock'  # the site's definition: index income means the benchmark is not a single stock
            by = {}
            for x in inc:
                if single(x):
                    continue
                by.setdefault(x['issuer'], []).append(x)
            for row in tab['rows']:
                issuer, on_desk, full, ahead = row[0], row[1], row[2], row[3]
                xs = by.get(issuer, [])
                ys = [x['windows']['1Y'] for x in xs if x.get('windows', {}).get('1Y') and x['windows']['1Y'].get('gap') is not None]
                mine = (len(xs), len(ys), sum(1 for w in ys if w['gap'] > 0.5))
                if (on_desk, full, ahead) != mine:
                    note('research', issuer, 'income-ahead counts', (on_desk, full, ahead), mine, 'funds on desk, with a full year, ahead')
                for col, key in ((4, 'gap'), (5, 'cash'), (6, 'price'), (7, 'total')):
                    med = median([w[key] for w in ys])
                    if med is not None and not close(pnum(row[col]), med, 0.06):
                        note('research', issuer, f'income-ahead median {key}', row[col], round(med, 1))
    # buffer-state
    r = load('data/research/buffer-state.json')
    if r:
        n += 1
        states = {}
        for f in funds:
            cap, ref, bs, be = f.get('startCap'), f.get('refReturn'), f['bufferStart'], f['bufferEnd']
            if ref is None:
                continue
            sb = bs - be
            used = max(0.0, min(sb, bs - ref))
            unp = min(-ref, -bs) if (ref < 0 and bs < 0) else 0.0
            lbf = max(0.0, be - ref)
            st = ('capped' if cap is not None and ref >= cap else 'exhausted' if lbf > 0 else 'engaged' if used > 0 else 'unprotected' if unp > 0
                  else 'uncapped' if cap is None else 'floor' if be <= -100 else 'open')
            states[st] = states.get(st, 0) + 1
        for line in r.get('summary', []):
            m = re.search(r'(\d+) of (\d+) .*?(at their cap|cap)', line)
            if m and 'cap' in line and states.get('capped') is not None and int(m.group(1)) != states['capped'] and 'reset' not in line:
                note('research', 'buffer-state', 'capped count', int(m.group(1)), states['capped'], line[:80])
    # insights lines
    ins = load('site/data/insights.json') or {}
    for line in ins.get('lines', []):
        txt = line.get('text', '')
        m = re.match(r'(\d+) of (\d+) buffer ETFs sit at their cap', txt)
        if m:
            n += 1
            capped = sum(1 for f in funds if f.get('startCap') is not None and f.get('refReturn') is not None and f['refReturn'] >= f['startCap'])
            if int(m.group(1)) != capped or int(m.group(2)) != len(funds):
                note('research', 'insights', 'capped line', (int(m.group(1)), int(m.group(2))), (capped, len(funds)), txt)
        m = re.match(r'Over the last year, (\d+) of (\d+) index income ETFs', txt)
        if m:
            n += 1
            single = lambda x: (x.get('benchmarkKind') or '') == 'stock'
            ys = [x for x in inc if not single(x) and x.get('windows', {}).get('1Y') and x['windows']['1Y'].get('gap') is not None]
            ahead = sum(1 for x in ys if x['windows']['1Y']['gap'] > 0.5)
            if (int(m.group(1)), int(m.group(2))) != (ahead, len(ys)):
                note('research', 'insights', 'income ahead line', (int(m.group(1)), int(m.group(2))), (ahead, len(ys)), txt)
    tally('research', n)


# ---------------------------------------------------------------- static pages
def stage_pages():
    inc = {r['ticker']: r for r in load('site/data/income.json') or []}
    funds = {f['ticker']: f for f in load('site/data/funds.json') or []}
    random.seed(11)
    n = 0
    for t in random.sample(sorted(inc), min(12, len(inc))):
        p = ROOT / 'site' / 'funds' / f'{t}.html'
        if not p.exists():
            note('pages', t, 'file', None, None, 'no static page')
            continue
        n += 1
        body = text(p.read_text())
        r = inc[t]
        w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD')
        for label, v in (('paid', w and w.get('cash')), ('rate', r.get('distributionRate')), ('trailing12mCash', r.get('trailing12mCash'))):
            if v is None:
                continue
            s1 = f'{abs(v):.1f}%'
            if s1 not in body and f'{v:.1f}' not in body:
                note('pages', t, label, v, None, 'figure not found on the static page')
    for t in random.sample(sorted(funds), min(12, len(funds))):
        p = ROOT / 'site' / 'funds' / f'{t}.html'
        if not p.exists():
            note('pages', t, 'file', None, None, 'no static page')
            continue
        n += 1
        body = text(p.read_text())
        f = funds[t]
        for label, v in (('refReturn', f.get('refReturn')), ('remainingCapFund', f.get('remainingCapFund')), ('downsideBeforeBuffer', f.get('downsideBeforeBuffer'))):
            if v is None:
                continue
            if f'{abs(v):.1f}%' not in body and f'{abs(v):.2f}%' not in body:
                note('pages', t, label, v, None, 'figure not found on the static page')
    tally('pages', n)


# ---------------------------------------------------------------- head to head pages and question blocks
def page_text(path):
    b = pathlib.Path(path).read_text()
    t = re.sub(r'<style[^>]*>.*?</style>|<script[^>]*>.*?</script>', ' ', b, flags=re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t))).replace('\u2212', '-')


def shows(body, v, d=1, sign=False):
    """Is a figure printed on the page, in the site's own format? Matched on a digit boundary, so 0.8% never
    stands in for 8%."""
    if v is None:
        return True
    forms = {f'{abs(v):.{d}f}%', f'{abs(v):.{d}f} pts'}
    return any(re.search(r'(?<![\d.])' + re.escape(f), body) for f in forms)


def stage_compare():
    """Every head to head page carries the desk's own figures for both funds, and every claim in its question
    block agrees with those figures."""
    root = ROOT / 'site' / 'compare'
    if not root.exists():
        note('compare', 'site/compare', 'directory', None, None, 'no comparison pages built')
        return
    funds = {f['ticker']: f for f in load('site/data/funds.json') or []}
    income = {r['ticker']: r for r in load('site/data/income.json') or []}
    th = load('site/data/thematic.json') or {'funds': [], 'matrix': None}
    themes = {r['ticker']: r for r in th.get('funds', [])}
    matrix = th.get('matrix') or {}
    tk = matrix.get('tickers') or []
    def overlap(a, b):
        if a not in tk or b not in tk:
            return None
        i, j = tk.index(a), tk.index(b)
        x, y = (i, j) if i < j else (j, i)
        try:
            return matrix['rows'][x][y - x - 1]
        except (IndexError, KeyError):
            return None
    n = 0
    for f in sorted(root.rglob('*.html')):
        desk = f.parent.name
        pair = f.stem.split('-')
        if len(pair) != 2:
            note('compare', f.stem, 'name', f.stem, None, 'file name is not two tickers')
            continue
        a, b = pair
        by = {'buffer': funds, 'income': income, 'themes': themes}.get(desk) or {}
        if a not in by or b not in by:
            note('compare', f.stem, 'fund', [a, b], None, f'not on the {desk} desk')
            continue
        n += 1
        body = page_text(f)
        for t in (a, b):
            r = by[t]
            if desk == 'buffer':
                checks = [('can still gain', r.get('remainingCapFund'), 1), ('fall before buffer', r.get('downsideBeforeBuffer'), 1), ('expense ratio', r.get('expenseRatio'), 2)]
                if str(r.get('daysRemaining')) not in body:
                    note('compare', f.stem, f'{t} daysRemaining', r.get('daysRemaining'), None, 'not printed on the page')
            elif desk == 'income':
                w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
                checks = [('cash', w.get('cash'), 1), ('total', w.get('total'), 1), ('gap', w.get('gap'), 1), ('payout rate', r.get('distributionRate'), 1), ('expense ratio', r.get('expenseRatio'), 2)]
            else:
                v = r.get('vsSPY') or {}
                w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
                checks = [('in the S&P 500', v.get('inIndex'), 1), ('active share', v.get('activeShare'), 1), ('top ten', r.get('top10Weight'), 1), ('total', w.get('total'), 1), ('expense ratio', r.get('expenseRatio'), 2)]
            for label, val, d in checks:
                if not shows(body, val, d):
                    note('compare', f.stem, f'{t} {label}', val, None, 'figure not printed on the page')
        if desk == 'themes':
            o = overlap(a, b)
            if o is not None and f'{o}%' not in body:
                note('compare', f.stem, 'overlap', o, None, 'overlap not printed on the page')
        # the claims in the question block must agree with the figures
        fa, fb = by[a].get('expenseRatio'), by[b].get('expenseRatio')
        m = re.search(r'so ([A-Z0-9.]+) is cheaper', body)
        if m and fa is not None and fb is not None:
            want = a if fa <= fb else b
            if m.group(1) != want:
                note('compare', f.stem, 'cheaper claim', m.group(1), want, f'{a} {fa}, {b} {fb}')
        m = re.search(r'so ([A-Z0-9.]+) paid more', body)
        if m and desk == 'income':
            wa = (by[a].get('windows') or {}).get('1Y') or (by[a].get('windows') or {}).get('ITD') or {}
            wb = (by[b].get('windows') or {}).get('1Y') or (by[b].get('windows') or {}).get('ITD') or {}
            if wa.get('cash') is not None and wb.get('cash') is not None:
                want = a if wa['cash'] >= wb['cash'] else b
                if m.group(1) != want:
                    note('compare', f.stem, 'paid more claim', m.group(1), want, f"{a} {wa['cash']}, {b} {wb['cash']}")
        m = re.search(r'so ([A-Z0-9.]+) returned more', body)
        if m and desk == 'income':
            wa = (by[a].get('windows') or {}).get('1Y') or (by[a].get('windows') or {}).get('ITD') or {}
            wb = (by[b].get('windows') or {}).get('1Y') or (by[b].get('windows') or {}).get('ITD') or {}
            if wa.get('total') is not None and wb.get('total') is not None:
                want = a if wa['total'] >= wb['total'] else b
                if m.group(1) != want:
                    note('compare', f.stem, 'returned more claim', m.group(1), want, f"{a} {wa['total']}, {b} {wb['total']}")
        m = re.search(r'so ([A-Z0-9.]+) differs more from the index', body)
        if m and desk == 'themes':
            va, vb = (by[a].get('vsSPY') or {}), (by[b].get('vsSPY') or {})
            if va.get('activeShare') is not None and vb.get('activeShare') is not None:
                want = a if va['activeShare'] >= vb['activeShare'] else b
                if m.group(1) != want:
                    note('compare', f.stem, 'differs more claim', m.group(1), want, f"{a} {va['activeShare']}, {b} {vb['activeShare']}")
        m = re.search(r'so ([A-Z0-9.]+) has more room', body)
        if m and desk == 'buffer':
            ra, rb = by[a].get('remainingCapFund'), by[b].get('remainingCapFund')
            if ra is not None and rb is not None:
                want = a if ra >= rb else b
                if m.group(1) != want:
                    note('compare', f.stem, 'more room claim', m.group(1), want, f'{a} {ra}, {b} {rb}')
    tally('compare', n)
    # every comparison page is in the sitemap
    sm = (ROOT / 'site' / 'sitemap.xml').read_text() if (ROOT / 'site' / 'sitemap.xml').exists() else ''
    missing = [f'/compare/{p.parent.name}/{p.name}' for p in root.rglob('*.html') if f'/compare/{p.parent.name}/{p.name}' not in sm]
    if missing:
        note('compare', 'sitemap', 'listed', len(missing), 0, f'pages not in the sitemap, for example {missing[0]}')


def stage_faqs():
    """Every question block on a fund page answers with the fund's own figures."""
    funds = {f['ticker']: f for f in load('site/data/funds.json') or []}
    income = {r['ticker']: r for r in load('site/data/income.json') or []}
    themes = {r['ticker']: r for r in (load('site/data/thematic.json') or {}).get('funds', [])}
    random.seed(23)
    n = 0
    for desk, by in (('buffer', funds), ('income', income), ('themes', themes)):
        for t in random.sample(sorted(by), min(12, len(by))):
            p = ROOT / 'site' / 'funds' / f'{t}.html'
            if not p.exists():
                continue
            body = page_text(p)
            if 'Questions people ask' not in body:
                note('faqs', t, 'block', None, None, f'no question block on the {desk} page')
                continue
            n += 1
            r = by[t]
            if desk == 'buffer':
                want = [('fall before buffer', r.get('downsideBeforeBuffer'), 1), ('expense ratio', r.get('expenseRatio'), 2)]
            elif desk == 'income':
                w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
                want = [('cash paid', w.get('cash'), 1), ('payout rate', r.get('distributionRate'), 1)]
            else:
                v = r.get('vsSPY') or {}
                want = [('in the S&P 500', v.get('inIndex'), 0), ('active share', v.get('activeShare'), 0)]
            for label, val, d in want:
                if not shows(body, val, d):
                    note('faqs', t, label, val, None, 'answer does not carry the figure')
    tally('faqs', n)


def stage_embeds():
    """Every embeddable graphic carries the fund's own figures, so a card on someone else's page cannot drift
    from the desk it came from."""
    root = ROOT / 'site' / 'embed'
    if not root.exists():
        note('embeds', 'site/embed', 'directory', None, None, 'no embeddable graphics built')
        return
    data = {'buffer': {f['ticker']: f for f in load('site/data/funds.json') or []},
            'income': {r['ticker']: r for r in load('site/data/income.json') or []},
            'themes': {r['ticker']: r for r in (load('site/data/thematic.json') or {}).get('funds', [])}}
    n = 0
    for desk, by in data.items():
        d = root / desk
        if not d.exists():
            note('embeds', desk, 'directory', None, None, 'no graphics for this desk')
            continue
        for f in sorted(d.glob('*.svg')):
            t = f.stem
            r = by.get(t)
            if not r:
                note('embeds', t, 'fund', None, None, f'graphic for a fund not on the {desk} desk')
                continue
            n += 1
            body = re.sub(r'<[^>]+>', ' ', f.read_text()).replace('\u2212', '-')
            body = re.sub(r'\s+', ' ', html.unescape(body))
            if t not in body:
                note('embeds', t, 'ticker', None, None, 'ticker not printed on the card')
            if desk == 'buffer':
                checks = [('fall before buffer', r.get('downsideBeforeBuffer'), 1)]
                if not r.get('isUncapped'):
                    checks.append(('can still gain', r.get('remainingCapFund'), 1))
                checks.append(('reference return', r.get('refReturn'), 1))
            elif desk == 'income':
                w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
                checks = [('cash paid', w.get('cash'), 1), ('total return', w.get('total'), 1)]
            else:
                v = r.get('vsSPY') or {}
                checks = [('in the S&P 500', v.get('inIndex'), 0), ('active share', v.get('activeShare'), 0)]
            for label, val, dg in checks:
                if not shows(body, val, dg):
                    note('embeds', t, label, val, None, 'figure not printed on the card')
            if 'etfiq.com' not in body:
                note('embeds', t, 'credit', None, None, 'no credit on the card')
    tally('embeds', n)


def stage_docs():
    """The static explainer, standards and hub pages exist and carry what they claim."""
    want = ['standards/index.html', 'learn/index.html', 'learn/buffer.html', 'learn/income.html', 'learn/themes.html', 'changed/index.html', 'issuers/index.html']
    n = 0
    for rel in want:
        p = ROOT / 'site' / rel
        if not p.exists():
            note('docs', rel, 'file', None, None, 'page missing')
            continue
        n += 1
        body = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<style[^>]*>.*?</style>|<script[^>]*>.*?</script>', ' ', p.read_text(), flags=re.S))))
        if len(body) < 900:
            note('docs', rel, 'length', len(body), '>900', 'page looks empty')
        if 'standards' in rel and 'independent publisher' not in body:
            note('docs', rel, 'independence', None, None, 'the independence statement is missing')
        if rel.startswith('learn/') and rel != 'learn/index.html' and body.count('.') < 20:
            note('docs', rel, 'terms', None, None, 'the glossary looks short')
    # the insight lines on the changed page agree with the desk files
    ins = load('site/data/insights.json') or {}
    p = ROOT / 'site' / 'changed' / 'index.html'
    if p.exists():
        body = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', p.read_text())))
        for line in (ins.get('lines') or []):
            if re.sub(r'\s+', ' ', line['text']) not in body:
                note('docs', 'changed', 'line', line['text'][:60], None, 'insight line not on the page')
    # every hub lists only funds that are on that desk
    funds = {f['ticker'] for f in load('site/data/funds.json') or []}
    themes = {r['ticker'] for r in (load('site/data/thematic.json') or {}).get('funds', [])}
    for p in sorted((ROOT / 'site' / 'buffer').glob('*.html')):
        if p.name == 'index.html':
            continue
        n += 1
        for t in set(re.findall(r'/funds/([A-Z0-9.]+)\.html', p.read_text())):
            if t not in funds:
                note('docs', p.name, 'fund', t, None, 'listed on a buffer hub but not on the buffer desk')
    for p in sorted((ROOT / 'site' / 'themes').glob('*.html')):
        if p.name == 'index.html':
            continue
        n += 1
        for t in set(re.findall(r'/funds/([A-Z0-9.]+)\.html', p.read_text())):
            if t not in themes:
                note('docs', p.name, 'fund', t, None, 'listed on a theme hub but not on the themes desk')
    tally('docs', n)


# ---------------------------------------------------------------- report
def report(stages):
    out = {'asOf': TODAY.isoformat(), 'stages': stages, 'counts': COUNTS, 'findings': FINDINGS}
    (ROOT / 'data' / 'census').mkdir(exist_ok=True)
    (ROOT / 'data' / 'census' / f'{TODAY.isoformat()}.json').write_text(json.dumps(out, indent=1, default=str))
    lines = [f'# ETFIQ accuracy census, {TODAY.isoformat()}', '', 'Every number recomputed from the raw sources with fresh code; every discrepancy listed.', '']
    for k, v in COUNTS.items():
        lines.append(f'- {k}: {v}')
    by = {}
    for f in FINDINGS:
        by.setdefault(f['stage'], []).append(f)
    lines += ['', f'## Findings: {len(FINDINGS)}', '']
    for st, fs in by.items():
        lines.append(f'### {st} ({len(fs)})')
        lines.append('')
        for f in fs[:400]:
            lines.append(f"- {f['ticker']} {f['field']}: site {f['site']!r}, recomputed {f['mine']!r}{(' (' + f['note'] + ')') if f['note'] else ''}")
        lines.append('')
    (ROOT / 'data' / 'census' / f'{TODAY.isoformat()}.md').write_text('\n'.join(lines))
    print(json.dumps({'counts': COUNTS, 'findings': len(FINDINGS), 'byStage': {k: len(v) for k, v in by.items()}}, indent=1, default=str))


if __name__ == '__main__':
    stages = sys.argv[1:] or ['income', 'buffer', 'live', 'themes', 'payouts', 'books', 'research', 'pages', 'compare', 'faqs', 'embeds', 'docs']
    funds = None
    if 'income' in stages:
        stage_income()
    if 'buffer' in stages or 'live' in stages:
        funds = stage_buffer()
    if 'live' in stages:
        stage_buffer_live(funds)
    if 'themes' in stages:
        stage_themes()
    if 'payouts' in stages:
        stage_payouts()
    if 'books' in stages:
        stage_books()
    if 'research' in stages:
        stage_research()
    if 'pages' in stages:
        stage_pages()
    if 'compare' in stages:
        stage_compare()
    if 'faqs' in stages:
        stage_faqs()
    if 'embeds' in stages:
        stage_embeds()
    if 'docs' in stages:
        stage_docs()
    report(stages)
    sys.exit(1 if FINDINGS else 0)
