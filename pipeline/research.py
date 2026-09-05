#!/usr/bin/env python3
"""ETFIQ Research: one computed piece per desk, rebuilt nightly from the desks' own files.

Each piece is a set of tables plus a computed summary, written as a static page (site/research/<slug>.html) with the
method and the data file it came from. If a narrative approved for the piece exists (data/research/<slug>.narrative.md,
written by pipeline/draft.py and checked against the tables), it is placed above the tables and labelled.

Pieces:
  buffer-state    The state of the buffer desk: caps, working buffers and protection by issuer and reset month.
  income-ahead    Ahead or behind, and where the cash came from: results by issuer, return of capital, the cost of the payout.
  themes-index    How much of a theme is already the index: in-index weight, active share and fees by theme; the twins.

Writes data/research/<slug>.json (the tables) and site/research/*.html. Run after insights.py, before prerender.py.
"""
import datetime
import html
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prerender import buffer_state, STATE_LABEL  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
BASE = 'https://etfiq.com'


def load(p, default):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else default


def med(a):
    a = [x for x in a if x is not None]
    return round(statistics.median(a), 1) if a else None


def fdate(d):
    try:
        return datetime.date.fromisoformat(d).strftime('%b %-d, %Y')
    except Exception:
        return d or ''


def p(v, sign=False, d=1):
    if v is None:
        return '·'
    return (f'{v:+.{d}f}%' if sign else f'{v:.{d}f}%').replace('-', '−')


def pts(v):
    return '·' if v is None else f'{v:+.1f} pts'.replace('-', '−')


# ---------------------------------------------------------------- pieces
def buffer_piece(funds, as_of):
    by_iss = {}
    for f in funds:
        by_iss.setdefault(f['issuer'], []).append(f)
    rows = []
    for iss, g in sorted(by_iss.items(), key=lambda kv: -len(kv[1])):
        st = [buffer_state(f) for f in g]
        rows.append([iss, len(g), st.count('capped'), st.count('engaged') + st.count('exhausted'), p(med([f.get('remainingCapFund') for f in g if not f.get('isUncapped')])), p(med([f.get('downsideBeforeBuffer') for f in g])), p(med([f.get('expenseRatio') for f in g]), d=2)])
    states = [buffer_state(f) for f in funds]
    st_rows = [[STATE_LABEL[k], states.count(k), p(states.count(k) / len(funds) * 100, d=0)] for k in ('capped', 'open', 'engaged', 'exhausted', 'unprotected', 'uncapped', 'floor') if states.count(k)]
    by_month = {}
    for f in funds:
        by_month.setdefault(f['periodEnd'][:7], []).append(f)
    m_rows = []
    for m, g in sorted(by_month.items())[:12]:
        st = [buffer_state(f) for f in g]
        m_rows.append([datetime.date.fromisoformat(m + '-01').strftime('%b %Y'), len(g), st.count('capped'), p(med([f.get('remainingCapFund') for f in g if not f.get('isUncapped')])), p(med([f['refReturn'] for f in g], ), sign=True)])
    capped = states.count('capped')
    summary = [f"On {fdate(as_of)}, {capped} of {len(funds)} buffer ETFs across {len(by_iss)} issuers sat at their cap, so in index terms those funds have no further upside this period.",
               f"{states.count('engaged') + states.count('exhausted')} funds had their buffer absorbing losses. The median fund could still gain {p(med([f.get('remainingCapFund') for f in funds if not f.get('isUncapped')]))} from its current price and could fall {p(med([f.get('downsideBeforeBuffer') for f in funds]))} before its buffer begins, by the issuers' own figures.",
               "Funds resetting soonest carry the least remaining cap, because their index has had the most time to rise toward it; the fresh caps sit in the months that reset last."]
    return {'slug': 'buffer-state', 'desk': 'buffer', 'title': 'The state of the buffer desk', 'asOf': as_of, 'summary': summary,
            'tables': [{'title': 'By issuer', 'columns': ['Issuer', 'Funds', 'At cap', 'Buffer working', 'Median can still gain', 'Median fall before buffer', 'Median expense ratio'], 'rows': rows},
                       {'title': 'Where every fund stands today', 'columns': ['Band state', 'Funds', 'Share'], 'rows': st_rows},
                       {'title': 'By reset month, next twelve months', 'columns': ['Period ends', 'Funds', 'At cap', 'Median can still gain', 'Median index move since period start'], 'rows': m_rows}],
            'method': 'Issuer-published figures (remaining cap net of fees and downside before buffer, both in fund-price terms) as of the date shown; band states are ETFIQ calculations in index terms from the published terms and the reference return. Medians across funds, not asset-weighted.',
            'data': f'{BASE}/data/funds.json', 'app': f'{BASE}/#/buffer/desk'}


