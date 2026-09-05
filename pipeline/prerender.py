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
FEES = {}
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


def tdate(d):
    """A date a reader and a machine both get right: the printed form wrapped in its ISO value."""
    return f'<time datetime="{esc(d)}">{fdate(d)}</time>' if d else 'n/a'


def cite_line(what, as_of, url):
    """The sentence to copy when quoting this page, so citing costs nobody any effort."""
    return (f'<p class="cite"><b>Cite this page.</b> ETFIQ, {esc(what)}, data as of {fdate(as_of)}. '
            f'<span class="mono">{esc(url)}</span> Free to use with attribution; the underlying files are at <a href="/data/">Open data</a>.</p>')


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


def buffer_words(f, as_of=None):
    ref = f['refAsset']
    state = buffer_state(f)
    on = f' on {fdate(as_of)}' if as_of else ''
    s = []
    if state == 'capped':
        s.append(f"{ref} had already risen past this fund's cap of {pct(f['startCap'])} for the period{on}, so in index terms there is no more upside to collect. The fund's own price can still drift up to about {pct(f.get('remainingCapFund'), sign=False)} as the period runs out.")
    elif f.get('isUncapped'):
        s.append(f"This fund has no cap. It takes a share of any further rise in {ref}.")
    elif f.get('remainingCapFund') is not None:
        s.append(f"From its price{on}, the fund can gain about {pct(f['remainingCapFund'], sign=False)} more before it reaches its cap.")
    dbb = f.get('downsideBeforeBuffer') or 0
    fall_ref = max(0.0, (1 - (1 + f['bufferStart'] / 100) / (1 + f['refReturn'] / 100)) * 100)
    if dbb > 0:
        s.append(f"The fund's price can fall {pct(dbb, sign=False)} from here before the buffer starts absorbing losses, by the issuer's figure. In index terms, {ref} can fall {pct(fall_ref, sign=False)} from today's level to the point where the buffer begins.")
    sb = f.get('startBuffer') or (f['bufferStart'] - f['bufferEnd'])
    used = max(0.0, min(sb, f['bufferStart'] - f['refReturn']))
    left = None if f.get('isFloor') else round(sb - used, 2)
    if left is not None:
        s.append(f"Protection left, in index points: {pct(left, sign=False)} of the {pct(sb, sign=False)} buffer still sits below today's {ref} level.")
    s.append(f"{f['daysRemaining']} days remained{on}. On {fdate(f['periodEnd'])} the period ends and a new cap is set.")
    return ' '.join(s), state, left, fall_ref


def buffer_page(f, as_of):
    words, state, left, fall_ref = buffer_words(f, as_of)
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
                faqs=buffer_faqs(f, state, left, fall_ref, as_of), related=related_links('buffer', f['ticker']) + neighbour_links('buffer', f['ticker']) + embed_block('buffer', f['ticker'], f['name']),
                cik=None, filings=[u for u in [(f.get('source') or {}).get('fundPage')] if u],
                sources=sources_block([(f"{f['issuer']} page for {f['ticker']}", (f.get('source') or {}).get('fundPage')),
                                       (f"{f['issuer']} product table", (f.get('source') or {}).get('issuerPage')),
                                       ('Prospectus filings on SEC EDGAR', f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={f['issuer'].split()[0]}&type=485BPOS&dateb=&owner=include&count=40")]))


def ref_line(f):
    return f"{f['refAsset']} {pct(f['refReturn'])} since the period began"


# ---------------------------------------------------------------- income desk
def income_words(r, src, as_of=None):
    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD')
    on = fdate(as_of) if as_of else None
    s = []
    if w:
        label = (f'the year to {on}' if on else 'the last 1 year') if w is (r.get('windows') or {}).get('1Y') else f"the period since launch on {fdate(r.get('inception'))}" + (f' to {on}' if on else '')
        s.append(f"Over {label}, {r['ticker']} paid {pct(w['cash'], sign=False)} of its starting value in cash distributions while its price {'fell ' + pct(-w['price'], sign=False) if w['price'] < 0 else 'rose ' + pct(w['price'], sign=False)}. With every distribution reinvested, the fund returned {pct(w['total'])}.")
        if w.get('bench') is not None:
            s.append(f"{r.get('benchmarkName') or r['benchmark']} returned {pct(w['bench'])} over the same days, so a holder was {'ahead' if w['gap'] > 0.5 else 'behind' if w['gap'] < -0.5 else 'about even'}{(' by ' + f"{abs(w['gap']):.1f} pts") if abs(w['gap']) > 0.5 else ''}.")
    if r.get('distributionRate') is not None:
        s.append(f"At its price{' on ' + on if on else ''} the latest distribution annualises to {pct(r['distributionRate'], sign=False)}, paid {r.get('payoutFrequency') or 'periodically'}.")
    if src and src.get('latest') and src['latest'].get('roc') is not None:
        s.append(f"{src['issuer']} estimates that {src['latest']['roc']:.0f}% of the distribution paid {fdate(src['latest'].get('date') or src.get('asOf'))} was a return of capital (19a-1 notice, estimated, a tax characterisation rather than a measure of erosion).")
    return ' '.join(s), w


def income_page(r, as_of, src):
    words, w = income_words(r, src, as_of)
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
                faqs=income_faqs(r, w, src, as_of), related=related_links('income', r['ticker']) + neighbour_links('income', r['ticker']) + embed_block('income', r['ticker'], r['name']),
                cik=r.get('cik'), filings=[u for u in [(src or {}).get('url'), (FEES.get(r['ticker']) or {}).get('source')] if u],
                sources=sources_block([(f"{(src or {}).get('issuer', r['issuer'])} 19a-1 distribution notice", (src or {}).get('url')),
                                       ('Prospectus filing with the expense ratio (SEC)', (FEES.get(r['ticker']) or {}).get('source')),
                                       ('Fund filings on SEC EDGAR', f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r.get('cik')}&type=485&dateb=&owner=include&count=40" if r.get('cik') else None),
                                       (f"{r['issuer']} website", ISSUER_SITE.get(r['issuer']))]))


# ---------------------------------------------------------------- themes desk
def theme_words(r, as_of=None):
    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD')
    on = fdate(as_of) if as_of else None
    s = []
    v = r.get('vsSPY')
    if v:
        s.append(f"By weight, {v['inIndex']:.0f}% of {r['ticker']}'s portfolio is stocks that are also in the S&P 500; its active share against the S&P 500 is {v['activeShare']:.0f}%.")
        s.append(f"The top ten holdings are {r['top10Weight']:.0f}% of the fund across {r['holdingsCount']} positions, as filed for {fdate(r.get('holdingsAsOf'))}.")
    else:
        s.append(f"{r['ticker']} has no public holdings filing captured yet.")
    if w:
        s.append((f"Over the year to {on}" if on else "Over the last year") + f" the fund returned {pct(w['total'])} with distributions reinvested against {pct(w.get('bench'))} for the S&P 500, so a holder was {'ahead' if (w.get('gap') or 0) > 0.5 else 'behind' if (w.get('gap') or 0) < -0.5 else 'about even'}{(' by ' + f"{abs(w['gap']):.1f} pts") if w.get('gap') is not None and abs(w['gap']) > 0.5 else ''}.")
    if r.get('drawdown') is not None and r['drawdown'] < -5:
        s.append(f"It sits {pct(-r['drawdown'], sign=False)} below its all-time high of {fdate(r.get('highDate'))}.")
    return ' '.join(s), w


def theme_page(r, as_of):
    words, w = theme_words(r, as_of)
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
                faqs=theme_faqs(r, w, as_of), related=related_links('themes', r['ticker']) + neighbour_links('themes', r['ticker']) + embed_block('themes', r['ticker'], r['name']),
                cik=r.get('cik'), filings=[u for u in [r.get('holdingsSource'), r.get('feeSource')] if u],
                sources=sources_block([('Holdings filing (SEC Form N-PORT)', r.get('holdingsSource')),
                                       ('Prospectus filing with the expense ratio (SEC)', r.get('feeSource')),
                                       (f"{r['issuer']} website", ISSUER_SITE.get(r['issuer']))]))


def buffer_faqs(f, state, left, fall_ref, as_of=None):
    t, ref = f['ticker'], f['refAsset']
    on = fdate(as_of) if as_of else None
    dt = f' on {on}' if on else ''
    out = []
    if f.get('isUncapped'):
        out.append((f'Does {t} have a cap?', f'No. {t} takes a share of any further rise in {ref}, so there is no ceiling on the upside this period.'))
    elif state == 'capped':
        out.append((f'How much can {t} still gain?', f'Nothing more in index terms{dt}. {ref} has already passed the cap of {pct(f["startCap"])} for this period, which runs from {fdate(f["periodStart"])} to {fdate(f["periodEnd"])}.'))
    elif f.get('remainingCapFund') is not None:
        out.append((f'How much can {t} still gain?', f'About {pct(f["remainingCapFund"], sign=False)} from its price{dt}, before it reaches its cap, by the issuer\'s published figure. The cap for the period was set at {pct(f.get("startCap"))}.'))
    dbb = f.get('downsideBeforeBuffer') or 0
    out.append((f'How far can {t} fall before the buffer helps?',
                f'{pct(dbb, sign=False)} in fund-price terms{dt}, by the issuer\'s figure. In index terms {ref} can fall {pct(fall_ref, sign=False)} from that level before the buffer begins. Losses until that point are the holder\'s.'))
    sb = f.get('startBuffer') or (f['bufferStart'] - f['bufferEnd'])
    if left is not None:
        out.append((f'How much of the {t} buffer is left?', f'{pct(left, sign=False)} of the {pct(sb, sign=False)} buffer sat below the {ref} level{dt}. That is an ETFIQ calculation in index points, on one definition for every issuer.'))
    out.append((f'When does {t} reset?', f'The outcome period ends on {fdate(f["periodEnd"])}, {f.get("daysRemaining")} days from the data{dt}. A new cap is set the next day and the buffer starts again.'))
    if f.get('expenseRatio') is not None:
        out.append((f'What does {t} cost?', f'The prospectus expense ratio is {pct(f["expenseRatio"], sign=False, d=2)} a year.'))
    return out


def income_faqs(r, w, src, as_of=None):
    t = r['ticker']
    on = fdate(as_of) if as_of else None
    out = []
    if w:
        label = (f'the year to {on}' if on else 'the last year') if w is (r.get('windows') or {}).get('1Y') else (f'the period from its launch on {fdate(r.get("inception"))}' + (f' to {on}' if on else ''))
        out.append((f'How much has {t} paid over the last year?',
                    f'Over {label}, {t} paid {pct(w["cash"], sign=False)} of its starting price in cash distributions, while the price {"fell " + pct(-w["price"], sign=False) if w["price"] < 0 else "rose " + pct(w["price"], sign=False)}.'))
        if w.get('gap') is not None:
            side = 'ahead of' if w['gap'] > 0.5 else 'behind' if w['gap'] < -0.5 else 'about even with'
            out.append((f'Is {t} ahead of {r["benchmark"]}?',
                        f'Over {label}, with every distribution reinvested, {t} returned {pct(w["total"])} against {pct(w["bench"])} for {r.get("benchmarkName") or r["benchmark"]}, so a holder was {side} it by {abs(w["gap"]):.1f} points.'))
    if r.get('distributionRate') is not None:
        out.append((f'How often does {t} pay, and how much?',
                    f'{t} pays {r.get("payoutFrequency") or "on no established schedule"}. The latest distribution annualises to {pct(r["distributionRate"], sign=False)} at its price{" on " + on if on else ""}, which is not a promise; the next one can differ.'))
    if src and src.get('latest') and src['latest'].get('roc') is not None:
        out.append((f'Is the {t} distribution return of capital?',
                    f'{src["issuer"]} estimates {src["latest"]["roc"]:.0f}% of the distribution paid {fdate(src["latest"].get("date") or src.get("asOf"))} was return of capital. That is a tax characterisation from the fund\'s own 19a-1 notice, not a measure of erosion.'))
    if r.get('expenseRatio') is not None:
        out.append((f'What does {t} cost?', f'The prospectus expense ratio is {pct(r["expenseRatio"], sign=False, d=2)} a year.'))
    return out


def theme_faqs(r, w, as_of=None):
    t, v = r['ticker'], r.get('vsSPY')
    on = fdate(as_of) if as_of else None
    out = []
    if v:
        out.append((f'How much of {t} is already in the S&P 500?',
                    f'By its holdings filed for {fdate(r.get("holdingsAsOf"))}, {v["inIndex"]:.0f}% of {t} by weight is stocks the S&P 500 already holds. Its active share against the index is {v["activeShare"]:.0f}%, so that share is the part doing something different.'))
        out.append((f'What does {t} hold?',
                    f'{r["holdingsCount"]} positions as filed for {fdate(r.get("holdingsAsOf"))}, with the top ten at {r["top10Weight"]:.0f}% of the fund. The largest are ' + ', '.join(f'{h["n"]} at {h["w"]:.1f}%' for h in (r.get('top') or [])[:3]) + '.'))
    if w and w.get('gap') is not None:
        side = 'ahead of' if w['gap'] > 0.5 else 'behind' if w['gap'] < -0.5 else 'about even with'
        out.append((f'Has {t} beaten the S&P 500?',
                    f'Over the year to {on} {t} returned {pct(w["total"])} with distributions reinvested, against {pct(w["bench"])} for the S&P 500, so it finished {side} the index by {abs(w["gap"]):.1f} points.'))
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


def doc_page(slug, title, desc, inner, ld_extra=None, desk=None, crumb=None, wide=False, short=None):
    url = f'{BASE}/{slug}'
    ld = {'@context': 'https://schema.org', '@graph': (ld_extra or []) + [
        crumbs([('ETFIQ', BASE + '/')] + (crumb or []) + [(title, url)]),
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': TODAY,
         'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE},
         'publisher': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}}]}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg"><link rel="alternate" type="application/rss+xml" title="ETFIQ" href="/feed.xml">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}p.cite{{margin:22px 0 0;padding:12px 14px;background:#F0F3F7;border-left:3px solid #2457E6;border-radius:0 8px 8px 0;font-size:13px;line-height:1.55;color:#3D4756}}p.cite .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}}table caption{{caption-side:top;text-align:left;font-size:12.5px;color:#5A6472;padding:0 0 8px}}.doc dl dt{{font-weight:600;margin:18px 0 6px}}.doc dl dd{{margin:0;color:#3B434F}}.doc h2{{margin-top:28px}}.doc .lede{{font-size:17px;color:#3B434F}}</style></head>
