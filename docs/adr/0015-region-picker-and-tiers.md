# 0015 — A state/province picker with a Standard (100) default

**Status:** Accepted, 2026-09-28 · **Ticket:** [#19](https://github.com/Ian-Costa18/AviAnki/issues/19)

The ticket asked for a clickable prototype. It's decided without one, because the options were already narrowed down by the GADM level-1 decision ([0008](0008-species-and-region-identity.md)) and the PRD's friction budget.

## Decision

- **The one required question is "Where do you go birding?"** It's answered with a single searchable `<select>` of US states, Canadian provinces and territories, grouped by country and showing display names (never `us-ma`). There's no map, no radius and no geolocation at v1. A radius or hotspot option would reopen [0004](0004-species-lists-from-gbif.md).
- **The choice is remembered** in `localStorage`, so a returning user starts on their region.
- **Tiers:**
  - **Standard** (the default) is the region's top 100 species by annual frequency.
  - **Everything** is the region's top 400, which is also how the catalog decides what to include. The catalog is the union of every region's top 400, around 1,000 species.
- **Season** is an option under *Advanced*: *"Only birds seen here in: [month]"*. It filters the ordered list to species whose frequency that month is at least 10% of their peak month, then takes the tier's count. The default is all year.
- **Other advanced options:** card types ([0010](0010-card-types.md)) and "Put these in a subdeck named after the region".
- **Outside the US and Canada:** a line under the picker reads *"Not in the list? AviAnki's website covers the US and Canada. The command-line tool works anywhere."*, with a link to the README.

## Consequences

- Species per default build: 100. Download size is roughly 100 × (60 KB photo + 100 KB audio), about 16 MB, which is well inside the PRD's 30-second budget.