def income_piece(income, sources, as_of):
    w1 = lambda r: (r.get('windows') or {}).get('1Y')
    idx = [r for r in income if r.get('benchmarkKind') != 'stock' and w1(r) and w1(r).get('gap') is not None]
    on_desk = {}
    for r in income:
        if r.get('benchmarkKind') != 'stock':
            on_desk[r['issuer']] = on_desk.get(r['issuer'], 0) + 1
    by_iss = {}
    for r in idx:
        by_iss.setdefault(r['issuer'], []).append(r)
    rows = []
    for iss, g in sorted(by_iss.items(), key=lambda kv: -len(kv[1])):
        if len(g) < 2:
            continue
        rows.append([iss, on_desk.get(iss, len(g)), len(g), sum(1 for r in g if w1(r)['gap'] > 0.5), pts(med([w1(r)['gap'] for r in g])), p(med([w1(r)['cash'] for r in g])), p(med([w1(r)['price'] for r in g]), sign=True), p(med([w1(r)['total'] for r in g]), sign=True)])
    roc_rows = []
    by_src = {}
    for t, s in sources.items():
        if s.get('latest') and s['latest'].get('roc') is not None:
            by_src.setdefault(s['issuer'], []).append((t, s['latest']['roc']))
    inc_by = {r['ticker']: r for r in income}
    for iss, g in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
        px = [w1(inc_by[t])['price'] for t, _ in g if t in inc_by and w1(inc_by[t])]
        roc_rows.append([iss, len(g), p(med([v for _, v in g]), d=0), sum(1 for _, v in g if v >= 90), p(med(px), sign=True)])
    buckets = [('Under 8%', 0, 8), ('8% to 15%', 8, 15), ('15% to 30%', 15, 30), ('30% to 60%', 30, 60), ('60% and above', 60, 1e9)]
    b_rows = []
    allw = [r for r in income if w1(r) and w1(r).get('gap') is not None and r.get('distributionRate') is not None]
    for lab, lo, hi in buckets:
        g = [r for r in allw if lo <= r['distributionRate'] < hi]
        if g:
            b_rows.append([lab, len(g), p(med([w1(r)['cash'] for r in g])), p(med([w1(r)['price'] for r in g]), sign=True), p(med([w1(r)['total'] for r in g]), sign=True), pts(med([w1(r)['gap'] for r in g]))])
    ahead = sum(1 for r in idx if w1(r)['gap'] > 0.5)
    top_roc = max(by_src.items(), key=lambda kv: len(kv[1])) if by_src else None
    summary = [f"Over the year to {fdate(as_of)}, {ahead} of {len(idx)} index income ETFs finished ahead of the index they write options on, once every cash payment was counted and reinvested. The median fund was {pts(med([w1(r)['gap'] for r in idx]))} against its benchmark.",
               (f"{top_roc[0]} estimates that the median fund's latest distribution was {p(med([v for _, v in top_roc[1]]), d=0)} return of capital, across {len(top_roc[1])} funds with 19a-1 notices." if top_roc else ''),
               "The higher the distribution rate, the worse the price did and the further behind the benchmark the fund fell: a payout above thirty percent a year has mostly been paid out of the price."]
    return {'slug': 'income-ahead', 'desk': 'income', 'title': 'Ahead or behind, and where the cash came from', 'asOf': as_of, 'summary': [s for s in summary if s],
            'tables': [{'title': 'Results by issuer, index income funds, one year', 'columns': ['Issuer', 'Funds on the desk', 'Funds with a full year', 'Ahead of benchmark', 'Median gap', 'Median cash paid', 'Median price change', 'Median total return'], 'rows': rows},
                       {'title': 'Return of capital by issuer, latest 19a-1 estimates', 'columns': ['Issuer', 'Funds with notices', 'Median return of capital', 'Funds at 90% or more', 'Median price change, one year'], 'rows': roc_rows},
                       {'title': 'The cost of the payout: by distribution rate, all funds, one year', 'columns': ['Distribution rate', 'Funds', 'Median cash paid', 'Median price change', 'Median total return', 'Median gap vs benchmark'], 'rows': b_rows}],
            'method': 'ETFIQ calculations from exchange prices and cash distributions (Tiingo end-of-day): cash as a share of the starting price, price change, total return with distributions reinvested, and the benchmark measured the same way. Return of capital is each issuer’s Rule 19a-1 estimate for its latest distribution. Medians across funds.',
            'data': f'{BASE}/data/income.json', 'app': f'{BASE}/#/income/ahead'}


