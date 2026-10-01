# 0008 — Minted species ids under IOC; GADM level-1 regions

**Status:** Accepted, 2026-08-25 · **Amended by:** [0022](0022-plausibility-threshold.md); common names amended by [0026](0026-north-american-common-names.md) · **Ticket:** [#20](https://github.com/Ian-Costa18/AviAnki/issues/20) (Q4, Q5)

## Context

Sources disagree about taxonomy, and they do it silently. iNaturalist has split the Whimbrel (*Numenius phaeopus* → *N. hudsonicus*), so looking it up by scientific name returns a plausible taxon with 24 records in place of 27,517, and the card would show a bird from the wrong continent.

## Decision

### Species

- **Each species has a minted internal id**: the IOC scientific name as a slug at the time it was minted, e.g. `cardinalis-cardinalis`. The id never changes afterwards, even if the name does.
- **IOC World Bird List is the declared authority.** AviAnki records what upstream decided and never invents a species.
- **`data/species.csv`** is checked in. It has one row per id, with the IOC scientific and common names plus each source's native key: `gbif_key`, `inat_taxon_id`, `wikipedia_title`, `ebird_code`, and `birdnet_label` ([0011](0011-media-selection.md)).
- **Splits:** the existing id follows the taxon that keeps the name, and the daughter species gets a new id. **Lumps:** the retired id stays as an alias row pointing at its successor.
- **Plausibility check:** a source's result for a species is flagged when its North American count is below a small fraction of the expected count from EOD (the fraction and the count are set by [0022](0022-plausibility-threshold.md)). A flagged result is treated as a mapping error, not as rarity.

### Regions

- **GADM level-1 is the region authority.** AviAnki doesn't decide what counts as a region.
- **`data/regions.csv`** maps a readable slug (`us-ma`, `ca-on`) to a display name, country and GADM gid. It **records the GADM version it was built against**. GADM gids are positional, so a renumbering then shows up as a diff instead of a silent mislabel.
- The eBird region code is another column in the same table, for the CLI.

## Consequences

- Note GUIDs are built from the species id ([0009](0009-note-identity.md)), so an IOC rename changes the displayed name without orphaning anyone's progress.
- The first build mints about 1,000 rows from GBIF's IOC checklist. After that, a change to either table is a reviewable diff.
