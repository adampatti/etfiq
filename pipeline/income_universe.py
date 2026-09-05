#!/usr/bin/env python3
"""Build the option-income ETF universe for the income desk.

Source: the SEC's yearly investment company series and class file, which lists every registered fund with its
ticker. Option-income funds are identified by name (covered call, premium income, option income, 0DTE,
YieldMax, YieldBOOST, Target 15 and so on), restricted to ETF-style tickers, and each is given a strategy tag
and a benchmark: the index or stock the fund writes options on, which is what "am I ahead" compares against.

Output: data/income_universe.json, one record per fund:
  ticker, name, issuer, cik, strategy, benchmark, benchmarkName, benchmarkKind (index | stock | proxy), include, why

`include` is the launch filter; `why` says which rule fired so the list can be reviewed by hand. Edit the
OVERRIDES table for anything the rules get wrong.

Usage: python3 pipeline/income_universe.py [--year 2026]
"""
import csv
import datetime
import io
import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTACT = os.environ.get('ETFIQ_CONTACT', 'admin@etfiq.com')

INCLUDE = re.compile(r'covered call|premium income|option income|options income|option strategy|yieldmax|yieldboost|yield premium|'
                     r'0dte|daily option|weekly option|buywrite|buy-write|call writ|target 15|enhanced income|income strategy|'
                     r'high income|dynamic income|premium yield|call overlay|option overlay|income advantage|equity income|dividend income|'
                     r'super income|max income|monthly income|weekly income|weekly pay|weekly distribution|monthly distribution|'
                     r'enhanced yield|income etf|innovation income|barrier|defined income|target income|risk-managed income|advantage large cap income', re.I)
EXCLUDE = re.compile(r'municipal|muni\b|bond|treasury|fixed income|mortgage|credit|floating|loan|preferred|money market|'
                     r'tax[- ]exempt|government|inflation|short duration|core plus|multi-?sector|real estate|reit|mlp|'
                     r'variable insurance|portfolio\b.*(class|fund)$|convertible|senior|bank loan|ultra short|ladder|'
                     r'hedged equity|balanced|allocation|target date|retirement|lifestyle|freedom|managed payout|'
                     r'closed-end|interval|series [a-z]$', re.I)
# entities that are ETF trusts or hold option-income ETFs; everything else needs an ETF-style ticker and a strong keyword
ETF_TRUST = re.compile(r'ETF|Exchange[- ]?Traded|Exchange Listed|Listed Funds|Tidal Trust|Global X Funds|iShares Trust|SPDR|'
                       r'Series Trust|ProShares Trust|Direxion|KraneShares|Simplify|Pacer|Innovator|Roundhill|Amplify|NEOS|REX|'
                       r'GraniteShares|Defiance|Kurv|YieldMax|VistaShares|Goldman Sachs ETF|J\.P\. Morgan Exchange|'
                       r'First Trust Exchange|Nationwide|Elevation|World Funds|Themes|Bitwise|Volatility Shares|Tema|'
                       r'Northern Lights|Two Roads|Collaborative|Unified|Capitol|EA Series|Investment Managers Series|Advisors Series', re.I)
STRONG = re.compile(r'covered call|premium income|option income|options income|option strategy|yieldmax|yieldboost|yield premium|'
                    r'0dte|buywrite|buy-write|call writ|target 15|income strategy|premium yield|call overlay|option overlay|'
                    r'super income|max income|weekly pay|enhanced income|defined income|target income|high income', re.I)

