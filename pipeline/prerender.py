#!/usr/bin/env python3
"""Static, crawlable pages for search engines and AI assistants.

The site is a single JavaScript page, which most AI crawlers and some search crawlers never execute. This script writes
plain HTML the way the page would read it: one page per fund on every desk, one index page per desk, robots.txt,
sitemap.xml and llms.txt. Every figure comes from the same data files the page inlines, with the same as-of dates
and the same definitions, so a crawler and a reader see the same numbers.

Writes: site/funds/<TICKER>.html, site/buffer/index.html, site/income/index.html, site/themes/index.html,
site/robots.txt, site/sitemap.xml, site/llms.txt. Run after build_site.py.
"""
import datetime
import html
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
BASE = 'https://etfiq.com'
TODAY = datetime.date.today().isoformat()


def load(p, default):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else default


def esc(s):
    return html.escape(str(s if s is not None else '').replace('\u2014', '-'), quote=True)


def pct(v, sign=True, d=1):
    if v is None:
        return 'not published'
    return (f'{v:+.{d}f}%' if sign else f'{v:.{d}f}%').replace('-', '−')


def pts(v):
    return 'not available' if v is None else (f'{v:+.1f} pts').replace('-', '−')


def fdate(d):
    try:
        return datetime.date.fromisoformat(d).strftime('%b %-d, %Y')
    except Exception:
        return d or ''


# ---------------------------------------------------------------- buffer desk
STATE_LABEL = {'capped': 'At cap', 'exhausted': 'Buffer exhausted', 'engaged': 'Buffer working', 'unprotected': 'In the unprotected slice', 'uncapped': 'Uncapped', 'floor': 'Full floor', 'open': 'Open'}


def buffer_state(f):
    ref, bs, be = f['refReturn'], f['bufferStart'], f['bufferEnd']
    used = max(0.0, min(f.get('startBuffer') or (bs - be), bs - ref))
    if f.get('isFloor') and ref < bs:
        return 'floor'
    if not f.get('isUncapped') and f.get('startCap') is not None and ref >= f['startCap']:
        return 'capped'
    if ref < be:
        return 'exhausted'
    if used > 0:
        return 'engaged'
    if ref < bs:
        return 'unprotected'
    return 'uncapped' if f.get('isUncapped') else 'open'


def buffer_words(f):
    ref = f['refAsset']
    state = buffer_state(f)
    s = []
    if state == 'capped':
        s.append(f"{ref} has already risen past this fund's cap of {pct(f['startCap'])} for the period, so in index terms there is no more upside to collect. The fund's own price can still drift up to about {pct(f.get('remainingCapFund'), sign=False)} as the period runs out.")
    elif f.get('isUncapped'):
        s.append(f"This fund has no cap. It takes a share of any further rise in {ref}.")
    elif f.get('remainingCapFund') is not None:
        s.append(f"From here the fund can gain about {pct(f['remainingCapFund'], sign=False)} more before it reaches its cap.")
    dbb = f.get('downsideBeforeBuffer') or 0
    fall_ref = max(0.0, (1 - (1 + f['bufferStart'] / 100) / (1 + f['refReturn'] / 100)) * 100)
    if dbb > 0:
        s.append(f"The fund's price can fall {pct(dbb, sign=False)} from here before the buffer starts absorbing losses, by the issuer's figure. In index terms, {ref} can fall {pct(fall_ref, sign=False)} from today's level to the point where the buffer begins.")
    sb = f.get('startBuffer') or (f['bufferStart'] - f['bufferEnd'])
    used = max(0.0, min(sb, f['bufferStart'] - f['refReturn']))
    left = None if f.get('isFloor') else round(sb - used, 2)
    if left is not None:
        s.append(f"Protection left, in index points: {pct(left, sign=False)} of the {pct(sb, sign=False)} buffer still sits below today's {ref} level.")
    s.append(f"{f['daysRemaining']} days remain. On {fdate(f['periodEnd'])} the period ends and a new cap is set.")
    return ' '.join(s), state, left, fall_ref


