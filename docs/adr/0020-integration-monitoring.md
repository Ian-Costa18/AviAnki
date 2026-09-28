# 0020 — The weekly check fails loudly and watches the real sources

**Status:** Accepted, 2026-09-28 · **Ticket:** [#26](https://github.com/Ian-Costa18/AviAnki/issues/26)

## Context

PR #4 made the integration test skip whenever allaboutbirds returned 403. The weekly check has passed ever since while testing nothing. allaboutbirds is dormant now ([0002](0002-allaboutbirds-dormant.md)), so pointing the check back at it would fail every week forever.

## Decision

- **Remove the skip, and remove the allaboutbirds integration tests.** A dormant source isn't monitored.
- **The weekly check covers what the product depends on.** It has no skips: a network failure counts as a failure and opens the tracking issue.
  1. **Source smoke tests.** For three fixed species (Northern Cardinal, Brown Pelican and Whimbrel, chosen for common, known audio gap, and known taxonomy split), each registered source returns candidates, and every candidate's licence record is complete. Brown Pelican is *expected* to have no audio, so the test asserts the absence is reported as absence, not an error.
  2. **GBIF EOD.** `species_for("us-ma")` returns at least 300 species. Also report if the dataset version has changed.
  3. **The published site.** `manifest.json` loads, and one random media file returns 200 with `access-control-allow-origin: *`.
  4. **eBird (CLI path).** It runs only when `EBIRD_API_KEY` is set. When the key isn't set this is the one allowed skip, and it's reported in the job summary.
- **Until the new sources exist** (build milestones M2–M3), the weekly check runs only the eBird smoke test. Its removal of the skip ships first.
