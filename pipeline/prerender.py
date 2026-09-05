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

import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rail as R  # noqa: E402

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
                'Issuer-published figures as of the date shown; ETFIQ calculations marked. Definitions on the learn page.',
                faqs=buffer_faqs(f, state, left, fall_ref), related=embed_block('buffer', f['ticker'], f['name']) + related_links('buffer', f['ticker']))


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
                'Every figure is an ETFIQ calculation from exchange prices and cash distributions (Tiingo end-of-day), total return with distributions reinvested. Return of capital is the issuer’s estimate.',
                faqs=income_faqs(r, w, src), related=embed_block('income', r['ticker'], r['name']) + related_links('income', r['ticker']))


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
                'Holdings from the fund’s latest public SEC N-PORT filing; overlap and active share computed by ETFIQ against the IVV and QQQM books; returns from Tiingo end-of-day prices with distributions reinvested.',
                faqs=theme_faqs(r, w), related=embed_block('themes', r['ticker'], r['name']) + related_links('themes', r['ticker']))


def buffer_faqs(f, state, left, fall_ref):
    t, ref = f['ticker'], f['refAsset']
    out = []
    if f.get('isUncapped'):
        out.append((f'Does {t} have a cap?', f'No. {t} takes a share of any further rise in {ref}, so there is no ceiling on the upside this period.'))
    elif state == 'capped':
        out.append((f'How much can {t} still gain?', f'Nothing more in index terms. {ref} has already passed the cap of {pct(f["startCap"])} for this period, which runs from {fdate(f["periodStart"])} to {fdate(f["periodEnd"])}.'))
    elif f.get('remainingCapFund') is not None:
        out.append((f'How much can {t} still gain?', f'About {pct(f["remainingCapFund"], sign=False)} from today\'s price before it reaches its cap, by the issuer\'s published figure. The cap for the period was set at {pct(f.get("startCap"))}.'))
    dbb = f.get('downsideBeforeBuffer') or 0
    out.append((f'How far can {t} fall before the buffer helps?',
                f'{pct(dbb, sign=False)} in fund-price terms, by the issuer\'s figure. In index terms {ref} can fall {pct(fall_ref, sign=False)} from today\'s level before the buffer begins. Losses until that point are the holder\'s.'))
    sb = f.get('startBuffer') or (f['bufferStart'] - f['bufferEnd'])
    if left is not None:
        out.append((f'How much of the {t} buffer is left?', f'{pct(left, sign=False)} of the {pct(sb, sign=False)} buffer still sits below today\'s {ref} level. That is an ETFIQ calculation in index points, on one definition for every issuer.'))
    out.append((f'When does {t} reset?', f'The outcome period ends on {fdate(f["periodEnd"])}, {f.get("daysRemaining")} days from this data. A new cap is set the next day and the buffer starts again.'))
    if f.get('expenseRatio') is not None:
        out.append((f'What does {t} cost?', f'The prospectus expense ratio is {pct(f["expenseRatio"], sign=False, d=2)} a year.'))
    return out


def income_faqs(r, w, src):
    t = r['ticker']
    out = []
    if w:
        label = 'the last year' if w is (r.get('windows') or {}).get('1Y') else f'since it launched on {fdate(r.get("inception"))}'
        out.append((f'How much has {t} paid over the last year?',
                    f'Over {label}, {t} paid {pct(w["cash"], sign=False)} of its starting price in cash distributions, while the price {"fell " + pct(-w["price"], sign=False) if w["price"] < 0 else "rose " + pct(w["price"], sign=False)}.'))
        if w.get('gap') is not None:
            side = 'ahead of' if w['gap'] > 0.5 else 'behind' if w['gap'] < -0.5 else 'about even with'
            out.append((f'Is {t} ahead of {r["benchmark"]}?',
                        f'With every distribution reinvested, {t} returned {pct(w["total"])} against {pct(w["bench"])} for {r.get("benchmarkName") or r["benchmark"]}, so a holder was {side} it by {abs(w["gap"]):.1f} points.'))
    if r.get('distributionRate') is not None:
        out.append((f'How often does {t} pay, and how much?',
                    f'{t} pays {r.get("payoutFrequency") or "on no established schedule"}. The latest distribution annualises to {pct(r["distributionRate"], sign=False)} at today\'s price, which is not a promise; the next one can differ.'))
    if src and src.get('latest') and src['latest'].get('roc') is not None:
        out.append((f'Is the {t} distribution return of capital?',
                    f'{src["issuer"]} estimates {src["latest"]["roc"]:.0f}% of the distribution paid {fdate(src["latest"].get("date") or src.get("asOf"))} was return of capital. That is a tax characterisation from the fund\'s own 19a-1 notice, not a measure of erosion.'))
    if r.get('expenseRatio') is not None:
        out.append((f'What does {t} cost?', f'The prospectus expense ratio is {pct(r["expenseRatio"], sign=False, d=2)} a year.'))
    return out


def theme_faqs(r, w):
    t, v = r['ticker'], r.get('vsSPY')
    out = []
    if v:
        out.append((f'How much of {t} is already in the S&P 500?',
                    f'{v["inIndex"]:.0f}% of {t} by weight is stocks the S&P 500 already holds. Its active share against the index is {v["activeShare"]:.0f}%, so that share is the part doing something different.'))
        out.append((f'What does {t} hold?',
                    f'{r["holdingsCount"]} positions as filed for {fdate(r.get("holdingsAsOf"))}, with the top ten at {r["top10Weight"]:.0f}% of the fund. The largest are ' + ', '.join(f'{h["n"]} at {h["w"]:.1f}%' for h in (r.get('top') or [])[:3]) + '.'))
    if w and w.get('gap') is not None:
        side = 'ahead of' if w['gap'] > 0.5 else 'behind' if w['gap'] < -0.5 else 'about even with'
        out.append((f'Has {t} beaten the S&P 500?',
                    f'Over the last year {t} returned {pct(w["total"])} with distributions reinvested, against {pct(w["bench"])} for the S&P 500, so it finished {side} the index by {abs(w["gap"]):.1f} points.'))
    if r.get('expenseRatio') is not None:
        fee = f'The prospectus expense ratio is {pct(r["expenseRatio"], sign=False, d=2)} a year.'
        if r.get('activeFee') is not None:
            fee += f' Because {v["activeShare"]:.0f}% of the fund differs from the S&P 500, the fee on that differing part works out at {pct(r["activeFee"], sign=False, d=2)}.'
        out.append((f'What does {t} cost?', fee))
    return out


# ---------------------------------------------------------------- explainers and standards, lifted from the app
DOC_RE = None


