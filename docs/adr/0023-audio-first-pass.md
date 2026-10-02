# 0023 — Audio: take the first candidate that passes BirdNET, and analyse only its first minute

**Status:** Superseded by [0031](0031-audio-quality-selection.md) (accepted 2026-09-28) · **Amends:** [0011](0011-media-selection.md) · **Ticket:** [#41](https://github.com/Ian-Costa18/AviAnki/issues/41)

## Context

[0011](0011-media-selection.md) downloads up to five audio candidates per species, runs BirdNET on each whole recording, and keeps the one with the highest summed confidence. M3 measured what that costs on a cold build of about 990 species:

- iNaturalist sounds run to several MB each (a 7.5 MB WAV in a 30-species sample). Five per species is roughly 35 GB of downloads.
- BirdNET costs about 0.02 CPU-seconds per second of audio, and Actions runners are slower than a dev machine. A full-recording pass over five candidates is hours of compute, and the cold-build estimate was already 75-225 minutes with fewer.

The PRD's bar is that a wrong clip is unshippable and a missing one is fine. Choosing the *best* of several passing clips buys polish, not correctness; the 0.5 gate is what buys correctness.

## Decision

- **Stop at the first candidate that passes.** Candidates are ordered Commons first, then iNaturalist by agreements (as in 0011), capped at 5, and evaluated in that order. The first one with confidence >= 0.5 in some 3 s window wins. Later candidates are not downloaded.
- **Analyse only the first 60 seconds** of a recording. The best 10 s window is chosen within that minute, and the processing chain then runs on the original bytes at that start offset. A recording whose bird only appears after a minute is rejected; that is an acceptable absence.
- **Provenance records the outcome**: `verified = "birdnet"` and the winning window's confidence. Rejected candidates are listed in the build report with the best confidence each reached.
- **Failure is still not absence.** If a source call fails, the species keeps its previous audio, or stays unfilled until the next build. Only an empty result from every source, or five candidates that all fail the gate, counts as absence.
- Everything else in 0011 stands: the 0.5 gate, the 10 s window, the processing chain, pins skipping ranking and BirdNET, the licence gate.

## Consequences

- Cold-build downloads and BirdNET time fall to roughly one candidate per species on average instead of five.
- The chosen clip is the first acceptable one, not the strongest. A later reviewer can pin a better clip with `data/pins.toml`.
