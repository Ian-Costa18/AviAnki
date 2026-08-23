# Can iNaturalist carry the audio for a North American bird deck?

Research for [#13](https://github.com/Ian-Costa18/AviAnki/issues/13), under the map in
[#6](https://github.com/Ian-Costa18/AviAnki/issues/6). Investigated 2026-08-23 against the
live iNaturalist API, the official iNaturalist OpenAPI spec, the Wikimedia Commons API, and
the AWS Open Data registry. Every number below came from a call made during this
investigation; the exact calls are given inline so they can be re-run.

---

## Verdict

**Yes for coverage. No for song-versus-call.**

iNaturalist has enough openly-licensed North American bird audio to build the deck.
**904 of the 1,176 US+Canada bird species (76.9%) with a research-grade observation have at
least one CC0/CC-BY/CC-BY-SA recording**, and for the species a real regional deck actually
contains the figure is **90–96%**. That is a working source, not a marginal one.

But **the song/call distinction cannot be recovered from iNaturalist metadata.** There is no
annotation for it, observation fields are effectively unused, and only **5.3% of sound
observations carry free text that unambiguously says "song" or "call"** — with false
positives that push the true usable figure lower still. Audio→Name degrades to
*"a noise this bird makes"* on iNaturalist alone.

Three further constraints that change the build, none of them fatal:

- **`static.inaturalist.org` sends no CORS header.** A browser cannot fetch iNaturalist audio
  *bytes*. This independently confirms the build-time-pipeline decision in
  [#7](https://github.com/Ian-Costa18/AviAnki/issues/7) and rules out any live-fetch fallback.
- **The AWS Open Dataset is images only.** Audio must be fetched file by file.
- **Raw audio is unusable as-shipped** — median −36.7 LUFS across a 50-file sample, a 46 dB
  spread. Normalisation is mandatory, and it works: the same chain closes the spread to 6 dB.

Where coverage fails, it fails **by vocal behaviour, not by rarity**. Kirtland's Warbler, one
of the rarest warblers in North America, has 17 openly-licensed research-grade recordings.
Brown Pelican, with 38,232 regional observations, has **zero** — 4 sound observations exist in
all of iNaturalist, none openly licensed. The gap is pelicans, cormorants, grebes, sea ducks,
shearwaters, and non-vocal raptors.

**Wikimedia Commons is not a coverage backstop** — roughly an order of magnitude smaller, and
across 56 sampled species it closed exactly one iNaturalist gap. It is valuable for a different
reason: **79% of its free bird audio is mirrored from xeno-canto with the `XC<id>` preserved in
the filename**, and xeno-canto's API documents a `type` field that distinguishes song from
call, plus a quality grade and a duration. That is the most promising route to rescuing the
song/call distinction for the species it covers, and it needs only a build-time API key — which
the map's constraints permit. See §6.

---

## 1. Coverage

### Method

Species counts come from `GET /v1/observations/species_counts`, which returns the number of
*distinct species* matching a filter in `total_results`. Audio availability is
`sounds=true&sound_license=cc0,cc-by,cc-by-sa`, optionally with `quality_grade=research`.

**The denominator is the whole argument here.** "Bird species observed in the US" is 2,611,
but that includes every vagrant, escaped cage bird, and misidentification ever logged —
roughly double any real checklist for the region. Filtering to `quality_grade=research` gives
**1,176 species for US+Canada**, which is the order of magnitude a genuine regional checklist
has, and is the denominator used below. Quoting coverage against the unfiltered 2,611 would
understate it badly (24.4%); quoting it against a top-450 regional list would overstate it.
Both bounds are given so the reader can pick.

*(I did not verify 1,176 against the ABA Checklist from its own source. It is plausibly close,
but treat it as "iNaturalist's research-grade species list", not "the ABA area list".)*

### US + Canada, all research-grade species

```http
GET /v1/observations/species_counts?taxon_id=3&place_id=1,6712&quality_grade=research&rank=species&per_page=500
GET /v1/observations/species_counts?taxon_id=<100 ids>&sounds=true&sound_license=cc0,cc-by,cc-by-sa&quality_grade=research
```

Audio counted globally — a recording of a Blackpoll Warbler is a recording of a Blackpoll
Warbler wherever it was made.

| Species floor (research-grade obs in US+Canada) | n | ≥1 open recording | ≥3 recordings |
|---|---|---|---|
| ≥1 (everything) | 1,176 | **76.9%** | 63.9% |
| ≥10 | 987 | 82.3% | 68.9% |
| ≥50 | 873 | 86.1% | 73.2% |
| ≥100 | 813 | 87.3% | 75.6% |
| ≥500 | 677 | **90.5%** | 80.2% |
| ≥1,000 | 616 | 92.0% | 82.1% |
| ≥5,000 | 417 | 95.0% | 86.6% |

The ≥500 row (n=677) is the closest thing to "the regularly occurring avifauna a deck would
cover": **90.5%**.

### Continent-level totals

```http
GET /v1/observations/species_counts?taxon_id=3&place_id=97394&...
```

| Filter | Distinct species |
|---|---|
| Any observation | 3,777 |
| Research grade | 2,404 |
| Any sound observation | 1,702 |
| Openly-licensed sound | 1,121 |
| Openly-licensed sound + research grade | 988 |

Note the drop from 1,702 to 1,121: **roughly a third of species that have iNaturalist audio at
all have none of it openly licensed.** The licence filter is a real cost, not a formality.

### Realistic regional decks

Five regions, each the top-N bird species by research-grade observation count in that region,
checked against globally-available open + research-grade audio.

```http
GET /v1/observations/species_counts?taxon_id=3&place_id=<region>&quality_grade=research&rank=species&per_page=200&page=N
```

Place IDs: Massachusetts 2, California 14, Texas 18, Ontario 6883, Arizona 40.

| Region | top 50 | top 100 | top 200 | top 300 | top 450 |
|---|---|---|---|---|---|
| Massachusetts | 100% | 99.0% | 95.5% | 93.7% | 89.8% |
| California | 98.0% | 96.0% | 94.5% | 92.7% | 89.8% |
| Texas | 98.0% | 97.0% | 96.0% | 96.3% | 95.3% |
| Ontario | 100% | 100% | 97.0% | 94.3% | 91.1% |
| Arizona | 98.0% | 98.0% | 95.0% | 95.0% | 92.7% |

A 200-species regional deck lands at **94–97%**. A 450-species deck at **90–95%**.

### Where it falls off

Union of the five regional lists: **739 distinct species, of which 84 (11.4%) have no open
research-grade audio.**

By how commonly the species is observed:

| Regional observations | Species | Have open audio |
|---|---|---|
| <10 | 26 | 73.1% |
| 10–49 | 36 | 72.2% |
| 50–199 | 60 | 81.7% |
| 200–999 | 144 | 79.9% |
| 1k–5k | 238 | 92.0% |
| ≥5k | 235 | 96.6% |

Rarity matters, but not much — the floor is 72%, not 10%. Taxonomic order is the far stronger
signal (orders with ≥8 species in the union; ancestors read from `GET /v1/taxa/<ids>`):

| Order | Coverage | |
|---|---|---|
| Procellariiformes (shearwaters, petrels) | 7/14 | **50.0%** |
| Apodiformes (hummingbirds, swifts) | 15/21 | 71.4% |
| Suliformes (cormorants, boobies) | 9/12 | 75.0% |
| Charadriiformes (shorebirds, gulls, alcids) | 90/119 | 75.6% |
| Anseriformes (waterfowl) | 45/57 | 78.9% |
| Accipitriformes (hawks, eagles) | 20/25 | 80.0% |
| Pelecaniformes (herons, pelicans) | 17/20 | 85.0% |
| Falconiformes | 8/9 | 88.9% |
| Strigiformes (owls) | 17/19 | 89.5% |
| Galliformes | 24/26 | 92.3% |
| Piciformes (woodpeckers) | 21/22 | 95.5% |
| **Passeriformes (songbirds)** | **315/323** | **97.5%** |
| Columbiformes / Gruiformes / Caprimulgiformes / Psittaciformes | all | 100% |

**This is a behaviour gap, not a data gap.** The commonest species with no open audio at all:

| Species | Regional obs | Sound obs in all of iNat | Openly licensed |
|---|---|---|---|
| Brown Pelican | 38,232 | 4 | 0 |
| American White Pelican | 20,056 | 4 | 0 |
| Cinnamon Teal | 12,263 | 4 | 0 |
| Eared Grebe | 11,637 | 17 | 1 |
| Lesser Scaup | 7,307 | 1 | 0 |
| Black Turnstone | 7,058 | 22 | 0 |
| Clark's Grebe | 5,542 | 14 | 0 |
| Canvasback | 4,655 | 1 | 0 |
| California Condor | 4,638 | 1 | 0 |
| Snowy Owl | 3,181 | 4 | 0 |
| White-winged Scoter | 2,597 | 0 | 0 |

These are photographed constantly and recorded almost never. Licensing is not the bottleneck
for them — **the recordings do not exist**, so no licence policy and no second CC-licensed
source built on the same community will fix it.

### Curated species spread

56 species chosen across behavioural categories, each resolved by scientific name through
`GET /v1/taxa?q=<name>&rank=species` before counting (guessed taxon IDs were wrong four times
out of eight in an early pass — always resolve).

| Group | n | ≥1 open+RG | ≥10 | median recordings |
|---|---|---|---|---|
| Common passerines | 13 | 13/13 | 13/13 | 1,236 |
| Uncommon migrants / declining species | 10 | 10/10 | 10/10 | 35 |
| Raptors and owls | 6 | 6/6 | 6/6 | 204 |
| Waterfowl | 7 | 6/7 | 4/7 | 89 |
| Shorebirds | 7 | 7/7 | 5/7 | 23 |
| Other non-passerines | 6 | 6/6 | 6/6 | 223 |
| Near-silent / low-vocal | 7 | 5/7 | 1/7 | 2 |

Selected values (`open+RG`): Carolina Wren 2,040 · Northern Cardinal 2,106 · Barred Owl 1,066 ·
American Woodcock 304 · **Cerulean Warbler 97** · Golden-cheeked Warbler 62 · Bachman's
Sparrow 50 · Black-capped Vireo 37 · Bicknell's Thrush 35 · Connecticut Warbler 24 ·
Golden-winged Warbler 20 · **Kirtland's Warbler 17** · Seaside Sparrow 17 · American Goshawk 13 ·
Piping Plover 11 · Sprague's Pipit 10 · Ruddy Turnstone 6 · Semipalmated Sandpiper 4 ·
Northern Pintail 3 · Turkey Vulture 3 · Black Vulture 2 · Bufflehead 1 · Wood Stork 1 ·
Harlequin Duck 0 · American White Pelican 0 · Brown Pelican 0.

Rarity is genuinely not the problem. Behaviour is.

> **Note on a number from charting.** #13 records 2,188 openly-licensed sound observations for
> American Robin. That used `license=`, which filters the **observation's** licence, not the
> recording's. The correct filter is `sound_license=`, and it gives **1,762**. Both were
> re-run: `sounds=true` alone → 15,646; `+license=cc0,cc-by,cc-by-sa` → 2,188;
> `+sound_license=cc0,cc-by,cc-by-sa` → 1,762; `+sound_license=cc0` → 410. The conclusion is
> unchanged, but the pipeline must use `sound_license`.

---

## 2. Song versus call — the distinction is not there

This was checked against **every metadata channel iNaturalist has**, on 1,800 openly-licensed
research-grade sound observations across 9 species (200 most recent each, `order_by=id`).

### Annotations — no such controlled term exists

```http
GET /v1/controlled_terms          -> total_results: 7
GET /v1/controlled_terms/for_taxon?taxon_id=12727  -> total_results: 0
```

All seven controlled terms iNaturalist defines: Alive or Dead, Established, Life Stage, Leaves,
Evidence of Presence, Flowers and Fruits, Sex. **None describes vocalisation.** The annotations
actually present on 1,600 sampled bird sound observations were Alive (1,587), Organism (1,578),
Adult (116), Male (30) — nothing about sound.

The API does support annotation filtering (`term_id`, `term_value_id`, `without_term_id`,
`annotation_user_id` are all in the spec), so the *mechanism* is there. There is simply no term
to filter on. Should iNaturalist ever add a vocalisation term, this becomes a one-parameter
change — worth designing the source adapter so that it can.

### Observation fields — technically possible, practically unused

`GET https://www.inaturalist.org/observation_fields.json?q=vocaliz` shows the fields exist:
`Vocalizing` (id 590, 6,346 values site-wide, all taxa), `Vocalizing Behavior` (id 3051, 242),
`Vocalization` (id 9126, 34). But across 1,600 sampled bird sound observations there were 34
distinct observation fields and **exactly four** vocalisation-related values in total
(`Singing = Yes`, `Vocalizing = yes`, `Vocalizing Behavior = Yes`, one habitat note). And note
what those fields record: *whether* the bird vocalised, not *which* vocalisation.

### Tags — 3% of observations have any tag at all

48 of 1,600 observations carried a tag. Across all of them: `song` ×2, `call` ×2,
`vocalizing` ×2, `vocalization` ×2. The commonest tag was `audio` (×22).

### Description free text — 5.3%, and soft even then

| | count | share |
|---|---|---|
| No free text at all | 1,063 | 59.1% |
| Free text, no vocalisation word | 638 | 35.4% |
| "call" only | 81 | 4.5% |
| "song" only | 15 | 0.8% |
| mentions both | 3 | 0.2% |
| **Unambiguous song-or-call** | **96** | **5.3%** |

A naive keyword match returns 16.2%, and **that number is wrong**. Spot-checking Barred Owl
matches showed 93 of 200 hits came from the phrase *"Audio from Wildlife Acoustics **Song**
Meter Micro 2"* — a recorder brand name. Removing brand-name false positives drops it to 5.3%.
This is exactly the kind of claim that would have survived into a design decision unchallenged.

Even the surviving 5.3% is soft. Real examples pulled from the sample:

- obs 355313120 — *"Louder bird. Junco singing in background"* — the vocalisation word refers
  to a **different species** than the observation's taxon.
- obs 357025685 — *"I think this is the bird I heard calling way up in a tree"* — "calling" as
  an everyday verb, not the technical song/call contrast.
- obs 347557088 — *"High-pitched call; repeats 4 times in this clip."* — genuinely usable.

Per species (out of 200 each), song-labelled / call-labelled: Red-tailed Hawk 0/21 ·
Mallard 2/23 · Blue Jay 0/8 · Killdeer 0/8 · Song Sparrow 6/2 · Barred Owl 1/7 ·
Northern Cardinal 2/6 · American Robin 3/4 · Carolina Wren 1/2. Several species have **zero**
song-labelled recordings in 200 — there is not enough signal to fill one card, let alone rank.

### What this means for the card types

Under [#9](https://github.com/Ian-Costa18/AviAnki/issues/9), Audio→Name is a chosen card type.
On iNaturalist alone it can only mean *"a noise this bird makes."* Three options, in order of
what the evidence supports:

1. **Accept the degradation.** Ship Audio→Name unlabelled. Honest, and still pedagogically
   useful — recognising a species from any vocalisation is a real skill.
2. **Get the label from a source that records it.** xeno-canto documents an explicit `type`
   field ("predefined terms such as 'call' or 'song'"). Its CC-BY/CC-BY-SA subset is mirrored
   on Commons, and those mirrors keep the `XC<id>` in the filename — so the label is one keyed
   lookup away. This covers only the species that have Commons mirrors (35 of the 56 sampled),
   so it yields a **partially** labelled deck, not a fully labelled one. See §6.
3. **Classify the audio.** Out of scope per #6 (BirdNET / signal analysis is explicitly ruled
   out of this spec).

**This is a decision the map owes an answer to, and it does not currently have one.** It is the
one place where this research changes the plan rather than confirming it.

---

## 3. Quality signals

From a full observation record (`GET /v1/observations?taxon_id=12727&sounds=true&sound_license=cc0&order_by=votes`):

**Available and useful for ranking:**

| Field | Use |
|---|---|
| `quality_grade` | `research` = community-confirmed ID. The single strongest filter. Costs ~10% of records (1,121 → 988 species at continent level). |
| `num_identification_agreements` / `num_identification_disagreements` | ID confidence beyond the binary quality grade. Median 1 agreement; **474/1,600 have ≥2**, 131 have none. Usable. |
| `identifications_count`, `identifications_most_agree`, `community_taxon_id` | Corroborate the species is what the deck says it is. |
| `captive` | Must be excluded — a zoo recording is not the wild vocalisation. |
| `user.observations_count` / `user.species_count` | Observer experience as a weak prior. |
| `sounds[].license_code`, `sounds[].attribution` | Required for the attribution constraint. `attribution` arrives pre-formatted, e.g. `"(c) Mila C., some rights reserved (CC BY)"`. |
| `order_by=random` | Supported. Useful for unbiased sampling during catalog QA. |

**Present but useless — `faves_count`.** This looked like the obvious quality signal and it is
not one. Across 1,600 sound observations fetched with `order_by=votes&order=desc` — that is,
the *most-faved end of the distribution* — **1,543 had zero faves, 57 had exactly one or two,
and none had three or more.** Birders fave photographs, not recordings. Do not build a ranking
on it.

**Not available, and this matters.** The `Sound` definition in the OpenAPI spec has exactly
eight properties — `id, attribution, license_code, file_url, file_content_type, flags, hidden,
moderator_actions` — and live responses add only `native_sound_id`, `secret_token`,
`play_local` and `subtype`. There is **no duration, no bitrate, no sample rate, no file size,
and no quality metric of any kind**, at the spec level or in practice. `subject_type` is `null`
on all 1,709 sounds sampled. There is also **no sound-specific endpoint** — no path in the spec
contains "sound"; audio is only ever reachable nested inside an observation.

Consequence: **the pipeline cannot rank on recording quality without downloading the file.**
Any duration- or loudness-based heuristic is a post-download filter, not a pre-download one.
That is affordable at ~1,200 species but it shapes the pipeline's structure — fetch a
candidate set per species, measure, then choose.

---

## 4. Practical quality

> **Stated limitation.** I could not listen to these recordings. Everything below is objective
> measurement via `ffprobe` and `ffmpeg` filters on 50 downloaded files (5 species × top-faved
> and most-recent, to avoid fave bias). **"How often is the bird audible over wind, traffic and
> human speech" is the one sub-question of #13 this research does not answer**, and it needs a
> human with headphones. What follows bounds the problem; it does not close it.

### Loudness — uniformly too quiet, and fixable

`ffmpeg -i <file> -af ebur128=peak=true -f null -`

| | median | p10 | p90 | min | max |
|---|---|---|---|---|---|
| Integrated loudness (LUFS) | **−36.7** | −50.1 | −20.6 | −60.1 | −13.8 |

Broadcast targets are −16 to −23 LUFS. **29 of 50 files are below −35 LUFS; 14 are below −45.**
The 46 dB spread is the bigger problem — an unnormalised deck would have the user reaching for
the volume knob on every card.

This is entirely fixable. Applying `highpass=f=250,loudnorm=I=-18:TP=-1.5:LRA=11`:

| | before | after |
|---|---|---|
| Median | −36.7 LUFS | −18.9 LUFS |
| Spread (max − min) | 46.3 dB | **6.1 dB** |
| Below −30 LUFS | 29/50 | **0/50** |

**Normalisation is not optional and must be part of the build pipeline.**

### Noise — indicative, not conclusive

As a crude proxy I compared energy in the 1.5–8 kHz band (where most passerine song sits)
against energy below 400 Hz (wind, traffic, handling noise):

- All 50 files: median **−1.6 dB** — bird band *quieter* than the rumble band. 29/50
  rumble-dominated.
- Restricted to the 30 high-frequency singers (American Robin, Northern Cardinal, Song
  Sparrow), where the proxy is most valid: median −2.4 dB, **17/30 rumble-dominated**, 23/30
  with under 6 dB of margin.

**Treat this as a caution flag, not a measurement.** The proxy is invalid for low-frequency
species — a Barred Owl hoots at 300–800 Hz, so it *should* read as "rumble-dominated." Even
for the high-frequency subset it cannot separate wind from a passing truck from a genuinely
distant bird. What it does establish is that a 250 Hz high-pass is clearly worth applying, and
that a meaningful fraction of recordings carry substantial low-frequency energy that is not
the bird. Observers say so themselves — obs 378536994: *"Somewhat difficult to hear over the
traffic noise on route 350."*

---

## 5. Formats and catalog size

`file_content_type` across 1,709 openly-licensed sounds:

| Type | Count | Share |
|---|---|---|
| `audio/mp4` (m4a/AAC) | 727 | 42.5% |
| `audio/x-wav` | 712 | 41.7% |
| `audio/mpeg` (mp3) | 269 | 15.7% |

Codecs actually found by `ffprobe` on the 50-file download: `aac`, `mp3`, `pcm_s16le`,
`pcm_s24le`, `pcm_f32le`. Sample rates 44.1 kHz (24), 48 kHz (22), 24 kHz (3), 32 kHz (1).
Mono and stereo both common.

**Transcoding is mandatory** — 42% of the corpus is uncompressed WAV, and `.m4a` playback
across Anki desktop, AnkiDroid and AnkiMobile is not something to gamble a deck on. `.mp3` is
the safe target, and `media.trim_to_mp3()` already exists in the CLI for exactly this.

Duration, from `ffprobe` on the 50-file sample:

| min | p25 | median | p75 | p90 | max |
|---|---|---|---|---|---|
| 3.1 s | 7.0 s | **11.4 s** | 19.7 s | 47.7 s | 216 s |

3/50 exceed 60 s, 1/50 exceeds 120 s. Source files: median 0.41 MB, mean 0.94 MB, max 5.97 MB.

**Card-ready output** — 10 s, mono, 44.1 kHz, 96 kbps mp3, after high-pass and loudnorm:

| Median | Mean | Max |
|---|---|---|
| 117 KB | 98 KB | 144 KB |

| Catalog | Size |
|---|---|
| 1 clip × 700 species | **~70 MB** |
| 2 clips × 700 species | **~140 MB** |

Comfortably inside the ~400 MB budget from
[#11](https://github.com/Ian-Costa18/AviAnki/issues/11), leaving room for images.

---

## 6. Wikimedia Commons as a second source

**Verdict: not a coverage backstop, but the key to the song/call problem.**

### Method, and a correction

Commons was measured two ways for the same 56 species, because the first method under-reported:

1. **Category** — `Category:Audio files of <scientific name>`, a real Commons convention,
   following one level of subcategories.
2. **Title search** — `intitle:"<term>" filemime:audio` for both scientific and common name.

They disagree. Northern Cardinal has **no** `Audio files of…` category yet has 6 audio files
findable by title; American Robin gives 14 by category and 15 by title. Neither method alone is
trustworthy; the numbers below take the **larger of the two per species**, so they are lower
bounds.

```http
GET https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2
    &list=categorymembers&cmtitle=Category:Audio files of Turdus migratorius&cmlimit=500
GET https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2
    &generator=search&gsrsearch=intitle:"Turdus migratorius" filemime:audio&gsrnamespace=6
    &prop=imageinfo&iiprop=url|mime|size|extmetadata&iiextmetadatafilter=LicenseShortName|Artist|Credit
```

> **Wikimedia rate-limits harder than iNaturalist.** Several queries returned **HTTP 429**
> ("You are making too many requests to the API"). An early helper checked only the exit code
> and the JSON parse, so 429 bodies were silently treated as "no results" — the same class of
> mistake as the TLS failure in §"Reproducing this". Any Commons client in the pipeline must
> **check the HTTP status and honour `Retry-After`.** The counts below are lower bounds partly
> for this reason.

### Coverage — thin, and it does not fill the gaps that matter

| | of 56 species |
|---|---|
| ≥1 freely-licensed audio file | 35 (62.5%) |
| ≥2 | 27 (48.2%) |
| ≥5 | 13 (23.2%) |
| Total freely-licensed files found | 160 |

Compare iNaturalist on the same 56 species: **54/56 have ≥1** openly-licensed research-grade
recording, most of them with hundreds. Commons is roughly an order of magnitude smaller.

More importantly, **Commons does not cover where iNaturalist fails.** Across all 56 species it
closed exactly **one** gap:

| Species | iNat open+RG | Commons free |
|---|---|---|
| American White Pelican | 0 | **2** |
| Northern Pintail | 3 | 2 |
| Turkey Vulture | 3 | 1 |
| Black Vulture | 2 | 1 |
| Harlequin Duck | 0 | 0 |
| Brown Pelican | 0 | 0 |

The two species with nothing anywhere stay at nothing. This is the expected result given §1 —
the missing recordings are of birds that are *rarely recorded by anyone*, and Commons draws on
the same volunteer pool.

### Licensing — everything found was usable, by construction

| Licence | Files |
|---|---|
| CC BY-SA 4.0 | 77 |
| CC BY-SA 3.0 | 71 |
| Public domain | 5 |
| CC0 | 3 |
| CC BY 4.0 | 2 |

**158 of 158 sampled files were freely licensed.** That is not a quality finding — Commons
only accepts free content, so it is definitional. What *is* notable: **93.7% is CC-BY-SA
(share-alike)**, the inverse of iNaturalist's CC-BY-dominated mix. If share-alike ever turns
out to be awkward for redistributing a `.apkg`, dropping it costs iNaturalist 3.6% of its
corpus but costs Commons almost all of it.

Formats: 140 mp3, 18 wav. Mp3-dominant, so lighter transcoding than iNaturalist.

### Song vs call — not in the filenames, but one lookup away

Filename labelling is as bad as iNaturalist's free text: **2/56 species had a
filename-labelled song, 2/56 a labelled call, and 0/56 had both.** Commons filenames do not
solve the problem directly.

**But 126 of the 160 freely-licensed files (79%) are xeno-canto mirrors**, and they preserve
the xeno-canto identifier in both the filename and the `Credit` metadata:

```text
File:Turdus migratorius - American Robin XC254484.mp3
  LicenseShortName: CC BY-SA 4.0
  Credit: Metadata: https://www.xeno-canto.org/254484
```

And xeno-canto records exactly what iNaturalist does not. From its own API documentation
(`GET https://xeno-canto.org/explore/api`):

> `type` : the sound type of the recording (combining both predefined terms such as 'call' or
> 'song' and additional free text options)

The same response also carries **`q`** (a human-assigned recording quality grade A–E) and
**`length`** (duration, e.g. `"4:08"`) — the two ranking signals §3 found missing from
iNaturalist.

The catch, verified live rather than assumed:

```
GET https://xeno-canto.org/api/2/recordings?query=nr:384609  -> 404
    "Xeno-canto API v2 is no longer available."
GET https://xeno-canto.org/api/3/recordings?query=nr:384609  -> 401
    "Missing or invalid 'key' parameter."
```

v2 is dead; v3 needs a key. **This does not conflict with the map's constraints.** #6 forbids
*shipping keys to the browser* and *asking users to obtain their own*. A key held as a GitHub
Actions secret in the build pipeline breaks neither rule — the browser only ever sees the
published catalog. xeno-canto's own docs note that "every XC member with a verified email
address already has one."

Note also that xeno-canto's own licence mix is mostly CC-BY-NC-* (the documented example shows
`by-nc-sa/4.0`), which the map excludes. That is precisely why the Commons subset matters: the
files that reached Commons are the CC-BY / CC-BY-SA ones, already filtered for us.

### A concrete path for the song/call problem

The evidence supports this shape, though it is a proposal and not a tested pipeline:

1. Take audio from **iNaturalist** for coverage (54/56 species, hundreds of candidates each).
2. Take **Commons xeno-canto mirrors** where they exist (35/56 species) — already free,
   mp3, and keyless to download.
3. For a Commons file whose name carries `XC<id>`, query **xeno-canto v3 by that id** with a
   build-time key to recover `type`, `q` and `length`.
4. Where `type` resolves to song or call, the Audio→Name card keeps its meaning. Where it does
   not, the card falls back to "any vocalisation."

This produces a *partially* labelled deck — roughly the 62.5% of species with any Commons
audio, minus those whose XC lookup fails — not a fully labelled one. **It does not rescue
song-vs-call across the whole deck**, and the map should decide whether a partially labelled
card type is acceptable or whether Audio→Name simply means "any vocalisation" everywhere.

### One trap worth naming

Commons audio search returns **Lingua Libre pronunciation recordings** — a human saying the
species' English name:

```text
File:LL-Q1860 (eng)-Vealhurl-American robin.wav   CC BY-SA 4.0
File:LL-Q1860 (eng)-Vealhurl-song sparrow.wav     CC BY-SA 4.0
```

These are correctly licensed, correctly named, correctly categorised — and would be catastrophic
on an Audio→Name card. Any Commons ingestion must exclude the `LL-` prefix and, more generally,
should not treat "the filename contains the species name" as sufficient evidence that the file
contains the bird.

---

## 7. Delivery, licensing and rate limits

### CORS — the finding that constrains the architecture

Checked with `curl -I -H "Origin: https://ian-costa18.github.io"`:

| Host | `Access-Control-Allow-Origin` |
|---|---|
| `api.inaturalist.org` | `*` |
| **`static.inaturalist.org`** (audio bytes) | **absent** |
| `commons.wikimedia.org/w/api.php` | `*` |
| `upload.wikimedia.org` (media bytes) | `*` |

Full response headers from `https://static.inaturalist.org/sounds/1414892.m4a` are
`content-type`, `content-length`, `date`, `last-modified`, `etag`,
`x-amz-server-side-encryption`, `accept-ranges`, `server`, `x-cache`, `via`, `x-amz-cf-pop`,
`x-amz-cf-id` — no CORS header of any kind.

**A browser can *play* iNaturalist audio via `<audio src>`, but cannot read the bytes to pack
into an `.apkg`.** This is independent confirmation of
[#7](https://github.com/Ian-Costa18/AviAnki/issues/7) and forecloses any live-fetch fallback
for iNaturalist audio. Wikimedia's media host, by contrast, *is* fetchable from the browser —
worth knowing, though it does not change the build-time-pipeline decision.

### No bulk audio export

The OpenAPI description points at the
[iNaturalist AWS Open Dataset](https://registry.opendata.aws/inaturalist-open-data/) for bulk
access, and notes that open-licensed media lives on `inaturalist-open-data.s3.amazonaws.com`.
That applies to **photos only**. The registry entry
([`open-data-registry/datasets/inaturalist-open-data.yaml`](https://github.com/awslabs/open-data-registry/blob/main/datasets/inaturalist-open-data.yaml))
is titled *"iNaturalist Licensed Observation **Images**"* and describes its resource as
*"Image files (e.g. JPEG)."*

Empirically, **all 1,708 sound URLs sampled were on `static.inaturalist.org`** — none on the
open-data bucket, including CC0 ones. Audio must be fetched one HTTP request at a time.

### Rate limits and terms

From the OpenAPI description (`GET /v1/swagger.json`, spec version 1.3.0):

> "we throttle API usage to a max of 100 requests per minute, though we ask that you try to
> keep it to 60 requests per minute or lower, and to keep under 10,000 requests per day."

> "The API is intended to support application development, **not data scraping**."

A full catalog build for ~1,200 species needs roughly 2–4 metadata calls per species plus one
media download per selected clip. That is a few thousand API calls — inside the daily budget,
but only just, and only if the build is incremental and cached. **The pipeline should
checkpoint and resume, not rebuild from scratch nightly.** Media downloads go to
`static.inaturalist.org`, a different host, so they should not count against the API budget —
but they are still traffic, and a considerate `User-Agent` identifying the project is the
minimum courtesy.

### Licence semantics — a trap to avoid

The spec defines `sound_license` as:

> "Must have at least one sound with this license"

This is an **observation-level** filter. An observation returned by
`sound_license=cc0,cc-by,cc-by-sa` may still contain additional sounds that are all-rights-
reserved. **94 of 1,600 sampled observations carried more than one sound**, so the case is not
hypothetical. In practice no mixed observation turned up — all 1,709 sounds inside openly-
filtered results were themselves open (cc-by 1,148 / cc0 499 / cc-by-sa 62) — but the contract
does not guarantee it. **The pipeline must re-check `sounds[].license_code` on each individual
sound before using it.**

Licence mix among openly-licensed sounds: **CC-BY 67.2%, CC0 29.2%, CC-BY-SA 3.6%.** CC-BY
dominates, so attribution is required for roughly two-thirds of the catalog — consistent with
the mandatory-attribution constraint in #6. `sounds[].attribution` supplies a ready-made
string. CC-BY-SA is a small enough slice (3.6%) that excluding it, if share-alike turns out to
be awkward for deck redistribution, would cost very little.

---

## 8. What this means for the map

**Confirmed:**

- iNaturalist is a viable primary audio source for North America. Register it.
- The build-time pipeline ([#7](https://github.com/Ian-Costa18/AviAnki/issues/7)) is
  necessary, not merely convenient — no CORS on the audio host.
- The ~400 MB budget ([#11](https://github.com/Ian-Costa18/AviAnki/issues/11)) holds with
  large margin: ~70–140 MB of audio.
- Stable source-native IDs required by
  [#10](https://github.com/Ian-Costa18/AviAnki/issues/10) exist: observation `id` and
  `sounds[].id` are both stable and citable.

**Newly constrained:**

- **Ranking heuristics must be split in two** — metadata pre-filters (`quality_grade`,
  `captive`, ID agreement) narrow the candidate set; measured filters (duration, loudness) can
  only be applied after download, because the API exposes no audio properties at all.
  **`faves_count` is not usable** — 1,543 of 1,600 recordings have zero faves.
- **Normalisation and transcoding are pipeline requirements**, not polish. −36.7 LUFS median,
  42% WAV.
- **The build must be incremental**, to stay inside 10,000 requests/day. A Commons client must
  additionally handle HTTP 429 and `Retry-After`.
- **`sound_license`, not `license`** — and re-check each sound's own `license_code`, since 94
  of 1,600 observations carry more than one sound.
- **Commons is a labelling source, not a coverage source.** Register it for the xeno-canto
  mirrors and their `XC<id>`, not to fill species gaps.

**Open, and owed a decision:**

- **Does Audio→Name keep the song/call distinction?** iNaturalist cannot supply it (5.3%, and
  soft). Commons filenames cannot either (3.6%). The xeno-canto route in §6 could label the
  ~62% of species with Commons mirrors, at the cost of a build-time API key and a third source.
  The choice is: accept "any vocalisation" everywhere and amend
  [#9](https://github.com/Ian-Costa18/AviAnki/issues/9), or accept a **partially** labelled
  deck. Both are defensible; neither is free.
- **Is a build-time-only API key acceptable?** #6 forbids keys in the browser and forbids
  asking users for their own. A GitHub Actions secret violates neither, but the map does not
  say so explicitly, and this decision unlocks xeno-canto's `type`, `q` and `length` fields.
- **How does the deck handle the ~10% of regional species with no audio?** Omit the card, omit
  the species, or fall back to a photo-only card. This interacts with #9 and #10. Note that
  these are disproportionately the seabirds and waterfowl a coastal user would most expect.
- **Someone must listen.** The practical-quality question is unanswered — I could not audition
  the audio. A human should audit ~30 clips chosen by the proposed heuristic before the ranking
  is fixed in the spec.

---

## Reproducing this

All measurements were made 2026-08-23 against the live APIs, keyless. Counts drift as
observations are added — expect them to rise. Base URL `https://api.inaturalist.org/v1/`.

Species counts:

```http
GET /observations/species_counts?taxon_id=3&place_id=1,6712&quality_grade=research&rank=species&per_page=500
GET /observations/species_counts?taxon_id=<ids>&sounds=true&sound_license=cc0,cc-by,cc-by-sa&quality_grade=research
```

Per-species availability:

```http
GET /observations?taxon_id=12727&sounds=true&sound_license=cc0,cc-by,cc-by-sa&quality_grade=research&per_page=0
```

Metadata channels:

```http
GET /controlled_terms
GET /controlled_terms/for_taxon?taxon_id=12727
GET /observations?taxon_id=<id>&sounds=true&sound_license=cc0,cc-by,cc-by-sa&quality_grade=research&per_page=100&order_by=id&order=desc
GET https://www.inaturalist.org/observation_fields.json?q=vocaliz
```

Spec and terms: `GET /swagger.json`.

**Four errors worth recording, because each produced a confident wrong answer before being
caught. Anyone re-running this should expect the same traps:**

1. **Guessed taxon IDs.** Wrong for 4 of 8 species (Song Sparrow is 9100, not 9135); the bad
   ones returned `HTTP 422`. **Always resolve via
   `GET /taxa?q=<scientific name>&rank=species` and match on exact `name`.**
2. **A fetch helper that swallowed exceptions.** A Commons client using Python's `urllib`
   failed TLS verification in this environment (expired root in the bundled CA store) and
   returned `{}` on error, reporting **zero Commons audio for every species** — a completely
   plausible-looking result that was entirely an artefact. Re-run through `curl` it produced
   real data. Later, the same swallow-and-continue pattern hid **HTTP 429** rate limiting.
   **Never let a fetch helper return an empty result on exception.**
3. **A keyword match with an unexamined false positive.** "Song" matched *"Wildlife Acoustics
   **Song** Meter Micro 2"*, a recorder brand, inflating song/call recoverability from 5.3% to
   16.2% — a threefold error in the number that decides a card type. **Read the matched strings
   before trusting the count.**
4. **Trusting one method for a coverage claim.** The Commons `Category:Audio files of…`
   convention is real but incomplete — Northern Cardinal has none, yet has 6 audio files. A
   single-method measurement would have reported a false zero. **Cross-check coverage claims
   with an independent query path.**