def app_doc(fn_name):
    """The static HTML of one of the app's document views, taken from site/index.html so the two never drift.
    Those views are plain template literals with one helper, d(term, definition), and no data interpolation."""
    src = (SITE / 'index.html').read_text()
    i = src.index(f'function {fn_name}(')
    j = src.index('\nfunction ', i + 10)
    body = src[i:j]
    i = body.index('return `') + len('return `')
    j = body.rindex('`;')
    tpl = body[i:j]
    tpl = re.sub(r"\$\{d\('((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)'\)\}",
                 lambda m: f'<dt>{m.group(1)}</dt><dd>{m.group(2)}</dd>', tpl)
    tpl = re.sub(r'<p><button[^>]*data-explain[^>]*>.*?</button></p>', '', tpl, flags=re.S)
    tpl = tpl.replace("\\'", "'").replace('\\`', '`')
    return tpl


def terms_of(html_):
    return [(re.sub(r'<[^>]+>', '', a).strip(), re.sub(r'<[^>]+>', '', b).strip()) for a, b in re.findall(r'<dt>(.*?)</dt><dd>(.*?)</dd>', html_, re.S)]


def doc_page(slug, title, desc, inner, ld_extra=None, desk=None, crumb=None):
    url = f'{BASE}/{slug}'
    ld = {'@context': 'https://schema.org', '@graph': (ld_extra or []) + [
        crumbs([('ETFIQ', BASE + '/')] + (crumb or []) + [(title, url)]),
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': TODAY,
         'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE},
         'publisher': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}}]}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}.doc dl dt{{font-weight:600;margin:18px 0 6px}}.doc dl dd{{margin:0;color:#3B434F}}.doc h2{{margin-top:28px}}.doc .lede{{font-size:17px;color:#3B434F}}</style></head>
<body>{R.rail(desk or '')}<main class="doc">
{inner}
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/portfolio/">Portfolio desk</a><a href="/research/">Research</a><a href="/learn/">Learn</a><a href="/standards/">Standards</a></nav></footer></body></html>"""


LEARN = {'buffer': ('Reading a buffer ETF: the vocabulary in plain words', 'What the band, the cap, the buffer, protection left and the outcome period mean on a defined outcome ETF, defined one at a time.'),
         'income': ('Reading an income ETF: the vocabulary in plain words', 'What cash paid, total return, the benchmark gap, the payout rate and return of capital mean on an option-income ETF.'),
         'themes': ('Reading a thematic ETF: the vocabulary in plain words', 'What overlap, active share, in-index weight, concentration and drawdown mean on a thematic ETF, and why the name is not the holdings.')}


def learn_pages():
    out = []
    for desk, (title, desc) in LEARN.items():
        inner = app_doc({'buffer': 'viewBufferLearn', 'income': 'viewIncomeLearn', 'themes': 'viewThemesLearn'}[desk])
        inner = re.sub(r'^<div class="doc">|</div>$', '', inner.strip())
        terms = terms_of(inner)
        ld = [{'@type': 'DefinedTermSet', 'name': title, 'url': f'{BASE}/learn/{desk}.html',
               'hasDefinedTerm': [{'@type': 'DefinedTerm', 'name': t, 'description': d[:900]} for t, d in terms]}] if terms else []
        nav = '<h2>The other desks</h2><nav class="rel">' + ''.join(
            f'<a href="/learn/{k}.html">{LEARN[k][0].split(":")[0]}</a>' for k in LEARN if k != desk) + f'<a href="/{desk}/">All {DESK_NAME[desk].split()[0].lower()} ETFs</a></nav>'
        body = inner + nav + f'<p class="note">Definitions as ETFIQ uses them on the {DESK_NAME[desk].lower()}. Every figure on the site is stated arithmetic on published data. <a href="/standards/">Standards and sources</a></p>'
        out.append((f'learn/{desk}.html', doc_page(f'learn/{desk}.html', title, desc, body, ld, desk=desk, crumb=[('Learn', f'{BASE}/learn/')])))
    idx = ('<h1>Learn: the vocabulary of these funds</h1><p class="lede">Three short glossaries, one per desk, in the order the words come up when you read a fund card. No jargon without a gloss.</p>'
           + '<nav class="rel">' + ''.join(f'<a href="/learn/{k}.html">{esc(v[0].split(":")[0])}</a>' for k, v in LEARN.items()) + '</nav>'
           + ''.join(f'<h2><a href="/learn/{k}.html">{esc(v[0])}</a></h2><p>{esc(v[1])}</p>' for k, v in LEARN.items()))
    out.append(('learn/index.html', doc_page('learn/', 'Learn: how to read a buffer, income or thematic ETF', 'Three plain-words glossaries, one per desk, defining every term ETFIQ uses.', idx)))
    return out


def standards_page():
    inner = app_doc('viewStandards')
    inner = re.sub(r'^<div class="doc">|</div>`?$', '', inner.strip())
    inner = inner.replace('<a href="#/standards">Standards</a>', '<a href="/standards/">Standards</a>')
    return doc_page('standards/', 'Standards, ownership and sources',
                    'Who publishes ETFIQ, what it publishes, what it never does, and where every figure on the site comes from.',
                    inner + '<h2>Read more</h2><nav class="rel"><a href="/learn/">Learn the vocabulary</a><a href="/research/">ETFIQ Research</a><a href="/llms.txt">llms.txt</a></nav>')


# ---------------------------------------------------------------- hub pages: issuer, theme, reset month
def hub_page(slug, title, desc, intro, rows, head, as_of, item_names, crumb=None, desk=None, extra=''):
    url = f'{BASE}/{slug}'
    ld = [{'@type': 'ItemList', 'name': title, 'numberOfItems': len(item_names),
           'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': t, 'url': f'{BASE}/funds/{t}.html'} for i, t in enumerate(item_names[:100])]}]
    trs = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    inner = (f'<p class="note">Data as of {fdate(as_of)}.</p><h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>{extra}'
             f'<div style="overflow-x:auto"><table><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead><tbody>{trs}</tbody></table></div>'
             '<p class="note">ETFIQ is an independent publisher and makes no recommendations; every figure is stated arithmetic on published data. <a href="/standards/">Standards and sources</a></p>')
    return doc_page(slug, title, desc, inner, ld, desk=desk, crumb=crumb)


# ---------------------------------------------------------------- head to head pages
# The funds people actually search for, one list per desk: the widely held names on the buffer and income desks,
# and the largest thematic funds by net assets. Every pair of them gets its own page.
BUFFER_TOP = ['PJAN', 'PAPR', 'PJUL', 'POCT', 'BJAN', 'BAPR', 'BJUL', 'BOCT', 'UJAN', 'UAPR', 'UJUL', 'UOCT', 'DJAN', 'DAPR', 'DJUL', 'DOCT', 'FJAN', 'FJUL', 'PSEP', 'PNOV']
INCOME_TOP = ['JEPI', 'JEPQ', 'SPYI', 'QQQI', 'QYLD', 'XYLD', 'RYLD', 'DIVO', 'GPIX', 'GPIQ', 'TSLY', 'NVDY', 'MSTY', 'CONY', 'ULTY', 'YMAX', 'FEPI', 'XDTE', 'QDTE', 'AIPI']
PAIRS_BY_TICKER = {}


def pair_slug(a, b):
    x, y = sorted([a, b])
    return f'{x}-{y}'


