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
   - **prominence**: how far the loudest tenth of the clip's frames sits above its noise floor, in decibels, measured in a band around the target's energy. **Dropped after calibration** (see *Calibrated values*): it did not separate clips beyond what presence and competitor already do.
4. **Rank.** A candidate is **good** when presence ≥ 0.6 and competitor < 0.5. Each candidate also gets a single **quality** score for ranking: mean target confidence over the clip, minus the competitor's excess over 0.3. The 0.5 gate from 0011 still decides whether a candidate is usable at all.

The numbers above were starting values. They were calibrated against the clip survey: the Nuthatch must come out good, and the shipped Blue Jay and Mourning Dove clips must not. The settled values are under *Calibrated values* below. All thresholds live in one place, beside `MIN_CONFIDENCE` in `media/verify.py`.

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

## Calibrated values

Calibrated on 2026-10-02 against the 702 clips then published (10 s, 48 kHz mono), scored with BirdNET v2.4 at a 1 s step over the shipped clip as it stands. The scoring is `ClipAnalysis.choose` in `src/avianki/media/verify.py`; the constants are beside `MIN_CONFIDENCE`.

| Constant | Value | Meaning |
|---|---|---|
| `OVERLAP_S` | 2.0 | a 3 s window every second |
| `MIN_CONFIDENCE` | 0.5 | unchanged: the usability gate, and the per-step "present" test |
| `PRESENCE_MIN` | 0.6 | share of the clip's steps with the target at 0.5 or more |
| `COMPETITOR_MAX` | 0.5 | a counted label at this or above makes the clip not good |
| `COMPETITOR_FREE` | 0.3 | quality ignores a competitor up to here |
| `OTHER_FLOOR` | 0.05 | other labels below this are not kept per window (memory only) |
| prominence | dropped | see below |

The starting values held. Presence 0.6 and competitor 0.5 are what the survey supports, and they classify the three examples as the ear does:

| Species | Presence | Competitor | Quality | Verdict |
|---|---|---|---|---|
| `sitta-carolinensis` (Nuthatch) | 0.875 | 0.07 (Black-capped Chickadee) | 0.80 | good |
| `cyanocitta-cristata` (Blue Jay) | 0.25 | 0.50 (Loggerhead Shrike) | 0.13 | not good |
| `zenaida-macroura` (Mourning Dove) | 0.625 | 0.54 (Gray Catbird) | 0.34 | not good (competitor only) |

Clips marked good among the 702 (680 pass the 0.5 gate on the clip as shipped):

| Presence | Competitor | Good |
|---|---|---|
| 0.5 | < 0.5 | 439 |
| **0.6** | **< 0.5** | **350** |
| 0.7 | < 0.5 | 274 |
| 0.8 | < 0.5 | 209 |
| 0.6 | < 0.4 | 334 |
| 0.6 | < 0.3 | 312 |

The Dove is the borderline case that decides the bar: it fails only on its competitor (0.541), and it would pass at competitor < 0.6, so that limit cannot move up. Its presence of 0.625 clears 0.6 with little to spare, so presence cannot move up much either. 38 of the 350 good clips carry a counted background label between 0.3 and 0.5: a faint distant bird behind the target is tolerated, which is what the 0.5 limit and the free zone up to 0.3 are for. Borderline ids to listen to when tuning: `megaceryle-alcyon` (present throughout, but an Eastern Phoebe at 0.51), `tyrannus-forficatus` (good, with a Least Tern at 0.47), `cistothorus-palustris` (good at presence 0.625, a Swamp Sparrow at 0.30), `podiceps-grisegena`, `cyrtonyx-montezumae`.

Decisions the calibration made, and corrections to this ADR's context:

- **Prominence is dropped.** Nine variants (band width 1, 2 and 4 kHz; top-tenth energy over the 10th, 25th percentile or median of the band) separate good from not-good clips with an area under the curve of only 0.58 to 0.59, hardly better than chance. They also call the Blue Jay clip prominent (35 dB). The target's presence and the competitor already carry the signal. There is no prominence field and no extra dependency.
- **The Blue Jay's competitor is 0.50, not 0.58.** The Gray Catbird at 0.58 in the context table came from windows padded past the end of the clip. Measured on the exact clip, the strongest other label is a Loggerhead Shrike at 0.50. It still fails the competitor limit (at or above 0.5), and its presence of 0.25 fails on its own. The context table's "another label at 0.5 or more: 28%" includes such padded-window readings.
- **Padded windows never count.** BirdNET pads the last windows past the end of the audio. They are excluded from every clip metric, and the whole-recording search ignores a window that is not entirely inside the stretch.
- **The competitor set.** Counted: the labels of `species.csv` species, plus the BirdNET labels `Dog`, `Engine`, `Fireworks`, `Gun`, `Human non-vocal`, `Human vocal`, `Human whistle`, `Power tools` and `Siren`. Not counted: `Insecta`, `Environmental` (wind, rain) and `Noise`, which are the natural background wanted. Adding `Environmental` and `Noise` to the set changes nothing among the 702 (350 good either way). Counting every label, the European false positives included, would lower the good count to 330, so those stay out.
- **Anchored stretch (refinement).** The ADR picks the 10 s stretch with the highest summed target confidence, then moves its start to the first step at 0.5. A stretch with a high sum made only of steps below 0.5 could win and then fail the gate. The choice is therefore limited to stretches that contain a step at 0.5 or more, whenever the recording has one, so the shipped clip always passes the gate when the recording does.
- **The gate is on the shipped clip.** A candidate is usable when a step at 0.5 or more lies inside the clip that would ship, not merely anywhere in the first minute.
- **Re-selection that cannot run keeps the old clip.** When audio from before rule 2 is invalidated but the sources fail or the budget runs out before a replacement is chosen, the previous clip stays published (it has no scores, so the next build tries again). This is the same fallback a failed pin gets.
- **The build report** counts, under *Audio quality*, the clips ranked, how many are good and how many settled for a non-good one, the quartiles of presence, competitor and quality, and how many recordings were analysed for how many species. The contact sheet shows each clip's scores beside its player.