def buffer_page(f, as_of):
    words, state, left, fall_ref = buffer_words(f)
    title = f"{f['ticker']} buffer ETF today: {f['name']}"
    desc = f"{f['ticker']} ({f['issuer']}) on {fdate(as_of)}: {STATE_LABEL[state]}. Can still gain {pct(f.get('remainingCapFund'), sign=False)}, fund can fall {pct(f.get('downsideBeforeBuffer'), sign=False)} before the buffer, {ref_line(f)}."
    rows = [
        ('Reference index', f['refAsset']), ('Buffer', f.get('bufferLabel', '')), ('Outcome period', f"{fdate(f['periodStart'])} to {fdate(f['periodEnd'])}" + (f" ({f['periodMonths']} months)" if f.get('periodMonths') else '')),
        ('Starting cap', 'uncapped' if f.get('isUncapped') else pct(f.get('startCap'))), (f"{f['refAsset']} return since period start", pct(f['refReturn'])), ('Fund return since period start', pct(f.get('fundReturn'))),
        ('Band state today (ETFIQ)', STATE_LABEL[state]), ('Can still gain (issuer, fund price)', 'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False)),
        ('Fall before buffer (issuer, fund price)', pct(f.get('downsideBeforeBuffer'), sign=False)), (f"Fall to the buffer in index terms (ETFIQ)", pct(fall_ref, sign=False)),
        ('Protection left in index points (ETFIQ)', 'full floor' if left is None else f"{pct(left, sign=False)} of {pct(f.get('startBuffer') or (f['bufferStart'] - f['bufferEnd']), sign=False)}"), ('Days left in period', str(f.get('daysRemaining', ''))), ('Expense ratio', pct(f.get('expenseRatio'), sign=False, d=2)),
    ]
    return page(title, desc, f['ticker'], f['name'], f['issuer'], 'buffer', as_of, words, rows, f"{BASE}/#/buffer/check/{f['ticker']}",
                'Issuer-published figures as of the date shown; ETFIQ calculations marked. Definitions on the learn page.')


def ref_line(f):
    return f"{f['refAsset']} {pct(f['refReturn'])} since the period began"


# ---------------------------------------------------------------- income desk
def income_words(r, src):
    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD')
    s = []
    if w:
        label = 'the last 1 year' if w is (r.get('windows') or {}).get('1Y') else f"since launch on {fdate(r.get('inception'))}"
        s.append(f"Over {label}, {r['ticker']} paid {pct(w['cash'], sign=False)} of its starting value in cash distributions while its price {'fell ' + pct(-w['price'], sign=False) if w['price'] < 0 else 'rose ' + pct(w['price'], sign=False)}. With every distribution reinvested, the fund returned {pct(w['total'])}.")
        if w.get('bench') is not None:
            s.append(f"{r.get('benchmarkName') or r['benchmark']} returned {pct(w['bench'])} over the same days, so a holder was {'ahead' if w['gap'] > 0.5 else 'behind' if w['gap'] < -0.5 else 'about even'}{(' by ' + f"{abs(w['gap']):.1f} pts") if abs(w['gap']) > 0.5 else ''}.")
    if r.get('distributionRate') is not None:
        s.append(f"At today's price the latest distribution annualises to {pct(r['distributionRate'], sign=False)}, paid {r.get('payoutFrequency') or 'periodically'}.")
    if src and src.get('latest') and src['latest'].get('roc') is not None:
        s.append(f"{src['issuer']} estimates that {src['latest']['roc']:.0f}% of the distribution paid {fdate(src['latest'].get('date') or src.get('asOf'))} was a return of capital (19a-1 notice, estimated, a tax characterisation rather than a measure of erosion).")
    return ' '.join(s), w


def income_page(r, as_of, src):
    words, w = income_words(r, src)
    title = f"{r['ticker']} income ETF: am I ahead of {r['benchmark']}? {r['name']}"
    gap = pts(w['gap']) if w and w.get('gap') is not None else 'not available'
    desc = f"{r['ticker']} ({r['issuer']}) over 1 year to {fdate(as_of)}: paid {pct(w['cash'], sign=False) if w else 'n/a'} in cash, total return {pct(w['total']) if w else 'n/a'}, {gap} against {r['benchmark']}."
    rows = [('Strategy', r.get('strategy', '')), ('Benchmark', f"{r.get('benchmarkName') or r['benchmark']}" + (' (proxy)' if r.get('benchmarkKind') == 'proxy' else '')), ('Pays', r.get('payoutFrequency') or 'not established'),
            ('Payout rate, annualised (ETFIQ)', pct(r.get('distributionRate'), sign=False)), ('Expense ratio (prospectus XBRL)', pct(r.get('expenseRatio'), sign=False, d=2)), ('Cash paid, trailing 12 months (ETFIQ)', pct(r.get('trailing12mCash'), sign=False)), ('Launched', fdate(r.get('inception')))]
    for k, lab in (('3M', '3 months'), ('6M', '6 months'), ('1Y', '1 year'), ('3Y', '3 years'), ('ITD', 'since launch')):
        x = (r.get('windows') or {}).get(k)
        if x:
            rows.append((f"{lab}: paid / price / total / {r['benchmark']} / ahead or behind (ETFIQ)", f"{pct(x['cash'], sign=False)} / {pct(x['price'])} / {pct(x['total'])} / {pct(x.get('bench'))} / {pts(x.get('gap'))}"))
    if src and src.get('latest') and src['latest'].get('roc') is not None:
        rows.append((f"Return of capital, latest distribution ({src['issuer']} 19a-1 estimate)", pct(src['latest']['roc'], sign=False)))
    return page(title, desc, r['ticker'], r['name'], r['issuer'], 'income', as_of, words, rows, f"{BASE}/#/income/check/{r['ticker']}",
                'Every figure is an ETFIQ calculation from exchange prices and cash distributions (Tiingo end-of-day), total return with distributions reinvested. Return of capital is the issuer’s estimate.')


# ---------------------------------------------------------------- themes desk
def theme_words(r):
    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD')
    s = []
    v = r.get('vsSPY')
    if v:
        s.append(f"By weight, {v['inIndex']:.0f}% of {r['ticker']}'s portfolio is stocks that are also in the S&P 500; its active share against the S&P 500 is {v['activeShare']:.0f}%.")
        s.append(f"The top ten holdings are {r['top10Weight']:.0f}% of the fund across {r['holdingsCount']} positions, as filed for {fdate(r.get('holdingsAsOf'))}.")
    else:
        s.append(f"{r['ticker']} has no public holdings filing captured yet.")
    if w:
        s.append(f"Over the last year the fund returned {pct(w['total'])} with distributions reinvested against {pct(w.get('bench'))} for the S&P 500, so a holder was {'ahead' if (w.get('gap') or 0) > 0.5 else 'behind' if (w.get('gap') or 0) < -0.5 else 'about even'}{(' by ' + f"{abs(w['gap']):.1f} pts") if w.get('gap') is not None and abs(w['gap']) > 0.5 else ''}.")
    if r.get('drawdown') is not None and r['drawdown'] < -5:
        s.append(f"It sits {pct(-r['drawdown'], sign=False)} below its all-time high of {fdate(r.get('highDate'))}.")
    return ' '.join(s), w


def theme_page(r, as_of):
    words, w = theme_words(r)
    v, q = r.get('vsSPY'), r.get('vsQQQ')
    title = f"{r['ticker']} thematic ETF: what did I actually buy? {r['name']}"
    desc = f"{r['ticker']} ({r['issuer']}, {r['themeName']}): {v['inIndex']:.0f}% already in the S&P 500, active share {v['activeShare']:.0f}%, top ten {r['top10Weight']:.0f}%." if v else f"{r['ticker']} ({r['issuer']}, {r['themeName']}): returns against the S&P 500 and Nasdaq-100 as of {fdate(as_of)}."
    rows = [('Theme (ETFIQ, editorial)', r['themeName']), ('Launched', fdate(r.get('inception')))]
    if v:
        rows += [('Already in the S&P 500, by weight (ETFIQ)', pct(v['inIndex'], sign=False)), ('Active share vs the S&P 500 (ETFIQ)', pct(v['activeShare'], sign=False)),
                 ('Already in the Nasdaq-100, by weight (ETFIQ)', pct(q['inIndex'], sign=False) if q else 'n/a'), ('Active share vs the Nasdaq-100 (ETFIQ)', pct(q['activeShare'], sign=False) if q else 'n/a'),
                 ('Top ten holdings weight', pct(r['top10Weight'], sign=False)), ('Holdings', str(r['holdingsCount'])), ('Net assets (latest filing)', f"${r['assets']/1e6:,.0f}M" if r.get('assets') else 'n/a'), ('Holdings as of (SEC N-PORT)', fdate(r.get('holdingsAsOf')))]
        rows.append(('Top holdings', ', '.join(f"{h['n']} {h['w']:.1f}%" for h in r.get('top', [])[:10])))
    for k, lab in (('3M', '3 months'), ('6M', '6 months'), ('1Y', '1 year'), ('3Y', '3 years'), ('ITD', 'since launch')):
        x = (r.get('windows') or {}).get(k)
        if x:
            rows.append((f"{lab}: total return / S&P 500 / gap / Nasdaq-100 gap (ETFIQ)", f"{pct(x['total'])} / {pct(x.get('bench'))} / {pts(x.get('gap'))} / {pts(x.get('gapQ'))}"))
    rows.append(('Below its all-time high (ETFIQ)', pct(r.get('drawdown'))))
    if r.get('expenseRatio') is not None:
        rows.append(('Expense ratio (prospectus XBRL)', pct(r['expenseRatio'], sign=False, d=2)))
    if r.get('activeFee') is not None:
        rows.append(('Fee for the part that differs from the S&P 500, active expense ratio (ETFIQ)', pct(r['activeFee'], sign=False, d=2)))
    if r.get('peers'):
        rows.append(('Closest funds by holdings overlap', ', '.join(f"{p['t']} {p['o']}%" for p in r['peers'])))
    return page(title, desc, r['ticker'], r['name'], r['issuer'], 'themes', as_of, words, rows, f"{BASE}/#/themes/check/{r['ticker']}",
                'Holdings from the fund’s latest public SEC N-PORT filing; overlap and active share computed by ETFIQ against the IVV and QQQM books; returns from Tiingo end-of-day prices with distributions reinvested.')


# ---------------------------------------------------------------- page shell
DESK_NAME = {'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk'}
STYLE = """body{margin:0;background:#F5F7FA;color:#0F1419;font:15px/1.5 Geist,system-ui,-apple-system,'Segoe UI',sans-serif}main{max-width:820px;margin:0 auto;padding:28px 20px 60px}header{background:#0F1419;color:#F2F4F7;padding:14px 20px;font-weight:700;letter-spacing:-.02em}header a{color:#F2F4F7;text-decoration:none}header b{color:#7AA2FF}h1{font-size:28px;letter-spacing:-.02em;margin:18px 0 6px}.lede{color:#3D4756;font-size:16px}.tk{font-family:'Geist Mono',ui-monospace,monospace;font-weight:600}.cta{display:inline-block;margin:14px 0 22px;padding:10px 16px;background:#2457E6;color:#fff;border-radius:6px;text-decoration:none;font-weight:600}table{border-collapse:collapse;width:100%;margin:12px 0 18px;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #DCE1E8;vertical-align:top}th{width:44%;color:#3D4756;font-weight:500}.note{color:#5B6675;font-size:13px}nav.desks a{margin-right:14px}footer{margin-top:40px;color:#5B6675;font-size:13px}"""


def page(title, desc, ticker, name, issuer, desk, as_of, words, rows, app_url, method):
    url = f"{BASE}/funds/{ticker}.html"
    ld = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'FinancialProduct', 'name': name, 'alternateName': ticker, 'identifier': ticker, 'provider': {'@type': 'Organization', 'name': issuer}, 'category': f'Exchange-traded fund, {DESK_NAME[desk].lower()}', 'url': url},
        {'@type': 'Dataset', 'name': f'ETFIQ {DESK_NAME[desk].lower()} record for {ticker}', 'description': desc, 'dateModified': as_of, 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'license': 'https://etfiq.com/#/standards', 'isAccessibleForFree': True, 'url': url},
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': as_of, 'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE}}]}
    trs = ''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in rows)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}</style></head>
