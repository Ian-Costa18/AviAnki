# Contributing to AviAnki

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and [ffmpeg](https://ffmpeg.org/) (ffmpeg is only needed for the catalog build, `--ebird` audio and regenerating the fixture catalog)
2. Clone and install dev dependencies:

   ```bash
   git clone https://github.com/Ian-Costa18/avianki.git
   cd avianki
   uv sync --group dev --extra catalog
   ```

3. Copy `.env.example` to `.env` and add your eBird API key (`EBIRD_API_KEY`) if you plan to test `avianki --ebird` or run the integration tests

## Quick verification checklist

Run these before opening a PR:

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ty check src/
```

## Development workflow

```bash
uv run ruff check src/ tests/                  # lint
uv run ty check src/                           # type check
uv run --with vulture vulture                  # dead code (settings in pyproject.toml; CI runs it)
uv run --with deptry deptry src                # undeclared or unused dependencies (CI runs it)
uv run pytest --integration --cov=avianki --cov-report=html # run all tests, including the integration tests, and coverage with HTML report
uv run pytest tests/acceptance                 # build decks and import them into Anki's own backend
# Test all Python versions we have in the classifiers
uv python install 3.10 3.11 3.12 3.13 3.14 # one-time: install
uv run --python 3.10 pytest
uv run --python 3.11 pytest
uv run --python 3.12 pytest
uv run --python 3.13 pytest
uv run --python 3.14 pytest
```

Fix Dependabot alerts as soon as you see them: `uv lock --upgrade-package NAME`, then run the tests, in a commit of their own.

The integration tests hit real network sources and are skipped by default. Pass `--integration` to opt in, and add `-m integration` to run only them. They are the weekly check's tests (below) plus the live BirdNET test, which needs the `verify` extra (`uv sync --extra verify` on Python 3.11-3.13). A network failure fails the test; the only skip is the eBird test without `EBIRD_API_KEY`.

### The weekly integration check

[`weekly-integration.yml`](.github/workflows/weekly-integration.yml) runs every Friday and on demand, and follows [ADR 0020](docs/adr/0020-integration-monitoring.md). It covers four checks:

1. **Source smoke tests** (`tests/sources/test_sources_live.py`): Commons and iNaturalist each return photo candidates for Northern Cardinal, Brown Pelican and Whimbrel, and every photo and audio candidate has a complete licence record. A source with no audio returns an empty result, never an error. The sources are built like the catalog build builds them, with no HTTP cache.
2. **GBIF EOD** (`tests/sources/test_gbif_live.py`): `species_for("us-ma")` lists at least 300 species. Uncached, this is about 400 extra requests and takes 6-8 minutes. A changed EOD dataset version is a notice in the job summary, not a failure: the next catalog build picks it up.
3. **The published site** (`tests/catalog/test_published_site_live.py`, plus the live deck in `tests/acceptance/test_acceptance_live.py` and the live web build in `tests/web/test_web_live_catalog.py`): the manifest loads, random media files return 200 with `access-control-allow-origin: *`, and the web app root serves the app's `<title>`.
4. **eBird** (`tests/sources/test_ebird_live.py`): runs only when the `EBIRD_API_KEY` secret is set. That is the one allowed skip, and the job summary says so prominently.

`scripts/weekly_summary.py` reads the JUnit report, writes the job summary and fails the job if any other test was skipped, or a check ran no tests. A failed run opens (or updates) a "Weekly integration check is failing" issue. To run it locally, use Python 3.13 so BirdNET runs: `uv run --python 3.13 --extra catalog --extra verify pytest --integration -m integration -rs`.

The acceptance tests (ADR 0019) use the `anki` package, a dev dependency, so they run wherever the dev group is installed. They cover imports, re-imports, tier upgrades, front-of-card name leaks and credits.

## Publishing a release

Pushing a tag does **not** publish anything: PyPI needs the maintainer's explicit approval. A release is five steps:

1. Bump the version in `pyproject.toml` (see the [Versioning](#versioning) section for which bump to use):

   ```bash
   uv version --bump patch   # or minor / major
   ```

2. Commit it with the lockfile and merge it to `main` through a pull request:

   ```bash
   git add pyproject.toml uv.lock
   git commit -m "Bump version to $(uv version --short)"
   ```

3. Tag the merge commit on `main` and push the tag (the tag is `v` plus the version, e.g. `v1.0.0`):

   ```bash
   git tag v$(uv version --short)
   git push origin v$(uv version --short)
   ```

4. Create the GitHub release from that tag (for example `gh release create v1.0.0 --generate-notes`).
5. A maintainer runs the **Publish to PyPI** workflow from the Actions tab (Run workflow) with the tag, e.g. `v1.0.0`.

The [publish workflow](.github/workflows/publish.yml) checks out that tag and fails if it is not `v` plus `project.version` in `pyproject.toml`. It then runs the test suite (the same setup as CI: the `catalog` extra and the Playwright browsers), builds the package, and uploads it to PyPI using OIDC trusted publishing under the `pypi` environment, so no token is needed. The upload job builds the exact commit the tests ran on. Configure required reviewers on the `pypi` environment if you want a second approval before the upload.

## Project structure

- `src/avianki/cli.py` — `avianki`, the user CLI: reads the published catalog (`catalog/client.py`) and writes the deck (`deck/`); `--ebird` goes through `catalog/adhoc.py`
- `src/avianki/deck/` — note types and card templates (`notetypes.py`, `card.css`), credits, species selection and the genanki writer (`build.py`)
- `src/avianki/core/`, `taxonomy/`, `sources/`, `media/`, `catalog/` — the catalog pipeline (HTTP client, licences, species and regions, source contract, GBIF, Commons, iNaturalist and eBird sources, image and audio processing, BirdNET verification, species lists, the published-format contract and the client that reads it); see [docs/source-layout.md](docs/source-layout.md) for the layout and dependency rule
- `src/avianki/data/` — `species.csv`, `regions.csv` and `pins.toml`, shipped in the wheel and found through `taxonomy.DATA_DIR`
- `src/avianki/sources/allaboutbirds/` — the 0.9 scraper, dormant and deliberately not registered (ADR 0002)
- `src/avianki/catalog_cli.py` — `avianki-catalog`, the maintainer-only catalog build (`build`, or `build --species-only`); a dev run is `uv run avianki-catalog build --regions us-ri,us-dc --max-species 30 --out build --cache-dir .cache/http`, and the audio check needs the `verify` extra (or pass `--no-verify`). `src/avianki/data/pins.toml` holds reviewer pins and exclusions
- `.github/workflows/catalog.yml` — the monthly (and on-demand) catalog build: it restores the previous release as state, runs `avianki-catalog build --update-species-csv`, uploads a `build-review` artifact (report, contact sheet, log, species.csv), then releases `catalog-YYYY-MM-DD` and deploys Pages. Run it from the Actions tab with `publish` off to build and validate without releasing. `.github/workflows/pages.yml` redeploys Pages from the newest release when only `web/` changes
- `scripts/assemble_site.py` (the Pages tree from a catalog and `web/`, with the 900 MB guard) and `scripts/fetch_latest_catalog.sh` (download the newest `catalog-*` release) — used by those workflows, and both have tests under `tests/scripts/`

See [CLAUDE.md](CLAUDE.md) for a deeper walkthrough of the data flow and key constraints.

## Extending cards and catalog data

Most feature work falls into one of these two paths.

### 1) Edit Anki cards (layout, templates, fields)

Each card type is its own `genanki.Model` in `src/avianki/deck/notetypes.py` with a single template: the front, and the one standard back all three share (ADR 0025): photo, name, scientific name, recording, credits. All models share the same `FIELDS` tuple and the CSS in `src/avianki/deck/card.css`. Model seeds, note GUIDs and the deck id are frozen (ADR 0009); `tests/deck/test_identity.py` pins them, and you must not edit those expected strings.

**To add a new card type:**

- Add it to `CARD_TYPES`, `MODEL_SEEDS` and `_NOTE_TYPES` (model name, template name, front, back) in `notetypes.py`, with a new, unique seed string. The `--cards` parser in `cli.py` takes its names from `CARD_TYPES` (`photo_audio` is spelled `photo-audio`).
- Teach `plan_notes` in `deck/build.py` (and its mirror `planNotes` in `web/js/select.js`) when a species gets that note, then regenerate `web/js/notetypes.json` with `scripts/gen_web_notetypes.py`.
- Add tests under `tests/deck/`, and an acceptance test if the front or back changes what a learner sees.

**Fields:**

- Keep field order stable: Anki maps fields by position, not name. Always append new fields; never reorder or remove existing ones.
- If you add a field, update `FIELDS` in `notetypes.py` and the note builder in `deck/build.py` in the same PR.

**Styles:**

- Edit `src/avianki/deck/card.css` for layout changes. All models share it at build time.

**Model IDs and GUIDs:**

- Each model's ID is derived from its seed string via `stable_id()`, and each note's GUID from the species id and card type. Never change either for a published note type: it would orphan existing cards in users' Anki collections.

### 2) Add or change catalog data

The catalog is built by `avianki-catalog build` (see [docs/source-layout.md](docs/source-layout.md)) and read by `avianki`. Sources live under `src/avianki/sources/`, selection rules in `catalog/select.py`, and the published format (the contract with the CLI and the web page) in `catalog/format.py`. Changing the format is a breaking change: bump `FORMAT_VERSION` and update `web/` and `catalog/client.py` together. The dependency rule in `tests/test_layout.py` decides what may import what.

For either path, run the quick verification checklist before opening a PR.

## Versioning

This project follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

| Bump | When |
| ---- | ---- |
| `MAJOR` | Breaking changes — anything that orphans existing Anki cards or requires a fresh import: changing a model seed string, reordering or removing fields, renaming a deck seed, changing note GUIDs |
| `MINOR` | New features that are backward-compatible: new card types, new fields (appended), new CLI flags |
| `PATCH` | Bug fixes, CSS tweaks, source fixes, documentation |

## Submitting changes

- Run `uv run pytest`, `uv run ruff check src/ tests/`, and `uv run ty check src/` before opening a PR
- Keep PRs focused — one feature or fix per PR
- Open an issue first for significant changes

## Notes for CLI changes

- If CLI flags or defaults change, update `README.md` in the same PR (options table and examples).
- Prefer `pathlib.Path` for filesystem code; avoid introducing `os.path` paths in new code.
