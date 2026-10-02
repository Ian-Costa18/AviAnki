# AviAnki

[![PyPI](https://img.shields.io/pypi/v/avianki)](https://pypi.org/project/avianki/)
[![Python](https://img.shields.io/pypi/pyversions/avianki)](https://pypi.org/project/avianki/)
[![License](https://img.shields.io/github/license/Ian-Costa18/AviAnki)](https://github.com/Ian-Costa18/AviAnki/blob/main/LICENSE)
[![Ruff](https://img.shields.io/badge/linter-ruff-orange)](https://github.com/astral-sh/ruff)

Anki flashcard decks for the birds of your state or province, by sight and by sound.

[**Build a deck**](https://ian-costa18.github.io/AviAnki/) &middot; [**Command line**](#command-line) &middot; [**Themes**](#themes) &middot; [**Changelog**](https://github.com/Ian-Costa18/AviAnki/blob/main/CHANGELOG.md) &middot; [**Contributing**](https://github.com/Ian-Costa18/AviAnki/blob/main/CONTRIBUTING.md)

<p align="center">
  <img src="https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/cards.gif" alt="One American Robin asked three ways: a photo, a recording, then both, each flipping to an answer with the bird's name, scientific name, recording and credits" width="424">
  <br><i>One bird, three kinds of card, question then answer.</i>
</p>

Pick where you go birding and AviAnki builds an [Anki](https://apps.ankiweb.net/) deck for its birds, most common species first: a photo or a recording on the front, the name on the answer. The media comes from a catalog rebuilt every month from freely licensed photos and recordings, so a build is a download. There is no account to make and no API key to get.

- The 100 most common species of a region, or every species the catalog holds for it (up to 400).
- Photo cards, audio cards, or one card with both.
- <!-- gen:theme-count -->Ten<!-- /gen:theme-count --> themes built in, or your own colours and type from a TOML file.
- Every photo and recording openly licensed, with its author and licence on the answer.
- Re-import a later build of the same region and your review progress is kept.
- Any eBird region, down to a single county, from the command line.

## Quick start

Open **[ian-costa18.github.io/AviAnki](https://ian-costa18.github.io/AviAnki/)**, choose your state or province, and press **Build my deck**. The deck is assembled in the browser: your choices are never sent to a server. The page carries the steps for opening the deck in Anki on an iPhone, an Android phone or a computer, and says where to get Anki.

The website covers the US and Canada, and a build takes about a minute. For anywhere else, or to script it, use the [command line](#command-line).

## Cards

Every deck is built from three kinds of card; you choose which with `--cards`, or with the tick boxes on the website.

| Card type     | `--cards` value | Front                       |
| ------------- | --------------- | --------------------------- |
| Photo         | `photo`         | a photo of the bird         |
| Audio         | `audio`         | a recording of the bird     |
| Photo + audio | `photo-audio`   | the photo and the recording |

Every back is the same: the name and scientific name, the photo, the recording, and the credit for each.

The default is `photo,audio`. A species with no photo (or no recording) gets no photo (or audio) card, and the run says so: the summary adds a line such as "3 of the 100 birds have no recording, so they have photo cards only." for each kind that some species lack. Fronts never show the bird's name. Every answer credits the author and licence of each asset on the card.

<details>
<summary><b>See each card type, front and answer</b></summary>

<!-- gen:card-shots -->
|               | Front                           | Answer                          |
| ------------- | ------------------------------- | ------------------------------- |
| Photo | ![Photo card, front](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/card-photo-front.png) | ![Photo card, answer](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/card-photo-back.png) |
| Audio | ![Audio card, front](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/card-audio-front.png) | ![Audio card, answer](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/card-audio-back.png) |
| Photo + Audio | ![Photo + Audio card, front](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/card-photo-audio-front.png) | ![Photo + Audio card, answer](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/card-photo-audio-back.png) |
<!-- /gen:card-shots -->

Rendered from the shipped templates and CSS by `scripts/gen_card_shots.py`, so they cannot drift from what Anki draws.

</details>

## Themes

<!-- gen:theme-count -->Ten<!-- /gen:theme-count --> themes ship with the deck. Each uses the system font of whatever you review on, follows Anki's night mode, keeps the photo in the same place on both sides, and shows the credits on every answer.

<p align="center">
  <img src="https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/themes.gif" alt="The built-in themes in turn, each shown in day mode beside night mode" width="744">
</p>

<details>
<summary><b>The <!-- gen:theme-count-lower -->ten<!-- /gen:theme-count-lower --> themes, one by one</b></summary>

Each shot is the same answer card in day mode (left) and night mode (right).

<!-- gen:theme-gallery -->
| Theme | Day and night |
| --- | --- |
| **`default`** — Photo first, the phone's own font, a black name | ![The default theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-default.png) |
| **`serif`** — A green serif name over the usual layout | ![The serif theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-serif.png) |
| **`field-guide`** — Warm paper, the name in spaced small capitals and an accent rule beside the names | ![The field-guide theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-field-guide.png) |
| **`nord`** — The Nord palette: cool Snow Storm paper by day, Polar Night by night, Frost blue accents | ![The nord theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-nord.png) |
| **`slate`** — Cool blue-grey with square corners and the credits in a thin box | ![The slate theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-slate.png) |
| **`forest`** — Sage green with round corners and the names on a soft green panel | ![The forest theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-forest.png) |
| **`plate`** — A vintage plate print: sepia paper, an italic serif name, centred between double rules | ![The plate theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-plate.png) |
| **`minimal`** — Everything centred on plain paper with a light name and lots of air | ![The minimal theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-minimal.png) |
| **`midnight`** — Always dark, by day and by night, with a soft blue accent | ![The midnight theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-midnight.png) |
| **`high-contrast`** — Larger type, pure black on white (white on black at night), strong outlines | ![The high-contrast theme](https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples/theme-high-contrast.png) |
<!-- /gen:theme-gallery -->

</details>

`--name-on-photo` changes the layout rather than the colours: the name sits on a dark gradient over the bottom of the photo, with the recording and credits below. The website previews both under **Customize your cards**, before you build.

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

## Command line

The command line builds the same decks from the same catalog, and adds what the website leaves out: scripting, `--theme-file`, and any eBird region.

```bash
uvx avianki us-ma
```

That writes `AviAnki-us-ma.apkg` to the current directory; open it in Anki by double-clicking it or with **File > Import**. You need [uv](https://docs.astral.sh/uv/); without it, `pip install avianki` and then `avianki us-ma` does the same thing. It needs Python 3.10 or newer and runs on macOS, Linux and Windows; the deck itself works in Anki Desktop, AnkiMobile and AnkiDroid.

`REGION` is a catalog region: its slug (`us-ma`, `ca-qc`) or its display name (`Massachusetts`). If the name is not in the catalog, the error lists the closest matches.

### Options

| Flag                       | Short | Description                                                                                         |
| -------------------------- | ----- | --------------------------------------------------------------------------------------------------- |
| `REGION`                   |       | Catalog region: slug (`us-ma`) or display name (`Massachusetts`). Required unless `--ebird` is given |
| `--tier TIER`              |       | `standard`: the 100 most common species (default). `everything`: every species the catalog holds for the region (up to 400) |
| `--cards TYPES`            |       | Comma-separated card types: `photo`, `audio`, `photo-audio` (default: `photo,audio`)                  |
| `--month 1-12`             |       | Only species likely to be seen in this month (default: all year)                                     |
| `--subdeck`                |       | Put new notes in a subdeck named after the region (`AviAnki::<Region>`); see the note below           |
| `--theme NAME`             |       | How the cards look; ten built-in themes — see [Themes](#themes) |
| `--theme-file FILE`        |       | A custom theme in TOML, such as the website's **Copy theme** button gives; cannot be combined with `--theme` |
| `--name-on-photo`          |       | On the answer, put the name over the bottom of the photo instead of below it; works with every theme |
| `--ebird CODE`             |       | Build from any eBird region code instead of the catalog; see [Any eBird region](#any-ebird-region)   |
| `--output FILE`            | `-o`  | Where to write the deck (default: `AviAnki-<region>.apkg`, or `AviAnki-<CODE>.apkg` with `--ebird`); `~` works and a missing folder is created |
| `--catalog-url URL_OR_DIR` |       | Where to read the catalog: a URL or a local directory (default: the published catalog)               |
| `--cache-dir DIR`          |       | Where downloaded catalog files are kept (default: your per-user cache directory); `~` works          |
| `--deck-name NAME`         |       | The deck's name (default: `AviAnki`); it cannot be empty, and `::` makes a subdeck; see the warning below |
| `--verbose`                | `-v`  | Show debug output and tracebacks                                                                     |
| `--quiet`                  | `-q`  | Show only warnings and errors; also hides the progress bar                                           |
| `--version`                |       | Print the version and exit                                                                           |

`-v` and `-q` cannot be combined. The exit status is 0 when a deck was written, 1 for a network or catalog problem or when there was nothing to write, 2 for a usage error (including an output path that cannot be written, which is checked before anything is downloaded), and 130 when you cancel with Ctrl-C. The progress bar is only drawn in a terminal, so redirected output stays clean.

Changing `--deck-name` puts the notes into a different deck in Anki, so a later import will not update the notes you already have. Leave it alone unless you want a separate deck.

`--subdeck` only affects birds that are not in your collection yet. Anki leaves a bird you already have in the deck it is in, so importing with `--subdeck` into a collection that already holds those birds moves nothing. To reorganise existing cards, move them in Anki's card browser (select them, then Change Deck).

### Examples

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

## Updating a deck

Every note has a fixed identity, so importing a newer build of the same region updates the notes you already have and keeps your review progress. Going from `standard` to `everything` adds only the extra species. Keep the default `--deck-name` for this to work.

## Any eBird region

The catalog covers the regions listed in it. For anything else, give `--ebird` an eBird region code (`US-MA`, `US-MA-017`, `CA-QC`, `MX-ROO`):

```bash
EBIRD_API_KEY=your_key uvx --with "avianki[catalog]" avianki --ebird US-MA-017
```

- Get a free key at [ebird.org/api/keygen](https://ebird.org/api/keygen) and put it in the environment or in a `.env` file (see [`.env.example`](https://github.com/Ian-Costa18/AviAnki/blob/main/.env.example)). Only `--ebird` needs it.
- Species that are in the catalog reuse its photos and recordings. Species that are not are built on the spot, which needs the `avianki[catalog]` extra. Audio for those also needs [ffmpeg](https://ffmpeg.org/) on your `PATH` and the `avianki[verify]` extra (BirdNET, Python 3.11 to 3.13). Without them the run degrades to photos and says so.
- The species come in eBird's order, so `standard` is the first 100 that eBird returns, and `everything` is every species eBird lists for the region.
- **The deck is for personal use only.** Every `--ebird` run prints: "Built from eBird data for personal use. eBird's terms don't allow redistributing this deck." The catalog decks, by contrast, contain only openly licensed media and species lists.

## How it works

A GitHub Actions workflow rebuilds the catalog every month: species lists per region from eBird occurrence data published through GBIF, then photos and recordings per species from Wikimedia Commons and iNaturalist under an exact licence allowlist, screened, resized, and checked with [BirdNET](https://birdnet.cornell.edu/) so a recording really is the bird it claims to be. The result is a static catalog on GitHub Pages, and both the website and the CLI read it; the deck itself is assembled on your own machine either way.

- [The specification](https://github.com/Ian-Costa18/AviAnki/blob/main/docs/web-app-spec.md) — what gets built, and how
- [Decision records](https://github.com/Ian-Costa18/AviAnki/tree/main/docs/adr) — why it is built that way
- [Credits for every asset](https://ian-costa18.github.io/AviAnki/catalog/credits.html) — the catalog's own credits page
- [Changelog](https://github.com/Ian-Costa18/AviAnki/blob/main/CHANGELOG.md)

## Credits and licences

Every photo and recording in the catalog decks is openly licensed, and the answer side of each card names the author and the licence. The catalog itself publishes a credits page listing every asset. Media comes from Wikipedia and Wikimedia Commons, with iNaturalist as a fallback; species lists are derived from eBird occurrence data published through GBIF.

## Thanks to Cornell Lab of Ornithology

The species lists behind AviAnki's regions, and the eBird API used by `--ebird`, come from [eBird](https://ebird.org), the citizen-science project of the [Cornell Lab of Ornithology](https://www.birds.cornell.edu). Their work makes tools like this possible.

**Get involved** — Cornell Lab runs some of the world's largest citizen science programs. You can contribute bird sightings through eBird, join community science projects like [Project FeederWatch](https://feederwatch.org) and [NestWatch](https://nestwatch.org), or participate in the annual [Christmas Bird Count](https://www.audubon.org/conservation/christmas-bird-count). Every observation helps researchers track bird populations and protect habitat.

**Donate** — Consider supporting the Cornell Lab directly: [give.birds.cornell.edu](https://give.birds.cornell.edu/page/87895/donate/1).

AviAnki is not affiliated with Anki, eBird or the Cornell Lab of Ornithology.

## Contributing

See [CONTRIBUTING.md](https://github.com/Ian-Costa18/AviAnki/blob/main/CONTRIBUTING.md).

If you find AviAnki useful, you can support its development at [buymeacoffee.com/IanCosta](https://buymeacoffee.com/IanCosta).

## Licence

AviAnki is MIT licensed. The photos and recordings in the catalog keep their own licences, named on every card and listed on the [credits page](https://ian-costa18.github.io/AviAnki/catalog/credits.html).
