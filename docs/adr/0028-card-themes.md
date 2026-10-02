# 0028 — Card themes, name on the photo, and custom themes

**Status:** Accepted, 2026-10-01 · **Amends:** [0025](0025-card-design.md) (one look becomes a default among several) · **Related:** [0009](0009-note-identity.md) (identity stays frozen), [0012](0012-credits-on-every-answer.md) (credits), [0018](0018-package-layout.md) (layout), [0027](0027-ioc-name-field.md) (the IOC tag) · **Closes:** #67

## Context

[0025](0025-card-design.md) gave every card one design. People who study at night, who like a book-like look, or who want large type have no way to change it short of editing the note type's CSS by hand in Anki, which the next import overwrites. Issue #67 asked for themes. The website also needs to show what a theme looks like before the deck is built.

## Decision

### Two independent settings, both fixed when the deck is built

- **Theme** (colours and type): `--theme NAME` on the CLI, a picker on the website. `default` is the 0025 design, and its CSS and templates are byte-identical to before.
- **Name on the photo** (layout): `--name-on-photo` and a checkbox. On the answer, the IOC tag, the name and the scientific name sit on a dark gradient over the bottom of the photo. The recording and the credits stay below it. It works with every theme. A note with no photo falls back to names below, as before.

### Only CSS and the back template's HTML change

The identity in [0009](0009-note-identity.md) is untouched: deck id, model ids and seeds, model, template and field names, card types, GUIDs. `tests/deck/test_identity.py` pins every theme and layout against the frozen values. Fronts never change between layouts, so the photo's box is the same on the front and the back (0025).

### Defined once, in Python

- `deck/themes.py` is the only definition. A theme is a set of **tokens**: six colours (background, text, secondary, name, accent, credits) for day and again for night, plus five choices (font, name style, name weight, corners, accent rule). `deck/themes/_template.css` turns tokens into CSS. Some built-ins add a few rules of their own in `deck/themes/<name>.css`.
- The composed CSS is `card.css`, then the theme's CSS, then the layout's CSS (`deck/name-on-photo.css`), each added after a newline only when it is not empty. `notetypes.models_for(theme, name_on_photo)` returns the three note types. `MODELS` is `models_for()`.
- The website gets the same data: `scripts/gen_web_notetypes.py` exports the built-in tokens, the template, the fixed value tables and the extra CSS into `web/js/notetypes.json`, and `web/js/themes.js` fills the template by the same rule. `tests/web/test_web_themes.py` proves the browser's CSS equals Python's for every theme and layout and for a custom token set, and the apkg equivalence tests build themed decks both ways.

### The themes

Ten, all system fonts only, each with a one-line description shown by the picker.

| Theme | Look |
| --- | --- |
| `default` | Photo first, the phone's own font, a black name (0025) |
| `serif` | A green serif name over the usual layout |
| `field-guide` | Warm paper, the name in spaced small capitals and an accent rule beside the names |
| `nord` | The Nord palette: Snow Storm paper by day, Polar Night by night, Frost blue accents; credits in a soft box |
| `slate` | Cool blue-grey, square corners, credits in a thin box |
| `forest` | Sage green, round corners, names on a soft green panel |
| `plate` | A vintage plate print: sepia, an italic serif name between double rules |
| `minimal` | Centred on plain paper, a light name, lots of air |
| `midnight` | Always dark, by day and by night, with a soft blue accent |
| `high-contrast` | Larger type, pure black on white (white on black at night), strong outlines |

A first draft had an eleventh, `ocean`. After the visual review it was too close to `nord` and `slate`, so it was dropped. `nord` was a requirement and uses the official palette (`#2e3440`, `#3b4252`, `#4c566a`, `#d8dee9`, `#e5e9f0`, `#eceff4`, `#5e81ac`, `#81a1c1`, `#88c0d0`).

Rules every theme follows, each checked by `tests/deck/test_themes.py`:

- System fonts only. No web fonts, no images.
- Night mode for both `.nightMode` and `.night_mode`. Anki's `.nightMode .av` out-ranks `.av`, so every theme redeclares its night values.
- The photo is never moved, resized or reordered, and nothing is placed above it (0025).
- The credits are always visible on the answer ([0012](0012-credits-on-every-answer.md)), the IOC tag stays, and the play button keeps its size and its label.
- Contrast: all small text (text, secondary, credits) is at least 4.5:1 in both modes, tested with the WCAG formula. **One documented exception:** `nord` by day sets the name and accent (`#5e81ac` on `#eceff4`) at 3.50:1. That passes WCAG's 3:1 for large text, since the name is 27px (24.6px in capitals), and for the tag as a graphic, but it is below 4.5:1. The test asserts the 3:1 floor for names and tags and 4.5:1 for everything else. We kept the official Nord blue rather than darken it.

