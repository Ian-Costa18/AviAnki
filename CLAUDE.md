# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# One-time setup (the catalog extra is needed by the catalog tests)
uv sync --group dev --extra catalog

# Run the CLI locally
uv run avianki REGION [OPTIONS]
uv run avianki --ebird CODE [OPTIONS]

# Maintainer-only catalog build
uv run avianki-catalog build --regions us-ri,us-dc --max-species 30 --out build --cache-dir .cache/http

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/cli/test_cli_catalog.py

# Run a single test by name
uv run pytest tests/cli/test_cli_catalog.py::test_name

# Include the tests that hit the real network (live catalog, eBird)
uv run pytest --integration

# Run tests with coverage
uv run pytest --cov=avianki

# Lint
uv run ruff check src/ tests/

# Type check
uv run ty check src/
```

## Architecture

The layout is in [docs/source-layout.md](docs/source-layout.md) (ADR 0018); update it in the same change as any file that adds, removes or moves a slice. The 1.0 pipeline has two halves joined by a published catalog: **the catalog build (maintainers, monthly) then the user CLI (catalog client, then deck)**.

**Catalog build.** `avianki-catalog` (`catalog_cli.py`) runs `catalog/build.py`: species lists per region (GBIF/eBird occurrence data), then photos and recordings per species from the registered sources (Commons, iNaturalist) under an exact licence allowlist, screened, resized, and audio-verified with BirdNET. The result is a static catalog (manifest, region files, species file, media) published on GitHub Pages. `catalog/validate.py` is the publish gate.

**User CLI.** `cli.py` owns orchestration for `avianki`:

1. **Read the catalog** with `catalog/client.py` (manifest, region, species, media, cached per user). A region is a catalog slug or display name.
2. **Choose and plan** with `deck/build.py`: `select_species` (tier, month) and `plan_notes` (which cards each species gets from `--cards`).
3. **Write the deck** with `deck/build.py:write_deck` (genanki). Note types, card templates and CSS live in `deck/notetypes.py` and `deck/card.css`; credits in `deck/credits.py`.

**`--ebird CODE`** is the one path that goes upstream. `cli.py` imports `catalog/adhoc.py`, which fetches the eBird species list (`sources/ebird`, `republishable=False`, so the registry refuses it; the token goes in a request header and is never cached), maps species onto the catalog where it can and builds the rest live with `catalog.build.build_species()`. Missing ffmpeg or BirdNET degrades to photos-only with a warning; a missing `catalog` extra is a hard error. Transient species ids are minted with `mint_id` and never written to `species.csv`. Every `--ebird` run prints `EBIRD_NOTICE` (personal use only), even with `-q`.

**Dependency rule** (`tests/test_layout.py`, AST-based): nothing downstream of the published catalog imports anything upstream of it. `deck/` may import only `catalog.format`, `catalog.client` and `core`; `cli.py` may import only `core`, `catalog.format`, `catalog.client`, `deck` and `catalog.adhoc`. `sources/` and `media/` are upstream. `sources/allaboutbirds/` is the dormant 0.9 scraper (ADR 0002) and is deliberately not registered.

**Identity is frozen (ADR 0009).** Model seeds, the deck id and note GUIDs (`genanki.guid_for("avianki", species_id, card_type)`) are pinned by `tests/deck/test_identity.py`. Never edit those expected strings; changing them orphans every user's cards.

**Package data.** `species.csv`, `regions.csv` and `pins.toml` live in `src/avianki/data/` and ship in the wheel; find them through `taxonomy.DATA_DIR`, never a repo-relative path (`tests/packaging/test_wheel_data.py` builds the real wheel).

**Exit codes:** 0 done; 1 network, catalog or nothing to write; 2 usage.

**Logging:** A single `logging.Logger("bird_deck")` is used across all modules. `core/log.py` (`setup_logging`) configures its handlers (stdout + file); entry points call it. Other modules just call `log = logging.getLogger("bird_deck")`.

**Tests.** `tests/` mirrors `src/avianki/`. `tests/fixtures/catalog/` is a tiny published catalog used by the CLI tests. `tests/acceptance/` builds decks with the CLI and imports them into Anki's own backend (the `anki` dev dependency, ADR 0019); the live us-ma test there is marked `integration`. No other test may touch the network.

## After major changes

Run these three checks before considering work done:

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ty check src/
```

## Coding conventions

- **Use `pathlib.Path` for all filesystem operations** — never `os.path`, `os.getcwd()`, `os.makedirs()`, etc. `Path` covers everything and is already used throughout the codebase.
- **Update `README.md` whenever CLI flags change** — the options table and examples section must stay in sync with `cli.py`.

## Key constraints

- `avianki REGION` needs no API key, no ffmpeg and no extras: it downloads finished media from the catalog.
- `EBIRD_API_KEY` is only required for `--ebird`. Building species the catalog lacks needs the `avianki[catalog]` extra; their audio also needs `ffmpeg` on `PATH` and `avianki[verify]` (BirdNET, Python 3.11 to 3.13 only).
- Catalog media must carry an allowed licence and a credit; every answer side shows the credit. eBird-built decks are for personal use and must not be republished.
- HTML parsing in the dormant `sources/allaboutbirds/scrape.py` uses BeautifulSoup 4; it is unused by the pipeline.
