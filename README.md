# Nuclear Index

A daily index of 18 listed nuclear companies, equal-weight and market-cap weight, in US dollars,
base 100 on 25 Nov 2025. Static page (`index.html`) reading `data/index.json`.

- **Constituents** — `constituents.json`: the 17 names on Simply Wall St's *Nuclear Renaissance*
  investing idea (snapshot 25 Nov 2026) plus newcleo (NWCL), which joins on 15 Sep 2026, its
  first session after the SPAC merger (Yahoo's earlier rows are the SPAC shell). Shares are held
  constant, taken from Yahoo market caps on 20-23 Nov 2026.
- **Build** — `python3 tools/build.py`: Yahoo Finance chart API (no key), FX from Yahoo `XXXUSD=X`.
  Fails rather than publish when a stock has no close in 6 days or an index moves >20% in a day.
- **Update** — `.github/workflows/update.yml`, weekdays 22:47 UTC plus a 05:47 UTC catch-up.
- **Changing the list** — edit `constituents.json` (shares from Yahoo's `trailingMarketCap` /
  price; London prices are in pence) and rebuild. The whole history is recomputed each run, so
  a change applies back to the base date.

Not investment advice.
