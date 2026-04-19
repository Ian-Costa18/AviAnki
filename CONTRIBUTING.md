# Contributing to avianki

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and [ffmpeg](https://ffmpeg.org/)
2. Clone and install dev dependencies:

   ```bash
   git clone https://github.com/Ian-Costa18/avianki.git
   cd avianki
   uv sync --group dev
   ```

3. Copy `.env.example` to `.env` and add your eBird API key (only needed for eBird region code input)

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

## Project structure

- `src/avianki/cli.py` — CLI entry point and full pipeline orchestration
- `src/avianki/allaboutbirds.py` — scraping allaboutbirds.org (species list, overview, sounds)
- `src/avianki/ebird.py` — eBird API calls (species list for a region)
- `src/avianki/media.py` — file download, caching, ffmpeg audio trimming
- `src/avianki/anki_model.py` — genanki model, card templates, and CSS

See [CLAUDE.md](CLAUDE.md) for a deeper walkthrough of the data flow and key constraints.

## Adding a new location input format

1. Add detection logic in `cli.main()` alongside the existing eBird/AAB checks
2. Produce a `slugs: list[str]` of allaboutbirds.org species slugs and a `deck_seed: str` (used to generate a stable deck ID)
3. Optionally populate `names: dict` mapping slug → `{comName, sciName}` to skip per-slug overview fetches

## Scraping fragility

HTML parsing uses BeautifulSoup 4 with CSS selectors against allaboutbirds.org page structure; small regex expressions are used only on individual attribute values. If scraping breaks, check whether the site's HTML has changed by comparing against the selectors in `allaboutbirds.py`.

## Publishing to PyPI

Add your PyPI token to `.env` as `UV_PUBLISH_TOKEN`, then:

```bash
uv version --bump patch   # or minor / major
uv build
uv run dotenv run -- uv publish
```

`dotenv run --` injects `UV_PUBLISH_TOKEN` from `.env` into the environment so `uv publish` can authenticate without exposing the token in shell history.

## Submitting changes

- Run `uv run pytest` and `uv run ruff check src/ tests/` before opening a PR
- Keep PRs focused — one feature or fix per PR
- Open an issue first for significant changes
