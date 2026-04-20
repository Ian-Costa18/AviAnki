# AviAnki

[![PyPI](https://img.shields.io/pypi/v/avianki)](https://pypi.org/project/avianki/)
[![Python](https://img.shields.io/pypi/pyversions/avianki)](https://pypi.org/project/avianki/)
[![License](https://img.shields.io/github/license/Ian-Costa18/avianki)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Ian-Costa18/avianki)](https://github.com/Ian-Costa18/avianki/stargazers)
[![Ruff](https://img.shields.io/badge/linter-ruff-orange)](https://github.com/astral-sh/ruff)

*Build Flashcards with Birds Near You*

Drop in your location and AviAnki builds a custom Anki deck — sorted by the species most likely to appear near you — pulling photos, calls, songs, and descriptions from [allaboutbirds.org](https://www.allaboutbirds.org).

Each species gets two card types:

- **Photo → Name** — given two photos and audio, identify the bird
- **Description → Name** — given audio and a written description, identify the bird

## Card examples

**Photo → Name** — identify the bird from photos and audio:

![Photo → Name front](examples/american_robin_picture_name_front.png)

**Description → Name** — identify the bird from audio and a redacted description:

![Description → Name front](examples/american_robin_description_name_front.png)

**Answer** — reveals the name, scientific name, photos, audio, and full description:

![Answer](examples/american_robin_picture_name_back.png)

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — for running and installing
- **[ffmpeg](https://ffmpeg.org/)** — for trimming audio clips

Install ffmpeg:

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg
```

## Quick start

1. Go to [allaboutbirds.org/guide/browse](https://www.allaboutbirds.org/guide/browse)
2. Under **Birds Near Me**, enter your city, ZIP code, or state/province — set the time of year to **Year-round** for a complete deck
3. Click **Browse**, copy the URL from your browser's address bar, and run:

```bash
uvx avianki "https://www.allaboutbirds.org/guide/browse/filter/loc/ChIJGzE9DS1l44kRoOhiASS_fHg/..."
```

That's it. An `.apkg` file is written to the current directory — import it into Anki via **File → Import**.

Use `--limit N` to cap the number of species for a smaller file size:

```bash
uvx avianki "https://www.allaboutbirds.org/guide/browse/..." --limit 30
```

## Usage

**From PyPI (recommended):**

```bash
uvx avianki LOCATION [OPTIONS]
```

**From a local clone:**

```bash
git clone https://github.com/Ian-Costa18/avianki.git
cd avianki
uv run avianki LOCATION [OPTIONS]
```

### Location formats

**allaboutbirds.org browse URL** (recommended — species sorted by local frequency, no API key needed):

```bash
uvx avianki "https://www.allaboutbirds.org/guide/browse/filter/loc/ChIJGzE9DS1l44kRoOhiASS_fHg/date/all/behavior/all/size/all/colors/all/sort/score/view/list-view"
```

**Google Place ID** (shorthand for the above):

```bash
uvx avianki ChIJGzE9DS1l44kRoOhiASS_fHg
```

Find a Place ID at [developers.google.com/maps/documentation/javascript/examples/places-placeid-finder](https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder).

**eBird region code** (species in taxonomic order, requires an API key):

```bash
uvx avianki US-MA
uvx avianki US-MA-017   # county level
```

Get a free eBird API key at [ebird.org/api/keygen](https://ebird.org/api/keygen), then set it in a `.env` file:

```env
EBIRD_API_KEY=your_key_here
```

### Options

Every option can also be set as an environment variable — useful for scripting or keeping a persistent configuration in `.env`. CLI flags always take precedence over env vars.

| Flag               | Short | Env var              | Description                                                             |
| ------------------ | ----- | -------------------- | ----------------------------------------------------------------------- |
| `LOCATION`         |       | `AVIANKI_LOCATION`   | allaboutbirds.org URL, Google Place ID, or eBird region code            |
| `--limit N`        | `-n`  | `AVIANKI_LIMIT`      | Cap the number of species included in the deck                          |
| `--output FILE`    | `-o`  | `AVIANKI_OUTPUT`     | Output `.apkg` path (default: auto-generated from location)             |
| `--deck-name NAME` | `-d`  | `AVIANKI_DECK_NAME`  | Override the deck name shown in Anki                                    |
| `--no-audio`       | `-A`  | `AVIANKI_NO_AUDIO`   | Skip downloading call and song audio                                    |
| `--no-images`      | `-I`  | `AVIANKI_NO_IMAGES`  | Skip downloading photos                                                 |
| `--delay SECONDS`  | `-D`  | `AVIANKI_DELAY`      | Wait between requests in seconds (default: `0`)                         |
| `--work-dir DIR`   | `-w`  | `AVIANKI_WORK_DIR`   | Directory for cached media, logs, and JSON (default: `<tmp>/avianki/`)  |
| `--media-dir DIR`  | `-m`  | `AVIANKI_MEDIA_DIR`  | Override media subdirectory (default: `<work-dir>/media/`)              |
| `--json-file FILE` | `-j`  | `AVIANKI_JSON_FILE`  | Path for `birds.json` output (default: `<work-dir>/birds.json`)         |
| `--ephemeral`      | `-e`  | `AVIANKI_EPHEMERAL`  | Run without persisting anything — see [Ephemeral mode](#ephemeral-mode) |
| `--no-cache`       | `-X`  | `AVIANKI_NO_CACHE`   | Skip cache lookup; delete downloaded media after packaging              |
| `--log-file FILE`  | `-l`  | `AVIANKI_LOG_FILE`   | Log file path (default: `<work-dir>/avianki.log`)                       |
| `--verbose`        | `-v`  | `AVIANKI_VERBOSE`    | Show debug-level output in the console                                  |
| `--quiet`          | `-q`  | `AVIANKI_QUIET`      | Only show warnings and errors; also suppresses the progress bar         |

Boolean env vars (`AVIANKI_NO_AUDIO`, `AVIANKI_NO_IMAGES`, `AVIANKI_EPHEMERAL`, `AVIANKI_NO_CACHE`, `AVIANKI_VERBOSE`, `AVIANKI_QUIET`) are enabled by setting them to `1`, `true`, or `yes`. See `.env.example` for a ready-to-copy template.

### Examples

```bash
# Your local birds, capped to 50 species
uvx avianki "https://www.allaboutbirds.org/guide/browse/..." --limit 50
AVIANKI_LIMIT=50 uvx avianki "https://www.allaboutbirds.org/guide/browse/..."

# Custom output path and deck name
uvx avianki "https://www.allaboutbirds.org/guide/browse/..." --output ~/Desktop/MyBirds.apkg --deck-name "My Birds"

# Images only, no audio
uvx avianki "https://www.allaboutbirds.org/guide/browse/..." --no-audio

# Add a delay between requests to be gentler on the server
uvx avianki "https://www.allaboutbirds.org/guide/browse/..." --delay 1.5

# Fully configured via .env — run with no arguments
# (set AVIANKI_LOCATION and other options in .env)
uvx avianki
```

## Output

An `.apkg` file is written to the current directory by default (e.g. `Birds_ChIJGzE9DS1l44kRoOhiASS_fHg.apkg` or `Birds_US-MA.apkg`). Import it into Anki via **File → Import**.

Downloaded images and audio are cached in the system temp directory (`<tmp>/avianki/media/` by default, or the directory set by `--media-dir`) so re-runs skip already-fetched files. Re-running the same location only fetches new or missing media. The log is written to `<tmp>/avianki/avianki.log`.

A `birds.json` file is also written to `<work-dir>/birds.json` (override with `--json-file`) containing the scraped data for every species. Each entry has the common name, scientific name, description, and paths to the cached image and audio files relative to `<work-dir>`. Audio fields are `null` when no clip was found. See [examples/example-birds.json](examples/example-birds.json) for a sample.

```json
[
  {
    "name": "American Robin",
    "sci_name": "Turdus migratorius",
    "description": "The quintessential early bird...",
    "images": ["media/bird_American_Robin_img1.jpg", "media/bird_American_Robin_img2.jpg"],
    "call": "media/bird_American_Robin_call.mp3",
    "song": "media/bird_American_Robin_song.mp3"
  }
]
```

## Ephemeral mode

`--ephemeral` is for one-shot runs where you want no persistent files. Instead of writing to `<work-dir>` directly, all temporary files (media, log, `birds.json`) go into `<work-dir>/.ephemeral/`. That subdirectory is deleted after the `.apkg` is packaged, leaving the base work directory untouched. The cache is never read or written in this mode.

## Notes

- Audio clips are trimmed to 10 seconds via ffmpeg to keep file sizes small.
- allaboutbirds.org browse URLs sort species by likelihood score for your location, which gives much better study order than eBird's taxonomic ordering.

## Thanks to Cornell Lab of Ornithology

All bird data, photos, audio, and descriptions in AviAnki come from [All About Birds](https://www.allaboutbirds.org), a free resource built and maintained by the [Cornell Lab of Ornithology](https://www.birds.cornell.edu). Their work makes tools like this possible.

**Get involved** — Cornell Lab runs some of the world's largest citizen science programs. You can contribute bird sightings through [eBird](https://ebird.org), join community science projects like [Project FeederWatch](https://feederwatch.org) and [NestWatch](https://nestwatch.org), or participate in the annual [Christmas Bird Count](https://www.audubon.org/conservation/christmas-bird-count). Every observation helps researchers track bird populations and protect habitat. Learn more at [allaboutbirds.org/news/get-involved](https://www.allaboutbirds.org/news/get-involved/).

**Donate** — If you find All About Birds useful, consider supporting the Cornell Lab directly: [give.birds.cornell.edu](https://give.birds.cornell.edu/page/87895/donate/1).

## Future Development

- More card types, with options to choose which types the user wants, such as
  - Identification with only song, call, description, image, etc.
  - Identification with [ID info](https://www.allaboutbirds.org/guide/American_Robin/id) instead of description.
  - Identification with [Life History](https://www.allaboutbirds.org/guide/American_Robin/lifehistory).
  - Identification with [Range Map](https://www.allaboutbirds.org/guide/American_Robin/maps-range).
  - Identification with [Scientific Name, Order, and Family](https://www.allaboutbirds.org/guide/American_Robin/overview#Cool%20Facts:~:text=Turdus,Turdidae).
  - Identification with [Other Names](https://www.allaboutbirds.org/guide/American_Robin/overview#Cool%20Facts:~:text=Other%20Names).
- [Cool Facts](https://www.allaboutbirds.org/guide/American_Robin/overview#Cool%20Facts:~:text=An,old,-%2E), [ID info](https://www.allaboutbirds.org/guide/American_Robin/id), [Life History](https://www.allaboutbirds.org/guide/American_Robin/lifehistory), [Range Map](https://www.allaboutbirds.org/guide/American_Robin/maps-range), and other fields added to card in some way, without overloading the card.

If you find AviAnki useful, consider supporting its development at [buymeacoffee.com/IanCosta](https://buymeacoffee.com/IanCosta).
