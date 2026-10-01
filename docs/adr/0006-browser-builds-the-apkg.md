# 0006 — The browser builds the `.apkg`, streaming, and on phones too

**Status:** Accepted, 2026-09-28 · **Tickets:** [#18](https://github.com/Ian-Costa18/AviAnki/issues/18), [#34](https://github.com/Ian-Costa18/AviAnki/issues/34) · **Evidence:** branch `prototype/apkg-in-browser`

## Context

The #18 prototype showed that `sql.js`, plus about 460 lines of hand-written writer code, produces an `.apkg` whose notes, models and decks match genanki's output byte for byte. Anki imports it cleanly on desktop and AnkiDroid.

The prototype assembled the zip with JSZip. Its **peak heap was about 2× the package size** and grew superlinearly (429 MB of heap for 212 MB of output). That's the number that threatens phones. #34 was going to measure the phone ceiling by hand.

## Decision

- **Port the prototype writer** (`apkg.js`: md5, base91 GUIDs, Python-compatible JSON, `req` computation, schema seeds) into `web/js/apkg/`.
- **Replace JSZip with streaming.** Use fflate's `Zip` with `ZipPassThrough` in store mode (the media is already compressed). Emit output chunks straight into `Blob` parts and drop each media buffer once it has been written. Browsers keep large Blob parts off the JS heap, so peak heap is roughly *one batch of in-flight media plus the SQLite database*, not 2× the package.
- **Download** by `URL.createObjectURL` plus `<a download>`. If `navigator.canShare({files})` is available, also offer a **Share** button, so iOS and Android can hand the file straight to Anki.
- **Parts as a fallback.** When a build is over 150 species *and* the device looks constrained (`navigator.deviceMemory` ≤ 4, or any iOS device), the app builds consecutive packages of 150 species each and names them `AviAnki-part-1-of-3.apkg` and so on (*amended 2026-09-30: `AviAnki-<region slug>-part-1-of-3.apkg`, so two regions' parts never collide in Downloads*). Because note identity is the bird ([0009](0009-note-identity.md)), importing the parts in any order produces the same collection as one package would.
- **#34 isn't run as a manual phone test.** It becomes an automated check in [0019](0019-verification-without-a-human.md): a Playwright build under a capped heap and mobile emulation.

## Consequences

- There's no `ffmpeg.wasm` or any other media processing in the browser. The catalog is ready to put on cards.
- The writer has to stay equivalent to genanki. A test compares a browser-built and a genanki-built package for the same selection.
- iOS Safari's memory behaviour is only approximated (by WebKit under emulation). That remaining risk is written down in the spec.
