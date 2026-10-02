# AviAnki

[![PyPI](https://img.shields.io/pypi/v/avianki)](https://pypi.org/project/avianki/)
[![Python](https://img.shields.io/pypi/pyversions/avianki)](https://pypi.org/project/avianki/)
[![License](https://img.shields.io/github/license/Ian-Costa18/avianki)](https://github.com/Ian-Costa18/AviAnki/blob/main/LICENSE)
[![Ruff](https://img.shields.io/badge/linter-ruff-orange)](https://github.com/astral-sh/ruff)

*Build Flashcards with Birds Near You*

Pick a region and AviAnki builds an Anki deck for learning its birds by photo and by sound, with the most common species first. The photos and recordings come from a ready-made catalog that is rebuilt every month from freely licensed sources.

**[Make a deck on the website →](https://ian-costa18.github.io/AviAnki/)** Nothing to install.

## The website

<a href="https://ian-costa18.github.io/AviAnki/"><img src="https://raw.githubusercontent.com/Ian-Costa18/AviAnki/main/docs/images/website.png" alt="The AviAnki website: pick your state or province, then press Build my deck" width="640"></a>

Open **[ian-costa18.github.io/AviAnki/](https://ian-costa18.github.io/AviAnki/)**, pick your state or province and press **Build my deck**. The deck is built in your browser and saved as an `.apkg` file; the page then walks you through opening it in Anki on an iPhone, an Android phone or a computer.

- **Customize your cards** before you build: pick a theme, put the name on the photo, or make a theme of your own, with a live preview of the question and answer in light and dark mode.
- **More options** chooses the card types, the 100 most common birds or everything up to 400, a month of the year and a subdeck, like the command line's flags.
- The website covers the US and Canada. For anywhere else, use the [command line](#command-line) with `--ebird`.

## The cards

<img src="https://raw.githubusercontent.com/Ian-Costa18/AviAnki/main/docs/images/themes.gif" alt="A Northern Cardinal card in each of the ten built-in themes: the question, the answer, and the answer in night mode" width="960">

Every deck is built from three kinds of card; you choose which on the website under **More options**, or with `--cards`.

| Card type     | `--cards` value | Front                       |
| ------------- | --------------- | --------------------------- |
| Photo         | `photo`         | a photo of the bird         |
| Audio         | `audio`         | a recording of the bird     |
| Photo + audio | `photo-audio`   | the photo and the recording |

Every back is the same: the name and scientific name, the photo, the recording, and the credit for each.

The default is `photo,audio`. A species with no photo (or no recording) simply gets no photo (or audio) card, and the run says so: the summary adds a line such as "3 of the 100 birds have no recording, so they have photo cards only." for each kind that some species lack. Fronts never show the bird's name. Every answer credits the author and licence of each asset on the card.

The slideshow above cycles through the ten built-in [themes](#themes). **Name on the photo** (`--name-on-photo`) lays the name over the bottom of the photo instead, in any theme:

<img src="https://raw.githubusercontent.com/Ian-Costa18/AviAnki/main/docs/images/name-on-photo.png" alt="The default theme with the name on the photo: the question, the answer, and the answer in night mode" width="720">

## Command line

The command line builds the same decks as the website, and it also works for any [eBird region](#any-ebird-region), not just the US and Canada.

### Quick start

```bash
uvx avianki us-ma
```

An `.apkg` file (`AviAnki-us-ma.apkg`) is written to the current directory. Open it in Anki by double-clicking it or with **File > Import**.

You need [uv](https://docs.astral.sh/uv/). Without it, `pip install avianki` and then `avianki us-ma` does the same thing. Building from the catalog needs no API key and no ffmpeg.

`REGION` is a catalog region: its slug (`us-ma`, `ca-qc`) or its display name (`Massachusetts`). If the name is not in the catalog, the error lists the closest matches.

### Options

| Flag                       | Short | Description                                                                                         |
| -------------------------- | ----- | --------------------------------------------------------------------------------------------------- |
| `REGION`                   |       | Catalog region: slug (`us-ma`) or display name (`Massachusetts`). Required unless `--ebird` is given |
| `--tier TIER`              |       | `standard`: the 100 most common species (default). `everything`: the region's 400 most common (upper or lower case both work) |
| `--cards TYPES`            |       | Comma-separated card types: `photo`, `audio`, `photo-audio` (default: `photo,audio`)                  |
| `--month 1-12`             |       | Only species likely to be seen in this month (default: all year)                                     |
| `--subdeck`                |       | Put new notes in a subdeck named after the region (`AviAnki::<Region>`); see the note below           |
| `--theme NAME`             |       | How the cards look: `default`, `serif`, `field-guide`, `nord`, `slate`, `forest`, `plate`, `minimal`, `midnight` or `high-contrast`; see [Themes](#themes) |
| `--theme-file FILE`        |       | A custom theme in TOML, such as the website's **Copy theme** button gives; cannot be combined with `--theme` |
| `--name-on-photo`          |       | On the answer, put the name over the bottom of the photo instead of below it; works with every theme |
| `--ebird CODE`             |       | Build from any eBird region code instead of the catalog; see [Any eBird region](#any-ebird-region)   |
| `--output FILE`            | `-o`  | Where to write the deck (default: `AviAnki-<region>.apkg`, or `AviAnki-<CODE>.apkg` with `--ebird`); `~` works, a missing folder is created, and an existing file is replaced |
| `--catalog-url URL_OR_DIR` |       | Where to read the catalog: a URL or a local directory (default: the published catalog)               |
| `--cache-dir DIR`          |       | Where downloaded catalog files are kept (default: your per-user cache directory); `~` works          |
| `--deck-name NAME`         |       | The deck's name (default: `AviAnki`); it cannot be empty, and `::` makes a subdeck; see the warning below |
| `--verbose`                | `-v`  | Show debug output and tracebacks                                                                     |
| `--quiet`                  | `-q`  | Show only warnings and errors; also hides the progress bar                                           |
| `--version`                |       | Print the version and exit                                                                           |

`-v` and `-q` cannot be combined. The exit status is 0 when a deck was written, 1 for a network or catalog problem or when there was nothing to write, 2 for a usage error (including an output path that cannot be written, which is checked before anything is downloaded), and 130 when you cancel with Ctrl-C. The progress bar is only drawn in a terminal, so redirected output stays clean.

Changing `--deck-name` puts the notes into a different deck in Anki, so a later import will not update the notes you already have. Leave it alone unless you want a separate deck.

`--subdeck` only affects birds that are not in your collection yet. Anki leaves a bird you already have in the deck it is in, so importing with `--subdeck` into a collection that already holds those birds moves nothing. To reorganise existing cards, move them in Anki's card browser (select them, then Change Deck).

#### Examples

```bash
# The 100 most common birds of Massachusetts, photo and audio cards
uvx avianki us-ma

# Every Massachusetts species, with all three card types
uvx avianki "Massachusetts" --tier everything --cards photo,audio,photo-audio

# What Arizona birders see in May, in their own subdeck
uvx avianki us-az --month 5 --subdeck

# Photo cards only, in a chosen file
uvx avianki ca-qc --cards photo -o ~/Desktop/quebec.apkg

# Nord colours, with the name over the photo
uvx avianki us-ma --theme nord --name-on-photo

# Your own colours, from a theme file
uvx avianki us-ma --theme-file my-theme.toml

# A deck for a county, straight from eBird (needs EBIRD_API_KEY; for personal use only)
uvx --with "avianki[catalog]" avianki --ebird US-MA-017
```

## Themes

Ten looks are built in: `default`, `serif`, `field-guide`, `nord`, `slate`, `forest`, `plate`, `minimal`, `midnight` and `high-contrast`. All of them use your phone's own fonts, follow Anki's night mode, keep the photo in the same place on both sides and always show the credits. `--name-on-photo` changes the layout instead: the name sits on a dark gradient over the bottom of the photo, and the recording and credits stay below. The website shows a live preview of both under **Customize your cards**, before you build.

**Anki keeps one look for the whole collection.** Styling belongs to the note type, so importing a deck with another `--theme` restyles every AviAnki card you already have, and replaces any styling you edited in Anki yourself. Your review history is kept.

### A theme of your own

On the website, pick **Custom…** under **Customize your cards**, set the colours (each for day and night) and the type, and press **Copy theme**. Save the text in a file and build with it:

```bash
uvx avianki us-ma --theme-file my-theme.toml
```

A theme file is TOML. Every key is optional; a missing one keeps the default's value:

```toml
font = "rounded"        # sans, serif, rounded, mono or humanist
name_style = "caps"     # normal or caps
name_weight = "regular" # regular or bold
corners = "round"       # square, slight or round
rule = "side"           # none, or side for an accent rule beside the names

[light]
background = "#fff7e0"
text = "#3b2f00"
secondary = "#6a5a1a"
name = "#c2410c"
accent = "#e11d48"
credits = "#6a5a1a"

[night]
background = "#2a2208"
text = "#fff3c4"
secondary = "#e0cf8a"
name = "#fdba74"
accent = "#fb7185"
credits = "#e0cf8a"
```

Colours are six-digit hex (`#rrggbb`), and the other values come from the lists shown. A bad value stops the run with exit status 2 before anything is downloaded. A custom theme sets colours and type only, so it doesn't include the extra touches some built-ins have, such as `nord`'s credit box. Nothing checks the contrast of your colours: use the website's preview.

## Updating a deck

Decks are built to be re-imported. Every note has a fixed identity, so importing a newer build of the same region updates the notes you already have and keeps your review progress. Going from `standard` to `everything` adds only the extra species. Keep the default `--deck-name` for this to work.

## Any eBird region

The catalog covers the regions listed in it. For anything else, give `--ebird` an eBird region code (`US-MA`, `US-MA-017`, `CA-QC`, `MX-ROO`):

```bash
EBIRD_API_KEY=your_key uvx --with "avianki[catalog]" avianki --ebird US-MA-017
```

- Get a free key at [ebird.org/api/keygen](https://ebird.org/api/keygen) and put it in the environment or in a `.env` file (see [`.env.example`](https://github.com/Ian-Costa18/AviAnki/blob/main/.env.example)). Only `--ebird` needs it.
- Species that are in the catalog reuse its photos and recordings. Species that are not are built on the spot, which needs the `avianki[catalog]` extra. Audio for those also needs [ffmpeg](https://ffmpeg.org/) on your `PATH` and the `avianki[verify]` extra (BirdNET, Python 3.11 to 3.13). Without them the run degrades to photos and says so.
- The species come in eBird's order, so `standard` is the first 100 that eBird returns, and `everything` is every species eBird lists for the region.
- **The deck is for personal use only.** Every `--ebird` run prints: "Built from eBird data for personal use. eBird's terms don't allow redistributing this deck." The catalog decks, by contrast, contain only openly licensed media and species lists.

## Credits and licences

Every photo and recording in the catalog decks is openly licensed, and the answer side of each card names the author and the licence. The catalog itself publishes a credits page listing every asset. Media comes from Wikipedia and Wikimedia Commons, with iNaturalist as a fallback; species lists are derived from eBird occurrence data published through GBIF.

## Thanks to Cornell Lab of Ornithology

The species lists behind AviAnki's regions, and the eBird API used by `--ebird`, come from [eBird](https://ebird.org), the citizen-science project of the [Cornell Lab of Ornithology](https://www.birds.cornell.edu). Their work makes tools like this possible.

**Get involved** — Cornell Lab runs some of the world's largest citizen science programs. You can contribute bird sightings through eBird, join community science projects like [Project FeederWatch](https://feederwatch.org) and [NestWatch](https://nestwatch.org), or participate in the annual [Christmas Bird Count](https://www.audubon.org/conservation/christmas-bird-count). Every observation helps researchers track bird populations and protect habitat.

**Donate** — Consider supporting the Cornell Lab directly: [give.birds.cornell.edu](https://give.birds.cornell.edu/page/87895/donate/1).

If you find AviAnki useful, consider supporting its development at [buymeacoffee.com/IanCosta](https://buymeacoffee.com/IanCosta).

## Contributing

See [CONTRIBUTING.md](https://github.com/Ian-Costa18/AviAnki/blob/main/CONTRIBUTING.md).
