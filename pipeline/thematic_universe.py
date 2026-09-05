#!/usr/bin/env python3
"""ETFIQ themes desk: which ETFs are thematic, and which theme each one belongs to.

Source: the SEC investment company series and class file (cached by income_universe.py), read for every class with a
ticker. A fund is thematic when its name carries a theme word from the taxonomy below and none of the exclusion
words (income, buffer, leverage, bonds, spot crypto). Each fund gets one primary theme: the first taxonomy entry whose
pattern matches, so order matters. The taxonomy is editorial and says so on the Standards page.

Output data/thematic_universe.json: ticker, name, issuer, entity, cik, seriesId, theme, include, why.
Hand tables: EXCLUDE_TICKERS for false positives, FORCE for thematic funds whose names carry no theme word, and
THEME_OVERRIDES for a ticker whose primary theme the rules get wrong.

Usage: python3 pipeline/thematic_universe.py
"""
import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import income_universe as iu  # noqa: E402  (issuer names and the SEC file cache)

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (theme key, theme name, name pattern). First match wins.
THEMES = [
    ('ai', 'Artificial intelligence', r'Artificial Intelligence|\bAI\b|\bA\.I\.|Machine Learning|Generative|Large Language'),
    ('robotics', 'Robotics and automation', r'Robotic|Automation|Humanoid|Drone'),
    ('semis', 'Semiconductors', r'Semiconductor'),
    ('quantum', 'Quantum computing', r'Quantum'),
    ('cyber', 'Cybersecurity', r'Cyber'),
    ('cloud', 'Cloud and software', r'\bCloud\b|Software|SaaS'),
    ('digital-infra', 'Digital infrastructure and data centers', r'Data Center|Digital Infrastructure|\b5G\b|Connectivity|Internet of Things|\bIoT\b'),
    ('blockchain', 'Blockchain and crypto equities', r'Blockchain|Crypto (?:Industry|Economy|Thematic|Equit)|Bitcoin Min|Digital Assets|Web3|Decentralized|Digital Transformation|Digital Economy'),
    ('internet', 'Internet and e-commerce', r'Internet|E-?Commerce|Online|Social Media'),
    ('fintech', 'Fintech and digital payments', r'Fin ?[Tt]ech|Financial Technology|Payments|Insurtech'),
    ('gaming', 'Gaming, esports and betting', r'Gaming|Esports|Video Game|Sports Betting|Casino|iGaming'),
    ('metaverse', 'Metaverse and immersive tech', r'Metaverse|Virtual Reality|Augmented Reality|Immersive'),
    ('genomics', 'Genomics and biotech innovation', r'Genomic|Gene\b|CRISPR|Precision Medicine|Immunotherapy|Biotech Innovation|Biotechnology Innovation'),
    ('health-innovation', 'Healthcare innovation and GLP-1', r'Obesity|GLP|Weight Loss|Healthcare Innovation|Health Innovation|Telehealth|Digital Health|Health Tech|MedTech|Medical Technology'),
    ('longevity', 'Longevity and aging', r'Longevity|Aging|Ageing|Senior Living'),
    ('clean-energy', 'Clean energy', r'Clean Energy|Renewable|Solar|Wind Energy|Green Energy|Clean ?Tech|Clean Edge|Clean Power|Hydrogen|\bH2\b|Fuel Cell|Alternative Energy|Climate Solutions|Low Carbon Energy'),
    ('ev', 'Electric vehicles and batteries', r'Electric Vehicle|\bEVs?\b|Autonomous|Battery|Lithium|Self-Driving|Future Mobility|Mobility'),
    ('nuclear', 'Nuclear and uranium', r'Uranium|Nuclear'),
    ('electrification', 'Electrification and the grid', r'Electrification|Smart Grid|\bGrid\b|Power Infrastructure|Copper'),
    ('infrastructure', 'Infrastructure', r'Infrastructure Development|U\.?S\.? Infrastructure|NextGen Infrastructure|Sustainable Infrastructure|Green Infrastructure|Environmental Infrastructure|Infrastructure ex-U'),
    ('space', 'Space', r'\bSpace\b|Lunar|Satellite'),
    ('defense', 'Defense', r'Defen[cs]e|Military|Aerospace'),
    ('water', 'Water', r'\bWater\b'),
    ('food', 'Food and agriculture', r'Ag ?Tech|Agricultur|Agribusiness|Future of Food|Food Innovation|Plant-Based|Emergent Food'),
    ('cannabis', 'Cannabis', r'Cannabis|Marijuana|Hemp'),
    ('pets', 'Pets and consumer themes', r'\bPets?\b|Pet Care|Luxury|Travel'),
    ('innovation', 'Broad innovation and megatrends', r'Innovation|Disruptive|Megatrend|Thematic ETF|Equity Megatrends|Next Gen(?:eration)? (?:100|200|Connected|Tech)|Future (?:Tech|Health|Planet|Consumer|Vehicles|Security|Sec|of Finance)|Moonshot|Exponential|Transformational|Engineering the Future|Future of Warfare'),
]
EXCLUDE = re.compile(r'Futures|Fund Class|Class [A-Z]\b|Advisor|\bK6\b|Portfolio$|Institutional|Investor Class|Carbon Allowance|Carbon Strategy|Carbon Reduction|Carbon Transition|Low Carbon Optimized|Metals Strategy|MLP|Energy Infrastructure|Listed Infrastructure|Global Infrastructure|Broad Infrastructure|Natural Gas|Crypto (?:10|20)|Crypto Index|Top 10|Active Crypto|CoinDesk|Food & Beverage|Food and Beverage|Gold|Silver|Airlines|Banks|Natural Monopoly|R&D Champions|Buffer|Covered Call|Income|Dividend|Bond|Treasur|Yield|Option|\bBull\b|\bBear\b|\b[23]X\b|Daily|Ultra|Inverse|\bShort\b|Leveraged|Managed Futures|Hedged|Target|Municipal|Preferred|Convertible|Mortgage|Currency|Bitcoin ETF|Bitcoin Trust|Ether ETF|Ethereum ETF|Ethereum Trust|Bitcoin Strategy|Ether Strategy|Solana|\bXRP\b|Litecoin|Spot|Money Market|Floating|Duration|Credit|Loan|Volatility|Equal Weight|Low Vol|Value ETF|Growth ETF|Momentum|Quality|Multi-Factor|ESG Aware|Fund of Funds|Enhanced|Weekly|Monthly|Cash', re.I)
# entities that are not exchange-traded thematic funds even when a name matches
EXCLUDE_ENTITY = re.compile(r'WisdomTree Digital|Mutual Fund|Variable', re.I)
EXCLUDE_TICKERS = set()
THEME_OVERRIDES = {
    'ARKK': 'innovation', 'ARKW': 'internet', 'ARKG': 'genomics', 'ARKF': 'fintech', 'ARKQ': 'robotics', 'ARKX': 'space',
    'BOTZ': 'robotics', 'ROBO': 'robotics', 'IRBO': 'robotics', 'AIQ': 'ai', 'CHAT': 'ai', 'THNQ': 'ai', 'IGPT': 'ai', 'WTAI': 'ai',
    'SKYY': 'cloud', 'CLOU': 'cloud', 'WCLD': 'cloud', 'IGV': 'cloud', 'HACK': 'cyber', 'CIBR': 'cyber', 'BUG': 'cyber', 'IHAK': 'cyber',
    'SMH': 'semis', 'SOXX': 'semis', 'XSD': 'semis', 'PSI': 'semis', 'FTXL': 'semis', 'SOXQ': 'semis',
    'ICLN': 'clean-energy', 'TAN': 'clean-energy', 'FAN': 'clean-energy', 'QCLN': 'clean-energy', 'PBW': 'clean-energy', 'ACES': 'clean-energy', 'CNRG': 'clean-energy', 'HYDR': 'clean-energy',
    'LIT': 'ev', 'DRIV': 'ev', 'IDRV': 'ev', 'KARS': 'ev', 'BATT': 'ev', 'URA': 'nuclear', 'URNM': 'nuclear', 'NLR': 'nuclear', 'NUKZ': 'nuclear',
    'UFO': 'space', 'ITA': 'defense', 'PPA': 'defense', 'XAR': 'defense', 'SHLD': 'defense', 'PAVE': 'infrastructure', 'IFRA': 'infrastructure', 'GRID': 'electrification', 'COPX': 'electrification',
    'PHO': 'water', 'CGW': 'water', 'FIW': 'water', 'MSOS': 'cannabis', 'MJ': 'cannabis', 'PAWZ': 'pets', 'BETZ': 'gaming', 'ESPO': 'gaming', 'HERO': 'gaming', 'NERD': 'gaming',
    'BLOK': 'blockchain', 'BKCH': 'blockchain', 'DAPP': 'blockchain', 'WGMI': 'blockchain', 'FINX': 'fintech', 'IPAY': 'fintech', 'ARKF': 'fintech',
    'GNOM': 'genomics', 'IDNA': 'genomics', 'XBI': None, 'IBB': None,
    'DTCR': 'digital-infra', 'SRVR': 'digital-infra', 'FIVG': 'digital-infra', 'SNSR': 'digital-infra', 'QTUM': 'quantum', 'META': 'metaverse', 'METV': 'metaverse',
    'MOO': 'food', 'KROP': 'food', 'HELX': 'health-innovation', 'SLIM': 'health-innovation', 'HEAL': 'health-innovation', 'LNGR': 'longevity',
    'MAGS': None, 'FNGS': None,
}
FORCE = [  # thematic funds whose names carry no theme word in the SEC file
    ('ARKK', 'ARK Innovation ETF', 'innovation'), ('ARKW', 'ARK Next Generation Internet ETF', 'internet'), ('ARKG', 'ARK Genomic Revolution ETF', 'genomics'),
    ('ARKF', 'ARK Fintech Innovation ETF', 'fintech'), ('ARKQ', 'ARK Autonomous Technology & Robotics ETF', 'robotics'), ('ARKX', 'ARK Space Exploration & Innovation ETF', 'space'),
    ('SMH', 'VanEck Semiconductor ETF', 'semis'), ('SOXX', 'iShares Semiconductor ETF', 'semis'), ('XSD', 'SPDR S&P Semiconductor ETF', 'semis'),
    ('IGV', 'iShares Expanded Tech-Software Sector ETF', 'cloud'), ('HACK', 'Amplify Cybersecurity ETF', 'cyber'), ('CIBR', 'First Trust NASDAQ Cybersecurity ETF', 'cyber'),
    ('ITA', 'iShares U.S. Aerospace & Defense ETF', 'defense'), ('PPA', 'Invesco Aerospace & Defense ETF', 'defense'), ('XAR', 'SPDR S&P Aerospace & Defense ETF', 'defense'),
    ('LIT', 'Global X Lithium & Battery Tech ETF', 'ev'), ('URA', 'Global X Uranium ETF', 'nuclear'), ('URNM', 'Sprott Uranium Miners ETF', 'nuclear'), ('NLR', 'VanEck Uranium and Nuclear ETF', 'nuclear'),
    ('PAVE', 'Global X U.S. Infrastructure Development ETF', 'infrastructure'), ('IFRA', 'iShares U.S. Infrastructure ETF', 'infrastructure'), ('COPX', 'Global X Copper Miners ETF', 'electrification'),
    ('PHO', 'Invesco Water Resources ETF', 'water'), ('CGW', 'Invesco S&P Global Water Index ETF', 'water'), ('FIW', 'First Trust Water ETF', 'water'),
    ('TAN', 'Invesco Solar ETF', 'clean-energy'), ('ICLN', 'iShares Global Clean Energy ETF', 'clean-energy'), ('QCLN', 'First Trust NASDAQ Clean Edge Green Energy Index Fund', 'clean-energy'), ('PBW', 'Invesco WilderHill Clean Energy ETF', 'clean-energy'),
    ('SKYY', 'First Trust Cloud Computing ETF', 'cloud'), ('CLOU', 'Global X Cloud Computing ETF', 'cloud'), ('WCLD', 'WisdomTree Cloud Computing Fund', 'cloud'),
    ('BOTZ', 'Global X Robotics & Artificial Intelligence ETF', 'robotics'), ('ROBO', 'ROBO Global Robotics & Automation Index ETF', 'robotics'), ('AIQ', 'Global X Artificial Intelligence & Technology ETF', 'ai'),
    ('BLOK', 'Amplify Transformational Data Sharing ETF', 'blockchain'), ('BKCH', 'Global X Blockchain ETF', 'blockchain'), ('DAPP', 'VanEck Digital Transformation ETF', 'blockchain'), ('WGMI', 'CoinShares Bitcoin Mining ETF', 'blockchain'),
    ('FINX', 'Global X FinTech ETF', 'fintech'), ('IPAY', 'Amplify Mobile Payments ETF', 'fintech'), ('GNOM', 'Global X Genomics & Biotechnology ETF', 'genomics'), ('IDNA', 'iShares Genomics Immunology and Healthcare ETF', 'genomics'),
    ('ESPO', 'VanEck Video Gaming and eSports ETF', 'gaming'), ('HERO', 'Global X Video Games & Esports ETF', 'gaming'), ('BETZ', 'Roundhill Sports Betting & iGaming ETF', 'gaming'),
    ('UFO', 'Procure Space ETF', 'space'), ('MSOS', 'AdvisorShares Pure US Cannabis ETF', 'cannabis'), ('PAWZ', 'ProShares Pet Care ETF', 'pets'), ('DRIV', 'Global X Autonomous & Electric Vehicles ETF', 'ev'),
    ('SRVR', 'Pacer Data & Infrastructure Real Estate ETF', 'digital-infra'), ('DTCR', 'Global X Data Center & Digital Infrastructure ETF', 'digital-infra'), ('QTUM', 'Defiance Quantum ETF', 'quantum'),
    ('GRID', 'First Trust NASDAQ Clean Edge Smart Grid Infrastructure Index Fund', 'electrification'), ('SHLD', 'Global X Defense Tech ETF', 'defense'), ('NUKZ', 'Range Nuclear Renaissance Index ETF', 'nuclear'),
    ('MOO', 'VanEck Agribusiness ETF', 'food'), ('CHAT', 'Roundhill Generative AI & Technology ETF', 'ai'), ('IGPT', 'Invesco AI and Next Gen Software ETF', 'ai'), ('WTAI', 'WisdomTree Artificial Intelligence and Innovation Fund', 'ai'),
    ('IRBO', 'iShares Future AI & Robotics ETF', 'robotics'), ('THNQ', 'ROBO Global Artificial Intelligence ETF', 'ai'), ('IHAK', 'iShares Cybersecurity and Tech ETF', 'cyber'), ('BUG', 'Global X Cybersecurity ETF', 'cyber'),
    ('KARS', 'KraneShares Electric Vehicles and Future Mobility Index ETF', 'ev'), ('IDRV', 'iShares Self-Driving EV and Tech ETF', 'ev'), ('BATT', 'Amplify Lithium & Battery Technology ETF', 'ev'), ('FAN', 'First Trust Global Wind Energy ETF', 'clean-energy'),
    ('HYDR', 'Global X Hydrogen ETF', 'clean-energy'), ('ACES', 'ALPS Clean Energy ETF', 'clean-energy'), ('CNRG', 'SPDR S&P Kensho Clean Power ETF', 'clean-energy'), ('METV', 'Roundhill Ball Metaverse ETF', 'metaverse'),
    ('DFEN', 'Direxion Daily Aerospace & Defense Bull 3X Shares', None), ('FIVG', 'Defiance Next Gen Connectivity ETF', 'digital-infra'), ('SNSR', 'Global X Internet of Things ETF', 'digital-infra'),
    ('HELX', 'Franklin Genomic Advancements ETF', 'genomics'), ('LNGR', 'Global X Longevity Thematic ETF', 'longevity'), ('KROP', 'Global X AgTech & Food Innovation ETF', 'food'), ('NERD', 'Roundhill Video Games ETF', 'gaming'),
    ('MJ', 'Amplify Alternative Harvest ETF', 'cannabis'), ('PSI', 'Invesco Semiconductors ETF', 'semis'), ('FTXL', 'First Trust Nasdaq Semiconductor ETF', 'semis'), ('SOXQ', 'Invesco PHLX Semiconductor ETF', 'semis'),
]
# listed and trading per Tiingo's ticker list but absent from the SEC series file (swept 2026-09-05); holdings arrive with each fund's first N-PORT
TIINGO_EXTRA = [
    ('AIEQ', 'Amplify AI Powered Equity ETF', 'ai'),
    ('AIHY', 'Defiance AI Hyperscale Leaders ETF', 'ai'),
    ('AINF', 'Defiance Inference AI Chip ETF', 'ai'),
    ('AIX', 'Defiance US 100 Tech AI Moat ETF', 'ai'),
    ('ANTW', 'Anthropic AI Lab Ecosystem ETF', 'ai'),
    ('BAI', 'iShares A.I. Innovation and Tech Active ETF', 'ai'),
    ('CAPA', 'Defiance AI Capacitors Leaders ETF', 'ai'),
    ('CGPT', 'VegaShares AI Inference ETF', 'ai'),
    ('COOL', 'VegaShares AI Thermal Cooling & Power Management ETF', 'ai'),
    ('DEPW', 'Google DeepMind AI Lab Ecosystem ETF', 'ai'),
    ('HIAI', 'Ai Funds High Conviction US Equity AI-Managed ETF', 'ai'),
    ('HLTH', 'Tema Healthcare AI ETF', 'ai'),
    ('KAIT', 'KraneShares Asia AI Technology ETF', 'ai'),
    ('MTAW', 'Meta AI Lab Ecosystem ETF', 'ai'),
    ('PBOT', 'Pictet AI & Automation ETF', 'ai'),
    ('PHOX', 'Aura AI Photonics ETF', 'ai'),
    ('TGRZ', 'China AI Tigers LLM ETF', 'ai'),
    ('RAYS', 'Global X Solar ETF', 'clean-energy'),
    ('WNDY', 'Global X Wind Energy ETF', 'clean-energy'),
    ('XIGV', 'Defiance US 100 Tech Ex Software ETF', 'cloud'),
    ('AMMO', 'VistaShares Defense Supercycle ETF', 'defense'),
    ('IDEF', 'iShares Defense Industrials Active ETF', 'defense'),
    ('TSSD', 'Truth Social American Security & Defense ETF', 'defense'),
    ('BYTE', 'Roundhill IO Digital Infrastructure ETF', 'digital-infra'),
    ('COPJ', 'Sprott Junior Copper Miners ETF', 'electrification'),
    ('COPP', 'Sprott Copper Miners ETF', 'electrification'),
    ('ELFY', 'ALPS Electrification Infrastructure ETF', 'electrification'),
    ('KWH', 'GMO Power Infrastructure ETF', 'electrification'),
    ('PWRZ', 'TrueShares Eagle Global Next Gen Power Infrastructure ETF', 'electrification'),
    ('CABZ', 'Roundhill Robotaxi Autonomous Vehicles & Technology ETF', 'ev'),
    ('LITP', 'Sprott Lithium Miners ETF', 'ev'),
    ('GAMR', 'Amplify Video Game Tech ETF', 'gaming'),
    ('XDNA', 'Kelly CRISPR & Gene Editing Technology ETF', 'genomics'),
    ('THNR', 'Amplify Weight Loss Drug & Treatment ETF', 'health-innovation'),
    ('INFR', 'ClearBridge Sustainable Infrastructure ETF', 'infrastructure'),
    ('BMED', 'BlackRock Future Health ETF', 'innovation'),
    ('KGRO', 'KraneShares China Innovation ETF', 'innovation'),
    ('QQJG', 'Invesco ESG NASDAQ Next Gen 100 ETF', 'innovation'),
    ('EWEB', 'Global X Emerging Markets Internet & E-commerce ETF', 'internet'),
    ('TNUK', 'Tortoise Nuclear Renaissance ETF', 'nuclear'),
    ('URNJ', 'Sprott Junior Uranium Miners ETF', 'nuclear'),
    ('AWAY', 'Amplify Travel Tech ETF', 'pets'),
    ('CROB', 'Defiance China Robotics ETF', 'robotics'),
    ('RTOO', 'VistaShares Robotics Supercycle ETF', 'robotics'),
    ('FSPC', 'First Trust Bloomberg Space Economy ETF', 'space'),
    ('GALX', 'VistaShares Space Supercycle ETF', 'space'),
    ('WSPC', 'WisdomTree Space Economy Fund', 'space'),
]
THEME_NAME = {k: n for k, n, _ in THEMES}


