#!/usr/bin/env python3
"""ETFIQ daily snapshot.

Pulls today's outcome-period values for every buffer ETF from the issuers that publish them, normalises
them to one schema, and writes:
  data/snapshots/<date>.json   every record captured, all structures, with provenance
  site/data/funds.json         the records the site draws (plain buffer and floor structures with current values)
  site/data/meta.json          as-of date, per-source counts, coverage

Sources, all public, verified 2026-09-04:
  Innovator  https://www.innovatoretfs.com/define/etfs/            one server-rendered page, every fund, every field;
                                                                    per-fund pages add the expense ratio and buffer range
  AllianzIM  https://www.allianzim.com/product-table/              one page carrying `const model = {...}` JSON, gross and net
  FT Vest    https://www.ftportfolios.com/Retail/Etf/EtfList.aspx  fund list, then one server-rendered summary page per fund

Everything else (terms history, the other sixteen issuers) goes through pipeline/edgar.py.

Environment:
  ETFIQ_DELAY   seconds between requests to one issuer (default 0.6)
  ETFIQ_CACHE   directory for per-fund page cache (default pipeline/cache); refreshed after CACHE_DAYS
"""
import collections
import datetime
import html
import json
import os
import pathlib
import re
import sys
import time

import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
DELAY = float(os.environ.get('ETFIQ_DELAY', '0.4'))
CACHE = pathlib.Path(os.environ.get('ETFIQ_CACHE', ROOT / 'pipeline' / 'cache'))
CACHE_DAYS = 7
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/128.0 Safari/537.36 ETFIQ-snapshot/0.1')

MONTHS = {m.lower(): m[:3] for m in ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                     'September', 'October', 'November', 'December']}
REF_KEYS = [('s&p 500', 'SPY'), ('spdr', 'SPY'), ('nasdaq-100', 'QQQ'), ('qqq', 'QQQ'), ('russell 2000', 'IWM'),
            ('msci eafe', 'EFA'), ('emerging', 'EEM'), ('20+ year treasury', 'TLT'), ('gold', 'GLD'), ('bitcoin', 'BTC')]


# ------------------------------------------------------------------ helpers
def get(url, tries=3):
    req_headers = {'User-Agent': UA, 'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9'}
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=req_headers), timeout=60) as r:
                return r.read().decode(r.headers.get_content_charset() or 'utf-8', errors='replace')
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def text(s):
    s = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', s, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()


def num(s):
    """'15.37%' | '-12.38%' | '26 days' | '$54.76' | '-' -> float or None."""
    if s is None:
        return None
    m = re.search(r'-?\d+(?:\.\d+)?', str(s).replace(',', ''))
    return float(m.group(0)) if m else None


