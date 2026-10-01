# Changelog

## Unreleased

### Cards

- **A new look.** The photo stays where it is when you flip a card, so your eye doesn't have to find it again. Cards use your phone's own font, follow night mode, and the credits are smaller.
- **Importing the new deck restyles your existing AviAnki cards** and keeps your review history. If you edited the AviAnki note types' styling by hand, those edits are replaced.

## 1.0.1

Fixes found by trying 1.0 the way a first-time user would, on the website and the command line.

### Decks

- **A 100-bird deck has 100 birds.** A bird with no photo or recording for the card types you chose no longer takes one of the 100 places; the next most-seen bird does. Before, Standard decks for Texas, Florida, Louisiana, Mississippi and Hawaii had 99, and an audio-only deck could have far fewer.
- **More birds have photos and recordings.** Western Cattle Egret had none, and Eurasian Eagle-Owl, Black Francolin and Manx Shearwater had none from iNaturalist, because their names didn't match. They're matched now.

### Website

- **Reloading during a build no longer splits your next deck.** Leaving or reloading the page mid-build used to make the next build claim it had run out of memory and split into two files.
- **A file that changed during your build gets the right message** ("the bird catalog was updated while you were building"), instead of a connection error, and isn't retried pointlessly.
- **Part files carry the region**, such as `AviAnki-us-tx-part-1-of-3.apkg`, so two regions' parts don't collide in your Downloads.
- **Clearer text.** Progress says whether it's fetching photos, recordings or both, and counts read "1 bird", "1 card".
- **Smaller fixes.** Warnings disappear as soon as you fix them, a second tap on Build is ignored while one is running, links and buttons are easier to tap on a phone, and the page has an icon.

### Command line

- **Cached photos and recordings are checked again.** A file in the cache that was cut short or damaged is now downloaded afresh, with a warning, instead of going into your deck.
- **Your settings file is found where you run the command.** A `.env` file in the folder you run `avianki` from is now read, wherever the program is installed.
- **`~` works** in `-o` and `--cache-dir`.
- **A bad `-o` is caught first.** If the output path cannot be written, `avianki` says so and exits with status 2 before downloading anything. A missing folder is still created. When an existing file is overwritten, the summary says it was replaced.
- **`avianki-catalog` without its extra** now tells you to install `avianki[catalog]` and exits with status 2, instead of printing a traceback.
- **Non-English names no longer crash redirected output** on Windows, and Ctrl-C prints "Cancelled." and exits with status 130.
- **The progress bar stays out of logs and pipes.** It is only drawn in a terminal.
- **The summary names missing media.** Birds with no recording, or no photo, are counted on their own line, with the right singular or plural.
- **Clearer options.** `--tier everything` is the region's 400 most common species, and the help and README now say so. `--tier` accepts upper case. `--version` is new. An empty `--deck-name` is an error, and a name with `::` prints a warning that it makes a subdeck.
- **More ways to name a region.** `dc`, `D.C.` and `Washington DC` find the District of Columbia, and a bare state code such as `ma` finds `us-ma`. When a short code matches several regions, the message lists the slugs and no longer suggests `--ebird`.
- **Advice with errors.** Network failures, a photo or recording that vanished while you were building, and a cache folder that cannot be written each say what to try next.
- **Quieter logs.** The "wrote" line is no longer printed twice.
- **`--subdeck` is described honestly.** Only birds not yet in your collection go to the subdeck, because Anki keeps a bird you already have where it is. The help and README say how to move the rest.

### Package

- The licence is declared the current way (an SPDX expression plus the licence file), the build no longer warns, and both the wheel and the source archive include `LICENSE`.
- The source archive leaves out stray files such as `.apkg`, `.log` and `.env`.
- The links in the README on PyPI point to the project on GitHub, so they no longer break.

## 1.0.0 — 2026-09-30

AviAnki 1.0 builds decks from a ready-made catalog of freely licensed photos and recordings, instead of scraping allaboutbirds.org on your machine. There's also a website that builds the same deck in your browser: https://ian-costa18.github.io/AviAnki/

### If you used AviAnki 0.9 or earlier: your new deck starts fresh

1.0 identifies each card by the bird and the card type, not by the place you built it for. That's what lets you change region, tier or card types later without getting duplicate cards. It also means a 1.0 deck doesn't match the cards of a 0.9 deck, so importing it adds a new **AviAnki** deck next to your old one instead of updating it.

Your old deck and its review history aren't touched. Keep studying it, or delete it once you've moved to the new one. This is a one-time break. From 1.0 on, rebuilding or re-importing a deck keeps your progress.

### What's new

- **A website.** Pick your state or province, tap **Build my deck**, and open the file in Anki. It works on phones too. Nothing to install except Anki.
- **A catalog instead of scraping.**
  - Species lists come from the eBird Observation Dataset (via GBIF), ranked by how often each bird is seen in each US state and Canadian province.
  - Photos and recordings come from Wikipedia, Wikimedia Commons and iNaturalist, under open licences only.
  - Every recording is checked by BirdNET to make sure it's the right bird.
  - The catalog is rebuilt monthly.
- **Photo and audio cards.** "What bird is this?" shows a photo, and "Who's calling?" plays a recording. A photo + audio card is optional. Every answer shows the name, the photo, the recording, and a credit line for each.
- **Tiers and seasons.**
  - `--tier standard` (the default) gives the 100 most-seen birds. `--tier everything` gives up to 400.
  - `--month` keeps only the birds seen that month.
  - `--subdeck` puts the cards in a subdeck named after the region.
- **Anywhere in the world, for personal use.** `avianki --ebird CODE` builds from any eBird region using your own `EBIRD_API_KEY`. eBird's terms don't allow sharing those decks.
- **Credits.** Every photo and recording is credited on its card. The deck description credits the datasets.

### Removed

- allaboutbirds.org URLs and Google Place IDs as input. Use a region slug (`us-ma`), a name (`Massachusetts`), or `--ebird` with an eBird code.
- The Description → Name card type. It may return once descriptions can be shown without giving away the name.
- `call` and `song` as separate fields. There's now one recording per bird, because the sources don't reliably tell songs from calls.

### Requirements

- Python 3.10 or newer. `uvx avianki us-ma` needs nothing else.
- `--ebird` builds of species outside the catalog also need `avianki[catalog]` and ffmpeg. BirdNET checking of recordings needs `avianki[verify]` (Python 3.11 to 3.13).
