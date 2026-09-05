# ETFIQ

Independent data on defined outcome (buffer) ETFs: every fund from every issuer on one comparable outcome band, with the day's remaining cap, remaining buffer and downside before buffer. Live at https://etfiq.com.

- `site/` is the whole site: one self-contained page, with the latest data inlined.
- `pipeline/snapshot.py` reads each issuer's published values every weekday evening (standard library only, no keys, no paid data); `pipeline/build_site.py` inlines the result and stamps the date.
- `pipeline/edgar.py` reads outcome-period terms from SEC 497K filings for the terms table and the history.
- `DATA-PIPELINE.md` explains the sources and what is still to build; `DEPLOY.md` explains hosting and the domain.

Run locally:

```bash
python3 pipeline/snapshot.py && python3 pipeline/build_site.py && open site/index.html
```

ETFIQ is an independent publisher, not an issuer, broker or adviser, and makes no recommendations. Issuer figures are shown as published; ETFIQ calculations are marked as such on the page.

© 2026 ETFIQ. All rights reserved.
