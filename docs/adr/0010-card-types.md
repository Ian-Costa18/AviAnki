# 0010 — Photo and Audio cards by default, Photo+Audio optional, Description deferred

**Status:** Accepted, 2026-09-28 · **Tickets:** [#9](https://github.com/Ian-Costa18/AviAnki/issues/9), [#23](https://github.com/Ian-Costa18/AviAnki/issues/23), [#25](https://github.com/Ian-Costa18/AviAnki/issues/25), [#32](https://github.com/Ian-Costa18/AviAnki/issues/32)

## Decision

### Card types

| Card type | Front | Default | Made when |
|---|---|---|---|
| Photo → Name | the photo | **on** | the species has a photo |
| Audio → Name | one recording | **on** | the species has audio |
| Photo + Audio → Name | photo and recording | off | both exist |
| Description → Name | — | **deferred** | — |

- **Each card type is its own note** with its own one-template note type, so choosing card types just means choosing which notes to build. A species with no audio still gets its photo card. Missing media never removes a species from the deck.
- **Description → Name is deferred, not dropped (#25).** Under the PRD's quality bar, a leaked name makes a card unshippable. For the 29% of species with a colour word in their name, redacting the name also removes the clue that identifies them, and no redactor fixes that. It can come back when there's a way to handle those species, for example by excluding them from this card type.
- **One `Audio` field (#32).** Neither source can tell songs from calls, so the card says *"Who's calling?"*, which covers any vocalisation. The existing CLI's `Call`/`Song` fields go away with the new note types ([0009](0009-note-identity.md)). The note types reserve an `Audio2` field for a second clip later.
- **Randomising between several clips isn't pursued.** The #18 prototype showed that Anki's autoplay queue ignores template JavaScript.

### Selection surfaces (#23)

- **Web:** the default path offers no choice. Under *Advanced*, three checkboxes show the defaults ticked.
- **CLI:** `--cards photo,audio,photo-audio`, defaulting to `photo,audio`. README is updated with it.
- Changing the selection later is additive, so it's the same deck with more or fewer notes.

### Fields, shared by all three note types

`SpeciesId, Name, SciName, Photo, Photo2, Audio, Audio2, Credits`

The front of every card shows only the prompt media. The back shows `Name`, `SciName`, the photo, the audio and the credits ([0012](0012-attribution.md)).

## Consequences

- #30 (`redact_name()` is case-sensitive) no longer blocks shipping the web app, because the web app has no description cards. It's still fixed in the CLI as housekeeping.
