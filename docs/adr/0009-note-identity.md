# 0009 — One `AviAnki` deck; GUID = f(species id, card type); the old CLI identity is broken on purpose

**Status:** Accepted, 2026-09-28 · **Ticket:** [#35](https://github.com/Ian-Costa18/AviAnki/issues/35) · **Implements:** PRD §6

## Decision

- **Deck name:** the literal string `AviAnki`. With the advanced subdeck option on, it's `AviAnki::<Region name>`.
- **Note GUID:** `genanki.guid_for("avianki", species_id, card_type)`. The browser uses the same function, ported from the prototype.
  - `species_id` is the minted id ([0008](0008-species-and-region-identity.md)).
  - `card_type` is one of `photo`, `audio` or `photo_audio`. **These strings are frozen**, and the test suite pins them.
- **Note type ids:** `md5` of the seeds `AviAnki_Photo_v2`, `AviAnki_Audio_v2` and `AviAnki_PhotoAudio_v2`. The seeds are frozen too. Changing a field list means new seeds and a new ADR.
- **Migration: none. The break is accepted** (the user decided this on 2026-09-28). Decks built by CLI ≤ 0.9 seed both the deck and the GUIDs from the location, so they won't match. The release that ships this is **1.0.0**, and its release notes tell existing users that the new deck starts fresh and the old one can be deleted or kept.
- **Renames don't break identity.** A rename changes `species.csv`'s name column, not the id. The next import updates the displayed name, because Anki updates the fields of existing GUIDs when the incoming note is newer.

## Consequences

- *You learn a bird once.* Changing tier, region, card type or catalog version, or building in several parts, never duplicates a note.
- This precedent applies to any future identity change: break it on purpose, with a major version bump and a release note, rather than trying to migrate.
