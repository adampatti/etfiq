# ETFIQ handoff

Written 2026-09-06. Everything needed to pick this up on a new machine, what was built, and what is open.

No secrets or personal email addresses appear in this file. The repository is public.

---

## 1. What ETFIQ is, as of today

A standalone, independent ETF data publisher at **etfiq.com**. No connection to any issuer. It makes no
recommendations and suggests no allocations. Every published number is arithmetic on a named public source,
and every figure ETFIQ computes rather than quotes is marked as such on the page.

Four desks:

| Desk | What it answers | Primary sources |
|---|---|---|
| Buffer | Where does my buffer ETF stand today | Issuer product pages (Innovator, AllianzIM, FT Vest), prospectus supplements |
| Income | Am I ahead of the benchmark | Tiingo end of day prices and distributions, Nasdaq and issuer payout dates, Rule 19a-1 notices |
| Themes | What did I actually buy | SEC Form N-PORT holdings, issuer daily holdings files, Tiingo returns |
| Portfolio | What does my whole portfolio own, protect and pay | Look-through books built from the other three |

**Scale**: 872 funds, 116 registered issuers, 2,802 pages, 1,729 head to head comparison pages,
630 look-through books, 134 funds with return of capital read from 19a-1 notices.

Read `DATA-PIPELINE.md` for source detail and `DEPLOY.md` for hosting and domain.

---

## 2. Setting up the new Mac

```bash
git clone https://github.com/adampatti/etfiq.git
cd etfiq
pip3 install -r pipeline/requirements.txt
```

Python 3.14 on the old machine. Anything 3.11 or newer should work.

**The site needs no build to view.** `site/index.html` is self contained. Open it, or serve the folder:

```bash
python3 -m http.server 8765 --directory site
```

There is a `.claude/launch.json` with an `etfiq` server entry, but it is gitignored (see below), so recreate
it if you want the Browser pane to start the server by name.

---

## 3. Files that will NOT travel with the repo

These are gitignored on purpose and must be copied across by hand from the old Mac. This is the single
most important section of this document.

| Path | What it is | Consequence if lost |
|---|---|---|
| `CLAUDE.md` | Project instructions Claude Code reads on every session | Claude loses every standing rule: no em dashes, no recommendation language, never write into the AssetOS folder |
| `pipeline/.env` | Local Tiingo token and contact string | Pipelines that need prices will not run locally |
| `.claude/` | Local Claude Code settings and `launch.json` | Minor, recreate as needed |
| `ETFIQ-DESIGN-SESSION-HANDOFF.md` | Original product decisions, section 11 erratum overrides sections 3, 7 and 8 | Loses the reasoning behind the desk design |
| `ETFIQ-Data-Business-Assessment-2026-09-04.md` | Measured corrections: the moat claim, Net Position, band geometry | Loses the corrections |
| `ETFIQ-External-Figures-Verification-2026-09-04.md` | Which external figures were verified against source on 2026-09-04 | Loses the verification record |
| `etfiq-funds-fixture.json` | v1 design fixture, provenance only | Low value, superseded |
| `etfiq-data-business-state-2026-09-04.memory.md` | Working state note | Low value |
| `pipeline/cache/` (most of it) | Tiingo prices, SEC holdings, SEC series file, sources, fees | Rebuilt automatically on first run, but the first run is slow and hits every source |

Copy the whole folder rather than picking files, then let git sort out what is tracked:

```bash
rsync -av --exclude '.git' /Volumes/OldMac/Users/adampatti/Desktop/ETFIQ/ ~/Desktop/ETFIQ/
```

**Also copy your Claude Code memory directory**, which lives outside the project:
`~/.claude/projects/-Users-adampatti-Desktop-ETFIQ/memory/`

---

## 4. Accounts and where credentials live

Nothing sensitive is in the repo. All of it is in accounts you own.

| Service | Account | Purpose |
|---|---|---|
| GitHub | adampatti/etfiq, public | Source and GitHub Pages hosting |
| GoDaddy | your account | Domain registration for etfiq.com, registered 2004 or 2005 |
| Cloudflare | your **personal Gmail**, not the vshareshq one | Web Analytics only. No DNS with them |
| Google Search Console | your **personal Gmail** | Indexing and query data |
| Bing Webmaster Tools | signed in on the old Mac | Indexing |
| Tiingo | your account | Price and distribution feed |
| Anthropic API | your account | Research narrative drafting only |

**Repository secrets** (GitHub, Settings, Secrets and variables, Actions). These already exist and travel
with the repo, not the machine:

