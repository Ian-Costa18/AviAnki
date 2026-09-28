# Source layout

The living map of the repo's layout, from [ADR 0018](adr/0018-package-layout.md). Update it in the same change as any file that adds, removes or moves a slice.

**Status:** target layout, partly built (M2 done: core, taxonomy, the source contract, the GBIF source and the species-only build). Items marked *(today)* already exist; the flat 0.9 modules (`cli.py`, `ebird.py`, `allaboutbirds.py`, `anki_model.py`) are still in place.

```text
src/avianki/
  core/                  imports nothing from avianki
    http.py              throttled, cached, budgeted client; honours Limits and Retry-After; one User-Agent  (today)
    licences.py          exact versioned allowlist; AssetRecord (licence research §5.1)  (today)
    log.py               the "bird_deck" logger setup  (today)
  taxonomy/              → core
    species.py           loads data/species.csv: minted ids, per-source keys, aliases  (today)
    regions.py           loads data/regions.csv: slug ↔ GADM gid ↔ eBird code  (today)
  sources/               → core, taxonomy
    __init__.py          re-exports the contract (contract.py) only, never the registry or a source
    contract.py          SpeciesSource, AssetSource, Candidate, FetchedAsset, Limits  (today)
    registry.py          registered sources and the ordered list per asset kind  (today)
    gbif/                SpeciesSource: eBird Observation Dataset facets, IOC names  (today)
    commons/             AssetSource: lead image, audio
    inaturalist/         AssetSource: photo fallback, audio
    ebird/               SpeciesSource, republishable=False, CLI only      (today: ebird.py)
    allaboutbirds/       present, NOT registered                            (today: allaboutbirds.py)
  media/                 → core
    __init__.py          the 0.9 helpers (download_file, trim_to_mp3, find_cached*) until the 1.0.0 CLI rewrite; re-exports MediaError  (today)
    errors.py            MediaError, ImageRejected (no third-party imports)  (today)
    images.py            inspect, resize → WebP, byte cap; needs Pillow (extra avianki[catalog])  (today)
    audio.py             window trim, high-pass, loudnorm, MP3 via ffmpeg on PATH  (today)
    verify.py            BirdNET gate (optional extra: avianki[verify])
  catalog/               → sources, media, taxonomy, core
    __init__.py          docstring only, so importing catalog.format never pulls in sources/
    format.py            JSON Schemas + dataclasses for the published format  ← THE CONTRACT
    species_lists.py     region species lists + minting into species.csv (§4 step 2)  (today)
    credit.py            renders the answer-side credit HTML (ADR 0012)
    select.py            ordered fill, ranking, pins, stickiness
    build.py             pipeline orchestration; public build_species() used by --ebird
    validate.py          the publish gate (ADR 0014)
    report.py            build-report.md, contact-sheet.html, credits.html
    client.py            reads a published catalog (manifest → species → media), with a local cache
  deck/                  → catalog.format, catalog.client, core   (never sources/ or media/)
    notetypes.py         three note types, frozen model seeds         (today: anki_model.py)
    card.css                                                           (today)
    credits.py           Credits field + deck description
    build.py             genanki writer
  cli.py                 `avianki`: deck, catalog, --ebird         (today, to be rewritten at 1.0.0)
  catalog_cli.py         `avianki-catalog build|validate|report`   (today: build --species-only)
  redact.py              CLI-only (core + itself), until Description→Name returns     (today)

web/                     imports no Python; depends only on catalog/format.py's documented schema
  index.html
  credits.html           generated at deploy
  js/
    app.js               the page: picker, advanced, progress, last mile
    catalog.js           manifest/region/species fetch; Cache Storage for media
    select.js            tier, month filter, card-type selection (mirrors deck/ logic)
    lastmile.js          platform detection + instructions
    apkg/                writer ported from prototype/apkg-in-browser (md5, guid, pyjson, req, schema)
  vendor/                sql-wasm.js, sql-wasm.wasm, fflate.js (pinned versions, checked in)
  css/app.css

data/
  species.csv            minted species ids (ADR 0008)
  regions.csv            region slugs ↔ GADM gids, GADM version pinned
  pins.toml              pins, exclusions, credit-removal requests (ADR 0011)

tests/                   mirrors src/avianki/
  core/ taxonomy/ sources/ media/ catalog/ deck/
  test_layout.py         enforces the dependency rule
  web/                   Playwright, incl. mobile emulation + heap cap
  acceptance/            built decks through Anki's own backend (ADR 0019)
  fixtures/catalog/      a tiny published catalog (3 regions, 12 species) for web + CLI tests

.github/workflows/
  ci.yml                 lint, types, unit tests, layout test                (today)
  catalog.yml            monthly + dispatch: build → validate → release → deploy Pages
  pages.yml              on push to web/: pull latest catalog release → deploy Pages
  species-lists.yml      dispatch, maintainer-only: species lists + minted species.csv as an artifact  (today)
  weekly-integration.yml ADR 0020                                           (today, to be rewritten)
  publish.yml            PyPI                                               (today)
```

## The dependency rule

> Nothing downstream of the published catalog imports anything upstream of it.

`deck/`, `cli.py` and `web/` sit downstream. `sources/` and `media/` sit upstream. `catalog/format.py` is the boundary between them. The only permitted crossing is `cli.py --ebird` calling `catalog.build.build_species()`. `tests/test_layout.py` enforces the rule.
