# 0032 — After 1.0: fields may be appended; a real break is a new card generation

**Status:** Accepted, 2026-10-04 · **Amends:** [0009](0009-note-identity.md), [0027](0027-ioc-name-field.md) (what the freeze covers after 1.0)

## Context

[0009](0009-note-identity.md) froze the identity and said a changed field list means new seeds. [0027](0027-ioc-name-field.md) then appended a field without new seeds, and said the freeze "resumes at the 1.0 announcement". Read together, that sounds as if the cards can never gain a field after 1.0 without wiping every learner's progress. That is stricter than Anki requires, and it would stop the cards from growing.

What Anki actually uses to recognise a learner's cards is three ids: the deck id, the note type ids (from the model seeds) and each note's GUID (from the species id and the card type). Templates, CSS and field contents are not part of that. 0027's acceptance test also showed that a field appended to the end updates the note types in place: no card is added or removed, and the review history is kept.

## Decision

Changes fall into three kinds.

| Change | Allowed in | What the learner sees |
|---|---|---|
| Templates, CSS, themes, wording, field contents, media, new species or regions | any release | Cards update on the next import. Progress is kept. |
| **A field appended to the end** of the field list | a minor release | Progress is kept. Someone who syncs gets Anki's one-time "which side do you keep?" prompt, because a changed note type is a full sync. |
| Anything else that touches the identity: a model seed, the deck id, the GUID function or its card-type strings, or reordering, renaming or removing a field | a major release, as a **new generation** | A new set of cards with no review history, next to the old ones. |

**Appending a field** needs, in the same pull request:

- a new ADR that says what the field is for;
- the field list literal in `tests/deck/test_identity.py` updated, with the existing fields in their positions;
- an acceptance test that imports a deck with the old field list, answers cards, imports the new one, and finds the same cards with their history ([0027](0027-ioc-name-field.md)'s test is the model);
- a changelog entry that mentions the sync prompt.

A new field must be empty-safe: a note built before it existed has it blank, and the card must still read correctly.

**A generation** is one set of model seeds and one GUID namespace. The seeds carry its number: today's are `AviAnki_Photo_v2`, `AviAnki_Audio_v2` and `AviAnki_PhotoAudio_v2`, so the current generation is 2. A new generation changes the seeds and the GUIDs together. If only the seeds changed, a new note would have the GUID of a note the learner already has under another note type, and Anki skips such notes on import.

When a generation is replaced:

- The release that brings the new one is a major version. Its notes say that the new cards start fresh and that the old ones are untouched.
- The old generation is **deprecated**, not removed. The CLI and the website can still build it, and it keeps getting catalog updates (new photos, recordings, species and names) and fixes. New card features go to the current generation only.
- A deprecated generation is removed no sooner than six months after the release that deprecated it, and the removal is announced in the changelog one release ahead.

The table of generations lives in [CONTRIBUTING.md](../../CONTRIBUTING.md#card-generations) and is updated in the release that changes it.

## Consequences

- The cards can keep growing after 1.0. Most ideas need a template change or an appended field, and neither costs a learner anything but one sync prompt.
- 0009's rule stands for a real break: do it on purpose, with a major version and a release note, and don't try to migrate review history.
- Nothing is built for this yet. There is one generation, so the CLI and the website have no generation option. The first release that adds a generation 3 also adds the way to choose generation 2.
- `Photo2` and `Audio2` stay reserved, so a second photo or recording needs no new field.