def themes_piece(themes, matrix, as_of):
    w1 = lambda r: (r.get('windows') or {}).get('1Y')
    by_theme = {}
    for r in themes:
        by_theme.setdefault(r['themeName'], []).append(r)
    rows = []
    for th, g in sorted(by_theme.items(), key=lambda kv: -sum(r.get('assets') or 0 for r in kv[1])):
        wh = [r for r in g if r.get('vsSPY')]
        ww = [r for r in g if w1(r) and w1(r).get('gap') is not None]
        rows.append([th, len(g), p(med([r['vsSPY']['inIndex'] for r in wh]), d=0), p(med([r['vsSPY']['activeShare'] for r in wh]), d=0), p(med([r.get('expenseRatio') for r in g]), d=2), p(med([r.get('activeFee') for r in g]), d=2), f"{sum(1 for r in ww if w1(r)['gap'] > 0.5)} of {len(ww)}", p(med([w1(r)['total'] for r in ww]), sign=True)])
    twins = []
    tick = matrix.get('tickers') or []
    for a, row in enumerate(matrix.get('rows') or []):
        for j, v in enumerate(row):
            if v >= 50:
                twins.append((v, tick[a], tick[a + 1 + j]))
    by_t = {r['ticker']: r for r in themes}
    twins.sort(reverse=True)
    t_rows = [[f"{a} and {b}", f"{v}%", by_t[a]['themeName'] if a in by_t else '', p(by_t[a].get('expenseRatio'), d=2) if a in by_t else '·', p(by_t[b].get('expenseRatio'), d=2) if b in by_t else '·'] for v, a, b in twins[:15]]
    ins = [r['vsSPY']['inIndex'] for r in themes if r.get('vsSPY')]
    high = sum(1 for v in ins if v >= 60)
    summary = [f"By their latest holdings filings, the typical thematic ETF has {p(med(ins), d=0)} of its weight in stocks the S&P 500 already holds, and {high} of {len(ins)} funds are more than sixty percent index names.",
               f"Across {len(by_theme)} themes and {len(themes)} funds, the median fee is {p(med([r.get('expenseRatio') for r in themes]), d=2)}; measured against only the part of each fund that differs from the S&P 500, the median fee for the difference is {p(med([r.get('activeFee') for r in themes]), d=2)}.",
               f"{len(twins)} pairs of funds hold portfolios that are more than half identical by weight; holding both is close to holding one of them twice."]
    return {'slug': 'themes-index', 'desk': 'themes', 'title': 'How much of a theme is already the index', 'asOf': as_of, 'summary': summary,
            'tables': [{'title': 'By theme, largest assets first', 'columns': ['Theme', 'Funds', 'Median in the S&P 500', 'Median active share', 'Median fee', 'Median fee for the difference', 'Beat the S&P 500, one year', 'Median total return, one year'], 'rows': rows},
                       {'title': 'Same portfolio, two names: pairs more than half identical', 'columns': ['Pair', 'Weight overlap', 'Theme', 'Fee, first', 'Fee, second'], 'rows': t_rows}],
            'method': 'Holdings from each fund’s latest public SEC N-PORT filing (issuer daily files for ARK and First Trust); in-index weight and active share computed by ETFIQ against the IVV and QQQM books; fees from prospectus XBRL; returns from Tiingo end-of-day prices with distributions reinvested. Themes are ETFIQ’s editorial taxonomy. Medians across funds.',
            'data': f'{BASE}/data/thematic.json', 'app': f'{BASE}/#/themes/themes'}


