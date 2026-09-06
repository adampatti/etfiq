#!/usr/bin/env python3
"""Embeddable graphics: one standalone SVG per fund, for other sites to place in their own pages.

Each file is a small card carrying the desk's signature object with literal colours and outlined nothing else, so it
renders anywhere: the outcome band for a buffer fund, the payout bar for an income fund, the difference bar for a
thematic fund. Every card states the ticker, the figures behind the drawing, the data date and etfiq.com, so a reader
who meets it on someone else's page knows what it is and where it came from.

Writes site/embed/<desk>/<TICKER>.svg from the same desk files the site publishes. Regenerated every night, so a page
that embeds one stays current without its owner touching it. Fund pages carry an "Embed this" snippet.
"""
import datetime
import html
import json
import pathlib
import sys

RASTER = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
OUT = SITE / 'embed'
INK, INK2, MUTED, LINE, LINE2 = '#0A0A0A', '#2B2B2B', '#6A6A68', '#E6E6E3', '#D2D2CE'
PROT, UNPROT, UP, UPFILL, UPLINE, CEIL = '#00806B', '#D12E1F', '#F0F0EE', '#D9D9D5', '#BEBEB9', '#B37400'
VIOLET, VIOLET_SOFT, ACCENT, GROUND, SURFACE = '#5B2BE8', '#EEEAFD', '#1D34F2', '#FAFAF9', '#FFFFFF'
FONT = "Geist,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif"
DESK_LABEL = {'buffer': 'buffer desk', 'income': 'income desk', 'themes': 'themes desk'}
MONO = "'Geist Mono',ui-monospace,SFMono-Regular,Menlo,monospace"
W, H = 640, 208
OG_W, OG_H = 1200, 630


def load(p, default):
    q = ROOT / p
    return json.loads(q.read_text()) if q.exists() else default


def esc(s):
    return html.escape(str(s if s is not None else '').replace('—', '-'), quote=True)


def pct(v, sign=True, d=1):
    if v is None:
        return 'n/a'
    return f'{v:+.{d}f}%'.replace('+', '') if not sign else (('-' if v < 0 else '+') + f'{abs(v):.{d}f}%')


def fdate(iso):
    try:
        return datetime.date.fromisoformat(iso).strftime('%b %-d, %Y')
    except Exception:
        return iso or ''


def txt(x, y, s, size=12, fill=INK2, weight=400, anchor='start', mono=False, ls=0.0):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO if mono else FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"' + (f' letter-spacing="{ls}"' if ls else '') + f'>{esc(s)}</text>')