<body>{R.rail(desk or '')}<main class="doc{' wide' if wide else ''}">
{crumb_html([('ETFIQ', BASE + '/')] + (crumb or []) + [(short or (title if len(title) < 40 else title[:38] + '...'), url)])}
{inner}
</main>{R.footer()}</body></html>"""


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
        nav = '<h2>Where to next</h2><nav class="rel">' + ''.join(
            f'<a href="/learn/{k}.html">{LEARN[k][0].split(":")[0]}</a>' for k in LEARN if k != desk) + f'<a href="/{desk}/">All {DESK_NAME[desk].split()[0].lower()} ETFs</a></nav>'
        body = inner + nav + f'<p class="note">Definitions as ETFIQ uses them on the {DESK_NAME[desk].lower()}. Every figure on the site is stated arithmetic on published data. <a href="/standards/">Standards and sources</a></p>'
        out.append((f'learn/{desk}.html', doc_page(f'learn/{desk}.html', title, desc, body, ld, desk=desk, crumb=[('Learn', f'{BASE}/learn/')])))
    idx = ('<h1>Vocabulary</h1><p class="lede">Three glossaries, one per desk, in the order the words appear on a fund card.</p>'
           + '<nav class="rel">' + ''.join(f'<a href="/learn/{k}.html">{esc(v[0].split(":")[0])}</a>' for k, v in LEARN.items()) + '</nav>'
           + ''.join(f'<h2><a href="/learn/{k}.html">{esc(v[0])}</a></h2><p>{esc(v[1])}</p>' for k, v in LEARN.items())
           + '<h2>Where to next</h2><nav class="rel"><a href="/questions/">Questions</a><a href="/rankings/">Rankings</a><a href="/research/">ETFIQ Research</a><a href="/standards/">Standards and sources</a></nav>')
    out.append(('learn/index.html', doc_page('learn/', 'Learn: how to read a buffer, income or thematic ETF', 'Three plain-words glossaries, one per desk, defining every term ETFIQ uses.', idx)))
    return out


def standards_page():
    inner = app_doc('viewStandards')
    inner = re.sub(r'^<div class="doc">|</div>`?$', '', inner.strip())
    inner = inner.replace('<a href="#/standards">Standards</a>', '<a href="/standards/">Standards</a>')
    return doc_page('standards/', 'Standards, ownership and sources',
                    'Who publishes ETFIQ, what it publishes, what it never does, and where every figure on the site comes from.',
                    inner + '<h2>Where to next</h2><nav class="rel"><a href="/learn/">Learn the vocabulary</a><a href="/research/">ETFIQ Research</a><a href="/llms.txt">llms.txt</a></nav>')


def feed_xml(items, as_of):
    """An RSS feed of what changed and what ETFIQ published, so the nightly work can be followed."""
    def rfc(d):
        try:
            return datetime.datetime.fromisoformat(d).strftime('%a, %d %b %Y 12:00:00 +0000')
        except Exception:
            return datetime.datetime.utcnow().strftime('%a, %d %b %Y 12:00:00 +0000')
    entries = ''.join(
        f'<item><title>{esc(t)}</title><link>{u}</link><guid isPermaLink="true">{u}</guid>'
        f'<pubDate>{rfc(d)}</pubDate><description>{esc(desc)}</description></item>'
        for t, u, d, desc in items)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f'<title>ETFIQ</title><link>{BASE}/</link>'
            '<description>Independent data on buffer, option-income and thematic ETFs. What changed, and what the desks show, every trading night.</description>'
            f'<language>en</language><lastBuildDate>{rfc(as_of)}</lastBuildDate>'
            f'<atom:link href="{BASE}/feed.xml" rel="self" type="application/rss+xml"/>'
            f'{entries}</channel></rss>\n')


# ---------------------------------------------------------------- ranked lists
# A list ranked by a published field is arithmetic. A list called "best" is an opinion, so the field goes in the
# title, no adjective does, and every page states the measure, the window, the date and the method.
def rank_page(slug, title, measure, window, method, desk, columns, rows, as_of, note='', related=''):
    url = f'{BASE}/rankings/{slug}.html'
    if not rows:
        return None
    desc = f'{title}. Ranked by {measure} as of {fdate(as_of)}, from ETFIQ data. Not a recommendation.'
    trs = ''.join('<tr><td class="num">' + str(i + 1) + '</td>' + ''.join(f'<td>{c}</td>' for c in r[1:]) + '</tr>' for i, r in enumerate(rows))
    ld = [{'@type': 'ItemList', 'name': title, 'numberOfItems': len(rows), 'itemListOrder': 'https://schema.org/ItemListOrderDescending',
           'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': r[0], 'url': f'{BASE}/funds/{r[0]}.html'} for i, r in enumerate(rows)]},
          {'@type': 'Dataset', 'name': title, 'description': desc, 'url': url, 'dateModified': as_of,
           'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'license': f'{BASE}/data/', 'isAccessibleForFree': True, 'creditText': 'ETFIQ (etfiq.com)'}]
    inner = (f'<p class="note">Ranked by {esc(measure)}{", " + esc(window) if window else ""}, as of {tdate(as_of)}. Rebuilt every trading night.</p>'
             f'<h1>{esc(title)}</h1>'
             f'<p class="lede">{esc(note)}</p>' if note else
             f'<p class="note">Ranked by {esc(measure)}{", " + esc(window) if window else ""}, as of {tdate(as_of)}. Rebuilt every trading night.</p><h1>{esc(title)}</h1>')
    inner += (f'<div style="overflow-x:auto"><table class="hub rank"><caption>{esc(title)}, ranked by {esc(measure)}, as of {fdate(as_of)}. Source: ETFIQ.</caption>'
              f'<thead><tr><th>#</th>{"".join(f"<th>{h}</th>" for h in columns)}</tr></thead><tbody>{trs}</tbody></table></div>'
              f'<h2>Method</h2><p>{esc(method)} The ranking is the published field sorted, nothing else: no scoring, no weighting and no view on any fund. '
              f'Every fund ETFIQ covers in this category is eligible, including funds that have closed, because leaving them out would flatter the category.</p>'
              f'<h2>Where to next</h2><nav class="rel">{related}</nav>'
              '<p class="note">A ranking is not a recommendation and no order on this site is an opinion. ETFIQ is an independent publisher, not an adviser. '
              '<a href="/standards/">Standards and sources</a></p>'
              + cite_line(f'{title}, ranked by {measure}', as_of, url))
    RANK_MEASURE[slug] = measure + (', ' + window if window else '')
    return slug, title, doc_page(f'rankings/{slug}.html', title, desc, inner, ld, desk=desk,
                                 crumb=[('Rankings', f'{BASE}/rankings/')], wide=True, short=title if len(title) < 44 else title[:42] + '...')


def rankings(funds, income, themes, core, as_b, as_i, as_t, matrix, sources):
    out = []
    tk = lambda t: f'<a href="/funds/{t}.html" class="tk">{t}</a>'
    N = 15
    w1y = lambda r: (r.get('windows') or {}).get('1Y') or {}
    add = lambda *a, **k: out.append(rank_page(*a, **k))

    # ---- buffer
    live = [f for f in funds if f.get('refReturn') is not None]
    rows = sorted((f for f in live if not f.get('isUncapped') and f.get('remainingCapFund') is not None), key=lambda f: -f['remainingCapFund'])[:N]
    add('buffer-most-room-to-cap', 'Buffer ETFs with the most room left to their cap', 'remaining cap from today\'s price, as the issuer publishes it', 'current outcome period',
        'Remaining cap is the issuer\'s own figure, net of fees, measured from the fund\'s current price.', 'buffer',
        ['Ticker', 'Fund', 'Can still gain', 'Fall before buffer', 'Buffer', 'Period ends'],
        [[f['ticker'], tk(f['ticker']), esc(f['name']), pct(f['remainingCapFund'], sign=False), pct(f.get('downsideBeforeBuffer'), sign=False), esc(f.get('bufferLabel', '')), fdate(f['periodEnd'])] for f in rows],
        as_b, 'A fund with room left has not yet used the upside its cap allows. It says nothing about what the index will do.',
        '<a href="/buffer/">Every buffer ETF</a><a href="/rankings/buffer-at-their-cap.html">Already at their cap</a><a href="/learn/buffer.html">The vocabulary</a>')
    rows = sorted((f for f in live if not f.get('isFloor') and f.get('protectionLeft') is not None), key=lambda f: -(f.get('protectionLeft') or 0))[:N] if any('protectionLeft' in f for f in live) else []
    if not rows:
        rows = sorted(live, key=lambda f: -((f['bufferStart'] - f['bufferEnd']) - max(0.0, min(f['bufferStart'] - f['bufferEnd'], f['bufferStart'] - f['refReturn']))))[:N]
    add('buffer-most-protection-left', 'Buffer ETFs with the most protection left', 'buffer still below the index level, in index points', 'current outcome period',
        'ETFIQ calculation on one definition for every issuer: the part of the buffer that still sits below today\'s index level.', 'buffer',
        ['Ticker', 'Fund', 'Protection left', 'Buffer', 'Index return', 'Period ends'],
        [[f['ticker'], tk(f['ticker']), esc(f['name']),
          pct(round((f['bufferStart'] - f['bufferEnd']) - max(0.0, min(f['bufferStart'] - f['bufferEnd'], f['bufferStart'] - f['refReturn'])), 2), sign=False),
          esc(f.get('bufferLabel', '')), pct(f['refReturn']), fdate(f['periodEnd'])] for f in rows],
        as_b, 'Protection left is not the same as safety. It is how much of the stated buffer has not yet been used.',
        '<a href="/buffer/">Every buffer ETF</a><a href="/rankings/buffer-most-room-to-cap.html">Most room to the cap</a>')
    rows = sorted((f for f in live if f.get('startCap') is not None and f['refReturn'] >= f['startCap']), key=lambda f: -(f['refReturn'] - f['startCap']))[:N]
    add('buffer-at-their-cap', 'Buffer ETFs already at their cap', 'how far the index has run past the cap', 'current outcome period',
        'A fund is at its cap when the reference index return for the period is at or above the cap struck on the first day.', 'buffer',
        ['Ticker', 'Fund', 'Cap', 'Index return', 'Past the cap by', 'Period ends'],
        [[f['ticker'], tk(f['ticker']), esc(f['name']), pct(f['startCap']), pct(f['refReturn']), pts(f['refReturn'] - f['startCap']), fdate(f['periodEnd'])] for f in rows],
        as_b, 'In index terms these funds have no further upside this period. They still hold their buffer, and they reset on the date shown.',
        '<a href="/buffer/">Every buffer ETF</a><a href="/rankings/buffer-resetting-soonest.html">Resetting soonest</a>')
    rows = sorted((f for f in live if (f.get('daysRemaining') or 0) > 0), key=lambda f: f.get('daysRemaining') or 999)[:N]
    add('buffer-resetting-soonest', 'Buffer ETFs resetting soonest', 'days until the outcome period ends', None,
        'The period end is the issuer\'s published date. A new cap is struck from the option prices of the following day.', 'buffer',
        ['Ticker', 'Fund', 'Days left', 'Period ends', 'Buffer', 'Can still gain'],
        [[f['ticker'], tk(f['ticker']), esc(f['name']), str(f['daysRemaining']), fdate(f['periodEnd']), esc(f.get('bufferLabel', '')),
          'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False)] for f in rows],
        as_b, 'A fund carries its freshest cap in the days after it resets.',
        '<a href="/buffer/">Every buffer ETF</a><a href="/browse/">Browse by reset month</a>')

    # ---- income
    have = [r for r in income if w1y(r).get('cash') is not None]
    rows = sorted(have, key=lambda r: -w1y(r)['cash'])[:N]
    add('income-highest-cash-paid', 'The income ETFs that paid the most cash', 'cash distributions as a percent of the starting price', 'one year',
        'Cash paid is every distribution over the window, as a percent of the price at the start of it. It is not a return: the price change sits beside it.', 'income',
        ['Ticker', 'Fund', 'Cash paid', 'Price change', 'Total return', 'vs benchmark'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pct(w1y(r)['cash'], sign=False), pct(w1y(r)['price']), pct(w1y(r)['total']), pts(w1y(r).get('gap'))] for r in rows],
        as_i, 'Paying the most cash and making the most money are different things. The price change and the benchmark gap are on the same row.',
        '<a href="/income/">Every income ETF</a><a href="/rankings/income-paid-most-price-fell-most.html">Paid most while the price fell</a><a href="/questions/do-covered-call-etfs-lose-value.html">Do these funds lose value?</a>')
    fell = [r for r in have if w1y(r)['price'] < 0]
    rows = sorted(fell, key=lambda r: (w1y(r)['price'] - w1y(r)['cash']))[:N]
    add('income-paid-most-price-fell-most', 'The income ETFs that paid the most while their price fell furthest', 'cash paid minus price change', 'one year',
        'Both figures come from exchange prices and the fund\'s own distributions over the same days.', 'income',
        ['Ticker', 'Fund', 'Cash paid', 'Price change', 'Total return', 'vs benchmark', 'Return of capital, latest'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pct(w1y(r)['cash'], sign=False), pct(w1y(r)['price']), pct(w1y(r)['total']), pts(w1y(r).get('gap')),
          pct(((sources.get(r['ticker']) or {}).get('latest') or {}).get('roc'), sign=False, d=0)] for r in rows],
        as_i, 'A falling price is not automatically a loss: the total return column counts the cash. This list shows where the two diverge most.',
        '<a href="/income/">Every income ETF</a><a href="/questions/what-is-return-of-capital.html">What return of capital means</a>')
    idx = [r for r in have if (r.get('benchmarkKind') or '') != 'stock' and w1y(r).get('gap') is not None]
    rows = sorted(idx, key=lambda r: -w1y(r)['gap'])[:N]
    add('income-furthest-ahead', 'The income ETFs furthest ahead of their benchmark', 'total return minus the benchmark return, in points', 'one year',
        'Total return reinvests every distribution on its ex-date and is measured against the index or stock the fund writes options on.', 'income',
        ['Ticker', 'Fund', 'Ahead by', 'Total return', 'Benchmark', 'Cash paid'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pts(w1y(r)['gap']), pct(w1y(r)['total']), f"{esc(r['benchmark'])} {pct(w1y(r).get('bench'))}", pct(w1y(r)['cash'], sign=False)] for r in rows],
        as_i, 'Ahead means a holder ended with more than the thing the fund writes options on would have given them, cash included.',
        '<a href="/income/">Every income ETF</a><a href="/rankings/income-furthest-behind.html">Furthest behind</a>')
    rows = sorted(idx, key=lambda r: w1y(r)['gap'])[:N]
    add('income-furthest-behind', 'The income ETFs furthest behind their benchmark', 'total return minus the benchmark return, in points', 'one year',
        'Total return reinvests every distribution on its ex-date and is measured against the index or stock the fund writes options on.', 'income',
        ['Ticker', 'Fund', 'Behind by', 'Total return', 'Benchmark', 'Cash paid'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pts(w1y(r)['gap']), pct(w1y(r)['total']), f"{esc(r['benchmark'])} {pct(w1y(r).get('bench'))}", pct(w1y(r)['cash'], sign=False)] for r in rows],
        as_i, 'Selling upside is the trade these funds make. In a rising market that shows up here.',
        '<a href="/income/">Every income ETF</a><a href="/rankings/income-furthest-ahead.html">Furthest ahead</a>')
    rocof = lambda r: ((sources.get(r['ticker']) or {}).get('latest') or {}).get('roc')
    roc = [r for r in income if rocof(r) is not None]
    rows = sorted(roc, key=lambda r: -rocof(r))[:N]
    add('income-highest-return-of-capital', 'The income ETFs with the highest estimated return of capital', 'the issuer\'s own estimate for its latest distribution', 'latest distribution',
        'Every figure is the issuer\'s Rule 19a-1 estimate for its most recent distribution, not an ETFIQ calculation, and not final until the tax year closes.', 'income',
        ['Ticker', 'Fund', 'Return of capital', 'Cash paid 1Y', 'Price change 1Y', 'Total return 1Y'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pct(rocof(r), sign=False, d=0), pct(w1y(r).get('cash'), sign=False), pct(w1y(r).get('price')), pct(w1y(r).get('total'))] for r in rows],
        as_i, 'A high figure is a tax characterisation, not proof of erosion. Whether the fund earned what it paid is the total return column.',
        '<a href="/income/">Every income ETF</a><a href="/questions/what-is-return-of-capital.html">What return of capital means</a>')
    cheap = [r for r in income if r.get('expenseRatio') is not None]
    rows = sorted(cheap, key=lambda r: r['expenseRatio'])[:N]
    add('income-cheapest', 'The cheapest option-income ETFs', 'prospectus expense ratio', None,
        'Fees are read from the risk and return data filed as XBRL with each fund\'s prospectus.', 'income',
        ['Ticker', 'Fund', 'Expense ratio', 'Cash paid 1Y', 'Total return 1Y', 'vs benchmark'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pct(r['expenseRatio'], sign=False, d=2), pct(w1y(r).get('cash'), sign=False), pct(w1y(r).get('total')), pts(w1y(r).get('gap'))] for r in rows],
        as_i, 'Cheapest is not best. The return columns are on the same row for that reason.',
        '<a href="/income/">Every income ETF</a><a href="/questions/how-much-do-etfs-cost.html">What these funds cost</a>')

    # ---- themes
    withb = [r for r in themes if r.get('vsSPY')]
    rows = sorted(withb, key=lambda r: -r['vsSPY']['inIndex'])[:N]
    add('themes-most-index', 'The thematic ETFs that are mostly the index already', 'weight in stocks the S&P 500 also holds', 'latest holdings filing',
        'ETFIQ matches each fund\'s filed holdings against the S&P 500 book on CUSIP, then ISIN, then ticker, then a normalised name.', 'themes',
        ['Ticker', 'Fund', 'Theme', 'In the S&P 500', 'Active share', 'Fee', 'Fee for the differing part'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), esc(r['themeName']), pct(r['vsSPY']['inIndex'], sign=False), pct(r['vsSPY']['activeShare'], sign=False),
          pct(r.get('expenseRatio'), sign=False, d=2), pct(r.get('activeFee'), sign=False, d=2)] for r in rows],
        as_t, 'The theme is a smaller bet than the name suggests when most of the fund is already in the index a holder owns elsewhere.',
        '<a href="/themes/">Every thematic ETF</a><a href="/rankings/themes-least-index.html">Least like the index</a><a href="/questions/what-is-active-share.html">What active share means</a>')
    rows = sorted(withb, key=lambda r: -r['vsSPY']['activeShare'])[:N]
    add('themes-least-index', 'The thematic ETFs least like the S&P 500', 'active share against the S&P 500', 'latest holdings filing',
        'Active share is one hundred minus the weight overlap with the S&P 500 book, computed by ETFIQ from filed holdings.', 'themes',
        ['Ticker', 'Fund', 'Theme', 'Active share', 'In the S&P 500', 'Total return 1Y', 'vs S&P 500'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), esc(r['themeName']), pct(r['vsSPY']['activeShare'], sign=False), pct(r['vsSPY']['inIndex'], sign=False),
          pct(w1y(r).get('total')), pts(w1y(r).get('gap'))] for r in rows],
        as_t, 'Different is not better. It is how much of the fund a holder did not already own through the index.',
        '<a href="/themes/">Every thematic ETF</a><a href="/rankings/themes-most-index.html">Mostly the index already</a>')
    fee_rows = [r for r in withb if r.get('expenseRatio') is not None and r['vsSPY']['inIndex'] >= 50]
    rows = sorted(fee_rows, key=lambda r: -(r['expenseRatio'] * r['vsSPY']['inIndex'] / 100))[:N]
    add('themes-costliest-index-exposure', 'The costliest way to own S&P 500 names', 'expense ratio multiplied by the weight already in the index',
        'latest holdings filing and prospectus',
        'Both inputs are published: the fee from the prospectus, the index weight from the fund\'s own holdings filing. The product is the fee a holder pays on the part of the fund the S&P 500 already covers.', 'themes',
        ['Ticker', 'Fund', 'Fee on index names', 'Expense ratio', 'In the S&P 500', 'Active share'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), pct(r['expenseRatio'] * r['vsSPY']['inIndex'] / 100, sign=False, d=2),
          pct(r['expenseRatio'], sign=False, d=2), pct(r['vsSPY']['inIndex'], sign=False), pct(r['vsSPY']['activeShare'], sign=False)] for r in rows],
        as_t, 'Only funds with at least half their weight already in the index are eligible, because the measure is meaningless below that.',
        '<a href="/themes/">Every thematic ETF</a><a href="/rankings/themes-most-index.html">Mostly the index already</a><a href="/core/">Core index funds</a>')
    drops = [r for r in themes if r.get('drawdown') is not None]
    rows = sorted(drops, key=lambda r: r['drawdown'])[:N]
    add('themes-furthest-below-high', 'The thematic ETFs furthest below their high', 'percent below the all-time high on the reinvested series', None,
        'Measured on total return with distributions reinvested, from the fund\'s own highest point since listing.', 'themes',
        ['Ticker', 'Fund', 'Theme', 'Below its high', 'High set', 'Total return 1Y'],
        [[r['ticker'], tk(r['ticker']), esc(r['name']), esc(r['themeName']), pct(r['drawdown']), fdate(r.get('highDate')), pct(w1y(r).get('total'))] for r in rows],
        as_t, 'A deep drawdown says where a fund has been, not where it is going.',
        '<a href="/themes/">Every thematic ETF</a><a href="/browse/">Browse by theme</a>')
    tks = (matrix or {}).get('tickers') or []
    pairs = []
    if tks and (matrix or {}).get('rows'):
        by = {r['ticker']: r for r in themes}
        for i, a in enumerate(tks):
            row = matrix['rows'][i]
            for k, v in enumerate(row):
                b = tks[i + k + 1]
                if v is not None and v >= 50 and a in by and b in by:
                    pairs.append((v, a, b))
        pairs.sort(reverse=True)
    add('themes-most-overlapping-pairs', 'The thematic ETFs that hold most of the same portfolio', 'weight overlap between two funds', 'latest holdings filings',
        'Weight overlap is the sum of the smaller weight of every security two funds share, from their own filings. ETFIQ computes it for every pair on the desk.', 'themes',
        ['Pair', 'Funds', 'Overlap', 'Themes'],
        [[a, f'{tk(a)} and {tk(b)}', f'{esc((by[a])["name"][:34])} · {esc((by[b])["name"][:34])}', f'{v}%',
          f'{esc(by[a]["themeName"])} · {esc(by[b]["themeName"])}'] for v, a, b in pairs[:N]] if pairs else [],
        as_t, 'Above half, holding both funds is close to holding one of them twice.',
        '<a href="/themes/">Every thematic ETF</a><a href="/compare/">Head to head</a>')
    return [o for o in out if o]


RANK_MEASURE = {}


def rankings_index(items, as_of):
    groups = {'buffer': [], 'income': [], 'themes': []}
    for slug, title, _ in items:
        d = 'buffer' if slug.startswith('buffer') else 'income' if slug.startswith('income') else 'themes'
        groups[d].append((slug, title))
    secs = ''
    for d, label in (('buffer', 'Buffer desk'), ('income', 'Income desk'), ('themes', 'Themes desk')):
        if groups[d]:
            secs += (f'<h2>{label}</h2><nav class="list">'
                     + ''.join(f'<a href="/rankings/{s}.html"><span class="lvl">{label}</span><b>{esc(t)}</b>'
                               f'<span>Ranked by {esc(RANK_MEASURE.get(s, "a single published field"))}.</span></a>' for s, t in groups[d]) + '</nav>')
    inner = (f'<p class="note">Rebuilt every trading night. Figures as of {tdate(as_of)}.</p>'
             '<h1>Rankings</h1>'
             '<p class="lede">Each list is one published field, sorted. The measure is in the title, the method is on the page, and nothing here is a view on any fund. '
             'For any other cut of the same data, the desks sort on every column.</p>'
             + secs
             + '<h2>Where to next</h2><nav class="rel"><a href="/statistics/">ETF statistics</a><a href="/compare/">Head to head</a><a href="/questions/">Questions</a><a href="/research/">ETFIQ Research</a></nav>'
             + '<p class="note">A ranking is not a recommendation. ETFIQ publishes the same fields for every fund in a category and suggests no allocation. '
               '<a href="/standards/">Standards and sources</a></p>')
    return doc_page('rankings/', 'Rankings: ETFs sorted by one published field',
                    'Buffer, option-income and thematic ETFs ranked by a single stated measure, rebuilt every trading night. Not recommendations.',
                    inner, short='Rankings')


# ---------------------------------------------------------------- comparisons across desks and among core funds
CORE_TOP = ['VOO', 'SPY', 'QQQ', 'VTI', 'SCHD', 'IVV', 'QQQM', 'VUG', 'VTV', 'VYM', 'VIG', 'IWM', 'IJH', 'IJR',
            'RSP', 'XLK', 'VGT', 'AGG', 'BND', 'GLD']
KIND_WORD = {'buffer': 'buffer', 'income': 'option-income', 'themes': 'thematic', 'core': 'index'}


def x_cmp_page(a, b, ka, kb, as_of, matrix, words_a, words_b, related_pairs):
    """A head to head between two funds that are not on the same desk, or between two core funds."""
    ta, tb = a['ticker'], b['ticker']
    url = f'{BASE}/compare/any/{pair_slug(ta, tb)}.html'
    overlap = pair_overlap(ta, tb, matrix) if (ka == 'themes' and kb == 'themes') else None
    title = f'{ta} vs {tb}: how they differ'
    labels, ra, rb = any_rows(a, b, ka, kb, {})
    wa = (a.get('windows') or {}).get('1Y') or {}
    wb = (b.get('windows') or {}).get('1Y') or {}
    desc = (f'{ta} and {tb} side by side to {fdate(as_of)}: one-year total return {pct(wa.get("total"))} against {pct(wb.get("total"))}, '
            f'expense ratio {pct(a.get("expenseRatio"), sign=False, d=2)} against {pct(b.get("expenseRatio"), sign=False, d=2)}.')
    faqs = []
    if wa.get('total') is not None and wb.get('total') is not None:
        best = ta if wa['total'] >= wb['total'] else tb
        faqs.append((f'Which returned more over the last year, {ta} or {tb}?',
                     f'In the year to {fdate(as_of)}, with distributions reinvested, {ta} returned {pct(wa["total"])} and {tb} returned {pct(wb["total"])}, so {best} returned more. '
                     'One year is one year; the longer windows are in the table.'))
    fa, fb = a.get('expenseRatio'), b.get('expenseRatio')
    if fa is not None and fb is not None:
        faqs.append((f'Which is cheaper, {ta} or {tb}?',
                     f'{ta} charges {pct(fa, sign=False, d=2)} a year and {tb} charges {pct(fb, sign=False, d=2)}, so {ta if fa <= fb else tb} is cheaper. Fees come from each fund\'s prospectus.'))
    va, vb = (a.get('vsSPY') or {}), (b.get('vsSPY') or {})
    if va.get('inIndex') is not None and vb.get('inIndex') is not None:
        faqs.append((f'How much do {ta} and {tb} overlap with the S&P 500?',
                     f'By their latest filed holdings, {va["inIndex"]:.0f}% of {ta} and {vb["inIndex"]:.0f}% of {tb} by weight is stocks the S&P 500 already holds.'
                     + (f' Between the two funds, {overlap}% of their books are the same securities at the same weight.' if overlap is not None else '')))
    if ka != kb:
        faqs.append((f'Are {ta} and {tb} the same kind of fund?',
                     f'No. {ta} is {"an" if KIND_WORD[ka][0] in "aeiou" else "a"} {KIND_WORD[ka]} ETF and {tb} is {"an" if KIND_WORD[kb][0] in "aeiou" else "a"} {KIND_WORD[kb]} ETF, '
                     'so they are built for different jobs. The table compares what both publish: return, cost and what each actually holds.'))
    faq_html, faq_ld = faq_block(faqs)
    ld = faq_ld + [
        crumbs([('ETFIQ', BASE + '/'), ('Head to head', f'{BASE}/compare/'), (f'{ta} vs {tb}', url)]),
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': as_of, 'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE}},
        {'@type': 'Dataset', 'name': f'ETFIQ comparison of {ta} and {tb}', 'description': desc, 'dateModified': as_of,
         'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'license': f'{BASE}/standards/', 'isAccessibleForFree': True, 'url': url}]
    head = (f'<tr><th></th><th><a href="/funds/{ta}.html">{esc(ta)}</a><div class="sub">{esc(a["name"])}</div></th>'
            f'<th><a href="/funds/{tb}.html">{esc(tb)}</a><div class="sub">{esc(b["name"])}</div></th></tr>')
    body = ''.join(f'<tr><th>{esc(l)}</th><td>{esc(x)}</td><td>{esc(y)}</td></tr>' for l, x, y in zip(labels, ra, rb))
    rel = ''.join(f'<a href="/compare/any/{pair_slug(x, y)}.html">{esc(x)} vs {esc(y)}</a>' for x, y in related_pairs[:8])
    inner = (f'<p class="note">Data as of {fdate(as_of)}. Both funds on the fields they both publish, from the same sources.</p>'
             f'<h1>{esc(ta)} vs {esc(tb)}</h1><p class="lede">{esc(a["name"])} and {esc(b["name"])}.</p>'
             + (f'<p class="lede">{overlap}% of the two portfolios are the same securities at the same weight.</p>' if overlap is not None else '')
             + f'<table class="cmp"><caption>{esc(ta)} and {esc(tb)} on the fields both publish, as of {fdate(as_of)}. Source: ETFIQ.</caption><thead>{head}</thead><tbody>{body}</tbody></table>'
             + f'<h2>{esc(ta)} in plain words</h2><p>{esc(words_a)}</p>'
             + f'<h2>{esc(tb)} in plain words</h2><p>{esc(words_b)}</p>'
             + faq_html
             + (f'<h2>Other comparisons</h2><nav class="rel">{rel}</nav>' if rel else '')
             + f'<h2>Where to next</h2><nav class="rel"><a href="/funds/{ta}.html">{esc(ta)} on its own</a><a href="/funds/{tb}.html">{esc(tb)} on its own</a><a href="/portfolio/">Hold both: look the portfolio through</a><a href="/rankings/">Rankings</a></nav>'
             + cite_line(f'{ta} against {tb}', as_of, url)
             + '<p class="note">A comparison is not a recommendation. ETFIQ publishes the same fields for every fund and suggests no allocation. '
               '<a href="/standards/">Standards and sources</a></p>')
    return doc_page(f'compare/any/{pair_slug(ta, tb)}.html', title, desc, inner, ld, wide=True, short=f'{ta} vs {tb}',
                    crumb=[('Head to head', f'{BASE}/compare/')])


def compare_index(rows, as_of):
    """One row per fund, with every comparison it appears in. A filter box narrows it; the rows are all in the
    HTML, so a crawler and a reader without scripts still see everything."""
    trs = ''.join(
        f'<tr data-k="{esc((t + " " + name).lower())}"><td><a href="/funds/{t}.html" class="tk">{esc(t)}</a></td>'
        f'<td>{esc(name)}</td><td>{esc(where)}</td><td>{"".join(links)}</td></tr>'
        for t, name, where, links in rows)
    inner = ('<h1>Head to head</h1>'
             '<p class="lede">Any two funds on the fields they both publish: what each returned, what it costs, and what it actually holds. '
             'Comparisons run within a desk and across them, and among the plain index funds people already own.</p>'
             '<div class="filterbox"><input id="cmpFilter" type="search" placeholder="Filter by ticker or fund name, for example JEPI" aria-label="Filter comparisons"></div>'
             f'<div style="overflow-x:auto"><table class="hub pairs"><caption>Every fund with a comparison page, as of {fdate(as_of)}. Source: ETFIQ.</caption>'
             '<thead><tr><th>Ticker</th><th>Fund</th><th>Where it sits</th><th>Compared with</th></tr></thead>'
             f'<tbody id="cmpRows">{trs}</tbody></table></div>'
             f'<p class="note" id="cmpCount">{len(rows)} funds with a comparison page.</p>'
             '<h2>Where to next</h2><nav class="rel"><a href="/rankings/">Rankings</a><a href="/issuers/">Every issuer</a>'
             '<a href="/portfolio/">Look a portfolio through</a><a href="/questions/">Questions</a></nav>'
             '<p class="note">A comparison is not a recommendation. <a href="/standards/">Standards and sources</a></p>'
             '<script>(function(){var i=document.getElementById("cmpFilter"),b=document.getElementById("cmpRows"),c=document.getElementById("cmpCount");'
             'if(!i||!b)return;var rows=[].slice.call(b.rows);i.addEventListener("input",function(){var q=i.value.trim().toLowerCase(),n=0;'
             'rows.forEach(function(r){var on=!q||r.getAttribute("data-k").indexOf(q)>-1;r.hidden=!on;if(on)n++;});'
             'if(c)c.textContent=n+" of "+rows.length+" funds"+(q?" matching "+i.value:"")+".";});})();</script>')
    return doc_page('compare/', 'Head to head: compare any two ETFs on what they publish',
                    'Buffer, option-income, thematic and core index ETFs compared two at a time on return, cost, holdings and overlap with the S&P 500.',
                    inner, wide=True, short='Head to head')


# ---------------------------------------------------------------- question pages and the statistics page
Q_TITLES = []


def q_page(slug, question, desk, answer, detail, examples, as_of, related):
    Q_TITLES.append((slug, question))
    """One page per question people actually type, answered first in a sentence, then shown with live figures."""
    url = f'{BASE}/questions/{slug}.html'
    faq_html, faq_ld = faq_block([(question, answer)])
    ex = ''
    if examples:
        ex = ('<h2>On the desk today</h2><div style="overflow-x:auto"><table class="hub"><thead><tr>'
              + ''.join(f'<th>{h}</th>' for h in examples[0]) + '</tr></thead><tbody>'
              + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in examples[1:])
              + '</tbody></table></div>')
    inner = (f'<p class="note">Answered from ETFIQ data as of {tdate(as_of)}.</p>'
             f'<h1>{esc(question)}</h1>'
             f'<p class="lede">{esc(answer)}</p>'
             + ''.join(f'<p>{d}</p>' for d in detail)
             + ex
             + f'<h2>Where to next</h2><nav class="rel">{related}</nav>'
             + '<p class="note">ETFIQ is an independent publisher of exchange-traded fund data and makes no recommendations. '
               'Every figure is stated arithmetic on published data. <a href="/standards/">Standards and sources</a></p>'
             + cite_line(question, as_of, url))
    return slug, doc_page(f'questions/{slug}.html', question, answer[:300], inner, faq_ld,
                          desk=desk, crumb=[('Questions', f'{BASE}/questions/')], short=question if len(question) < 42 else question[:40] + '...')


def question_pages(funds, income, themes, core, as_b, as_i, as_t):
    Q_TITLES.clear()
    out = []
    n_at_cap = sum(1 for f in funds if f.get('startCap') is not None and f.get('refReturn') is not None and f['refReturn'] >= f['startCap'])
    idx = [r for r in income if (r.get('benchmarkKind') or '') != 'stock' and ((r.get('windows') or {}).get('1Y') or {}).get('gap') is not None]
    ahead = sum(1 for r in idx if r['windows']['1Y']['gap'] > 0.5)
    ins = sorted((r['vsSPY']['inIndex'] for r in themes if r.get('vsSPY')))
    med_in = ins[len(ins) // 2] if ins else None
    fees = sorted(r['expenseRatio'] for r in income if r.get('expenseRatio') is not None)
    med_fee = fees[len(fees) // 2] if fees else None
    roc = sorted(r['src']['latest']['roc'] for r in income if (r.get('src') or {}).get('latest', {}).get('roc') is not None) if any('src' in r for r in income) else []
    top_cash = sorted((r for r in income if ((r.get('windows') or {}).get('1Y') or {}).get('cash') is not None), key=lambda r: -r['windows']['1Y']['cash'])[:8]
    soon = sorted((f for f in funds if (f.get('daysRemaining') or 999) <= 45), key=lambda f: f.get('daysRemaining') or 999)[:8]
    diff = sorted((r for r in themes if r.get('vsSPY')), key=lambda r: -r['vsSPY']['activeShare'])[:8]

    out.append(q_page('what-is-a-buffer-etf', 'What is a buffer ETF?', 'buffer',
        f'A buffer ETF, also called a defined outcome ETF, absorbs a stated range of an index\'s losses over a set period in exchange for a ceiling on the gain. ETFIQ tracks {len(funds)} of them, and on {fdate(as_b)}, {n_at_cap} had already reached that ceiling.',
        ['The fund buys options on a reference index, usually the S&P 500 through SPY, that pay off in a shape decided on the first day of the period. A typical fund absorbs the first 9 or 15 percent of index losses and caps the gain somewhere above 10 percent. Both numbers are struck from option prices on day one, so the same fund carries a different cap each year.',
         'Two things surprise buyers. The protection applies over the whole outcome period, not day to day, so a fund bought halfway through has different terms than the ones advertised on the first day. And once the index has risen past the cap, there is no more upside to collect however far it climbs; the fund is waiting for the reset.',
         'ETFIQ places every fund on one band from its buffer floor to its cap, so funds from different issuers can be read the same way. <a href="/learn/buffer.html">The vocabulary is here</a>.'],
        [['Ticker', 'Fund', 'Buffer', 'Can still gain', 'Fall before buffer', 'Period ends']] +
        [[f'<a href="/funds/{f["ticker"]}.html" class="tk">{f["ticker"]}</a>', esc(f['name']), esc(f.get('bufferLabel', '')),
          'uncapped' if f.get('isUncapped') else pct(f.get('remainingCapFund'), sign=False), pct(f.get('downsideBeforeBuffer'), sign=False), fdate(f['periodEnd'])] for f in soon],
        as_b, '<a href="/buffer/">Every buffer ETF</a><a href="/learn/buffer.html">The vocabulary</a><a href="/questions/how-does-a-buffer-etf-reset.html">How a buffer resets</a>'))

    out.append(q_page('how-does-a-buffer-etf-reset', 'How does a buffer ETF reset?', 'buffer',
        f'On the last day of its outcome period the options expire, and the next day the fund strikes a new cap from that day\'s option prices while the buffer starts again from zero. ETFIQ tracks {len(funds)} buffer ETFs, and {len(soon)} of the ones shown here reset within 45 days of {fdate(as_b)}.',
        ['A fund carries its freshest cap in the days after it resets, and its least remaining room just before. That is why the same ticker can look generous in January and exhausted in November.',
         'The buffer resets too. A fund whose index fell during the period, using part of the buffer, starts the next period with the whole buffer intact and a cap struck at the new level.',
         'Because caps are set by the option market, they move with volatility. A calm market produces lower caps; a nervous one produces higher caps for the same buffer.'],
        [['Ticker', 'Fund', 'Period ends', 'Days left', 'Buffer', 'State']] +
        [[f'<a href="/funds/{f["ticker"]}.html" class="tk">{f["ticker"]}</a>', esc(f['name']), fdate(f['periodEnd']), str(f.get('daysRemaining')), esc(f.get('bufferLabel', '')), STATE_LABEL[buffer_state(f)]] for f in soon],
        as_b, '<a href="/buffer/">Every buffer ETF</a><a href="/questions/what-is-a-buffer-etf.html">What a buffer ETF is</a><a href="/browse/">Browse by reset month</a>'))

    out.append(q_page('what-is-return-of-capital', 'What is return of capital in an ETF distribution?', 'income',
        'Return of capital is the part of a distribution that is not income or realised gains, so it comes back out of the fund\'s own assets and is not taxed as income in the year it is paid. It lowers the cost basis instead.'
        + (f' Across the funds ETFIQ tracks, the median latest estimate is {roc[len(roc) // 2]:.0f}% of the distribution.' if roc else ''),
        ['Issuers estimate the split on a Rule 19a-1 notice with each distribution, and the estimate is not final until the tax year closes. ETFIQ shows the issuer\'s own figure and never a computed one.',
         'A high return of capital figure is not automatically a warning. A fund that writes options can generate cash that is characterised as return of capital even while the total return is healthy. What matters is whether the fund earned what it paid, which the price change beside the cash tells you.',
         'That is why ETFIQ always shows return of capital next to the price change over the same period rather than on its own.'],
        [['Ticker', 'Fund', 'Cash paid 1Y', 'Price 1Y', 'Total return 1Y', 'Return of capital, latest']] +
        [[f'<a href="/funds/{r["ticker"]}.html" class="tk">{r["ticker"]}</a>', esc(r['name']),
          pct(r['windows']['1Y']['cash'], sign=False), pct(r['windows']['1Y']['price']), pct(r['windows']['1Y']['total']),
          pct(((r.get('src') or {}).get('latest') or {}).get('roc'), sign=False, d=0)] for r in top_cash],
        as_i, '<a href="/income/">Every income ETF</a><a href="/learn/income.html">The vocabulary</a><a href="/questions/do-covered-call-etfs-lose-value.html">Do covered call ETFs lose value?</a>'))

    out.append(q_page('do-covered-call-etfs-lose-value', 'Do covered call ETFs lose value?', 'income',
        f'Many do lose price while paying cash, which is not the same as losing money. Over the year to {fdate(as_i)}, {ahead} of {len(idx)} index option-income ETFs finished ahead of the index they write options on once every distribution was counted and reinvested.',
        ['A covered call fund sells away part of the upside, so in a rising market it usually trails the index. The cash it pays can exceed what it earns, and when it does the price falls to fund the difference.',
         'The honest test is total return with distributions reinvested, measured against the index or stock the fund actually writes options on, which is what ETFIQ publishes for every fund over five windows.',
         'A fund paying 40 percent a year while its price falls 30 percent has not necessarily hurt you, and a fund paying 8 percent while flat has not necessarily helped. The gap to the benchmark settles it.'],
        [['Ticker', 'Fund', 'Cash paid 1Y', 'Price 1Y', 'Total return 1Y', 'vs benchmark']] +
        [[f'<a href="/funds/{r["ticker"]}.html" class="tk">{r["ticker"]}</a>', esc(r['name']),
          pct(r['windows']['1Y']['cash'], sign=False), pct(r['windows']['1Y']['price']), pct(r['windows']['1Y']['total']), pts(r['windows']['1Y'].get('gap'))] for r in top_cash],
        as_i, '<a href="/income/">Every income ETF</a><a href="/questions/what-is-return-of-capital.html">What return of capital means</a><a href="/compare/">Head to head</a>'))

    out.append(q_page('what-is-active-share', 'What is active share, and what does it tell you about an ETF?', 'themes',
        f'Active share is the share of a fund that is not the index, by weight. A fund at 85% active share has 15% of its money in index names at index weights. Across the thematic ETFs ETFIQ tracks, the typical fund holds {med_in:.0f}% of its weight in stocks the S&P 500 already owns.' if med_in is not None else 'Active share is the share of a fund that is not the index, by weight.',
        ['ETFIQ computes it from each fund\'s latest filed holdings against the S&P 500 book, matching securities on CUSIP, then ISIN, then ticker, then a normalised name. Overlap is the sum of the smaller weight of every security the two hold in common, and active share is one hundred minus that.',
         'The number matters because a thematic fund is usually bought for the part that is different. If most of the fund is index names you already own, the theme is a smaller bet than the name suggests, and the fee is being paid on the whole fund rather than on the differing part.',
         'ETFIQ also shows what that works out to: the fee divided by the share that differs, which is the price of the active decision.'],
        [['Ticker', 'Fund', 'Theme', 'In the S&P 500', 'Active share', 'Fee', 'Fee for the differing part']] +
        [[f'<a href="/funds/{r["ticker"]}.html" class="tk">{r["ticker"]}</a>', esc(r['name']), esc(r['themeName']),
          pct(r['vsSPY']['inIndex'], sign=False), pct(r['vsSPY']['activeShare'], sign=False),
          pct(r.get('expenseRatio'), sign=False, d=2), pct(r.get('activeFee'), sign=False, d=2)] for r in diff],
        as_t, '<a href="/themes/">Every thematic ETF</a><a href="/learn/themes.html">The vocabulary</a><a href="/questions/are-thematic-etfs-worth-it.html">Are thematic ETFs different from the index?</a>'))

    out.append(q_page('are-thematic-etfs-worth-it', 'How different is a thematic ETF from the index?', 'themes',
        f'Less different than the name suggests, on average. By their latest holdings filings, the typical thematic ETF ETFIQ tracks carries {med_in:.0f}% of its weight in stocks the S&P 500 already holds.' if med_in is not None else 'ETFIQ measures every thematic ETF against the S&P 500 book by holdings.',
        ['A theme is a story about the future; the holdings are what you own. The two can differ a great deal, because an index provider building a themed index still has to find liquid, investable companies, and the largest of those are usually already in the S&P 500.',
         'ETFIQ measures the overlap for every fund and also between funds, so two funds in the same theme can be checked against each other. Some pairs share more than half their book at the same weights.',
         'None of this says a theme is good or bad. It says how much of it you did not already own.'],
        [['Ticker', 'Fund', 'Theme', 'In the S&P 500', 'Active share', 'Total return 1Y', 'vs S&P 500']] +
        [[f'<a href="/funds/{r["ticker"]}.html" class="tk">{r["ticker"]}</a>', esc(r['name']), esc(r['themeName']),
          pct(r['vsSPY']['inIndex'], sign=False), pct(r['vsSPY']['activeShare'], sign=False),
          pct(((r.get('windows') or {}).get('1Y') or {}).get('total')), pts(((r.get('windows') or {}).get('1Y') or {}).get('gap'))] for r in diff],
        as_t, '<a href="/themes/">Every thematic ETF</a><a href="/questions/what-is-active-share.html">What active share means</a><a href="/browse/">Browse by theme</a>'))

    out.append(q_page('how-much-do-etfs-cost', 'How much do these ETFs cost?', 'income',
        f'The median option-income ETF ETFIQ tracks charges {med_fee:.2f}% a year, taken from each fund\'s own prospectus.' if med_fee is not None else 'Fees come from each fund\'s prospectus.',
        ['Fees on these funds sit well above a plain index fund, which charges three to twenty basis points. The question is what the extra buys, and ETFIQ shows that alongside: the cash a fund paid, whether it beat what it writes options on, and for thematic funds how much of the portfolio actually differs from the index.',
         'ETFIQ reads every fee from the risk and return data filed as XBRL with the fund\'s prospectus rather than from a marketing page, so a fee here matches the fee in the document that governs the fund.'],
        None, as_i, '<a href="/income/">Every income ETF</a><a href="/core/">Core index funds for comparison</a><a href="/data/">The underlying data</a>'))
    return out


Q_BLURB = {
    'what-is-a-buffer-etf': 'What a defined outcome fund does, why the cap and the buffer are struck on day one, and what a mid-period buyer actually gets.',
    'how-does-a-buffer-etf-reset': 'What happens on the last day of an outcome period, why the new cap can differ, and when a fund is at its freshest.',
    'what-is-return-of-capital': 'What the issuers estimate on a 19a-1 notice, why a high figure is not proof of erosion, and what to read beside it.',
    'do-covered-call-etfs-lose-value': 'Whether a falling price means losing money, and the test that settles it: total return against what the fund writes options on.',
    'what-is-active-share': 'How ETFIQ measures the part of a fund that is not the index, and what the fee on that part works out at.',
    'are-thematic-etfs-worth-it': 'How much of a theme a holder did not already own through the index, measured from filed holdings.',
    'how-much-do-etfs-cost': 'What these funds charge, read from the prospectus, and what the extra buys.',
}


def questions_index(qs, as_of):
    links = ''.join(f'<a href="/questions/{slug}.html"><span class="lvl">Question</span><b>{esc(q)}</b>'
                    f'<span>{esc(Q_BLURB.get(slug, "Answered from ETFIQ data, rebuilt every trading night."))}</span></a>' for slug, q in qs)
    inner = ('<h1>Questions</h1><p class="lede">The questions people ask about these funds, answered from the data on the desks and rebuilt every trading night.</p>'
             f'<nav class="list">{links}</nav>'
             '<h2>Where to next</h2><nav class="rel"><a href="/learn/">The vocabulary</a><a href="/rankings/">Rankings</a><a href="/compare/">Head to head</a><a href="/statistics/">ETF statistics</a></nav>'
             '<p class="note">Every answer is stated arithmetic on published data. <a href="/standards/">Standards and sources</a></p>')
    return doc_page('questions/', 'Questions about buffer, income and thematic ETFs',
                    'Plain answers to the questions people ask about defined outcome, option-income and thematic ETFs, from live data.', inner, short='Questions')


def stats_page(funds, income, themes, core, as_b, as_i, as_t, extra):
    url = f'{BASE}/statistics/'
    lines = []
    n_cap = sum(1 for f in funds if f.get('startCap') is not None and f.get('refReturn') is not None and f['refReturn'] >= f['startCap'])
    idx = [r for r in income if (r.get('benchmarkKind') or '') != 'stock' and ((r.get('windows') or {}).get('1Y') or {}).get('gap') is not None]
    ahead = sum(1 for r in idx if r['windows']['1Y']['gap'] > 0.5)
    gaps = sorted(r['windows']['1Y']['gap'] for r in idx)
    cash = sorted(r['windows']['1Y']['cash'] for r in idx)
    ins = sorted(r['vsSPY']['inIndex'] for r in themes if r.get('vsSPY'))
    med = lambda xs: xs[len(xs) // 2] if xs else None
    lines.append((f'Buffer ETFs covered, {fdate(as_b)}', str(len(funds)), f'{len(set(f["issuer"] for f in funds))} issuers'))
    lines.append(('Buffer ETFs at their cap', str(n_cap), f'{n_cap / len(funds) * 100:.0f}% of the desk' if funds else ''))
    lines.append(('Buffer ETFs resetting within 45 days', str(sum(1 for f in funds if (f.get('daysRemaining') or 999) <= 45)), 'a new cap is struck the next day'))
    lines.append((f'Option-income ETFs covered, {fdate(as_i)}', str(len(income)), f'{len(set(r["issuer"] for r in income))} issuers'))
    lines.append(('Index income ETFs ahead of their benchmark over one year', f'{ahead} of {len(idx)}', 'total return with distributions reinvested'))
    lines.append(('Median gap to the benchmark, index income ETFs', pts(med(gaps)), 'one year'))
    lines.append(('Median cash paid, index income ETFs', pct(med(cash), sign=False), 'one year, as a percent of the starting price'))
    lines.append((f'Thematic ETFs covered, {fdate(as_t)}', str(len(themes)), '27 themes'))
    lines.append(('Weight of the typical thematic ETF already in the S&P 500', pct(med(ins), sign=False), 'by its latest holdings filing'))
    lines.append(('Core index, bond and commodity funds covered', str(len(core)), 'the funds the desks measure against'))
    rows = ''.join(f'<tr><th>{esc(a)}</th><td class="num"><b>{esc(b)}</b></td><td class="muted">{esc(c)}</td></tr>' for a, b, c in lines)
    ld = [{'@type': 'Dataset', 'name': 'ETFIQ statistics', 'description': 'Category-level statistics on buffer, option-income and thematic ETFs, recomputed every trading night.',
           'url': url, 'dateModified': max(as_b, as_i, as_t), 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE},
           'license': f'{BASE}/data/', 'isAccessibleForFree': True, 'creditText': 'ETFIQ (etfiq.com)'}]
    inner = (f'<p class="note">Recomputed every trading night. Figures as of {tdate(max(as_b, as_i, as_t))}.</p>'
             '<h1>ETF statistics</h1><p class="lede">Category-level figures for defined outcome, option-income and thematic ETFs, counted from the funds ETFIQ covers. '
             'Free to cite with attribution and the date.</p>'
             f'<div style="overflow-x:auto"><table class="hub"><tbody>{rows}</tbody></table></div>'
             f'<h2>What changed today</h2><p>{extra}</p>'
             '<h2>Using these figures</h2><p>Name ETFIQ as the source and state the date, for example: ETFIQ, data as of '
             f'{fdate(max(as_b, as_i, as_t))}, etfiq.com. The underlying files are at <a href="/data/">Open data</a>, and the method is on <a href="/standards/">Standards</a>. '
             'Counts are of the funds ETFIQ covers, which is buffer, option-income and thematic ETFs plus the core funds the desks measure against, not the whole ETF market.</p>'
             '<h2>Where to next</h2><nav class="rel"><a href="/rankings/">Rankings</a><a href="/changed/">What changed today</a><a href="/research/">ETFIQ Research</a><a href="/data/">Open data</a><a href="/questions/">Questions</a></nav>'
             + cite_line('ETF statistics', max(as_b, as_i, as_t), url))
    return doc_page('statistics/', 'ETF statistics: buffer, option-income and thematic funds',
                    'How many buffer ETFs sit at their cap, how many income ETFs beat their benchmark, how much of the typical thematic ETF is already the index. Recomputed nightly.',
                    inner, ld, wide=True, short='Statistics')


# ---------------------------------------------------------------- core index funds
def core_words(r, as_of):
    on = fdate(as_of)
    t = r['ticker']
    s = [f"{t} is a {r['kindLabel'].lower()} tracking {r['note']}."]
    w = (r.get('windows') or {}).get('1Y')
    if w:
        s.append(f"Over the year to {on} it returned {pct(w['total'])} with distributions reinvested, against {pct(w.get('bench'))} for the S&P 500 and {pct(w.get('benchQ'))} for the Nasdaq-100.")
    if r.get('expenseRatio') is not None:
        s.append(f"The prospectus expense ratio is {pct(r['expenseRatio'], sign=False, d=2)} a year.")
    v = r.get('vsSPY')
    if v:
        s.append(f"By its holdings filed for {fdate(r.get('holdingsAsOf'))}, {v['inIndex']:.0f}% of the fund by weight is stocks the S&P 500 also holds, across {r.get('holdingsCount')} positions, with the top ten at {pct(r.get('top10Weight'), sign=False)}.")
    if r.get('drawdown') is not None and r['drawdown'] < -3:
        s.append(f"It sat {pct(-r['drawdown'], sign=False)} below its high of {fdate(r.get('highDate'))} on {on}.")
    return ' '.join(s)


def core_faqs(r, as_of):
    on = fdate(as_of)
    t = r['ticker']
    out = []
    w = (r.get('windows') or {}).get('1Y')
    if w:
        out.append((f'How has {t} performed?', f"Over the year to {on}, {t} returned {pct(w['total'])} with distributions reinvested, against {pct(w.get('bench'))} for the S&P 500. Over three years the figure is {pct(((r.get('windows') or {}).get('3Y') or {}).get('total'))}."))
    if r.get('expenseRatio') is not None:
        out.append((f'What does {t} cost?', f"The prospectus expense ratio is {pct(r['expenseRatio'], sign=False, d=2)} a year."))
    v = r.get('vsSPY')
    if v and r.get('holdingsCount'):
        out.append((f'What does {t} hold?', f"{r['holdingsCount']} positions as filed for {fdate(r.get('holdingsAsOf'))}, with the top ten at {pct(r.get('top10Weight'), sign=False)} of the fund. {v['inIndex']:.0f}% of its weight is in stocks the S&P 500 also holds."))
    if r.get('drawdown') is not None:
        out.append((f'How far is {t} below its high?', f"{pct(-r['drawdown'], sign=False)} below its high of {fdate(r.get('highDate'))}, measured on the reinvested series to {on}."))
    return out


def core_page(r, as_of, neighbours):
    t = r['ticker']
    url = f'{BASE}/funds/{t}.html'
    title = f"{t}: {r['name']}"
    w = (r.get('windows') or {}).get('1Y') or {}
    desc = (f"{t} ({r['note']}) to {fdate(as_of)}: one-year total return {pct(w.get('total'))} against {pct(w.get('bench'))} for the S&P 500, "
            f"expense ratio {pct(r.get('expenseRatio'), sign=False, d=2)}.")
    rows = [('What it tracks', r['note']), ('Fund type', r['kindLabel']), ('Expense ratio (prospectus XBRL)', pct(r.get('expenseRatio'), sign=False, d=2)),
            ('Price', 'n/a' if r.get('price') is None else f"${r['price']:.2f}"), ('Listed since', fdate(r.get('inception')))]
    for k, lab in (('3M', '3 months'), ('6M', '6 months'), ('1Y', '1 year'), ('3Y', '3 years'), ('ITD', 'since listing')):
        x = (r.get('windows') or {}).get(k)
        if x:
            rows.append((f'{lab}: total return / S&P 500 / gap / Nasdaq-100 gap (ETFIQ)',
                         f"{pct(x['total'])} / {pct(x.get('bench'))} / {pts(x.get('gap'))} / {pts(x.get('gapQ'))}"))
    rows.append(('Below its high (ETFIQ)', pct(r.get('drawdown'))))
    if r.get('holdingsCount'):
        rows += [('Holdings', str(r['holdingsCount'])), ('Top ten weight', pct(r.get('top10Weight'), sign=False)),
                 ('Holdings as of (SEC filing)', fdate(r.get('holdingsAsOf')))]
        if r.get('top'):
            rows.append(('Top holdings', ', '.join(f"{h['n']} {h['w']:.1f}%" for h in r['top'][:10])))
    if r.get('vsSPY'):
        rows += [('Already in the S&P 500, by weight (ETFIQ)', pct(r['vsSPY']['inIndex'], sign=False)),
                 ('Active share vs the S&P 500 (ETFIQ)', pct(r['vsSPY']['activeShare'], sign=False))]
    if r.get('vsQQQ'):
        rows.append(('Already in the Nasdaq-100, by weight (ETFIQ)', pct(r['vsQQQ']['inIndex'], sign=False)))
    ld = [{'@type': 'FinancialProduct', 'name': r['name'], 'alternateName': t, 'identifier': t,
           'category': 'Exchange-traded fund, core index fund', 'url': url},
          {'@type': 'Dataset', 'name': f'ETFIQ record for {t}', 'description': desc, 'dateModified': as_of,
           'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'license': f'{BASE}/standards/', 'isAccessibleForFree': True, 'url': url}]
    faq_html, faq_ld = faq_block(core_faqs(r, as_of))
    inner = (f'<p class="note">Data as of {tdate(as_of)}. Returns from exchange end-of-day prices with distributions reinvested; holdings from the fund\'s latest SEC filing.</p>'
             f'<h1><span class="tk">{esc(t)}</span> · {esc(r["name"])}</h1><p class="lede">{esc(r["kindLabel"])} · {esc(r["note"])}</p>'
             f'<p>{esc(core_words(r, as_of))}</p>'
             f'<table class="kv"><tbody>{"".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)}</tbody></table>'
             f'{faq_html}'
             + sources_block([('Holdings filing (SEC Form N-PORT)', r.get('holdingsSource')),
                              ('Prospectus filing with the expense ratio (SEC)', (FEES.get(r['ticker']) or {}).get('source'))])
             + neighbours
             + cite_line(f'{t}, core index fund', as_of, url)
             + '<p class="note">ETFIQ covers buffer, option-income and thematic ETFs. This fund is here because the desks measure against it and portfolios hold it. '
             'ETFIQ is an independent publisher and makes no recommendations. <a href="/standards/">Standards and sources</a></p>')
    return doc_page(f'funds/{t}.html', title, desc, inner, ld + faq_ld, crumb=[('Core funds', f'{BASE}/core/')], short=t)


# ---------------------------------------------------------------- 404, privacy, contact, terms
CONTACT_EMAIL = 'data@etfiq.com'


def not_found_page():
    body = ('<h1>That page is not here</h1>'
            '<p class="lede">The address may have changed, or the fund may not be on a desk. Everything ETFIQ publishes is one of these.</p>'
            '<nav class="rel"><a href="/">Home</a><a href="/buffer/">Buffer ETFs</a><a href="/income/">Income ETFs</a><a href="/themes/">Thematic ETFs</a>'
            '<a href="/portfolio/">Portfolio desk</a><a href="/issuers/">Every issuer</a><a href="/compare/">Head to head</a><a href="/research/">Research</a>'
            '<a href="/learn/">Vocabulary</a><a href="/data/">Open data</a><a href="/standards/">Standards</a></nav>'
            '<h2>Looking for a fund?</h2><p>Fund pages sit at <code>/funds/TICKER.html</code>, for example <a href="/funds/JEPI.html">/funds/JEPI.html</a>. '
            'The <a href="' + BASE + '/#/">search box on the home page</a> takes any ticker on any desk.</p>')
    return doc_page('404.html', 'Page not found', 'That address is not on ETFIQ. Every desk, fund page and dataset is listed here.', body, short='Not found')


def privacy_page():
    body = ('<p class="note">Last updated ' + fdate(TODAY) + '.</p>'
            '<h1>Privacy</h1><p class="lede">ETFIQ is free to read and asks for nothing to use it. This page says what is collected when you do give something, and what is not.</p>'
            '<h2>Reading the site</h2><p>No account, no sign-in and no tracking pixel. ETFIQ runs no advertising network and no third-party analytics or advertising script. '
            'The site is served as static files; the host records ordinary web server information such as the address requested and the time, which ETFIQ does not use to build a profile of you.</p>'
            '<h2>What stays on your device</h2><p>The funds you follow, saved portfolios, your chosen window and theme are kept in your own browser storage. They are never sent to ETFIQ and are not visible to anyone else. '
            'Clearing your browser data removes them.</p>'
            '<h2>If you ask for alerts or the weekly note</h2><p>The email address and the tickers you enter are used to send what you asked for, and nothing else. '
            'They are not sold, rented or shared for anyone else\'s marketing. Every message carries an unsubscribe link, and asking to be removed removes the address.</p>'
            '<h2>Data about funds</h2><p>Everything ETFIQ publishes is about funds, not about people: issuer disclosures, filings with the SEC and exchange prices. See <a href="/standards/">Standards</a> for the sources and <a href="/data/">Open data</a> for the files.</p>'
            '<h2>Children</h2><p>ETFIQ is not directed at children and does not knowingly collect information from anyone under 13.</p>'
            '<h2>Changes and questions</h2><p>Material changes will be noted here with the date. Questions, corrections or a request to be removed: <a href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a>.</p>'
            '<nav class="rel"><a href="/standards/">Standards and sources</a><a href="/terms/">Terms</a><a href="/contact/">Contact</a></nav>')
    return doc_page('privacy/', 'Privacy', 'What ETFIQ collects, which is almost nothing: no account, no tracking pixel, no third-party analytics, and email used only for what you asked for.', body, short='Privacy')


def terms_page():
    body = ('<p class="note">Last updated ' + fdate(TODAY) + '.</p>'
            '<h1>Terms of use</h1><p class="lede">Plain terms for a site that publishes data and sells nothing.</p>'
            '<h2>Not advice</h2><p>ETFIQ is an independent publisher of data about exchange-traded funds. It is not an investment adviser, broker-dealer or fund issuer, '
            'and nothing here is investment advice, an offer, a solicitation or a recommendation to buy or sell anything. Every figure is stated arithmetic on published data. '
            'Decisions about your money are yours, and a fund prospectus is the governing document for any fund.</p>'
            '<h2>Accuracy</h2><p>Figures come from issuer disclosures, filings with the SEC and exchange prices, and each carries the date it was published. '
            'ETFIQ recomputes every published number nightly from the raw sources and corrects errors on the page where they appeared, with the date. '
            'Data can still be wrong, late or incomplete, and it is provided as it is, without warranty.</p>'
            '<h2>Using the data</h2><p>The files at <a href="/data/">Open data</a> and the graphics at <code>/embed/</code> are free to use, including commercially, '
            'with attribution to ETFIQ and a link. Please do not present ETFIQ figures as your own, and do not remove the credit from an embedded graphic.</p>'
            '<h2>Trademarks</h2><p>Fund and index names belong to their owners and appear here to identify the funds being described. '
            'ETFIQ is not affiliated with, endorsed by or sponsored by any issuer or index provider.</p>'
            '<h2>Questions</h2><p><a href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a></p>'
            '<nav class="rel"><a href="/standards/">Standards and sources</a><a href="/privacy/">Privacy</a><a href="/contact/">Contact</a></nav>')
    return doc_page('terms/', 'Terms of use', 'ETFIQ publishes data and makes no recommendations. How the figures are produced, corrected, and how the open data may be reused.', body, short='Terms')


def contact_page():
    body = ('<h1>Contact ETFIQ</h1><p class="lede">One address, read by a person.</p>'
            '<p><a class="cta" href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a></p>'
            '<h2>Corrections</h2><p>If a figure looks wrong, send the ticker, the page and what you expected. Errors are corrected on the page where they appeared, with the date. '
            'Every number is recomputed nightly from the raw sources, so a correction to the method fixes every page at once.</p>'
            '<h2>Issuers</h2><p>ETFIQ publishes the same fields for every fund in a category, from every issuer, and does not accept payment for placement, for a ranking position or for the omission of a fund. '
            'If a figure ETFIQ takes from your disclosure is stale or misread, write and it will be checked against the source.</p>'
            '<h2>Journalists and researchers</h2><p>The underlying files are public at <a href="/data/">Open data</a>, free to use with attribution. '
            'For a figure that is not in them, or the method behind one, write and ask.</p>'
            '<nav class="rel"><a href="/standards/">Standards and sources</a><a href="/data/">Open data</a><a href="/privacy/">Privacy</a><a href="/terms/">Terms</a></nav>')
    return doc_page('contact/', 'Contact', 'How to reach ETFIQ for corrections, data questions and press.', body, short='Contact')


# ---------------------------------------------------------------- the open data page
DATA_FILES = [
    ('funds.json', 'Buffer desk', "Every defined outcome ETF with its published terms and current figures: reference index, buffer, cap, outcome period, index and fund return, remaining cap and downside before the buffer as the issuer publishes them, plus the ETFIQ fields (protection left in index points, buffer used, state)."),
    ('income.json', 'Income desk', "Every option-income ETF with price, cash distributions and total return over 3 months, 6 months, 1 year, 3 years and since launch, each against the index or stock it writes options on, with payout frequency, annualised payout rate, trailing twelve month cash and the prospectus expense ratio."),
    ('thematic.json', 'Themes desk', "Every thematic ETF with its holdings summary, weight already in the S&P 500 and the Nasdaq-100, active share, top ten weight, returns against both indexes, drawdown, fee and active expense ratio, plus a fund-to-fund overlap matrix."),
    ('payouts.json', 'Payout calendar', "Declared, scheduled and estimated distributions per fund, with ex and pay dates, the cadence and the ex-to-pay lag."),
    ('sources.json', 'Return of capital', "Issuers' own Rule 19a-1 estimates of what each distribution was made of, with the notice it came from."),
    ('insights.json', 'What changed', "The computed lines published each trading night, one per finding, with the desk and a link."),
    ('books/index.json', 'Look-through books', "An index of the filed holdings book held for each fund, with its as-of date and whether the fund is synthetic. Individual books sit at /data/books/TICKER.json."),
]


def data_page(as_of, counts):
    url = f'{BASE}/data/'
    title = 'ETFIQ open data'
    desc = 'Every figure ETFIQ publishes, as JSON, free to use with attribution. Rebuilt every trading night from issuer pages, SEC filings and exchange prices.'
    rows = ''.join(f'<tr><th><a href="/data/{fn}"><code>{fn}</code></a></th><td>{esc(lab)}</td><td>{esc(d)}</td></tr>' for fn, lab, d in DATA_FILES)
    ld = [
        {'@type': 'Dataset', 'name': 'ETFIQ exchange-traded fund data', 'description': desc, 'url': url, 'dateModified': as_of,
         'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'publisher': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE},
         'license': url, 'isAccessibleForFree': True, 'creditText': 'ETFIQ (etfiq.com)', 'temporalCoverage': as_of,
         'keywords': ['exchange-traded funds', 'buffer ETFs', 'defined outcome', 'option income', 'covered call', 'thematic ETFs', 'holdings', 'active share'],
         'distribution': [{'@type': 'DataDownload', 'name': lab, 'description': d, 'encodingFormat': 'application/json', 'contentUrl': f'{BASE}/data/{fn}'} for fn, lab, d in DATA_FILES]}]
    parts = [
        f'<p class="note">Rebuilt every trading night. Current files as of {fdate(as_of)}.</p>',
        '<h1>Open data</h1><p class="lede">Every figure on this site is published as JSON at a stable address. Free to use, including commercially, with attribution to ETFIQ and a link to the page or file you used.</p>',
        f'<h2>How to cite</h2><p>Name ETFIQ as the source, state the as-of date carried in the file, and link to etfiq.com. For example: ETFIQ, buffer desk, data as of {fdate(as_of)}, etfiq.com.</p>',
        f'<h2>The files</h2><div style="overflow-x:auto"><table class="hub"><thead><tr><th>File</th><th>Desk</th><th>What it holds</th></tr></thead><tbody>{rows}</tbody></table></div>',
        f'<h2>What is in them today</h2><p>{esc(counts)}</p>',
        '<h2>Method</h2><p>Terms come from issuer product pages and prospectus supplements filed with the SEC. Prices and distributions come from exchange end-of-day data. Holdings come from Form N-PORT and, where an issuer publishes one, its daily file. Fees come from the prospectus risk and return data filed as XBRL. Every figure ETFIQ computes rather than quotes is marked on the page and described on <a href="/standards/">Standards</a>. Each published number is recomputed from the raw sources every night by separate code, and anything that does not reproduce is listed before the site is published.</p>',
        '<h2>Fair use</h2><p>The files are served from a static host with no rate limit and no key. Please cache rather than fetch repeatedly; they change once a night.</p>',
        '<h2>Where to next</h2><nav class="rel"><a href="/statistics/">ETF statistics</a><a href="/research/">ETFIQ Research</a><a href="/standards/">Standards and sources</a><a href="/llms.txt">llms.txt</a></nav>',
    ]
    return doc_page('data/', title, desc, ''.join(parts), ld, wide=True, short='Open data')


# ---------------------------------------------------------------- hub pages: issuer, theme, reset month
def hub_page(slug, title, desc, intro, rows, head, as_of, item_names, crumb=None, desk=None, extra='', short=None, ld_extra=None, onward=''):
    url = f'{BASE}/{slug}'
    ld = (ld_extra or []) + [{'@type': 'ItemList', 'name': title, 'numberOfItems': len(item_names),
           'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': t, 'url': f'{BASE}/funds/{t}.html'} for i, t in enumerate(item_names[:100])]}]
    trs = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    inner = (f'<p class="note">Data as of {tdate(as_of)}.</p><h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>{extra}'
             f'<div style="overflow-x:auto"><table class="hub"><caption>{esc(title)}, as of {fdate(as_of)}. Source: ETFIQ.</caption><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead><tbody>{trs}</tbody></table></div>'
             + (f'<h2>Where to next</h2><nav class="rel">{onward}</nav>' if onward else '')
             + '<p class="note">ETFIQ is an independent publisher and makes no recommendations; every figure is stated arithmetic on published data. <a href="/standards/">Standards and sources</a></p>'
             + cite_line(title, as_of, url))
    return doc_page(slug, title, desc, inner, ld, desk=desk, crumb=crumb, wide=True, short=short)


# ---------------------------------------------------------------- head to head pages
# The funds people actually search for, one list per desk: the widely held names on the buffer and income desks,
# and the largest thematic funds by net assets. Every pair of them gets its own page.
BUFFER_TOP = ['PJAN', 'PAPR', 'PJUL', 'POCT', 'BJAN', 'BAPR', 'BJUL', 'BOCT', 'UJAN', 'UAPR', 'UJUL', 'UOCT', 'DJAN', 'DAPR', 'DJUL', 'DOCT', 'FJAN', 'FAPR', 'FJUL', 'FOCT',
               'PSEP', 'PNOV', 'BSEP', 'GJAN', 'PFEB', 'PMAR', 'PMAY', 'PJUN', 'PAUG', 'PDEC']
INCOME_TOP = ['JEPI', 'JEPQ', 'SPYI', 'QQQI', 'QYLD', 'XYLD', 'RYLD', 'DIVO', 'GPIX', 'GPIQ', 'TSLY', 'NVDY', 'MSTY', 'CONY', 'ULTY', 'YMAX', 'FEPI', 'XDTE', 'QDTE', 'AIPI',
               'BALI', 'ISPY', 'SVOL', 'JEPY', 'AMZY', 'APLY', 'GOOY', 'MSFO', 'OARK', 'SDTY']
PAIRS_BY_TICKER = {}
DESK_HUBS = {}


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
            f'<p>The {EMBED_LABEL[desk]} for {esc(ticker)}, redrawn every trading night. Free to use with the credit link; paste these two lines into any page or newsletter.</p>'
            f'<p><img src="/embed/{desk}/{ticker}.svg" alt="{esc(ticker)} {EMBED_LABEL[desk]}, ETFIQ" width="640" loading="lazy" style="max-width:100%;height:auto;border-radius:10px"></p>'
            f'<pre class="embed"><code>{esc(snippet)}</code></pre>')


NEIGHBOURS = {}   # (desk, ticker) -> list of (label, href), the paths off every fund page


def issuer_slug(name):
    return re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')


def build_neighbours(funds, income, themes, has_hub=None):
    """Every fund page gets somewhere to go: its issuer, its group on the desk, and its closest funds.
    Without this most pages are dead ends, which costs both readers and crawl depth."""
    MON = {'01': 'january', '02': 'february', '03': 'march', '04': 'april', '05': 'may', '06': 'june',
           '07': 'july', '08': 'august', '09': 'september', '10': 'october', '11': 'november', '12': 'december'}
    has_hub = has_hub if has_hub is not None else set()
    by_issuer = {}
    for desk, rs in (('buffer', funds), ('income', income), ('themes', themes)):
        for r in rs:
            by_issuer.setdefault(r['issuer'], []).append((desk, r['ticker']))
    def issuer_link(name):
        return [(f'All {name} funds', f'/issuers/{issuer_slug(name)}.html')] if issuer_slug(name) in has_hub else []
    fam, refs, bench, theme_of = {}, {}, {}, {}
    for f in funds:
        fam.setdefault(f.get('family') or f['name'], []).append(f['ticker'])
        refs.setdefault(f['refAsset'], []).append(f['ticker'])
    for r in income:
        bench.setdefault(r['benchmark'], []).append(r['ticker'])
    for r in themes:
        theme_of.setdefault(r['theme'], []).append(r['ticker'])
    def near(pool, t, k=5):
        i = pool.index(t) if t in pool else 0
        others = [x for x in pool if x != t]
        return others[max(0, i - k):i + k][:6]
    for f in funds:
        t, links = f['ticker'], []
        links += issuer_link(f['issuer'])
        mm = f['periodEnd'][5:7]
        if mm in MON:
            links.append((f"Buffer ETFs resetting in {MON[mm].title()}", f"/buffer/{MON[mm]}.html"))
        links += [(x, f'/funds/{x}.html') for x in near(sorted(fam.get(f.get('family') or f['name'], [])), t)]
        links += [(x, f'/funds/{x}.html') for x in near(sorted(refs.get(f['refAsset'], [])), t, 3)][:4]
        NEIGHBOURS[('buffer', t)] = links
    for r in income:
        t, links = r['ticker'], []
        links += issuer_link(r['issuer'])
        links.append((f"Every income ETF on {r['benchmark']}", f"/income/"))
        links += [(x, f'/funds/{x}.html') for x in near(sorted(bench.get(r['benchmark'], [])), t, 6)]
        NEIGHBOURS[('income', t)] = links
    for r in themes:
        t, links = r['ticker'], []
        links += issuer_link(r['issuer'])
        links.append((f"All {r['themeName'].lower()} ETFs", f"/themes/{r['theme']}.html"))
        links += [(p['t'], f"/funds/{p['t']}.html") for p in (r.get('peers') or [])[:5]]
        if len(links) < 5:
            links += [(x, f'/funds/{x}.html') for x in near(sorted(theme_of.get(r['theme'], [])), t)]
        NEIGHBOURS[('themes', t)] = links


def neighbour_links(desk, ticker):
    ls = NEIGHBOURS.get((desk, ticker)) or []
    seen, out = set(), []
    for label, href in ls:
        if href in seen:
            continue
        seen.add(href)
        out.append(f'<a href="{href}">{esc(label)}</a>')
    out.append(f'<a href="/{desk}/">Every fund on the {DESK_NAME[desk].lower()}</a>')
    return f'<h2>Funds near this one</h2><nav class="rel">{"".join(out[:12])}</nav>'


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


def any_rows(a, b, ka, kb, extra):
    """Fields both funds have, for a pair that crosses desks: what each is, what it returned, what it costs,
    and how much of it is the index."""
    def one(r, kind):
        w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
        what = {'buffer': lambda: f"Defined outcome, {r.get('bufferLabel', '')} on {r.get('refAsset')}",
                'income': lambda: f"{r.get('strategy', 'option income')}, vs {r.get('benchmark')}",
                'themes': lambda: r.get('themeName', 'thematic'),
                'core': lambda: r.get('note', 'index fund')}[kind]()
        v = r.get('vsSPY') or {}
        cash = ((r.get('windows') or {}).get('1Y') or {}).get('cash') if kind == 'income' else None
        return [{'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk', 'core': 'Core fund'}[kind],
                r.get('issuer', 'n/a'), what,
                pct(w.get('total')), pct(w.get('bench')), pts(w.get('gap')),
                pct(cash, sign=False) if cash is not None else 'not an income fund',
                pct(r.get('expenseRatio'), sign=False, d=2),
                pct(v.get('inIndex'), sign=False) if v else 'no filed book',
                str(r.get('holdingsCount') or 'n/a')]
    labels = ['Where it sits', 'Issuer', 'What it is', 'Total return, 1 year', 'S&P 500 over the same days', 'Gap to the S&P 500',
              'Cash paid, 1 year', 'Expense ratio', 'Already in the S&P 500', 'Holdings']
    ra, rb = one(a, ka), one(b, kb)
    # a field only appears when both funds publish it, so no cell has to say the figure is missing
    keep = [i for i in range(len(labels)) if not (ra[i] in ('not an income fund', 'no filed book', 'n/a') and rb[i] in ('not an income fund', 'no filed book', 'n/a'))]
    keep = [i for i in keep if not (ra[i] in ('no filed book',) or rb[i] in ('no filed book',))]
    return [labels[i] for i in keep], [ra[i] for i in keep], [rb[i] for i in keep]


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


def cmp_faqs(desk, a, b, extra, overlap, as_of=None):
    ta, tb = a['ticker'], b['ticker']
    on = fdate(as_of) if as_of else None
    dt = f' to {on}' if on else ''
    out = []
    if desk == 'income':
        wa, _ = w1(a)
        wb, _ = w1(b)
        if wa and wb:
            more = ta if wa['cash'] >= wb['cash'] else tb
            out.append((f'Which paid more, {ta} or {tb}?',
                        f'Over the year{dt}, {ta} paid {pct(wa["cash"], sign=False)} of its starting price in cash and {tb} paid {pct(wb["cash"], sign=False)}, so {more} paid more. Cash paid is not the same as money made: the price change matters too.'))
            best = ta if (wa.get('total') or -999) >= (wb.get('total') or -999) else tb
            out.append((f'Which returned more once distributions are counted, {ta} or {tb}?',
                        f'With every distribution reinvested, {ta} returned {pct(wa["total"])} and {tb} returned {pct(wb["total"])} over the year{dt}, so {best} returned more.'))
    if desk == 'buffer':
        if a.get('remainingCapFund') is not None and b.get('remainingCapFund') is not None:
            more = ta if a['remainingCapFund'] >= b['remainingCapFund'] else tb
            out.append((f'Which has more room to gain, {ta} or {tb}?',
                        f'From their prices{" on " + on if on else ""}, {ta} can gain about {pct(a["remainingCapFund"], sign=False)} before its cap and {tb} about {pct(b["remainingCapFund"], sign=False)}, so {more} has more room left this period.'))
        out.append((f'Which resets first, {ta} or {tb}?',
                    f'{ta} ends its outcome period on {fdate(a["periodEnd"])} and {tb} on {fdate(b["periodEnd"])}. A new cap is set the day after each.'))
    if desk == 'themes':
        if overlap is not None:
            word = 'close to holding one of them twice' if overlap >= 50 else 'a meaningful overlap' if overlap >= 20 else 'mostly different names'
            out.append((f'Do {ta} and {tb} hold the same stocks?',
                        f'By their latest filings, {overlap}% of their books are the same securities at the same weight, which is {word}. Overlap is the sum of the smaller weight of every security they share.'))
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
    cmp_og = f'{BASE}/embed/social/{desk}/{ta}.png' if (SITE / 'embed' / 'social' / desk / f'{ta}.png').exists() else f'{BASE}/og.png'
    faqs = cmp_faqs(desk, a, b, extra, overlap, as_of)
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
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg"><link rel="alternate" type="application/rss+xml" title="ETFIQ" href="/feed.xml">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{cmp_og}"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}</style></head>
<body>{R.rail(desk)}<main>
{crumb_html([('ETFIQ', BASE + '/'), (DESK_NAME[desk], f'{BASE}/{desk}/'), ('Head to head', f'{BASE}/compare/'), (f'{ta} vs {tb}', url)])}
<p class="note">Data as of {tdate(as_of)}. Every figure is the {DESK_NAME[desk].lower()}'s own, on published data.</p>
<h1>{esc(ta)} vs {esc(tb)}</h1><p class="lede">{esc(a['name'])} and {esc(b['name'])}, side by side on the {DESK_NAME[desk].lower()}.</p>
{ov}
<a class="cta" href="{BASE}/#/{desk}/compare/{ta},{tb}">Open the live comparison on ETFIQ</a>
<table class="cmp"><caption>{esc(ta)} and {esc(tb)} on the {esc(DESK_NAME[desk].lower())} fields, as of {fdate(as_of)}. Source: ETFIQ.</caption><thead>{head}</thead><tbody>{body}</tbody></table>
<h2>{esc(ta)} in plain words</h2><p>{esc(words_a)}</p>
<h2>{esc(tb)} in plain words</h2><p>{esc(words_b)}</p>
{faq_html}
{'<h2>Other comparisons</h2><nav class="rel">' + rel + '</nav>' if rel else ''}
{cite_line(ta + ' against ' + tb, as_of, url)}
<p class="note">ETFIQ is an independent publisher of exchange-traded fund data. It is not a fund issuer, broker-dealer or investment adviser, and it makes no recommendations; every figure here is stated arithmetic on published data. <a href="{BASE}/standards/">Standards and sources</a></p>
</main>{R.footer()}</body></html>"""


