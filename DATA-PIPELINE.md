# ETFIQ data pipeline

What feeds the desk, where it comes from, what it costs, and what is still to build. Everything here was verified by fetching the sources from this machine on 2026-09-04.

## The short answer

The data lives in two places, and both are free.

1. **Period terms** (cap gross and net, buffer range, period dates) are in the prospectus supplements every fund files with the SEC at each reset, form 497K. EDGAR keeps every one since inception, so the full history of terms is reconstructible at no cost. This is the durable asset: a normalised terms table across every issuer since each fund's first period. Your instinct was right that this is the cheapest source and the most work, because nineteen issuers phrase the same facts differently.
2. **Daily current values** (fund return, reference return, remaining cap, remaining buffer, downside before buffer, days remaining, NAV) are published by the issuers on their own sites, in plain server-rendered HTML or embedded JSON, and overwritten daily. The three issuers holding about 91 percent of category assets each expose their entire lineup on one page or one page per fund.

Reference asset prices are published by the issuers alongside those values, so no market data subscription is needed for the daily snapshot. A price feed becomes useful only for recomputing history and for the option-implied cap curve.

## Sources, as verified

| Issuer | Share of assets | Source | Shape | Fields |
|---|---|---|---|---|
| FT Vest (First Trust) | 48.9% | ftportfolios.com, `EtfList.aspx` then `EtfSummary.aspx?Ticker=` per fund | Server-rendered HTML, one page per fund | Starting cap gross and net, buffer start and end as percent and as reference-asset price levels, period dates, days remaining, fund value and return, reference value and return, remaining cap gross and net, reference return to realize the cap, remaining buffer, downside before buffer, expense ratio, NAV, net assets |
| Innovator (Goldman Sachs since 2026-04-02) | 36.6% | innovatoretfs.com `/define/etfs/` | One server-rendered table, every fund, dated | Ticker, family, series month, reference asset, fund price and return, reference return, return to cap, remaining cap, remaining buffer, downside before buffer, days remaining, starting cap, period dates, starting reference and fund prices. Per-fund pages add the expense ratio and the buffer range in the issuer's words |
| AllianzIM | 6.1% | allianzim.com `/product-table/` | `const model = {...}` JSON in the page, keyed by ticker | Everything above, gross and net, as fractions, plus net assets, NAV, participation rate for uncapped funds, period start and end |
| Everyone else | about 8% | SEC 497K filings, then each issuer's fund page | Prose, varies by issuer | Terms only from EDGAR; current values need one parser per issuer |

The scraper is `pipeline/snapshot.py`. It has no dependencies beyond the Python standard library and runs in about four minutes because it visits one page per FT Vest fund and, once a week, one page per Innovator fund to confirm each fund's buffer range and expense ratio from the issuer's own words rather than from a family map.

## What the snapshot produces

- `data/snapshots/YYYY-MM-DD.json`: every record captured, including structures the band does not draw yet (dual direction, accelerated, income-and-buffer), each with provenance: source page, fund page, as-of date, and whether the buffer geometry came from the issuer page or a family map.
- `site/data/funds.json`: the records the desk draws, which today means plain buffer and floor structures with current values.
- `site/data/meta.json`: as-of date, per-source counts, and coverage.

One record carries both spaces and marks which is which. Issuer fields are fund-price space, net of fees, exactly as published. ETFIQ fields are reference-return space, computed from the published terms and the reference return: remaining cap in reference terms, buffer used, unprotected loss taken, loss below the floor, and the state of the band. Net Position is still computed and stored for continuity but is not displayed, for the reason in the assessment.

## Schedule and cost

`.github/workflows/snapshot.yml` runs the scraper on GitHub's free Actions minutes at 22:40 UTC, Monday to Friday, commits the snapshot, rebuilds the page and deploys it. Cost: zero. If the repository is private, the free tier still covers about ten times this usage.

## Universe

The SEC publishes a yearly file of every registered fund series and class with tickers. Filtering its series names for buffer, outcome, protection and floor language gives 298 tickered series across Innovator ETFs Trust, First Trust Exchange-Traded Fund VIII, AIM ETF Products Trust (AllianzIM), PGIM Rock ETF Trust, Listed Funds Trust (TrueShares), iShares Trust, and a tail of smaller trusts. ETF Action counts 487 buffer ETFs, so the name filter misses some and the issuer pages catch the rest. Build the master list once as the union of the SEC file and the issuer pages, then reconcile by hand against the ETF Action league table. `python pipeline/edgar.py universe` prints the SEC side.

