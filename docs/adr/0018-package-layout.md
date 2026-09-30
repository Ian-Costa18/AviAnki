# 0018 — Vertical slices with a dependency rule enforced by a test

**Status:** Accepted, 2026-09-28 · **Ticket:** [#21](https://github.com/Ian-Costa18/AviAnki/issues/21) · **Living document:** [`docs/source-layout.md`](../source-layout.md)

## Decision

- **Slices follow lifecycle stages** where the flow converges (taxonomy → catalog → deck) and **source type** where it diverges (`sources/<name>/`). The layout is in `docs/source-layout.md`.
- **The dependency rule:** *nothing downstream of the published catalog imports anything upstream of it.*
  - `deck/` and `cli.py` depend on `catalog/format.py` and `catalog/client.py` only, never on `sources/` or `media/`. The single exception is the `--ebird` path, which reaches the pipeline through `catalog/build.py`'s public function. *(Amended in M5: the crossing is the module `catalog/adhoc.py`, which wraps `build_species()` and the eBird source behind `build_ebird_species()`. The CLI imports that module, including its two exception types, and nothing else upstream. `tests/test_layout.py` allows exactly this.)*
  - `sources/*` never import each other, `catalog/` or `deck/`.
  - `core/` imports nothing from the package.
  - `web/` imports no Python at all. Its only dependency is the catalog format.

  This invariant is what keeps the catalog neutral about `.apkg` (PRD §1) and makes the browser a peer of the CLI instead of an afterthought.
- **Enforcement:** `tests/test_layout.py` parses imports with `ast` and asserts the rule. There's no new dependency.
- **The browser app** is a sibling tree, `web/`: plain HTML and ES modules with vendored `sql.js` and `fflate`, and **no bundler or build step**. The Pages workflow copies `web/` to the site root next to `catalog/`.
- **Tests mirror `src/avianki/`** under `tests/`. There's also `tests/web/` (Playwright) and `tests/acceptance/` (built decks through Anki's backend, see [0019](0019-verification-without-a-human.md)).
- **Migration is incremental.** New slices are added next to the flat modules. `cli.py` switches over in one change (the 1.0.0 break), then `ebird.py`, `media.py` and `redact.py` move into their slices, and `allaboutbirds.py` moves to `sources/allaboutbirds/` unregistered. *(Done in M5. `redact.py` stays flat: it has no upstream imports and nothing uses it until Description to Name returns.)*