def cmp_url(desk, a, b):
    return f'{BASE}/compare/{desk}/{pair_slug(a, b)}.html'


EMBED_LABEL = {'buffer': 'outcome band', 'income': 'payout bar', 'themes': 'difference bar'}


def embed_block(desk, ticker, name):
    """The snippet another site pastes to show this fund's graphic, updated every night, with a credit link."""
    if not (SITE / 'embed' / desk / f'{ticker}.svg').exists():
        return ''
    snippet = (f'<a href="{BASE}/funds/{ticker}.html">'
               f'<img src="{BASE}/embed/{desk}/{ticker}.svg" alt="{ticker} {EMBED_LABEL[desk]}, ETFIQ" width="640"></a>\n'
               f'<p><a href="{BASE}/funds/{ticker}.html">{ticker} {EMBED_LABEL[desk]}, updated daily by ETFIQ</a></p>')
    return (f'<h2>Put this on your own page</h2>'
            f'<p>The {EMBED_LABEL[desk]} for {esc(ticker)} as a picture that redraws itself every trading night, free to use with the credit link. '
            f'Paste these two lines into any page, newsletter or blog post.</p>'
            f'<p><img src="/embed/{desk}/{ticker}.svg" alt="{esc(ticker)} {EMBED_LABEL[desk]}, ETFIQ" width="640" loading="lazy" style="max-width:100%;height:auto;border-radius:10px"></p>'
            f'<pre class="embed"><code>{esc(snippet)}</code></pre>')


def related_links(desk, ticker):
    ps = PAIRS_BY_TICKER.get((desk, ticker)) or []
    if not ps:
        return ''
    links = ''.join(f'<a href="/compare/{desk}/{pair_slug(ticker, o)}.html">{esc(ticker)} vs {esc(o)}</a>' for o in ps[:6])
    return f'<h2>Compare {esc(ticker)}</h2><nav class="rel">{links}</nav>'


def w1(r):
    """The one-year window, or the whole record since launch for a fund younger than that."""
    ws = r.get('windows') or {}
    return ws.get('1Y') or ws.get('ITD'), bool(ws.get('1Y'))


def pair_overlap(a, b, matrix):
    """Weight overlap between two thematic funds, from the packed upper-triangle matrix on the themes desk."""
    tk = (matrix or {}).get('tickers') or []
    if a not in tk or b not in tk:
        return None
    i, j = tk.index(a), tk.index(b)
    if i == j:
        return 100
    x, y = (i, j) if i < j else (j, i)
    try:
        return matrix['rows'][x][y - x - 1]
    except (IndexError, KeyError):
        return None


def cmp_rows(desk, a, b, extra):
    """Field rows for a head to head page: the desk's own fields, the same values its cards carry."""
    if desk == 'buffer':
        def one(f):
            sb = f.get('startBuffer') or (f['bufferStart'] - f['bufferEnd'])
            used = max(0.0, min(sb, f['bufferStart'] - f['refReturn']))
            left = None if f.get('isFloor') else round(sb - used, 2)
            return [f['issuer'], f['refAsset'], f.get('bufferLabel', ''), f"{fdate(f['periodStart'])} to {fdate(f['periodEnd'])}", str(f.get('daysRemaining')),
                    'uncapped' if f.get('isUncapped') else pct(f.get('startCap')),
                    'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False),
                    pct(f.get('downsideBeforeBuffer'), sign=False),
                    'full floor' if left is None else f"{pct(left, sign=False)} of {pct(sb, sign=False)}",
                    pct(f['refReturn']), pct(f.get('fundReturn')), STATE_LABEL[buffer_state(f)], pct(f.get('expenseRatio'), sign=False, d=2)]
        labels = ['Issuer', 'Reference index', 'Buffer', 'Outcome period', 'Days left', 'Starting cap', 'Can still gain', 'Fall before buffer', 'Protection left, index points', 'Index return this period', 'Fund return this period', 'State today', 'Expense ratio']
    elif desk == 'income':
        def one(r):
            w, full = w1(r)
            since = '' if full or not w else f" (since launch on {fdate(w['from'])})"
            return [r['issuer'], r.get('strategy', ''), r.get('benchmarkName') or r['benchmark'], r.get('payoutFrequency') or 'not established',
                    pct(r.get('distributionRate'), sign=False), pct(r.get('expenseRatio'), sign=False, d=2),
                    (pct(w['cash'], sign=False) + since) if w else 'not available', pct(w['price']) if w else 'not available',
                    (pct(w['total']) + since) if w else 'not available', pct(w.get('bench')) if w else 'not available',
                    pts(w.get('gap')) if w else 'not available',
                    pct((extra.get(r['ticker']) or {}).get('roc'), sign=False, d=0) if (extra.get(r['ticker']) or {}).get('roc') is not None else 'not published',
                    f"{r.get('daysSinceInception')} days"]
        labels = ['Issuer', 'Strategy', 'Benchmark', 'Pays', 'Payout rate, annualised', 'Expense ratio', 'Cash paid, 1 year', 'Price change, 1 year', 'Total return, 1 year', 'Benchmark return, 1 year', 'Ahead or behind', 'Return of capital, latest estimate', 'Age']
    else:
        def one(r):
            v, q = r.get('vsSPY') or {}, r.get('vsQQQ') or {}
            w, full = w1(r)
            since = '' if full or not w else f" (since launch on {fdate(w['from'])})"
            return [r['issuer'], r['themeName'], pct(v.get('inIndex'), sign=False), pct(v.get('activeShare'), sign=False), pct(q.get('inIndex'), sign=False),
                    str(r.get('holdingsCount') or 'not filed yet'), pct(r.get('top10Weight'), sign=False),
                    pct(r.get('expenseRatio'), sign=False, d=2), pct(r.get('activeFee'), sign=False, d=2),
                    (pct(w['total']) + since) if w else 'not available', pts(w.get('gap')) if w else 'not available', pts(w.get('gapQ')) if w else 'not available', pct(r.get('drawdown'))]
        labels = ['Issuer', 'Theme', 'In the S&P 500', 'Active share vs the S&P 500', 'In the Nasdaq-100', 'Holdings', 'Top ten, share of the fund', 'Expense ratio', 'Fee for the differing part', 'Total return, 1 year', 'vs the S&P 500', 'vs the Nasdaq-100', 'Below its high']
    return labels, one(a), one(b)