def theme_of(name):
    for key, _, pat in THEMES:
        if re.search(pat, name):
            return key
    return None


def build():
    rows = list(csv.DictReader(open(iu.sec_file(), encoding='utf-8-sig', errors='replace')))
    out, seen = [], set()
    for x in rows:
        tk = (x.get('Class Ticker') or '').strip().upper()
        name = re.sub(r'\s+', ' ', (x.get('Class Name') or '').strip())
        entity = (x.get('Entity Name') or '').strip()
        if not tk or tk in seen or not re.fullmatch(r'[A-Z]{2,5}', tk) or (len(tk) == 5 and tk.endswith('X')):
            continue
        if EXCLUDE_ENTITY.search(entity):
            continue
        theme = theme_of(name)
        if tk in THEME_OVERRIDES:
            theme = THEME_OVERRIDES[tk]
        if not theme:
            continue
        if EXCLUDE.search(name) and tk not in THEME_OVERRIDES:
            continue
        if tk in EXCLUDE_TICKERS:
            continue
        seen.add(tk)
        out.append({'ticker': tk, 'name': name, 'issuer': iu.issuer_of(name, entity), 'entity': entity, 'cik': str(int(x['CIK Number'])),
                    'seriesId': (x.get('Series ID') or '').strip(), 'theme': theme, 'themeName': THEME_NAME[theme], 'include': True,
                    'why': 'theme word in the name' if tk not in THEME_OVERRIDES else 'theme assigned by hand'})
    by_name = {re.sub(r'[^a-z0-9]', '', r['name'].lower()): r for r in out}
    for tk, name, theme in FORCE:
        if tk in seen or theme is None:
            continue
        # find the SEC row by ticker (no theme word in the name) to carry the series id
        row = next((x for x in rows if (x.get('Class Ticker') or '').strip().upper() == tk), None)
        seen.add(tk)
        out.append({'ticker': tk, 'name': (row['Class Name'].strip() if row else name), 'issuer': iu.issuer_of(name, row['Entity Name'] if row else ''),
                    'entity': (row['Entity Name'].strip() if row else ''), 'cik': (str(int(row['CIK Number'])) if row else ''), 'seriesId': ((row.get('Series ID') or '').strip() if row else ''),
                    'theme': theme, 'themeName': THEME_NAME[theme], 'include': True, 'why': 'forced: thematic fund with no theme word in the name'})
    for tk, name, theme in TIINGO_EXTRA:
        if tk in seen:
            continue
        seen.add(tk)
        out.append({'ticker': tk, 'name': name, 'issuer': iu.issuer_of(name, ''), 'entity': '', 'cik': '', 'seriesId': '', 'theme': theme, 'themeName': THEME_NAME[theme], 'include': True,
                    'why': 'listed per Tiingo, absent from the SEC series file'})
    out.sort(key=lambda r: (r['themeName'], r['issuer'], r['ticker']))
    (ROOT / 'data').mkdir(exist_ok=True)
    (ROOT / 'data' / 'thematic_universe.json').write_text(json.dumps(out, indent=1))
    from collections import Counter
    print(f'{len(out)} thematic funds', file=sys.stderr)
    print(Counter(r['themeName'] for r in out).most_common(), file=sys.stderr)
    return out


if __name__ == '__main__':
    build()
