#!/usr/bin/env python3
"""Research narratives: Claude drafts from the computed tables, the pipeline checks the draft, and only a draft that
passes is published.

For each piece in data/research/<slug>.json, the tables and summary are sent to Claude with ETFIQ's rules. The reply
is accepted only if every number in it appears in the tables or the summary, it uses none of the words the site bans,
and it contains no recommendation language. An accepted draft is written to data/research/<slug>.narrative.html and
placed on the research page by research.py, labelled as drafted by Claude and checked against the tables.

Needs ANTHROPIC_API_KEY. Skips quietly without it. Redrafts when the tables changed since the last accepted draft
(a hash of the tables is kept next to the narrative), so the words follow the numbers.
"""
import hashlib
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS = [m.strip() for m in os.environ.get('ETFIQ_DRAFT_MODEL', 'claude-sonnet-5,claude-sonnet-4-5,claude-sonnet-4-5-20250929,claude-3-7-sonnet-latest').split(',') if m.strip()]
BANNED = re.compile(r'\b(best|top pick|buy|sell|recommend\w*|favou?rite|winner|should (?:own|hold|avoid)|must-have)\b', re.I)

SYSTEM = """You write for ETFIQ, an independent publisher of exchange-traded fund data. Rules that cannot be broken:
- Write only from the tables and summary you are given. Every number you use must appear there, unchanged. Do not compute new figures.
- Never recommend, rank by opinion, or suggest what to buy, sell, hold or avoid. Describe what the data shows.
- Plain words for a retail reader who knows what an ETF is; an adviser should find it precise. No jargon without a gloss. No hype, no adjectives of praise.
- Short paragraphs, about 350 to 500 words, no headings, no bullet lists, no em dashes.
- Name issuers and funds only as they appear in the tables. Say "the median fund" when the figure is a median.
- End with one sentence on what the reader can check on the live desk.
Return only the prose."""


def numbers(text):
    return set(re.findall(r'\d+(?:\.\d+)?', text.replace(',', '')))


class ApiError(Exception):
    pass


def call(payload):
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(payload).encode(), headers={
        'content-type': 'application/json', 'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01', 'user-agent': 'ETFIQ data pipeline'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:300]
        raise ApiError(f'HTTP {e.code}: {body}') from None
    return ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text').strip()


def pick_model():
    """The first model id in MODELS the key can use, found with a one-token request; None when none answers."""
    for m in MODELS:
        try:
            call({'model': m, 'max_tokens': 5, 'messages': [{'role': 'user', 'content': 'Reply with the word ready.'}]})
            print(f'draft: using model {m}', file=sys.stderr)
            return m
        except ApiError as e:
            print(f'draft: model {m} unavailable ({str(e)[:160]})', file=sys.stderr)
        except Exception as e:
            print(f'draft: model {m} error ({str(e)[:120]})', file=sys.stderr)
    return None


def check(text, piece):
    allowed = numbers(json.dumps(piece['tables'])) | numbers(' '.join(piece['summary'])) | numbers(piece['asOf'] or '') | {'19', '1'}
    used = numbers(text)
    stray = sorted(u for u in used if u not in allowed and u.rstrip('0').rstrip('.') not in {a.rstrip('0').rstrip('.') for a in allowed})
    if stray:
        return f'numbers not in the tables: {stray[:8]}'
    m = BANNED.search(text)
    if m:
        return f'banned word: {m.group(0)}'
    if len(text.split()) < 150 or len(text.split()) > 700:
        return f'length {len(text.split())} words'
    if '\u2014' in text:  # an em dash, written as an escape so this file carries none
        return 'em dash'
    return None


def build():
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print('draft: no ANTHROPIC_API_KEY; skipping narratives', file=sys.stderr)
        return
    model = pick_model()
    if not model:
        print('draft: no usable model; narratives kept as they are', file=sys.stderr)
        return
    for pj in sorted((ROOT / 'data' / 'research').glob('*.json')):
        piece = json.loads(pj.read_text())
        digest = hashlib.sha256(json.dumps(piece['tables'], sort_keys=True).encode()).hexdigest()[:16]
        hp = pj.with_suffix('.hash')
        if hp.exists() and hp.read_text().strip() == digest and pj.with_suffix('.narrative.html').exists():
            print(f"  {piece['slug']}: tables unchanged, narrative kept", file=sys.stderr)
            continue
        user = f"Piece: {piece['title']} (data as of {piece['asOf']}).\n\nComputed summary:\n" + '\n'.join(piece['summary']) + '\n\nTables (JSON):\n' + json.dumps(piece['tables'], indent=0) + f"\n\nMethod: {piece['method']}\n\nWrite the narrative."
        text, err = '', 'no attempt'
        for attempt in range(3):
            try:
                text = call({'model': model, 'max_tokens': 1400, 'system': SYSTEM, 'messages': [{'role': 'user', 'content': user + (f"\n\nYour previous draft was rejected: {err}. Use only figures from the tables and summary." if attempt else '')}]})
            except Exception as e:
                err = f'api error {str(e)[:200]}'
                print(f"  {piece['slug']}: {err}", file=sys.stderr)
                continue
            err = check(text, piece)
            if not err:
                break
            print(f"  {piece['slug']}: draft {attempt + 1} rejected ({err})", file=sys.stderr)
        if err:
            print(f"  {piece['slug']}: no narrative published", file=sys.stderr)
            continue
        paras = ''.join(f'<p>{html.escape(p.strip())}</p>' for p in re.split(r'\n\s*\n', text) if p.strip())
        pj.with_suffix('.narrative.html').write_text(paras)
        hp.write_text(digest)
        print(f"  {piece['slug']}: narrative accepted, {len(text.split())} words", file=sys.stderr)


if __name__ == '__main__':
    build()