def cmp_faqs(desk, a, b, extra, overlap):
    ta, tb = a['ticker'], b['ticker']
    out = []
    if desk == 'income':
        wa, _ = w1(a)
        wb, _ = w1(b)
        if wa and wb:
            more = ta if wa['cash'] >= wb['cash'] else tb
            out.append((f'Which paid more, {ta} or {tb}?',
                        f'Over the last year {ta} paid {pct(wa["cash"], sign=False)} of its starting price in cash and {tb} paid {pct(wb["cash"], sign=False)}, so {more} paid more. Cash paid is not the same as money made: the price change matters too.'))
            best = ta if (wa.get('total') or -999) >= (wb.get('total') or -999) else tb
            out.append((f'Which returned more once distributions are counted, {ta} or {tb}?',
                        f'With every distribution reinvested, {ta} returned {pct(wa["total"])} and {tb} returned {pct(wb["total"])} over the last year, so {best} returned more.'))
    if desk == 'buffer':
        if a.get('remainingCapFund') is not None and b.get('remainingCapFund') is not None:
            more = ta if a['remainingCapFund'] >= b['remainingCapFund'] else tb
            out.append((f'Which has more room to gain, {ta} or {tb}?',
                        f'From today\'s price {ta} can gain about {pct(a["remainingCapFund"], sign=False)} before its cap and {tb} about {pct(b["remainingCapFund"], sign=False)}, so {more} has more room left this period.'))
        out.append((f'Which resets first, {ta} or {tb}?',
                    f'{ta} ends its outcome period on {fdate(a["periodEnd"])} and {tb} on {fdate(b["periodEnd"])}. A new cap is set the day after each.'))
    if desk == 'themes':
        if overlap is not None:
            word = 'close to holding one of them twice' if overlap >= 50 else 'a meaningful overlap' if overlap >= 20 else 'mostly different names'
            out.append((f'Do {ta} and {tb} hold the same stocks?',
                        f'{overlap}% of their books are the same securities at the same weight, which is {word}. Overlap is the sum of the smaller weight of every security they share.'))
        va, vb = a.get('vsSPY') or {}, b.get('vsSPY') or {}
        if va.get('inIndex') is not None and vb.get('inIndex') is not None:
            diff = ta if va['activeShare'] >= vb['activeShare'] else tb
            out.append((f'Which is more different from the S&P 500, {ta} or {tb}?',
                        f'{ta} has {va["inIndex"]:.0f}% of its weight in S&P 500 names and {tb} has {vb["inIndex"]:.0f}%, so {diff} differs more from the index.'))
    fa, fb = a.get('expenseRatio'), b.get('expenseRatio')
    if fa is not None and fb is not None:
        cheap = ta if fa <= fb else tb
        out.append((f'Which is cheaper, {ta} or {tb}?',
                    f'{ta} charges {pct(fa, sign=False, d=2)} a year and {tb} charges {pct(fb, sign=False, d=2)}, so {cheap} is cheaper. Fees come from each fund\'s prospectus.'))
    return out


CMP_Q = {'buffer': 'which buffer ETF stands where?', 'income': 'which one paid, and which one earned it?', 'themes': 'which one is really different?'}


def cmp_page(desk, a, b, as_of, extra, matrix, words_a, words_b):
    ta, tb = a['ticker'], b['ticker']
    url = cmp_url(desk, ta, tb)
    overlap = pair_overlap(ta, tb, matrix) if desk == 'themes' else None
    title = f'{ta} vs {tb}: {CMP_Q[desk]}'
    labels, ra, rb = cmp_rows(desk, a, b, extra)
    if desk == 'income':
        wa, _ = w1(a)
        wb, _ = w1(b)
        desc = (f'{ta} and {tb} side by side on {fdate(as_of)}: cash paid {pct(wa["cash"], sign=False) if wa else "n/a"} against {pct(wb["cash"], sign=False) if wb else "n/a"}, '
                f'total return {pct(wa["total"]) if wa else "n/a"} against {pct(wb["total"]) if wb else "n/a"} over the last year.')
    elif desk == 'buffer':
        desc = (f'{ta} and {tb} side by side on {fdate(as_of)}: can still gain {pct(a.get("remainingCapFund"), sign=False)} against {pct(b.get("remainingCapFund"), sign=False)}, '
                f'fall before the buffer {pct(a.get("downsideBeforeBuffer"), sign=False)} against {pct(b.get("downsideBeforeBuffer"), sign=False)}.')
    else:
        va, vb = a.get('vsSPY') or {}, b.get('vsSPY') or {}
        desc = (f'{ta} and {tb} side by side on {fdate(as_of)}: {pct(va.get("inIndex"), sign=False)} against {pct(vb.get("inIndex"), sign=False)} already in the S&P 500'
                + (f', {overlap}% of the two books in common.' if overlap is not None else '.'))
    faqs = cmp_faqs(desk, a, b, extra, overlap)
    faq_html, faq_ld = faq_block(faqs)
    ld = {'@context': 'https://schema.org', '@graph': faq_ld + [
        crumbs([('ETFIQ', BASE + '/'), (DESK_NAME[desk], f'{BASE}/{desk}/'), (f'{ta} vs {tb}', url)]),
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': as_of, 'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE}},
        {'@type': 'Dataset', 'name': f'ETFIQ comparison of {ta} and {tb}', 'description': desc, 'dateModified': as_of, 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'isAccessibleForFree': True, 'url': url}]}
    head = f'<tr><th></th><th><a href="/funds/{ta}.html">{esc(ta)}</a><div class="sub">{esc(a["name"])}</div></th><th><a href="/funds/{tb}.html">{esc(tb)}</a><div class="sub">{esc(b["name"])}</div></th></tr>'
    body = ''.join(f'<tr><th>{esc(l)}</th><td>{esc(x)}</td><td>{esc(y)}</td></tr>' for l, x, y in zip(labels, ra, rb))
    ov = f'<p class="lede">{overlap}% of the two portfolios are the same securities at the same weight.</p>' if overlap is not None else ''
    others = sorted(set((PAIRS_BY_TICKER.get((desk, ta)) or []) + (PAIRS_BY_TICKER.get((desk, tb)) or [])) - {ta, tb})[:8]
    rel = ''.join(f'<a href="/compare/{desk}/{pair_slug(ta, o)}.html">{esc(ta)} vs {esc(o)}</a>' for o in others[:4]) + \
          ''.join(f'<a href="/compare/{desk}/{pair_slug(tb, o)}.html">{esc(tb)} vs {esc(o)}</a>' for o in others[4:8])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}</style></head>
<body>{R.rail(desk)}<main>
<p class="note">Data as of {fdate(as_of)}. Every figure is the {DESK_NAME[desk].lower()}'s own, on published data.</p>
<h1>{esc(ta)} vs {esc(tb)}</h1><p class="lede">{esc(a['name'])} and {esc(b['name'])}, side by side on the {DESK_NAME[desk].lower()}.</p>
{ov}
<a class="cta" href="{BASE}/#/{desk}/compare/{ta},{tb}">Open the live comparison on ETFIQ</a>
<table><thead>{head}</thead><tbody>{body}</tbody></table>
<h2>{esc(ta)} in plain words</h2><p>{esc(words_a)}</p>
<h2>{esc(tb)} in plain words</h2><p>{esc(words_b)}</p>
{faq_html}
{'<h2>Other comparisons</h2><nav class="rel">' + rel + '</nav>' if rel else ''}
<p class="note">ETFIQ is an independent publisher of exchange-traded fund data. It is not a fund issuer, broker-dealer or investment adviser, and it makes no recommendations; every figure here is stated arithmetic on published data. <a href="{BASE}/#/standards">Standards and sources</a></p>
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/portfolio/">Portfolio desk</a><a href="/research/">Research</a></nav></footer></body></html>"""


