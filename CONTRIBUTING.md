# Contributing to avianki

## Setup

1. Install [uv](https://docs.astral.sh/uv/)
2. Clone and install dev dependencies:

   ```bash
   git clone https://github.com/Ian-Costa18/avianki.git
   cd avianki
   uv sync --group dev
   ```

3. Copy `.env.example` to `.env` and add your eBird API key (`EBIRD_API_KEY`) if you plan to test eBird region code input

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
uv run pytest --integration --cov=avianki --cov-report=html  # run all tests, including the integration test, and coverage with HTML report
uv run python scripts/gen_examples.py          # regenerate examples/ card screenshots and example-birds.json (needs network; media cached by integration test)
# If publishing to PyPi:
uv version --bump patch   # or minor / major
uv build
uv run dotenv run -- uv publish
```

The integration test runs the full pipeline against allaboutbirds.org and verifies the output deck; it is skipped by default. Pass `--integration` to opt in.

Use `--integration` only when you intentionally want a networked end-to-end run.

## Project structure

- `src/avianki/cli.py` — CLI entry point and full pipeline orchestration
- `src/avianki/allaboutbirds.py` — scraping allaboutbirds.org (species list, overview, sounds)
- `src/avianki/ebird.py` — eBird API calls (species list for a region)
- `src/avianki/media.py` — file download, caching, audio trimming
- `src/avianki/anki_model.py` — genanki models, card templates, and shared fields
- `src/avianki/card.css` — shared CSS for all card types

See [CLAUDE.md](CLAUDE.md) for a deeper walkthrough of the data flow and key constraints.

## Extending cards and scraped data

Most feature work falls into one of these two paths.

### 1) Edit Anki cards (layout, templates, fields)

Each card type is its own `genanki.Model` in `src/avianki/anki_model.py` with a single template. All models share the same `FIELDS` list and CSS from `src/avianki/card.css`.

**To add a new card type:**

- Define a new `genanki.Model` in `anki_model.py` with a unique seed string (e.g. `_stable_id("BirdDeck_SongModel_v1")`).
- In `cli.py`, add a `deck.add_note(...)` call for the new model alongside the existing photo/desc notes.
- Add tests in `tests/test_anki_model.py` for the new model's template name.

**Fields:**

- Keep field order stable — Anki maps fields by position, not name. Always append new fields; never reorder or remove existing ones.
- If you add a field, update both `FIELDS` in `anki_model.py` and the `note_fields` list in `cli.py` in the same PR.

**Styles:**

- Edit `src/avianki/card.css` for layout changes. All models share it at build time.

**Model IDs:**

- Each model's ID is derived from its seed string via `_stable_id()`. Never change a seed string for a published model — it would orphan all existing cards in users' Anki collections.

### 2) Scrape additional fields from allaboutbirds.org

- Add extraction logic in `src/avianki/allaboutbirds.py` using BeautifulSoup selectors.
- Prefer selectors against structured HTML; avoid whole-page regex parsing.
- Thread the new data through `src/avianki/cli.py` so it reaches:
  - note fields (if shown on cards)
  - `birds.json` output
- Add or update fixture-based parser tests in `tests/test_allaboutbirds.py` and related fixtures in `tests/fixtures/`.
- If output JSON shape changes, update `examples/example-birds.json` and any tests that assert JSON structure.

For either path, run the quick verification checklist before opening a PR.

## Scraping fragility

HTML parsing uses BeautifulSoup 4 with CSS selectors against allaboutbirds.org page structure; small regex expressions are used only on individual attribute values. If scraping breaks, check whether the site's HTML has changed by comparing against the selectors in `allaboutbirds.py`.

## Versioning

This project follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

| Bump | When |
| ---- | ---- |
| `MAJOR` | Breaking changes — anything that orphans existing Anki cards or requires a fresh import: changing a model seed string, reordering or removing fields, renaming a deck seed, changing note GUIDs |
| `MINOR` | New features that are backward-compatible: new card types, new scraped fields (appended), new CLI flags |
| `PATCH` | Bug fixes, CSS tweaks, scraping fixes, documentation |

## Publishing to PyPI

Add your PyPI token to `.env` as `UV_PUBLISH_TOKEN`, then:

```bash
uv version --bump patch   # or minor / major
uv build
uv run dotenv run -- uv publish
```

`dotenv run --` injects `UV_PUBLISH_TOKEN` from `.env` into the environment so `uv publish` can authenticate without exposing the token in shell history.

## Submitting changes

- Run `uv run pytest`, `uv run ruff check src/ tests/`, and `uv run ty check src/` before opening a PR
- Keep PRs focused — one feature or fix per PR
- Open an issue first for significant changes

## Notes for CLI changes

- If CLI flags or defaults change, update `README.md` in the same PR (options table and examples).
- Prefer `pathlib.Path` for filesystem code; avoid introducing `os.path` paths in new code.