# ---------------------------------------------------------------- pages
STYLE = """body{margin:0;background:#F5F7FA;color:#0F1419;font:15px/1.55 Geist,system-ui,-apple-system,'Segoe UI',sans-serif}header{background:#0F1419;color:#F2F4F7;padding:14px 20px;font-weight:700;letter-spacing:-.02em}header a{color:#F2F4F7;text-decoration:none}header b{color:#7AA2FF}main{max-width:920px;margin:0 auto;padding:28px 20px 60px}.eyebrow{font:600 11px/1 Geist,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#5B6675}h1{font-size:32px;letter-spacing:-.025em;margin:8px 0 6px;line-height:1.15}.dek{font-size:17px;color:#3D4756;margin:0 0 20px}.sum p{font-size:16px;margin:0 0 10px}.narr{border-left:4px solid #2457E6;background:#fff;padding:14px 18px;border-radius:0 8px 8px 0;margin:18px 0}.narr .lab{font:600 11px/1 Geist,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#5B6675;margin-bottom:8px}h2{font-size:17px;margin:28px 0 8px;letter-spacing:-.01em}table{border-collapse:collapse;width:100%;font-size:13.5px;background:#fff;border:1px solid #DCE1E8;border-radius:6px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #E6EAF0;vertical-align:top}th{font:600 10.5px/1 Geist,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#5B6675;background:#F7F9FB}td:not(:first-child),th:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}.note{color:#5B6675;font-size:13px;margin-top:22px}.cta{display:inline-block;margin:10px 0 0;padding:9px 14px;background:#2457E6;color:#fff;border-radius:6px;text-decoration:none;font-weight:600}nav.list a{display:block;padding:14px 16px;border:1px solid #DCE1E8;border-radius:8px;background:#fff;margin:10px 0;color:#0F1419;text-decoration:none}nav.list b{display:block;font-size:17px}nav.list span{color:#5B6675;font-size:13px}.wrap{overflow-x:auto}footer{margin-top:40px;color:#5B6675;font-size:13px}"""


def esc(s):
    return html.escape(str(s if s is not None else '').replace('\u2014', '-'), quote=True)


def piece_page(pc, narrative):
    url = f"{BASE}/research/{pc['slug']}.html"
    tables = ''.join(f"<h2>{esc(t['title'])}</h2><div class=\"wrap\"><table><thead><tr>{''.join(f'<th>{esc(c)}</th>' for c in t['columns'])}</tr></thead><tbody>{''.join('<tr>' + ''.join(f'<td>{esc(c)}</td>' for c in r) + '</tr>' for r in t['rows'])}</tbody></table></div>" for t in pc['tables'])
    narr = f"<div class=\"narr\"><div class=\"lab\">Narrative drafted by Claude from the tables on this page and checked against them line by line</div>{narrative}</div>" if narrative else ''
    ld = {'@context': 'https://schema.org', '@type': 'Article', 'headline': pc['title'], 'datePublished': pc['asOf'], 'dateModified': pc['asOf'], 'author': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'publisher': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'url': url, 'description': pc['summary'][0]}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(pc['title'])} | ETFIQ Research</title><meta name="description" content="{esc(pc['summary'][0])}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<meta property="og:title" content="{esc(pc['title'])}"><meta property="og:description" content="{esc(pc['summary'][0])}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}</style></head>
