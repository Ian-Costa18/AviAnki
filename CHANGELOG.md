# Changelog

## 1.0.0

AviAnki 1.0 is the first stable release. It builds on 0.10 with card themes, clearer recordings and a friendlier website. From here on, an update keeps your review progress: see [Versioning](CONTRIBUTING.md#versioning) for the promise.

### If you used AviAnki 0.9 or earlier: your new deck starts fresh

Decks from 0.10 on identify each card by the bird and the card type, not by the place you built it for. A 1.0 deck doesn't match the cards of a 0.9 deck, so importing it adds a new **AviAnki** deck next to your old one instead of updating it. Your old deck and its review history aren't touched: keep studying it, or delete it once you've moved over. A deck built with 0.10 updates in place, and your progress is kept.

### Recordings: the bird you're asked about is the one you hear

- **Each recording is scored** for how much of the clip the bird is in, and for whether another bird is louder. Up to 10 recordings are tried per bird and the best one is kept, instead of the first that passes. See [ADR 0031](docs/adr/0031-audio-quality-selection.md).
- **Clips start on the bird.** The 10 seconds on the card are the stretch where the bird is clearest, not the first 10 seconds of the recording.
- **Five clips were replaced by ear** after a listening review.

### The website: friendlier wording and a study guide you can read first

- **How to study, before you build.** The steps for opening your deck are now on the first screen, under the form, and the line under **Build my deck** links to them. The Done screen shows the same guide.
- **Device tabs.** Pick **iPhone & iPad**, **Android** or **Computer**. The tab for your device is selected for you, and the tabs work with the keyboard and screen readers.
- **Two ways on iPhone and iPad.** Free: Anki on a computer, sync to AnkiWeb, then study at ankiweb.net in Safari. Paid: AnkiMobile (US$24.99, which helps fund Anki's development) straight on the phone. AnkiWeb can't open a deck file on its own, so the free way needs a computer once. See [ADR 0030](docs/adr/0030-friendly-copy-and-device-tabs.md).
- **Steps that match the apps.** Every button the steps name is the one the app shows: **Import** when Anki opens a deck file, **Add** in AnkiDroid, and **Yes** when Anki's first sync asks *"Replace it with local collection?"*.
- **Plainer, kinder wording** across the page: a line under the headline that says what you'll get, headings, hints, buttons and error messages. *Advanced* is now *More options*.
- **"20 new cards a day", not "20 new birds".** Anki's daily limit counts cards, and a bird can have more than one. The deck description says the same.

### Website

- **A deploy no longer mixes new and cached files.** The site's scripts, styles and data are served from a folder named for the deploy, so a page always loads the files that belong to it. Right after an update, returning visitors could see the new page with old files (for example only the Default theme) until a hard refresh. A page cached from before an update reloads itself once to recover.

### Card themes

- **Ten themes** for the cards: `default` (the current look), `serif`, `field-guide`, `nord`, `slate`, `forest`, `plate`, `minimal`, `midnight` and `high-contrast`. Pick one with `--theme NAME`, or on the website under **Customize your cards**. All use your phone's own fonts and follow night mode, and the credits are always on the answer.
- **Name on the photo.** `--name-on-photo` (or the website checkbox) puts the name over the bottom of the photo on the answer. It works with every theme.
- **Make your own.** On the website, choose **Custom…**, set the colours (day and night), font, name style, weight and corners, and watch the preview change. **Copy theme** gives a small TOML file that `--theme-file my-theme.toml` reads. The page address remembers your look, so you can bookmark or share it.
- **A live preview** on the website: a sample card, question and answer, light or dark, drawn with the real card templates before you build.
- **One look per Anki collection.** Anki keeps styling per note type, so importing a deck with another theme restyles the AviAnki cards you already have (and replaces styling you edited by hand). Your review history is kept, and the default look is unchanged if you pick no theme.

## 0.10.0

AviAnki 0.10 builds decks from a ready-made catalog of freely licensed photos and recordings, instead of scraping allaboutbirds.org on your machine. There's also a website that builds the same deck in your browser: https://ian-costa18.github.io/AviAnki/

### If you used AviAnki 0.9 or earlier: your new deck starts fresh

0.10 identifies each card by the bird and the card type, not by the place you built it for. That's what lets you change region, tier or card types later without getting duplicate cards. It also means a 0.10 deck doesn't match the cards of a 0.9 deck, so importing it adds a new **AviAnki** deck next to your old one instead of updating it.

Your old deck and its review history aren't touched. Keep studying it, or delete it once you've moved to the new one. This is a one-time break. From 0.10 on, rebuilding or re-importing a deck keeps your progress.

### What's new

- **A website.** Pick your state or province, tap **Build my deck**, and open the file in Anki. It works on phones too. Nothing to install except Anki.
  - A build with more birds than fits in memory is split into numbered parts named after the region, such as `AviAnki-us-tx-part-1-of-3.apkg`.
  - Reloading or leaving the page mid-build doesn't affect the next one. If the catalog is updated while you build, you're told so.
  - Progress says whether it's fetching photos, recordings or both.
- **A catalog instead of scraping.**
  - Species lists come from the eBird Observation Dataset (via GBIF), ranked by how often each bird is seen in each US state and Canadian province.
  - Photos and recordings come from Wikipedia, Wikimedia Commons and iNaturalist, under open licences only.
  - Every recording is checked by BirdNET to make sure it's the right bird.
  - The catalog is rebuilt monthly.
- **Photo and audio cards.** "What bird is this?" shows a photo, and "Who's calling?" plays a recording. A photo + audio card is optional. Every answer shows the name, the photo, the recording, and a credit line for each.
- **A new look.** The photo stays put when you flip a card, so your eye doesn't have to find it again. Every back has the same order: photo, name, recording. Recording cards have a compact play button with the question beside it. Cards use your phone's own font, follow night mode, and the credits are smaller. Importing a deck restyles your existing AviAnki cards and keeps your review history. If you edited the AviAnki note types' styling by hand, those edits are replaced.
- **Names North American birders know.** Cards use eBird's English names (Black-bellied Plover, Rock Pigeon). Where the international (IOC) name is different, a small "IOC" tag above the name shows it.
- **Tiers and seasons.**
  - `--tier standard` (the default) gives the 100 most-seen birds. `--tier everything` gives the region's 400 most common species. A bird with no photo or recording for the card types you chose doesn't take up a place; the next most-seen bird does.
  - `--month` keeps only the birds seen that month.
  - `--subdeck` puts the cards in a subdeck named after the region. Only birds not yet in your collection go there, because Anki keeps a bird you already have where it is. The help and README say how to move the rest.
- **Anywhere in the world, for personal use.** `avianki --ebird CODE` builds from any eBird region using your own `EBIRD_API_KEY`. eBird's terms don't allow sharing those decks.
- **Credits.** Every photo and recording is credited on its card. The deck description credits the datasets.

### Command line

- **Naming a region is forgiving.** A slug (`us-ma`), a name (`Massachusetts`), `dc`, `D.C.`, `Washington DC` or a bare state code such as `ma` all work. When a short code matches several regions, the message lists the slugs.
- **Cached photos and recordings are checked again.** A file in the cache that was cut short or damaged is downloaded afresh, with a warning, instead of going into your deck.
- **Your settings file is found where you run the command.** A `.env` file in the folder you run `avianki` from is read, wherever the program is installed.
- **Paths are checked first.** `~` works in `-o` and `--cache-dir`. If the output path cannot be written, `avianki` says so and exits with status 2 before downloading anything. A missing folder is created. When an existing file is overwritten, the summary says it was replaced.
- **Clearer feedback.** The summary counts birds with no recording or no photo on their own line. The progress bar is only drawn in a terminal. Network failures, a photo or recording that vanished while you were building, and a cache folder that cannot be written each say what to try next. Ctrl-C prints "Cancelled." and exits with status 130, and non-English names don't break redirected output on Windows.
- **Small options.** `--version` prints the version. `--tier` accepts upper case. An empty `--deck-name` is an error, and a name with `::` prints a warning that it makes a subdeck.
- **`avianki-catalog` without its extra** tells you to install `avianki[catalog]` and exits with status 2.
- **More birds have photos and recordings.** Western Cattle Egret, Eurasian Eagle-Owl, Black Francolin and Manx Shearwater are matched to the right sources.

### Package

- The licence is declared the current way (an SPDX expression plus the licence file), and both the wheel and the source archive include `LICENSE`. The source archive leaves out stray files such as `.apkg`, `.log` and `.env`.
- The links in the README on PyPI point to the project on GitHub.

### Removed

- allaboutbirds.org URLs and Google Place IDs as input. Use a region slug (`us-ma`), a name (`Massachusetts`), or `--ebird` with an eBird code.
- The Description → Name card type. It may return once descriptions can be shown without giving away the name.
- `call` and `song` as separate fields. There's now one recording per bird, because the sources don't reliably tell songs from calls.

### Requirements

- Python 3.10 or newer. `uvx avianki us-ma` needs nothing else.
- `--ebird` builds of species outside the catalog also need `avianki[catalog]` and ffmpeg. BirdNET checking of recordings needs `avianki[verify]` (Python 3.11 to 3.13).
