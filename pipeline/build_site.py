#!/usr/bin/env python3
"""Inline the latest data into site/index.html and stamp the as-of dates.

Blocks filled (each a <script type="application/json"> with an id):
  etfiq-data             site/data/funds.json          buffer desk records
  etfiq-income           site/data/income.json         income desk records (empty array until the feed runs)
  etfiq-income-universe  data/income_universe.json     the income universe, included funds only, republished to site/data/
  etfiq-thematic         site/data/thematic.json       themes desk records and the fund-to-fund overlap matrix
  etfiq-sources          site/data/sources.json        issuers' 19a-1 estimates of distribution sources by ticker
  etfiq-insights         site/data/insights.json       what changed: computed lines for the home page

CONFIG.asOf comes from site/data/meta.json, CONFIG.incomeAsOf from site/data/income_meta.json.
Idempotent; run after every snapshot. The page also works from data/*.json when the blocks are absent.
"""
import json
import os, re, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
html_path = ROOT / 'site' / 'index.html'
html = html_path.read_text()

def load(p, default):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else default

def fill(block_id, data):
    global html
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\/').replace('\u2014', '-').replace('\\u2014', '-')
    html, n = re.subn(r'(<script type="application/json" id="' + block_id + r'">).*?(</script>)',
                      lambda m: m.group(1) + payload + m.group(2), html, count=1, flags=re.S)
    if n != 1:
        sys.exit(f'block {block_id} not found in site/index.html')

funds = load('site/data/funds.json', [])
income = load('site/data/income.json', [])
universe = [u for u in load('data/income_universe.json', []) if u.get('include')]
for u in universe:
    for k in ('entity', 'cik', 'why', 'include'):
        u.pop(k, None)
# the income desk falls back to this list when the price feed is empty, and fetches it the way it fetches the other desk data
(ROOT / 'site' / 'data' / 'income_universe.json').write_text(json.dumps(universe, separators=(',', ':')))
payouts = load('site/data/payouts.json', [])
for p in payouts:
    p.pop('history', None)
INLINE_LARGE = os.environ.get('ETFIQ_INLINE') == '1'  # the desks fetch their data; set to inline it for a file-only copy
fill('etfiq-data', funds if INLINE_LARGE else [])
fill('etfiq-payouts', payouts if INLINE_LARGE else [])
fill('etfiq-income', income if INLINE_LARGE else [])
fill('etfiq-income-universe', universe if INLINE_LARGE else [])
thematic = load('site/data/thematic.json', {'funds': [], 'matrix': None})
for r in thematic.get('funds', []):
    for k in ('entity', 'cik', 'why', 'holdingsFiled'):
        r.pop(k, None)
fill('etfiq-thematic', thematic if INLINE_LARGE else {'funds': [], 'matrix': None})
fill('etfiq-sources', load('site/data/sources.json', {}))
fill('etfiq-insights', load('site/data/insights.json', {'lines': [], 'stats': {}}))
research = []
for rp in sorted((ROOT / 'data' / 'research').glob('*.json')):
    pc = json.loads(rp.read_text())
    research.append({'slug': pc['slug'], 'desk': pc['desk'], 'title': pc['title'], 'asOf': pc.get('asOf'), 'summary': (pc.get('summary') or [''])[0],
                     'narrative': rp.with_suffix('.narrative.html').exists()})
fill('etfiq-research', research)
lede = ('Independent data on {nb} defined outcome (buffer) ETFs, {ni} option-income ETFs and {nt} thematic ETFs, plus the core index funds the desks measure against. '
        'Rebuilt every trading night from issuer disclosures, filings with the SEC and exchange prices.')
html, k = re.subn(r'<p class="fabout" id="dirLede">.*?</p>',
                  '<p class="fabout" id="dirLede">' + lede.format(nb=len(funds), ni=len(income), nt=len(thematic.get('funds', []))) + '</p>', html, count=1, flags=re.S)
if k != 1:
    sys.exit('site directory lede not found')
meta = load('site/data/meta.json', {})
imeta = load('site/data/income_meta.json', {})
tmeta = load('site/data/thematic_meta.json', {})
_as = meta.get('asOf')
banner_default = (f'<b>Live data</b> as published by issuers on {_as}, and filed with the SEC. Every figure carries its date.'
                  if _as else '<b>Sample data.</b> Values below are illustrative and are not live fund figures.')
html, k = re.subn(r'(<span id="bannerText">).*?(</span>)', lambda m: m.group(1) + banner_default + m.group(2), html, count=1, flags=re.S)
if k != 1:
    sys.exit('banner default not found')
foot_default = ' · '.join(x for x in [f'Buffer data {_as}' if _as else 'Buffer desk on sample data',
                                      f"income prices {imeta.get('asOf')}" if imeta.get('asOf') else 'income feed not connected',
                                      f"themes prices {tmeta.get('asOf')}" if tmeta.get('asOf') else None] if x)
html, k = re.subn(r'(<span id="footAsOf">).*?(</span>)', lambda m: m.group(1) + foot_default + m.group(2), html, count=1, flags=re.S)
if k != 1:
    sys.exit('footer date default not found')
imeta = load('site/data/income_meta.json', {})
tmeta = load('site/data/thematic_meta.json', {})
for key, val in (('asOf', meta.get('asOf')), ('incomeAsOf', imeta.get('asOf')), ('thematicAsOf', tmeta.get('asOf'))):
    html, n = re.subn(key + r":\s*(?:null|'[^']*'),", key + ': ' + ('null' if not val else repr(val)) + ',', html, count=1)
    if n != 1:
        sys.exit(f'CONFIG.{key} not found')
if '\u2014' in html:
    sys.exit('an em dash is in site/index.html; ETFIQ never publishes one')
html_path.write_text(html)
print(f'inlined {len(funds)} buffer funds, {len(income)} income funds, {len(universe)} income universe, {len(thematic.get("funds", []))} thematic funds; asOf={meta.get("asOf")}, incomeAsOf={imeta.get("asOf")}, thematicAsOf={tmeta.get("asOf")}')
