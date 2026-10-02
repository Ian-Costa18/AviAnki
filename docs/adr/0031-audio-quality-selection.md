# 0031 — Audio: pick the clip where the bird is the one you hear

**Status:** Accepted, 2026-10-02 · **Supersedes:** [0023](0023-audio-first-pass.md) · **Amends:** [0005](0005-media-sources.md), [0011](0011-media-selection.md), [0014](0014-catalog-rebuilds.md), [0021](0021-contract-field-additions.md) · **Ticket:** [#83](https://github.com/Ian-Costa18/AviAnki/issues/83)

## Context

0023 keeps the first recording in which BirdNET gives the species 0.5 in any 3-second window. That proves the bird is *somewhere* in the recording. It says nothing about whether the 10-second clip we ship is *about* that bird. Listening to the first catalog showed the gap. The Blue Jay is faint, under crickets and a Gray Catbird. The Mourning Dove doesn't start for three seconds, and a catbird and a titmouse come first. The White-breasted Nuthatch, by contrast, is clearly in front even with other sounds around it. In a deck of 200 birds, a clip with two or three singers is a guessing game about which one is the answer.

We re-scored all 697 published clips with BirdNET in 1-second steps. Here "present" means the species scores 0.5 or more:

| Measure on the shipped 10 s clip | Clips |
|---|---|
| Target present in under half the clip | 29% |
| Target first present at 2 s or later | 19% |
| Another label at 0.5 or more | 28% |
| At least one of the three | 51% |
| Clean: present in 75% or more, from within 1 s, nothing else above 0.3 | 26% |
| No 3 s stretch reaches 0.5 at all (the cut missed the bird) | 3% |

Our three examples score the same way the ear does. The Nuthatch is present in 88% of its clip, with nothing else above 0.07. The Blue Jay is present in 25%, with a Gray Catbird at 0.58. The Mourning Dove starts at 3 s, with a Gray Catbird at 0.54. So the problem can be measured, and fixing it is a ranking problem, not a listening one.

Background sound itself is not the problem. A field recording with other birds faintly behind the target is what birding sounds like, and it is fine. The problem is when the target is not clearly the main thing heard.

## Decision

### 1. Score every candidate on the clip it would become

BirdNET runs over the first 60 s ([0023](0023-audio-first-pass.md)'s bound stands) with a **1-second step** (overlap 2 s), instead of back-to-back 3 s windows. For a candidate:

1. **Find the stretch.** Take the 10 s stretch, on the 1 s grid, with the highest summed target confidence.
2. **Start on the bird.** Move the start to the first step inside that stretch where the target reaches 0.5, keeping 10 s where the recording allows it. The clip no longer opens on something else.
3. **Measure that exact clip:**
   - **presence**: the share of its steps where the target is at 0.5 or more.
   - **competitor**: the highest confidence of any *other* label inside the clip. Only these labels count:
     - species in our own `species.csv` (BirdNET's European false positives don't count);
     - BirdNET's non-bird noise labels (human voice, engine, dog and similar).

     Labels in the target's own genus are ignored, because they are BirdNET confusions, not second birds.
   - **prominence**: how far the loudest tenth of the clip's frames sits above its noise floor, in decibels, measured in a band around the target's energy. This is the audio-engineering measure for "faint, distant bird under crickets". It is **kept only if calibration shows it separates clips beyond what presence and competitor already do**. Otherwise it is dropped, and this ADR is amended to say so.
4. **Rank.** A candidate is **good** when presence ≥ 0.6 and competitor < 0.5 (plus the prominence floor, if calibration keeps it). Each candidate also gets a single **quality** score for ranking: mean target confidence over the clip, minus the competitor's excess over 0.3. The 0.5 gate from 0011 still decides whether a candidate is usable at all.

The numbers above are starting values. The implementation calibrates them against the 697-clip survey: the Nuthatch must come out good, and the shipped Blue Jay and Mourning Dove clips must not. The values it settles on are written back into this ADR when it merges. All thresholds live in one place, beside `MIN_CONFIDENCE`.

### 2. Look further, stop early

- Up to **10** candidates per species, not 5.
- **The first good candidate wins.** If none is good, the usable candidate with the highest quality score wins. If none is usable, the species has no audio, as before.
- Most species should stop after one or two downloads. The rare species that drain all ten are the ones that most needed it.

### 3. xeno-canto metadata orders the Commons candidates

79% of Commons audio mirrors xeno-canto ([0005](0005-media-sources.md)), and xeno-canto records two things per recording:
- a quality grade, A to E;
- an `also` list of background species.

The shipped Blue Jay is grade A, yet its `also` list names the Gray Catbird. So the background list is the useful part of the metadata.

- For a Commons candidate with a xeno-canto number, look its metadata up with the xeno-canto API v3.
- Order Commons candidates with **no background species** first, then by grade (A, B, then C, D, E, or none), then by the existing rank key.
- **It orders; it never gates.** BirdNET still decides.
- `Candidate` gains two optional hints, extending 0021: `xc_quality` (the grade, or None) and `xc_background` (the number of background species, or None). Like 0021's hints, they steer selection only and never reach the catalog.
- **xeno-canto stays metadata only.** Its own downloads are mostly NC-licensed. Audio still comes only from Commons mirrors and iNaturalist under the existing licence allowlist. This amends 0005's "no xeno-canto API": the account now exists, and these hints are worth having.
- **The key.** It comes from `XC_API_KEY`: the `.env` locally, a repository secret in the catalog workflow. The API takes it as a URL parameter, so it must be **removed from HTTP cache keys, logs and error messages**, the same rule as the eBird token. Lookups are cached by xeno-canto number.
- **Without a key, or if the API fails,** the build keeps the existing order and the build report notes it. It is never a build failure.

### 4. Re-select once, then stay sticky

- Provenance gains `audio_rule` (now `2`) and the chosen clip's `presence`, `competitor` and `quality`. These are additive fields on the provenance file.
- Under 0014, "a check that has since become stricter" invalidates a sticky asset. Previous audio without `audio_rule >= 2` therefore goes back through selection once.
- If the old recording still wins, it is kept with its new cut. After that, audio is sticky as before.
- Pins still skip ranking and BirdNET.
- This churns existing audio exactly once. That is acceptable before 1.0.

### 5. A person listens to the tail only

After the rebuild, a review page lists the lowest-quality clips, about 50, with players and a keep or replace choice. Replacements land in `data/pins.toml` as usual. That turns "listen to 700 clips" into "listen to the doubtful few". It is a review aid, not part of the build.

### Not doing: cleaning the audio

There is no denoising and no source separation:
- Noise reduction can't remove a second bird.
- Bird-separation models leave artefacts.
- Some background is realistic and wanted.

Choosing better recordings fixes the root cause.

## Consequences

- The cold audio pass costs more: up to twice the downloads in the worst case, and three times the BirdNET steps per minute analysed. The early stop keeps the typical species at one or two candidates. The first rebuild after this change re-selects every species' audio once.
- The build report gains:
  - the presence, competitor and quality distribution;
  - the share of species that settled for a non-good clip;
  - the xeno-canto lookup count.
- A missing `XC_API_KEY` secret makes the ordering slightly worse, never a failure.
- Audio coverage should stay about the same, because the 0.5 gate is unchanged. What changes is which recording wins and where it is cut.
