# AviAnki web app — specification

**Status:** Implemented in 1.0.0, 2026-09-30 (accepted 2026-09-28) · **Map:** [#6](https://github.com/Ian-Costa18/AviAnki/issues/6) · **Product requirements:** [`PRD.md`](PRD.md) · **Decisions:** [`adr/`](adr/README.md) · **Layout:** [`source-layout.md`](source-layout.md)

This spec is the destination of map #6. Someone holding this document, the PRD and the ADRs should be able to build AviAnki 1.0 with no architectural question left open. Where this document and an ADR disagree, the ADR wins, and this document gets fixed.

---

## 1. What gets built

A free, static website where a bird watcher picks their state or province, taps **Build**, and gets an Anki deck of the birds they're most likely to see. Each card has a photo or a recording, verified media, and proper credits. The same catalog also feeds the Python CLI.

```text
            GitHub Actions (monthly)                              GitHub Pages (static)
 ┌──────────────────────────────────────────────┐        ┌──────────────────────────────┐
 │ GBIF EOD ──▶ SpeciesSource ─┐                │        │  index.html + web/js         │
 │                             ▼                │        │  catalog/manifest.json       │
 │ Commons ──▶ AssetSource ─▶ select ─▶ media ──┼─deploy─▶  catalog/species.*.json      │
 │ iNat    ──▶ AssetSource ─┘   (pins,  (resize,│        │  catalog/regions/*.json      │
 │                              sticky) BirdNET,│        │  catalog/media/<hash>.*      │
 │                                      loudnorm│        └──────────────┬───────────────┘
 │            validate ─▶ release tarball       │                       │ fetch (no custom headers)
 └──────────────────────────────────────────────┘          ┌────────────┴────────────┐
                                                           ▼                         ▼
                                          browser: sql.js + fflate          CLI: catalog.client
                                          streams AviAnki.apkg              + genanki → .apkg
```

## 2. Scope of 1.0

| In | Deferred | Out |
|---|---|---|
| US and Canada, one region per state, province and territory | Mexico and the rest of North America | Worldwide catalog (the CLI's `--ebird` covers it) |
| Photo→Name and Audio→Name (default), Photo+Audio→Name (optional) | Description→Name; second photo and second clip; song/call labels | Scheduling, custom reviewer, accounts, servers |
| Standard (100) and Everything (400) tiers; month filter; subdeck option | Radius or hotspot regions | allaboutbirds and Macaulay as sources |
| Automatic selection with BirdNET-verified audio; pins by PR | xeno-canto API | Community voting backend |

## 3. Data identity

- **Species:** minted ids in `src/avianki/data/species.csv`, with IOC as the declared authority ([ADR 0008](adr/0008-species-and-region-identity.md)).
- **Regions:** slugs in `src/avianki/data/regions.csv` over GADM level-1, with the GADM version pinned (ADR 0008).
- **Notes:** deck `AviAnki`; GUID `guid_for("avianki", species_id, card_type)` with `card_type ∈ {photo, audio, photo_audio}`; model seeds `AviAnki_{Photo,Audio,PhotoAudio}_v2` ([ADR 0009](adr/0009-note-identity.md)). All of these strings are frozen, and `tests/deck/test_identity.py` pins them.

## 4. The catalog pipeline

It runs as `avianki-catalog build` in `.github/workflows/catalog.yml`.

1. **Load state.** Download the previous `catalog-*` release tarball, if there is one: its manifest, provenance and media.
2. **Species.**
   - Check the EOD dataset version. If it has changed, or there's no previous state, call `GbifSpeciesSource.species_for(region)` for every region in `regions.csv`, map to species ids (each GBIF backbone key named by eBird's own name for its records, [ADR 0024](adr/0024-species-names-from-ebird-verbatim.md)), and write each region's ordered list with 12 monthly values.
   - The catalog's species set is the union of each region's top 400.
   - Species with no row in `species.csv` are minted and appear in the build report as a diff to commit.
3. **Select, per species and role** ([ADR 0011](adr/0011-media-selection.md)):
   1. Apply pins from `pins.toml`.
   2. Keep sticky assets that are still valid ([ADR 0014](adr/0014-catalog-rebuilds.md)).
   3. Fill what's still missing with ordered fill over the registered sources ([ADR 0007](adr/0007-source-contract.md)), with licence gate → generic rejects → download → measure → BirdNET (audio, first minute only; the first candidate that passes wins, [ADR 0023](adr/0023-audio-first-pass.md)) → rank (photos).
   4. A source error keeps the previous entry and is logged. Absence is recorded as absence.
4. **Process.** Images become WebP at 800 px on the long side, q80, capped at 150 KB. Audio becomes a 10 s window with high-pass and loudnorm, as MP3. Each step appends to the asset's `modifications`.
5. **Assemble.** Write the content-addressed media, `species.<hash>.json`, `regions/<slug>.<hash>.json`, `provenance.<hash>.json` and `manifest.json`. Also generate `credits.html`, `contact-sheet.html` and `build-report.md`.
6. **Validate.** Run the gate in ADR 0014. On failure, stop: nothing is released and nothing is deployed.
7. **Release and deploy.** Attach the tarball to release `catalog-YYYY-MM-DD`, copy `web/` in next to it, and run `upload-pages-artifact` → `deploy-pages`.

**Etiquette.** Throttling, budget and caching all live centrally in `core.http`:

- **Wikimedia:** requests in series; batch titles with `|`; `maxlag=5`.
- **iNaturalist:** 1 request/s, ≤ 10,000 requests/day; `per_page` at the maximum.
- **User-Agent** everywhere: `AviAnki-catalog/<version> (https://github.com/Ian-Costa18/AviAnki)`.

The first full build of about 1,000 species is expected to take several hours and may span two runs, which [ADR 0014](adr/0014-catalog-rebuilds.md) allows. Steady-state monthly runs touch only new or invalidated species.

**Licence allowlist** (exact ids only): `CC0-1.0`, `PDM-1.0`, `CC-BY-{2.0,2.5,3.0,4.0}`, `CC-BY-SA-{2.0,2.5,3.0,4.0}`. iNaturalist's unversioned `cc-by`/`cc-by-sa` are accepted as `CC-BY-4.0`/`CC-BY-SA-4.0` for the licence URL, but their credits always follow the 3.0 rules and include the title ([ADR 0012](adr/0012-attribution.md)). Everything else is rejected.

## 5. Published catalog format (the Python ↔ browser contract)

It's defined in code by `src/avianki/catalog/format.py` (JSON Schema). This section is the readable version. Paths are relative to `manifest.base_url`.

**`catalog/manifest.json`**, fetched with `cache: "no-cache"`:

```json
{
  "format": 1,
  "catalog_version": "2026-11-01",
  "base_url": "https://ian-costa18.github.io/AviAnki/catalog/",
  "gadm_version": "4.1",
  "species_file": "species.3f9a0c21.json",
  "regions": [
    {"slug": "us-ma", "name": "Massachusetts", "country": "US",
     "file": "regions/us-ma.8c1e44d0.json", "species_count": 400}
  ],
  "dataset_credits": [
    {"text": "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF",
     "licence_id": "CC-BY-4.0", "url": "https://doi.org/10.15468/aomfnb",
     "modifications": "filtered and ranked by region"}
  ],
  "total_bytes": 312000000
}
```

**`catalog/regions/<slug>.<hash>.json`** is in rank order. `monthly` holds relative frequencies from 0 to 255, January first:

```json
{"slug": "us-ma", "species": [["turdus-migratorius", [180,190,230,255,255,250,240,235,230,220,200,185]], ...]}
```

**`catalog/species.<hash>.json`**:

```json
{
  "turdus-migratorius": {
    "name": "American Robin",
    "sci": "Turdus migratorius",
    "photo": [{"file": "media/1a2b3c4d5e6f7a8b.webp", "bytes": 45120,
               "credit": "Photo: <i>Turdus-migratorius-002</i> by <b>Mdf</b> · <a href=\"https://creativecommons.org/licenses/by-sa/3.0/\">CC BY-SA 3.0</a> · <a href=\"https://commons.wikimedia.org/wiki/File:Turdus-migratorius-002.jpg\">source</a> · resized"}],
    "audio": [{"file": "media/9f8e7d6c5b4a3921.mp3", "bytes": 98211, "credit": "Recording: ..."}]
  }
}
```

The `credit` values are pipeline-rendered, escaped HTML that uses only `a`, `b` and `i`. Empty `photo` or `audio` lists mean absence.

**`catalog/provenance.<hash>.json`** maps each media filename to its full licence research §5.1 record. It's for audit only.

**Compatibility.** Adding optional keys doesn't change `format`. Anything else bumps it, and old clients show a "please reload" message.

## 6. The deck (shared by browser and CLI)

**Note types.** There are three, with one template each. They all share these fields:

`SpeciesId, Name, SciName, Photo, Photo2, Audio, Audio2, Credits`

`Photo2` and `Audio2` are reserved and empty at 1.0.

| Note type | Front | Back |
|---|---|---|
| AviAnki · Photo | *What bird is this?* + `{{Photo}}` | `{{Name}}`, `{{SciName}}`, `{{Photo}}`, `{{Audio}}`, `{{Credits}}` |
| AviAnki · Audio | *Who's calling?* + `{{Audio}}` | the same back |
| AviAnki · Photo + Audio | both | the same back |

- **Media filenames** are `avianki_<catalog hash name>`, so identical media stays identical across builds.
- **Fields hold** `<img src="…">` and `[sound:…]`.
- **`card.css`** carries forward the current styling, plus `.credits { font-size: .75em; opacity: .7 }` with underlined links.

**Deck.** `AviAnki`, or `AviAnki::<Region>` with the subdeck option. The description holds:

- the study guidance ([ADR 0016](adr/0016-last-mile.md))
- the dataset credit
- the compilation and licence notice ([ADR 0012](adr/0012-attribution.md))
- for `--ebird` builds only, the not-for-redistribution line

**Selection.**

1. Take the region's ordered list.
2. Apply the month filter if one is set: keep species with `monthly[m] ≥ 0.1 × max(monthly)`, computed in integers as `10 × monthly[m] ≥ max(monthly)` so exactly 10% is kept. A species whose values are all zero is dropped.
3. Keep the species that would get at least one note for the selected card types: a photo card needs a photo, an audio card needs a recording, a photo-and-audio card needs both. A species with no usable media is passed over, not counted.
4. Take the first 100 (Standard) or all of them (Everything).
5. For each kept species, make one note per selected card type whose media exists. Every note carries both of the species' first photo and first recording (when it has them) and both credit lines, because every back shows the photo and plays the recording.

Because the media check comes before the limit, a Standard deck is 100 birds you can study whenever the region has that many: a species without media in the top 100 is replaced by the 101st, and so on down the list.

The browser (`web/js/select.js`, `selectSpecies`) and the CLI (`deck/build.py`, `select_species`) implement this identically, and a shared fixture test (`tests/fixtures/selection/cases.json`) proves it.

*Amended 2026-09-30: the media check (step 3) used to come after the limit, so a bird without media shrank a Standard deck below 100.*

**Part names.** When a build is split, each file is `AviAnki-<region slug>-part-<n>-of-<m>.apkg` (for example `AviAnki-us-ma-part-1-of-3.apkg`), so the parts of two regions never share a name in Downloads. An unsplit build is `AviAnki-<region slug>.apkg`.

## 7. The web app

The code is in `web/`: plain ES modules, vendored `sql.js` and `fflate`, with no build step.

**Screen 1: Pick.**

- A one-line pitch, e.g. *"Learn to recognise the birds where you live, by sight and sound."*
- *Where do you go birding?* A searchable state/province select, grouped by country and remembered in `localStorage`.
- **Build my deck**, with the Anki line underneath ([ADR 0016](adr/0016-last-mile.md)).
- *Advanced* (collapsed): tier, month, card types, subdeck.
- Footer: dataset credit, licence notice, the catalog's `credits.html` (published at `catalog/credits.html`) and a GitHub link.

**Screen 2: Building.** The progress text speaks a bird watcher's language: *"Finding the 100 birds most seen in Massachusetts… Downloading photos and recordings (43 of 100)… Packing your deck…"* (it says "photos", "recordings" or "photos and recordings" to match the cards chosen, and every count agrees in number: "1 bird", "2 birds"). Media is fetched with at most 6 in flight, and read from Cache Storage when it's already there. The zip streams into Blob parts ([ADR 0006](adr/0006-browser-builds-the-apkg.md)). On constrained devices, Everything builds in parts of 150, and the page says so *before* starting.

**Screen 3: Done.** The file downloads automatically, with a **Save again** link and, where supported, a **Share** button. Then come the platform-specific instructions and the *What you'll see* box ([ADR 0016](adr/0016-last-mile.md)), and finally *"Add another region"*, which is additive.

**Errors.**

- **Network failure:** automatic retry, then *"We couldn't reach the bird catalog. Check your connection and try again."*
- **Unknown manifest `format`:** *"AviAnki has been updated. Please reload."*
- **Out of memory:** the next build is automatically split into parts: 150 species each, or halves when the build was already 150 or fewer.

**Budgets.**

- A Standard build is about 16 MB and should land in under 10 s on 50 Mbps.
- The app shell, excluding the 660 KB wasm, should stay under 150 KB, measured gzipped as GitHub Pages serves it (the vendored `sql-wasm.js` and `fflate.js` count).
- Peak JS heap for any build should stay under 200 MB ([ADR 0019](adr/0019-verification-without-a-human.md)).

## 8. The CLI

This is [ADR 0017](adr/0017-cli-reads-the-catalog.md) in full.

- `avianki REGION` reads the catalog and builds with genanki.
- `avianki --ebird CODE` builds anywhere, using the live sources and the not-for-redistribution notice.
- `avianki-catalog` is for maintainers.
- The **version is 1.0.0**, because the identity change breaks existing decks ([ADR 0009](adr/0009-note-identity.md)).
- README's options table and examples are rewritten in the same change.

## 9. Verification

Everything is automated ([ADR 0019](adr/0019-verification-without-a-human.md)):

- **Unit tests** per slice.
- **The layout rule test.**
- **Acceptance tests** that run built decks through Anki's own backend: import, media check, re-import identity, a front-side leak check, and credits present.
- **Browser vs genanki equivalence.**
- **Playwright end-to-end tests**, including mobile emulation under a 256 MB heap cap.
- **The BirdNET gate** and the **catalog validation gate** in every catalog build.

The weekly integration check is [ADR 0020](adr/0020-integration-monitoring.md).

**Not covered:** real iOS Safari and AnkiMobile. A tap-through on a real phone before announcing 1.0 is recommended, not required.

## 10. Build order

Each milestone ships on its own branch with passing `pytest`, `ruff` and `ty`.

| # | Milestone | Done when |
|---|---|---|
| M0 | **Housekeeping.** Bump `soupsieve` (4 Dependabot alerts); fix #30 (case-insensitive `redact_name`); #26 per ADR 0020; remove stale research worktrees. | CI green; Dependabot clear |
| M1 | **Deploy spike.** `catalog.yml` publishes 450 MB of dummy media plus a stub `web/` to Pages. | Deploy time measured and under 8 min, or ADR 0003 revisited |
| M2 | **Taxonomy and species.** `core/`, `taxonomy/`, `sources/contract.py`, `sources/gbif`; mint `species.csv` and `regions.csv`. | `avianki-catalog build --species-only` writes region lists for all regions |
| M3 | **Assets.** `sources/commons`, `sources/inaturalist`, `media/` including BirdNET; `catalog/select.py`, `validate.py`, `report.py`. | A 3-region catalog builds and validates locally; the contact sheet is reviewed |
| M4 | **Real catalog.** Full build in Actions; release and deploy. | Catalog live on Pages |
| M5 | **Deck and CLI 1.0.** `deck/`, `catalog/client.py`, the `cli.py` rewrite, `--ebird`, README, acceptance tests. | `avianki us-ma` produces a deck that passes every acceptance check |
| M6 | **Web app.** `web/` per §7, with the writer ported from the prototype and switched to fflate streaming. | Playwright end-to-end tests, including mobile, pass; the browser build is equivalent to genanki |
| M7 | **Release.** PyPI 1.0.0; weekly check switched to the real sources; this spec's status updated to *Implemented*. | — |

## 11. Known risks

| Risk | Mitigation |
|---|---|
| The Pages deploy exceeds 10 min at full size | **Measured in M1 ([#39](https://github.com/Ian-Costa18/AviAnki/issues/39)): 450 MB in 6,202 files uploaded in ~14 s and deployed in ~18 s.** Fallbacks if that ever changes, in order: drop the Everything tier to 300; split media across a second Pages repo. |
| The first build hits iNaturalist's daily budget | Incremental builds that publish partial progress (ADR 0014) |
| BirdNET rejects too much audio | The build report counts rejects. The threshold (0.5) can be tuned in one place. Pins handle individual cases. |
| iOS memory and hand-off | Parts builds and a Share button; one real-device check recommended |
| Pages bandwidth | Configurable `base_url`; move hosts when GitHub Support emails |
| BirdNET's model licence is NC | Used only as a build tool by a non-commercial project, never redistributed (ADR 0011) |
