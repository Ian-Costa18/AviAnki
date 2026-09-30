# Source layout

The living map of the repo's layout, from [ADR 0018](adr/0018-package-layout.md). Update it in the same change as any file that adds, removes or moves a slice.

**Status:** M5 is done: the 1.0 pipeline (catalog client, then deck) is built end to end, `cli.py` is rewritten, and the 0.9 flat modules are gone. Everything under `src/avianki/` is built; items marked *(today)* exist. In `web/`, the deck half is built (M6: `js/select.js`, `js/deck.js`, `js/apkg/`, `js/notetypes.json`, `vendor/`) with its tests in `tests/web/`; the page, catalog fetching and last-mile modules are not yet. `sources/allaboutbirds/` is present but deliberately unregistered ([ADR 0002](adr/0002-allaboutbirds-dormant.md)).

```text
src/avianki/
  core/                  imports nothing from avianki
    http.py              throttled, cached, budgeted client; honours Limits and Retry-After; one User-Agent  (today)
    licences.py          exact versioned allowlist; AssetRecord (licence research §5.1)  (today)
    log.py               the "bird_deck" logger setup  (today)
  taxonomy/              → core
    species.py           loads data/species.csv (shipped in the wheel): minted ids, per-source keys, aliases  (today)
    regions.py           loads data/regions.csv (shipped in the wheel): slug ↔ GADM gid ↔ eBird code  (today)
  sources/               → core, taxonomy
    __init__.py          re-exports the contract (contract.py) only, never the registry or a source
    contract.py          SpeciesSource, AssetSource, Candidate, FetchedAsset, Limits  (today)
    registry.py          registered sources and the ordered list per asset kind  (today)
    gbif/                SpeciesSource: eBird Observation Dataset facets, IOC names  (today)
    commons/             AssetSource: Wikipedia lead image + Commons audio  (today)
      source.py            CommonsSource: batched Wikipedia/Wikidata/Commons queries, fetch, resolve_pin
      parse.py             pure: payload parsers, taxon guard, photo/audio gates, credit chain, ranking
    inaturalist/         AssetSource: photo fallback, audio  (today)
      source.py          INaturalistSource: taxon mapping + plausibility check (ADR 0008), candidates, fetch, pins
      parse.py           pure: /taxa, species_counts and observation parsing; the photo and sound gates (ADR 0011)
    ebird/               SpeciesSource, republishable=False, used only by catalog/adhoc.py  (today)
      source.py            EbirdSpeciesSource: species list + taxonomy over the injected HttpClient; the token goes in a header
      parse.py             pure: species-code list and taxonomy payload parsers
    allaboutbirds/       present, NOT registered (dormant, ADR 0002); scrape.py is the 0.9 scraper, unused  (today)
  media/                 → core
    __init__.py          docstring; re-exports MediaError  (today)
    errors.py            MediaError, ImageRejected (no third-party imports)  (today)
    images.py            inspect, resize → WebP, byte cap; needs Pillow (extra avianki[catalog])  (today)
    audio.py             window trim, high-pass, loudnorm, MP3 via ffmpeg on PATH  (today)
    verify.py            BirdNET gate (optional extra: avianki[verify]; Python 3.11-3.13)  (today)
  catalog/               → sources, media, taxonomy, core
    __init__.py          docstring only, so importing catalog.format never pulls in sources/
    format.py            JSON Schemas + dataclasses for the published format  ← THE CONTRACT  (today)
    species_lists.py     region species lists + minting into species.csv (§4 step 2)  (today)
    credit.py            renders the answer-side credit HTML (ADR 0012)  (today)
    pins.py              loads and validates data/pins.toml; a pin is "<source>:<token>"  (today)
    select.py            pure selection rules: candidate screening, stickiness, provenance and credit for a chosen asset, overall species order  (today)
    build.py             pipeline orchestration: run_build(), and the public build_species() used by adhoc.py  (today)
    adhoc.py             the one place the CLI crosses upstream: eBird species list, id mapping, live build of species the catalog lacks (`avianki --ebird`, ADR 0017)  (today)
    validate.py          the publish gate (ADR 0014): stable-coded checks, shrink limits, `format_result`  (today)
    report.py            `BuildReport` + build-report.md, contact-sheet.html, credits.html  (today)
    client.py            reads a published catalog (manifest → region → species → media) from a URL or directory into a per-user cache; imports only format and core, works without the catalog extra  (today)
  deck/                  → catalog.format, catalog.client, core   (never sources/ or media/)
    notetypes.py         three note types, frozen card types, model seeds and field list  (today)
    card.css             carried-forward styling plus `.credits`  (today)
    credits.py           Credits field + deck description  (today)
    build.py             frozen deck id and note GUID, `select_species`, `plan_notes`, the genanki writer `write_deck`  (today)
  cli.py                 `avianki REGION` and `avianki --ebird CODE` (ADR 0017)  (today)
  catalog_cli.py         `avianki-catalog build`  (today; `build --species-only` runs the species half alone; validation and the reports run inside `build`)
  redact.py              imports nothing from the package; unused until Description→Name returns  (today)

web/                     imports no Python; depends only on catalog/format.py's documented schema
  index.html
  credits.html           generated at deploy
  js/
    app.js               the page: picker, advanced, progress, last mile
    catalog.js           manifest/region/species fetch; Cache Storage for media
    select.js            `selectSpecies` (tier, month filter) and `planNotes` (card types, first assets); mirrors deck/build.py, proven on tests/fixtures/selection/cases.json  (today)
    deck.js              `buildDeck`: notes, fields, credits, description, ids; documents the media-feed contract  (today)
    notetypes.json       the three note types (with `req`) and the fixed description strings, generated from deck/ by scripts/gen_web_notetypes.py  (today)
    lastmile.js          platform detection + instructions
    apkg/                the .apkg writer, reproducing genanki 0.13.1's output  (today)
      writer.js          SQLite via sql.js, then a streamed store-mode zip (fflate) into Blob parts
      schema.js          the collection schema and the col row's literals
      pyjson.js          `json.dumps`-compatible JSON (separators, ensure_ascii, key order)
      md5.js             md5 for the frozen deck and note-type ids
      guid.js            genanki's `guid_for` (SHA-256, base 91) for the frozen note GUID
      prefetch.js        `orderedPrefetch`: a bounded (6 in flight), in-order media feed
  vendor/                sql-wasm.js, sql-wasm.wasm, fflate.js (pinned versions, checked in; README.md records versions, sources and sha256)
  css/app.css

src/avianki/data/        package data: ships in the wheel, found through taxonomy.DATA_DIR (issue #51)
  species.csv            minted species ids (ADR 0008)
  regions.csv            region slugs ↔ GADM gids, GADM version pinned
  pins.toml              pins, exclusions, credit-removal requests (ADR 0011)

tests/                   mirrors src/avianki/
  core/ taxonomy/ sources/ media/ catalog/ deck/ cli/ packaging/  (today)
  scripts/               assemble_site.py and fetch_latest_catalog.sh (fake `gh` on PATH); gen_web_notetypes.py keeps web/js/notetypes.json equal to deck/  (today)
  test_layout.py         enforces the dependency rule
  web/                   pytest + Playwright (Chromium and WebKit; skipped when a browser is missing)  (today)
    web_support.py       static server for web/ + the fixture catalog, the in-page build driver, the same build through Python, a package reader
    conftest.py          session server and browsers; `page` runs each test in both engines
    test_web_select.py            select.js against the shared selection cases and plan_notes
    test_web_apkg_equivalence.py  browser .apkg vs genanki's: col JSON text, every row and column, media map and bytes
    test_web_units.py             md5, GUID, JSON, escaping, description, prefetch, media-feed misuse
    test_web_anki_import.py       browser decks imported by Anki's backend (clean media, no name leak, credits)
    test_web_heap.py              JS heap before/after a build (records, never asserts)
    test_web_vendor.py            web/vendor hashes match its README
    (mobile emulation arrives with the UI)
  acceptance/            built decks through Anki's own backend (ADR 0019); the live us-ma check is marked integration  (today)
  fixtures/catalog/      a tiny published catalog (3 regions, 12 species, ~90 KB) for web + CLI tests; make_fixture.py regenerates it with the real writers (needs the catalog extra and ffmpeg)  (today)
  fixtures/selection/    cases.json: language-neutral selection cases shared by deck/ and web/js/select.js  (today)

scripts/
  assemble_site.py         stdlib-only: catalog dir + web/ (or a stub index) → the Pages tree, .nojekyll, 900 MB guard  (today)
  fetch_latest_catalog.sh  downloads and extracts the newest catalog-* release; shared by catalog.yml and pages.yml  (today)
  gen_web_notetypes.py     dumps deck/'s note types and description strings to web/js/notetypes.json; `--check` for drift  (today)

.github/workflows/
  ci.yml                 lint, types, unit tests, layout test, browser tests (installs Chromium and WebKit)  (today)
  catalog.yml            monthly + dispatch: load previous release → build → validate → release → deploy Pages  (today)
  pages.yml              on push to web/: pull latest catalog release → deploy Pages  (today)
  species-lists.yml      dispatch, maintainer-only: species lists + minted species.csv as an artifact  (today)
  weekly-integration.yml ADR 0020                                           (today, to be rewritten)
  publish.yml            PyPI                                               (today)
```

## The dependency rule

> Nothing downstream of the published catalog imports anything upstream of it.

`deck/`, `cli.py` and `web/` sit downstream. `sources/` and `media/` sit upstream. `catalog/format.py` is the boundary between them. The only permitted crossing is `cli.py` importing `catalog/adhoc.py` for `--ebird`, which calls `catalog.build.build_species()` and the eBird source (amended in M5: one module rather than one function, because the CLI also needs its exceptions). `tests/test_layout.py` enforces the rule.