<body><header><a href="{BASE}/">ETF<b>IQ</b></a> &nbsp;·&nbsp; <a href="/research/">Research</a></header><main>
<div class="eyebrow">ETFIQ Research · {esc({'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk'}[pc['desk']])} · data as of {fdate(pc['asOf'])}</div>
<h1>{esc(pc['title'])}</h1>
<div class="sum">{''.join(f'<p>{esc(s)}</p>' for s in pc['summary'])}</div>
<a class="cta" href="{pc['app']}">Open the live desk</a>
{narr}{tables}
<p class="note"><b>Method.</b> {esc(pc['method'])} Data file: <a href="{pc['data']}">{pc['data']}</a>. Rebuilt every trading night. ETFIQ is an independent publisher and makes no recommendations. <a href="{BASE}/#/standards">Standards</a></p>
</main><footer><a href="/research/">All research</a> · <a href="/buffer/">Buffer desk pages</a> · <a href="/income/">Income desk pages</a> · <a href="/themes/">Themes desk pages</a></footer></body></html>"""


def index_page(pieces):
    url = f'{BASE}/research/'
    items = ''.join(f"<a href=\"/research/{pc['slug']}.html\"><b>{esc(pc['title'])}</b><span>{esc({'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk'}[pc['desk']])} · data as of {fdate(pc['asOf'])} · {esc(pc['summary'][0][:140])}…</span></a>" for pc in pieces)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETFIQ Research</title><meta name="description" content="Findings computed from ETFIQ's three desks: buffer ETFs, option-income ETFs and thematic ETFs. Rebuilt every trading night, with the method and the data file for every table."><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg"><style>{STYLE}</style></head>
<body><header><a href="{BASE}/">ETF<b>IQ</b></a> &nbsp;·&nbsp; Research</header><main>
<div class="eyebrow">ETFIQ Research</div><h1>What the data shows, one piece per desk</h1><p class="dek">Findings computed from the desks' own files, rebuilt every trading night, with the method and the data file for every table. Never a fund pick.</p>
<nav class="list">{items}</nav>
<p class="note">ETFIQ is an independent publisher, not an issuer, broker or adviser. <a href="{BASE}/#/standards">Standards and ownership</a></p></main></body></html>"""


def build():
    funds = load('site/data/funds.json', [])
    income = load('site/data/income.json', [])
    th = load('site/data/thematic.json', {'funds': [], 'matrix': {}})
    sources = load('site/data/sources.json', {})
    meta, imeta, tmeta = load('site/data/meta.json', {}), load('site/data/income_meta.json', {}), load('site/data/thematic_meta.json', {})
    pieces = []
    if funds:
        pieces.append(buffer_piece(funds, meta.get('asOf')))
    if income:
        pieces.append(income_piece(income, sources, imeta.get('asOf')))
    if th.get('funds'):
        pieces.append(themes_piece(th['funds'], th.get('matrix') or {}, tmeta.get('asOf')))
    (ROOT / 'data' / 'research').mkdir(parents=True, exist_ok=True)
    out = SITE / 'research'
    out.mkdir(exist_ok=True)
    for pc in pieces:
        (ROOT / 'data' / 'research' / f"{pc['slug']}.json").write_text(json.dumps(pc, indent=1))
        narr_p = ROOT / 'data' / 'research' / f"{pc['slug']}.narrative.html"
        narrative = narr_p.read_text() if narr_p.exists() else ''
        (out / f"{pc['slug']}.html").write_text(piece_page(pc, narrative))
    (out / 'index.html').write_text(index_page(pieces))
    print(f'research: {len(pieces)} pieces')
    for pc in pieces:
        print(f"  {pc['slug']}: {pc['summary'][0][:120]}")


if __name__ == '__main__':
    build()
