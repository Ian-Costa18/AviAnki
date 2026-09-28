# 0014 — Monthly incremental rebuilds, sticky selections, a validation gate

**Status:** Accepted, 2026-09-28 · **Ticket:** [#24](https://github.com/Ian-Costa18/AviAnki/issues/24)

## Decision

### Cadence

- **The media half** rebuilds on a cron on the 1st of each month, plus manual `workflow_dispatch`.
- **The species half** changes only when GBIF publishes a new eBird Observation Dataset version. Every run checks the dataset's metadata. If the version hasn't changed, the previous region files are reused as they are.

### Selections are sticky

An asset chosen for a species keeps its place in later builds unless one of these happens:

- it disappears upstream
- its licence leaves the allowlist
- it fails a check that has since become stricter
- a pin says otherwise

Existing users' cards don't churn from month to month.

### Builds are incremental

- **State** is the previous release's manifest and provenance. Media is reused from the previous release's tarball rather than being re-downloaded from the sources.
- **Source calls** are made only for species that are new, unresolved, or whose sticky asset was invalidated.
- **The HTTP cache** (`actions/cache`) keeps a partly finished first build from starting over.
- **If a run stops short** because of the 10,000-requests-a-day budget or a 5-hour job cap, it publishes what it has. Unfinished species are simply absent this month.

### Versioning

- `catalog_version` is the build date. The browser always takes the newest manifest.
- Content-addressed media means cache invalidation never needs to happen ([0013](0013-catalog-layout.md)).
- The manifest has a `format` integer. The app refuses a format it doesn't know and shows a "please reload" message.

### Validation gate

A build publishes only if **all** of the following hold. Otherwise the job fails, nothing is released or deployed, and the previous site keeps serving.

1. Every JSON file matches its schema, and every referenced media file exists with the hash in its name.
2. Every asset's `licence_id` is in the exact, versioned allowlist, and every attribution field the licence requires is present ([0012](0012-attribution.md)).
3. Every audio asset passed BirdNET or is pinned.
4. The total site is ≤ 900 MB.
5. **No region lost more than 10% of its species**, and the catalog lost no more than 5% of its assets, compared with the previous build. Deliberate drops need a `--allow-shrink` override.

A species whose source calls *failed* keeps its previous entry, which is how the source contract separates failure from absence ([0007](0007-source-contract.md)).

### Build report

Every run writes `build-report.md` as a job summary. It shows counts per role, what was rejected and why, BirdNET rejects, species with no media, and sources that failed.
