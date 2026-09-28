# 0017 — The CLI is a catalog client, with an explicit `--ebird` escape hatch

**Status:** Accepted, 2026-09-28 · **Ticket:** [#37](https://github.com/Ian-Costa18/AviAnki/issues/37)

## Decision

### Default: read the published catalog

`avianki REGION` accepts a catalog slug (`us-ma`) or a display name (`Massachusetts`). It reads the manifest from `--catalog-url` (by default the Pages site), downloads only the media it needs into the local cache, and writes the `.apkg` with genanki using the same note types, GUIDs and deck description as the browser. There's no ffmpeg, API key or scraping on this path.

### Escape hatch: `--ebird CODE`

- `--ebird CODE` covers any eBird region, anywhere in the world.
- The species list comes from the eBird API (it needs `EBIRD_API_KEY`), ordered as it is today.
- Media for each species comes from the catalog when the species is in it. Otherwise it's fetched live through the **same source registry and processing** the pipeline uses, which needs ffmpeg and optionally `avianki[verify]` for BirdNET. Mixing the two within one deck is fine, because provenance is per asset.
- The CLI prints a clear notice: **"Built from eBird data for personal use. eBird's terms don't allow redistributing this deck."** The deck description says the same thing.
- Coverage is detected, not asserted by the user. If `REGION` isn't in the catalog, the CLI says so and suggests `--ebird` with the matching code from `regions.csv` where there is one.
- For thinly covered species the CLI ships the thin deck (absence is acceptable). It doesn't fall back per species unless `--ebird` is given.

### Removed

- allaboutbirds URLs and Place IDs as input ([0002](0002-allaboutbirds-dormant.md)).
- Location-seeded deck names and GUIDs ([0009](0009-note-identity.md)).

### Maintainer entry point

`avianki-catalog build|validate|report` runs the pipeline. It's separate from `avianki` so the user-facing help stays short.

### Flags (the README is updated in the same change)

| Flag | Default |
|---|---|
| `REGION` | required, unless `--ebird` is given |
| `--tier standard\|everything` | `standard` |
| `--cards photo,audio,photo-audio` | `photo,audio` |
| `--month 1-12` | all year |
| `--subdeck` | off |
| `--ebird CODE` | off |
| `-o/--output` | `AviAnki-<region>.apkg` |
| `--catalog-url` | the Pages catalog |
| `-v`, `-q` | as today |

`--deck-name` stays as an advanced flag, and its help text warns that changing it puts notes into a different deck.
