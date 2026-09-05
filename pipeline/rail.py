"""The site's top rail for static pages (research, fund pages): the same logo, desks, Research and alerts as the app."""
BASE = 'https://etfiq.com'
RAIL_CSS = ("header.rail{background:#0F1419;color:#F2F4F7;padding:0 20px;display:flex;align-items:center;gap:22px;height:60px;position:sticky;top:0;z-index:5}"
            "header.rail .logo{display:flex;align-items:center;gap:10px;color:#F2F4F7;text-decoration:none;font-weight:700;letter-spacing:-.04em;font-size:22px}"
            "header.rail .logo b{color:#5A87E5;font-weight:700}header.rail nav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;margin-left:6px}header.rail nav::-webkit-scrollbar{display:none}"
            "header.rail nav a{color:#B8C0CC;text-decoration:none;font-weight:500;font-size:14px;padding:19px 12px 17px;border-bottom:2px solid transparent;white-space:nowrap}"
            "header.rail nav a:hover{color:#fff}header.rail nav a.on{color:#fff;border-bottom-color:#5A87E5}"
            "header.rail .alerts{margin-left:auto;background:#2457E6;color:#fff;text-decoration:none;font-weight:600;font-size:14px;padding:9px 14px;border-radius:8px;white-space:nowrap}"
            "@media (max-width:560px){header.rail nav a .long{display:none}header.rail .alerts{display:none}}")
MARK = ('<svg width="28" height="28" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#1C2430"/><line x1="11" y1="32" x2="53" y2="32" stroke="#fff" stroke-opacity=".3" stroke-width="2.5" stroke-linecap="round"/>'
        '<rect x="20" y="19" width="5.5" height="26" rx="2.75" fill="#fff"/><circle cx="41" cy="32" r="8.5" fill="none" stroke="#fff" stroke-width="4.2"/><line x1="46.5" y1="37.5" x2="52" y2="43" stroke="#3B6DF2" stroke-width="4.2" stroke-linecap="round"/></svg>')


def rail(active=''):
    items = [('buffer', f'{BASE}/#/buffer/check', 'Buffer', ' desk'), ('income', f'{BASE}/#/income/check', 'Income', ' desk'), ('themes', f'{BASE}/#/themes/check', 'Themes', ' desk'),
             ('portfolio', f'{BASE}/#/portfolio', 'Portfolio', ' desk'), ('research', '/research/', 'Research', '')]
    nav = ''.join(f'<a href="{h}"{" class=\"on\"" if k == active else ""}>{a}{f"<span class=\"long\">{b}</span>" if b else ""}</a>' for k, h, a, b in items)
    return f'<header class="rail"><a class="logo" href="{BASE}/" aria-label="ETFIQ home">{MARK}<span>ETF<b>IQ</b></span></a><nav>{nav}</nav><a class="alerts" href="{BASE}/#/alerts">Get alerts</a></header>'
