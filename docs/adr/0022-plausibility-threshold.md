# 0022 — The plausibility threshold is 0.02%, not 5%, and compares like with like

**Status:** Accepted, 2026-09-28 · **Amends:** [0008](0008-species-and-region-identity.md) · **Ticket:** [#41](https://github.com/Ian-Costa18/AviAnki/issues/41)

## Context

[0008](0008-species-and-region-identity.md) flags a source's result when its North American count is below 5% of the count EOD expects. The 5% was a guess made before any source was queried. M3 measured it, for the first 30 rows of `data/species.csv`, against iNaturalist research-grade observations in the US and Canada:

- iNaturalist and eBird are different populations of observers, so their counts are not proportional. Across the 28 species that EOD records in North America, the median ratio is **2.8%**, and **18 of 28** correct mappings fall below 5%. A 5% threshold would discard about two thirds of good species.
- The one real mapping error in the sample is the case that motivated the check. iNaturalist's *Numenius phaeopus* is Eurasian-only and has 9 North American observations; EOD's lumped Whimbrel has 657,609. The ratio is **0.000014**.
- The lowest correct mapping is the Crested Myna, at **0.0012** (3 observations against 2,514).

A wrong-taxon mapping shows up as a difference of orders of magnitude, not as a modest shortfall, so the threshold can sit far below the ordinary spread between two sources.

## Decision

- **The threshold is `PLAUSIBILITY_MIN_RATIO = 0.0002`**, in `sources/inaturalist/`. It sits between the one known error (0.000014) and the lowest correct mapping (0.0012). The sample is 28 species with one error, so it is calibrated but thin; every flag is reported in `build-report.md` and can be reviewed and pinned.
- **The expected count is EOD's North American count for the species**: the sum of the species' annual counts across the 64 region lists (US states and Canadian provinces). The catalog build supplies it to the source as `expected_counts`. It is compared with the source's count for the United States and Canada. A regional or global count would change the ratio and is not comparable.
- **A flagged species gets no candidates from that source** and appears in the report's plausibility section. It is treated as a mapping error, not as rarity, as in 0008. A species with no expected count is not checked.
- The check stays a guard against mapping errors and is no substitute for the taxon-name gates each source already applies.
