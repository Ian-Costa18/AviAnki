# 0004 — Region species lists come from GBIF's eBird Observation Dataset

**Status:** Accepted, 2026-08-24 · **Ticket:** [#29](https://github.com/Ian-Costa18/AviAnki/issues/29)

## Decision

- **The catalog's species lists, frequency ranks and monthly seasonality** come from GBIF's eBird Observation Dataset (EOD), published by the Cornell Lab under **CC BY 4.0**. It's the same observations as eBird, through a channel that allows republication.
- **Common names** come from GBIF vernacular names filtered to the **IOC World Bird List**. The species record's own `vernacularName` is the fallback.
- **eBird's API is not used anywhere on the web side.** It survives only behind the CLI's `--ebird` flag, and decks built that way are marked not for redistribution ([0017](0017-cli-reads-the-catalog.md)).

## Consequences

- Region lists are keyed by GADM level-1 ([0008](0008-species-and-region-identity.md)).
- EOD is an **annual snapshot**. Species lists refresh when GBIF publishes a new EOD version, not on the media cadence ([0014](0014-catalog-rebuilds.md)).
- The EOD needs dataset-level CC BY credit, which goes in the deck description and the site footer ([0012](0012-attribution.md)).
