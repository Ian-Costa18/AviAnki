# Architecture Decision Records

Each file records one decision. The GitHub ticket linked from it has the full discussion, and the linked research branch has the evidence. The spec that puts them all together is [`docs/web-app-spec.md`](../web-app-spec.md).

An accepted ADR is not edited to change its decision. To change it, write a new ADR that supersedes it, and mark the old one `Superseded by NNNN`.

| # | Decision | Tickets |
|---|---|---|
| [0001](0001-build-time-pipeline-static-catalog.md) | Build-time pipeline and a static catalog, not live scraping | #7 |
| [0002](0002-allaboutbirds-dormant.md) | allaboutbirds.org is dormant code, not a registered source | #8, #5, #27 |
| [0003](0003-north-america-on-github-pages.md) | North America only, hosted free on GitHub Pages | #11, #16 |
| [0004](0004-species-lists-from-gbif.md) | Region species lists come from GBIF's eBird Observation Dataset | #29 |
| [0005](0005-media-sources.md) | Commons and iNaturalist supply the media; no Wikipedia or xeno-canto at v1 | #13, #14, #15, #31 |
| [0006](0006-browser-builds-the-apkg.md) | The browser builds the `.apkg`, streaming, and on phones too | #18, #34 |
| [0007](0007-source-contract.md) | Two narrow source contracts with declared limits | #20 |
| [0008](0008-species-and-region-identity.md) | Minted species ids under IOC; GADM level-1 regions | #20 |
| [0009](0009-note-identity.md) | One `AviAnki` deck; GUID = f(species id, card type); the old CLI identity is broken on purpose | #35 |
| [0010](0010-card-types.md) | Photo and Audio cards by default, Photo+Audio optional, Description deferred | #9, #23, #25, #32 |
| [0011](0011-media-selection.md) | Automatic media selection, with BirdNET verifying audio | #10, #33 |
| [0012](0012-attribution.md) | Credits go on the answer side of every card, and dataset credit goes in the deck description | #22 |
| [0013](0013-catalog-layout.md) | Content-addressed files per asset, plus a small manifest | #28 |
| [0014](0014-catalog-rebuilds.md) | Monthly incremental rebuilds, sticky selections, a validation gate | #24 |
| [0015](0015-region-picker-and-tiers.md) | A state/province picker with a Standard (100) default | #19 |
| [0016](0016-last-mile.md) | Explain Anki before the build and give per-platform steps after it | #36 |
| [0017](0017-cli-reads-the-catalog.md) | The CLI is a catalog client, with an explicit `--ebird` escape hatch | #37 |
| [0018](0018-package-layout.md) | Vertical slices with a dependency rule enforced by a test | #21 |
| [0019](0019-verification-without-a-human.md) | Decks are verified automatically: Anki's backend, Playwright and BirdNET | #33, #34 |
| [0020](0020-integration-monitoring.md) | The weekly check fails loudly and watches the real sources | #26 |
| [0021](0021-contract-field-additions.md) | Four fields beyond the §5.1 record: `licence_version_assumed` and three ranking hints (amends 0007) | #40 |
| [0022](0022-plausibility-threshold.md) | The plausibility threshold is 0.02%, not 5%, and compares like with like (amends 0008) | #41 |
| [0023](0023-audio-first-pass.md) | Audio: first candidate that passes BirdNET wins, analysing only the first minute (amends 0011) | #41 |
| [0024](0024-species-names-from-ebird-verbatim.md) | A GBIF backbone key takes the name eBird itself gives its records (amends 0004) | #56 |
| [0025](0025-card-design.md) | Card design: photo first, the phone's own font, night mode, and an IOC tag (amends 0012) | #68 |
| [0026](0026-north-american-common-names.md) | Cards use eBird's English names; IOC stays the taxonomy (amends 0004, 0008) | — |
| [0027](0027-ioc-name-field.md) | The IocName field: a ninth field for the IOC tag (amends 0009) | — |
| [0028](0028-card-themes.md) | Card themes, name on the photo and custom themes: CSS only, defined once in Python (amends 0025) | #67 |
| [0029](0029-versioned-web-assets.md) | The website's own files are versioned per deploy (`v/<sha>/`), with a reload-once fallback for a stale page | #79 |
| [0030](0030-friendly-copy-and-device-tabs.md) | Friendlier wording, device tabs, and a study guide you can read before building (amends 0016) | #80 |
