# 0021 — Four fields beyond the §5.1 record: one licence flag and three ranking hints

**Status:** Accepted, 2026-09-28; two more hints added by [0031](0031-audio-quality-selection.md) · **Amends:** [0007](0007-source-contract.md) · **Ticket:** [#40](https://github.com/Ian-Costa18/AviAnki/issues/40)

## Context

ADR 0007 holds `Candidate` and `FetchedAsset` to the licence research §5.1 field list and says any new field needs an ADR. Building the contract in M2 surfaced two needs that the list doesn't cover:

- **Where a licence version was assumed.** [0012](0012-attribution.md) says a credit line must carry the title when the licence version is unknown at the source, as with iNaturalist's unversioned `cc-by`. The catalog records such an asset as `CC-BY-4.0` (spec §4), so the fact that the version was *assumed* would otherwise be lost. The credit renderer and the validation gate would then apply the 4.0 rules and could drop a required title.
- **Filtering and ranking before download.** [0011](0011-media-selection.md) rejects photos under 800 px on the long side and ranks iNaturalist candidates by identification agreements. Both are known from metadata. Without them on the candidate, the pipeline would have to download an asset before it could reject it, or know which source produced it.

## Decision

- `AssetRecord` gains **`licence_version_assumed: bool`** (default `False`). The licence resolver sets it when it maps an unversioned licence to a versioned id. It's serialised into provenance, so an audit can see why a title was required.
- `Candidate` gains three optional, source-agnostic hints, where `None` means the source doesn't say:
  - **`width`** and **`height`** (pixels), for the 800 px rule
  - **`agreements`** (community identification agreements), for ranking
- `FetchedAsset` is unchanged.

The hints steer selection only. They never reach the published catalog, which stays neutral about its sources ([0013](0013-catalog-layout.md)).

## Consequences

- ADR 0007's rule stands: any further field needs another ADR.
- Sources that can't supply a hint leave it `None`. The pipeline then measures after download, as it has to for audio anyway.