ISSUER_RULES = [  # (name regex, issuer)
    (r'^YieldMax', 'YieldMax'), (r'^Defiance', 'Defiance'), (r'^Roundhill', 'Roundhill'), (r'^REX ', 'REX'), (r'^GraniteShares', 'GraniteShares'),
    (r'^Kurv', 'Kurv'), (r'^NEOS', 'NEOS'), (r'^Global X', 'Global X'), (r'^JPMorgan', 'JPMorgan'), (r'^Goldman Sachs', 'Goldman Sachs'),
    (r'^iShares', 'iShares'), (r'^Amplify', 'Amplify'), (r'^FT Vest|^First Trust', 'First Trust'), (r'^Innovator', 'Innovator'),
    (r'^VistaShares', 'VistaShares'), (r'^ProShares', 'ProShares'), (r'^Nationwide', 'Nationwide'), (r'^Pacer', 'Pacer'),
    (r'^Simplify', 'Simplify'), (r'^KraneShares', 'KraneShares'), (r'^Bitwise', 'Bitwise'), (r'^TappAlpha', 'TappAlpha'),
    (r'^Zega', 'Zega'), (r'^Madison', 'Madison'), (r'^Cboe Vest', 'Cboe Vest'), (r'^Infrastructure Capital', 'Infrastructure Capital'),
    (r'^Tidal', 'Tidal'), (r'^Direxion', 'Direxion'), (r'^Themes', 'Themes'), (r'^Nuveen', 'Nuveen'), (r'^Fidelity', 'Fidelity'),
    (r'^SPDR', 'State Street'), (r'^Invesco', 'Invesco'), (r'^BlackRock', 'BlackRock'), (r'^Franklin', 'Franklin'), (r'^Schwab', 'Schwab'),
    (r'^Vanguard', 'Vanguard'), (r'^Calamos', 'Calamos'), (r'^AllianzIM', 'AllianzIM'), (r'^Bancreek', 'Bancreek'), (r'^Tema', 'Tema'),
    (r'^State Street', 'State Street'), (r'^FT ', 'First Trust'), (r'^Grayscale', 'Grayscale'), (r'^Tuttle', 'Tuttle'), (r'^DailyDelta', 'DailyDelta'),
]
KNOWN_OPTION_ISSUERS = {'YieldMax', 'GraniteShares', 'First Trust', 'Global X', 'NEOS', 'VistaShares', 'REX', 'Roundhill', 'Bitwise', 'Defiance',
                        'Amplify', 'Grayscale', 'JPMorgan', 'ProShares', 'Goldman Sachs', 'KraneShares', 'iShares', 'Kurv', 'Innovator',
                        'Nationwide', 'Pacer', 'Simplify', 'Madison', 'TappAlpha', 'Zega', 'Cboe Vest', 'Infrastructure Capital', 'Tidal',
                        'State Street', 'Invesco', 'Calamos', 'Tuttle', 'DailyDelta', 'Direxion', 'Themes', 'Bancreek', 'AdvisorShares'}
UNAMBIGUOUS = re.compile(r'covered call|option income|options income|option strategy|yieldmax|yieldboost|yield premium|0dte|buywrite|buy-write|'
                         r'call writ|target 15|premium income|income strategy|call overlay|option overlay|risk-managed income|advantage large cap income', re.I)

