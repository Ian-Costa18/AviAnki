# 0012 — Credits go on the answer side of every card, and dataset credit goes in the deck description

**Status:** Accepted, 2026-09-28 · **Ticket:** [#22](https://github.com/Ian-Costa18/AviAnki/issues/22) · **Evidence:** branch `research/licence-obligations` §5.3

## Decision

### Per asset: the `Credits` field

- The field is rendered by the pipeline, never from source HTML. Every value is escaped, and Commons' `Artist` wiki markup is reduced to plain text plus a link.
- There's one line per asset, clearly tied to that asset:
  > Photo: *Title* by **Creator** · [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) · [source](https://commons.wikimedia.org/wiki/File:…) · resized
- A line always includes the **title** when the licence is 3.0 or earlier, **or** when the licence version is unknown. iNaturalist's `cc-by` has no version, so we always follow the stricter 3.0 rule for it. That settles the open iNat licence-version question without asking iNat.
- Credits appear on the **answer side only**, in small but legible type (`.credits`: 0.75em, muted colour, links underlined). The front stays clean, because a credit line such as a file title can give the species away.
- AviAnki's own name never appears on a card. That keeps asset credits "at least as prominent" as ours, which BY-SA 3.0 §4(c) requires.

### Per deck: the description

The `AviAnki` deck description is shown on the deck overview in every Anki client. It carries:

1. Three lines of how-to-study guidance ([0016](0016-last-mile.md)).
2. Dataset credit: *"Species lists and seasonality: eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF, CC BY 4.0"*, with a link to the dataset DOI, plus *"modified: filtered and ranked by region"*.
3. The licence notice:
   > This deck is a compilation. AviAnki's templates and selection are MIT-licensed. Each photo and recording keeps its own licence, credited on its card, and no further terms are imposed on it.

The web app footer repeats items 2 and 3 and links a generated `credits.html`, which lists every asset in the catalog.

### Existing decks

The field layout is new ([0009](0009-note-identity.md)). New note types mean there's nothing to migrate.