- `TIINGO_TOKEN`
- `ANTHROPIC_API_KEY`
- `ETFIQ_CONTACT`

**A gotcha that has cost time twice.** Chrome on the old Mac defaults to a `vshareshq.com` Google account,
but Search Console and Cloudflare are on your personal Gmail. If Search Console says "you don't have access
to this property", you are on the wrong account. Switch accounts, or use the account-pinned URL:

```
https://search.google.com/u/5/search-console?resource_id=sc-domain%3Aetfiq.com
```

The `u/5` is the account index and may differ on a fresh machine.

---

## 5. How the site is built

**`site/index.html`** is the entire application: one self contained page with hash routing. Data is fetched
at runtime rather than inlined, which took the shell from 1.90 MB to 0.35 MB. Setting `ETFIQ_INLINE=1`
re-inlines everything for a file-only copy that works with no server.

**Static crawl layer**: 2,802 pre-rendered pages so that crawlers and AI engines never depend on JavaScript.
Fund pages, comparison pages, hub pages, ranking pages, question pages, document pages. Built by
`pipeline/prerender.py`.

**Nightly run**, `.github/workflows/snapshot.yml`, 19:30 New York on weekdays, in this order:

```
core.py  snapshot.py  income.py  payouts.py  sources.py  fees.py  thematic.py
books.py  insights.py  research.py  [draft.py + research.py]  build_site.py
embed.py  prerender.py  census.py  indexnow.py
```

`pages.yml` deploys `site/` to GitHub Pages on any push touching `site/**`.
`narrative.yml` drafts research narratives on demand.

**To rebuild locally** after editing the app or a template:

```bash
python3 pipeline/build_site.py      # app shell
python3 pipeline/prerender.py       # the 2,789 static pages
python3 pipeline/research.py        # research pages
python3 pipeline/census.py          # verify, exits 1 on findings
```

---

## 6. Traffic and AI search: everything built

This is the section you asked for in detail. The strategy assumes two different readers: Google's crawler,
and an AI engine answering a question. Both are served by the same static layer.

### 6.1 The static crawl layer, 2,802 pages

Nothing that matters requires JavaScript. Every fund, every comparison, every ranking and every question has
a real HTML page with the answer in the text, not in a script.

| Page type | Count | Why it exists |
|---|---|---|
| Fund pages | 922 | The long tail. Someone searches a ticker, lands on the answer |
| Head to head comparisons | 1,729 | "JEPI vs SPYI" is a real query with real volume |
| Hub pages | 93 | By issuer, by theme, by reset month |
| Ranking pages | 16 | "Highest paying covered call ETFs" style queries |
| Question pages | 8 | Direct answers to common questions |
| Document pages | Standards, open data, statistics, changed today, research | Trust and citation surfaces |

### 6.2 Structured data

Every page carries schema.org JSON-LD so machines can read it without parsing prose:

- **FinancialProduct** on fund pages, with PropertyValue identifiers and `sameAs` links to EDGAR and the issuer
- **Dataset** with an explicit licence and citation text, on the open data and statistics pages
- **FAQPage** on fund and question pages
- **BreadcrumbList** on every page
- **ItemList** on hubs and rankings
- **DefinedTermSet** on the vocabulary pages
- **WebApplication** on the app

### 6.3 AI citation specifics

The bet is that AI engines cite sources that are unambiguous, dated and attributable.

- **Every figure carries its date and its source on the page**, in text, not a footnote
- **Every computed figure is marked ETFIQ** so a model can distinguish a quoted number from a derived one
- **`llms.txt`** at the root, describing the site and pointing at the open data
- **Open data**: every published figure available as JSON at a stable address, free to use with attribution
- **Citation lines** on every page giving the exact form to cite
- **Plain-word answers**: pages answer the question in the first sentence rather than burying it
- **Research narratives** labelled "ETFIQ Narrative", with no model credit on the page

### 6.4 Internal linking

A crawl found 812 of 872 fund pages had one internal link or fewer, which is a dead end for both crawlers and
readers. `build_neighbours()` in `prerender.py` now gives every fund page a set of real onward links: same
issuer, same theme, same reset month, head to head against its closest peers. A follow-on bug where 59 pages
linked to issuer hubs that are only written for issuers with two or more funds was also fixed.

### 6.5 Outbound links

Deliberate, because they signal what the data rests on: issuer product pages, issuer home pages from the
issuer hubs, SEC EDGAR filing links, and Rule 19a-1 notice sources.

