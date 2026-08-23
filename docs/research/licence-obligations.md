# Licence obligations and how attribution reaches the card

Research for [#17](https://github.com/Ian-Costa18/AviAnki/issues/17). Feeds [#20](https://github.com/Ian-Costa18/AviAnki/issues/20) (source contract) and [#22](https://github.com/Ian-Costa18/AviAnki/issues/22) (attribution on the card).

**Researched 2026-08-23.**

> **This is a reading of the licence texts and terms of service, not legal advice.**
> Every obligation below is traced to a clause in a primary document, quoted where it
> matters. Creative Commons itself disclaims giving legal advice in the preamble of every
> licence ("Creative Commons Corporation … is not a law firm and does not provide legal
> services or legal advice"). Nothing here has been reviewed by a lawyer. Where a question
> is genuinely unsettled it is marked **AMBIGUOUS** rather than resolved confidently.

---

## 0. Sources actually read

Primary documents, read in full text (not summaries):

| Short name | Document | URL |
|---|---|---|
| CC0 | Creative Commons CC0 1.0 Universal, legal code | https://creativecommons.org/publicdomain/zero/1.0/legalcode.en |
| BY 4.0 | Creative Commons Attribution 4.0 International, legal code | https://creativecommons.org/licenses/by/4.0/legalcode.en |
| BY-SA 4.0 | Creative Commons Attribution-ShareAlike 4.0 International, legal code | https://creativecommons.org/licenses/by-sa/4.0/legalcode.en |
| BY-ND 4.0 | Creative Commons Attribution-NoDerivatives 4.0 International, legal code | https://creativecommons.org/licenses/by-nd/4.0/legalcode.en |
| BY 3.0 | Creative Commons Attribution 3.0 Unported, legal code | https://creativecommons.org/licenses/by/3.0/legalcode.en |
| BY-SA 3.0 | Creative Commons Attribution-ShareAlike 3.0 Unported, legal code | https://creativecommons.org/licenses/by-sa/3.0/legalcode.en |
| CC FAQ | Creative Commons Frequently Asked Questions | https://creativecommons.org/faq/ |
| CC SA-interp | Creative Commons wiki, "ShareAlike interpretation" | https://wiki.creativecommons.org/wiki/ShareAlike_interpretation |
| CC TASL | Creative Commons wiki, "Recommended practices for attribution" | https://wiki.creativecommons.org/wiki/Best_practices_for_attribution |
| WMF ToU | Wikimedia Foundation Terms of Use | https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use |
| WMF UA | Wikimedia Foundation User-Agent Policy | https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy |
| MW Etiquette | MediaWiki API:Etiquette | https://www.mediawiki.org/wiki/API:Etiquette |
| Commons Reuse | Commons:Reusing content outside Wikimedia | https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia |
| iNat ToU | iNaturalist Terms of Use, rev. 11 July 2023 | https://www.inaturalist.org/pages/terms |
| iNat API | iNaturalist API Recommended Practices, rev. 27 Feb 2025 | https://www.inaturalist.org/pages/api+recommended+practices |
| eBird API ToU | eBird API Terms of Use, last edited 19 Oct 2021 | https://www.birds.cornell.edu/home/ebird-api-terms-of-use/ |
| eBird Data ToU | eBird Data Access Terms of Use, last updated 9 Nov 2020 | https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use/ |
| XC Terms | xeno-canto Terms of Use | https://xeno-canto.org/about/terms |
| XC API | xeno-canto API v3 documentation | https://xeno-canto.org/explore/api |
| XC Search | xeno-canto search tips (`lic:` tag) | https://xeno-canto.org/help/search |

**Retrieval note.** `xeno-canto.org`, `inaturalist.org` and `birds.cornell.edu` all block
non-browser clients (Anubis proof-of-work, Cloudflare). Those five documents were read from
Internet Archive captures of the pages themselves (`web.archive.org/web/<ts>id_/<url>`,
captures dated 2026-03-03 through 2026-08-12) — the archived document text, not a third-party
summary. Everything else was fetched live. Two live API probes were made to confirm what
metadata is actually returned: `api.inaturalist.org/v1/observations` and
`commons.wikimedia.org/w/api.php` (`prop=imageinfo&iiprop=extmetadata`).

---

## 1. Per-licence obligations

### 1.1 CC0 1.0 — no attribution obligation

CC0 §2 ("Waiver") is a waiver, not a licence with conditions:

> "Affirmer hereby overtly, fully, permanently, irrevocably and unconditionally waives,
> abandons, and surrenders all of Affirmer's Copyright and Related Rights and associated
> claims and causes of action … (iv) for any purpose whatsoever"

There is **no attribution condition anywhere in CC0**. §3 is a fallback licence, also
unconditional. CC's own guidance confirms this and recommends credit anyway:

> "Although attribution is not a legal obligation under CC0 dedication's or CC Public Domain
> Mark's licensing terms, we recommend that you consider including information about the
> hosting institution for public domain materials when it is reasonable to do so." — CC TASL,
> "Citing public domain materials"

Two things CC0 does **not** give you, both in §4:

- §4(a): "No trademark or patent rights held by Affirmer are waived".
- §4(c): "Affirmer disclaims responsibility for clearing rights of other persons that may
  apply to the Work or any use thereof … Further, Affirmer disclaims responsibility for
  obtaining any necessary consents, permissions or other rights required for any use of the
  Work." — i.e. CC0 on a photo does **not** clear the rights of anyone depicted in it. Not a
  practical risk for bird photos, but it is the reason CC0 is not a blanket safety guarantee.

**Obligation: none legally. Record and display credit anyway** — it costs nothing, it is CC's
recommendation, and a uniform credit line across all assets is simpler to build than a
conditional one.

### 1.2 CC BY 4.0 — the attribution condition, exactly

BY 4.0 §3(a)(1). The trigger is *Sharing*, and "Share" is defined in §1 as providing material
to the public by any means requiring permission — distributing a `.apkg` to a friend is
Sharing.

> "If You Share the Licensed Material (including in modified form), You must:
> **(A)** retain the following if it is supplied by the Licensor with the Licensed Material:
> **(i)** identification of the creator(s) of the Licensed Material and any others designated
> to receive attribution, in any reasonable manner requested by the Licensor (including by
> pseudonym if designated); **(ii)** a copyright notice; **(iii)** a notice that refers to
> this Public License; **(iv)** a notice that refers to the disclaimer of warranties;
> **(v)** a URI or hyperlink to the Licensed Material to the extent reasonably practicable;
> **(B)** indicate if You modified the Licensed Material and retain an indication of any
> previous modifications; and **(C)** indicate the Licensed Material is licensed under this
> Public License, and include the text of, or the URI or hyperlink to, this Public License."

Note the shape of this. (A) is **conditional retention** — you must keep what the licensor
supplied. (B) and (C) are **unconditional** — you must state modification status and you must
state the licence and give its text or URI, whether or not the licensor supplied that.

On *form* and *placement*, §3(a)(2):

> "You may satisfy the conditions in Section 3(a)(1) in any reasonable manner based on the
> medium, means, and context in which You Share the Licensed Material. For example, it may be
> reasonable to satisfy the conditions by providing a URI or hyperlink to a resource that
> includes the required information."

So the licence is deliberately flexible about *where* attribution lives, including allowing an
indirection to a URL. It is not flexible about *whether* it is there.

§3(a)(3): "If requested by the Licensor, You must remove any of the information required by
Section 3(a)(1)(A) to the extent reasonably practicable." — a takedown-of-credit obligation.

Two further conditions bear directly on bundling:

- §2(a)(5)(B) **No downstream restrictions**: "You may not offer or impose any additional or
  different terms or conditions on, or apply any Effective Technological Measures to, the
  Licensed Material if doing so restricts exercise of the Licensed Rights by any recipient of
  the Licensed Material."
- §2(b)(1) **No endorsement**: nothing in the licence permits asserting or implying that the
  use is "sponsored, endorsed, or granted official status by, the Licensor".

CC's recommended practical form is **TASL** — Title, Author, Source, License (CC TASL, "Basic
components of attribution"). Title is *optional* in 4.0 and *required* in 3.0 and earlier
(same page, "License details").

### 1.3 CC BY-SA 4.0 — everything in BY 4.0, plus §3(b)

BY-SA 4.0 §3(a) is **word-for-word identical** to BY 4.0 §3(a)(1)–(3). The only addition is
§3(b):

> "**ShareAlike.** In addition to the conditions in Section 3(a), **if You Share Adapted
> Material You produce**, the following conditions also apply.
> **(1)** The Adapter's License You apply must be a Creative Commons license with the same
> License Elements, this version or later, or a BY-SA Compatible License.
> **(2)** You must include the text of, or the URI or hyperlink to, the Adapter's License You
> apply. …
> **(3)** You may not offer or impose any additional or different terms or conditions on, or
> apply any Effective Technological Measures to, Adapted Material that restrict exercise of
> the rights granted under the Adapter's License You apply."

Emphasis added. The condition is gated entirely on producing **Adapted Material**. See §2.

### 1.4 The 3.0 licences — you will hit these, and they are stricter

Wikimedia Commons is full of CC BY-SA 3.0 files. A live probe of
`File:Cyanocitta-cristata-004.jpg` (a featured Blue Jay photo) returned
`License = cc-by-sa-3.0`, `LicenseUrl = http://creativecommons.org/licenses/by-sa/3.0/`. This
is not an edge case.

BY-SA 3.0 §4(c) (and the identical BY 3.0 §4(b)) requires **more** than 4.0 does:

> "…keep intact all copyright notices for the Work and provide, reasonable to the medium or
> means You are utilizing: (i) the name of the Original Author (or pseudonym, if applicable)
> if supplied … (ii) **the title of the Work if supplied**; (iii) to the extent reasonably
> practicable, the URI, if any, that Licensor specifies to be associated with the Work …"

and adds a **prominence rule** absent from 4.0:

> "…in the case of a Adaptation or Collection, at a minimum such credit will appear, if a
> credit for all contributing authors of the Adaptation or Collection appears, then as part of
> these credits and **in a manner at least as prominent as the credits for the other
> contributing authors**."

and §4(a) makes the licence URI mandatory per copy:

> "You must include a copy of, or the Uniform Resource Identifier (URI) for, this License with
> **every copy of the Work** You Distribute or Publicly Perform. … You must keep intact all
> notices that refer to this License and to the disclaimer of warranties with every copy of
> the Work…"

**Consequence for the pipeline:** the licence *version* is load-bearing, not cosmetic. A
per-asset record that says "CC BY-SA" without a version cannot generate a compliant credit
line, because it cannot know whether the title is mandatory. Store the full licence URI.

### 1.5 CC BY-ND 4.0 and CC BY-NC-* — excluded, but for different reasons

- **NC licences** (BY-NC, BY-NC-SA, BY-NC-ND) are outside the map's constraint (#6: "Only
  openly-licensed media (CC0 / CC-BY / CC-BY-SA)"). They are also awkward independently: the
  CC FAQ's collection table distinguishes "Commercial Collection (BY, BY-SA, BY-ND)" from
  "NonCommercial Collection", and a freely redistributable deck a stranger might sell is
  hard to keep on the NC side of that line.
- **ND licences** are the interesting case; see §3.

---

## 2. Share-alike reach: collection vs adaptation

**Answer: including an unmodified CC BY-SA asset in a deck imposes nothing on the deck as a
whole. It binds only that asset.** This is not an inference — CC states it directly.

The 4.0 licences deleted the "Collection" concept entirely and hang everything on **Adapted
Material**, defined in BY-SA 4.0 §1:

> "**Adapted Material** means material subject to Copyright and Similar Rights that is derived
> from or based upon the Licensed Material and in which the Licensed Material is translated,
> altered, arranged, transformed, or otherwise modified in a manner requiring permission under
> the Copyright and Similar Rights held by the Licensor. For purposes of this Public License,
> where the Licensed Material is a musical work, performance, or **sound recording**, Adapted
> Material is always produced where the Licensed Material is **synched in timed relation with
> a moving image**."

And §3(b) applies only "if You Share Adapted Material You produce". A deck that places an
unmodified photo next to unrelated text produces no Adapted Material, so §3(b) never fires.

CC's own interpretation page says so explicitly:

> "**The ShareAlike condition applies only for works considered adaptations under copyright
> law, not simply in collections with other works (also referred to as mere aggregations).**
> … Simply including an SA work unmodified alongside unrelated materials does not produce an
> adaptation." — CC SA-interp, "Key points about the ShareAlike licenses"

> "**ShareAlike photo being used unmodified in a larger work.** Unless the larger work would be
> considered an adaptation of it, using a ShareAlike photo as a separate element within it
> does not require original materials in the larger work to be ShareAlike or compatible. **The
> larger work may be licensed under any terms.**" — CC SA-interp, "Examples"

And the CC FAQ, on collections generally:

> "**All Creative Commons licenses (including the version 4.0 licenses) allow licensed
> material to be included in collections such as anthologies, encyclopedias, and broadcasts.
> You may choose a license for the collection, however this does not change the license
> applicable to the original material.** When you include CC-licensed content in a collection,
> you still must adhere to the license conditions governing your use of the material
> incorporated." — CC FAQ, "If I create a collection that includes a work offered under a CC
> license, which license(s) may I choose for the collection?"

The pre-4.0 licences say the same thing in older vocabulary, and say it even more bluntly —
BY-SA 3.0 §4(a): "This Section 4(a) applies to the Work as incorporated in a Collection, **but
this does not require the Collection apart from the Work itself to be made subject to the
terms of this License.**"

### 2.1 The one trap: the sound-recording synch rule

The Adapted Material definition contains a special rule for sound recordings — synching to a
**moving image** always produces Adapted Material, and CC SA-interp lists it as an explicit
example ("ShareAlike music being used as the soundtrack to a video … the resulting video must
be under a ShareAlike or compatible license").

An Anki card is a static HTML page with an `[sound:...]` tag. **There is no moving image and no
timed relation.** The synch rule does not fire. Worth stating in the source contract so nobody
re-derives the worry later — but if a future card type ever animates alongside audio, this
changes.

### 2.2 What this means for the deck's own licence

The deck is a **collection**. AviAnki may license its own contribution — card templates, CSS,
note model, species ordering, the selection itself — under whatever it likes. Each bundled
asset stays under its own licence.

The one hard limit is BY 4.0 §2(a)(5)(B) / BY-SA 4.0 §3(b)(3): whatever terms AviAnki puts on
the deck **must not restrict a recipient's exercise of the licensed rights in the individual
assets**. A deck-level "all rights reserved" or "non-commercial only" notice that appeared to
cover the bundled CC BY assets would breach that. The deck notice must be explicit that
per-asset licences govern the assets. See §5.4 — this is exactly where eBird's terms collide.

---

## 3. Derivative works: trimming to 10 s, transcoding, resizing

Three different operations with three different answers.

### 3.1 Transcoding and resizing — permitted under *all six* CC licences, ND included

BY 4.0 §2(a)(4), identical in all 4.0 licences including BY-ND:

> "**Media and formats; technical modifications allowed.** The Licensor authorizes You to
> exercise the Licensed Rights in all media and formats whether now known or hereafter
> created, and to make technical modifications necessary to do so. … For purposes of this
> Public License, **simply making modifications authorized by this Section 2(a)(4) never
> produces Adapted Material.**"

CC FAQ confirms and extends this to resolution:

> "**Can I take a CC-licensed work and use it in a different format?** Yes. … licensees are
> granted permission to use the material as the license allows, whatever the media or format
> chosen by the user … **This is true even in our NoDerivatives licenses.**"

> "Under U.S. copyright law, for example, mechanical reproduction of a work into a different
> format is unlikely to create a separate, new work. Consequently, digitally enhancing or
> changing the format of a work **absent some originality** … will not likely create a
> separate work for copyright purposes. … Accordingly, in some jurisdictions releasing a
> photograph under a CC license will give the public permission to reuse the photograph in a
> different resolution." — CC FAQ, "How do I know if a low-resolution photo and a
> high-resolution photo are the same work?"

So `ffmpeg`-to-MP3 and a proportional resize are **technical modifications, not adaptations**,
and trigger no ShareAlike obligation. Note the FAQ's hedges ("in some jurisdictions", "absent
some originality") — a crop that reframes the subject is an editorial choice, not a technical
one, and is on the other side of this line. Keep image processing to proportional scaling and
format conversion and this stays clean.

### 3.2 Trimming to 10 seconds — an excerpt, and a different question

Trimming is not covered by §2(a)(4). Taking a 10-second window out of a 3-minute recording is
selection, not format conversion. Under BY 4.0 and BY-SA 4.0 this is unproblematic either way:

- BY 4.0 §2(a)(1)(A) grants the right to "reproduce and Share the Licensed Material, **in whole
  or in part**", and §2(a)(1)(B) grants the right to "produce, reproduce, and Share Adapted
  Material". Both routes are licensed.
- BY-SA 4.0 grants the same. **If** the trim counts as Adapted Material, §3(b) applies **to the
  trimmed clip**: AviAnki must offer the clip under CC BY-SA (same version or later) and
  include that licence's URI. It still does not reach the deck (§2).

The cheap, safe move: treat every trimmed BY-SA clip as Adapted Material and label it BY-SA
anyway. That is true whichever way the question falls, and it removes the need to decide.

Either way, BY 4.0 / BY-SA 4.0 §3(a)(1)(B) applies: **"indicate if You modified the Licensed
Material"**, and the CC FAQ names excerpting as exactly the case that requires it —

> "You must also indicate if you have modified the work — for example, **if you have taken an
> excerpt**, or cropped a photo. … It is not necessary to note trivial alterations, such as
> correcting a typo or changing a font size."

So: "Trimmed to 10 s" (and, if you want to be thorough, "converted to MP3") must appear in the
credit line for every trimmed asset.

### 3.3 ND and trimming — **AMBIGUOUS**, and the reason to just exclude ND

BY-ND 4.0 §2(a)(1) is the whole story:

> "…grants You a worldwide, royalty-free, non-sublicensable, non-exclusive, irrevocable license
> to exercise the Licensed Rights in the Licensed Material to: **(A)** reproduce and Share the
> Licensed Material, in whole or in part; and **(B) produce and reproduce, but not Share,
> Adapted Material.**"

and §3(a)(1) closes with: "**For the avoidance of doubt, You do not have permission under this
Public License to Share Adapted Material.**"

You may trim privately. You may not distribute the trim **if the trim is an adaptation**. Is a
10-second excerpt an adaptation? The CC FAQ leans toward "not necessarily":

> "Incorporating an unaltered excerpt from an ND-licensed work into a larger work only creates
> an adaptation if the larger work can be said to be built upon and derived from the work from
> which the excerpt was taken. Generally, no derivative work is made … when the excerpt is used
> to illuminate an idea or provide an example in another larger work. Instead, only the
> reproduction right of the original copyright holder is being exercised…" — CC FAQ, "Can I
> reuse an excerpt of a larger work that is licensed with the NoDerivs restriction?"

with an explicit carve-back in the next paragraph: "There are exceptions to that general rule,
however, when the excerpts are combined with other material in a way that creates some new
version of the original."

**Reading, flagged as ambiguous:** an argument exists that a 10-second unaltered excerpt on a
flashcard is a permitted partial reproduction, since §2(a)(1)(A) explicitly licenses
reproduction "in whole or in part" and the deck is not built upon the recording. The
counter-argument is that the deck presents the clip *as* the bird's call — i.e. as a substitute
for the work, not as an illustration of a point about it — and it is exactly the kind of "new
version of the original" the carve-back contemplates. This is not resolvable from the licence
text, and the answer may differ by jurisdiction ("What constitutes an adaptation … varies
slightly based on the law of the relevant jurisdiction").

**Recommendation: exclude ND unconditionally.** Not because the answer is certainly "no", but
because the cost of exclusion is one filter and the cost of being wrong is a deck that
thousands of people have redistributed.

### 3.4 On the claim that "xeno-canto carries a meaningful amount of CC-BY-ND" — **partly refuted, partly unverified**

What the primary sources actually establish:

- **XC's own Terms of Use describe only three licence families**, and the only ND one is
  NonCommercial: "Attribution-NonCommercial-NoDerivs (BY-NC-ND): This is the most restrictive
  of our licenses"; "Attribution-NonCommercial-ShareAlike (BY-NC-SA)"; "Attribution-ShareAlike
  (BY-SA)". **Bare BY-ND is not among the options XC describes.** XC also notes these are
  "necessarily simplified summaries".
- **ND and CC0 are nonetheless searchable licence conditions on XC**, so ND-without-NC material
  can exist historically: "License conditions are Attribution (BY), NonCommercial (NC),
  ShareAlike (SA), NoDerivatives (ND) and Public Domain/copyright free (CC0). … for 'no rights
  reserved' recordings, use `lic:PD`." — XC Search, "Recording license"
- **The volume could not be measured.** XC API v3 requires a per-account key
  (`https://xeno-canto.org/api/3/recordings` returns HTTP 401 "Missing or invalid 'key'
  parameter" without one), API v2 is retired (404), and the HTML search UI is behind a
  proof-of-work challenge. A `lic:BY-ND` count needs an XC account key.

**So the framing in #17 is off in a useful way.** The ND problem on xeno-canto arrives almost
entirely wearing an NC label — and the `NC` filter that the #6 constraint already mandates
removes it before the ND question is ever reached. The residual risk is bare BY-ND, whose
volume is unknown and probably small.

**This does not make the ND filter optional.** The obligation is: **match on the full licence
identifier, not on a prefix.** A pipeline that allowlists by testing "does the licence start
with `cc-by`" admits `cc-by-nd` and `cc-by-nc-nd`. Allowlist exact identifiers.

**Action:** register for an XC account key and run `lic:BY-ND` / `lic:PD` counts, both to size
this and because the key is needed for the pipeline regardless (§4.4).

---

## 4. API terms of service — a separate question from the content licence

A licence can permit redistribution while the terms under which you *obtained* the asset
restrict you. All four sources have such terms, and they differ sharply.

### 4.1 iNaturalist — permissive content terms, concrete rate limits elsewhere

**Content licensing.** iNat ToU, "Responsibility of Contributors":

> "If you own the Content prior to contributing the Content to the Site, and that Content is
> subject to Intellectual Property rights, you retain ownership of those rights. **Unless you
> specify otherwise when you post Content, you agree to license Content you contribute to the
> Platform under the Creative Commons Attribution Noncommercial license (CC BY-NC).**"

So **the default is CC BY-NC and therefore out of scope for AviAnki.** Open-licensed photos are
the minority that opted in. This is a filter requirement, not an incidental detail.

**The ToU contains no anti-scraping or anti-bulk clause.** I looked for one specifically; the
only rate-shaped language is about *posting* ("You will post only Content that is relevant to
iNaturalist and at a rate and volume that does not hinder other Users' ability to use
iNaturalist"). Redistribution of downloaded content is not restricted by the ToU — the ToU
disclaims responsibility for it rather than forbidding it ("iNaturalist disclaims any
responsibility for any harm resulting … from any downloading by those visitors of content
posted to the Platform").

**The operative constraints live in iNat API Recommended Practices**, and they are specific:

> "Please keep requests to about **1 per second**, and around **10k API requests a day**"
> "The API is meant to be used for building applications and for fetching small to medium
> batches of data. **It is not meant to be a way to download data in bulk**"
> "**Downloading over 5 GB of media per hour or 24 GB of media per day may result in a
> permanent block**"
> "Please use a **single IP address** for fetching data. If we think multiple IPs are being
> used in coordination to bypass rate limits, we may block those IPs regardless of query rate"
> "please consider using a **custom User Agent** to identify your application"
> "To fetch a lot of observation data efficiently, we recommend using **observation exports** …
> Another recommended way to get a lot of data at once is to use the dataset of research grade
> observations that we submit weekly to **GBIF**"
> "If using the API to fetch a lot of results, please use the **highest supported `per_page`**
> value. For example you can get up to 200 observations in a single request"

Pagination caps at 10k results; beyond that, sort by `id` ascending and use `id_above`.

**Note on the GitHub Actions build.** "Please use a single IP address" is in direct tension with
running the catalog build on GitHub-hosted runners, whose egress IP is arbitrary and varies per
job. This is unlikely to be read as coordinated evasion for a once-weekly single-job build, but
it is worth (a) a stable descriptive `User-Agent` naming the project and a contact, and (b) an
email to `help@inaturalist.org` — the page itself says "If you're looking for even more data,
contact us directly".

**What the API returns** (verified by live probe of `/v1/observations`): each photo object has
`id`, `license_code`, `attribution`, `url`, `original_dimensions`. Critically:

- The **photo's** `license_code` is independent of the **observation's** `license_code`. In the
  probed record the observation was `cc0` while every photo was `cc-by`. **Filter on the photo,
  never the observation.**
- `license_code` is **unversioned** (`"cc-by"`, not `"cc-by-4.0"`). The photo's public page
  (`https://www.inaturalist.org/photos/{id}`) links `creativecommons.org/licenses/by/4.0` for a
  `cc-by` photo, so 4.0 appears to be what iNat means — but the API does not say so. **AMBIGUOUS**;
  see §7.
- `attribution` is a pre-built string, e.g. `"(c) carnifex, some rights reserved (CC BY)"`.
  It is the licensor-supplied credit and §3(a)(1)(A)(i) says to retain it "in any reasonable
  manner requested by the Licensor" — so **use it verbatim** rather than reconstructing a name.

### 4.2 Wikimedia — reuse is welcomed, mechanics are policy-bound

**Content.** WMF ToU §7, "Non-text media":

> "Non-text media on the Projects are available under a variety of different licenses…"

and, on reuse:

> "**Re-use:** Reuse of content that we host is welcome, though exceptions exist for content
> contributed under 'fair use' … Any reuse must comply with the underlying license(s)."
> "**For any non-text media, you agree to comply with the applicable license under which the
> work has been made available** (which can be discovered by clicking on the work and looking at
> the licensing section on its description page…)"
> "With both text content and non-text media, **you agree to clearly indicate that the original
> work has been modified.** For each copy or modified version that you distribute, you agree to
> include a **licensing notice stating which license the work is released under, along with
> either a hyperlink or URL to the text of the license or a copy of the license itself**."

That last sentence is a ToU obligation *in addition to* the CC licence, and it is stricter than
CC0 (which requires nothing) — but it is easily satisfied by the uniform credit line.

**Credit the creator, not the uploader** — Commons Reuse:

> "The person who uploaded the work to Wikimedia Commons may be the original content creator or
> they may not… **it is the content creator who must be credited, not the uploader.**"

**API.** WMF ToU §12 incorporates three documents by reference:

> "By using our APIs, you agree to abide by all applicable policies governing the use of the
> APIs, which include but are not limited to the **User-Agent Policy**, the **Robot Policy**, and
> the **API:Etiquette** … which are incorporated into these Terms of Use by reference."

- WMF UA: "**Scripts should use an informative User-Agent string with contact information, or
  they may be blocked without notice.**" Format:
  `CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org) generic-library/0.0`, and
  "Do not use generic agents such as 'curl', 'lwp', 'Python-urllib'". User-Agent strings
  beginning with defaults like `python-requests/x` "may also be blocked".
- MW Etiquette: "There is no hard speed limit on read requests, but be considerate…";
  "**Make your requests in series rather than in parallel**"; ask for multiple items per request
  via the pipe character or a generator; "If your requests obtain data that can be cached for a
  while, you should take steps to cache it"; use `GET` not `POST` for reads; use `maxlag` for
  non-interactive tasks.
- ToU §4 prohibits "Engaging in automated uses of the Project Websites that are abusive or
  disruptive" and "placing an undue burden on an API".

**What the API returns** (verified live, `prop=imageinfo&iiprop=extmetadata|url|user`):
`Artist`, `ObjectName` (title), `Credit`, `License` (e.g. `cc-by-sa-3.0`), `LicenseShortName`,
`LicenseUrl`, `UsageTerms`, `AttributionRequired`, `Permission`, `Restrictions`,
`descriptionurl`. This is a complete TASL record **including the version** — the best-shaped
metadata of the four sources.

Two gotchas seen in the live response:
- `Artist` is **HTML**, e.g. `<a href="//commons.wikimedia.org/wiki/User:Mdf" …>Mdf</a>`. It is
  arbitrary wiki-authored markup and must be sanitised before it reaches a card template.
- Files are frequently **dual-licensed**. The probed file returned `Permission = "You may select
  the license of your choice."` with GFDL among its categories alongside CC BY-SA 3.0. The
  pipeline must pick one licence, record which it picked, and attribute under that one.
- `Restrictions` is a real field (trademark, personality rights, etc.). It was empty here.
  **Treat a non-empty `Restrictions` as a rejection**, or at minimum a manual-review flag.

### 4.3 eBird / Cornell — the restrictive one, and it conflicts with redistribution

This is the source where the API terms, not the content licence, are the binding constraint.
eBird content is **not** CC-licensed at all.

**eBird API ToU §2 (Permitted Use):**

> "…we grant you a non-exclusive, non-transferable, non-sublicensable, revocable license and
> right to use the API to access eBird Data **for non-commercial use**…"
> "You may download API Content the Cornell Lab of Ornithology designates as offered for
> download **to any single device a single copy** of such API Content **for personal and
> non-commercial use only.**"

**§3 (Attribution):**

> "You agree to attribute eBird.org as the source of the data accessed via the API wherever it
> is used or displayed. Whenever possible, please accompany this with a link back to
> eBird.org."

**§5 (Intellectual Property):** "You may not frame or mirror any portion of the API Sites." and
"You agree to maintain all copyright or other proprietary notices embedded in or attached to any
API Content."

**§Preamble** binds everything to a second document: "all data derived from the API ('eBird
Data') are subject to the **eBird Data Access Terms of Use**". Those are stricter still:

> "eBird data are supplied **only for applied and basic research and education**."
> "The recipient will **only use the eBird data provided for the purpose for which it was
> requested**. If subsequent or different use is required the recipient must contact the Cornell
> Lab of Ornithology again for written approval."
> "The recipient **will not pass the original datasets on to any third parties** and will direct
> all such thirds parties' requests for use of eBird data back to the Cornell Lab of
> Ornithology."
> "The recipient **will not publish or publicly distribute eBird data in their original format,
> either whole or in part, in any media, including but not limited to on a website**, FTP site,
> CD, memory stick. The recipient should provide a link to the original data source location on
> the Cornell Lab of Ornithology website where appropriate."
> "The recipient **may only pass on datasets derived** from the Cornell Lab of Ornithology's
> original eBird data … **if these derived data are supplied with the same Terms of Use**."
> "The Cornell Lab of Ornithology and eBird logos **must not be used** on any derived products…"
> "User agrees to send, free of change, an electronic copy of all products published using eBird
> data supplied by the Cornell Lab of Ornithology to … eBird@cornell.edu."

**This is a genuine conflict with the map's destination, and #20 has to resolve it.** AviAnki
uses eBird for one thing: the region → species list. Under these terms, publishing that mapping
in a static catalog on GitHub Pages is publishing eBird data, and the escape hatch — passing on
*derived* data with the same ToU attached — drags a non-commercial, research-and-education-only
restriction onto the catalog. That collides head-on with BY 4.0 §2(a)(5)(B) ("You may not offer
or impose any additional or different terms or conditions on … the Licensed Material") if the
deck's terms are not carefully scoped, and it collides with "a bird watcher should be able to
hand a deck to a friend".

Three options for #20, in increasing order of comfort:

1. **Keep eBird out of the published artefacts.** Use eBird only as a build-time query in the
   CLI (where the user brings their own key, is the "recipient", and is not redistributing),
   and derive the *catalog's* species lists from a licence-clean source.
2. **Publish the species list with the eBird ToU attached**, scoped explicitly and only to that
   file — with a deck/catalog notice making unambiguous that the media assets are governed by
   their own CC licences and are not subject to it. Legally survivable-looking, practically
   confusing, and still non-commercial.
3. **Ask Cornell.** The Data ToU has a written-approval path and an `ebird@cornell.edu` contact.
   For a free, non-commercial educational tool this is a plausible ask.

Also note: **Macaulay Library media (eBird's photos and audio) is not openly licensed** and is
squarely inside the API ToU's "API Content" definition ("still images, text, pictorial works,
video images … audio recordings"), which §2 restricts to "a single copy … for personal and
non-commercial use only". eBird/ML is not a viable media source for a redistributable deck.
The #8 decision already made allaboutbirds dormant; this is the same wall.

### 4.4 xeno-canto — permissive content, explicit request to talk before bulk

**Content.** XC Terms:

> "Sounds are published on xeno-canto under one of several Creative Commons licenses."
> "Each time a recording is shown on a page of xeno-canto at least the following details will
> also be mentioned: **recordist name, license, and xeno-canto catalogue number**."

**XC's own attribution ask**, over and above CC:

> "Honour the attibution clause in the CC licenses: **always mention the recordist** if you
> refer to a recording."
> "At least mention the url **www.xeno-canto.org** in your acknowledgements."
> "Cite sounds as you would cite any other data source. Mention the **recordist**, the
> **XC-number** and the **stable url** for the recording."

**Bulk retrieval** — XC Terms, "Server Resources":

> "xeno-canto runs a server with specifications appropriate for rather intensive use by many
> users at the same time. Unfortunately the server **cannot usually accomodate indiscriminate
> automated requests such as mass downloads of pages or files. Such use of the site is
> (actively) discouraged** especially if it deteriorates the user experience or if it interferes
> with site maintenance. **Requests for the transfer of large amounts of data, for any use
> allowed by the license, are of course welcome at the contact address below.**"

That is an explicit, standing invitation. A North America catalog build is a mass download by
any reading. **Email xeno-canto before the first full build.**

**API v3** requires a key and the key must not be committed:

> "The `key` parameter is new to API v3 and is required… **Do not share your key with others and
> take care not to publish it in any git repositories**, as prolonged abuse of the API may
> result in a warning and ultimately in revocation of your key."
> "Developers building applications on the XC API are encouraged to **create a key for their app
> rather than to use a personal key**."
> "`per_page` … Valid values for this parameter range between 50 and 500, with a default of 100"
> "As we trust these measures to improve performance … we have **lifted the strict rate limit**
> on the API."

The rate limit is lifted, but the Server Resources clause still governs mass file downloads —
those come from the audio URLs, not the API.

**What the API returns:** `id` (XC catalogue number), `rec` (recordist), `lic` — "the URL
describing the license of this recording", e.g. `"//creativecommons.org/licenses/by-nc-sa/4.0/"`
— `url` (stable recording page), `gen`/`sp`/`en`, `type`, `q` (quality), `length`, and the audio
file URL. Note `lic` is a **versioned URL**, which is exactly what §1.4 says to store. XC solves
the version problem that iNat does not.

Also relevant to catalog stability:

> "In principle recordists can take their recordings off line at any time using the xeno-canto
> website."

Deleted recordings are a cache-invalidation and takedown concern, not a licence one — but a
deck already distributed cannot be recalled, and CC licences are irrevocable (BY 4.0 §2(a)(1),
"irrevocable"), so a licence validly granted at fetch time survives the recording's removal.
Record the fetch date so this is provable.

---

## 5. Concrete obligations

### 5.1 Per-asset record (the source contract — #20)

Every asset in the catalog must carry, as structured fields:

| Field | Why | Notes |
|---|---|---|
| `source` | provenance, per-source rules | `inaturalist` \| `wikimedia` \| `xenocanto` |
| `source_asset_id` | stable identity, pins (#10), citation | XC catalogue number; iNat photo id; Commons page title |
| `source_url` | BY 4.0 §3(a)(1)(A)(v); XC "stable url"; CC TASL "Source" | the human-viewable page, not the CDN file URL |
| `file_url` | fetch + re-fetch | separate from `source_url` |
| `licence_id` | BY 4.0 §3(a)(1)(C) | **exact, versioned** SPDX-style id, e.g. `CC-BY-SA-3.0`. Never a bare family name |
| `licence_url` | BY 4.0 §3(a)(1)(C); BY-SA 3.0 §4(a) requires URI per copy | canonical `creativecommons.org` deed URL |
| `creator` | BY 4.0 §3(a)(1)(A)(i) | the **creator**, not the uploader (Commons Reuse) |
| `creator_url` | CC TASL "Author" | profile/user page where available |
| `attribution_text` | §3(a)(1)(A)(i) "in any reasonable manner requested by the Licensor" | licensor-supplied string used verbatim where the source provides one (iNat `attribution`, Commons `Credit`/`Attribution`) |
| `title` | **mandatory** for 3.0 and earlier (BY-SA 3.0 §4(c)(ii)); optional in 4.0 | Commons `ObjectName` |
| `copyright_notice` | BY 4.0 §3(a)(1)(A)(ii) | retain if supplied |
| `modifications` | BY 4.0 §3(a)(1)(B) | list, e.g. `["trimmed to 10s", "transcoded to mp3"]`; empty list if untouched |
| `prior_modifications` | §3(a)(1)(B) "retain an indication of any previous modifications" | retain if supplied |
| `restrictions` | Commons `Restrictions`; CC0 §4 third-party rights | non-empty ⇒ reject or flag |
| `retrieved_at` | proves the licence at grant time survived later deletion | ISO date |
| `source_terms_version` | ToS changes without notice (eBird API ToU: "reserves the right to change these API Terms at any time without prior notice") | date of the terms read |

### 5.2 Pipeline obligations

1. **Allowlist exact versioned licence identifiers.** Not prefixes. `cc-by` must not match
   `cc-by-nd` or `cc-by-nc-nd`. Allowed set: `CC0-1.0`, `CC-BY-{2.0,2.5,3.0,4.0}`,
   `CC-BY-SA-{2.0,2.5,3.0,4.0}`, plus public-domain marks if the source offers them. Everything
   else — any `NC`, any `ND`, unknown, or unversioned-and-unresolvable — is rejected.
2. **Reject rather than guess.** An asset whose licence cannot be resolved to an exact
   identifier does not enter the catalog.
3. **Filter on the asset, not its container.** iNat's photo `license_code` is independent of the
   observation's.
4. **Credit the creator, not the uploader** (Commons).
5. **Handle dual licensing explicitly.** Where Commons offers a choice, pick one, record which,
   attribute under that one.
6. **Record modifications as they happen**, in the pipeline stage that performs them — the trim
   step appends `"trimmed to 10s"`, the transcode step appends `"transcoded to mp3"`.
7. **Keep image processing technical.** Proportional resize and format conversion only; no
   crops, no colour grading. This keeps §2(a)(4) applicable and avoids creating adaptations.
8. **Label trimmed CC-BY-SA audio as CC-BY-SA** (same version or later) in the emitted record,
   whether or not the trim is legally an adaptation. Cheap; removes the question.
9. **Sanitise source-supplied HTML** before it reaches a card template. Commons `Artist` is
   arbitrary wiki markup.
10. **Per-source retrieval discipline:**
    - **iNaturalist:** ≤1 req/s, ≤10k requests/day, ≤5 GB media/hour and ≤24 GB/day; `per_page`
      at the maximum; `id_above` paging past 10k; descriptive `User-Agent`; prefer GBIF/AWS
      Open Data or observation exports for genuinely bulk metadata.
    - **Wikimedia:** `User-Agent` in the documented format with a contact URL and email, never
      generic; requests **in series**, not in parallel; batch titles with `|`; `GET` not `POST`;
      cache; `maxlag` for the unattended build.
    - **xeno-canto:** an **app** API key, kept out of the repo (GitHub Actions secret);
      `per_page=500`; and **email xeno-canto before the first bulk build** — their terms invite
      exactly this.
    - **eBird:** see 5.4.
11. **Cache and re-fetch sparingly.** A rebuild that re-downloads unchanged media is the
    "indiscriminate automated request" all three sources ask you not to make.
12. **Record `retrieved_at`** so an irrevocable grant is provable after a source deletes the
    asset.
13. **Ship no DRM and no additional restrictions** on catalog assets (BY 4.0 §2(a)(5)(B)).
    Note the CC FAQ's carve-out: "merely converting material into a different format that is
    difficult to access … does not violate the restriction" — a `.apkg` zip is fine.
14. **Implement a credit-removal path.** BY 4.0 §3(a)(3) and BY-SA 3.0 §4(a) both require
    removing credit on the licensor's request; the pin/curation file (#10) is the natural place.

### 5.3 Card and deck obligations (#22)

15. **Attribution ships inside the `.apkg`.** §3(a)(2) permits satisfying the conditions "by
    providing a URI or hyperlink to a resource that includes the required information", but a
    deck handed to a friend is used offline, indefinitely, by someone who never visits the site.
    A URL alone makes compliance contingent on GitHub Pages still being there. Embed the
    credits; link out as a convenience.
16. **Attribution must be visible on a rendered card.** CC TASL, "Common pitfalls", rules out
    the two tempting shortcuts: "**Attribute in alt text** … Using this field for licensing
    information makes browsing difficult for those users" and "**Attribute in metadata fields
    only** … many users are likely not aware of, and will never see, attribution information
    included in metadata".
17. **Per-asset credit, unambiguously bound to its asset.** CC TASL, on multi-source works:
    "Lastly, **it is clear which attribution belongs to which work**." Two photos and two audio
    clips on one note means four distinct credit lines, each identifiable.
18. **Each credit line carries, at minimum:** creator; title (mandatory when the asset is
    3.0-or-earlier); licence name **and** URL; source URL; and the modification note where the
    asset was trimmed or transcoded. A workable template:

    > *Blue Jay* by **Mdf** — [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) —
    > [source](https://commons.wikimedia.org/wiki/File:Cyanocitta-cristata-004.jpg) — trimmed to 10 s

19. **Prominence.** BY-SA 3.0 §4(c): credit must appear "in a manner at least as prominent as
    the credits for the other contributing authors". If the deck credits AviAnki anywhere, asset
    credits must be at least as prominent. Practically: do not put AviAnki's name on the card and
    the photographer's name in a footer.
20. **A deck-level credits note** listing every asset in TASL form, plus the licence URLs, plus
    an AviAnki/eBird acknowledgement. This is CC's own recommendation for offline media: "For
    media such as offline materials, video, audio, and images, consider publishing a web page
    with attribution information." Implemented as a dedicated note in the deck (so it survives
    redistribution) it also satisfies #15.
21. **Deck licence notice**, stating that the deck as a collection is a compilation, that
    AviAnki's own contribution (templates, styling, selection) is under *X*, and that **each
    bundled asset remains under its own licence and no additional terms are imposed on it**.
    Required by BY 4.0 §2(a)(5)(B), and it is the sentence that makes the collection/adaptation
    distinction visible to a recipient.
22. **No implied endorsement** (BY 4.0 §2(b)(1)). Do not present recordists or photographers as
    contributors to, or endorsers of, AviAnki. Do not use Cornell/eBird logos (eBird Data ToU).
23. **Do not put share-alike on the deck.** §2 establishes it is not required. Doing it anyway
    would be a voluntary restriction on AviAnki's own contribution, and would make the deck
    incompatible with any future non-SA content.
24. **Card-side placement — a judgement call, not a licence rule.** §3(a)(2)'s "reasonable
    manner based on the medium, means, and context" gives latitude. The recommendation is:
    compact credit on the **answer** side (where the bird is already named and the card is not
    time-pressured), plus the full deck-level credits note. Putting it on the question side of a
    Photo→Name card leaks the answer where the credit line names the species — so the question
    side, if credited at all, should carry creator and licence only.

### 5.4 eBird-specific obligations

25. **Attribute eBird.org with a link wherever eBird-derived data is used or displayed** (API
    ToU §3) — the deck credits note and the web app footer.
26. **Do not bundle any Macaulay Library / eBird media.** API ToU §2 permits "a single copy …
    for personal and non-commercial use only".
27. **Do not use eBird or Cornell Lab logos** on any derived product (Data ToU).
28. **Resolve the catalog question in #20 before publishing any eBird-derived species list.**
    The Data ToU forbids publicly distributing eBird data "in their original format, either
    whole or in part, in any media, including … on a website", and permits passing on derived
    data only "if these derived data are supplied with the same Terms of Use". Pick option 1, 2
    or 3 from §4.3 — do not let this default.
29. **Send published products to `eBird@cornell.edu`** if eBird data is used (Data ToU, final
    clause).

---

## 6. Quick reference: what each licence demands

| | CC0 1.0 | CC BY 4.0 | CC BY-SA 4.0 | CC BY / BY-SA 3.0 | CC BY-ND 4.0 |
|---|---|---|---|---|---|
| Credit creator | not required | **required** | **required** | **required** | **required** |
| Title | — | optional | optional | **required if supplied** | optional |
| Licence name + URI | — | **required** | **required** | **required, every copy** | **required** |
| Link to source | — | **required if practicable** | **required if practicable** | **required if practicable** | **required if practicable** |
| Copyright + warranty notices | — | **retain if supplied** | **retain if supplied** | **keep intact** | **retain if supplied** |
| Mark modifications | — | **required** | **required** | required for adaptations | **required** |
| Transcode / resize | yes | yes (§2(a)(4)) | yes (§2(a)(4)) | yes | **yes** (§2(a)(4)) |
| Trim to 10 s and **share** | yes | yes | yes, clip stays BY-SA | yes | **no / AMBIGUOUS** — exclude |
| Obliges the deck as a whole | no | no | **no** (§2) | **no** (3.0 §4(a) explicit) | n/a |
| In AviAnki's allowlist | ✅ | ✅ | ✅ | ✅ | ❌ |

---

## 7. Open questions and flagged ambiguities

1. **eBird species lists in a published catalog.** The sharpest open issue. The Data Access ToU
   text does not obviously permit it and the derived-data escape attaches a non-commercial,
   research-and-education restriction to whatever carries it. Belongs to #20. **Do not assume
   this one resolves itself.**
2. **iNaturalist licence versions.** `license_code` is unversioned. The photo page links 4.0 for
   a `cc-by` photo, which is strong evidence but not a statement of policy, and says nothing
   about photos licensed years ago. Since 3.0 mandates the title and 4.0 does not, the version
   changes what a compliant credit line must contain. Resolve by asking iNat directly, or fall
   back to the strictest reading (include the title, always) so the record is compliant under
   either version.
3. **Is a 10-second excerpt an adaptation?** Unresolvable from the licence text; the CC FAQ
   argues both sides and notes jurisdictional variation. Immaterial for CC0/BY/BY-SA (all
   licence the trim either way). Material only for ND, which is why ND is excluded rather than
   reasoned about.
4. **Bare CC-BY-ND volume on xeno-canto — unmeasured.** Needs an XC account key to count. The
   exact-match allowlist makes the answer irrelevant to correctness, but it is worth knowing
   how much material the filter is discarding.
5. **GitHub Actions egress IPs vs. iNaturalist's "please use a single IP address".** Almost
   certainly fine for a weekly single-job build, but it is a written request AviAnki cannot
   literally honour. Mention it in the email to iNat rather than hoping.
6. **Terms drift.** eBird's API ToU says Cornell "reserves the right to change these API Terms at
   any time without prior notice"; iNat and WMF reserve similar rights. `source_terms_version`
   in the per-asset record exists so a future reader knows which text was relied on. Re-read all
   six documents before any major release.
7. **Not researched here:** GDPR/personality rights in photos containing identifiable people
   (Commons Reuse flags this as a non-copyright restriction), and whether the deck's own
   compilation attracts a database right in the EU.
