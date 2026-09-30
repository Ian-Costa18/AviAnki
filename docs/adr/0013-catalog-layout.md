# 0013 — Content-addressed files per asset, plus a small manifest

**Status:** Accepted, 2026-09-28 · **Ticket:** [#28](https://github.com/Ian-Costa18/AviAnki/issues/28)

## Context

Pages fixes `max-age=600`, and bundling was proposed so that returning users wouldn't have to revalidate about 400 files. But per-region bundles duplicate shared species across dozens of regions, and a bundle can't skip audio for a user who unticked audio cards.

## Decision

- **One file per asset**, named by content: `media/<sha256 first 16 hex>.<webp|mp3>`. Species shared between regions are stored once.
- **The app caches media itself.** It uses the **Cache Storage API**, keyed by filename. A content-addressed file never changes, so a cached copy is used without revalidating. Only the manifest is re-fetched, with `cache: "no-cache"`. This avoids the 10-minute revalidation problem without bundling.
- **Downloads use at most 6 fetches at a time.** Pages serves HTTP/2, so about 200 requests for a Standard deck are cheap.
- **Layout under the site root:**

```
catalog/manifest.json                     small; fetched on every visit
catalog/species.<hash>.json               every species: names + chosen assets + rendered credits
catalog/regions/<slug>.<hash>.json        ordered species ids + monthly frequency
catalog/provenance.<hash>.json            full §5.1 records, for audit (the app never loads it)
catalog/media/<hash>.<ext>
credits.html                              generated from provenance
```

- The format is documented in the spec, and `catalog/format.py` holds the JSON Schemas. **The format is the contract between Python and the browser.** Neither side imports the other.
- `manifest.base_url` is where the browser resolves every catalog path from, so moving to a different host is a one-line change. The Python client (`catalog/client.py`) instead resolves paths against the location it read the manifest from, so a local directory or mirror works; a host move there means a new `DEFAULT_BASE_URL` in a release.
- **The format stays neutral about `.apkg`** (PRD §1). It holds no Anki concepts: no GUIDs, note types or `[sound:]` tags. Those are added by the deck builders.

## Consequences

- The CLI reads the same layout and can fetch just the species it needs ([0017](0017-cli-reads-the-catalog.md)).
- Filenames are also the Anki media filenames (prefixed `avianki_`), so re-imports carry identical media, which Anki deduplicates.
