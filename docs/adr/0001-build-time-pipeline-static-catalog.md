# 0001 — Build-time pipeline and a static catalog, not live scraping

**Status:** Accepted, 2026-08-23 · **Ticket:** [#7](https://github.com/Ian-Costa18/AviAnki/issues/7)

## Context

A browser can't fetch the media live. allaboutbirds.org sits behind a Cloudflare challenge, eBird and xeno-canto need API keys that can't ship to a browser, and iNaturalist's media host sends no CORS headers.

## Decision

A Python pipeline runs in GitHub Actions. It fetches openly licensed media once, processes it, and publishes a **static catalog**. The browser reads that catalog from the same origin and builds the deck on the device. There is no server, and there are no keys in the browser.

## Consequences

- Any API key the pipeline needs is an Actions secret. It never reaches a user.
- The catalog becomes the durable asset. The PRD (§1) requires its format to stay neutral about `.apkg`.
- Freshness now depends on how often the catalog is rebuilt ([0014](0014-catalog-rebuilds.md)).