### 6.6 Sitemaps

`sitemap-index.xml` plus six section files, 2,793 URLs. Submitted to Google Search Console and Bing Webmaster
Tools on 2026-09-05. As of 2026-09-06 both are reading successfully and Google has discovered 2,793 pages.
`indexnow.py` pings IndexNow after every nightly run so Bing and Yandex learn about changes immediately.

### 6.7 Embeddable widgets

`pipeline/embed.py` builds SVG cards other sites can embed, one per fund, 817 of them. Each carries an ETFIQ
attribution and a link back. The theory is straightforward: an embedded card is a link you did not have to ask
for, and it renders as an image so it survives on sites that strip scripts. Also builds 1200x630 social cards,
rasterised to PNG in CI only.

### 6.8 Analytics, added 2026-09-06

Cloudflare Web Analytics on all 2,798 content pages. Cookieless, so no consent banner is needed and the site
stays on the privacy-preserving default. The beacon is in `rail.py`'s shared footer so a single edit covers
every generated page, plus the app shell and the three frozen research archive pages.

Set up under your personal Gmail rather than the issuer-domain account, so nothing links ETFIQ's analytics to
a fund issuer.

**Recommendation on record**: do not add Meta, X or LinkedIn pixels yet. Cloudflare plus Search Console covers
what a reference site needs, and every pixel sets third-party cookies, which obligates a consent banner. The
one exception is the LinkedIn Insight Tag if LinkedIn ads are planned within six months, because retargeting
audiences take months to build and cannot be backfilled.

### 6.9 Realistic timeline

Sitemap submitted 2026-09-05. Expect indexing counts within one to three days, first impressions in one to two
weeks, meaningful clicks in four to eight weeks. The 2004 domain age helps. Watch for comparison pages marked
"crawled, currently not indexed", which is the normal outcome for thin pages and would mean the comparison
pages need more distinct content.

---

## 7. Data accuracy machinery

This is what the business rests on, and it is the part to protect.

**`pipeline/census.py`** recomputes every published number from the raw sources with independent code and
exits 1 on any discrepancy. It runs every night and writes to `data/census/`. Stages: income, buffer, live,
themes, payouts, books, research, pages, compare, faqs, embeds, docs, plus the guards below.

**Guards added on 2026-09-06**, each because something real went wrong:

- `check_issuers` : every published issuer must reproduce from a curated rule or a confirmed SEC registrant
- `check_published_keys` : no CUSIP-shaped identifier may reach a published file
- `check_core_overlap` : a core fund's overlap must reproduce from its whole filing, not a truncated book

**A warning about the census.** It is written from the same understanding as the pipeline, so it can share a
blind spot. The SPY bug in section 8 survived the census for weeks because both sides used the same truncated
book. When something matters, check invariants that hold regardless of implementation: a fund against itself
must be 100 percent overlap and 0 percent active share, overlap must be symmetric, active share must equal
100 minus overlap, and known answers must land (SPY and IVV against the S&P 500 are 0 percent active share,
international funds are 0 percent in-index).

---

## 8. Recent fixes worth knowing about

**Issuer names were guessed from the fund name.** `issuer_of` ran a regex on the fund's own name before
consulting the SEC registrant, so the leading capitalised word became the issuer. The site published
Anthropic, Google and Meta as ETF issuers. Fixed: curated rule, then SEC registrant with trust wording
stripped and confirmed against the fund name, then "not published". Never a guess. 43 funds are now honestly
unattributed rather than wrongly attributed.

**SPY was published with 5.7 percent active share against itself.** `core.py` computed overlap from the
published book, which `books.py` truncates to 300 rows, while reporting the full holdings count. 17 core funds
were corrected. `core.py` now reads the filing.

**CUSIPs were being published.** 4,332 of them, on a page that says "free to use, including commercially".
CUSIPs are licensed by CUSIP Global Services and bulk redistribution generally needs a licence. They are now
internal only: the primary match key inside the pipeline, replaced in every published book by an opaque ETFIQ
security id. The row shape is unchanged and slot 2 was only ever a join key, so look-through and overlap
behave identically.

**Buffer funds had no stable identifier.** Ticker only, and tickers get reused. 236 of 245 now carry their SEC
series id and CIK, resolved by ticker then by name against the SEC's own series and class file.

**Three mobile overflow bugs**, all found by testing at 375px:

- the footer grid used `minmax(min(170px,100%),1fr)`, which with a gap resolved against intrinsic size and
  chose five 150px tracks, pushing every page 495px wider than a phone
