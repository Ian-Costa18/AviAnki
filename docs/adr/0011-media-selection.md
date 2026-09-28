# 0011 — Automatic media selection, with BirdNET verifying audio

**Status:** Accepted, 2026-09-28; audio selection amended by [0023](0023-audio-first-pass.md) · **Tickets:** [#10](https://github.com/Ian-Costa18/AviAnki/issues/10), [#33](https://github.com/Ian-Costa18/AviAnki/issues/33) · **Amends:** map #6 "out of scope: BirdNET"

## Context

The PRD's bar is that *wrongness* is unshippable. For audio, that means a clip where the bird can't be heard, or a clip of a different bird. #33 planned for a person to listen to about 30 clips before fixing the ranking. The user doesn't want to curate by hand. The iNaturalist API also exposes no audio properties at all, and `faves_count` is zero on 96% of recordings.

## Decision

### Photos (no measurement needed)

1. **Commons lead image.** Reject it if it's SVG, not a photograph, has a long side under 800 px, or has a non-empty `Restrictions`. Fetch the 960 px thumbnail bucket (arbitrary widths return 400). Downscale so the long side is 800 px. Encode WebP q80, stepping down to a 150 KB cap.
2. **Fallback: iNaturalist.** Research grade, not captive, at least 2 ID agreements, and the licence on the allowlist. Rank by agreements, then by licence permissiveness. Fetch the `large` size, then the same resize and encode.
3. Processing is purely technical (resize and re-encode). There's no cropping or colour work, so the result stays a copy rather than an adaptation (licence research §5.2 item 7).

### Audio (measured, then verified)

1. **Candidates:** Commons audio in the species' category, then iNaturalist (research grade, `sound_license` on the allowlist, not captive), ranked by ID agreements. Up to **5** are downloaded.
2. **Verify with BirdNET.** Run BirdNET on each full recording and look up the species' `birdnet_label`. **A candidate is rejected unless some 3-second window has a confidence of at least 0.5 for the target species.** This check replaces the human listening in #33, and it enforces "wrong bird" and "inaudible bird" automatically.
3. **Pick the window.** The winning candidate is the one with the highest summed confidence over its best **10-second window**. That window is what gets trimmed. This replaces `trim_to_mp3()`'s "first 10 seconds" assumption.
4. **Process:** `highpass=f=250,loudnorm=I=-18:TP=-1.5:LRA=11`, then mono 44.1 kHz 96 kbps MP3. This is the chain the audio research measured, which brought a 46 dB loudness spread down to 6 dB. The modifications `["trimmed to 10 s", "high-pass filtered", "loudness normalised", "transcoded to MP3"]` are appended to the asset record.
5. **If nothing passes, the species has no audio.** That's an acceptable absence, not an error.

### Pins

`data/pins.toml` has one table per species id, with these keys:

- `photo`: a source token to force
- `audio`: a source token to force
- `exclude`: a list of tokens never to use
- `note`: a free-text reason

A pinned asset still goes through the licence gate, but skips ranking and BirdNET. Pins arrive as pull requests. The same file carries **credit-removal requests** (`exclude` plus a note), which the CC licences require us to honour.

### BirdNET licensing

BirdNET-Analyzer's model is **CC BY-NC-SA 4.0**. It's used only as a build-time tool, in a non-commercial MIT project. The model isn't redistributed and its outputs aren't shipped, only our choice of clip. It's installed as an optional extra (`avianki[verify]`), needed by the catalog build and by `--ebird` CLI builds that want verification.

## Consequences

- Audio coverage drops below the 90–96% the research measured, because BirdNET rejects some recordings. That's the intended trade: quality beats coverage.
- `species.csv` gains a `birdnet_label` column. Species BirdNET doesn't know get no audio, and the build report lists them.