# ---------------------------------------------------------------- page shell
DESK_NAME = {'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk'}
STYLE = R.RAIL_CSS + """pre.embed{background:#0F1419;color:#E6EAF0;padding:14px 16px;border-radius:10px;overflow-x:auto;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-all}dl.faq{margin:0 0 8px}dl.faq dt{font-weight:600;margin:18px 0 6px}dl.faq dd{margin:0;color:#3B434F}nav.rel{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 6px}nav.rel a{border:1px solid #D9DEE6;border-radius:999px;padding:6px 12px;background:#fff;font-size:13.5px;text-decoration:none;color:#0F1419}nav.rel a:hover{border-color:#2457E6}thead th .sub{font-weight:400;font-size:12px;color:#5B6572;margin-top:4px;max-width:220px}body{margin:0;background:#F5F7FA;color:#0F1419;font:15px/1.5 Geist,system-ui,-apple-system,'Segoe UI',sans-serif}main{max-width:820px;margin:0 auto;padding:28px 20px 60px}h1{font-size:28px;letter-spacing:-.02em;margin:18px 0 6px}.lede{color:#3D4756;font-size:16px}.tk{font-family:'Geist Mono',ui-monospace,monospace;font-weight:600}.cta{display:inline-block;margin:14px 0 22px;padding:10px 16px;background:#2457E6;color:#fff;border-radius:6px;text-decoration:none;font-weight:600}table{border-collapse:collapse;width:100%;margin:12px 0 18px;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #DCE1E8;vertical-align:top}th{width:44%;color:#3D4756;font-weight:500}.note{color:#5B6675;font-size:13px}nav.desks a{margin-right:14px}footer{margin-top:40px;color:#5B6675;font-size:13px}"""


def faq_block(faqs):
    """A question and answer list in the words people search, from figures already on the page."""
    if not faqs:
        return '', []
    html_ = '<h2>Questions people ask</h2><dl class="faq">' + ''.join(f'<dt>{esc(q)}</dt><dd>{esc(a)}</dd>' for q, a in faqs) + '</dl>'
    ld = [{'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faqs]}]
    return html_, ld


def crumbs(items):
    return {'@type': 'BreadcrumbList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': nm, 'item': u} for i, (nm, u) in enumerate(items)]}


def page(title, desc, ticker, name, issuer, desk, as_of, words, rows, app_url, method, faqs=None, related=''):
    url = f"{BASE}/funds/{ticker}.html"
    faq_html, faq_ld = faq_block(faqs or [])
    ld = {'@context': 'https://schema.org', '@graph': faq_ld + [crumbs([('ETFIQ', BASE + '/'), (DESK_NAME[desk], f'{BASE}/{desk}/'), (ticker, url)])] + [
        {'@type': 'FinancialProduct', 'name': name, 'alternateName': ticker, 'identifier': ticker, 'provider': {'@type': 'Organization', 'name': issuer}, 'category': f'Exchange-traded fund, {DESK_NAME[desk].lower()}', 'url': url},
        {'@type': 'Dataset', 'name': f'ETFIQ {DESK_NAME[desk].lower()} record for {ticker}', 'description': desc, 'dateModified': as_of, 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'license': 'https://etfiq.com/#/standards', 'isAccessibleForFree': True, 'url': url},
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': as_of, 'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE}}]}
    trs = ''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in rows)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}</style></head>
<body>{R.rail(desk)}<main>
<p class="note">Data as of {fdate(as_of)}. {esc(method)}</p>
<h1><span class="tk">{esc(ticker)}</span> · {esc(name)}</h1><p class="lede">{esc(issuer)} · {DESK_NAME[desk]}</p>
<a class="cta" href="{app_url}">Open the live card on ETFIQ</a>
<p>{esc(words)}</p>
<table><tbody>{trs}</tbody></table>
{faq_html}
{related}
<p class="note">ETFIQ is an independent publisher of exchange-traded fund data. It is not a fund issuer, broker-dealer or investment adviser, and it makes no recommendations; sort orders and figures are stated arithmetic on published data. <a href="{BASE}/#/standards">Standards</a> · <a href="{BASE}/#/{desk}/learn">How to read this desk</a></p>
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/llms.txt">llms.txt</a></nav></footer></body></html>"""


def index_page(desk, rows, as_of, intro):
    url = f"{BASE}/{desk}/"
    title = {'buffer': 'Every buffer ETF on one comparable band', 'income': 'Every option-income ETF against its benchmark', 'themes': 'Every thematic ETF: what you actually bought'}[desk]
    head = {'buffer': ['Ticker', 'Fund', 'Issuer', 'Index', 'Buffer', 'Period ends', 'Can still gain', 'Fall before buffer', 'State'],
            'income': ['Ticker', 'Fund', 'Issuer', 'Benchmark', 'Paid 1Y', 'Total return 1Y', 'Ahead or behind 1Y', 'Return of capital, latest'],
            'themes': ['Ticker', 'Fund', 'Issuer', 'Theme', 'In the S&P 500', 'Active share vs S&P', 'Top ten', 'Total return 1Y', 'vs S&P 500 1Y']}[desk]
    trs = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    tickers = [re.search(r'>([A-Z0-9.]+)</a>', r[0]).group(1) for r in rows if re.search(r'>([A-Z0-9.]+)</a>', r[0])]
    ld = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'Dataset', 'name': f'ETFIQ {DESK_NAME[desk].lower()}', 'description': intro, 'dateModified': as_of, 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'isAccessibleForFree': True, 'url': url},
        {'@type': 'ItemList', 'name': title, 'numberOfItems': len(tickers), 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': t, 'url': f'{BASE}/funds/{t}.html'} for i, t in enumerate(tickers[:100])]},
        crumbs([('ETFIQ', BASE + '/'), (DESK_NAME[desk], url)])]}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(intro)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}main{{max-width:1100px}}th,td{{white-space:nowrap}}th{{width:auto}}</style></head>
<body>{R.rail(desk)}<main>
<p class="note">Data as of {fdate(as_of)}.</p><h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>
<a class="cta" href="{BASE}/#/{desk}/desk">Open the live desk on ETFIQ</a>
<div style="overflow-x:auto"><table><thead><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr></thead><tbody>{trs}</tbody></table></div>
<p class="note">ETFIQ is an independent publisher. It makes no recommendations; every list is stated arithmetic on published data. <a href="{BASE}/#/standards">Standards</a></p>
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/portfolio/">Portfolio desk</a><a href="/research/">Research</a></nav></footer></body></html>"""