- the desk nav overflowed once its gaps were widened; it scrolls internally now
- the trailing link in a section divider is nowrap and could not shrink, pushing every page 11px wide

**JEPI's holdings book was another fund's filing.** The income universe had no series ids, so a name search
matched a fund of funds. Fixed with series id verification on every filing.

**VistaShares "paid 1Y" was wrong**, reported by you. Funds a few days short of a year silently showed six
month figures. Fixed with a labelled "since date" fallback.

**TPRY's payout rate showed 65 percent**, reported by you. `frequency()` paired the wrong ex-dates for funds
with three to six distributions, mislabelling nine funds as weekly.

---

## 9. Design system, as it stands

Changed substantially on 2026-09-06 after a side by side comparison.

- **Palette**: near-white ground `#FAFAF9`, near-black ink `#0A0A0A`, one electric accent `#1D34F2`. The rail
  uses a brighter `#4A5DFF` because the base accent is too dark on near-black
- **Links are ink with a hairline rule**, not a colour. This is deliberate: it leaves green, amber and red as
  the only colours on a page, so a colour always means something (protected, at cap, losing money)
- **Type**: Source Serif 4 for the headline tier only, Geist for every interface surface, Geist Mono for all
  figures with tabular numerals
- **Surfaces**: 3px radii, no drop shadows, hairline borders carry the separation
- **Nav**: plain text with a 2px rule under the active desk. Not boxes
- **Logo**: `pipeline/brand.py`. Ink `#0A0A0A`, the IQ in `#1D34F2` on light and `#6274FF` on the dark coin

**`brand.py` cannot regenerate on this machine.** It needs cached Fraunces and Geist woff2 files in
`pipeline/cache/fonts/`, which are absent. The existing SVGs were recoloured in place. If you ever rerun the
brand builder, restore those fonts first or it will fail.

---

## 10. Home page structure

Rebuilt 2026-09-06 on the principle that the page should show before it asks.

1. Hero, search box, ten one-click ticker chips
2. One fund, the whole card. A real fund card, clickable through, with tabs for JEPI, PJAN and ARKK
3. What is behind it. A depth strip counted from the data, not claimed
4. One example from each desk. Three columns, each with that desk's signature chart on a real fund
5. Portfolio desk door
6. What changed, number first
7. Research

---

## 11. Standing rules

- **No em dashes anywhere**, on the site or in any document in this folder. The pipeline has guards
- **No recommendation language**: never best, top pick, buy, recommended, favorite, winner, worst. ETFIQ makes
  no recommendations and suggests no allocations
- **Never write into `/Users/adampatti/Desktop/AssetOS`**. Separate live build
- **The banner** shows the issuer publication date when live data is inlined and falls back to the sample-data
  warning when it is not. Never remove either
- **Research narratives** are labelled "ETFIQ Narrative". No model credit on the page
- **Independence statement**, not an issuer-affiliation disclosure. No counsel gating applies

---

## 12. Open items

**Needs you**

- **iPhone check.** Open `https://etfiq.com/themes/ai.html` on a phone and confirm the header does not run
  wider than the screen, the page does not scroll sideways, and content below the header is present. Three
  mobile overflow bugs were fixed without ever testing on real iOS Safari
- **About and author page.** Held. This is the highest-value remaining item for search, because Google weights
  named author expertise heavily for financial content and an anonymous site caps how far it can rank. It
  needs your name, role and ETF background. Once supplied, the Person and author schema wires across all 2,802 pages
- **Weekly note.** Held. Your constraint: it must carry a genuinely actionable, insightful take, not a data
  dump. Not yet designed
- **Wider ETF universe.** Held, and there is a recommendation against it on record: thin coverage of thousands
  of funds risks the quality signal the three deep desks currently earn

**Mine, when there is data**

- Next traffic round once Search Console has a week of per-section indexing data

**Yours alone**

- Links and citations outreach
- Alerts backend and newsletter, which needs a hosted service

---

## 13. Verification state at handoff

- Census: 0 findings across all stages
- No em dashes anywhere in `site/`
- No CUSIP-shaped keys in any published file
- No horizontal overflow at 375px on the app or a static page
- Overlap engine passes identity, symmetry and bounds invariants, and all known-answer checks
- 34 of 36 sampled head to head pages reproduce from the SEC filings. The 2 that did not were correct on the
  site and stale in the check, because the site used fresher issuer daily files
- Working tree clean, deploy green