def shell(ticker, name, sub, inner, as_of, desk):
    """The card around a graphic: ticker, fund name, the figures, and where it came from."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{esc(ticker)}: {esc(sub)}">
<rect width="{W}" height="{H}" rx="10" fill="{SURFACE}" stroke="{LINE}"/>
{txt(20, 32, ticker, 20, INK, 700, mono=True, ls=-0.4)}
{txt(20 + 12 + len(ticker) * 12.6, 32, name[:52], 12.5, MUTED, 500)}
{inner}
{txt(20, H - 44, sub if len(sub) <= 96 else sub[:93].rstrip(' ,·') + '...', 12, INK2, 500)}
<line x1="20" y1="{H - 32}" x2="{W - 20}" y2="{H - 32}" stroke="{LINE}"/>
{txt(20, H - 14, f'ETFIQ · {DESK_LABEL[desk]} · data as of {fdate(as_of)}', 11, MUTED, 500)}
{txt(W - 20, H - 14, 'etfiq.com', 11, ACCENT, 600, anchor='end')}
</svg>'''


def band_svg(f, as_of):
    pad, y, bh = 20, 74, 26
    bs, be, ref, cap = f['bufferStart'], f['bufferEnd'], f['refReturn'], f.get('startCap')
    is_floor = be <= -100
    lo = min(bs - 40 if is_floor else be, ref) - 3
    hi = max(max(ref, 0) + 12 if cap is None else cap, ref) + 3
    span = (hi - lo) or 1
    X = lambda v: pad + (min(max(v, lo), hi) - lo) / span * (W - 2 * pad)
    sb = f.get('startBuffer') or (bs - be)
    used = max(0.0, min(sb, bs - ref))
    s = ''
    rect = lambda x0, x1, fill, op=1: '' if x1 - x0 <= 0 else f'<rect x="{x0:.1f}" y="{y}" width="{x1 - x0:.1f}" height="{bh}" fill="{fill}" fill-opacity="{op}"/>'
    floor_x = pad if is_floor else X(be)
    s += rect(floor_x, X(bs) if used == 0 else X(max(ref, be)), PROT)
    if used > 0:
        s += rect(X(max(ref, be)), X(bs), PROT, 0.32)
    if bs < 0:
        s += rect(X(bs), X(0), UNPROT, 1 if ref >= bs else 0.35)
    if cap is None:
        s += rect(X(0), W - pad, UP)
        if ref > 0:
            s += rect(X(0), X(ref), UPFILL)
    else:
        s += rect(X(0), X(cap), UP)
        if ref > 0:
            s += rect(X(0), min(X(ref), X(cap)), UPFILL)
        capped = ref >= cap
        s += f'<rect x="{X(cap) - (5 if capped else 1):.1f}" y="{y - 3}" width="{6 if capped else 2}" height="{bh + 6}" fill="{CEIL}"/>'
    s += f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{y - 2}" y2="{y + bh + 2}" stroke="{LINE2}"/>'
    rx = X(ref if cap is None else min(ref, cap))
    s += f'<line x1="{rx:.1f}" x2="{rx:.1f}" y1="{y - 5}" y2="{y + bh + 5}" stroke="{INK}" stroke-width="2"/>'
    if f.get('fundReturn') is not None:
        s += f'<circle cx="{X(f["fundReturn"]):.1f}" cy="{y + bh / 2:.1f}" r="4.5" fill="{SURFACE}" stroke="{INK}" stroke-width="1.5"/>'
    left = 'full floor' if is_floor else pct(be, sign=False) + ' floor'
    s += txt(pad, y - 12, left, 10.5, MUTED, 500, mono=True)
    s += txt(W - pad, y - 12, 'no cap' if cap is None else pct(cap) + ' cap', 10.5, MUTED, 500, anchor='end', mono=True)
    s += txt(rx, y + bh + 18, f"{f['refAsset']} {pct(ref)}", 11, INK, 600, anchor='middle' if pad + 60 < rx < W - pad - 60 else ('start' if rx <= pad + 60 else 'end'), mono=True)
    gain = 'uncapped' if cap is None else pct(f.get('remainingCapFund'), sign=False)
    left_txt = 'full floor' if is_floor else pct(round(sb - used, 2), sign=False)
    sub = f"Can still gain {gain} · fall before buffer {pct(f.get('downsideBeforeBuffer'), sign=False)} · protection left {left_txt}"
    return shell(f['ticker'], f['name'], sub, s, as_of, 'buffer'), social_card(f['ticker'], f['name'], sub, s, as_of, 'buffer')


def paybar_svg(r, as_of):
    pad, y, bh, gap = 20, 66, 15, 6
    w = (r.get('windows') or {}).get('1Y') or (r.get('windows') or {}).get('ITD')
    if not w:
        return None, None
    vals = [w['cash'], w['price'], w['total'], w.get('bench') or 0, 0]
    lo, hi = min(vals) - 4, max(vals) + 6
    span = (hi - lo) or 1
    X = lambda v: pad + (min(max(v, lo), hi) - lo) / span * (W - 2 * pad)
    z = X(0)
    s = f'<line x1="{z:.1f}" x2="{z:.1f}" y1="{y - 6}" y2="{y + 2 * bh + gap + 6}" stroke="{LINE2}"/>'
    s += f'<rect x="{z:.1f}" y="{y}" width="{max(0, X(w["cash"]) - z):.1f}" height="{bh}" fill="{PROT}"/>'
    px = w['price']
    s += f'<rect x="{min(z, X(px)):.1f}" y="{y + bh + gap}" width="{abs(X(px) - z):.1f}" height="{bh}" fill="{UNPROT if px < 0 else PROT}" fill-opacity="{0.85 if px < 0 else 0.45}"/>'
    tx = X(w['total'])
    s += f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="{y - 6}" y2="{y + 2 * bh + gap + 6}" stroke="{INK}" stroke-width="2"/>'
    if w.get('bench') is not None:
        bx = X(w['bench'])
        s += f'<circle cx="{bx:.1f}" cy="{y + bh + gap / 2:.1f}" r="5" fill="{SURFACE}" stroke="{INK}" stroke-width="1.5"/>'
    s += txt(pad, y - 12, 'cash paid', 10.5, MUTED, 500, mono=True)
    s += txt(pad, y + 2 * bh + gap + 20, 'price change', 10.5, MUTED, 500, mono=True)
    s += txt(W - pad, y - 12, f"total {pct(w['total'])} · benchmark {pct(w.get('bench'))}", 10.5, MUTED, 500, anchor='end', mono=True)
    win = 'over 1 year' if w is (r.get('windows') or {}).get('1Y') else f"since launch on {fdate(w.get('from'))}"
    side = 'ahead by' if (w.get('gap') or 0) > 0.5 else 'behind by' if (w.get('gap') or 0) < -0.5 else 'even with'
    g = f"{side} {abs(w['gap']):.1f} pts" if w.get('gap') is not None else 'no benchmark'
    sub = f"Paid {pct(w['cash'], sign=False)}, price {pct(w['price'])}, {g} vs {r['benchmark']} {win}"
    return shell(r['ticker'], r['name'], sub, s, as_of, 'income'), social_card(r['ticker'], r['name'], sub, s, as_of, 'income')


def diffbar_svg(r, as_of):
    pad, y, bh, gap = 20, 74, 16, 8
    v = r.get('vsSPY')
    if not v:
        return None, None
    full = W - 2 * pad
    ins = v['inIndex'] / 100 * full
    s = f'<rect x="{pad}" y="{y}" width="{full:.1f}" height="{bh}" rx="3" fill="{VIOLET_SOFT}"/>'
    s += f'<rect x="{pad}" y="{y}" width="{ins:.1f}" height="{bh}" rx="3" fill="{LINE2}"/>'
    s += f'<rect x="{pad + ins:.1f}" y="{y}" width="{max(0, full - ins):.1f}" height="{bh}" fill="{VIOLET}"/>'
    top = r.get('top10Weight') or 0
    s += f'<rect x="{pad}" y="{y + bh + gap}" width="{full:.1f}" height="{bh - 5}" rx="3" fill="{VIOLET_SOFT}"/>'
    s += f'<rect x="{pad}" y="{y + bh + gap}" width="{top / 100 * full:.1f}" height="{bh - 5}" rx="3" fill="{VIOLET}" fill-opacity="0.55"/>'
    s += txt(pad, y - 12, f"{v['inIndex']:.0f}% already in the S&P 500", 10.5, MUTED, 500, mono=True)
    s += txt(W - pad, y - 12, f"{v['activeShare']:.0f}% different", 10.5, VIOLET, 600, anchor='end', mono=True)
    s += txt(pad, y + 2 * bh + gap + 12, f"top ten {top:.0f}% of the fund, {r.get('holdingsCount') or 0} holdings", 10.5, MUTED, 500, mono=True)
    w = (r.get('windows') or {}).get('1Y')
    perf = f", 1 year {pct(w['total'])}" if w else ''
    sub = f"{v['inIndex']:.0f}% index names, active share {v['activeShare']:.0f}%{perf}"
    return shell(r['ticker'], r['name'], sub, s, as_of, 'themes'), social_card(r['ticker'], r['name'], sub, s, as_of, 'themes')


def social_card(ticker, name, sub, inner, as_of, desk):
    """The same card at link-preview size, so a shared fund page shows its own numbers."""
    scale = 1.6
    body = f'<g transform="translate({(OG_W - W * scale) / 2:.1f} {(OG_H - H * scale) / 2 + 40:.1f}) scale({scale})">{inner}</g>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {OG_W} {OG_H}" width="{OG_W}" height="{OG_H}" role="img" aria-label="{esc(ticker)}: {esc(sub)}">
<rect width="{OG_W}" height="{OG_H}" fill="#0A0A0A"/>
<rect x="{(OG_W - W * scale) / 2:.1f}" y="{(OG_H - H * scale) / 2 + 40:.1f}" width="{W * scale:.1f}" height="{H * scale:.1f}" rx="16" fill="{SURFACE}"/>
{body}
{txt(OG_W / 2, 92, ticker, 54, "#FAFAF9", 800, anchor="middle", mono=True, ls=-1.5)}
{txt(OG_W / 2, 122, name[:64], 19, "#9A9A97", 500, anchor="middle")}
{txt(OG_W / 2, OG_H - 44, f"ETFIQ · {DESK_LABEL.get(desk, desk)} · data as of {fdate(as_of)} · etfiq.com", 18, "#9A9A97", 500, anchor="middle")}
</svg>'''


def raster(svg, path):
    """A PNG of the social card, because link previews reject SVG. Needs cairosvg; without it the page falls back
    to the site image, so a machine that cannot rasterise still builds a correct site."""
    global RASTER
    if RASTER is False:
        return 0
    try:
        import cairosvg
    except Exception:
        RASTER = False
        print('embed: no cairosvg, social PNGs skipped', file=sys.stderr)
        return 0
    try:
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(path), output_width=OG_W, output_height=OG_H)
        return 1
    except Exception as e:
        RASTER = False
        print(f'embed: rasteriser failed, social PNGs skipped ({str(e)[:80]})', file=sys.stderr)
        return 0


def build():
    meta, imeta, tmeta = load('site/data/meta.json', {}), load('site/data/income_meta.json', {}), load('site/data/thematic_meta.json', {})
    today = datetime.date.today().isoformat()
    made = {}
    png = 0
    for desk, path, as_of, fn in (('buffer', 'site/data/funds.json', meta.get('asOf', today), band_svg),
                                  ('income', 'site/data/income.json', imeta.get('asOf', today), paybar_svg),
                                  ('themes', 'site/data/thematic.json', tmeta.get('asOf', today), diffbar_svg)):
        data = load(path, [])
        rows = data['funds'] if isinstance(data, dict) else data
        d = OUT / desk
        s_dir = OUT / 'social' / desk
        d.mkdir(parents=True, exist_ok=True)
        s_dir.mkdir(parents=True, exist_ok=True)
        for old in list(d.glob('*.svg')) + list(s_dir.glob('*.svg')) + list(s_dir.glob('*.png')):
            old.unlink()
        n = 0
        for r in rows:
            svg, social = fn(r, as_of)
            if svg:
                (d / f"{r['ticker']}.svg").write_text(svg)
                (s_dir / f"{r['ticker']}.svg").write_text(social)
                png += raster(social, s_dir / f"{r['ticker']}.png")
                n += 1
        made[desk] = n
    print(json.dumps({'embeds': made, 'total': sum(made.values()), 'socialPng': png}, indent=1))
    return made


if __name__ == '__main__':
    build()