# ---------------------------------------------------------------- page shell
DESK_NAME = {'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk'}
STYLE = R.RAIL_CSS + R.FOOTER_CSS + """pre.embed{background:#0F1419;color:#E6EAF0;padding:14px 16px;border-radius:10px;overflow-x:auto;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-all}dl.faq{margin:0 0 8px}dl.faq dt{font-weight:600;margin:18px 0 6px}dl.faq dd{margin:0;color:#3B434F}nav.rel{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 6px}nav.rel a{border:1px solid #D9DEE6;border-radius:999px;padding:6px 12px;background:#fff;font-size:13.5px;text-decoration:none;color:#0F1419}nav.rel a:hover{border-color:#2457E6}nav.rel.out a::after{content:' \\2197';color:#5A6472}thead th .sub{font-weight:400;font-size:12px;color:#5B6572;margin-top:4px;max-width:220px}body{margin:0;background:#F5F7FA;color:#0F1419;font:15px/1.5 Geist,system-ui,-apple-system,'Segoe UI',sans-serif}main{max-width:820px;margin:0 auto;padding:28px 20px 60px}h1{font-size:28px;letter-spacing:-.02em;margin:18px 0 6px}.lede{color:#3D4756;font-size:16px}.tk{font-family:'Geist Mono',ui-monospace,monospace;font-weight:600}.cta{display:inline-block;margin:14px 0 22px;padding:10px 16px;background:#2457E6;color:#fff;border-radius:6px;text-decoration:none;font-weight:600}table{border-collapse:collapse;width:100%;margin:12px 0 18px;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #DCE1E8;vertical-align:top}th{color:#3D4756;font-weight:500}table.kv tbody th{width:42%}table.cmp tbody th{width:26%;white-space:normal}table.cmp thead th{width:37%}main.doc.wide{max-width:1120px}nav.list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:12px;margin:14px 0 20px}nav.list a{display:block;padding:16px 18px;border:1px solid #D9DEE6;border-radius:10px;background:#fff;text-decoration:none;color:#0F1419}nav.list a:hover{border-color:#2457E6}nav.list a .lvl{display:block;font:600 10.5px/1 Geist,system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#2457E6;margin-bottom:8px}nav.list a b{display:block;font-size:16px;line-height:1.3;letter-spacing:-.01em;margin-bottom:6px}nav.list a span{display:block;color:#3D4756;font-size:13.5px;line-height:1.45}table.pairs td{white-space:normal}table.pairs td:last-child{display:flex;flex-wrap:wrap;gap:5px}table.pairs td a{display:inline-block;padding:3px 8px;border:1px solid #DCE1E8;border-radius:999px;font-size:12px;white-space:nowrap;text-decoration:none;color:#0F1419;background:#fff}table.pairs td a:hover{border-color:#2457E6}table.pairs td .more{color:#5A6472;font-size:12px;align-self:center}.filterbox{display:flex;gap:8px;max-width:460px;margin:8px 0 16px}.filterbox input{flex:1;padding:10px 12px;border:1px solid #C3CBD6;border-radius:8px;font:14px Geist,system-ui,sans-serif}nav.crumb{font-size:12.5px;color:#5A6472;margin:2px 0 14px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}nav.crumb a{color:#2457E6;text-decoration:none}nav.crumb a:hover{text-decoration:underline}nav.crumb b{color:#C3CBD6;font-weight:400}nav.crumb span{color:#12161C;font-weight:600}table.hub th:first-child,table.hub td:first-child{width:70px;white-space:nowrap}table.hub th:nth-child(3),table.hub td:nth-child(3){width:86px}table.hub td:nth-child(2){min-width:210px}table.hub td,table.hub th{white-space:normal}table.hub .tk{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600}.note{color:#5B6675;font-size:13px}nav.desks a{margin-right:14px}footer{margin-top:40px;color:#5B6675;font-size:13px}"""


