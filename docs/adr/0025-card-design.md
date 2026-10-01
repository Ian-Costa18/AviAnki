# 0025 — Card design: photo first, the phone's own font, night mode, and an IOC tag

**Status:** Accepted, 2026-10-01 · **Amends:** [0012](0012-attribution.md) (credit type size) · **Ticket:** [#68](https://github.com/Ian-Costa18/AviAnki/issues/68) · **Follow-up:** [#67](https://github.com/Ian-Costa18/AviAnki/issues/67) (themes)

## Context

The 1.0 cards were styled once and never reviewed on a real screen. Mockups built from the published catalog, at phone and computer widths and in both day and night mode, showed four problems:

- **The photo jumps.** The answer side puts the name above the photo, so the photo moves down when the card flips and the eye has to find it again.
- **No night mode.** `card.css` hard-codes a light background, so in night mode the card stays a glaring light box.
- **The card is nested in itself.** Anki's `<body>` already has class `card`. The templates wrap everything in a second `<div class="card">`, so every `.card` rule applies twice: double padding and a nested maximum width.
- **Credits are louder than they need to be.** At 0.75em in Georgia they take about a third of a phone screen on some birds.

The maintainer reviewed 18 variants and chose this design. The alternatives are in #67 as themes.

## Decision

### Layout: the photo stays still, and every back is the same

- Only the photo has to stay still when a card flips; it is the biggest thing on the card. The play button may move.
- Fronts put the photo first, with the prompt under it ("What bird is this?"). The audio front is a compact play button with "Who's calling?" beside it, on one line. A photo + audio front is the photo, then the play button with the question beside it.
- All three card types share one back, so the order never varies. There is no question on it. In this order:
  1. the photo, if the note has one, where it was on the front
  2. the optional IOC tag
  3. the name
  4. the scientific name
  5. the recording, if the note has one, labelled "Hear the call"
  6. the credits
- The photo is full width, rounded, with height up to 46vh and `object-fit: contain`. The grey letterbox box is gone.

### Type and colour

- **Font:** the system font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif`), 17px, line height 1.45, left-aligned, maximum width 560px, centred.
- **Name:** 1.6em, bold, in the main text colour.
- **Scientific name:** italic, in the secondary colour.
- **Colour tokens:**

  | Token | Day | Night |
  |---|---|---|
  | text | `#111` | `#f1f1f1` |
  | secondary text | `#5f6368` | `#a0a4a8` |
  | background | `#fff` | `#1c1c1e` |

- **Night mode:** handled under both `.nightMode` (desktop and iOS) and `.night_mode` (AnkiDroid). Because `.night_mode` appears in the CSS, AnkiDroid's automatic colour inversion doesn't apply.
- **No nesting:** the template wrapper is `<div class="av">`, not `.card`, and `.card` styles only the page background.

### Credits (amends 0012)

- Credits use the system font at 11.5px (it was 0.75em, about 12px in Georgia), line height 1.4, in the secondary colour, under a thin rule.
- They stay visible on every answer side; nothing is collapsed. Everything else in 0012 stands: what a credit line contains, title rules, and answer side only.

### The IOC tag

- When the name on the card differs from the IOC English name, a small tag sits directly above the name: `IOC Grey Plover`, with "IOC" in bold, inside a thin rounded outline in the secondary colour. The text is 10.5px.
- No tag for differences in spelling or punctuation only (Grey/Gray, hyphens, capitals, apostrophes).
- No tag where the two lists split the bird differently and the IOC name refers to another population, for example Yellow Warbler vs Mangrove Warbler. A tag there would name the wrong bird.
- The tag needs the North American names to land first: it arrives with the names change (a separate ADR). Until then no card has a tag, and the CSS for it ships unused.

### What doesn't change

- Fields, model ids, card-type names and GUIDs stay frozen ([0009](0009-note-identity.md)). Only template HTML and CSS change.
- Anki updates the note type on import, so a re-imported deck restyles existing cards and keeps their review history.
- The browser deck stays identical to the genanki deck. `web/js/notetypes.json` is regenerated from `deck/notetypes.py`.

## Consequences

- Importing a 1.1 deck restyles every AviAnki card in the collection, including cards from an older import. That is intended.
- Anyone who edited the AviAnki note type's styling by hand loses those edits on re-import. The changelog says so.
- Themes (#67) build on this layout. They may change CSS and the order of the answer block, but must keep the photo in place.
