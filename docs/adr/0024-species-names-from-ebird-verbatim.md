# 0024 — A GBIF backbone key takes the name eBird itself gives its records

**Status:** Accepted, 2026-09-30 · **Amends:** [0004](0004-species-lists-from-gbif.md) · **Ticket:** [#56](https://github.com/Ian-Costa18/AviAnki/issues/56)

## Context

[0004](0004-species-lists-from-gbif.md) faceted EOD by GBIF backbone `speciesKey` and named each key from the IOC checklist on GBIF. The first full build showed the backbone lumps taxa that IOC and eBird split, and the lumped key carries the older, wider name. EOD's records keep eBird's own name in `verbatimScientificName`:

| Backbone key | Named by 0004 | eBird's names for the records under the key |
|---|---|---|
| 2480487 | Hen Harrier, *Circus cyaneus* | *C. hudsonius* 96%, *C. cyaneus* 4% |
| 2480556 | Grey-lined Hawk, *Buteo nitidus* | *B. plagiatus* 87%, *B. nitidus* 13% |
| 2474416 | Western Swamphen, *Porphyrio porphyrio* | *P. poliocephalus* 75%, *P. porphyrio* 19%, *P. madagascariensis* 5% |

A card that calls a Northern Harrier a Hen Harrier is wrong, and the PRD ranks wrongness below absence. The iNaturalist plausibility check ([0022](0022-plausibility-threshold.md)) catches some of these, but only for iNaturalist media. It doesn't catch the name or the Commons photo.

## Decision

- **eBird's name decides.** For every backbone key in a region's list, the source looks at EOD's `verbatimScientificName` facet for that key. Names are cut to the binomial, lower-cased and summed.
- **Global check first, regional only when needed.** One facet request per key, made once per build and cached, lists the names eBird uses under that key anywhere. A key where every name resolves to the same IOC species keeps that species. A key whose names resolve to more than one IOC species gets one more facet request per region it appears in, and takes the IOC species with the most records in that region.
- **Minority records drop out.** The key's counts and monthly vector go to the chosen species. Records under the other names are not listed separately in that region; that is an acceptable absence. When the dropped share is over 10% of the key's regional records, the report lists it.
- **A name not in the IOC list** falls back to 0004's backbone resolution (checklist key, then name, then synonyms). If the key resolves to an IOC species different from its eBird name, the report lists the key as a re-resolved key.
- **Every re-resolved key is reported** in `species-lists-report.md` and the build report: backbone key, the name 0004 would have given, the name used, and the regional share.
- The plausibility check stays as a backstop for iNaturalist media.

## Consequences

- About one extra GBIF request per listed species per build (roughly 1,000, cached by `core.http`), plus a regional request for each split key in each region it appears in. That's a few minutes at 2 requests/s.
- Species ids that were minted from the wrong name, such as `circus-cyaneus`, stay in `species.csv` as the IOC species they name. They drop out of North American region lists, and the correct species (`circus-hudsonius` and the others) are minted. No id changes meaning, so [0008](0008-species-and-region-identity.md) and [0009](0009-note-identity.md) hold.
- A lump that eBird itself hasn't split, such as iNaturalist splitting *Trogon elegans* while eBird hasn't, is outside this rule. The plausibility check handles those by dropping iNaturalist media.