def portfolio_page(as_of, books):
    url = f'{BASE}/portfolio/'
    title = 'Portfolio desk: what does my whole portfolio actually own, protect and pay?'
    intro = ('Enter the ETFs you or a client hold, with weights, share counts or dollar amounts. One page answers with the look-through to filed holdings, '
             'the overlap between positions, the weighted fee, the buffer protection blended by weight, the cash by month for twelve months, and the outcome of a chosen market move on every buffer position. '
             'Every number is arithmetic on published data; nothing is suggested.')
    views = [('What you own', "Every fund looked through to its latest SEC filing or the issuer's daily file, weighted by position: the names you are really concentrated in, the share already in the S&P 500, the pairs of funds that overlap, and the weighted expense ratio."),
             ('Protection', "The buffer desk's fields for every buffer ETF you hold, blended by weight: what they can still gain, how far they can fall before the buffer, the protection left in index points, with every band on one scale."),
             ('Cash', "Twelve months of payouts for every income ETF you hold: declared and scheduled from the payout calendar, then carried forward at each fund's cadence and marked projected, with the issuer's latest estimate of return of capital."),
             ('If the market moves', "Pick a move in the S&P 500 from today to each fund's period end and see the outcome of every buffer ETF from its published cap and buffer, beside the same money unbuffered in the index."),
             ('Compare funds', 'Up to four funds from any desk as their desk cards, side by side.')]
    examples = [('VOO:40,JEPI:25,PJAN:20,ARKK:15', 'A retail mix'), ('PJAN:25,PAPR:25,PJUL:25,POCT:25', 'A buffer ladder'), ('JEPI:150S,TSLY:200S,QYLD:300S', 'Three income funds by shares'), ('SPY:30,QQQ:20,SCHD:20,TSLY:10,BOTZ:10,DSEP:10', 'Income and themes on a core')]
    ld = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'WebApplication', 'name': 'ETFIQ Portfolio desk', 'url': f'{BASE}/#/portfolio', 'applicationCategory': 'FinanceApplication', 'operatingSystem': 'Web', 'isAccessibleForFree': True, 'description': intro,
         'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'}, 'provider': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}},
        {'@type': 'WebPage', 'name': title, 'description': intro, 'url': url, 'dateModified': as_of, 'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE}}]}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(intro[:300])}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(intro[:300])}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}main{{max-width:820px}}</style></head>
<body>{R.rail('portfolio')}<main>
<p class="note">Books as of {fdate(as_of)}: {books} funds with filed holdings, from every income and themes desk fund and the core index funds.</p>
<h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>
<a class="cta" href="{BASE}/#/portfolio">Open the Portfolio desk on ETFIQ</a>
<h2>Five views</h2><table><tbody>{''.join(f'<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>' for a, b in views)}</tbody></table>
<h2>Try an example</h2><p>{' · '.join(f'<a href="{BASE}/#/portfolio/own/{sp}">{esc(l)}</a>' for sp, l in examples)}</p>
<h2>How positions are written</h2><p>Tickers with a weight (PJAN:20), a share count (JEPI:150S) or a dollar amount (JEPI:$25000), separated by commas. Any fund on the buffer, income or themes desk, plus the core index funds. The link carries the positions, so a portfolio can be shared or bookmarked; named portfolios can be kept on the device.</p>
<p class="note">Books come from each fund's latest SEC N-PORT filing or the issuer's daily file, dated on the desk. Buffer funds enter the look-through as their reference index; synthetic income funds as the stock or index they write options on; a fund with no filing yet stands in as the stock or index in its name; all labelled. ETFIQ is an independent publisher and makes no recommendations or allocation suggestions. <a href="{BASE}/#/standards">Standards</a></p>
</main><footer><nav class="desks"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/research/">Research</a></nav></footer></body></html>"""


def build():
    funds = load('site/data/funds.json', [])
    income = load('site/data/income.json', [])
    themes = load('site/data/thematic.json', {'funds': []})['funds']
    sources = load('site/data/sources.json', {})
    meta = load('site/data/meta.json', {}); imeta = load('site/data/income_meta.json', {}); tmeta = load('site/data/thematic_meta.json', {})
    as_b, as_i, as_t = meta.get('asOf', TODAY), imeta.get('asOf', TODAY), tmeta.get('asOf', TODAY)
    by = {'buffer': {f['ticker']: f for f in funds}, 'income': {r['ticker']: r for r in income}, 'themes': {r['ticker']: r for r in themes}}
    top = {'buffer': [t for t in BUFFER_TOP if t in by['buffer']],
           'income': [t for t in INCOME_TOP if t in by['income']],
           'themes': [r['ticker'] for r in sorted(themes, key=lambda r: -(r.get('assets') or 0)) if r.get('vsSPY')][:20]}
    PAIRS_BY_TICKER.clear()
    for desk, ts in top.items():
        for t in ts:
            PAIRS_BY_TICKER[(desk, t)] = [o for o in ts if o != t]
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
    w1y = lambda r: (r.get('windows') or {}).get('1Y') or {}
    b_rows = [[link(f['ticker']), esc(f['name']), esc(f['issuer']), f['refAsset'], esc(f.get('bufferLabel', '')), fdate(f['periodEnd']), 'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False), pct(f.get('downsideBeforeBuffer'), sign=False), STATE_LABEL[buffer_state(f)]] for f in funds]
    i_rows = [[link(r['ticker']), esc(r['name']), esc(r['issuer']), r['benchmark'], pct(w1y(r).get('cash'), sign=False), pct(w1y(r).get('total')), pts(w1y(r).get('gap')), pct(((sources.get(r['ticker']) or {}).get('latest') or {}).get('roc'), sign=False)] for r in income]
    t_rows = [[link(r['ticker']), esc(r['name']), esc(r['issuer']), esc(r['themeName']), pct((r.get('vsSPY') or {}).get('inIndex'), sign=False), pct((r.get('vsSPY') or {}).get('activeShare'), sign=False), pct(r.get('top10Weight'), sign=False), pct(w1y(r).get('total')), pts(w1y(r).get('gap'))] for r in themes]
    for desk, rows, as_of, intro in (('buffer', b_rows, as_b, f'{len(funds)} defined outcome (buffer) ETFs from every issuer ETFIQ covers, each placed on one comparable band from buffer to cap, with how much it can still gain, how far it can fall before the buffer, and the protection left, as of {fdate(as_b)}.'),
                                     ('income', i_rows, as_i, f'{len(income)} option-income ETFs measured against the index or stock they write options on: cash paid, price change, total return with distributions reinvested, and whether a holder came out ahead, as of {fdate(as_i)}.'),
                                     ('themes', t_rows, as_t, f'{len(themes)} thematic ETFs in 27 themes: how much of each is already in the S&P 500, active share, concentration, and returns against the plain index, from SEC holdings filings and exchange prices as of {fdate(as_t)}.')):
        d = SITE / desk
        d.mkdir(exist_ok=True)
        (d / 'index.html').write_text(index_page(desk, rows, as_of, intro)); urls.append((f'{BASE}/{desk}/', as_of))
    # explainers, standards and the old site's paths
    for rel, html_ in learn_pages():
        fp = SITE / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(html_)
        urls.append((f'{BASE}/{rel}'.replace('/index.html', '/'), TODAY))
    (SITE / 'standards').mkdir(exist_ok=True)
    (SITE / 'standards' / 'index.html').write_text(standards_page())
    urls.append((f'{BASE}/standards/', TODAY))
    for old_path, target in (('about', '/standards/'), ('contact', '/standards/'), ('blog', '/research/'), ('services', '/'), ('hello-world', '/')):
        d = SITE / old_path
        d.mkdir(exist_ok=True)
        (d / 'index.html').write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>ETFIQ</title>'
                                      f'<link rel="canonical" href="{BASE}{target}"><meta http-equiv="refresh" content="0; url={target}">'
                                      f'<meta name="robots" content="noindex,follow"></head><body><p>This page has moved. <a href="{target}">Continue to ETFIQ</a>.</p></body></html>')
    # hubs: every issuer, every theme, every reset month
    hubs = 0
    by_issuer = {}
    for desk, rs in (('buffer', funds), ('income', income), ('themes', themes)):
        for r in rs:
            by_issuer.setdefault(r['issuer'], {}).setdefault(desk, []).append(r)
    (SITE / 'issuers').mkdir(exist_ok=True)
    for old in (SITE / 'issuers').glob('*.html'):
        old.unlink()
    issuer_rows = []
    for issuer, desks in sorted(by_issuer.items()):
        total = sum(len(v) for v in desks.values())
        if total < 2:
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', issuer.lower()).strip('-')
        rows, names = [], []
        for desk in ('buffer', 'income', 'themes'):
            for r in sorted(desks.get(desk, []), key=lambda r: r['ticker']):
                names.append(r['ticker'])
                if desk == 'buffer':
                    detail = f"{esc(r.get('bufferLabel', ''))} on {esc(r['refAsset'])}, period ends {fdate(r['periodEnd'])}"
                    figure = 'uncapped' if r.get('isUncapped') else pct(r.get('remainingCapFund'), sign=False) + ' left to the cap'
                elif desk == 'income':
                    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
                    detail = f"{esc(r.get('strategy', ''))}, vs {esc(r['benchmark'])}"
                    figure = f"paid {pct(w.get('cash'), sign=False)}, total {pct(w.get('total'))}"
                else:
                    v = r.get('vsSPY') or {}
                    detail = esc(r['themeName'])
                    figure = f"{pct(v.get('inIndex'), sign=False)} already in the S&P 500"
                rows.append([f'<a href="/funds/{r["ticker"]}.html" class="tk">{esc(r["ticker"])}</a>', esc(r['name']), DESK_NAME[desk].split()[0], detail, figure])
        title = f'{issuer} ETFs on ETFIQ: every fund, one page'
        counts = ', '.join(f'{len(v)} {k}' for k, v in desks.items() if v)
        intro = f'Every {issuer} fund ETFIQ covers, with the same fields as its desk: {counts}. Figures as published, ETFIQ calculations marked.'
        desc = f'{issuer}: {total} exchange-traded funds with current figures from ETFIQ ({counts}).'
        (SITE / 'issuers' / f'{slug}.html').write_text(hub_page(f'issuers/{slug}.html', title, desc, intro, rows,
                                                               ['Ticker', 'Fund', 'Desk', 'What it is', 'Where it stands'], max(as_b, as_i, as_t), names,
                                                               crumb=[('Issuers', f'{BASE}/issuers/')]))
        urls.append((f'{BASE}/issuers/{slug}.html', max(as_b, as_i, as_t)))
        issuer_rows.append([f'<a href="/issuers/{slug}.html">{esc(issuer)}</a>', str(total), counts])
        hubs += 1
    (SITE / 'issuers' / 'index.html').write_text(hub_page('issuers/', 'Every ETF issuer ETFIQ covers',
                                                          'Buffer, option-income and thematic ETF issuers covered by ETFIQ, with the number of funds on each desk.',
                                                          f'{len(issuer_rows)} issuers, every fund treated identically on its desk.', sorted(issuer_rows, key=lambda r: -int(r[1])),
                                                          ['Issuer', 'Funds', 'Desks'], max(as_b, as_i, as_t), []))
    urls.append((f'{BASE}/issuers/', max(as_b, as_i, as_t)))
    # theme hubs
    by_theme = {}
    for r in themes:
        by_theme.setdefault((r['theme'], r['themeName']), []).append(r)
    for (key, name), rs in sorted(by_theme.items(), key=lambda kv: kv[0][1]):
        rs = sorted(rs, key=lambda r: -(r.get('assets') or 0))
        names = [r['ticker'] for r in rs]
        ins = [(r.get('vsSPY') or {}).get('inIndex') for r in rs if r.get('vsSPY')]
        med = sorted(ins)[len(ins) // 2] if ins else None
        rows = [[f'<a href="/funds/{r["ticker"]}.html" class="tk">{esc(r["ticker"])}</a>', esc(r['name']), esc(r['issuer']),
                 pct((r.get('vsSPY') or {}).get('inIndex'), sign=False), pct((r.get('vsSPY') or {}).get('activeShare'), sign=False),
                 pct(((r.get('windows') or {}).get('1Y') or {}).get('total')), pts(((r.get('windows') or {}).get('1Y') or {}).get('gap')),
                 pct(r.get('expenseRatio'), sign=False, d=2)] for r in rs]
        title = f'{name} ETFs: what each one actually holds'
        intro = (f'{len(rs)} {name.lower()} ETFs, measured by what they hold rather than what they are called'
                 + (f'. The typical fund in this theme has {med:.0f}% of its weight in stocks the S&P 500 already holds.' if med is not None else '.'))
        desc = f'{len(rs)} {name.lower()} ETFs compared by holdings overlap with the S&P 500, active share, one-year return and fee.'
        (SITE / 'themes' / f'{key}.html').write_text(hub_page(f'themes/{key}.html', title, desc, intro, rows,
                                                              ['Ticker', 'Fund', 'Issuer', 'In the S&P 500', 'Active share', 'Total return 1Y', 'vs S&P 500', 'Fee'], as_t, names,
                                                              crumb=[('Themes desk', f'{BASE}/themes/')], desk='themes'))
        urls.append((f'{BASE}/themes/{key}.html', as_t))
        hubs += 1
    # buffer reset month hubs
    months = {}
    for f in funds:
        months.setdefault(f['periodEnd'][5:7], []).append(f)
    MON = {'01': 'January', '02': 'February', '03': 'March', '04': 'April', '05': 'May', '06': 'June', '07': 'July', '08': 'August', '09': 'September', '10': 'October', '11': 'November', '12': 'December'}
    for mm, fs in sorted(months.items()):
        fs = sorted(fs, key=lambda f: (f['periodEnd'], f['ticker']))
        names = [f['ticker'] for f in fs]
        rows = [[f'<a href="/funds/{f["ticker"]}.html" class="tk">{esc(f["ticker"])}</a>', esc(f['name']), esc(f['issuer']), esc(f['refAsset']), esc(f.get('bufferLabel', '')),
                 fdate(f['periodEnd']), 'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False), pct(f.get('downsideBeforeBuffer'), sign=False),
                 STATE_LABEL[buffer_state(f)]] for f in fs]
        title = f'Buffer ETFs that reset in {MON[mm]}'
        intro = (f'{len(fs)} defined outcome ETFs whose outcome period ends in {MON[mm]}, when the options expire and a new cap is struck. '
                 'A fund is at its freshest cap in the days after it resets, and has the least room left just before.')
        desc = f'{len(fs)} buffer ETFs with a {MON[mm]} reset: current cap room, fall before the buffer and state today, every issuer on one page.'
        (SITE / 'buffer' / f'{MON[mm].lower()}.html').write_text(hub_page(f'buffer/{MON[mm].lower()}.html', title, desc, intro, rows,
                                                                         ['Ticker', 'Fund', 'Issuer', 'Index', 'Buffer', 'Period ends', 'Can still gain', 'Fall before buffer', 'State'], as_b, names,
                                                                         crumb=[('Buffer desk', f'{BASE}/buffer/')], desk='buffer'))
        urls.append((f'{BASE}/buffer/{MON[mm].lower()}.html', as_b))
        hubs += 1
    # what changed today
    ins = load('site/data/insights.json', {'lines': [], 'asOf': max(as_b, as_i, as_t)})
    lines = ins.get('lines') or []
    if lines:
        secs = ''
        for d in ('buffer', 'income', 'themes'):
            ls = [l for l in lines if l.get('desk') == d]
            if ls:
                secs += f'<h2>{DESK_NAME[d]}</h2><ul>' + ''.join(f'<li>{esc(l["text"])}</li>' for l in ls) + '</ul>'
        ld = [{'@type': 'ItemList', 'name': f'What changed on ETFIQ, {ins.get("asOf")}', 'numberOfItems': len(lines),
               'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': l['text']} for i, l in enumerate(lines)]}]
        inner = (f'<p class="note">Computed from the desks\' own files on {fdate(ins.get("asOf"))}. Rebuilt every trading night.</p>'
                 f'<h1>What changed, {fdate(ins.get("asOf"))}</h1>'
                 '<p class="lede">Every line here is counted from the published data that morning, not written by hand. No line is a view on any fund.</p>'
                 + secs + '<h2>Go deeper</h2><nav class="rel"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/research/">ETFIQ Research</a></nav>')
        (SITE / 'changed').mkdir(exist_ok=True)
        (SITE / 'changed' / 'index.html').write_text(doc_page('changed/', f'What changed in buffer, income and thematic ETFs, {fdate(ins.get("asOf"))}',
                                                              f'Counted from the published data on {fdate(ins.get("asOf"))}: caps reached, buffers working, funds ahead of their benchmark, themes against the index.', inner, ld))
        urls.append((f'{BASE}/changed/', ins.get('asOf') or TODAY))
    words = {'buffer': lambda f: buffer_words(f)[0], 'income': lambda r: income_words(r, sources.get(r['ticker']))[0], 'themes': lambda r: theme_words(r)[0]}
    matrix = load('site/data/thematic.json', {}).get('matrix')
    roc = {t: {'roc': (v.get('latest') or {}).get('roc')} for t, v in sources.items()}
    cmpdir = SITE / 'compare'
    if cmpdir.exists():
        for old in cmpdir.rglob('*.html'):
            old.unlink()
    npairs = 0
    for desk, ts in top.items():
        d = cmpdir / desk
        d.mkdir(parents=True, exist_ok=True)
        as_of = {'buffer': as_b, 'income': as_i, 'themes': as_t}[desk]
        for i, ta in enumerate(ts):
            for tb in ts[i + 1:]:
                a, b = by[desk][ta], by[desk][tb]
                x, y = (a, b) if ta < tb else (b, a)
                html_ = cmp_page(desk, x, y, as_of, roc, matrix, words[desk](x), words[desk](y))
                (d / f'{pair_slug(ta, tb)}.html').write_text(html_)
                urls.append((cmp_url(desk, ta, tb), as_of))
                npairs += 1
    bidx = load('site/data/books/index.json', {'asOf': max(as_b, as_i, as_t), 'books': {}})
    (SITE / 'portfolio').mkdir(exist_ok=True)
    (SITE / 'portfolio' / 'index.html').write_text(portfolio_page(bidx.get('asOf') or max(as_b, as_i, as_t), sum(1 for v in bidx.get('books', {}).values() if v.get('n'))))
    urls.append((f'{BASE}/portfolio/', bidx.get('asOf') or max(as_b, as_i, as_t)))
    for r in sorted((SITE / 'research').glob('*.html')) if (SITE / 'research').exists() else []:
        urls.append((f'{BASE}/research/' + ('' if r.name == 'index.html' else r.name), max(as_b, as_i, as_t)))
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + f'<url><loc>{BASE}/</loc><lastmod>{max(as_b, as_i, as_t)}</lastmod></url>\n' + ''.join(f'<url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n' for u, d in urls) + '</urlset>\n'
    (SITE / 'sitemap.xml').write_text(sm)
    (SITE / 'robots.txt').write_text("User-agent: *\nAllow: /\n\n" + ''.join(f'User-agent: {b}\nAllow: /\n\n' for b in ('GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-User', 'Claude-SearchBot', 'anthropic-ai', 'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Googlebot', 'Bingbot', 'Applebot', 'Applebot-Extended', 'CCBot', 'Amazonbot', 'meta-externalagent', 'DuckAssistBot', 'YouBot', 'cohere-ai')) + f'Sitemap: {BASE}/sitemap.xml\n')
    (SITE / 'llms.txt').write_text(f"""# ETFIQ

> Independent data on exchange-traded funds, in plain words, for retail investors and advisers. Four desks: buffer (defined outcome) ETFs on one comparable band; option-income ETFs against the index or stock they write options on; thematic ETFs measured by how much of them is already in the S&P 500; and a Portfolio desk that looks through a whole portfolio of ETFs to what it really holds, protects and pays. ETFIQ is not an issuer, broker or adviser and makes no recommendations. Sort orders are stated arithmetic on published data.

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
- [Head to head comparisons]({BASE}/compare/): every pair of the most widely held funds on each desk, in one table with the desk's own fields
- [Portfolio desk]({BASE}/portfolio/): enter ETF positions with weights, shares or dollars; the look-through to filed holdings, overlap between positions, weighted fee, blended buffer protection, cash by month, and the outcome of a market move on buffer positions from published terms. Positions travel in the link; nothing to sign up for.
- [Standards and ownership]({BASE}/#/standards)
- [Live application]({BASE}/)

## Data files

- {BASE}/data/funds.json (buffer desk records), {BASE}/data/income.json (income desk records), {BASE}/data/thematic.json (themes desk records and the fund-to-fund overlap matrix), {BASE}/data/payouts.json (payout calendar), {BASE}/data/sources.json (19a-1 estimates). Free to read; cite ETFIQ and the as-of date.
""")
    print(f'prerendered {len(urls)} pages: {len(funds)} buffer, {len(income)} income, {len(themes)} themes, {npairs} comparisons, {hubs} hubs')


if __name__ == '__main__':
    build()
