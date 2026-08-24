# PROTOTYPE — can a browser build a valid `.apkg`?

**Throwaway.** Built to answer [issue #18](https://github.com/Ian-Costa18/AviAnki/issues/18),
the load-bearing feasibility question for the static-site architecture. Nothing
here is production code: no tests, no error handling, no abstractions.

**Answer: yes.** A browser produces a `.apkg` that Anki imports clean, and that
Anki treats as *the same deck* as a CLI-built one. Full findings are on the
issue; this file is how to re-run it.

## Run it

```bash
uv run python prototype/apkg-in-browser/serve.py     # http://localhost:8777
```

Two buttons:

- **Build the 3-species catalog deck** — real Commons photos and iNaturalist
  audio from `catalog/`, the real note types out of `avianki.anki_model`, plus a
  prototype-only note type testing the randomised-audio question. Add
  `?noproto=1` to leave that out and get a file directly comparable to a
  genanki build.
- **Scale test** — synthetic media at the sizes the photo/audio research
  measured. This is the one that matters on a phone.

## Check the result

```bash
# rebuild the catalog (network; needs ffmpeg)
uv run python prototype/apkg-in-browser/build_catalog.py

# build the same deck with genanki, for comparison
uv run python prototype/apkg-in-browser/build_reference.py

# diff the two where it matters
uv run python prototype/apkg-in-browser/compare_apkg.py <browser>.apkg reference-genanki.apkg
```

The verification scripts need Anki's own libraries, which are not project
dependencies — install them into a throwaway venv pinned to the *desktop*
version so the result speaks for the app actually installed:

```bash
uv venv /tmp/ankiverify --python 3.13
uv pip install --python /tmp/ankiverify "anki==25.09.2" "aqt==25.09.2" PyQt6-WebEngine

# import through Anki's real Rust backend; a second file is imported into the
# same collection, which is how the duplicate-deck question gets answered
/tmp/ankiverify/bin/python prototype/apkg-in-browser/verify_apkg.py <first>.apkg [<second>.apkg]

# what does Anki do with three [sound:] tags? (backend view)
/tmp/ankiverify/bin/python prototype/apkg-in-browser/inspect_audio_card.py <file>.apkg

# …and in the real desktop webview (silent — see the module docstring)
/tmp/ankiverify/bin/python prototype/apkg-in-browser/drive_anki_desktop.py <file>.apkg 8
```

`drive_anki_desktop.py` opens the actual Anki desktop app, forces each
randomiser template into the real reviewer N times, and reads back the card's
own diagnostic div. It is muted at the source and has a watchdog, so it never
plays audio and never sits open unattended.

## How much had to be written by hand

`apkg.js` is 462 lines. There is no browser equivalent of `genanki`, so the
gap is filled by:

| Piece | ~lines | Why there is no library |
|---|---|---|
| `md5` | 50 | WebCrypto deliberately omits md5, and the deck/model IDs are md5-derived |
| base91 note GUIDs | 25 | Anki's own encoding; needs `BigInt` for the 8-byte integer |
| Python-compatible JSON | 40 | `JSON.stringify` differs from `json.dumps` in three separate ways (below) |
| `req` computation | 55 | Needs enough of mustache to run genanki's sentinel trick |
| schema + `col` seed blobs | 180 | Transcribed verbatim from genanki; no JS source exists |
| builder glue | ~110 | — |

Plus 0.8 MB of vendored `sql.js` (including a 660 KB wasm) and `JSZip`.

**The three JSON traps**, all of which silently corrupt the output rather than
erroring:

1. Python's default separators are `', '` and `': '`; JS uses `','` and `':'`.
2. Python defaults to `ensure_ascii=True`. The card templates contain 🖼 🔊 🎵,
   so this bites on the first build.
3. JS objects reorder integer-like keys ascending. The `models` blob is keyed by
   numeric notetype IDs, so plain objects silently resort them — `Map` throughout.

## Files

| | |
|---|---|
| `index.html`, `app.js` | the page |
| `apkg.js` | the hand-written `.apkg` writer |
| `serve.py` | static server; also exports the real note types to `model.generated.json` |
| `build_catalog.py` | fetches the 3-species media catalog |
| `build_reference.py` | the same deck via genanki |
| `compare_apkg.py` | diffs two `.apkg`s where it matters |
| `verify_apkg.py` | imports through Anki's real backend |
| `inspect_audio_card.py` | what Anki does with three `[sound:]` tags |
| `drive_anki_desktop.py` | the same question in the real desktop webview |
| `desktop-webview-result.txt` | captured output of the run reported on the issue |