## Build order from here

1. **Run the snapshot daily.** It is wired. Set the repository secret `ETFIQ_CONTACT` so EDGAR requests carry a contact, and push.
2. **Terms table from EDGAR.** `pipeline/edgar.py search --cik 1415726` lists a trust's 497K filings; `terms <url>` parses the period, cap gross and net, fee and buffer range from one filing. Run it across the three trusts back to inception, then extend the parser one issuer at a time. This is the week of work that becomes the asset nobody else has assembled.
3. **The other sixteen issuers.** PGIM, Calamos, TrueShares, iShares, Pacer, AB and the rest each need a small parser for current values. Their terms already come from step 2. Together they are about 8 percent of assets, so they can follow the launch.
4. **History pages.** With the terms table and daily snapshots accumulating, the completed-periods slot in the fund panel fills in: every period since inception, cap, buffer, reference return, fund return, whether the cap bound and the buffer engaged. Completed periods before the snapshots began can be reconstructed from terms plus NAV and reference price history from any end-of-day price source (Stooq is free; Tiingo and Polygon start around thirty dollars a month).
5. **The cap the option market offers.** A daily curve of the cap a fresh period could strike at each buffer level and horizon, from listed option prices, gives every fund's starting cap a benchmark. Needs an options data feed; it is the first paid data in the plan.

## Terms of use

The issuer pages are public, unauthenticated, and built to be read by advisors; the scraper reads them once a day at human speed with an identified user agent. The SEC asks only for a contact in the user agent. No login, no API key and no paid data are involved in anything the desk shows today.

## First run, 2026-09-04

| Source | Rows on the issuer page | Captured | Drawn on the desk | Notes |
|---|---|---|---|---|
| Innovator | 160 | 116 | 108 | Rows left out are barrier and accelerated-only products and rows without period dates. Dual direction, accelerated-buffer and premium-income structures are captured but not drawn. |
| AllianzIM | 59 | 56 | 56 | The three Buffer Allocation funds of funds are excluded. |
| FT Vest | 106 | 101 | 81 | Five pages did not parse, one of them a Quarterly Dynamic page that returns no fund content. Dual direction, digital return, premium income and enhance structures are captured but not drawn. |
| Total | 325 | 273 | 245 | |

States on the desk that evening: 87 funds at their cap in reference terms, 113 open, 13 with the buffer engaged, 2 inside the unprotected slice of a deep buffer, 13 full floor, 17 uncapped, none exhausted. The desk groups them into 58 series.

The band draws plain buffer and floor structures. Dual direction, accelerated, digital return and income-and-buffer funds need their own payoff shapes before they are shown; they sit in the snapshot with a `structure` tag so nothing is lost meanwhile.

The FT Vest Max Buffer line turned out not to be a 100 point buffer: the issuer sets "the maximum available buffer" from option prices at each reset, so the twelve monthly funds carry buffer ends between about minus 44 and minus 78 percent, with one at minus 100. The desk's shared scale stops at minus 40 and draws deeper buffers running off its left edge; the fund panel shows each one on its own scale.

## Income desk, added 2026-09-04 late evening

**Question:** am I ahead of the benchmark? For every option-income ETF, total return with every distribution reinvested, against the total return of the index or stock the fund writes options on, over 3-month, 6-month, 1-year, 3-year and since-launch windows, plus cash paid, price change, payout rate and payout frequency.

**Universe:** `pipeline/income_universe.py` builds `data/income_universe.json` from the SEC series and class file by name (covered call, premium income, option income, 0DTE, YieldMax, YieldBOOST, Target 15 and so on), restricted to ETF-style tickers and known option-income issuers, with a benchmark mapped from the name (S&P 500 to SPY, Nasdaq-100 to QQQ, single stocks to the stock, proxies marked). First run: 414 candidates, 283 included, 131 left for hand review in the `why` field. Five known funds whose names hide the strategy are forced in.

**Feed:** Tiingo end-of-day, Power plan, about $30 a month. `pipeline/income.py` pulls one request per ticker (fund and benchmark) with per-day caching, split-adjusts closes and cash so reverse splits do not distort the price and paid columns, and uses Tiingo's adjusted close for total return. First run: 216 of 283 funds returned prices; the 67 missing are mostly funds the feed does not carry yet or tickers that are not live. Over the trailing year, 37 of 159 funds with a full year of history were ahead of their benchmark.