def faq_block(faqs):
    """A question and answer list in the words people search, from figures already on the page."""
    if not faqs:
        return '', []
    html_ = '<h2>Questions people ask</h2><dl class="faq">' + ''.join(f'<dt>{esc(q)}</dt><dd>{esc(a)}</dd>' for q, a in faqs) + '</dl>'
    ld = [{'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faqs]}]
    return html_, ld


ISSUER_SITE = {
    'Innovator': 'https://www.innovatoretfs.com/', 'First Trust': 'https://www.ftportfolios.com/', 'YieldMax': 'https://www.yieldmaxetfs.com/',
    'AllianzIM': 'https://www.allianzim.com/', 'Global X': 'https://www.globalxetfs.com/', 'GraniteShares': 'https://graniteshares.com/',
    'iShares': 'https://www.ishares.com/', 'Amplify': 'https://amplifyetfs.com/', 'Defiance': 'https://www.defianceetfs.com/',
    'Invesco': 'https://www.invesco.com/', 'State Street': 'https://www.ssga.com/', 'REX': 'https://www.rexshares.com/',
    'Roundhill': 'https://www.roundhillinvestments.com/', 'NEOS': 'https://neosfunds.com/', 'VanEck': 'https://www.vaneck.com/',
    'Kurv': 'https://kurvinvest.com/', 'ProShares': 'https://www.proshares.com/', 'VistaShares': 'https://vistashares.com/',
    'WisdomTree': 'https://www.wisdomtree.com/', 'Fidelity': 'https://www.fidelity.com/etfs/overview',
    'KraneShares': 'https://kraneshares.com/', 'Bitwise': 'https://bitwiseinvestments.com/', 'ARK': 'https://ark-funds.com/',
    'Direxion': 'https://www.direxion.com/', 'Grayscale': 'https://www.grayscale.com/', 'JPMorgan': 'https://am.jpmorgan.com/us/en/asset-management/adv/products/etf/',
    'Vanguard': 'https://investor.vanguard.com/investment-products/etfs', 'Schwab': 'https://www.schwabassetmanagement.com/',
    'Franklin': 'https://www.franklintempleton.com/', 'Sprott': 'https://sprottetfs.com/', 'Xtrackers': 'https://etf.dws.com/',
    'TrueShares': 'https://www.true-shares.com/', 'Calamos': 'https://www.calamos.com/', 'Nationwide': 'https://etf.nationwidefinancial.com/',
    'Tuttle': 'https://www.tuttlecap.com/', 'Aptus': 'https://aptusetfs.com/', 'Westwood': 'https://westwoodgroup.com/',
    'PGIM': 'https://www.pgim.com/', 'Janus': 'https://www.janushenderson.com/', 'Simplify': 'https://www.simplify.us/',
    'Goldman Sachs': 'https://www.gsam.com/', 'BlackRock': 'https://www.blackrock.com/', 'Pacer': 'https://www.paceretfs.com/',
    'SoFi': 'https://www.sofi.com/invest/', 'Tema': 'https://www.temaetfs.com/', 'Themes': 'https://themesetfs.com/',
    'Nicholas': 'https://nicholasetfs.com/', 'TappAlpha': 'https://www.tappalpha.com/', 'Tortoise': 'https://tortoiseecofin.com/',
}


STATIC_FOR = {'#/buffer/desk': '/buffer/', '#/buffer/entry': '/buffer/', '#/buffer/ladder': '/buffer/', '#/income/desk': '/income/', '#/income/ahead': '/income/',
              '#/income/calendar': '/income/', '#/themes/desk': '/themes/', '#/themes/themes': '/themes/', '#/portfolio': '/portfolio/'}


def sources_block(items):
    """Links to the documents a figure came from. An independent publisher should send the reader to the primary
    source, and a page that does is easier for a reader, a journalist or a model to verify."""
    links = [f'<a href="{u}" rel="noopener" target="_blank">{esc(lab)}</a>' for lab, u in items if u]
    if not links:
        return ''
    return ('<h2>Where these figures came from</h2><nav class="rel out">' + ''.join(links) + '</nav>'
            '<p class="note">ETFIQ links to the documents behind every figure. It is not affiliated with any issuer, and a link is not an endorsement.</p>')


def crumb_html(items):
    """The visible trail, from the same list the breadcrumb markup uses."""
    if not items:
        return ''
    parts = [f'<a href="{u}">{esc(nm)}</a>' for nm, u in items[:-1]] + [f'<span>{esc(items[-1][0])}</span>']
    return '<nav class="crumb">' + ' <b>/</b> '.join(parts) + '</nav>'


def crumbs(items):
    return {'@type': 'BreadcrumbList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': nm, 'item': u} for i, (nm, u) in enumerate(items)]}


