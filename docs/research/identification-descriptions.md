# Is there a usable identification-description source?

Research for [#15](https://github.com/Ian-Costa18/AviAnki/issues/15). Feeds the decision in
[#25](https://github.com/Ian-Costa18/AviAnki/issues/25). Investigated 2026-08-23.

## Verdict

**Yes, conditionally — and the only candidate that works is Wikipedia's `== Description ==`
section, not the lead.** It is genuinely identification-focused prose for roughly three
North American species in four, it is CC BY-SA 4.0, and it is available through a stable,
key-free, rate-friendly API. It is not free: it needs a sentence filter, a rewritten
redactor, and an accepted per-species failure mode.

Three things are settled negatives:

- **Composing prose from structured trait data is dead.** No open dataset records which
  body part is which colour. AVONET (CC BY 4.0, all 11,009 species) has 37 columns and not
  one of them is a colour. Wikidata has a colour statement for **13 of 23,067** bird
  species. There is nothing to compose from.
- **Every other text aggregator is a Wikipedia mirror, a taxonomy stub, or unreachable.**
  GBIF, Wikispecies, EOL, and iNaturalist were all checked and all fail.
- **Public-domain field guides read beautifully and cannot be plumbed.** Reed's 1906–1913
  guides are exactly the right register, but they cover about a third of the modern list
  under 1910 AOU names, 44% of their accounts barely describe the bird at all (the facing
  colour plate did that job), and the text is OCR.

The residual risk is not licensing and not coverage. It is that **redaction and
identification pull in opposite directions for the 29% of North American species with a
colour word in their name**, and no amount of engineering fixes that.

---

## Method

Two samples, both fetched live from the MediaWiki API (`action=query&prop=extracts&explaintext=1`):

1. **40 hand-picked common North American species** — read by hand, to calibrate what the
   prose actually reads like.
2. **150 species drawn at random (seed 1729) from a 1,433-species North American list** —
   the union of the eBird `spplist` for `US` and `CA`, intersected with the eBird taxonomy
   at `category=species`. This is the unbiased sample; all percentages below come from it.

All 150 resolved to an English Wikipedia article. 5 of the 150 could not be confirmed as
the right article (the scientific name did not appear in the lead), so treat the coverage
figures as having roughly ±3% of slop.

Other sources were probed directly with `curl` against their public APIs.

---

## Wikipedia's Description section

### Availability

| | count | share |
|---|---|---|
| resolved to an enwiki article | 150 / 150 | 100% |
| has a `== Description ==`-class level-2 section | **129 / 150** | **86%** |
| has ≥ 200 characters of colour-bearing prose in it | **120 / 150** | **80%** |

Heading names are almost perfectly uniform: `Description` × 127, `Description and
taxonomy` × 1, `Appearance` × 1. **This is the single most encouraging result in the
study** — a one-line heading match extracts the right section for essentially every
article that has one. It does not need a parser, only a level-aware section splitter that
keeps nested subsections (a naive splitter drops the body of articles like Golden Eagle
and Pink-footed Shearwater, whose Description opens straight into a `=== Plumage ===`
subsection).

The 21 species with no Description section are a mix of genuinely obscure vagrants and
exotics (Golden Palm Weaver, Cut-throat, House Crow, Siberian House-Martin) and a
disconcerting number of ordinary North American birds:

> Sora, White Ibis, Merlin, Inca Dove, Dusky Flycatcher, Bachman's Sparrow,
> Scripps's Murrelet, Northern Beardless-Tyrannulet, Gray-headed Chickadee

There is no fallback for these. The lead is taxonomic and the article has no other
descriptive section. **They need an explicit "no description card for this species" rule.**

### Is the prose actually identification-useful?

Mostly, once you filter it. Two structural problems:

**1. It opens with measurements, not appearance.** Across all 129 Description sections,
**419 of 1,780 sentences (24%) are pure measurement** with no appearance content —
wing chord, culmen, tarsus, body mass, regional weight averages. The American robin's
Description spends its first three sentences on this before reaching anything a birder
could use:

> The eastern subspecies (T. m. migratorius) is 23 to 28 cm (9.1 to 11.0 in) long with a
> wingspan ranging from 31 to 41 cm (12 to 16 in) [...] Among standard measurements, the
> wing chord is 11.5 to 14.5 cm (4.5 to 5.7 in), the culmen is 1.8 to 2.2 cm (0.71 to
> 0.87 in) and the tarsus is 2.9 to 3.3 cm (1.1 to 1.3 in). **The head varies from jet
> black to gray, with white eye arcs and white supercilia. The throat is white with black
> streaks [...] The adult has a brown back and a reddish-orange breast, varying from a
> rich red maroon to peachy orange.**

The bolded half is exactly what the card wants. A sentence-level filter — keep sentences
containing a colour or pattern word, drop the rest — recovers it cleanly, and that is what
the samples below use.

**2. Some Description sections contain no appearance content at all.** The Northern
Cardinal's entire Description is 485 characters and never mentions the colour red:

> The northern cardinal is a mid-sized songbird with a body length of 21–23.5 cm
> (8.3–9.3 in) and a wingspan of 25–31 cm (9.8–12.2 in). The adult weighs from 33.6–65 g
> (1.19–2.29 oz), with an average 44.8 g (1.58 oz). The male averages slightly larger than
> the female.

The Eastern Bluebird's is 393 characters and never says it is blue. The Wood Duck —
described in its own lead as "one of the most colorful North American waterfowls" — gets
measurements and a comparison to a mallard. The Osprey's opens on the shape of its toes
and the reticulation of its tarsi. Tufted Titmouse, Nelson's Sparrow, and Eastern Phoebe
have Descriptions that are nothing but a flattened infobox measurement table rendered as
`Measurements:` followed by a list.

Distribution of usable prose per species, over the 150-species sample:

| ID prose extracted | species | share |
|---|---|---|
| no Description section | 21 | 14% |
| section present, < 200 chars usable | 9 | 6% |
| 200–400 chars | 37 | 25% |
| 400+ chars | 83 | 55% |

**Read that as: about 55% are comfortably good, 25% are usable but thin, and 20% fail.**

### What the finished card would say

End-to-end output — Description section, sentence-filtered, redacted with the improved
redactor described below:

> **Peregrine Falcon** — The back and the long pointed wings of the adult are usually
> bluish black to slate grey with indistinct darker barring; the wingtips are black. The
> white to rusty underparts are barred with thin clean bands of dark brown or black. The
> tail, coloured like the back but with thin clean bars, is long, narrow, and rounded at
> the end with a black tip and a white band at the very end. The top of the head and a
> "moustache" along the cheeks are black, contrasting sharply with the pale sides of the
> neck and white throat.

> **King Eider** — The male is unmistakable with its mostly black body, buff-tinged white
> breast and multicoloured head. The head, nape and neck are a pale bluish grey. The cheek
> is pale green. The bill, separated from the face by a thin black line, is red with a
> white nail and a large, distinctive yellow knob.

> **Stilt Sandpiper** — The [redacted] resembles the curlew [redacted] in its long bill,
> long neck, pale supercilium and white rump. It is readily distinguished from that
> species by its straighter bill, its longer and greenish-yellow (not black) legs, and in
> flight, by the lack of a wingbar. Breeding adults are distinctive, heavily barred with
> blackish bars on a white background beneath, and with reddish-orange patches above and
> below the white supercilium.

These are good cards. Now the failures:

> **Wilson's Snipe** — They have short greenish-grey legs and a very long straight dark
> bill. The body is mottled brown on top and pale underneath.

Thin, but honest. And the one that cannot be salvaged:

> **Mangrove Yellow Warbler** — Apart from the rufous hood of the male, all subspecies are
> very similar. Females and immature birds have similarly greenish-[redacted] uppersides
> and are a duller [redacted] below. In all, the remiges and rectrices are blackish olive
> with [redacted] edges.

### Licence

Confirmed live from `api.wikimedia.org/core/v1/wikipedia/en/page/{title}/bare`:

```
license: Creative Commons Attribution-Share Alike 4.0
url:     https://creativecommons.org/licenses/by-sa/4.0/deed.en
```

CC BY-SA 4.0 is inside the map's stated `CC0 / CC-BY / CC-BY-SA` envelope, so this is
permitted. Two consequences worth naming rather than discovering later:

- **Attribution must reach the card**, same as media. Article title plus a link is the
  normal form.
- **Share-alike is viral over the field.** A deck containing CC BY-SA description text is
  itself a derivative and has to be redistributable on the same terms. That is very likely
  fine for a project whose whole point is shareable decks, but it is a constraint the
  photo/audio sources (which can be CC0 or CC BY) do not impose, and it should be a
  conscious choice rather than a side effect.

---

## Redaction on Wikipedia prose

`redact.py` was built against allaboutbirds, which capitalised bird names (`Green Heron`).
**Wikipedia writes them in lowercase mid-sentence (`the green heron`), and the current
redactor is case-sensitive.** Reading its candidate list: it adds `com_name`, each
whitespace-separated part, their plurals, and then — only for the *last* part — a
lowercase form. So `Green Heron` produces `Green`, `Heron`, `heron`, `herons`, but never
`green`. Against Wikipedia prose that silently under-redacts.

Measured over the 129 Description sections:

| leak | current `redact.py` | improved redactor |
|---|---|---|
| a word from the common name survives | **81 (63%)** | 0 |
| genus or abbreviated binomial survives | **47 (36%)** | 0 |
| subspecies-structured prose | 32 (25%) | 32 (25%) |
| self-referential name hint | 3 | 3 |
| heavily over-redacted (> 6% of tokens) | 0 | **9 (7%)** |

The current behaviour produces cards that answer themselves:

> The blue-winged [redacted] is a small [redacted] at 11.4–12.7 cm long.
> The king [redacted] is a large sea duck.
> The stilt [redacted] resembles the curlew [redacted] in its long bill.
> The green [redacted] is a relatively small [redacted].

The fix is mechanical — make the pattern case-insensitive, split on hyphens as well as
spaces, and add the genus, the full binomial, the bare epithet, and abbreviated forms
(`T. bicolor`, `T. m. migratorius`) as candidates. That drives both leak classes to zero
in the sample. **But it trades one problem for another**, and the trade does not go away:

### The colour-name trap

**420 of 1,433 North American species (29%) have a literal colour word in their common
name**; 594 (41%) have a colour, pattern, or body-part word. For those species, redacting
the name *is* redacting the diagnostic feature. Yellow Warbler, Blue Jay, Scarlet Tanager,
Vermilion Flycatcher, Green Heron, Red-winged Blackbird — you can have a card that does
not answer itself, or a card that describes the bird, not both.

This is not a Wikipedia problem. It applied to allaboutbirds too. It is worse here only
because Wikipedia's prose is longer and names the bird more often. **Any prose-based
Description card carries it.** It probably wants an explicit policy — most likely
"redact the noun, keep the modifier when the modifier is a colour", accepting a partial
give-away, or excluding colour-named species from the description card type.

### Residual problems no redactor fixes

**Subspecies-structured prose, 25% of sections.** Wikipedia describes polytypic species by
enumerating races. On a flashcard this is noise:

> Adults of the nominate subspecies E. a. affinis have pale grayish lores...
> The red spots at the base of the bills are absent in haringtoni.
> There are 27 subspecies of the rufous-collared [redacted].

**Dangling cross-references.** `(see "Subspecies" below)` in the Peregrine Falcon text
points at a page the card does not contain.

**Self-referential name hints**, which survive redaction because they never name the bird:

> The legs are long and very slender (hence the common name) and yellow. *(Sharp-shinned Hawk)*
> a small fleshy black "horn" extending upwards from the eye, from which the animal
> derives its common name *(Horned Puffin)*

---

## Sources ruled out

### Structured trait data — the "compose prose" route

**This route is closed, and the reason is simple: nobody has published the data.**

**Wikidata.** Measured by SPARQL over 23,067 items that are bird species
(`wdt:P171* wd:Q5113` and `wdt:P105 wd:Q7432`):

| property | species with a value | share |
|---|---|---|
| P462 colour | **13** | **0.1%** |
| P2043 length | 9 | 0.0% |
| P2048 height | 7 | 0.0% |
| P2050 wingspan | 1,110 | 4.8% |
| P2067 mass | 4,760 | 20.6% |

The American robin's Wikidata item carries 90 statements. Almost all are external
database identifiers. There is no plumage description anywhere in it.

**AVONET** (Tobias et al. 2022, `10.6084/m9.figshare.16586228`) is the best bird trait
dataset that exists: **CC BY 4.0**, 90,020 individuals, all 11,009 extant species,
downloaded and inspected. Its 37 columns are:

```
Beak.Length_Culmen, Beak.Length_Nares, Beak.Width, Beak.Depth, Tarsus.Length,
Wing.Length, Kipps.Distance, Secondary1, Hand-Wing.Index, Tail.Length, Mass,
Habitat, Habitat.Density, Migration, Trophic.Level, Trophic.Niche,
Primary.Lifestyle, Min/Max/Centroid Latitude, Centroid.Longitude, Range.Size, ...
```

Not one colour, pattern, or plumage field. Prose composed from AVONET would read *"a small
forest bird of about 22 g with a short beak and a medium tail, eating invertebrates"* —
which describes several thousand species equally well. The licence is perfect and the data
is useless for this purpose.

### Other text sources

| source | probe result |
|---|---|
| **GBIF** `/species/{key}/descriptions` | 7 records for the American robin, all `Distribution`, `Notes`, `native range`, `eunis habitat`. Zero morphology. |
| **Wikispecies** | `Turdus migratorius` returns Taxonavigation, Name, References, Vernacular names. Pure nomenclature — no description section exists in the project's page model at all. |
| **EOL** | v1 API `?texts=10` returns `dataObjects: 0`. The website is behind a Cloudflare interstitial (`Enable JavaScript and cookies to continue`) — the same failure mode as allaboutbirds. Even if reachable, EOL's bird text is largely mirrored Wikipedia plus Animal Diversity Web, which is CC BY-NC-SA and therefore outside the licence envelope. |
| **iNaturalist** | `/v1/taxa` returns `wikipedia_url` and a `wikipedia_summary`. It is a Wikipedia mirror of the *lead*, which is the thing already known not to work. |
| **allaboutbirds.org** | `HTTP 403`. Still blocked, consistent with [#8](https://github.com/Ian-Costa18/AviAnki/issues/8). |
| **Birds of the World** | `HTTP 200` but subscription-gated and © Cornell. Not redistributable at any coverage level. |
| **NatureServe Explorer** | API reachable and returns records, but its bird content is conservation-status and distribution, not plumage, and the content is not openly licensed. |

### Public-domain field guides — the near miss

Not in the ticket's candidate list, and the most interesting thing found. Chester Reed's
*Bird Guide* series (1906–1913, public domain, on the Internet Archive) is written in
precisely the register the card wants — terse, diagnostic, field-first:

> **Wilson Snipe** — Bill very long, but not as heavy as that of the Woodcock; eyes not
> abnormally large; head striped with black and whitish; back handsomely variegated with
> black, brown and white; sides barred with black and white.

> **Stilt Sandpiper** — Bill slender and only moderately long. In summer, the entire
> underparts are rusty-white, barred with blackish; ear-coverts and top of head browner;
> back mixed brown and black. In winter, they are gray above and whitish below, with the
> breast streaked with dusty.

That is better than most of Wikipedia. Three problems kill it:

1. **Coverage.** Parsing the ALL-CAPS species headings out of all three volumes (east of
   the Rockies, western, water birds) and matching against the modern 1,433-species list
   gives **345 exact (24%)**, **460 including fuzzy matches (32%)**. The true figure is
   higher, because Reed uses 1910 AOU names — the Northern Cardinal is `CARDINAL`, the
   Northern Flicker is `FLICKER`, the Canada Warbler is the Canadian Warbler — but closing
   that gap means hand-building a several-hundred-entry 1910-AOU → eBird crosswalk. And
   the ceiling is still the ~700 species recognised in North America in 1910: no Hawaii,
   no established exotics, and none of the recent splits, which are exactly the
   hard-to-identify birds a description card would be most valuable for.

2. **Reed relied on the facing colour plate.** Of 951 parsed accounts, **18% contain no
   colour or pattern word at all** in the description text and another **26% contain only
   one to three**. The Cardinal's account is anecdote about cage-trapping. The Flicker's
   entire description is *"Male with a black moustache mark; female without."* The plate
   carried the appearance, and the plate is not text.

3. **It is OCR.** `wliite`, `othor`, `marslies`, `Macrorhamphvs`, `L5<i \ 1.10`. Cleanable,
   but it is another parser to own.

**Bent's *Life Histories of North American Birds*** (Smithsonian, 1919–1968, US Government
work, public domain) covers every North American species and was checked as the obvious
answer to Reed's coverage gap. It is the wrong register entirely — its `Plumages` sections
are museum-skin moult sequences:

> Plumages.—The molts and plumages correspond to those of the eastern bobwhite, but Dr.
> Jonathan Dwight (1900) says that "the juvenal plumage is browner than in virginianus."

> The scapulars are brownish, each feather with a rather broad whitish shaft stripe, and
> barred with yellowish white and black, and the wing coverts have much the same pattern,
> but the barring is pale cinnamon and brown.

Unusable on a flashcard, and many volumes are lending-restricted on the Internet Archive
even though the underlying text is public domain.

---

## What this implies for #25

Reading the three outcomes #25 lays out:

- **Keep it** is available. Wikipedia's Description section, sentence-filtered, is a real
  source for ~80% of North American species under an acceptable licence.
- **Rebuild it from structured traits** is not available and will not become available.
  Close that option.
- **Drop it for now** remains reasonable if the ~20% failure rate, the share-alike
  consequence, or the colour-name trap is judged too expensive.

If it is kept, the work it implies:

1. A level-aware section extractor keyed on the `Description` heading (nested subsections
   must be kept).
2. A sentence filter that drops measurement-only sentences — 24% of the raw text.
3. A rewritten `redact.py`: case-insensitive, hyphen-splitting, and covering genus, full
   binomial, bare epithet, and abbreviated binomial forms.
4. An explicit policy for colour-named species (29% of the list).
5. An explicit "no description card" rule for the ~14% with no Description section, which
   includes ordinary birds like Sora, Merlin, and White Ibis.
6. Attribution plumbing for CC BY-SA, and a decision that the deck itself is CC BY-SA.

---

## Uncertainty and limits

- **"Identification-useful" was measured by colour- and pattern-word density**, which is a
  proxy, not a judgement. It was calibrated by hand-reading roughly 60 samples, and the
  bucket boundaries (200 chars, 400 chars) are chosen, not derived. The shape of the
  distribution is solid; the exact percentages are not precise to better than a few points.
- **Wikipedia is a moving target.** The 86% section-coverage figure will drift, in both
  directions, and should be re-measured rather than trusted long-term.
- **5 of 150 sampled articles could not be confirmed as the correct species page.** The
  common-name-to-article mapping worked for all 150, but a production pipeline should map
  through Wikidata's eBird taxon ID (P3444) sitelinks rather than by name — that property
  exists and is well populated, though I did not measure its coverage (the full SPARQL
  export timed out at ~4 MB, which itself indicates the mapping is large).
- **The Reed coverage numbers are a floor.** Real content coverage is higher; I did not
  build the 1910-AOU crosswalk that would measure it properly. My judgement is that the
  plate-dependence problem (44% of accounts under-describing) matters more than the name
  mapping, but I have not proven that.
- **Non-English Wikipedias were not evaluated.** Some have better-disciplined bird
  descriptions; all would need translation, which introduces a different set of problems.
- **LLM-generated descriptions were not evaluated.** The ticket asked for a source that can
  be redistributed, and generation is a different decision with different risks
  (accuracy, cost, provenance). If #25 wants that option explored it needs its own ticket.

## Sources

- English Wikipedia, MediaWiki Action API — `en.wikipedia.org/w/api.php`
- Wikimedia Core REST API (licence confirmation) — `api.wikimedia.org/core/v1/wikipedia/en`
- Wikidata Query Service — `query.wikidata.org/sparql`
- Wikispecies — `species.wikimedia.org/w/api.php`
- eBird API v2, `ref/taxonomy/ebird` and `product/spplist` — `api.ebird.org`
- GBIF API v1 — `api.gbif.org/v1/species/{key}/descriptions`
- Encyclopedia of Life API v1 and website — `eol.org`
- iNaturalist API v1 — `api.inaturalist.org/v1/taxa`
- NatureServe Explorer API — `explorer.natureserve.org/api/data/search`
- AVONET, Tobias et al. 2022, *Ecology Letters* — `doi:10.6084/m9.figshare.16586228` (CC BY 4.0)
- Chester A. Reed, *Bird Guide* (east of the Rockies / western / water birds), 1906–1913,
  Internet Archive `birdguideeastofr12reedrich`, `westernbirdguide00unse`, `birdguidewaterbi00reed_0`
- Arthur Cleveland Bent, *Life Histories of North American Gallinaceous Birds*, 1932,
  Internet Archive `lifehistoriesofn00bent_10`
