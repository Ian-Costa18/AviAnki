# Source layout

The living map of the repo's layout, from [ADR 0018](adr/0018-package-layout.md). Update it in the same change as any file that adds, removes or moves a slice.

**Status:** built. AviAnki 1.0 matches this layout: the catalog pipeline, the catalog client, `deck/`, the 1.0 `avianki` CLI and the web app in `web/`. `sources/allaboutbirds/` is present but deliberately unregistered ([ADR 0002](adr/0002-allaboutbirds-dormant.md)).

```text
src/avianki/
  core/                  imports nothing from avianki
    http.py              throttled, cached, budgeted client; honours Limits and Retry-After; one User-Agent
    licences.py          exact versioned allowlist; AssetRecord (licence research §5.1)
    log.py               the "bird_deck" logger setup
    text.py              `fold`, the case-, accent- and space-insensitive key every name lookup uses; `use_utf8_output`, which keeps a redirected stream on Windows from crashing on a non-ASCII name
  taxonomy/              → core
    species.py           loads data/species.csv (shipped in the wheel): minted ids, per-source keys, aliases, the optional IOC name (ADR 0027)
    regions.py           loads data/regions.csv (shipped in the wheel): slug ↔ GADM gid ↔ eBird code
  sources/               → core, taxonomy
    __init__.py          re-exports the contract (contract.py) only, never the registry or a source
    contract.py          SpeciesSource, AssetSource, Candidate, FetchedAsset, Limits
    registry.py          registered sources and the ordered list per asset kind
    gbif/                SpeciesSource: eBird Observation Dataset facets, IOC scientific names, eBird English names for new species (ADR 0026)
    commons/             AssetSource: Wikipedia lead image + Commons audio
      source.py            CommonsSource: batched Wikipedia/Wikidata/Commons queries, fetch, resolve_pin
      parse.py             pure: payload parsers, taxon guard, photo/audio gates, credit chain, ranking
      xenocanto.py         xeno-canto API v3 metadata lookup (grade, background species) that orders Commons audio; the key is a secret param, ADR 0031
    inaturalist/         AssetSource: photo fallback, audio
      source.py          INaturalistSource: taxon mapping + plausibility check (ADR 0008), candidates, fetch, pins
      parse.py           pure: /taxa, species_counts and observation parsing; the photo and sound gates (ADR 0011)
    ebird/               SpeciesSource, republishable=False, used only by catalog/adhoc.py
      source.py            EbirdSpeciesSource: species list + taxonomy over the injected HttpClient; the token goes in a header
      parse.py             pure: species-code list and taxonomy payload parsers
    allaboutbirds/       present, NOT registered (dormant, ADR 0002); scrape.py is the 0.9 scraper, unused
  media/                 → core
    __init__.py          docstring; re-exports MediaError
    errors.py            MediaError, ImageRejected (no third-party imports)
    images.py            inspect, resize → WebP, byte cap; needs Pillow (extra avianki[catalog])
    audio.py             window trim, high-pass, loudnorm, MP3 via ffmpeg on PATH
    verify.py            BirdNET scoring (optional extra: avianki[verify]; Python 3.11-3.13): the 0.5 gate, the clip start, presence/competitor/quality and every audio threshold (ADR 0031)
  catalog/               → sources, media, taxonomy, core
    __init__.py          docstring only, so importing catalog.format never pulls in sources/
    format.py            JSON Schemas + dataclasses for the published format  ← THE CONTRACT
    species_lists.py     region species lists + minting into species.csv (§4 step 2)
    credit.py            renders the answer-side credit HTML (ADR 0012)
    pins.py              loads and validates data/pins.toml; a pin is "<source>:<token>"
    select.py            pure selection rules: candidate screening, stickiness (including the audio rule), good/usable/best-quality audio choice, provenance and credit for a chosen asset, overall species order
    build.py             pipeline orchestration: run_build(), and the public build_species() used by adhoc.py
    adhoc.py             the one place the CLI crosses upstream: eBird species list, id mapping, live build of species the catalog lacks (`avianki --ebird`, ADR 0017)
    validate.py          the publish gate (ADR 0014): stable-coded checks, shrink limits, `format_result`
    report.py            `BuildReport` + build-report.md (with the audio quality distributions), contact-sheet.html, credits.html
    client.py            reads a published catalog (manifest → region → species → media) from a URL or directory into a per-user cache; imports only format and core, works without the catalog extra
  deck/                  → catalog.format, catalog.client, core   (never sources/ or media/)
    notetypes.py         three note types (each its own front, one shared back), frozen card types, model seeds and field list (IocName appended, ADR 0027), `models_for(theme, name_on_photo)` (ADR 0028)
    card.css             card styling: the `.av` layout, night mode, `.credits`, the `.ioc-tag` (ADR 0025, 0027)
    name-on-photo.css    the layout CSS for `--name-on-photo`: names on a gradient over the photo (ADR 0028)
    themes.py            theme tokens, the built-in registry, token validation, TOML in and out, `compose_css` (ADR 0028)
    themes/              `_template.css` (tokens to CSS) and the extra rules of the built-ins that have some (`nord.css`, `serif.css`, ...)
    credits.py           Credits field + deck description
    build.py             frozen deck id and note GUID, `select_species` (month filter, media check, tier), `plan_notes`, the genanki writer `write_deck` (takes the theme and layout)
  cli.py                 `avianki REGION` and `avianki --ebird CODE` (ADR 0017)
  catalog_cli.py         `avianki-catalog build`  (`build --species-only` runs the species half alone; validation and the reports run inside `build`)
  redact.py              imports nothing from the package; unused until Description→Name returns

web/                     imports no Python; depends only on catalog/format.py's documented schema
  index.html             three screens (Pick, Building, Done) and the footer
                         (no credits.html here: the catalog publishes `catalog/credits.html` and the footer links to it, next to whichever manifest is in use)
  js/
    app.js               the page: pick, `selectSpecies`, `planParts`, `buildDeck` fed from Cache Storage, download, Done screen, focus and error handling
    catalog.js           manifest (no-cache, format check), region and species files, media through Cache Storage, 2 retries with backoff, `?catalog=` override
    select.js            `selectSpecies` (month filter, media check, tier) and `planNotes` (card types, first assets); mirrors deck/build.py, proven on tests/fixtures/selection/cases.json
    deck.js              `buildDeck`: notes, fields, credits, description, ids; documents the media-feed contract
    notetypes.json       the three note types (with `req`), the fixed description strings and the look data (theme tokens, template, value tables), generated from deck/ by scripts/gen_web_notetypes.py
    themes.js            ADR 0028: token validation, the CSS template filled by the same rule as deck/themes.py, TOML, the page-address form of a look
    preview.js           the live card preview: a small mustache renderer, sandboxed iframes, the replay-button lookalike, the placeholder card
    customize.js         the "Customize your cards" section: theme picker, name-on-photo, custom editor, Copy theme, address and localStorage
    lastmile.js          `detectPlatform` (pure, unit-tested with sample user agents) and `renderStudyGuide`, the device tabs (ARIA tabs, detected device selected) shown on the first screen and on Done
    parts.js             ADR 0006: `planParts` (150 species per package on a constrained device), file names, the `?partSize=` test hook, out-of-memory detection, the bird counter for progress  (a module of its own so the rule is testable without the page)
    apkg/                the .apkg writer, reproducing genanki 0.13.1's output
      writer.js          SQLite via sql.js, then a streamed store-mode zip (fflate) into Blob parts
      schema.js          the collection schema and the col row's literals
      pyjson.js          `json.dumps`-compatible JSON (separators, ensure_ascii, key order)
      md5.js             md5 for the frozen deck and note-type ids
      guid.js            genanki's `guid_for` (SHA-256, base 91) for the frozen note GUID
      prefetch.js        `orderedPrefetch`: a bounded (6 in flight), in-order media feed
  vendor/                sql-wasm.js, sql-wasm.wasm, fflate.js (pinned versions, checked in; README.md records versions, sources and sha256)
  css/app.css            one mobile-first column, light and dark, no images

src/avianki/data/        package data: ships in the wheel, found through taxonomy.DATA_DIR (issue #51)
  species.csv            minted species ids (ADR 0008), with an ioc_name column (ADR 0027)
  regions.csv            region slugs ↔ GADM gids, GADM version pinned
  pins.toml              pins, exclusions, credit-removal requests (ADR 0011)

tests/                   mirrors src/avianki/
  core/ taxonomy/ sources/ media/ catalog/ deck/ cli/ packaging/
  deck/, cli/            also hold test_themes.py (registry, contrast, safety) and test_cli_theme.py; test_identity.py pins every theme and layout
  scripts/               assemble_site.py (test_assemble_site_versioning.py: every import, fetch and tag of the assembled shell resolves inside v/<sha>/) and fetch_latest_catalog.sh (fake `gh` on PATH); gen_web_notetypes.py keeps web/js/notetypes.json equal to deck/; weekly_summary.py's gate; the workflow files' shape (publish is manual, no examples step)
  sources/, catalog/     also hold the weekly live checks (integration): test_sources_live.py, test_gbif_live.py, test_published_site_live.py
  test_layout.py         enforces the dependency rule
  web/                   pytest + Playwright (Chromium and WebKit; skipped when a browser is missing)
    web_support.py       static server for web/ + a catalog (manifest served with `base_url` rewritten to itself, CORS open), the in-page build driver, the same build through Python, a package reader; `python tests/web/web_support.py` serves the app locally
    app_support.py       drives the real page (pick, build, collect downloads), the expected GUIDs from the Python side, import into one Anki collection and the acceptance checks
    synthetic_catalog.py 400-species catalog of random-byte media (about 16 MB Standard, 64 MB Everything) made at test time with the real writers, never committed
    conftest.py          session server and browsers; `page` runs each test in both engines; `new_context` opens contexts (devices, init scripts)
    test_web_select.py            select.js against the shared selection cases and plan_notes
    test_web_apkg_equivalence.py  browser .apkg vs genanki's: col JSON text, every row and column, media map and bytes
    test_web_units.py             md5, GUID, JSON, escaping, description, prefetch, media-feed misuse
    test_web_themes.py            themes.js vs deck/themes.py for every theme, layout and a custom token set; validation parity; the photo, credits and names in the browser (several aspect ratios)
    test_web_customize_e2e.py     the Customize section: picker, checkbox, custom editor, Copy theme, address and localStorage; the built deck's CSS equals Python's
    test_web_anki_import.py       browser decks imported by Anki's backend (clean media, no name leak, credits)
    test_web_heap.py              JS heap before/after a build (records, never asserts)
    test_web_vendor.py            web/vendor hashes match its README
    test_web_app_e2e.py           the page in both engines: Massachusetts, advanced options, Québec, errors, Cache Storage, `?catalog=`, accessibility
    test_web_parts.py             `parts.js` units, and constrained-device builds in parts (three packages equal the single package, out-of-memory fallback)
    test_web_lastmile.py          platform detection, the device tabs (roles, keyboard, detected tab, readable before building, same on Done), Share only when `canShare` says so
    test_web_catalog_url.py       `?catalog=` honoured on localhost only, never on the public site
    test_web_cache_busting.py     an assembled site (assemble_site.py) builds a deck from v/<sha>/ files only; a stale index.html reloads once and recovers, never loops
    test_web_shell_budget.py      html + css + js + vendored js under 150 KB gzipped (only the wasm excluded)
    test_web_mobile_heap.py       Pixel 7 profile, 4x CPU throttle, 256 MB heap cap: Standard and Everything-in-parts on the synthetic catalog; iPhone 14 in WebKit
    test_web_live_catalog.py      one build from the published catalog (integration)
  acceptance/            built decks through Anki's own backend (ADR 0019); the live us-ma check is marked integration
  fixtures/catalog/      a tiny published catalog (3 regions, 12 species, ~90 KB) for web + CLI tests; make_fixture.py regenerates it with the real writers (needs the catalog extra and ffmpeg)
  fixtures/selection/    cases.json: language-neutral selection cases shared by deck/ and web/js/select.js

scripts/
  assemble_site.py         stdlib-only: catalog dir + web/ (or a stub index) → the Pages tree (index.html at the root, the app's own files under v/<sha>/, ADR 0029), .nojekyll, 900 MB guard
  fetch_latest_catalog.sh  downloads and extracts the newest catalog-* release; shared by catalog.yml and pages.yml
  gen_web_notetypes.py     dumps deck/'s note types and description strings to web/js/notetypes.json; `--check` for drift
  weekly_summary.py        reads the weekly run's JUnit report: writes the job summary, fails on any skip but eBird's
  gen_card_shots.py        two stages: a card studio renders deck/'s templates and themes with live catalog media in
                           Chromium, then a compositor animates those pixels → docs/examples/ and the README's gen: blocks

.github/workflows/
  ci.yml                 lint, types, unit tests, layout test, browser tests (installs Chromium and WebKit); vulture, deptry and a 1% jscpd threshold
  catalog.yml            monthly + dispatch: load previous release → build → validate → release → deploy Pages
  pages.yml              on push to web/: pull latest catalog release → deploy Pages
  species-lists.yml      dispatch, maintainer-only: species lists + minted species.csv as an artifact
  weekly-integration.yml ADR 0020: source smoke tests, GBIF EOD, the published site and app, live acceptance; eBird only with a key
  publish.yml            PyPI, manual dispatch only with a tag that must match the version
```

## The dependency rule

> Nothing downstream of the published catalog imports anything upstream of it.

`deck/`, `cli.py` and `web/` sit downstream. `sources/` and `media/` sit upstream. `catalog/format.py` is the boundary between them. The only permitted crossing is `cli.py` importing `catalog/adhoc.py` for `--ebird`, which calls `catalog.build.build_species()` and the eBird source (amended in M5: one module rather than one function, because the CLI also needs its exceptions). `tests/test_layout.py` enforces the rule.
