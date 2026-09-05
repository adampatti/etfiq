#!/usr/bin/env python3
"""Inline the latest data into site/index.html and stamp the as-of dates.

Blocks filled (each a <script type="application/json"> with an id):
  etfiq-data             site/data/funds.json          buffer desk records
  etfiq-income           site/data/income.json         income desk records (empty array until the feed runs)
  etfiq-income-universe  data/income_universe.json     the income universe, included funds only

CONFIG.asOf comes from site/data/meta.json, CONFIG.incomeAsOf from site/data/income_meta.json.
Idempotent; run after every snapshot. The page also works from data/*.json when the blocks are absent.
"""
import json, re, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
html_path = ROOT / 'site' / 'index.html'
html = html_path.read_text()

def load(p, default):
    p = ROOT / p
    return json.loads(p.read_text()) if p.exists() else default

def fill(block_id, data):
    global html
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    html, n = re.subn(r'(<script type="application/json" id="' + block_id + r'">).*?(</script>)',
                      lambda m: m.group(1) + payload + m.group(2), html, count=1, flags=re.S)
    if n != 1:
        sys.exit(f'block {block_id} not found in site/index.html')

funds = load('site/data/funds.json', [])
income = load('site/data/income.json', [])
universe = [u for u in load('data/income_universe.json', []) if u.get('include')]
fill('etfiq-data', funds)
fill('etfiq-income', income)
fill('etfiq-income-universe', universe)
meta = load('site/data/meta.json', {})
imeta = load('site/data/income_meta.json', {})
for key, val in (('asOf', meta.get('asOf')), ('incomeAsOf', imeta.get('asOf'))):
    html, n = re.subn(key + r":\s*(?:null|'[^']*'),", key + ': ' + ('null' if not val else repr(val)) + ',', html, count=1)
    if n != 1:
        sys.exit(f'CONFIG.{key} not found')
html_path.write_text(html)
print(f'inlined {len(funds)} buffer funds, {len(income)} income funds, {len(universe)} income universe; asOf={meta.get("asOf")}, incomeAsOf={imeta.get("asOf")}')