<body><header><a href="{BASE}/">ETF<b>IQ</b></a> &nbsp;·&nbsp; <a href="/{desk}/">{DESK_NAME[desk]}</a></header><main>
<p class="note">Data as of {fdate(as_of)}. {esc(method)}</p>
<h1><span class="tk">{esc(ticker)}</span> · {esc(name)}</h1><p class="lede">{esc(issuer)} · {DESK_NAME[desk]}</p>
<a class="cta" href="{app_url}">Open the live card on ETFIQ</a>
<p>{esc(words)}</p>
<table><tbody>{trs}</tbody></table>
<p class="note">ETFIQ is an independent publisher of exchange-traded fund data. It is not a fund issuer, broker-dealer or investment adviser, and it makes no recommendations; sort orders and figures are stated arithmetic on published data. <a href="{BASE}/#/standards">Standards</a> · <a href="{BASE}/#/{desk}/learn">How to read this desk</a></p>
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/llms.txt">llms.txt</a></nav></footer></body></html>"""


def index_page(desk, rows, as_of, intro):
    url = f"{BASE}/{desk}/"
    title = {'buffer': 'Every buffer ETF on one comparable band', 'income': 'Every option-income ETF against its benchmark', 'themes': 'Every thematic ETF: what you actually bought'}[desk]
    head = {'buffer': ['Ticker', 'Fund', 'Issuer', 'Index', 'Buffer', 'Period ends', 'Can still gain', 'Fall before buffer', 'State'],
            'income': ['Ticker', 'Fund', 'Issuer', 'Benchmark', 'Paid 1Y', 'Total return 1Y', 'Ahead or behind 1Y', 'Return of capital, latest'],
            'themes': ['Ticker', 'Fund', 'Issuer', 'Theme', 'In the S&P 500', 'Active share vs S&P', 'Top ten', 'Total return 1Y', 'vs S&P 500 1Y']}[desk]
    trs = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    ld = {'@context': 'https://schema.org', '@type': 'Dataset', 'name': f'ETFIQ {DESK_NAME[desk].lower()}', 'description': intro, 'dateModified': as_of, 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'isAccessibleForFree': True, 'url': url}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(intro)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}main{{max-width:1100px}}th,td{{white-space:nowrap}}th{{width:auto}}</style></head>