### Name on the photo

The `.photo` wrapper is `position: relative; width: fit-content; max-width: 100%`, so the gradient is exactly as wide as the picture and never overhangs a tall photo. The names are `position: absolute` at the bottom on a gradient from `rgba(0,0,0,.84)` to transparent, so white text keeps its contrast on any photo. The layout also applies to the front, so the photo's box is identical on both sides.

A very wide photo would be shorter than the names, so the overlay image has `min-height: 130px` with `object-fit: cover`: such a picture is cropped a little instead of the names hanging off its top. This was found by the browser test (an 800×300 picture overhung with a 112px minimum, because `high-contrast` has larger type), and the test now covers landscape, portrait, 800×300 and 1600×240.

### Custom themes

A `custom` choice in the picker lets someone set the tokens themselves:

- "Start from" any built-in, then six colour pickers, each for day and night, and fixed lists for font (sans, serif, rounded, mono, humanist), name style (normal, capitals), name weight (regular, bold), corners (square, slight, round) and accent rule (none, beside the names). Everything updates the preview as it is changed.
- **Safety.** Colours must match `^#[0-9a-fA-F]{6}$` (and are written in lower case). Everything else is one of a fixed list of values. No free text ever reaches CSS or HTML. The same rule is in Python (`tokens_from_mapping`) and JavaScript (`validateTokens`), and tests try bad colours (including a trailing newline and `;}` injections) and bad choices in both.
- **Tokens only.** A custom theme is the token template, so a built-in's extra rules (for example `nord`'s credit box) are not part of it. Starting from `nord` gives its colours, not its credit box.
- **Sharing.** **Copy theme** gives a TOML snippet (shown in a text box when the clipboard is not available). `avianki REGION --theme-file my-theme.toml` reads it: a missing key keeps the default's value, and a bad value or file exits with status 2. `--theme` and `--theme-file` cannot be combined. The look is also in the page address (`#theme=custom&...`), so a link reproduces it, and the last choice is kept in localStorage as a convenience (wrapped in try/catch, and the page works without it). A bad link falls back to the default look; it never half-applies.

### The website

- "Customize your cards" is always visible below the **Build my deck** button, not inside Advanced, which keeps only the deck options. It holds the picker, the checkbox, the custom editor and the preview. We call it "Customize" everywhere, not "settings".
- **The preview** draws a mock Rock Pigeon (`columba-livia`) card from the real note-type templates and the composed CSS, using a small renderer for the three mustache forms the templates use. The question and the answer are sandboxed `srcdoc` iframes (`sandbox="allow-same-origin"`: no scripts run inside them) with `<body class="card">`, side by side on wide screens and stacked on phones. A card-type switcher follows the ticked card types, a "Dark mode" toggle adds `nightMode`, and the picture, recording and credits are the species' real catalog media. The replay button is a lookalike that really plays the recording. If the catalog has no Rock Pigeon (or has not loaded), a plain placeholder picture is drawn and says it is an example.
- **One look per collection.** Anki keeps styling per note type, so a collection has one look at a time. The CLI `--help`, the README and a hint beside the picker all say so: importing a deck with another theme restyles the cards you already have, and replaces styling you edited yourself. Review history is kept; an acceptance test imports a deck, answers cards, re-imports with another theme and checks no note or progress is lost.
- **Size.** The page shell is 86 KB gzipped after this change, against the 150 KB budget in `test_web_shell_budget.py`, so the budget stays as it is.

## Consequences

- A theme or a custom theme is cheap to add: tokens, plus optional extra CSS, plus a description. The tests that apply to every theme pick it up from the registry.
- Importing a themed deck over an existing one updates the three note types' CSS (and the back template with `--name-on-photo`) in place. No field, template name or id changes, so Anki doesn't ask anything and no full sync is forced. Cards in a collection that has never imported AviAnki are unaffected.
- A custom theme given by a hand-written TOML file can have poor contrast. The CLI doesn't check it. The website's pickers don't either: the preview is the check.
- `tomli` is now a dependency on Python 3.10 (3.11 and later have `tomllib`).
