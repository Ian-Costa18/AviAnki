# 0002 — allaboutbirds.org is dormant code, not a registered source

**Status:** Accepted, 2026-08-25 · **Tickets:** [#8](https://github.com/Ian-Costa18/AviAnki/issues/8), [#5](https://github.com/Ian-Costa18/AviAnki/issues/5), [#27](https://github.com/Ian-Costa18/AviAnki/issues/27)

## Context

Every request to allaboutbirds.org now returns 403 with a Cloudflare challenge. Macaulay Library sends no CORS headers. Both look like deliberate signals from Cornell.

## Decision

- `allaboutbirds.py` stays in the repo so the scraping knowledge isn't lost. It moves to `sources/allaboutbirds/` and is **not registered** with the source registry.
- The CLI drops allaboutbirds URLs and Google Place IDs as input forms ([0017](0017-cli-reads-the-catalog.md)).
- #5 stays open, labelled blocked-upstream.
- **#27 (ask Cornell for Macaulay access) is closed as not planned.** The plan works without Cornell. If anyone wants to knock on that door later, it's a new effort.

## Consequences

The source contract ([0007](0007-source-contract.md)) doesn't have to model a hostile source.