<body><header><a href="{BASE}/">ETF<b>IQ</b></a> &nbsp;·&nbsp; {DESK_NAME[desk]}</header><main>
<p class="note">Data as of {fdate(as_of)}.</p><h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>
<a class="cta" href="{BASE}/#/{desk}/desk">Open the live desk on ETFIQ</a>
<div style="overflow-x:auto"><table><thead><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr></thead><tbody>{trs}</tbody></table></div>
<p class="note">ETFIQ is an independent publisher. It makes no recommendations; every list is stated arithmetic on published data. <a href="{BASE}/#/standards">Standards</a></p>
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a></nav></footer></body></html>"""


def build():
    funds = load('site/data/funds.json', [])
    income = load('site/data/income.json', [])
    themes = load('site/data/thematic.json', {'funds': []})['funds']
    sources = load('site/data/sources.json', {})
    meta = load('site/data/meta.json', {}); imeta = load('site/data/income_meta.json', {}); tmeta = load('site/data/thematic_meta.json', {})
    as_b, as_i, as_t = meta.get('asOf', TODAY), imeta.get('asOf', TODAY), tmeta.get('asOf', TODAY)
    out = SITE / 'funds'
    out.mkdir(exist_ok=True)
    for old in out.glob('*.html'):
        old.unlink()
    urls = []
    for f in funds:
        (out / f"{f['ticker']}.html").write_text(buffer_page(f, as_b)); urls.append((f"{BASE}/funds/{f['ticker']}.html", as_b))
    for r in income:
        (out / f"{r['ticker']}.html").write_text(income_page(r, as_i, sources.get(r['ticker']))); urls.append((f"{BASE}/funds/{r['ticker']}.html", as_i))
    for r in themes:
        if (out / f"{r['ticker']}.html").exists():
            continue  # a ticker on two desks keeps its first page
        (out / f"{r['ticker']}.html").write_text(theme_page(r, as_t)); urls.append((f"{BASE}/funds/{r['ticker']}.html", as_t))
    link = lambda t: f'<a href="/funds/{t}.html" class="tk">{t}</a>'
    w1 = lambda r: (r.get('windows') or {}).get('1Y') or {}
    b_rows = [[link(f['ticker']), esc(f['name']), esc(f['issuer']), f['refAsset'], esc(f.get('bufferLabel', '')), fdate(f['periodEnd']), 'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False), pct(f.get('downsideBeforeBuffer'), sign=False), STATE_LABEL[buffer_state(f)]] for f in funds]
    i_rows = [[link(r['ticker']), esc(r['name']), esc(r['issuer']), r['benchmark'], pct(w1(r).get('cash'), sign=False), pct(w1(r).get('total')), pts(w1(r).get('gap')), pct(((sources.get(r['ticker']) or {}).get('latest') or {}).get('roc'), sign=False)] for r in income]
    t_rows = [[link(r['ticker']), esc(r['name']), esc(r['issuer']), esc(r['themeName']), pct((r.get('vsSPY') or {}).get('inIndex'), sign=False), pct((r.get('vsSPY') or {}).get('activeShare'), sign=False), pct(r.get('top10Weight'), sign=False), pct(w1(r).get('total')), pts(w1(r).get('gap'))] for r in themes]
    for desk, rows, as_of, intro in (('buffer', b_rows, as_b, f'{len(funds)} defined outcome (buffer) ETFs from every issuer ETFIQ covers, each placed on one comparable band from buffer to cap, with how much it can still gain, how far it can fall before the buffer, and the protection left, as of {fdate(as_b)}.'),
                                     ('income', i_rows, as_i, f'{len(income)} option-income ETFs measured against the index or stock they write options on: cash paid, price change, total return with distributions reinvested, and whether a holder came out ahead, as of {fdate(as_i)}.'),
                                     ('themes', t_rows, as_t, f'{len(themes)} thematic ETFs in 27 themes: how much of each is already in the S&P 500, active share, concentration, and returns against the plain index, from SEC holdings filings and exchange prices as of {fdate(as_t)}.')):
        d = SITE / desk
        d.mkdir(exist_ok=True)
        (d / 'index.html').write_text(index_page(desk, rows, as_of, intro)); urls.append((f'{BASE}/{desk}/', as_of))
    for r in sorted((SITE / 'research').glob('*.html')) if (SITE / 'research').exists() else []:
        urls.append((f'{BASE}/research/' + ('' if r.name == 'index.html' else r.name), max(as_b, as_i, as_t)))
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + f'<url><loc>{BASE}/</loc><lastmod>{max(as_b, as_i, as_t)}</lastmod></url>\n' + ''.join(f'<url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n' for u, d in urls) + '</urlset>\n'
    (SITE / 'sitemap.xml').write_text(sm)
    (SITE / 'robots.txt').write_text("User-agent: *\nAllow: /\n\n" + ''.join(f'User-agent: {b}\nAllow: /\n\n' for b in ('GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-User', 'Claude-SearchBot', 'anthropic-ai', 'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Googlebot', 'Bingbot', 'Applebot', 'Applebot-Extended', 'CCBot', 'Amazonbot', 'meta-externalagent', 'DuckAssistBot', 'YouBot', 'cohere-ai')) + f'Sitemap: {BASE}/sitemap.xml\n')
    (SITE / 'llms.txt').write_text(f"""# ETFIQ

