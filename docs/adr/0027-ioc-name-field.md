# 0027 — The IocName field

**Status:** Accepted, 2026-10-01 · **Amends:** [0009](0009-note-identity.md) (the field list) · **Related:** [0025](0025-card-design.md) (the IOC tag), [0026](0026-north-american-common-names.md) (eBird names on cards)

## Context

[0026](0026-north-american-common-names.md) put eBird's English names on the cards. For 40 birds the IOC English name is a genuinely different name for the same bird (Grey Plover for Black-bellied Plover, Rock Dove for Rock Pigeon). [0025](0025-card-design.md) planned a small outlined "IOC" tag above the name for those birds, so a learner who meets the other name elsewhere can match it.

The tag needs somewhere to live in the note. The field list is frozen by [0009](0009-note-identity.md), but AviAnki hasn't been announced as 1.0 yet, only the maintainer has decks, and the maintainer approved the change. The alternative is to put the tag's HTML inside `SciName`. That would mix markup into a plain-text field for good, and every later change to the tag would mean rewriting data.

## Decision

- **`IocName` is appended as the ninth field**, after `Credits`. The other eight keep their names and positions.
- **Everything else in the identity is unchanged:** the deck name and id, the three model seeds and ids, the model and template names, the card types and the note GUIDs. 0009 says a changed field list means new seeds. Not here: new seeds would create three new note types next to the old ones, instead of updating them.
- **The field holds the IOC English name only where it differs from `Name`.** It's empty for every other bird. The data is the `ioc_name` column in `species.csv` (the last column), and an optional `ioc_name` key on the species entry in the published catalog. The key is omitted when empty. Old catalogs without it still load, and the manifest `format` doesn't change, because adding an optional key doesn't ([web-app-spec §5](../web-app-spec.md)).
- **Only the back shows it**, inside `.names` above the name: `{{#IocName}}<div class="ioc"><span class="ioc-tag"><b>IOC</b> {{IocName}}</span></div>{{/IocName}}`. A front never contains it, because it would give the answer away. A test checks this.
- **`--ebird` species built live have none.** They are not in `species.csv`.
- **The freeze in 0009 resumes at the 1.0 announcement.** After that, any change to the identity needs a new ADR and a major version, as 0009 says.

## Consequences

- Importing a 0.10 deck over a deck built before this change makes Anki update the three AviAnki note types in place: it adds the `IocName` field and the new back. The acceptance test imports a deck with the old eight-field note types, answers cards, then imports the nine-field deck. No card or note is added or removed, card ids and GUIDs are the same, and the review history is kept. Anki asked nothing during the import.
- Changing a note type's fields is a schema change, so Anki's next AnkiWeb sync asks which side to keep (a full sync). This only affects someone who already imported a pre-change deck and syncs.
- The tag shows on the 40 birds after the next catalog build publishes `ioc_name`. Until then the field is empty and the cards look as they did.
- A catalog build carries `ioc_name` through from `species.csv`, and `--update-species-csv` keeps it when it rewrites the file.
