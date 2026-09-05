#!/usr/bin/env python3
"""Inline site/data/funds.json into site/index.html and stamp the as-of date from site/data/meta.json.

Idempotent: run it after every snapshot. The page keeps working from the inline block when opened as a
single file (the artifact, a file:// preview) and from data/funds.json when the block is absent.
"""
import json, re, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
html_path = ROOT / 'site' / 'index.html'
funds = json.loads((ROOT / 'site' / 'data' / 'funds.json').read_text())
meta_path = ROOT / 'site' / 'data' / 'meta.json'
meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

html = html_path.read_text()
data = json.dumps(funds, separators=(',', ':')).replace('</', '<\\/')
html, n = re.subn(r'(<script type="application/json" id="etfiq-data">).*?(</script>)',
                  lambda m: m.group(1) + data + m.group(2), html, count=1, flags=re.S)
if n != 1:
    sys.exit('data block not found in site/index.html')
as_of = meta.get('asOf')
html, n2 = re.subn(r"asOf:\s*(?:null|'[^']*'),", "asOf: " + ('null' if not as_of else repr(as_of)) + ",", html, count=1)
if n2 != 1:
    sys.exit('CONFIG.asOf not found in site/index.html')
html_path.write_text(html)
print(f'inlined {len(funds)} funds into site/index.html, asOf={as_of}')