> Independent data on exchange-traded funds, in plain words, for retail investors and advisers. Three desks: buffer (defined outcome) ETFs on one comparable band; option-income ETFs against the index or stock they write options on; thematic ETFs measured by how much of them is already in the S&P 500. ETFIQ is not an issuer, broker or adviser and makes no recommendations. Sort orders are stated arithmetic on published data.

Data as of: buffer desk {as_b}, income desk {as_i}, themes desk {as_t}. Refreshed every trading night.

## Definitions

- Buffer desk: "Can still gain" and "Fall before buffer" are the issuer's own figures in fund-price terms (remaining cap net of fees; downside before buffer). "Protection left" is ETFIQ's calculation in index points: the part of the buffer still below today's index level. The outcome band places every fund on one axis from buffer floor to cap in reference-return space.
- Income desk: cash paid, price change and total return with distributions reinvested over 3M, 6M, 1Y, 3Y and since launch, from Tiingo end-of-day prices; "ahead or behind" is total return minus the benchmark's total return in points. Return of capital figures are issuers' Rule 19a-1 estimates.
- Themes desk: holdings from each fund's latest public SEC N-PORT filing; "in the S&P 500" is the fund's weight in securities the index holds; active share is one minus the summed minimum weights against the IVV (S&P 500) or QQQM (Nasdaq-100) book; themes are ETFIQ's editorial taxonomy.

