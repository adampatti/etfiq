"""Brand assets: the ETFIQ crest and lockups as self-contained SVG, every glyph outlined to a path so no font is needed.

Direction E, chosen 2026-09-05: a coin seal with a double ring and a Fraunces 800 serif IQ monogram (Q in blue), the wordmark
ETFIQ in Archivo 800 wide-tracked capitals (IQ in blue), and the tagline in Geist 500 capitals. Writes site/crest.svg (the mark),
site/favicon.svg (no rings, for tabs), site/logo.svg and site/logo-dark.svg (horizontal lockup with the tagline), and the inline
wordmark and tagline SVGs the header and the static page rail carry. The fonts are fetched from Google Fonts into the scratch
directory given as FONTS (woff2, needs brotli); og.png and apple-touch-icon.png are rendered from the SVGs with headless Chrome.
"""
import os
import json, pathlib
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
SP = pathlib.Path(os.environ.get('FONTS', pathlib.Path(__file__).parent / 'cache' / 'fonts'))
SITE = pathlib.Path(__file__).resolve().parents[1] / 'site'
INK, INK_COIN, BLUE, BLUE_DARK, WHITE, MUTED_L, MUTED_D = '#0F1419', '#161C24', '#2457E6', '#5A87E5', '#F2F4F7', '#5B6572', '#8A93A0'

_fonts = {}
def font(fam, axes):
    key = (fam, tuple(sorted(axes.items())))
    if key not in _fonts:
        f = TTFont(SP / f'{fam}.woff2'); f.flavor = None
        f = instancer.instantiateVariableFont(f, axes)
        _fonts[key] = f
    return _fonts[key]

def run(fam, axes, text, size, tracking_em=0.0):
    """Glyph paths for a text run at cap height `size` (px): list of (d, x_offset_px, color_slot) plus total ink bounds."""
    f = font(fam, axes); gs = f.getGlyphSet(); cmap = f.getBestCmap(); cap = f['OS/2'].sCapHeight; upm = f['head'].unitsPerEm
    s = size / cap
    x = 0.0; items = []; minx, maxx = None, None
    for ch in text:
        gname = cmap[ord(ch)]; g = gs[gname]
        pen = SVGPathPen(gs); g.draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
        bp = BoundsPen(gs); g.draw(bp)
        if bp.bounds:
            bx0, by0, bx1, by1 = bp.bounds
            minx = x + bx0 * s if minx is None else min(minx, x + bx0 * s); maxx = x + bx1 * s if maxx is None else max(maxx, x + bx1 * s)
        items.append((ch, pen.getCommands(), x))
        x += g.width * s + tracking_em * upm * s
    return {'items': items, 'scale': s, 'width': maxx - (minx or 0), 'minx': minx or 0, 'maxx': maxx or 0}

def paths(r, x0, baseline, color_of):
    return ''.join(f'<path fill="{color_of(ch, i)}" transform="translate({x0 + xo - r["minx"]:.3f} {baseline:.3f}) scale({r["scale"]:.6f})" d="{d}"/>' for i, (ch, d, xo) in enumerate(r['items']) if d)

def crest(rings=True, cap=19.0, coin=INK_COIN, blue=BLUE_DARK):
    r = run('Fraunces', {'wght': 800, 'opsz': 144}, 'IQ', cap, tracking_em=-0.045)
    x0 = 32 - r['width'] / 2; base = 32 + cap / 2
    body = f'<circle cx="32" cy="32" r="32" fill="{coin}"/>'
    if rings:
        body += f'<circle cx="32" cy="32" r="27.5" fill="none" stroke="#fff" stroke-opacity=".3" stroke-width="2"/><circle cx="32" cy="32" r="24.5" fill="none" stroke="#fff" stroke-opacity=".95" stroke-width="2"/>'
    body += paths(r, x0, base, lambda ch, i: blue if ch == 'Q' else '#fff')
    return body

def wordmark(cap, ink, blue):
    r = run('Archivo', {'wght': 800}, 'ETFIQ', cap, tracking_em=0.2)
    return r, (lambda x0, base: paths(r, x0, base, lambda ch, i: blue if i >= 3 else ink))

def tagline(cap, color):
    r = run('Geist', {'wght': 500}, 'INDEPENDENT ETF DATA, IN PLAIN WORDS', cap, tracking_em=0.09)
    return r, (lambda x0, base: paths(r, x0, base, lambda ch, i: color))

def svg(vb_w, vb_h, body, w=None, h=None):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:g} {vb_h:g}"' + (f' width="{w:g}" height="{h:g}"' if w else '') + f'>{body}</svg>'

def lockup(dark):
    ink, blue, mut = (WHITE, BLUE_DARK, MUTED_D) if dark else (INK, BLUE, MUTED_L)
    wm, draw_wm = wordmark(22, ink, blue); tg, draw_tg = tagline(8.0, mut)
    x0 = 82
    body = crest() + draw_wm(x0, 29) + draw_tg(x0, 52.5)
    W = x0 + max(wm['width'], tg['width']) + 2
    return svg(W, 64, body), W

out = {}
out['crest.svg'] = svg(64, 64, crest())
out['favicon.svg'] = svg(64, 64, crest(rings=False, cap=30.0))
lk, W = lockup(False); out['logo.svg'] = lk
lkd, _ = lockup(True); out['logo-dark.svg'] = lkd
for name, body in out.items():
    (SITE / name).write_text(body)
# header pieces for index.html and rail.py: the wordmark and tagline as standalone SVGs sized by cap height
wm, draw_wm = wordmark(686, 'currentColor', 'var(--iq, #5A87E5)')
wb = draw_wm(0, 686); (SP / 'wordmark-inline.svg').write_text(svg(wm['width'], 686, wb))
tg, draw_tg = tagline(710, 'currentColor'); (SP / 'tagline-inline.svg').write_text(svg(tg['width'], 710, draw_tg(0, 710)))
print(json.dumps({'lockupWidth': round(W, 1), 'wordmarkAspect': round(wm['width'] / 686, 4), 'taglineAspect': round(tg['width'] / 710, 4), 'sizes': {k: len(v) for k, v in out.items()}}, indent=1))
