# 0019 — Decks are verified automatically: Anki's backend, Playwright and BirdNET

**Status:** Accepted, 2026-09-28 · **Tickets:** [#33](https://github.com/Ian-Costa18/AviAnki/issues/33), [#34](https://github.com/Ian-Costa18/AviAnki/issues/34)

## Context

The map assumed a person would listen to clips (#33), look over cards, and build a deck on a physical phone (#34). The user asked for as much of that as possible to be automated. The #18 prototype already drove Anki's real Rust backend (`verify_apkg.py`) and the real desktop reviewer (`drive_anki_desktop.py`).

## Decision

| Question | How it's answered automatically | Where |
|---|---|---|
| Does the file import? | Import into a fresh collection with the `anki` PyPI package (the same Rust backend the apps use). Zero errors, expected note and card counts, **media check clean**. | `tests/acceptance/` |
| Does re-importing keep progress? | Answer some cards, re-import a rebuilt deck, assert every note comes back as `duplicate` or updated, and that the review history is unchanged. Also test a Standard → Everything upgrade and a multi-part import. | same |
| Is every card answerable, and does the front give nothing away? | Render every card's question and answer with the backend. The front must reference media that exists and must not contain the common name, scientific name, or any word of either. The back must contain the name and a credit line for every asset. | same |
| Is the browser build equivalent to genanki? | Build the same selection both ways and compare notes, models, GUIDs and media. | same |
| Does the web app work end to end? | Playwright (Chromium and WebKit) against a locally served fixture catalog: pick a region, build, capture the download, feed it to the acceptance checks. | `tests/web/` |
| Can a phone build it? (#34) | Playwright mobile emulation (Pixel 7, iPhone 14) with 4× CPU throttling, and Chromium launched with `--js-flags=--max-old-space-size=256` to stand in for a constrained tab. Build Standard, and build Everything in parts. Record peak `performance.memory`. **Fail if a build dies or goes over 200 MB of heap.** | `tests/web/` |
| Is the bird audible, and is it the right bird? (#33) | The BirdNET gate in the pipeline ([0011](0011-media-selection.md)). | catalog build |
| Is the photo the right bird? | Commons lead images are editorially curated. The plausibility check catches taxonomy mismatches ([0008](0008-species-and-region-identity.md)). Each build also writes a **contact sheet** (`contact-sheet.html`, a grid of photo and name) that an agent reviews by eye at release time. | catalog build |

## Remaining risk, stated plainly

- **iOS Safari** is only approximated by WebKit under emulation. Real memory limits and the download or share hand-off on an iPhone aren't reproduced.
- **AnkiMobile** can't be tested without an Apple device.

A single tap-through on a real phone before announcing 1.0 is recommended but not required. An Android emulator running AnkiDroid is possible if that risk ever needs closing without a device.