## Pages

- [Buffer desk, every fund]({BASE}/buffer/): {len(funds)} funds
- [Income desk, every fund]({BASE}/income/): {len(income)} funds
- [Themes desk, every fund]({BASE}/themes/): {len(themes)} funds
- Fund pages: {BASE}/funds/TICKER.html, for example {BASE}/funds/PJAN.html, {BASE}/funds/JEPI.html, {BASE}/funds/ARKK.html
- [ETFIQ Research]({BASE}/research/): one computed piece per desk, rebuilt nightly, with method and data file
- [Portfolio desk]({BASE}/#/portfolio): enter ETF positions with weights, shares or dollars; the look-through to filed holdings, overlap between positions, weighted fee, blended buffer protection, cash by month, and the outcome of a market move on buffer positions from published terms. Positions travel in the link; nothing to sign up for.
- [Standards and ownership]({BASE}/#/standards)
- [Live application]({BASE}/)

## Data files

- {BASE}/data/funds.json (buffer desk records), {BASE}/data/income.json (income desk records), {BASE}/data/thematic.json (themes desk records and the fund-to-fund overlap matrix), {BASE}/data/payouts.json (payout calendar), {BASE}/data/sources.json (19a-1 estimates). Free to read; cite ETFIQ and the as-of date.
""")
    print(f'prerendered {len(urls)} pages: {len(funds)} buffer, {len(income)} income, {len(themes)} themes')


if __name__ == '__main__':
    build()