**Not yet captured:** return of capital from 19a-1 notices (the cash column is total cash regardless of tax character), expense ratios and assets for income funds, and the 67 missing tickers. The nightly job runs `income.py` whenever the `TIINGO_TOKEN` secret is set.

## Payout calendar, added 2026-09-05

**Question:** what is paying, when, and how much, for the next 45 days. `pipeline/payouts.py` writes `site/data/payouts.json` after `income.py` runs.

Three states, never blended:

- **Declared.** Nasdaq's dividend API carries declaration, ex, record and pay dates with amounts, but only for funds listed on Nasdaq (JEPQ, QYLD, GPIX, FEPI and the like). An upcoming ex-date there is the issuer's declaration.
- **Scheduled.** YieldMax publishes declaration, ex and pay dates for the whole year per payer group on its distribution schedule page; the amount is the last payment until the issuer declares. Other issuers' schedule pages can be added the same way.
- **Estimated.** Projected from the fund's own cadence (the median gap between its recent ex-dates, from the Tiingo history) and its last amount, with the pay date set by the fund's usual ex-to-pay lag where Nasdaq history gives one, otherwise two days. Weekend dates roll to Monday; exchange holidays are not yet handled.

The page shows the per-share amount and the payout per $10,000 invested at today's price, marks each event with its state, and totals the next 30 days for the funds a reader has pinned.

**Index income versus single-stock income.** Funds that write options on one company (YieldMax, GraniteShares YieldBOOST, Kurv, Defiance and the rest) are a different product from index funds like JEPI and SPYI: weekly payouts, extreme swings, principal that can halve in a year. Every income view carries a switch, index income by default, single stock or all on request, and the headline figures follow the switch.

## Ticker collisions and unlaunched funds (2026-09-05)

The SEC series and class file lists funds before they launch, sometimes with a ticker reserved and sometimes with none. Two failure modes showed up with VistaShares:

- A reserved ticker that a prior security used. Tiingo carried a price series under GATE from 2021 (a SPAC), relabelled with the fund's name, so an unlaunched fund appeared on the site with someone else's history. GATE is excluded in OVERRIDES until it trades. Rule for the future: when a fund's first Tiingo date predates the issuer's first launch by more than a few months, treat it as a collision and check by hand.
- Launched funds with no ticker in the SEC file (SIOO, DRKY, ACKY, TPRY). These are carried in FORCE with names from Tiingo's security metadata.

Funds the SEC file lists with a ticker but Tiingo has no prices for (ARAB, HRVD, LUSA, NRWY, UUSA, VUSA and the DIVBoost and BitBonds lineups) are simply not trading yet and drop out of income.json on their own.

## Daily refresh (2026-09-05)

`.github/workflows/snapshot.yml` runs twice each trading night, 23:30 UTC and 03:30 UTC, and on demand from the Actions tab. Each data step runs on its own: a failure in one desk leaves that desk on its last good data while the others refresh, the page still builds and deploys, and the run is marked failed so GitHub emails the owner. The run summary lists each step's outcome and the as-of date of both desks. The page itself shows an amber banner when a desk's data is more than two trading days old, so a silent failure can never look fresh.

The income universe (`data/income_universe.json`) is rebuilt by hand, not nightly: run `python3 pipeline/income_universe.py` after checking the SEC series file and Tiingo's supported-tickers list for new launches. Two lists in that script carry what the name rules cannot: `HAND_INCLUDE` for funds the SEC file names but the rules park for review, and `TIINGO_EXTRA` for funds that trade but have no ticker in the SEC file yet. Both were last reviewed on 2026-09-05.

## Buffer desk field definitions (2026-09-05)

The three answers on the buffer desk are not all the same kind of number:

- **Can still gain** is the issuer's remaining cap, net of fees, from the fund's current price. All three issuers publish it the same way.
- **Fall before buffer** is the issuer's "downside before buffer": how far the fund's price can fall before the buffer starts absorbing losses. It is in fund-price terms at every issuer, so the site words it as the fund, not the index. The index-terms equivalent, `fallBeforeBufferRef` = 1 − (1 + bufferStart) / (1 + refReturn), is an ETFIQ calculation shown on the fund card.
- **Protection left** is an ETFIQ calculation in index points: the part of the buffer still below today's index level, `startBuffer − bufferUsed`. Issuers' own "remaining buffer" figures are not comparable with each other (AllianzIM counts the distance down to the buffer as well, FT Vest counts only the buffer, Innovator uses a third method), so each issuer's figure is shown on the fund card labelled as its own, and the column uses the ETFIQ definition for every fund.
