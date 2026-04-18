# Merlin Anki

Builds Anki flashcard decks for learning to identify birds by sight and sound. Cards are sourced from [allaboutbirds.org](https://www.allaboutbirds.org) and include photos, call/song audio, and species descriptions.

Each species generates two card types:

- **Photo → Name** — given two photos and audio, identify the bird
- **Description → Name** — given audio and a written description, identify the bird

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** — for dependency management
- **[ffmpeg](https://ffmpeg.org/)** — for trimming audio clips

Install ffmpeg:

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg
```

## Installation

```bash
git clone https://github.com/yourname/merlin-anki.git
cd merlin-anki
uv sync
```

## Configuration

Copy `.env.example` to `.env` and fill in your key:

```env
EBIRD_API_KEY=your_key_here
```

An eBird API key is only required if using an eBird region code as the location. Get one free at [ebird.org/api/keygen](https://ebird.org/api/keygen).

## Usage

```bash
uv run python build_bird_deck.py LOCATION [--limit N] [--clear-cache]
```

### Location formats

**allaboutbirds.org browse URL** (recommended — species sorted by local frequency):

1. Go to [allaboutbirds.org/guide/browse](https://www.allaboutbirds.org/guide/browse)
2. Under **Birds Near Me**, enter your city, ZIP code, or state/province
3. Set the time of year — **Year-round** is recommended for a complete deck
4. Click **Browse**, then copy the URL from your browser's address bar

```bash
uv run python build_bird_deck.py "https://www.allaboutbirds.org/guide/browse/filter/loc/ChIJGzE9DS1l44kRoOhiASS_fHg/date/all/behavior/all/size/all/colors/all/sort/score/view/list-view"
```

**Google Place ID** (shorthand for the above):

```bash
uv run python build_bird_deck.py ChIJGzE9DS1l44kRoOhiASS_fHg
```

Find a Place ID at [developers.google.com/maps/documentation/javascript/examples/places-placeid-finder](https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder).

**eBird region code** (species in taxonomic order, requires API key):

```bash
uv run python build_bird_deck.py US-MA
uv run python build_bird_deck.py US-MA-017   # county level
```

### Options

| Flag            | Description                                      |
| --------------- | ------------------------------------------------ |
| `--limit N`     | Cap the number of species (useful for testing)   |
| `--clear-cache` | Delete previously downloaded media before running |

### Examples

```bash
# Build a deck for your area (recommended approach)
uv run python build_bird_deck.py "https://www.allaboutbirds.org/guide/browse/..." --limit 50

# Re-download all media from scratch
uv run python build_bird_deck.py US-MA --clear-cache

# Quick test with 5 species
uv run python build_bird_deck.py US-MA --limit 5
```

## Output

An `.apkg` file is written to the current directory (e.g. `Birds_US_MA.apkg`). Import it into Anki via **File → Import**.

Downloaded images and audio are cached in `media/` so re-runs skip already-fetched files.

## Notes

- Audio clips are trimmed to 10 seconds via ffmpeg to keep file sizes small.
- allaboutbirds.org browse URLs sort species by likelihood score for your location, which gives much better study order than eBird's taxonomic ordering.