def iso(us):
    """'9/30/2025' -> '2025-09-30'; 'November 24, 2025' -> '2025-11-24'."""
    if not us:
        return None
    us = us.strip()
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', us)
    if m:
        return f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%d-%b-%y'):
        try:
            return datetime.datetime.strptime(us, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def ref_from_name(n):
    n = (n or '').lower()
    for k, v in REF_KEYS:
        if k in n:
            return v
    return None


def cache_load(name):
    p = CACHE / name
    if p.exists():
        try:
            d = json.loads(p.read_text())
            if (TODAY - datetime.date.fromisoformat(d.get('_date', '2000-01-01'))).days <= CACHE_DAYS:
                return d
        except Exception:
            pass
    return {'_date': TODAY.isoformat()}


def cache_save(name, d):
    CACHE.mkdir(parents=True, exist_ok=True)
    d['_date'] = TODAY.isoformat()
    (CACHE / name).write_text(json.dumps(d, indent=1))


# ------------------------------------------------------------------ Innovator
def innovator_geometry(family):
    """Buffer start and end from the family name. Confirmed against the issuer's own fund pages where cached."""
    f = family.lower()
    if 'barrier' in f or ('accelerated' in f and 'buffer' not in f):
        return None
    structure = 'buffer'
    if 'dual directional' in f:
        structure = 'dual'
    elif 'accelerated' in f:
        structure = 'accelerated'
    elif 'premium income' in f:
        structure = 'income-buffer'
    m_floor = re.search(r'\b(\d+) floor', f)
    m_n = re.search(r'\b(\d+) buffer', f)
    if 'ultra buffer' in f:
        bs, be = -5, -35
    elif 'power buffer' in f:
        bs, be = 0, -15
    elif 'defined protection' in f:
        bs, be, structure = 0, -100, 'floor'
    elif '5 to 15 buffer' in f:
        bs, be = -5, -15
    elif 'defined wealth shield' in f:
        bs, be = 0, -20
    elif m_floor:
        bs, be, structure = -int(m_floor.group(1)), -100, 'floor'
    elif m_n:
        bs, be = 0, -int(m_n.group(1))
    elif 'buffer etf' in f:
        bs, be = 0, -9
    else:
        return None
    return {'bufferStart': float(bs), 'bufferEnd': float(be), 'structure': structure}


def innovator():
    url = 'https://www.innovatoretfs.com/define/etfs/'
    s = get(url)
    m = re.search(r'As of (\d{1,2}/\d{1,2}/\d{4})', s)
    as_of = iso(m.group(1)) if m else TODAY.isoformat()
    rows = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        mm = re.search(r'class="ticlink">([a-z0-9]+)<', tr)
        if not mm:
            continue
        c = [text(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(c) < 17:
            continue
        t = mm.group(1).upper()
        if t not in rows or len(c) > len(rows[t]):
            rows[t] = c
    pages = cache_load('innovator_pages.json')
    recs = []
    for t, c in rows.items():
        family, series, ref = c[1], c[2], c[3]
        g = innovator_geometry(family)
        if not g:
            continue
        ps, pe = iso(c[15]), iso(c[16])
        if not ps or not pe:
            continue
        # per-fund page: expense ratio and the issuer's own buffer range, cached for a week
        fund_url = f'https://www.innovatoretfs.com/etf/default.aspx?ticker={t.lower()}'
        if t not in pages:
            try:
                pt = text(get(fund_url))
                e = re.search(r'Expense Ratio\s*([\d.]+)%', pt)
                rng = re.search(r'from (-?\d+(?:\.\d+)?)% to (-?\d+(?:\.\d+)?)%', pt)
                first = re.search(r'first (\d+(?:\.\d+)?)% of', pt)
                pages[t] = {'expense': float(e.group(1)) if e else None,
                            'range': [float(rng.group(1)), float(rng.group(2))] if rng else ([0.0, -float(first.group(1))] if first else None)}
            except Exception as ex:
                pages[t] = {'expense': None, 'range': None, 'error': str(ex)[:80]}
            time.sleep(DELAY)
            if len(pages) % 10 == 0:
                cache_save('innovator_pages.json', pages)
        pg = pages[t]
        bs, be = g['bufferStart'], g['bufferEnd']
        if pg.get('range') and pg['range'][0] <= 0 and pg['range'][1] < pg['range'][0]:
            bs, be = pg['range']  # the issuer's own statement wins over the family map
        words = series.split()
        mon = MONTHS.get(words[0].lower(), words[0]) if words else ''
        tail = ' '.join(words[1:])
        name = f'Innovator {family} - {mon}' + (f' {tail}' if tail else '')
        start_cap = None if 'uncapped' in family.lower() else num(c[14])
        recs.append(dict(
            ticker=t, name=name, issuer='Innovator', family=f'Innovator {family}', structure=g['structure'],
            refAsset=ref, refName=ref, periodStart=ps, periodEnd=pe, daysRemaining=int(num(c[12]) or 0),
            startCap=start_cap, startCapNet=None, participation=None,
            bufferStart=bs, bufferEnd=be,
            refReturn=num(c[6]), fundReturn=num(c[5]),
            remainingCapRefPub=num(c[8]), remainingCapFund=num(c[9]), remainingCapFundGross=None,
            remainingBuffer=num(c[10]), downsideBeforeBuffer=abs(num(c[11]) or 0.0),
            nav=num(c[4]), expenseRatio=pg.get('expense'), netAssets=None,
            source={'issuerPage': url, 'fundPage': fund_url, 'asOf': as_of, 'geometry': 'issuer page' if pg.get('range') else 'family map'}))
    cache_save('innovator_pages.json', pages)
    return recs, {'issuer': 'Innovator', 'url': url, 'asOf': as_of, 'rows': len(rows), 'kept': len(recs)}


# ------------------------------------------------------------------ AllianzIM
def allianz():
    url = 'https://www.allianzim.com/product-table/'
    s = get(url)
    i = s.find('const model = ')
    if i < 0:
        raise RuntimeError('AllianzIM model block not found')
    model, _ = json.JSONDecoder().raw_decode(s[i + len('const model = '):])
    recs = []
    as_of = TODAY.isoformat()
    for t, v in model.items():
        cur, st = v.get('current') or {}, v.get('start') or {}
        strat = v.get('strategy') or ''
        m = re.match(r'(Buffer|Floor)(\d+)', strat)
        if not m or strat == 'BufferAllocation' or not st.get('start_of_outcome_period'):
            continue
        kind, n = m.group(1), int(m.group(2))
        if kind == 'Buffer':
            bs, be, structure = 0.0, -float(n), ('floor' if n >= 100 else 'buffer')
        else:
            bs, be, structure = -float(n), -100.0, 'floor'
        uncapped = v.get('upside_opportunity') == 'uncapped'
        f = lambda k, d=cur: (None if d.get(k) is None else round(d[k] * 100, 2))
        as_of = iso(cur.get('day')) or as_of
        series = v.get('series') or ''
        mon = MONTHS.get(series.split('/')[0].strip().lower(), series.split('/')[0].strip()) if series else ''
        group = v.get('strategy_group') or ''
        dbb = f('downside_before_buffer_net')
        if dbb is None:
            dbb = f('downside_before_floor_net')
        recs.append(dict(
            ticker=t, name=f'AllianzIM {group} {strat} ETF - {mon}', issuer='AllianzIM', family=f'AllianzIM {group} {strat} ETF',
            structure=structure, refAsset=v.get('ref_asset_abbr') or ref_from_name(v.get('reference_name')) or '', refName=v.get('reference_name'),
            periodStart=iso(st['start_of_outcome_period']), periodEnd=iso(st['end_of_outcome_period']),
            daysRemaining=int(cur.get('number_of_days_remaining') or 0), daysElapsed=cur.get('number_of_days_into_period'),
            startCap=None if uncapped else f('starting_cap_gross', st), startCapNet=None if uncapped else f('starting_cap_net', st),
            participation=f('upside_participation_rate', st) if uncapped else None,
            bufferStart=bs, bufferEnd=be,
            refReturn=f('reference_level_period_return'), fundReturn=f('etf_current_period_net_return'),
            remainingCapRefPub=f('index_return_to_cap'), remainingCapFund=f('remaining_cap_net'), remainingCapFundGross=f('remaining_cap_gross'),
            remainingBuffer=f('remaining_buffer_calc_net'), downsideBeforeBuffer=abs(dbb or 0.0),
            nav=v.get('nav'), expenseRatio=num(v.get('net_expense_ratio')), netAssets=v.get('net_assets'),
            source={'issuerPage': url, 'fundPage': f'https://www.allianzim.com/etfs/{t.lower()}/', 'asOf': as_of, 'geometry': 'strategy name'}))
    return recs, {'issuer': 'AllianzIM', 'url': url, 'asOf': as_of, 'rows': len(model), 'kept': len(recs)}


# ------------------------------------------------------------------ FT Vest
def ftvest():
    list_url = 'https://www.ftportfolios.com/Retail/Etf/EtfList.aspx'
    s = get(list_url)
    funds = []
    for m in re.finditer(r"EtfSummary\.aspx\?Ticker=([A-Z]+)'[^>]*>([^<]+)<", s):
        t, name = m.group(1), re.sub(r'\s+[\u2013\u2014]\s+', ' - ', html.unescape(m.group(2)).strip())
        if 'Buffer' in name and not re.search(r'Laddered|Fund of|Model|Allocation', name):
            funds.append((t, name))
    seen = set()
    funds = [x for x in funds if not (x[0] in seen or seen.add(x[0]))]
    recs = []
    as_of = TODAY.isoformat()
    errors = 0
    day_cache = cache_load(f'ftvest_{TODAY.isoformat()}.json')
    fetched = 0
    for t, name in funds:
        url = f'https://www.ftportfolios.com/Retail/Etf/EtfSummary.aspx?Ticker={t}'
        if t in day_cache:
            recs.append(day_cache[t])
            as_of = day_cache[t]['source']['asOf']
            continue
        try:
            pt = text(get(url))
        except Exception:
            errors += 1
            continue
        time.sleep(DELAY)
        fetched += 1
        r = lambda pat, flags=0: re.search(pat, pt, flags)
        cap_m = (r(r'up to (?:a )?predetermined (?:upside )?cap of ([\d.]+)%') or r(r'Fund Cap \(Net\) ([\d.]+)% \(([\d.]+)%\)')
                 or r(r'Starting Cap(?: \(Net\))? ([\d.]+)% \(([\d.]+)%\)'))
        per = (r(r'over the period from ([A-Z][a-z]+ \d{1,2}, \d{4}) (?:to|through) ([A-Z][a-z]+ \d{1,2}, \d{4})')
               or r(r'began on ([A-Z][a-z]+ \d{1,2}, \d{4})[^.]{0,160}?(?:through|to|until|ends? on|ending(?: on)?) ([A-Z][a-z]+ \d{1,2}, \d{4})')
               or r(r'Target Outcome Period[^.]{0,80}?([A-Z][a-z]+ \d{1,2}, \d{4})[^.]{0,40}?([A-Z][a-z]+ \d{1,2}, \d{4})'))
        b_start = r(r'Buffer Start % / Reference Asset Value (-?[\d.]+)% / \$([\d,.]+)')
        b_end = r(r'Buffer End % / Reference Asset Value (-?[\d.]+)% / \$([\d,.]+)')
        cur_as_of = r(r'Current Values \(as of (\d{1,2}/\d{1,2}/\d{4})')
        days = r(r'Remaining Outcome Period (\d+) days')
        fund_v = r(r'Fund Value/Return \$([\d,.]+) / (-?[\d.]+)%')
        ref_v = r(r'Reference Asset Value/Return \$([\d,.]+) / (-?[\d.]+)%')
        rem_cap = r(r'Remaining Cap \(Net\) (-?[\d.]+)% \((-?[\d.]+)%\)')
        ref_to_cap = r(r'Reference Asset Return to Realize the Cap (-?[\d.]+)%')
        rem_buf = r(r'Remaining Buffer \(Net\) (-?[\d.]+)% \((-?[\d.]+)%\)')
        dbb = r(r'Downside Before Buffer \(Net\) (-?[\d.]+)% \((-?[\d.]+)%\)')
        cap_net = r(r'Fund Cap \(Net\) ([\d.]+)% \(([\d.]+)%\)') or r(r'upside cap of ([\d.]+)%\D{0,80}?the cap is ([\d.]+)%')
        exp = r(r'Total Expense Ratio\*? ([\d.]+)%')
        nav = r(r'Closing NAV \d? ?\$([\d.]+)')
        assets = r(r'Total Net Assets \$([\d,]+)')
        ref_name = r(r'price return of the (.*?)\s*\(the "Underlying ETF"\)')
        structure = ('dual' if 'Dual Directional' in name else 'digital' if 'Digital Return' in name else 'accelerated' if 'Enhance' in name
                     else 'income-buffer' if 'Income' in name else 'buffer')
        start_cap = float(cap_m.group(1)) if cap_m else None
        if not (per and b_start and b_end and ref_v) or (start_cap is None and structure == 'buffer' and 'Uncapped' not in name):
            errors += 1
            continue
        as_of = iso(cur_as_of.group(1)) if cur_as_of else as_of
        bs, be = float(b_start.group(1)), float(b_end.group(1))
        if be <= -100:
            structure = 'floor'
        recs.append(dict(
            ticker=t, name=name, issuer='First Trust', family=re.sub(r'\s+-\s+\S+$', '', name), structure=structure,
            refAsset=ref_from_name(ref_name.group(1) if ref_name else name) or '', refName=ref_name.group(1) if ref_name else None,
            periodStart=iso(per.group(1)), periodEnd=iso(per.group(2)), daysRemaining=int(days.group(1)) if days else 0,
            startCap=start_cap, startCapNet=(float(cap_net.group(2)) if cap_net else (float(cap_m.group(2)) if cap_m and cap_m.lastindex and cap_m.lastindex >= 2 else None)),
            participation=None,
            bufferStart=bs, bufferEnd=be,
            refReturn=float(ref_v.group(2)), fundReturn=float(fund_v.group(2)) if fund_v else None,
            remainingCapRefPub=float(ref_to_cap.group(1)) if ref_to_cap else None,
            remainingCapFund=float(rem_cap.group(2)) if rem_cap else None, remainingCapFundGross=float(rem_cap.group(1)) if rem_cap else None,
            remainingBuffer=float(rem_buf.group(2)) if rem_buf else None, downsideBeforeBuffer=abs(float(dbb.group(2))) if dbb else 0.0,
            nav=float(nav.group(1)) if nav else None, expenseRatio=float(exp.group(1)) if exp else None,
            netAssets=float(assets.group(1).replace(',', '')) if assets else None,
            refLevels={'bufferStart': float(b_start.group(2).replace(',', '')), 'bufferEnd': float(b_end.group(2).replace(',', ''))},
            source={'issuerPage': list_url, 'fundPage': url, 'asOf': as_of, 'geometry': 'issuer page'}))
        day_cache[t] = recs[-1]
        if fetched % 10 == 0:
            cache_save(f'ftvest_{TODAY.isoformat()}.json', day_cache)
    cache_save(f'ftvest_{TODAY.isoformat()}.json', day_cache)
    return recs, {'issuer': 'First Trust', 'url': list_url, 'asOf': as_of, 'rows': len(funds), 'kept': len(recs), 'errors': errors}


# ------------------------------------------------------------------ normalise
def finish(r):
    """ETFIQ calculations in reference-return space, from the published terms and the reference return."""
    for k in ('name', 'family'):
        r[k] = re.sub(r'\s+[\u2013\u2014]\s+', ' - ', r[k])
    r['family'] = re.sub(r'\s+-\s+[^-]+$', '', r['name'])
    ref, bs, be = r['refReturn'], r['bufferStart'], r['bufferEnd']
    r['startBuffer'] = round(bs - be, 2)
    if r.get('daysElapsed') is None:
        r['daysElapsed'] = max(0, (TODAY - datetime.date.fromisoformat(r['periodStart'])).days)
    if ref is None:
        return r
    r['bufferUsed'] = round(max(0.0, min(r['startBuffer'], bs - ref)), 2)
    r['unprotectedLoss'] = round(min(-ref, -bs), 2) if (ref < 0 and bs < 0) else 0.0
    r['lossBelowFloor'] = round(max(0.0, be - ref), 2)
    cap = r.get('startCap')
    r['remainingCap'] = None if cap is None else round(max(0.0, cap - ref), 2)
    r['netPosition'] = None if cap is None else round(r['remainingCap'] - (r.get('downsideBeforeBuffer') or 0.0), 2)
    return r


def main():
    all_recs, sources = [], []
    for fn in (innovator, allianz, ftvest):
        try:
            recs, meta = fn()
            all_recs += [finish(r) for r in recs]
            sources.append(meta)
            print(f"{meta['issuer']}: {meta['kept']} of {meta['rows']} rows kept, as of {meta['asOf']}", file=sys.stderr)
        except Exception as ex:
            sources.append({'issuer': fn.__name__, 'error': str(ex)[:200]})
            print(f'{fn.__name__} failed: {ex}', file=sys.stderr)
    all_recs.sort(key=lambda r: (r['issuer'], r['ticker']))
    site = [r for r in all_recs if r['structure'] in ('buffer', 'floor') and r.get('refReturn') is not None and r.get('periodStart')]
    as_of = max([s.get('asOf') for s in sources if s.get('asOf')] or [TODAY.isoformat()])
    meta = {
        'asOf': as_of, 'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'sources': sources, 'captured': len(all_recs), 'shown': len(site),
        'structures': dict(collections.Counter(r['structure'] for r in all_recs)),
        'issuers': dict(collections.Counter(r['issuer'] for r in site)),
        'coverage': 'Issuers holding about 91 percent of buffer ETF assets (ETF Action, April 2026). Other issuers arrive through pipeline/edgar.py.'
    }
    (ROOT / 'data' / 'snapshots').mkdir(parents=True, exist_ok=True)
    (ROOT / 'data' / 'snapshots' / f'{TODAY.isoformat()}.json').write_text(json.dumps({'meta': meta, 'funds': all_recs}, indent=1))
    (ROOT / 'site' / 'data').mkdir(parents=True, exist_ok=True)
    (ROOT / 'site' / 'data' / 'funds.json').write_text(json.dumps(site, separators=(',', ':')))
    (ROOT / 'site' / 'data' / 'meta.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == '__main__':
    main()
