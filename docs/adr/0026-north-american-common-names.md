# 0026 — Cards use eBird's English names; IOC stays the taxonomy

**Status:** Accepted, 2026-10-01 · **Amends:** [0004](0004-species-lists-from-gbif.md), [0008](0008-species-and-region-identity.md) (where common names come from) · **Related:** [0025](0025-card-design.md) (the IOC tag)

## Context

AviAnki's audience is North American birders (PRD). The catalog named every species from the IOC World Bird List, but 111 of 993 IOC English names differ from the eBird names those birders use:

- **59 differ only in spelling or punctuation**, e.g. Grey/Gray or American Golden Plover/Golden-Plover.
- **40 are different names for the same bird**, e.g. Grey Plover/Black-bellied Plover, Rock Dove/Rock Pigeon, Rough-legged Buzzard/Rough-legged Hawk, Black-necked Grebe/Eared Grebe.
- **12 are birds the two lists split differently.** eBird's records carry a scientific name that IOC uses for a different population, so the IOC name names the wrong bird:

  | eBird name | IOC name for the same scientific name |
  |---|---|
  | Yellow Warbler | Mangrove Warbler |
  | Green-winged Teal | Eurasian Teal |
  | Yellow-rumped Warbler | Myrtle Warbler |

  The other nine are Hepatic Tanager, Green Jay, Vermilion Flycatcher, Fox Sparrow, Northern Pygmy-Owl, Sargasso Shearwater, Northern House Wren, Redpoll and Zebra Finch.

## Decision

- **The card's name is eBird's English name**, as eBird itself gives it on the records in the eBird Observation Dataset (EOD), the dataset the catalog already uses and credits.
  - `species.csv`'s `common_name` holds that name for all 993 species with eBird records.
  - The 7 rows without one (aliases and species with no records) keep their IOC name.
- **IOC stays the taxonomy.** Scientific names, species ids ([0008](0008-species-and-region-identity.md)), the backbone resolution ([0004](0004-species-lists-from-gbif.md), [0024](0024-species-names-from-ebird-verbatim.md)) and BirdNET labels are unchanged.
- **Newly minted species take eBird's name too.** When a build mints a species, its common name comes from an EOD record's `vernacularName`. IOC's English name is the fallback, then the scientific name.
- **Credits:**
  - The eBird dataset credit gains "and English species names".
  - The IOC credit becomes "for scientific names".
- **The IOC tag ([0025](0025-card-design.md)) shows only for the 40 birds that have a genuinely different name for the same bird.** Spelling-only differences and the 12 differently-split birds get no tag. The tag's data and template are a separate change.

## Consequences

- Re-importing a deck renames the 111 birds' cards in place. Note GUIDs come from the species id ([0009](0009-note-identity.md)), so review history is kept.
- Credit lines in the catalog that print the species name (for example iNaturalist titles) pick up the new name at the next catalog build.
- `--ebird` decks already used eBird's names for species built live; now they match catalog species too.
