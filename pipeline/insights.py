#!/usr/bin/env python3
"""What changed: dated, sourced, plain-word lines computed from the desks' data, for the home page and the weekly note.

Every line is arithmetic on the same files the page inlines, and each links to the grid or view that proves it. The
previous buffer snapshot (data/snapshots/) gives day-over-day movement where it exists. No model writes these.

Writes site/data/insights.json: {asOf, lines: [{desk, text, href}], stats}. Run after the other pipelines, before build_site.py.
"""
import datetime
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prerender import buffer_state  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(p, default):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else default


def pct(v, d=0):
    return f'{v:.{d}f}%'


def build():
    funds = load('site/data/funds.json', [])
    income = load('site/data/income.json', [])
    themes = load('site/data/thematic.json', {'funds': []})['funds']
    payouts = load('site/data/payouts.json', [])
    sources = load('site/data/sources.json', {})
    meta, imeta, tmeta = load('site/data/meta.json', {}), load('site/data/income_meta.json', {}), load('site/data/thematic_meta.json', {})
    as_b, as_i, as_t = meta.get('asOf'), imeta.get('asOf'), tmeta.get('asOf')
    lines, stats = [], {}

    # ---- buffer desk
    if funds:
        states = {f['ticker']: buffer_state(f) for f in funds}
        capped = [t for t, s in states.items() if s == 'capped']
        working = [t for t, s in states.items() if s in ('engaged', 'exhausted')]
        soon = [f['ticker'] for f in funds if f.get('daysRemaining', 999) <= 30]
        fresh = [f['ticker'] for f in funds if f.get('daysElapsed', 999) <= 7]
        stats['buffer'] = {'funds': len(funds), 'capped': len(capped), 'working': len(working), 'resetSoon': len(soon), 'freshCaps': len(fresh)}
        # movement since the previous snapshot
        snaps = sorted(p for p in (ROOT / 'data' / 'snapshots').glob('20??-??-??.json') if p.stem < (as_b or '9999'))
        newly = []
        if snaps:
            prev = json.loads(snaps[-1].read_text()).get('funds', [])
            prev_states = {f['ticker']: buffer_state(f) for f in prev if f.get('refReturn') is not None and f.get('periodStart') and f.get('structure') in ('buffer', 'floor')}
            newly = [t for t in capped if t in prev_states and prev_states[t] != 'capped']
            stats['buffer']['newlyCapped'] = len(newly)
            stats['buffer']['previousSnapshot'] = snaps[-1].stem
        lines.append({'desk': 'buffer', 'text': f"{len(capped)} of {len(funds)} buffer ETFs sit at their cap today" + (f", {len(newly)} of them new since {snaps[-1].stem}" if newly else '') + '.', 'href': '#/buffer/desk'})
        if working:
            lines.append({'desk': 'buffer', 'text': f"{len(working)} buffer ETFs have their buffer absorbing losses right now.", 'href': '#/buffer/desk'})
        lines.append({'desk': 'buffer', 'text': f"{len(soon)} buffer ETFs reset within 30 days" + (f"; {len(fresh)} reset in the last week and carry fresh caps." if fresh else '.'), 'href': '#/buffer/entry'})

    # ---- income desk
    if income:
        idx = [r for r in income if r.get('benchmarkKind') != 'stock']
        w1 = lambda r: (r.get('windows') or {}).get('1Y')
        with_w = [r for r in idx if w1(r) and w1(r).get('gap') is not None]
        ahead = [r for r in with_w if w1(r)['gap'] > 0.5]
        fat_fell = [r for r in with_w if w1(r)['cash'] >= 10 and w1(r)['price'] < 0]
        stats['income'] = {'funds': len(income), 'indexFunds': len(idx), 'withYear': len(with_w), 'ahead': len(ahead), 'paidTenFell': len(fat_fell)}
        if with_w:
            lines.append({'desk': 'income', 'text': f"Over the last year, {len(ahead)} of {len(with_w)} index income ETFs finished ahead of their benchmark once cash was counted and reinvested.", 'href': '#/income/ahead'})
        if fat_fell:
            lines.append({'desk': 'income', 'text': f"{len(fat_fell)} income ETFs paid 10% or more in cash over the year while their price fell.", 'href': '#/income/desk'})
        today = datetime.date.fromisoformat(as_i) if as_i else datetime.date.today()
        week = (today + datetime.timedelta(days=7)).isoformat()
        paying = [p for p in payouts if any(n.get('pay') and today.isoformat() < n['pay'] <= week for n in p.get('next', []))]
        if paying:
            published = sum(1 for p in paying if any(n.get('status') in ('declared', 'scheduled') for n in p.get('next', [])))
            lines.append({'desk': 'income', 'text': f"{len(paying)} income ETFs pay out in the next seven days, {published} of them on dates the issuer has published.", 'href': '#/income/calendar'})
            stats['income']['payingThisWeek'] = len(paying)
        # return of capital by the largest issuer with notices
        by_issuer = {}
        for t, s in sources.items():
            if s.get('latest') and s['latest'].get('roc') is not None:
                by_issuer.setdefault(s['issuer'], []).append(s['latest']['roc'])
        if by_issuer:
            iss, vals = max(by_issuer.items(), key=lambda kv: len(kv[1]))
            lines.append({'desk': 'income', 'text': f"{iss}'s latest distributions were {pct(statistics.median(vals))} return of capital at the median fund, by its own 19a-1 estimates across {len(vals)} funds.", 'href': '#/income/desk'})
            stats['income']['rocIssuer'] = {'issuer': iss, 'medianRoc': round(statistics.median(vals), 1), 'funds': len(vals)}

    # ---- themes desk
    if themes:
        ins = [r['vsSPY']['inIndex'] for r in themes if r.get('vsSPY')]
        w1 = lambda r: (r.get('windows') or {}).get('1Y')
        with_w = [r for r in themes if w1(r) and w1(r).get('gap') is not None]
        beat = [r for r in with_w if w1(r)['gap'] > 0.5]
        by_theme = {}
        for r in with_w:
            by_theme.setdefault(r['themeName'], []).append(w1(r))
        lead = max(((k, statistics.median(x['total'] for x in v), sum(1 for x in v if x['gap'] > 0.5), len(v)) for k, v in by_theme.items() if len(v) >= 3), key=lambda x: x[1], default=None)
        lag = min(((k, statistics.median(x['total'] for x in v), sum(1 for x in v if x['gap'] > 0.5), len(v)) for k, v in by_theme.items() if len(v) >= 3), key=lambda x: x[1], default=None)
        twins = 0
        M = load('site/data/thematic.json', {}).get('matrix') or {}
        for row in M.get('rows', []):
            twins += sum(1 for v in row if v >= 50)
        stats['themes'] = {'funds': len(themes), 'withHoldings': len(ins), 'medianInSPY': round(statistics.median(ins), 1) if ins else None, 'beat': len(beat), 'withYear': len(with_w), 'twinPairs': twins}
        if ins:
            lines.append({'desk': 'themes', 'text': f"The typical thematic ETF has {pct(statistics.median(ins))} of its weight in S&P 500 names, by its latest holdings filing.", 'href': '#/themes/themes'})
        if lead:
            lines.append({'desk': 'themes', 'text': f"Over the last year the median {lead[0].lower()} fund returned {lead[1]:+.0f}% and {lead[2]} of {lead[3]} beat the S&P 500; the median {lag[0].lower()} fund returned {lag[1]:+.0f}%.", 'href': '#/themes/themes'})
        if twins:
            lines.append({'desk': 'themes', 'text': f"{twins} pairs of thematic ETFs hold portfolios that are more than half identical.", 'href': '#/themes/own'})
    out = {'asOf': max(x for x in (as_b, as_i, as_t) if x) if any((as_b, as_i, as_t)) else datetime.date.today().isoformat(), 'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'lines': lines, 'stats': stats}
    (ROOT / 'site' / 'data' / 'insights.json').write_text(json.dumps(out, indent=1))
    for l in lines:
        print(f"  [{l['desk']}] {l['text']}")
    return out


if __name__ == '__main__':
    build()
