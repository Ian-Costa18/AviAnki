# Photo sources: iNaturalist vs Wikimedia Commons

Research for [#14](https://github.com/Ian-Costa18/AviAnki/issues/14). Investigated against the live
iNaturalist API, the MediaWiki Action API on en.wikipedia.org and commons.wikimedia.org, and official
project documentation. All numbers below were measured, not quoted. Measurements taken 2026-08-23.

---

## Recommendation

**Wikimedia Commons is the primary photo source. iNaturalist is the fallback, and the supplier of
second and third images.**

Prefer Commons, fall back to iNat. Concretely:

1. For each species, take the **en.wikipedia lead image** (`prop=pageimages`) and resolve it on
   Commons. This is a photo for 99.1% of North American bird species, it is openly licensed 100% of
   the time, and it is a *curated* choice — it survived editorial selection on a species article.
2. Reject it and fall through to iNaturalist when it is **not a photograph** (SVG/`image/svg+xml`,
   which means a range map — 10 species in the whole NA list) or is **too small** (long side below
   800px — 8.4% of species).
3. Use iNaturalist for **image 2 and image 3** on every card, filtered to `cc0,cc-by,cc-by-sa`.
   Commons supplies one strong image per species; iNat supplies volume for variation
   (male/female/juvenile/flight).

**Neither source alone is sufficient, but for opposite reasons.** Commons has near-perfect coverage
and quality but structurally offers roughly one card-grade image per species. iNat has enormous
volume but its coverage collapses in the tail (35% of the 675 rarest NA species have **zero**
openly-licensed research-grade photos) and its quality signal does not select for identifiability.

This is the first real test of the source contract ([#20](https://github.com/Ian-Costa18/AviAnki/issues/20))
and it argues for a **ranked-preference dispatch with per-species fallthrough**, not a single
registered photo source. See [Consequences for the source contract](#consequences-for-the-source-contract).

---

## Method

Species sample: 38 North American species spanning common passerines (9), uncommon migrants (8),
raptors (7), waterfowl (7) and shorebirds (7) — listed in the [full table](#per-species-sample-38-species).

Scale sample: the full iNaturalist North America bird list, **1,665 species**, pulled from
`/v1/observations/species_counts` (place 97394 = North America, taxon 3 = Aves, research grade, with
photos). Split into a head (990 most-observed) and a tail (675 least-observed, 1–111 observations
each) so tail behaviour could be reported separately rather than averaged away.

All iNaturalist counts are scoped to **research grade, with photos, place_id=97394 (North America)**.

---

## 1. Coverage under CC0 / CC-BY / CC-BY-SA only

### Wikimedia Commons

```
GET https://en.wikipedia.org/w/api.php
    ?action=query&format=json&formatversion=2&redirects=1
    &titles=Cardinalis+cardinalis|Turdus+migratorius|...   (40 per batch)
    &prop=pageimages&piprop=original|name
```

| Population | Species | Lead image present | No article | No lead image | Lead < 800px |
|---|---|---|---|---|---|
| Head (most observed) | 990 | **990 (100.0%)** | 0 | 0 | 74 (7.5%) |
| Tail (least observed) | 675 | **674 (99.9%)** | 0 | 1 (0.1%) | 66 (9.8%) |
| **Combined** | **1,665** | **1,664 (99.94%)** | 0 | 1 | 140 (8.4%) |

The single miss is *Podilymbus gigas*, the Atitlán Grebe, extinct since 1989.

Of the 1,662 distinct lead files, **14 (0.84%) are not photographs**: 10 SVG range maps and 4
19th-century book plates. Every one belongs to a Central American endemic (Panama/Costa Rica) or an
African species recorded at a zoo — species a North American deck is unlikely to carry. Detectable
before download: SVG shows as `mime: image/svg+xml`; book plates are rarer and would need a pin.

### iNaturalist

```
GET https://api.inaturalist.org/v1/observations/species_counts
    ?place_id=97394&taxon_id=3&quality_grade=research&photos=true
    &photo_license=cc0,cc-by,cc-by-sa&per_page=500&page=1..5
```

| Open photos available | Head (990) | Tail (675) |
|---|---|---|
| ≥ 1 | 990 (100.0%) | 436 (**64.6%**) |
| ≥ 3 | 990 (100.0%) | 291 (43.1%) |
| ≥ 5 | 990 (100.0%) | 218 (32.3%) |
| ≥ 10 | 990 (100.0%) | 104 (15.4%) |
| ≥ 25 | 990 (100.0%) | 8 (1.2%) |
| ≥ 100 | 889 (89.8%) | 0 |
| **zero** | **0** | **239 (35.4%)** |

For the common half of the list iNat is abundant — every one of the 990 head species has at least 25
openly-licensed research-grade North American photos. For the tail it fails outright on more than a
third of species.

### Combined

Exactly **one species in 1,665** has neither an openly-licensed iNat photo nor a Wikipedia lead image
(*Podilymbus gigas*, extinct). Coverage of the union is complete for practical purposes.

---

## 2. Licence mix

### iNaturalist: ~10% open, and it does not vary

Measured per species across the 38-species sample. Buckets derived from three calls per species:
total, `photo_license=cc0,cc-by,cc-by-sa`, and `photo_licensed=false` (all-rights-reserved).

```
GET /v1/observations?taxon_id=9083&place_id=97394&quality_grade=research
    &photos=true&per_page=0                              -> total_results
GET ...&photo_license=cc0,cc-by,cc-by-sa                 -> open
GET ...&photo_licensed=false                             -> all rights reserved
```

Aggregate over 4,299,549 research-grade photographed NA observations across the 38 species:

| Bucket | Observations | Share |
|---|---|---|
| **CC0 / CC-BY / CC-BY-SA (usable)** | **442,515** | **10.29%** |
| CC-BY-NC / CC-BY-NC-SA / CC-BY-NC-ND / CC-BY-ND | 2,973,388 | 69.16% |
| All rights reserved (no licence set) | 883,646 | 20.55% |

Per-species open share: **min 4.2%, median 10.3%, max 13.7%**. By group — passerines 10.6%, uncommon
migrants 10.2%, raptors 9.9%, waterfowl 10.1%, shorebirds 10.3%. The ratio is flat; there is no
group where iNat is more or less open.

The cause is iNaturalist's default. Per their help centre: *"By default, all observation data, images,
and sounds posted to iNaturalist have a default license of CC BY-NC"* — non-commercial, and therefore
outside the map's CC0/CC-BY/CC-BY-SA constraint. The ~90% loss is structural and will not improve.

Note `photo_license=none` returns 0 and is **not** a way to select all-rights-reserved photos; use
`photo_licensed=false`. Sum of the licence buckets plus `photo_licensed=false` reconciles exactly to
the unfiltered total, which is how the ARR figure above was validated.

Openly-licensed photos are served from the AWS Open Data bucket
`inaturalist-open-data.s3.amazonaws.com`; `static.inaturalist.org` returns **403** for the same photo
id. Useful signal, but not a licence check — verify `license_code` on the photo object regardless.

### Wikimedia Commons: 100% open, by policy

Licence mix of all 1,662 distinct lead images, from `prop=imageinfo&iiprop=extmetadata`:

| Licence | Files | Share |
|---|---|---|
| CC BY-SA 4.0 | 533 | 32.1% |
| CC BY-SA 2.0 | 312 | 18.8% |
| CC BY 2.0 | 240 | 14.4% |
| CC BY-SA 3.0 | 208 | 12.5% |
| CC BY 4.0 | 159 | 9.6% |
| Public domain | 82 | 4.9% |
| CC BY-SA 2.5 | 39 | 2.3% |
| CC BY 3.0 | 38 | 2.3% |
| CC0 | 33 | 2.0% |
| CC BY 2.5 / CC BY-SA 1.0 / CC BY-SA 3.0-de | 9 | 0.5% |
| unparsed (`?`) | 9 | 0.5% |
| **NC or ND** | **0** | **0.0%** |

Zero non-commercial and zero no-derivatives content, which is not luck — it is
[Commons:Licensing](https://commons.wikimedia.org/wiki/Commons:Licensing) policy: *"Unless also
licensed under an acceptable free license, non-commercial and/or non-derivative content cannot be
uploaded to Wikimedia Commons."* Every Commons file is by definition inside the project's constraint.

A 50-file sample from each species' `Category:<scientific name>` (1,783 files total) came back
798 CC BY-SA, 767 CC BY, 153 PD, 63 CC0, 2 unparsed — again zero NC/ND.

The 9 unparsed cases still need handling: treat a missing or unrecognised `extmetadata.License` as a
hard reject rather than an assumption of openness.

**This is the headline asymmetry.** iNat costs a 90% discard to satisfy the licence constraint;
Commons costs nothing.

---

## 3. Quality and suitability for an ID flashcard

Judged by eye against the ticket's criterion — bird large in frame, in focus, unobstructed — on ten
species per source, chosen to include both sources' likely weak points.

### Wikimedia Commons lead images: 10/10 usable, 9/10 textbook

The en.wikipedia lead image is a genuinely curated artefact. Editors picked it to illustrate a
species article, which is very nearly the same selection problem as an ID flashcard.

- *Anas platyrhynchos* — both sexes side by side, sharp, unobstructed. Ideal.
- *Somateria mollissima* — drake filling the frame on a shell beach, clean blue background.
- *Ammospiza leconteii* — sparrow on a stem against a plain green field, every diagnostic mark legible.
- *Setophaga cerulea*, *Poecile atricapillus*, *Actitis macularius*, *Sturnus vulgaris*,
  *Oporornis agilis* — all field-guide quality.
- *Branta canadensis* — sharp flight shot; whole bird and chinstrap clear, though a standing shot
  would serve a beginner better.
- *Contopus cooperi* — the weakest: only 480×640 (below the 800px target), soft, backlit against
  white sky. Still shows the diagnostic vest and is usable.

Only 23% of lead images carry a formal Commons assessment badge (`quality` 322, `featured` 149,
`valued` 147, `potd` 35, `poty` 19; 1,281 have none), but the un-badged ones were just as good. The
lead-image selection is itself the quality signal; the Commons badges are a bonus, not the filter.

### iNaturalist top-ranked open photos: 3/10 excellent, 3/10 mediocre, 4/10 unusable

Ranked with `order_by=votes&order=desc` — the faves signal named in
[#10](https://github.com/Ian-Costa18/AviAnki/issues/10) — restricted to open licences.

Excellent: *Calidris pusilla* (textbook), *Setophaga cerulea*, *Zonotrichia albicollis*.

Mediocre: *Falco sparverius* (dramatic wings-spread action shot, but a power cable crosses the bird),
*Oporornis agilis* (half-buried in grass, legs and lower body hidden), *Contopus cooperi* (small in
frame, a branch across the body, cluttered background — worse than the Commons lead despite being
higher resolution).

Unusable:

- ***Sturnus vulgaris*** (12 faves) — a bedraggled juvenile on concrete beside a person's pink
  sneakers. An adult European Starling is glossy and spangled; this teaches the wrong bird.
- ***Somateria mollissima*** (2 faves, chosen from 2,177 open candidates) — a distant blurry
  smartphone shot of a dark duck seen from behind on a blue tarp.
- ***Branta canadensis*** (41 faves — the **highest** fave count anywhere in the sample) — two soft,
  low-contrast geese with heads down and one seen from the rear, with goslings.
- ***Anas platyrhynchos*** (3 faves) — a hen leading ten ducklings across asphalt; the adult occupies
  perhaps 4% of the frame.

**The faves signal selects for charm, not for identifiability, and at the top of the distribution it
actively anti-correlates.** The two most-faved images in the sample are among the four worst
flashcards. Ranking by votes is not a usable quality heuristic on its own.

It is also a much thinner signal than expected, because the faves live in the 90% of photos we cannot
use. Top-candidate fave counts across 38 species: median 4, max 41. For 20 of 38 species the top-8
sequence collapses to `[n, 1, 1, 1, 1, 1, 1, 1]` — beyond first place there is nothing to rank by.
*Numenius phaeopus* returned a single open candidate with 0 faves.

**Uncertainty stated plainly:** ten species per source is a small visual sample and my judgement of
"usable" is subjective. The gap is wide enough (10/10 vs 3/10) that I am confident in the direction,
but not in the precise ratio. What I am confident about is the *mechanism*: Commons lead images are
pre-selected by humans for the exact purpose we need; iNat's open subset is not selected at all, and
the signal available for selecting it rewards something else.

---

## 4. Sizes, formats, and bytes at ~800px WebP

Target: long side 800px, WebP. Measured with Pillow 12.3.0, `method=6`, over all 38 sample species.

| Source | q=75 mean / median | **q=80 mean / median** | q=85 mean / median | max (q=80) |
|---|---|---|---|---|
| Wikimedia Commons | 38.9 / 35.9 KB | **47.8 / 45.3 KB** | 59.5 / 55.6 KB | 135.6 KB |
| iNaturalist | 42.3 / 30.4 KB | **51.2 / 37.0 KB** | 63.4 / 45.9 KB | 148.0 KB |

**Both sources come in comfortably under the catalog's ~80KB per image budget** at q=80. Outliers
(busy backgrounds, fine feather detail) reach ~150KB; a per-image byte cap with a quality step-down
would cover them.

### Available sizes

**iNaturalist** serves fixed variants at `.../photos/{photo_id}/{size}.jpg`. Measured on photo
517002723 (original 2048×1152):

| variant | dimensions | bytes |
|---|---|---|
| `square` | 75×75 | 4.5 KB |
| `thumb` | 100×56 | 4.1 KB |
| `small` | 240×135 | 21 KB |
| `medium` | 500×281 | 83 KB |
| `large` | 1024×576 | 287 KB |
| `original` | 2048×1152 | 921 KB |

`large` caps the **long** side at 1024, so a portrait image arrives ~768 wide. Every one of the 38
sampled `large` fetches still had a long side ≥ 800px. Fetch `large`, downscale locally. Always JPEG.

**Wikimedia Commons has a hard constraint that changed recently and must be designed around.**
Arbitrary thumbnail widths are now rejected:

```
GET https://upload.wikimedia.org/wikipedia/commons/thumb/5/5c/<file>.jpg/800px-<file>.jpg
-> 400  "Use thumbnail sizes listed on https://w.wiki/GHai"
```

Probed 28 widths; exactly six under 4K are accepted: **120, 250, 500, 960, 1280, 1920**.
[MediaWiki: Common thumbnail sizes](https://www.mediawiki.org/wiki/Common_thumbnail_sizes) gives the
production set as `20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840` and states: *"External image
requests that go through PHP (such as InstantCommons or the imageinfo API) will be rounded up to the
closest standard size; direct requests (hotlinking) will be rejected unless they use a standard size."*
([phab:T414805](https://phabricator.wikimedia.org/T414805))

`Special:FilePath/<file>?width=800` does not error — it silently redirects to the 960px bucket. So:
**fetch the 960px bucket and downscale to 800 locally.** There is no 800px bucket and asking for one
is a 400.

Commons serves **no WebP**; `...jpg.webp` and `lossy-...jpg.webp` both 400. Conversion is local for
both sources — which is fine, the pipeline already resizes.

Formats on Commons lead images: 1,618 JPEG (97.4%), 34 PNG (2.0%), 10 SVG (0.6%). The PNGs cost
significantly more on fetch (up to 6 MB for a 960px thumb vs ~150 KB for JPEG) but convert to the same
WebP size. The SVGs are range maps and must be rejected outright.

---

## 5. Stable asset IDs

Both sources provide them, but **iNaturalist's is not independently resolvable and this constrains
the pin format**.

### Wikimedia Commons — clean

| Identifier | Example | Notes |
|---|---|---|
| Commons page id / M-id | `115093761` / `M115093761` | Numeric, immutable, survives file rename. The Structured Data entity id. |
| Canonical file title | `File:Male northern cardinal in Central Park (52612).jpg` | Human-readable; **can be renamed** by Commons admins. |
| SHA-1 | `ef3b9fe3fb51b8890484dc7e4c7675205bd9a2a7` | Content hash; changes when a new version is uploaded. |

A pinned M-id resolves directly and alone:
`https://commons.wikimedia.org/w/api.php?action=query&titles=File:...&prop=imageinfo`, or by curid
via `descriptionshorturl`. **Pin the M-id, keep the title for display, keep the sha1 to detect
re-uploads.**

### iNaturalist — needs a compound key

| Identifier | Example | Notes |
|---|---|---|
| Photo id | `517002723` | Numeric, stable, forms the media URL. |
| Observation id | `287527828` | Numeric, stable. |
| Observation UUID | `ef71a87e-...` (on `observation_photos`) | Stable. |

**There is no `/v1/photos/{id}` endpoint.** Verified: `GET https://api.inaturalist.org/v1/photos/517002723`
returns **404**, and the `inaturalist.org/photos/{id}` web page returns **403** to non-browser clients.
The only way to recover a photo's licence and attribution from an id is through its parent
observation (`GET /v1/observations?id=287527828`), which does round-trip correctly.

So an iNat pin must be **`(observation_id, photo_id)`**, not a bare photo id. A bare photo id is
enough to build the image URL but not enough to re-derive the attribution the licence requires. This
is a direct requirement on the contract from
[#10](https://github.com/Ian-Costa18/AviAnki/issues/10)'s pinning decision.

---

## 6. Attribution metadata

Both sources carry everything the map's mandatory-attribution rule needs. Commons carries it more
completely.

### Wikimedia Commons

From `prop=imageinfo&iiprop=extmetadata`, filtered with
`iiextmetadatafilter=License|LicenseShortName|LicenseUrl|UsageTerms|Artist|Credit|AttributionRequired|Restrictions|Assessments`:

| Field | Example |
|---|---|
| `Artist` | `<a href="//commons.wikimedia.org/wiki/User:Rhododendrites">Rhododendrites</a>` (HTML — strip tags) |
| `Credit` | `Own work` |
| `LicenseShortName` | `CC BY-SA 4.0` |
| `License` | `cc-by-sa-4.0` (machine-readable) |
| `LicenseUrl` | `https://creativecommons.org/licenses/by-sa/4.0` |
| `AttributionRequired` | `true` (36/38 sample) / `false` (2/38, PD and CC0) |
| `Restrictions` | empty on all 1,662 lead images checked |
| `descriptionurl` | `https://commons.wikimedia.org/wiki/File:...` — the source URL |
| `Assessments` | `quality|featured|potd` |

Gaps: `Artist` is **missing on 9 of 1,662 (0.5%)** lead images (e.g. `File:Anser erythropus.jpg`,
`File:Corvus-brachyrhynchos-001.jpg`). `License` is unparsed on 9. Both need a fallback — `Credit`,
then the uploader, then reject.

### iNaturalist

The photo object on an observation carries `id`, `license_code` (`cc-by`), `attribution`
(`"(c) Daughter Dad, some rights reserved (CC BY)"`), `original_dimensions`, and `url`. The
observation carries `user.login` (`daughterdad`), `user.name` (`Daughter Dad`), and `uri`
(the observation page, usable as the source URL).

The `attribution` string is pre-rendered and includes the author and licence, but there is **no
licence URL field** — the pipeline must map `license_code` to a CC URL itself. Author name comes from
the observation's user, not the photo, which is another reason the pin needs the observation id.

---

## A taxonomy hazard worth recording

*Numenius phaeopus* returned **24** North American research-grade photographed observations, against
22,651 globally. Cause: iNaturalist has split the Whimbrel. `Numenius hudsonicus` (taxon 1188213,
"Hudsonian Whimbrel") holds **27,517** NA records and 2,945 open ones; `Numenius phaeopus`
(taxon 3901) is now "Eurasian Whimbrel". eBird/Clements and en.wikipedia still treat
*Numenius phaeopus* as the Whimbrel covering North America.

The failure is silent: a scientific-name lookup returns a plausible-looking taxon with almost no
data, and the resulting card would carry a photo of the wrong continent's bird. **Wikipedia was
unaffected** — the redirect from *Numenius phaeopus* landed on the right article with a good lead
image.

Implication: the iNat source must resolve species through an explicit, checked-in taxon-id mapping
with a sanity threshold (flag any species whose NA observation count is implausibly low relative to
its global count), not by scientific-name search at build time. Expect more splits — this is one of
dozens across AOS/Clements/iNat.

---

## Consequences for the source contract (#20)

1. **Sources need a declared preference order per media type, and the pipeline must be able to fall
   through.** Not "which source supplies photos" but "ask Commons, then ask iNat". A boolean
   `supplies_photos` capability is not enough.
2. **A source must be able to return a candidate *and* have that candidate rejected by the pipeline.**
   The reject reasons here are generic — not a photograph, below minimum resolution, licence not in
   the allowed set, attribution incomplete — so they belong in the narrow dispatched layer, not
   inside each source.
3. **Asset ids are not uniformly a single scalar.** Commons pins as one M-id; iNat needs
   `(observation_id, photo_id)`. The contract should treat the source-native id as an **opaque
   source-specific token** the source itself can round-trip, rather than mandating an integer.
4. **Ranking logic cannot be delegated wholesale to "each source's own quality signals."**
   [#10](https://github.com/Ian-Costa18/AviAnki/issues/10) assumed those signals are good proxies for
   card quality. Commons' `Assessments` is a decent one but covers only 23% of files; iNat's faves
   are demonstrably a poor one. The realistic ranking for photos is: Commons lead image first (its
   curation *is* the signal), Commons badge as a tiebreak, iNat faves only as a weak ordering within
   the fallback pool — with pins carrying disproportionate weight, exactly as #10 anticipated.
5. **Species resolution is a source-specific concern with cross-source hazards.** The Whimbrel split
   means the contract needs a place for a source to say "I resolved this species to *this* internal
   id" so mismatches are auditable.
6. **Licence and attribution must travel as structured fields, not a rendered string.** iNat gives a
   pre-rendered `attribution` and Commons gives HTML in `Artist`; the contract should normalise both
   to `{author, licence_code, licence_url, source_url}` at the source boundary.

## Catalog budget implication (#11)

At the measured q=80 median of ~45 KB, three images per species across ~1,000 North American species
is roughly **135 MB**, comfortably inside the ~400 MB budget. Photos are not the constraint; audio
will be.

---

## Reproducing

Scripts used are not checked in (throwaway). Key calls, verbatim:

```bash
# iNat: resolve the North America place
curl 'https://api.inaturalist.org/v1/places/autocomplete?q=North%20America'      # -> 97394

# iNat: NA bird species list with open-licensed photo counts
curl 'https://api.inaturalist.org/v1/observations/species_counts?place_id=97394&taxon_id=3&quality_grade=research&photos=true&photo_license=cc0,cc-by,cc-by-sa&per_page=500&page=1'

# iNat: licence buckets for one species
curl 'https://api.inaturalist.org/v1/observations?taxon_id=9083&place_id=97394&quality_grade=research&photos=true&per_page=0'
curl 'https://api.inaturalist.org/v1/observations?taxon_id=9083&place_id=97394&quality_grade=research&photos=true&per_page=0&photo_license=cc0,cc-by,cc-by-sa'
curl 'https://api.inaturalist.org/v1/observations?taxon_id=9083&place_id=97394&quality_grade=research&photos=true&per_page=0&photo_licensed=false'

# iNat: best open candidates for a species
curl 'https://api.inaturalist.org/v1/observations?taxon_id=9083&place_id=97394&quality_grade=research&photos=true&photo_license=cc0,cc-by,cc-by-sa&order_by=votes&order=desc&per_page=8'

# Wikipedia: lead image, batched
curl 'https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2&redirects=1&titles=Cardinalis%20cardinalis&prop=pageimages&piprop=original|name'

# Commons: full metadata for a lead file
curl 'https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2&titles=File:Male%20northern%20cardinal%20in%20Central%20Park%20(52612).jpg&prop=imageinfo&iiprop=url|size|mime|sha1|extmetadata|canonicaltitle&iiurlwidth=800'

# Commons: 960px bucket (800 is a 400)
curl -L 'https://commons.wikimedia.org/wiki/Special:FilePath/Male_northern_cardinal_in_Central_Park_(52612).jpg?width=960'
```

iNaturalist throttles aggressively well below its documented 60 req/min for these count queries —
429s appeared at ~1 req/s. A ~3 s pace with exponential backoff ran clean.

---

## Sources

- iNaturalist API v1 — <https://api.inaturalist.org/v1/docs/>
- iNaturalist help, licensing defaults — <https://help.inaturalist.org/> ("By default, all observation
  data, images, and sounds posted to iNaturalist have a default license of CC BY-NC")
- iNaturalist Open Data on AWS — <https://registry.opendata.aws/inaturalist-open-data/>
- Commons:Licensing — <https://commons.wikimedia.org/wiki/Commons:Licensing>
- MediaWiki, Common thumbnail sizes — <https://www.mediawiki.org/wiki/Common_thumbnail_sizes>
- Thumbnail size restriction task — <https://phabricator.wikimedia.org/T414805>
- API:Imageinfo — <https://www.mediawiki.org/wiki/API:Imageinfo>
- API:Pageimages — <https://www.mediawiki.org/wiki/Extension:PageImages#API>

---

## Per-species sample (38 species)

`iNat NA RG` = research-grade NA observations with photos. `top faves` = fave count of the
highest-ranked openly-licensed candidate. `Commons lead px` = original dimensions of the
en.wikipedia lead image.

| Species | Group | iNat NA RG | iNat open | open % | top faves | Commons lead px | licence | Commons badge |
|---|---|---|---|---|---|---|---|---|
| *Cardinalis cardinalis*<br>Northern Cardinal | passerine-common | 340,551 | 35,068 | 10.3% | 22 | 2996x3934 | CC BY-SA 4.0 | quality + featured + potd |
| *Turdus migratorius*<br>American Robin | passerine-common | 416,575 | 42,511 | 10.2% | 11 | 3444x2584 | CC BY-SA 4.0 | quality + featured |
| *Cyanocitta cristata*<br>Blue Jay | passerine-common | 165,423 | 16,626 | 10.1% | 6 | 3319x4526 | CC BY-SA 4.0 | quality + featured + potd |
| *Poecile atricapillus*<br>Black-capped Chickadee | passerine-common | 138,382 | 18,943 | 13.7% | 8 | 1024x1024 | CC BY-SA 3.0 | - |
| *Sturnus vulgaris*<br>European Starling | passerine-common | 161,259 | 16,926 | 10.5% | 12 | 7056x4704 | CC BY-SA 4.0 | quality + valued |
| *Zonotrichia albicollis*<br>White-throated Sparrow | passerine-common | 111,027 | 12,627 | 11.4% | 6 | 2962x1974 | CC BY-SA 3.0 | quality + featured + potd |
| *Sitta carolinensis*<br>White-breasted Nuthatch | passerine-common | 103,178 | 11,413 | 11.1% | 6 | 3966x2982 | CC BY-SA 4.0 | quality + featured |
| *Agelaius phoeniceus*<br>Red-winged Blackbird | passerine-common | 276,741 | 29,665 | 10.7% | 9 | 3643x5464 | CC BY-SA 4.0 | quality |
| *Spinus tristis*<br>American Goldfinch | passerine-common | 172,997 | 16,355 | 9.5% | 4 | 3000x2422 | CC BY 2.0 | - |
| *Setophaga cerulea*<br>Cerulean Warbler | migrant-uncommon | 2,399 | 252 | 10.5% | 4 | 1024x842 | CC BY-SA 3.0 | - |
| *Setophaga striata*<br>Blackpoll Warbler | migrant-uncommon | 12,026 | 1,305 | 10.9% | 2 | 1769x1214 | CC BY-SA 3.0 | - |
| *Vermivora chrysoptera*<br>Golden-winged Warbler | migrant-uncommon | 4,025 | 383 | 9.5% | 2 | 1736x1112 | CC BY 4.0 | - |
| *Setophaga fusca*<br>Blackburnian Warbler | migrant-uncommon | 14,366 | 1,393 | 9.7% | 13 | 4901x3268 | CC BY-SA 4.0 | quality |
| *Oporornis agilis*<br>Connecticut Warbler | migrant-uncommon | 983 | 94 | 9.6% | 1 | 1593x1278 | CC BY 2.0 | - |
| *Catharus fuscescens*<br>Veery | migrant-uncommon | 9,629 | 970 | 10.1% | 6 | 3328x2773 | CC BY-SA 4.0 | quality + featured + valued |
| *Contopus cooperi*<br>Olive-sided Flycatcher | migrant-uncommon | 10,335 | 1,136 | 11.0% | 1 | 480x640 | CC BY-SA 2.0 | - |
| *Ammospiza leconteii*<br>LeConte's Sparrow | migrant-uncommon | 1,839 | 145 | 7.9% | 4 | 1400x1040 | CC BY 3.0 | - |
| *Haliaeetus leucocephalus*<br>Bald Eagle | raptor | 214,877 | 20,573 | 9.6% | 6 | 4007x3206 | CC BY 2.0 | - |
| *Buteo jamaicensis*<br>Red-tailed Hawk | raptor | 329,224 | 32,663 | 9.9% | 23 | 4426x2951 | CC BY 2.0 | quality |
| *Accipiter striatus*<br>Sharp-shinned Hawk | raptor | 22,751 | 2,128 | 9.4% | 15 | 2178x3132 | CC0 | - |
| *Falco sparverius*<br>American Kestrel | raptor | 106,298 | 11,620 | 10.9% | 20 | 1107x1383 | CC BY 2.0 | - |
| *Bubo virginianus*<br>Great Horned Owl | raptor | 74,953 | 6,094 | 8.1% | 20 | 2559x3199 | CC BY-SA 3.0 | - |
| *Circus hudsonius*<br>Northern Harrier | raptor | 56,292 | 6,764 | 12.0% | 8 | 1634x2460 | CC BY 2.0 | - |
| *Aegolius acadicus*<br>Northern Saw-whet Owl | raptor | 5,513 | 413 | 7.5% | 4 | 4695x3130 | CC BY-SA 2.0 | - |
| *Anas platyrhynchos*<br>Mallard | waterfowl | 524,049 | 50,783 | 9.7% | 3 | 2384x2384 | CC BY-SA 2.5 | valued |
| *Aix sponsa*<br>Wood Duck | waterfowl | 113,098 | 10,980 | 9.7% | 4 | 5371x3581 | CC BY-SA 4.0 | quality |
| *Branta canadensis*<br>Canada Goose | waterfowl | 395,060 | 39,134 | 9.9% | 41 | 4281x3256 | Public domain | - |
| *Bucephala albeola*<br>Bufflehead | waterfowl | 93,413 | 11,428 | 12.2% | 2 | 2749x1988 | CC BY-SA 4.0 | - |
| *Mergus merganser*<br>Common Merganser | waterfowl | 77,962 | 8,035 | 10.3% | 16 | 5517x3597 | CC BY 2.0 | - |
| *Somateria mollissima*<br>Common Eider | waterfowl | 17,718 | 2,177 | 12.3% | 2 | 6000x4000 | CC BY-SA 4.0 | quality |
| *Anas rubripes*<br>American Black Duck | waterfowl | 24,337 | 2,745 | 11.3% | 2 | 3545x2353 | CC BY-SA 4.0 | quality |
| *Charadrius vociferus*<br>Killdeer | shorebird | 139,816 | 14,394 | 10.3% | 6 | 5800x4143 | CC BY-SA 4.0 | quality + featured |
| *Actitis macularius*<br>Spotted Sandpiper | shorebird | 78,275 | 8,073 | 10.3% | 3 | 1122x840 | CC BY-SA 3.0 | - |
| *Limosa fedoa*<br>Marbled Godwit | shorebird | 27,066 | 3,186 | 11.8% | 2 | 3456x2304 | CC BY-SA 2.5 | - |
| *Calidris pusilla*<br>Semipalmated Sandpiper | shorebird | 16,440 | 1,746 | 10.6% | 3 | 3500x2333 | CC BY-SA 4.0 | quality |
| *Numenius phaeopus*<br>Whimbrel | shorebird | 24 | 1 | 4.2% | 0 | 3543x2362 | CC BY-SA 2.5 | featured |
| *Arenaria interpres*<br>Ruddy Turnstone | shorebird | 34,804 | 3,223 | 9.3% | 2 | 2838x2271 | CC BY-SA 4.0 | quality |
| *Calidris canutus*<br>Red Knot | shorebird | 5,844 | 543 | 9.3% | 2 | 4914x3276 | CC BY-SA 4.0 | quality + featured |

