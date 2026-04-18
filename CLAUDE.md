# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the CLI locally
uv run avianki LOCATION [OPTIONS]

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_allaboutbirds.py

# Run a single test by name
uv run pytest tests/test_allaboutbirds.py::test_name

# Run tests with coverage
uv run pytest --cov=avianki

# Lint
uv run ruff check src/ tests/

# Type check
uv run ty check src/
```

## Architecture

The app has a single pipeline: **resolve species list → scrape media per species → build Anki deck**.

`cli.py` owns the full pipeline and all orchestration logic. The other modules are pure helpers — they do no orchestration themselves.

**Data flow:**

1. **Species resolution** — `cli.main()` inspects the `location` argument:
   - eBird region code (e.g. `US-MA`) → `ebird.fetch_species()` returns `[{comName, sciName, speciesCode}]`, then converts to slugs via `allaboutbirds.species_slug()`
   - allaboutbirds.org URL or Google Place ID → `allaboutbirds.fetch_browse_species()` returns slugs directly in likelihood-score order

2. **Per-species scraping** — for each slug, `cli.main()` calls:
   - `allaboutbirds.fetch_overview(slug)` → `{desc, sciName, images: [url, ...]}`
   - `allaboutbirds.fetch_sounds(slug)` → `{calls: [url, ...], songs: [url, ...]}`
   - `allaboutbirds._get_images()` / `_get_audio()` → download via `media.download_file()`, trim audio via `media.trim_to_mp3()` (ffmpeg), cache to `media/`

3. **Deck assembly** — `genanki.Note` is built with fields `[BirdName, SciName, Image1, Image2, Call, Song, Description]` and added to a `genanki.Deck`. The model and card templates (two card types: Photo→Name and Description→Name) live entirely in `anki_model.py`.

**Media caching:** Files are written to `media/` with names like `bird_{safe_name}_img1.jpg`, `bird_{safe_name}_call.mp3`. `media.find_cached_image()` / `find_cached_audio()` check for any matching extension before re-downloading.

**Deck/model IDs:** Both are derived from `hashlib.md5` of a seed string so they remain stable across runs — critical for Anki to recognize the deck as the same one on re-import.

**Logging:** A single `logging.Logger("bird_deck")` is used across all modules. `cli.py` configures its handlers (stdout + file). Other modules just call `log = logging.getLogger("bird_deck")`.

## Key constraints

- All HTML parsing uses `re` — there is no BeautifulSoup dependency. Regex patterns are tightly coupled to allaboutbirds.org page structure and will break if the site changes.
- `ffmpeg` must be on `PATH` for audio trimming; `media.trim_to_mp3()` will return `False` if it isn't.
- `EBIRD_API_KEY` is only required for eBird region codes; allaboutbirds.org URLs and Place IDs work without it.