def page(title, desc, ticker, name, issuer, desk, as_of, words, rows, app_url, method, faqs=None, related='', sources='', cik=None, filings=None):
    url = f"{BASE}/funds/{ticker}.html"
    og = f'{BASE}/embed/social/{desk}/{ticker}.png' if (SITE / 'embed' / 'social' / desk / f'{ticker}.png').exists() else f'{BASE}/og.png'
    faq_html, faq_ld = faq_block(faqs or [])
    ld = {'@context': 'https://schema.org', '@graph': faq_ld + [crumbs([('ETFIQ', BASE + '/'), (DESK_NAME[desk], f'{BASE}/{desk}/'), (ticker, url)])] + [
        {'@type': 'FinancialProduct', 'name': name, 'alternateName': ticker, 'url': url, 'category': f'Exchange-traded fund, {DESK_NAME[desk].lower()}',
         'identifier': [{'@type': 'PropertyValue', 'propertyID': 'tickerSymbol', 'value': ticker}] + ([{'@type': 'PropertyValue', 'propertyID': 'secCik', 'value': str(cik)}] if cik else []),
         'provider': dict({'@type': 'Organization', 'name': issuer}, **({'sameAs': [ISSUER_SITE[issuer]]} if ISSUER_SITE.get(issuer) else {})),
         'sameAs': [u for u in [f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=485' if cik else None, ISSUER_SITE.get(issuer)] if u]},
        dict({'@type': 'Dataset', 'name': f'ETFIQ {DESK_NAME[desk].lower()} record for {ticker}', 'description': desc, 'dateModified': as_of, 'creator': {'@type': 'Organization', 'name': 'ETFIQ', 'url': BASE}, 'license': f'{BASE}/standards/', 'isAccessibleForFree': True, 'url': url}, **({'citation': [{'@type': 'CreativeWork', 'url': u} for u in filings]} if filings else {})),
        {'@type': 'WebPage', 'name': title, 'description': desc, 'url': url, 'dateModified': as_of, 'isPartOf': {'@type': 'WebSite', 'name': 'ETFIQ', 'url': BASE}}]}
    trs = ''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in rows)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg"><link rel="alternate" type="application/rss+xml" title="ETFIQ" href="/feed.xml">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{og}"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}</style></head>
<body>{R.rail(desk)}<main>
{crumb_html([('ETFIQ', BASE + '/'), (DESK_NAME[desk], f'{BASE}/{desk}/'), (ticker, url)])}
<p class="note">Data as of {tdate(as_of)}. {esc(method)}</p>
<h1><span class="tk">{esc(ticker)}</span> · {esc(name)}</h1><p class="lede">{esc(issuer)} · {DESK_NAME[desk]}</p>
<a class="cta" href="{app_url}">Open the live card on ETFIQ</a>
<p>{esc(words)}</p>
<table class="kv"><caption>{esc(ticker)} ({esc(name)}), {esc(DESK_NAME[desk].lower())} fields as of {fdate(as_of)}. Source: ETFIQ.</caption><tbody>{trs}</tbody></table>
{faq_html}
{sources}
{related}
{cite_line(ticker + ' on the ' + DESK_NAME[desk].lower(), as_of, url)}
<p class="note">ETFIQ is an independent publisher of exchange-traded fund data. It is not a fund issuer, broker-dealer or investment adviser, and it makes no recommendations; sort orders and figures are stated arithmetic on published data. <a href="{BASE}/standards/">Standards</a> · <a href="{BASE}/#/{desk}/learn">How to read this desk</a></p>
</main>{R.footer()}</body></html>"""


def index_page(desk, rows, as_of, intro, hub_nav=''):
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
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(intro)}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg"><link rel="alternate" type="application/rss+xml" title="ETFIQ" href="/feed.xml">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}main{{max-width:1100px}}th,td{{white-space:nowrap}}th{{width:auto}}</style></head>
<body>{R.rail(desk)}<main>
{crumb_html([('ETFIQ', BASE + '/'), (DESK_NAME[desk], url)])}
<p class="note">Data as of {fdate(as_of)}.</p><h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>
<a class="cta" href="{BASE}/#/{desk}/desk">Open the live desk on ETFIQ</a>
{hub_nav}
<div style="overflow-x:auto"><table><thead><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr></thead><tbody>{trs}</tbody></table></div>
<h2>Where to next</h2><nav class="rel"><a href="/rankings/">Rankings on this desk</a><a href="/compare/">Compare two funds</a><a href="/issuers/">By issuer</a><a href="/questions/">Questions</a><a href="/learn/{desk}.html">The vocabulary</a></nav>
<p class="note">ETFIQ is an independent publisher. It makes no recommendations; every list is stated arithmetic on published data. <a href="{BASE}/standards/">Standards</a></p>
</main>{R.footer()}</body></html>"""


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
<title>{esc(title)} | ETFIQ</title><meta name="description" content="{esc(intro[:300])}"><link rel="canonical" href="{url}"><link rel="icon" href="/favicon.svg"><link rel="alternate" type="application/rss+xml" title="ETFIQ" href="/feed.xml">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(intro[:300])}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}/og.png">
<script type="application/ld+json">{json.dumps(ld, separators=(',', ':'))}</script><style>{STYLE}main{{max-width:820px}}</style></head>
<body>{R.rail('portfolio')}<main>
<p class="note">Books as of {fdate(as_of)}: {books} funds with filed holdings.</p>
<h1>{esc(title)}</h1><p class="lede">{esc(intro)}</p>
<a class="cta" href="{BASE}/#/portfolio">Open the Portfolio desk on ETFIQ</a>
<h2>Five views</h2><table class="kv"><tbody>{''.join(f'<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>' for a, b in views)}</tbody></table>
<h2>Try an example</h2><p>{' · '.join(f'<a href="{BASE}/#/portfolio/own/{sp}">{esc(l)}</a>' for sp, l in examples)}</p>
<h2>Where to next</h2><nav class="rel"><a href="{BASE}/#/portfolio">Open the Portfolio desk</a><a href="/core/">Core index funds</a><a href="/compare/">Head to head</a><a href="/rankings/">Rankings</a></nav>
<h2>How positions are written</h2><p>Tickers with a weight (PJAN:20), a share count (JEPI:150S) or a dollar amount (JEPI:$25000), separated by commas. Any fund on the buffer, income or themes desk, plus the core index funds. The link carries the positions, so a portfolio can be shared or bookmarked; named portfolios can be kept on the device.</p>
<p class="note">Books come from each fund's latest SEC N-PORT filing or the issuer's daily file, dated on the desk. Buffer funds enter the look-through as their reference index; synthetic income funds as the stock or index they write options on; a fund with no filing yet stands in as the stock or index in its name; all labelled. ETFIQ is an independent publisher and makes no recommendations or allocation suggestions. <a href="{BASE}/standards/">Standards</a></p>
</main>{R.footer()}</body></html>"""


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
           'themes': [r['ticker'] for r in sorted(themes, key=lambda r: -(r.get('assets') or 0)) if r.get('vsSPY')][:30]}
    # the hub links each desk index page carries, worked out before any page is written
    MONS = {'01': 'January', '02': 'February', '03': 'March', '04': 'April', '05': 'May', '06': 'June', '07': 'July', '08': 'August', '09': 'September', '10': 'October', '11': 'November', '12': 'December'}
    theme_keys = sorted({(r['theme'], r['themeName']) for r in themes})
    month_keys = sorted({f['periodEnd'][5:7] for f in funds})
    DESK_HUBS['themes'] = ('<h2>Browse by theme</h2><nav class="rel">' + ''.join(f'<a href="/themes/{k}.html">{esc(n)}</a>' for k, n in theme_keys) + '<a href="/issuers/">By issuer</a><a href="/rankings/">Rankings</a></nav>')
    DESK_HUBS['buffer'] = ('<h2>Browse by reset month</h2><nav class="rel">' + ''.join(f'<a href="/buffer/{MONS[m].lower()}.html">{MONS[m]}</a>' for m in month_keys if m in MONS) + '<a href="/issuers/">By issuer</a><a href="/rankings/">Rankings</a></nav>')
    DESK_HUBS['income'] = '<h2>Browse</h2><nav class="rel"><a href="/issuers/">Every issuer</a><a href="/compare/">Head to head</a><a href="/rankings/">Rankings</a><a href="/learn/income.html">The vocabulary</a></nav>'
    _by_issuer = {}
    for _d, _rs in (('buffer', funds), ('income', income), ('themes', themes)):
        for _r in _rs:
            _by_issuer.setdefault(_r['issuer'], 0)
            _by_issuer[_r['issuer']] += 1
    HUB_SLUGS = {issuer_slug(k) for k, v in _by_issuer.items() if v >= 2}
    build_neighbours(funds, income, themes, HUB_SLUGS)
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
    FEES.update(load('data/fees.json', {}))
    matrix = load('site/data/thematic.json', {}).get('matrix')
    core = load('site/data/core.json', [])
    as_c = load('site/data/core_meta.json', {}).get('asOf', max(as_b, as_i, as_t))
    core_rows, core_written = [], []
    for r in core:
        t = r['ticker']
        if (out / f'{t}.html').exists():
            continue  # a fund already on a desk keeps its desk page
        nb = ('<h2>Funds near this one</h2><nav class="rel">'
              + ''.join(f'<a href="/funds/{o}.html">{o}</a>' for o in [x['ticker'] for x in core if x['ticker'] != t and x['kind'] == r['kind']][:6])
              + '<a href="/core/">Every core fund</a><a href="/portfolio/">Portfolio desk</a></nav>')
        (out / f'{t}.html').write_text(core_page(r, as_c, nb))
        urls.append((f'{BASE}/funds/{t}.html', as_c))
        core_written.append(t)
        w = (r.get('windows') or {}).get('1Y') or {}
        core_rows.append([f'<a href="/funds/{t}.html" class="tk">{t}</a>', esc(r['name']), esc(r['kindLabel']), esc(r['note']),
                          pct(w.get('total')), pts(w.get('gap')), pct(r.get('expenseRatio'), sign=False, d=2),
                          str(r.get('holdingsCount') or '')])
    if core_rows:
        (SITE / 'core').mkdir(exist_ok=True)
        (SITE / 'core' / 'index.html').write_text(hub_page(
            'core/', 'Core index funds: the funds the desks measure against',
            f'{len(core_rows)} index, bond, commodity and digital asset funds with returns against the S&P 500 and the Nasdaq-100, fees and filed holdings.',
            f'{len(core_rows)} funds, on the same fields and the same windows as the three desks. They are here because the desks measure against them and portfolios hold them.',
            core_rows, ['Ticker', 'Fund', 'Type', 'Tracks', 'Total return 1Y', 'vs S&P 500', 'Fee', 'Holdings'], as_c, core_written, short='Core funds',
            onward='<a href="/compare/">Compare two funds</a><a href="/portfolio/">Look a portfolio through</a><a href="/income/">Income ETFs measured against these</a>'))
        urls.append((f'{BASE}/core/', as_c))
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
        (d / 'index.html').write_text(index_page(desk, rows, as_of, intro, hub_nav=DESK_HUBS.get(desk, ''))); urls.append((f'{BASE}/{desk}/', as_of))
    # explainers, standards and the old site's paths
    for rel, html_ in learn_pages():
        fp = SITE / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(html_)
        urls.append((f'{BASE}/{rel}'.replace('/index.html', '/'), TODAY))
    (SITE / 'standards').mkdir(exist_ok=True)
    (SITE / 'standards' / 'index.html').write_text(standards_page())
    urls.append((f'{BASE}/standards/', TODAY))
    (SITE / '404.html').write_text(not_found_page())
    for slug, fn in (('privacy', privacy_page), ('terms', terms_page), ('contact', contact_page)):
        (SITE / slug).mkdir(exist_ok=True)
        (SITE / slug / 'index.html').write_text(fn())
        urls.append((f'{BASE}/{slug}/', TODAY))
    for old_path, target in (('about', '/standards/'), ('blog', '/research/'), ('services', '/'), ('hello-world', '/')):
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
                    figure = 'uncapped' if r.get('isUncapped') else (pct(r['remainingCapFund'], sign=False) + ' left to the cap' if r.get('remainingCapFund') is not None else 'no figure published')
                elif desk == 'income':
                    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD') or {}
                    detail = f"{esc(r.get('strategy', ''))}, vs {esc(r['benchmark'])}"
                    figure = f"paid {pct(w['cash'], sign=False)}, total {pct(w['total'])}" if w.get('cash') is not None else 'no return figures yet'
                else:
                    v = r.get('vsSPY') or {}
                    detail = esc(r['themeName'])
                    figure = f"{pct(v['inIndex'], sign=False)} already in the S&P 500" if v.get('inIndex') is not None else 'no holdings filing yet'
                rows.append([f'<a href="/funds/{r["ticker"]}.html" class="tk">{esc(r["ticker"])}</a>', esc(r['name']), DESK_NAME[desk].split()[0], detail, figure])
        kinds = [k for k in ('buffer', 'income', 'themes') if desks.get(k)]
        words = {'buffer': 'buffer', 'income': 'income', 'themes': 'thematic'}
        kind_words = ', '.join(words[k] for k in kinds[:-1]) + (' and ' if len(kinds) > 1 else '') + words[kinds[-1]]
        title = f'{issuer} {kind_words} ETFs'
        counts = ', '.join(f'{len(desks[k])} {words[k]}' for k in kinds)
        intro = f'{counts}, on the same fields as their desks. ETFIQ covers buffer, option-income and thematic ETFs; an issuer\'s other funds are not here.'
        site_link = ISSUER_SITE.get(issuer)
        extra_html = (f'<nav class="rel out"><a href="{site_link}" rel="noopener" target="_blank">{esc(issuer)} website</a></nav>' if site_link else '')
        desc = f'{issuer}: the {total} {kind_words} ETFs ETFIQ covers ({counts}), with current figures.'
        org_ld = [{'@type': 'Organization', 'name': issuer, 'url': f'{BASE}/issuers/{slug}.html'}]
        if site_link:
            org_ld[0]['sameAs'] = [site_link]
        (SITE / 'issuers' / f'{slug}.html').write_text(hub_page(f'issuers/{slug}.html', title, desc, intro, rows,
                                                               ['Ticker', 'Fund', 'Desk', 'What it is', 'Where it stands'], max(as_b, as_i, as_t), names,
                                                               crumb=[('Browse', f'{BASE}/#/browse'), ('Issuers', f'{BASE}/issuers/')], short=issuer, extra=extra_html, ld_extra=org_ld,
                                                               onward=''.join(f'<a href="/{k}/">Every {w} ETF</a>' for k, w in (('buffer', 'buffer'), ('income', 'income'), ('themes', 'thematic')) if desks.get(k))
                                                                       + '<a href="/compare/">Compare two funds</a><a href="/rankings/">Rankings</a><a href="/issuers/">Every issuer</a>'))
        urls.append((f'{BASE}/issuers/{slug}.html', max(as_b, as_i, as_t)))
        issuer_rows.append([f'<a href="/issuers/{slug}.html">{esc(issuer)}</a>', str(total), counts])
        hubs += 1
    (SITE / 'issuers' / 'index.html').write_text(hub_page('issuers/', 'Every ETF issuer ETFIQ covers',
                                                          'Buffer, option-income and thematic ETF issuers covered by ETFIQ, with fund counts per desk.',
                                                          f'{len(issuer_rows)} issuers. Every fund is treated identically on its desk.', sorted(issuer_rows, key=lambda r: -int(r[1])),
                                                          ['Issuer', 'Funds', 'Desks'], max(as_b, as_i, as_t), [],
                                                          onward='<a href="/rankings/">Rankings</a><a href="/compare/">Compare two funds</a><a href="/statistics/">ETF statistics</a>'))
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
        intro = (f'{len(rs)} funds, measured by holdings rather than by name'
                 + (f'. The typical fund carries {med:.0f}% of its weight in S&P 500 names.' if med is not None else '.'))
        desc = f'{len(rs)} {name.lower()} ETFs compared by holdings overlap with the S&P 500, active share, one-year return and fee.'
        (SITE / 'themes' / f'{key}.html').write_text(hub_page(f'themes/{key}.html', title, desc, intro, rows,
                                                              ['Ticker', 'Fund', 'Issuer', 'In the S&P 500', 'Active share', 'Total return 1Y', 'vs S&P 500', 'Fee'], as_t, names,
                                                              crumb=[('Browse', f'{BASE}/#/browse/theme'), ('Themes desk', f'{BASE}/themes/')], desk='themes', short=name,
                                                              onward='<a href="/themes/">Every thematic ETF</a><a href="/rankings/themes-most-index.html">Which are mostly the index</a>'
                                                                      '<a href="/compare/">Compare two funds</a><a href="/learn/themes.html">The vocabulary</a>'))
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
        intro = f'{len(fs)} defined outcome ETFs whose period ends in {MON[mm]}, when the options expire and a new cap is struck.'
        desc = f'{len(fs)} buffer ETFs with a {MON[mm]} reset: current cap room, fall before the buffer and state today, every issuer on one page.'
        (SITE / 'buffer' / f'{MON[mm].lower()}.html').write_text(hub_page(f'buffer/{MON[mm].lower()}.html', title, desc, intro, rows,
                                                                         ['Ticker', 'Fund', 'Issuer', 'Index', 'Buffer', 'Period ends', 'Can still gain', 'Fall before buffer', 'State'], as_b, names,
                                                                         crumb=[('Browse', f'{BASE}/#/browse/month'), ('Buffer desk', f'{BASE}/buffer/')], desk='buffer', short=f'{MON[mm]} resets',
                                                                         onward='<a href="/buffer/">Every buffer ETF</a><a href="/rankings/buffer-most-room-to-cap.html">Most room to the cap</a>'
                                                                                 '<a href="/compare/">Compare two funds</a><a href="/learn/buffer.html">The vocabulary</a>'))
        urls.append((f'{BASE}/buffer/{MON[mm].lower()}.html', as_b))
        hubs += 1
    # ranked lists, one published field each
    rdir = SITE / 'rankings'
    rdir.mkdir(exist_ok=True)
    for old_r in rdir.glob('*.html'):
        old_r.unlink()
    ranks = rankings(funds, income, themes, core, as_b, as_i, as_t, matrix, sources)
    for slug, title, html_ in ranks:
        (rdir / f'{slug}.html').write_text(html_)
        urls.append((f'{BASE}/rankings/{slug}.html', max(as_b, as_i, as_t)))
    (rdir / 'index.html').write_text(rankings_index(ranks, max(as_b, as_i, as_t)))
    urls.append((f'{BASE}/rankings/', max(as_b, as_i, as_t)))
    # question pages and the statistics page
    (SITE / 'questions').mkdir(exist_ok=True)
    for old_q in (SITE / 'questions').glob('*.html'):
        old_q.unlink()
    qs = question_pages(funds, income, themes, core, as_b, as_i, as_t)
    qmeta = []
    for slug, html_ in qs:
        (SITE / 'questions' / f'{slug}.html').write_text(html_)
        urls.append((f'{BASE}/questions/{slug}.html', max(as_b, as_i, as_t)))
        qmeta.append(slug)
    ins_lines = load('site/data/insights.json', {'lines': []}).get('lines') or []
    (SITE / 'questions' / 'index.html').write_text(questions_index([(sl, ti) for sl, ti in Q_TITLES], max(as_b, as_i, as_t)))
    urls.append((f'{BASE}/questions/', max(as_b, as_i, as_t)))
    (SITE / 'statistics').mkdir(exist_ok=True)
    (SITE / 'statistics' / 'index.html').write_text(stats_page(funds, income, themes, core, as_b, as_i, as_t,
                                                               ' '.join(esc(l['text']) for l in ins_lines[:4]) or 'Rebuilt nightly.'))
    urls.append((f'{BASE}/statistics/', max(as_b, as_i, as_t)))
    # the open data page
    _books = load('site/data/books/index.json', {'books': {}}).get('books', {})
    counts_line = f'{len(funds)} buffer ETFs, {len(income)} option-income ETFs and {len(themes)} thematic ETFs, with filed holdings books for {sum(1 for v in _books.values() if v.get("n"))} funds.'
    (SITE / 'data').mkdir(exist_ok=True)
    (SITE / 'data' / 'index.html').write_text(data_page(max(as_b, as_i, as_t), counts_line))
    urls.append((f'{BASE}/data/', max(as_b, as_i, as_t)))
    # what changed today
    ins = load('site/data/insights.json', {'lines': [], 'asOf': max(as_b, as_i, as_t)})
    lines = ins.get('lines') or []
    if lines:
        secs = ''
        for d in ('buffer', 'income', 'themes'):
            ls = [l for l in lines if l.get('desk') == d]
            if ls:
                secs += f'<h2><a href="/{d}/">{DESK_NAME[d]}</a></h2><ul>' + ''.join(f'<li>{esc(l["text"])} <a href="{STATIC_FOR.get(l.get("href"), "/" + d + "/")}">see the desk</a></li>' for l in ls) + '</ul>'
        ld = [{'@type': 'ItemList', 'name': f'What changed on ETFIQ, {ins.get("asOf")}', 'numberOfItems': len(lines),
               'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': l['text']} for i, l in enumerate(lines)]}]
        inner = (f'<p class="note">Computed from the desks\' own files on {fdate(ins.get("asOf"))}. Rebuilt every trading night.</p>'
                 f'<h1>What changed, {fdate(ins.get("asOf"))}</h1>'
                 '<p class="lede">Every line is counted from the published data that morning. None is a view on any fund.</p>'
                 + secs + '<h2>Where to next</h2><nav class="rel"><a href="/buffer/">All buffer ETFs</a><a href="/income/">All income ETFs</a><a href="/themes/">All thematic ETFs</a><a href="/research/">ETFIQ Research</a></nav>')
        (SITE / 'changed').mkdir(exist_ok=True)
        (SITE / 'changed' / 'index.html').write_text(doc_page('changed/', f'What changed in buffer, income and thematic ETFs, {fdate(ins.get("asOf"))}',
                                                              f'Counted from the published data on {fdate(ins.get("asOf"))}: caps reached, buffers working, funds ahead of their benchmark, themes against the index.', inner, ld))
        urls.append((f'{BASE}/changed/', ins.get('asOf') or TODAY))
    words = {'buffer': lambda f: buffer_words(f, as_b)[0], 'income': lambda r: income_words(r, sources.get(r['ticker']), as_i)[0], 'themes': lambda r: theme_words(r, as_t)[0]}
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
    # comparisons across desks, and among the core funds people already own
    core_by = {r['ticker']: r for r in core}
    kinds = {}
    for d, rs in (('buffer', funds), ('income', income), ('themes', themes)):
        for r in rs:
            kinds.setdefault(r['ticker'], (d, r))
    for t, r in core_by.items():
        kinds.setdefault(t, ('core', r))
    core_top = [t for t in CORE_TOP if t in core_by]
    x_pairs = []
    for i, ta in enumerate(core_top):          # every pair of the funds people already hold
        for tb in core_top[i + 1:]:
            x_pairs.append((ta, tb))
    CROSS = {'income': ['VOO', 'SPY', 'QQQ', 'SCHD', 'VTI'], 'themes': ['VOO', 'QQQ', 'VTI'], 'buffer': ['VOO', 'SPY']}
    for desk, cores in CROSS.items():          # a desk fund against the plain fund it is an alternative to
        for t in top[desk]:
            for c in cores:
                if c in core_by and t != c:
                    x_pairs.append((t, c))
    x_pairs = sorted({tuple(sorted(p)) for p in x_pairs})
    xdir = SITE / 'compare' / 'any'
    if xdir.exists():
        for old_x in xdir.glob('*.html'):
            old_x.unlink()
    xdir.mkdir(parents=True, exist_ok=True)
    x_by_ticker = {}
    for ta, tb in x_pairs:
        x_by_ticker.setdefault(ta, []).append(tb)
        x_by_ticker.setdefault(tb, []).append(ta)
    nx = 0
    for ta, tb in x_pairs:
        if ta not in kinds or tb not in kinds:
            continue
        ka, a = kinds[ta]
        kb, b = kinds[tb]
        wf = {'buffer': lambda r: buffer_words(r, as_b)[0], 'income': lambda r: income_words(r, sources.get(r['ticker']), as_i)[0],
              'themes': lambda r: theme_words(r, as_t)[0], 'core': lambda r: core_words(r, as_c)}
        rel = [tuple(sorted((ta, o))) for o in x_by_ticker.get(ta, [])[:4] if o != tb] + [tuple(sorted((tb, o))) for o in x_by_ticker.get(tb, [])[:4] if o != ta]
        html_ = x_cmp_page(a, b, ka, kb, max(as_b, as_i, as_t), matrix, wf[ka](a), wf[kb](b), rel)
        (xdir / f'{pair_slug(ta, tb)}.html').write_text(html_)
        urls.append((f'{BASE}/compare/any/{pair_slug(ta, tb)}.html', max(as_b, as_i, as_t)))
        nx += 1
    where = {'buffer': 'Buffer desk', 'income': 'Income desk', 'themes': 'Themes desk', 'core': 'Core fund'}
    cmp_rows_idx = {}
    for desk, ts in top.items():
        for i2, ta in enumerate(ts):
            for tb in ts[i2 + 1:]:
                for x, y in ((ta, tb), (tb, ta)):
                    cmp_rows_idx.setdefault(x, []).append((y, f'/compare/{desk}/{pair_slug(x, y)}.html'))
    for ta, tb in x_pairs:
        for x, y in ((ta, tb), (tb, ta)):
            cmp_rows_idx.setdefault(x, []).append((y, f'/compare/any/{pair_slug(x, y)}.html'))
    idx_rows = []
    for t in sorted(cmp_rows_idx):
        k, r = kinds.get(t, (None, None))
        if not r:
            continue
        seen2, links = set(), []
        for other, u in sorted(cmp_rows_idx[t]):
            if other in seen2:
                continue
            seen2.add(other)
            links.append(f'<a href="{u}">vs {esc(other)}</a>')
        shown, rest = links[:12], len(links) - 12
        if rest > 0:
            shown.append(f'<span class="more">and {rest} more on <a href="/funds/{t}.html">the {esc(t)} page</a></span>')
        idx_rows.append((t, r.get('name', ''), where.get(k, ''), shown))
    (SITE / 'compare' / 'index.html').write_text(compare_index(idx_rows, max(as_b, as_i, as_t)))
    urls.append((f'{BASE}/compare/', max(as_b, as_i, as_t)))
    bidx = load('site/data/books/index.json', {'asOf': max(as_b, as_i, as_t), 'books': {}})
    (SITE / 'portfolio').mkdir(exist_ok=True)
    (SITE / 'portfolio' / 'index.html').write_text(portfolio_page(bidx.get('asOf') or max(as_b, as_i, as_t), sum(1 for v in bidx.get('books', {}).values() if v.get('n'))))
    urls.append((f'{BASE}/portfolio/', bidx.get('asOf') or max(as_b, as_i, as_t)))
    for r in sorted((SITE / 'research').glob('*.html')) if (SITE / 'research').exists() else []:
        urls.append((f'{BASE}/research/' + ('' if r.name == 'index.html' else r.name), max(as_b, as_i, as_t)))
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + f'<url><loc>{BASE}/</loc><lastmod>{max(as_b, as_i, as_t)}</lastmod></url>\n' + ''.join(f'<url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n' for u, d in urls) + '</urlset>\n'
    feed_items = []
    ins_all = load('site/data/insights.json', {'lines': [], 'asOf': max(as_b, as_i, as_t)})
    if ins_all.get('lines'):
        day = ins_all.get('asOf') or TODAY
        feed_items.append((f'What changed, {fdate(day)}', f'{BASE}/changed/', day,
                           ' '.join(l['text'] for l in ins_all['lines'][:6])))
    for rp in sorted((SITE / 'research').glob('*.html')):
        if rp.name == 'index.html':
            continue
        m = re.search(r'<h1>(.*?)</h1>', rp.read_text())
        d2 = re.search(r'<div class="sum"><p>(.*?)</p>', rp.read_text())
        feed_items.append((re.sub(r'<[^>]+>', '', m.group(1)) if m else rp.stem,
                           f'{BASE}/research/{rp.name}', max(as_b, as_i, as_t),
                           re.sub(r'<[^>]+>', '', d2.group(1))[:400] if d2 else 'ETFIQ Research, rebuilt every trading night.'))
    for slug, title, _ in ranks[:6]:
        feed_items.append((title, f'{BASE}/rankings/{slug}.html', max(as_b, as_i, as_t), f'{title}, rebuilt every trading night from published data.'))
    (SITE / 'feed.xml').write_text(feed_xml(feed_items, max(as_b, as_i, as_t)))
    def section(u):
        r = u.replace(BASE + '/', '')
        if r.startswith('funds/'):
            return 'funds'
        if r.startswith('compare/'):
            return 'compare'
        if r.startswith('rankings/'):
            return 'rankings'
        if r.startswith('research/'):
            return 'research'
        if r.startswith(('issuers/', 'themes/', 'buffer/', 'income/', 'core/')) and r.count('/') == 1 and r != '':
            return 'hubs'
        return 'pages'
    parts = {}
    parts.setdefault('pages', []).append((f'{BASE}/', max(as_b, as_i, as_t)))
    for u, d in urls:
        parts.setdefault(section(u), []).append((u, d))
    names = []
    for name, items in sorted(parts.items()):
        body = ''.join(f'<url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n' for u, d in items)
        (SITE / f'sitemap-{name}.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + '</urlset>\n')
        names.append(name)
    (SITE / 'sitemap-index.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                            + ''.join(f'<sitemap><loc>{BASE}/sitemap-{x}.xml</loc><lastmod>{max(as_b, as_i, as_t)}</lastmod></sitemap>\n' for x in names)
                                            + '</sitemapindex>\n')
    (SITE / 'sitemap.xml').write_text(sm)
    (SITE / 'robots.txt').write_text("User-agent: *\nAllow: /\n\n" + ''.join(f'User-agent: {b}\nAllow: /\n\n' for b in ('GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-User', 'Claude-SearchBot', 'anthropic-ai', 'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Googlebot', 'Bingbot', 'Applebot', 'Applebot-Extended', 'CCBot', 'Amazonbot', 'meta-externalagent', 'DuckAssistBot', 'YouBot', 'cohere-ai')) + f'Sitemap: {BASE}/sitemap.xml\nSitemap: {BASE}/sitemap-index.xml\n')
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
- [Rankings]({BASE}/rankings/): each list is one published field sorted, with the measure in the title and the method on the page. Not recommendations
- [Feed]({BASE}/feed.xml): what changed each trading night, plus the research and the rankings
- [Questions]({BASE}/questions/): plain answers to what a buffer ETF is, what return of capital means, whether covered call ETFs lose value, what active share measures, each worked through with live figures
- [ETF statistics]({BASE}/statistics/): category-level counts recomputed nightly, free to cite with attribution and the date
- [Core index funds]({BASE}/core/): the plain index, bond and commodity funds the desks measure against, on the same fields
- [Research archive]({BASE}/research/): each night's pieces kept at a dated address
- [Open data]({BASE}/data/): every figure as JSON at a stable address, free to use with attribution, rebuilt nightly. Files: funds.json, income.json, thematic.json, payouts.json, sources.json, insights.json, books/index.json
- [Standards, ownership and sources]({BASE}/standards/): who publishes this, what it never does, and where every figure comes from
- [Learn the vocabulary]({BASE}/learn/): three plain-words glossaries, one per desk, defining every term used here
- [What changed today]({BASE}/changed/): counted from the published data each trading night
- [Every issuer]({BASE}/issuers/): one page per issuer listing all of its funds across the desks
- Theme pages: https://etfiq.com/themes/THEME.html, for example https://etfiq.com/themes/ai.html
- Buffer reset months: https://etfiq.com/buffer/MONTH.html, for example https://etfiq.com/buffer/january.html
- Embeddable graphics, free to use with a credit link: https://etfiq.com/embed/DESK/TICKER.svg, for example https://etfiq.com/embed/buffer/PJAN.svg
- [Live application]({BASE}/)

## Data files

- {BASE}/data/funds.json (buffer desk records), {BASE}/data/income.json (income desk records), {BASE}/data/thematic.json (themes desk records and the fund-to-fund overlap matrix), {BASE}/data/payouts.json (payout calendar), {BASE}/data/sources.json (19a-1 estimates). Free to read; cite ETFIQ and the as-of date.
""")
    print(f'prerendered {len(urls)} pages: {len(funds)} buffer, {len(income)} income, {len(themes)} themes, {npairs} comparisons, {hubs} hubs')


if __name__ == '__main__':
    build()