BENCH_RULES = [  # (name regex, benchmark ticker, benchmark name, kind)
    (r'S&P ?500|SPY\b|Large ?Cap Core Premium|Equity Premium Income ETF$', 'SPY', 'S&P 500 (SPY)', 'index'),
    (r'Nasdaq|NASDAQ|QQQ', 'QQQ', 'Nasdaq-100 (QQQ)', 'index'),
    (r'Russell 2000|Small ?Cap|IWM\b', 'IWM', 'Russell 2000 (IWM)', 'index'),
    (r'Dow|DJIA', 'DIA', 'Dow Jones Industrial Average (DIA)', 'index'),
    (r'Equal Weight', 'RSP', 'S&P 500 Equal Weight (RSP)', 'index'),
    (r'Bitcoin|BTC\b', 'IBIT', 'Bitcoin (IBIT)', 'proxy'),
    (r'Ether\b|Ethereum|ETH\b', 'ETHA', 'Ether (ETHA)', 'proxy'),
    (r'Gold\b', 'GLD', 'Gold (GLD)', 'proxy'),
    (r'Silver\b', 'SLV', 'Silver (SLV)', 'proxy'),
    (r'Treasury|TLT\b|20\+ Year', 'TLT', '20+ Year Treasury (TLT)', 'index'),
    (r'Emerging', 'EEM', 'Emerging Markets (EEM)', 'index'),
    (r'International|EAFE|Developed', 'EFA', 'Developed Markets ex US (EFA)', 'index'),
    (r'Magnificent|MAG ?7|Mag7', 'QQQ', 'Nasdaq-100 (QQQ), used as the Magnificent Seven proxy', 'proxy'),
    (r'Semiconductor|SMH\b', 'SMH', 'Semiconductors (SMH)', 'index'),
    (r'Berkshire', 'BRK-B', 'Berkshire Hathaway (BRK.B)', 'stock'),
    (r'Low Volatility', 'USMV', 'USA Min Vol (USMV), used as the low volatility proxy', 'proxy'),
    (r'Momentum', 'MTUM', 'USA Momentum (MTUM), used as the momentum proxy', 'proxy'),
    (r'Quality', 'QUAL', 'USA Quality (QUAL), used as the quality proxy', 'proxy'),
    (r'Value', 'VLUE', 'USA Value (VLUE), used as the value proxy', 'proxy'),
    (r'Dividend Aristocrat', 'NOBL', 'S&P 500 Dividend Aristocrats (NOBL)', 'index'),
    (r'Innovation|FANG|Tech', 'QQQ', 'Nasdaq-100 (QQQ), used as the technology proxy', 'proxy'),
]
STOCK_NAMES = {  # words that name a single stock in fund names
    'TSLA': 'Tesla', 'NVDA': 'NVIDIA', 'AAPL': 'Apple', 'AMZN': 'Amazon', 'GOOGL': 'Alphabet', 'GOOG': 'Alphabet', 'MSFT': 'Microsoft',
    'META': None, 'NFLX': 'Netflix', 'AMD': 'AMD', 'COIN': 'Coinbase', 'MSTR': 'MicroStrategy', 'PLTR': 'Palantir', 'DIS': 'Disney',
    'JPM': None, 'XOM': 'Exxon', 'PYPL': 'PayPal', 'SQ': None, 'ABNB': 'Airbnb', 'SNOW': 'Snowflake', 'AI': None,
    'MRNA': 'Moderna', 'BABA': 'Alibaba', 'SMCI': 'Super Micro', 'MU': 'Micron', 'AVGO': 'Broadcom', 'CRWD': 'CrowdStrike',
    'HOOD': 'Robinhood', 'SHOP': 'Shopify', 'UBER': None, 'BRK': 'Berkshire', 'ARM': None, 'INTC': 'Intel', 'TSM': 'TSMC',
    'ORCL': 'Oracle', 'MARA': 'MARA', 'RIOT': 'Riot', 'GME': 'GameStop', 'ASML': 'ASML', 'LLY': 'Eli Lilly', 'BA': None,
    'GS': None, 'JNJ': 'Johnson & Johnson', 'WMT': 'Walmart', 'COST': 'Costco', 'CVX': 'Chevron', 'PFE': 'Pfizer',
    'F': None, 'GM': None, 'RIVN': 'Rivian', 'LCID': 'Lucid', 'SOFI': 'SoFi', 'CRM': 'Salesforce', 'NKE': 'Nike', 'SBUX': 'Starbucks',
    'CVNA': 'Carvana', 'RDDT': 'Reddit', 'APP': None, 'CEG': None, 'VST': None, 'SPOT': 'Spotify', 'GRNY': None,
    'NUKZ': None, 'BMNR': 'Bitmine', 'OKLO': 'Oklo', 'IONQ': 'IonQ', 'RKLB': 'Rocket Lab', 'ACHR': 'Archer', 'JOBY': 'Joby', 'CRCL': None,
    'UNH': 'UnitedHealth', 'ADBE': 'Adobe', 'NOW': None, 'BRKB': 'Berkshire', 'MSTX': None, 'ELI': 'Eli Lilly', 'NVO': 'Novo Nordisk',
}
FORCE = [  # funds whose names do not carry a strategy keyword in the SEC file
    {'ticker': 'SIOO', 'name': 'VistaShares Target 15 S&P 100 Distribution ETF', 'issuer': 'VistaShares', 'entity': 'VistaShares', 'cik': '', 'strategy': 'Target 15 distribution, options overlay', 'benchmark': 'OEF', 'benchmarkName': 'S&P 100 (OEF)', 'benchmarkKind': 'index', 'include': True, 'why': 'forced: listed and trading, SEC series file carries no ticker yet'},
    {'ticker': 'ACKY', 'name': 'VistaShares Target 15 ACKtivist Distribution ETF', 'issuer': 'VistaShares', 'entity': 'Tidal Trust III', 'cik': '0001722388', 'strategy': 'Target 15 distribution, options overlay', 'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY), used as the proxy', 'benchmarkKind': 'proxy', 'include': True, 'why': 'forced: listed and trading, SEC series file carries no ticker yet'},
    {'ticker': 'DRKY', 'name': 'VistaShares Target 15 DRUKMacro Distribution ETF', 'issuer': 'VistaShares', 'entity': 'Tidal Trust III', 'cik': '0001722388', 'strategy': 'Target 15 distribution, options overlay', 'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY), used as the proxy', 'benchmarkKind': 'proxy', 'include': True, 'why': 'forced: listed and trading, SEC series file carries no ticker yet'},
    {'ticker': 'TPRY', 'name': 'VistaShares Target 15 TEPRTantrum Contrarian Distribution ETF', 'issuer': 'VistaShares', 'entity': 'Tidal Trust III', 'cik': '0001722388', 'strategy': 'Target 15 distribution, options overlay', 'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY), used as the proxy', 'benchmarkKind': 'proxy', 'include': True, 'why': 'forced: listed and trading, SEC series file carries no ticker yet'},
    {'ticker': 'BALI', 'name': 'iShares Advantage Large Cap Income ETF', 'issuer': 'iShares', 'entity': 'iShares Trust', 'cik': '1100663', 'strategy': 'covered call', 'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index', 'include': True, 'why': 'forced: known option-income fund'},
    {'ticker': 'NUSI', 'name': 'Nationwide Nasdaq-100 Risk-Managed Income ETF', 'issuer': 'Nationwide', 'entity': 'Nationwide Mutual Funds', 'cik': '1048702', 'strategy': 'covered call', 'benchmark': 'QQQ', 'benchmarkName': 'Nasdaq-100 (QQQ)', 'benchmarkKind': 'index', 'include': True, 'why': 'forced: known option-income fund'},
    {'ticker': 'NSPI', 'name': 'Nationwide S&P 500 Risk-Managed Income ETF', 'issuer': 'Nationwide', 'entity': 'Nationwide Mutual Funds', 'cik': '1048702', 'strategy': 'covered call', 'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index', 'include': True, 'why': 'forced: known option-income fund'},
    {'ticker': 'NDJI', 'name': 'Nationwide Dow Jones Risk-Managed Income ETF', 'issuer': 'Nationwide', 'entity': 'Nationwide Mutual Funds', 'cik': '1048702', 'strategy': 'covered call', 'benchmark': 'DIA', 'benchmarkName': 'Dow Jones Industrial Average (DIA)', 'benchmarkKind': 'index', 'include': True, 'why': 'forced: known option-income fund'},
    {'ticker': 'NTKI', 'name': 'Nationwide Russell 2000 Risk-Managed Income ETF', 'issuer': 'Nationwide', 'entity': 'Nationwide Mutual Funds', 'cik': '1048702', 'strategy': 'covered call', 'benchmark': 'IWM', 'benchmarkName': 'Russell 2000 (IWM)', 'benchmarkKind': 'index', 'include': True, 'why': 'forced: known option-income fund'},
]
OVERRIDES = {  # ticker: dict of fields to force
    'OMAH': {'benchmark': 'BRK-B', 'benchmarkName': 'Berkshire Hathaway B (BRK-B), used as the proxy', 'benchmarkKind': 'proxy', 'strategy': 'Target 15 distribution, options overlay'},
    'GATE': {'include': False, 'why': 'excluded: fund not launched; the price history under this ticker belongs to a prior security (issuer confirmed 2026-09-05)'},
    # single-stock funds the name rules miss: class-share tickers, short products, Tuttle 0DTE names
    'BRKC': {'benchmark': 'BRK-B', 'benchmarkName': 'Berkshire Hathaway B (BRK-B)', 'benchmarkKind': 'stock', 'strategy': 'single-stock option income'},
    'CRSH': {'benchmark': 'TSLA', 'benchmarkName': 'Tesla (TSLA)', 'benchmarkKind': 'stock', 'strategy': 'short single-stock option income'},
    'DIPS': {'benchmark': 'NVDA', 'benchmarkName': 'NVIDIA (NVDA)', 'benchmarkKind': 'stock', 'strategy': 'short single-stock option income'},
    'FIAT': {'benchmark': 'COIN', 'benchmarkName': 'Coinbase (COIN)', 'benchmarkKind': 'stock', 'strategy': 'short single-stock option income'},
    'MSTK': {'benchmark': 'MSTR', 'benchmarkName': 'Strategy (MSTR)', 'benchmarkKind': 'stock', 'strategy': '0DTE single-stock covered call'},
    'NVDL': {'benchmark': 'NVDA', 'benchmarkName': 'NVIDIA (NVDA)', 'benchmarkKind': 'stock', 'strategy': '0DTE single-stock covered call'},
    'JEPI': {'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index', 'strategy': 'covered call'},
    'JEPQ': {'benchmark': 'QQQ', 'benchmarkName': 'Nasdaq-100 (QQQ)', 'benchmarkKind': 'index', 'strategy': 'covered call'},
    'DIVO': {'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'proxy', 'strategy': 'dividend stocks with call overlay', 'include': True},
    'IDVO': {'benchmark': 'EFA', 'benchmarkName': 'Developed Markets ex US (EFA)', 'benchmarkKind': 'proxy', 'include': True},
    'SPYI': {'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index'},
    'QQQI': {'benchmark': 'QQQ', 'benchmarkName': 'Nasdaq-100 (QQQ)', 'benchmarkKind': 'index'},
    'IWMI': {'benchmark': 'IWM', 'benchmarkName': 'Russell 2000 (IWM)', 'benchmarkKind': 'index'},
    'GPIX': {'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index'},
    'GPIQ': {'benchmark': 'QQQ', 'benchmarkName': 'Nasdaq-100 (QQQ)', 'benchmarkKind': 'index'},
    'XDTE': {'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index', 'strategy': '0DTE covered call'},
    'QDTE': {'benchmark': 'QQQ', 'benchmarkName': 'Nasdaq-100 (QQQ)', 'benchmarkKind': 'index', 'strategy': '0DTE covered call'},
    'RDTE': {'benchmark': 'IWM', 'benchmarkName': 'Russell 2000 (IWM)', 'benchmarkKind': 'index', 'strategy': '0DTE covered call'},
    'BALI': {'benchmark': 'SPY', 'benchmarkName': 'S&P 500 (SPY)', 'benchmarkKind': 'index', 'include': True},
    'KNG': {'benchmark': 'NOBL', 'benchmarkName': 'S&P 500 Dividend Aristocrats (NOBL)', 'benchmarkKind': 'index', 'include': True},
}


def issuer_of(name, entity):
    for pat, iss in ISSUER_RULES:
        if re.search(pat, name):
            return iss
    m = re.match(r'^([A-Z][A-Za-z&\.]+)', name)
    return m.group(1) if m else entity.title()


def strategy_of(name):
    n = name.lower()
    if '0dte' in n or 'daily option' in n or 'daily covered' in n: return '0DTE covered call'
    if 'yieldmax' in n or 'option income strategy' in n or 'yield premium' in n or 'yieldboost' in n or 'synthetic' in n: return 'synthetic covered call'
    if 'dual directional' in n or 'barrier' in n: return 'defined income'
    if 'buffer' in n and 'income' in n: return 'buffer with income'
    if 'covered call' in n or 'buywrite' in n or 'buy-write' in n or 'call writ' in n: return 'covered call'
    if 'premium income' in n or 'enhanced income' in n or 'target 15' in n or 'high income' in n or 'premium yield' in n: return 'covered call'
    if 'dividend' in n: return 'dividend stocks with call overlay'
    return 'option income'


def benchmark_of(name):
    for tk, label in STOCK_NAMES.items():
        if re.search(r'\b' + re.escape(tk) + r'\b', name) or (label and re.search(r'\b' + re.escape(label) + r'\b', name)):
            t = {'BRK': 'BRK-B', 'BRKB': 'BRK-B', 'GOOG': 'GOOGL'}.get(tk, tk)
            return t, f'{label or tk} ({tk})', 'stock'
    for pat, tk, label, kind in BENCH_RULES:
        if re.search(pat, name, re.I):
            return tk, label, kind
    return 'SPY', 'S&P 500 (SPY), used as a default proxy', 'proxy'


SINGLE_PATTERNS = [
    r'YieldMax(?:\(R\)|™)?\s+([A-Z]{1,5})\s+Option', r'YieldMax(?:\(R\)|™)?\s+Short\s+([A-Z]{1,5})\s+Option', r'YieldMax(?:\(R\)|™)?\s+([A-Z]{1,5})\s+Short\s+Option', r'YieldMax(?:\(R\)|™)?\s+(BRK)\.B\s+Option', r'Tuttle Capital\s+([A-Z]{1,5})\s+0DTE', r'YieldBOOST\s+([A-Z]{1,5})\b', r'Kurv[^()]*\(([A-Z]{1,5})\)',
    r'Defiance\s+([A-Z]{1,5})\s+(?:Option|Daily|Weekly)', r'Bitwise\s+([A-Z]{1,5})\s+Option', r'Roundhill\s+([A-Z]{1,5})\s+WeeklyPay',
    r'REX\s+([A-Z]{1,5})\s+(?:Growth|Income|Premium)', r'Tuttle[^()]*\(([A-Z]{1,5})\)', r'\(([A-Z]{2,5})\)\s*(?:ETF)?$',
]
TOKEN_SKIP = {'ETF', 'US', 'USA', 'SP', 'SPX', 'NDX', 'DJIA', 'BTC', 'ETH', 'SOL', 'XRP'}
TICKER_FIX = {'GOOG': 'GOOGL', 'BRK': 'BRK-B', 'BRKB': 'BRK-B', 'FB': 'META'}
INDEX_RULES = [
    (r'Bitcoin|\bBTC\b', 'IBIT', 'Bitcoin (IBIT)', 'proxy'), (r'Ether\b|Ethereum|\bETH\b', 'ETHA', 'Ether (ETHA)', 'proxy'),
    (r'Solana|\bSOL\b|XRP|Crypto|Blockchain', 'BITQ', 'Crypto industry (BITQ), used as the crypto proxy', 'proxy'),
    (r'R2000|Russell 2000|Small ?Cap', 'IWM', 'Russell 2000 (IWM)', 'index'), (r'Q100|Nasdaq|NASDAQ|QQQ', 'QQQ', 'Nasdaq-100 (QQQ)', 'index'),
    (r'Equal Weight', 'RSP', 'S&P 500 Equal Weight (RSP)', 'index'), (r'Mid ?Cap', 'MDY', 'S&P MidCap 400 (MDY)', 'index'),
    (r'Dow\b|DJIA', 'DIA', 'Dow Jones Industrial Average (DIA)', 'index'), (r'Magnificent|MAG ?7|Mag7', 'MAGS', 'Magnificent Seven (MAGS)', 'index'),
    (r'Semiconductor', 'SMH', 'Semiconductors (SMH)', 'index'), (r'Gold Miner', 'GDX', 'Gold miners (GDX)', 'index'), (r'Gold\b', 'GLD', 'Gold (GLD)', 'proxy'),
    (r'Silver\b', 'SLV', 'Silver (SLV)', 'proxy'), (r'Energy|\bOil\b|Petroleum|Midstream|MLP', 'XLE', 'Energy sector (XLE), used as the energy proxy', 'proxy'),
    (r'Financial', 'XLF', 'Financials sector (XLF)', 'proxy'), (r'Utilit', 'XLU', 'Utilities sector (XLU)', 'proxy'), (r'Health', 'XLV', 'Health care sector (XLV)', 'proxy'),
    (r'Technology|\bTech\b', 'XLK', 'Technology sector (XLK)', 'proxy'), (r'Consumer', 'XLY', 'Consumer discretionary (XLY)', 'proxy'),
    (r'Industrial', 'XLI', 'Industrials (XLI)', 'proxy'), (r'Communication', 'XLC', 'Communication services (XLC)', 'proxy'), (r'Material', 'XLB', 'Materials (XLB)', 'proxy'),
    (r'\bAI\b|Artificial Intelligence', 'AIQ', 'AI and technology (AIQ), used as the AI proxy', 'proxy'), (r'Innovation|FANG', 'QQQ', 'Nasdaq-100 (QQQ), used as the innovation proxy', 'proxy'),
    (r'Aristocrat', 'NOBL', 'S&P 500 Dividend Aristocrats (NOBL)', 'index'), (r'Dividend', 'SCHD', 'US dividend stocks (SCHD), used as the dividend proxy', 'proxy'),
    (r'Treasury|\bTLT\b|20\+ Year', 'TLT', '20+ Year Treasury (TLT)', 'index'), (r'Emerging', 'EEM', 'Emerging Markets (EEM)', 'index'),
    (r'Europe', 'VGK', 'Europe (VGK)', 'index'), (r'Japan', 'EWJ', 'Japan (EWJ)', 'index'), (r'China', 'FXI', 'China large caps (FXI)', 'index'),
    (r'International|EAFE|Developed', 'EFA', 'Developed Markets ex US (EFA)', 'index'), (r'Global|World', 'ACWI', 'All-country world (ACWI)', 'index'),
    (r'Berkshire', 'BRK-B', 'Berkshire Hathaway (BRK.B)', 'stock'), (r'Low Volatility', 'USMV', 'USA Min Vol (USMV), used as the low volatility proxy', 'proxy'),
    (r'Momentum', 'MTUM', 'USA Momentum (MTUM), used as the momentum proxy', 'proxy'), (r'Quality', 'QUAL', 'USA Quality (QUAL), used as the quality proxy', 'proxy'),
    (r'Value', 'VLUE', 'USA Value (VLUE), used as the value proxy', 'proxy'),
    (r'S&P ?500|SPY\b|U\.?S\.? Stocks|U\.?S\.? Equity|Large ?Cap|US Equity|Core Premium|Equity Premium Income ETF$', 'SPY', 'S&P 500 (SPY)', 'index'),
]


def benchmark_of(name):
    for pat in SINGLE_PATTERNS:
        m = re.search(pat, name)
        if m and m.group(1) not in TOKEN_SKIP:
            t = TICKER_FIX.get(m.group(1), m.group(1))
            label = STOCK_NAMES.get(m.group(1)) or STOCK_NAMES.get(t)
            return t, f'{label + " " if label else ""}({t})'.strip(), 'stock'
    for pat, tk, label, kind in INDEX_RULES:
        if re.search(pat, name, re.I):
            return tk, label, kind
    return 'SPY', 'S&P 500 (SPY), used as a default proxy', 'proxy'


def is_etf_ticker(t):
    return 1 <= len(t) <= 5 and t.isalpha() and t.isupper() and not (len(t) == 5 and t.endswith('X'))


def build(year=None):
    year = year or datetime.date.today().year
    cache = ROOT / 'pipeline' / 'cache' / f'sec-series-class-{year}.csv'
    if not cache.exists():
        url = f'https://www.sec.gov/files/investment/data/other/investment-company-series-class-information/investment-company-series-class-{year}.csv'
        req = urllib.request.Request(url, headers={'User-Agent': f'ETFIQ-research/0.1 {CONTACT}'})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(urllib.request.urlopen(req, timeout=180).read())
    rd = csv.DictReader(io.StringIO(cache.read_text(encoding='utf-8-sig')))
    seen, out = set(), []
    for x in rd:
        name = (x.get('Series Name') or '').strip()
        tk = (x.get('Class Ticker') or '').strip().upper()
        entity = x.get('Entity Name') or ''
        if not tk or tk in seen or not is_etf_ticker(tk):
            continue
        if not INCLUDE.search(name) or EXCLUDE.search(name):
            continue
        strong = bool(STRONG.search(name))
        etf_trust = bool(ETF_TRUST.search(entity))
        if not (strong or etf_trust):
            continue
        seen.add(tk)
        bt, bn, bk = benchmark_of(name)
        rec = {'ticker': tk, 'name': name, 'issuer': issuer_of(name, entity), 'entity': entity, 'cik': str(int(x['CIK Number'])),
               'strategy': strategy_of(name), 'benchmark': bt, 'benchmarkName': bn, 'benchmarkKind': bk,
               'include': False, 'why': ''}
        if UNAMBIGUOUS.search(name):
            rec['include'], rec['why'] = True, 'option-income keyword in the name'
        elif strong and rec['issuer'] in KNOWN_OPTION_ISSUERS:
            rec['include'], rec['why'] = True, 'income keyword from a known option-income issuer'
        else:
            rec['why'] = 'income keyword only; review by hand'
        rec.update(OVERRIDES.get(tk, {}))
        out.append(rec)
    for f in FORCE:
        if f['ticker'] not in seen:
            out.append(dict(f))
            seen.add(f['ticker'])
    out.sort(key=lambda r: (r['issuer'], r['ticker']))
    (ROOT / 'data').mkdir(exist_ok=True)
    (ROOT / 'data' / 'income_universe.json').write_text(json.dumps(out, indent=1))
    return out


if __name__ == '__main__':
    year = int(sys.argv[sys.argv.index('--year') + 1]) if '--year' in sys.argv else None
    u = build(year)
    inc = [r for r in u if r['include']]
    import collections
    print(f'{len(u)} candidates, {len(inc)} included')
    print('by issuer (included):', dict(collections.Counter(r['issuer'] for r in inc).most_common(30)))
    print('by strategy (included):', dict(collections.Counter(r['strategy'] for r in inc)))
    print('by benchmark kind (included):', dict(collections.Counter(r['benchmarkKind'] for r in inc)))
    print('excluded but candidate:', [r['ticker'] + ' ' + r['name'][:40] for r in u if not r['include']][:25])
