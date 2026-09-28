# 0005 — Commons and iNaturalist supply the media; no Wikipedia or xeno-canto at v1

**Status:** Accepted, 2026-09-28 · **Tickets:** [#13](https://github.com/Ian-Costa18/AviAnki/issues/13), [#14](https://github.com/Ian-Costa18/AviAnki/issues/14), [#15](https://github.com/Ian-Costa18/AviAnki/issues/15), [#31](https://github.com/Ian-Costa18/AviAnki/issues/31) · **Evidence:** branches `research/photo-sources`, `research/inaturalist-audio`, `research/identification-descriptions`

## Context

The research found:

- **Commons lead images** are photos for 99.1% of species and always openly licensed. 10 out of 10 sampled were usable.
- **iNaturalist's top-by-faves photos** were only 3 out of 10 excellent, and just 10% of iNat photos are openly licensed.
- **iNaturalist audio** covers 90–96% of regional species but carries no song/call labels.
- **Commons audio** is thin, but 79% of it is xeno-canto mirrors.
- **Wikipedia's Description section** covers about 80% of species. However, 29% of North American species have a colour word in their name, so redacting the name also removes the feature that identifies them.

The ordering rule, decided in #20, is **freest first**: keyless sources before keyed ones, and less strict licences break ties.

## Decision

| Role | Sources, in order | Count per species |
|---|---|---|
| Photo | Commons (the en.wikipedia lead image) → iNaturalist | 1 at v1 |
| Audio | Commons → iNaturalist | 1 at v1 |
| Description | none at v1 | — |

- **One photo, not three.** The Commons lead image is the only candidate with measured quality. An iNat photo is used **only** when Commons has nothing usable, and even then it has to be research grade, not captive, with at least 2 identification agreements. Additional photos for variety are deferred. The note type reserves a `Photo2` field so adding them later doesn't need a note-type migration.
- **No xeno-canto API (#31: no).** It would add a keyed source, an account, and an email to xeno-canto before the first build, all to get labels that v1 doesn't use ([0010](0010-card-types.md)). Commons' xeno-canto mirrors are still used as ordinary Commons audio.
- **No Wikipedia descriptions at v1.** Description→Name is deferred ([0010](0010-card-types.md)), and an answer-side description isn't worth a third source and a CC BY-SA text credit at v1.

## Consequences

- There are two asset sources, both keyless, so the pipeline has no secrets for media.
- Species with no usable audio get no audio cards, which the PRD's "absence is acceptable" rule allows. Expect gaps in seabirds and waterfowl.
