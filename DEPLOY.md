# Deploying ETFIQ to etfiq.com

Checked 2026-09-04: both `etfiq.com` (registered 2006, renewed under a New York registrant) and `etfiq.ai` (registered 2026-05-02) are at GoDaddy and use GoDaddy DNS. `etfiq.com` currently resolves to a GoDaddy parking address (160.153.0.45). Nothing is deployed anywhere yet.

## Hosting choice

GitHub Pages, published by GitHub Actions from the `site/` folder of a GitHub repository.

Why this and not a hosting account: it is free, HTTPS on a custom domain is automatic, this machine is already logged in to GitHub as `adampatti`, the daily data snapshot is a second workflow in the same repository that commits and redeploys, and any future session publishes by pushing. Cloudflare Pages, Vercel or Netlify work the same way if you ever want them; only the DNS target changes.

## Status on 2026-09-04, evening

Done: repository https://github.com/adampatti/etfiq (public), GitHub Pages enabled from the Actions workflow, custom domain `etfiq.com` attached. Update 2026-09-05: DNS done. The four A records and the `www` CNAME are in place at GoDaddy and propagated; GitHub serves the site for etfiq.com over HTTP. HTTPS enforcement (step 4) switches on automatically once GitHub issues the certificate. A leftover `_acme-challenge` CNAME from an old Cloudflare setup can be deleted. The old GoDaddy WordPress site that used to answer at etfiq.com is now unreachable and its hosting can be cancelled. `etfiq.ai` forwarding is step 5.

## One-time setup

1. Create the repository from this folder and push it. Public, because Pages on a private repository needs a paid plan and the site is public anyway.

```bash
cd /Users/adampatti/Desktop/ETFIQ && git init -b main && git add -A && git commit -m "ETFIQ buffer desk: site, fixture v2, pipeline, docs" && gh repo create etfiq --public --source=. --push
```

2. Turn on Pages with the Actions source. The workflow in `.github/workflows/pages.yml` then publishes `site/` on every push that touches it. The first address is `https://adampatti.github.io/etfiq/`.

```bash
gh api -X POST repos/adampatti/etfiq/pages -f build_type=workflow
```

3. Point the domain at GitHub. In GoDaddy: My Products, `etfiq.com`, DNS. Remove the parking A record and any forwarding, then add:

| Type | Name | Value |
|---|---|---|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | adampatti.github.io |

4. Tell GitHub the domain and require HTTPS. `site/CNAME` already contains `etfiq.com`, so the setting survives redeploys.

```bash
gh api -X PUT repos/adampatti/etfiq/pages -f cname=etfiq.com -F https_enforced=true
```

DNS usually propagates within an hour; the certificate issues automatically after that. Check with:

```bash
dig +short etfiq.com A && gh api repos/adampatti/etfiq/pages --jq '.html_url, .https_enforced, .status'
```

5. `etfiq.ai`: in the same GoDaddy screen, set domain forwarding (permanent, 301) to `https://etfiq.com`. A second Pages site is possible later if the .ai domain should stand on its own.

## Every deploy after that

Edit, then `git push` from this folder. Or ask a session to do it.

## Sign-ups

The alerts form posts JSON to `CONFIG.signupEndpoint` in `site/index.html`. Until one is set, choices are kept on the reader's device and nothing is collected. Any form backend that accepts JSON works (Formspree, Basin, a Google Apps Script web app); for the weekly note itself, Buttondown or ConvertKit accept subscribers by API. The record includes the exact SMS consent text and timestamp, which is what a TCPA agreement needs to be provable.

## The daily data snapshot

`.github/workflows/snapshot.yml` runs `pipeline/snapshot.py` at 22:40 UTC Monday to Friday, writes `data/snapshots/YYYY-MM-DD.json` and `site/data/funds.json`, runs `pipeline/build_site.py` to inline the new data and today's date into `site/index.html`, commits, and deploys. The banner switches from "Sample data" to "Live data as published by issuers on <date>" on its own once `asOf` is set by the build step. Set the repository secret `ETFIQ_CONTACT` to a contact email; the SEC asks for one in the user agent of anything that reads EDGAR. See `DATA-PIPELINE.md` for sources and coverage.
