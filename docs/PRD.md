# AviAnki — Product Requirements

**Status:** Accepted — 2026-08-24
**Resolves:** [#12 · PRD: who AviAnki is for and what done looks like](https://github.com/Ian-Costa18/AviAnki/issues/12)
**Part of:** [Map: AviAnki as a static web app](https://github.com/Ian-Costa18/AviAnki/issues/6)

This document exists so that later tickets stop re-litigating two questions: **what counts as acceptable friction**, and **what counts as a good card**. It is the arbiter for both.

Where a design decision conflicts with this document, either this document wins or it gets amended in the open. It does not get quietly ignored.

---

## 1. Who AviAnki is for

**A bird watcher who has never used Anki.**

They came for birds. They have no GitHub account, no API keys, no terminal, and no idea what `US-MA` means. Spaced repetition is not something they asked for — it is an implementation detail they now have to live with.

They are **not**:

- an existing Anki user who happens to bird (a real but tiny audience, and one that needs nothing built for them)
- a developer
- someone we are recruiting into the Anki ecosystem

That last point matters. **Anki is a delivery vehicle, not the product.** The product is *learning to identify the birds near you*. Anki is currently the best way to deliver that, and it may not always be — a purpose-built reviewer is a plausible future.

> **Consequence — the catalog is the durable asset.**
> The media catalog must not be shaped by `.apkg`'s needs. The deck builder is one consumer of the catalog, not its reason for existing. This is cheap to honour now and expensive to retrofit, and it binds [#28 (catalog layout)](https://github.com/Ian-Costa18/AviAnki/issues/28) and [#20 (source contract)](https://github.com/Ian-Costa18/AviAnki/issues/20).

## 2. What AviAnki owns

**We own the card. We do not own the schedule.**

| Ours | Not ours |
| --- | --- |
| Which photo, and whether it shows the bird | When a card is next shown |
| Whether the audio is audible and the bird is in it | Difficulty curve and card ordering |
| Whether the description gives the answer away | Confusion-pair sequencing |
| Whether the prompt is answerable at all | Retention tracking |
| Attribution, correctness, licensing | New-cards-per-day and deck options |

The north star is **learning**, not decks delivered. That is not the scope — scheduling and pedagogy-over-time are explicitly out (§10) — but it is the tiebreaker:

> **When a decision trades card quality against deck size, quality wins.**

**Success is defined at first review, not at download.** A user who downloads a file and never sees a card is a product failure, not a user failure. This makes the path from *download* to *first card* a first-class design problem (§4).

## 3. Two audiences, two surfaces

The web app and the CLI serve **different people** and are allowed to diverge.

| | Web app | CLI |
| --- | --- | --- |
| **User** | The bird watcher of §1 | Maintainers, CI, and people comfortable in a terminal |
| **Assumes** | A browser | `uv`, `ffmpeg`, a terminal, sometimes an API key |
| **May stay technical** | No | **Yes, indefinitely** |
| **Geographic scope** | North America ([#11](https://github.com/Ian-Costa18/AviAnki/issues/11)) | Unrestricted |

Making the CLI non-technical is a second product — it would mean solving region selection twice, shipping `ffmpeg`, and eliminating the API key. The web app exists to *be* the non-technical path. The CLI stays flag-heavy and fast, and that is an asset.

## 4. First run, end to end

This is what success looks like. Each step is a place the user can be lost.

1. **Lands on the site.** No account, no install prompt, no permission dialog. One line explaining what this is.
2. **Answers one question: *where are you?*** Mechanism is [#19](https://github.com/Ian-Costa18/AviAnki/issues/19)'s to decide; the constraint is that it is the *only* required decision.
3. **Clicks Build.** Progress that names what it is doing, in words a bird watcher understands.
4. **The file downloads** — target under ~30 seconds on a normal connection (§5).
5. **The page tells them what happens next.** They need Anki; here is the link for their platform; here is what to tap when the file opens. This step is currently missing entirely and is the single most likely place to lose someone.
6. **They open the file, and see a bird.**

**Step 6 is the success criterion.** Steps 1–4 completing while step 6 does not is a failure.

## 5. Friction budget

**Exactly one required decision: where the user is.** Everything else is defaulted.

**Nothing is removed, only defaulted.** Card types, species count, season, deck layout and output naming all remain reachable under an advanced disclosure. The default path is one decision; no user is locked out of any capability.

Options are *not* presented up front. "Which card types do you want?" is unanswerable before you have seen a card — a default answers it better than the user can.

**Time budget: under ~30 seconds from *Build* to the file landing**, on a normal home connection.

This is really a **byte** budget. From [#18](https://github.com/Ian-Costa18/AviAnki/issues/18), assembly is nearly free — 20 s for 400 species — so the wait is dominated by media download at roughly **530 KB per species**:

| Species | Media | ~time @ 50 Mbps |
| --- | --- | --- |
| 100 | ~53 MB | ~10 s |
| 400 | ~212 MB | ~35 s + 20 s build |

## 6. Deck identity, and the tiers

### Identity is the bird, not the region

**One deck, named `AviAnki`.** The region selects *which birds get added to it*, and every build is additive. Subdeck layout is available under advanced for anyone who wants it.

```
Note GUID = f(species, card type)
```

**Nothing else.** Not the region, not the tier, not the deck size, not the catalog version.

This is the mechanism behind the promise:

> **You learn a bird once.** Rebuilding never loses progress.

It holds across tier upgrades, catalog refreshes, added card types, and changes of region. [#18](https://github.com/Ian-Costa18/AviAnki/issues/18) proved the mechanism against Anki's own importer: notes deduplicate by GUID, decks match by name, and a re-import of already-known notes reports `duplicate`, leaving existing scheduling untouched.

Region-scoped decks were considered and rejected. **The importer matches GUIDs across the entire collection, not per deck** — so region-scoped decks *require* region-scoped GUIDs, and those duplicate a user's progress every time they cross a state line. The two cannot be mixed: shared GUIDs with per-region decks produce decks with holes where the shared birds should be.

> **This breaks the current CLI.** `cli.py` seeds the GUID with the location (`guid_for(deck_seed, name, "v1_photo")`) and names the deck per region. Both must change, and changing them orphans progress for anyone running the published CLI today. That migration is its own decision, not a side effect of this document.

### Two tiers

| Tier | Contents | Default |
| --- | --- | --- |
| **Standard** | Top ~100 species by local frequency | Yes |
| **Everything** | The whole catalog for the region | No |

Likelihood ordering is the project's actual edge — a beginner's first session should not open on a bird they will never see. Seasonality is therefore a **filter on an already-ordered list**, not a required decision.

Upgrading Standard → Everything is a plain re-import into the same deck. Anki's new-card limit already paces a large deck, so deck size is not the burden it appears to be.

**~400 species is the catalog size for North America ([#11](https://github.com/Ian-Costa18/AviAnki/issues/11)); ~100 is the default *deck* size.** These are different numbers and must not be conflated.

## 7. The card quality bar

Coverage is ragged by nature. [#13](https://github.com/Ian-Costa18/AviAnki/issues/13) found a *behavioural* audio hole — seabirds and waterfowl, with Brown Pelican at zero recordings against 38,232 observations — and [#15](https://github.com/Ian-Costa18/AviAnki/issues/15) found 20% of species have no usable description. Every species arrives with some subset of {photo, audio, description}.

**Each card type has a minimum bar, applied per card type — not per species.** A species missing audio still gets its photo card. A missing clip never costs a species its presence in the deck.

The governing principle:

> ### Absence is acceptable. Wrongness is not.

**Acceptable — ship it:**

- a species with no audio (photo cards only)
- a species with no description (no Description → Name card)
- thin coverage in a rare region
- a deck smaller than the user expected

**Unshippable — never ship it:**

- a photo of the wrong species
- a description that leaks the bird's name
- a card with no answerable prompt
- media with attribution missing or wrong

The asymmetry is deliberate. A missing card costs the user nothing — they never knew it could have existed. A **wrong** card actively teaches them to misidentify a bird, which is worse than not having built the deck at all.

The last item is not a quality issue: [#17](https://github.com/Ian-Costa18/AviAnki/issues/17) established attribution as a licence obligation, so shipping without it is a legal failure.

**Two of these are live today.** [#30](https://github.com/Ian-Costa18/AviAnki/issues/30) (`redact_name()` is case-sensitive) is exactly the name-leak case, and #15 found that 29% of North American species carry a colour word in their own name — so the leak cannot always be redacted away. Under this bar these are **ship-blockers, not polish.**

## 8. Devices

**Mobile is equal to desktop at v1. The phone must be able to build a deck.**

The reasoning is not that phones are fashionable. It is that the phone is where the deck gets *used*, and requiring a desktop build reintroduces a cross-device file handoff — which is itself the most hostile step in the whole flow. Building on the phone deletes that step rather than trying to make it survivable.

Peak JS heap runs at roughly **2× the finished package**, and superlinearly ([#18](https://github.com/Ian-Costa18/AviAnki/issues/18)):

| Tier | Package | Est. peak heap | Phone |
| --- | --- | --- | --- |
| Standard, ~100 sp. | ~53 MB | ~106 MB | must work |
| Everything, ~400 sp. | ~212 MB | ~430 MB | at risk on mid-range |

**Requirements:**

- **Standard must build on any reasonably current phone.**
- **Everything builds incrementally on mobile** — several smaller packages imported in sequence into the same deck. This is nearly free given §6: bird-scoped GUIDs mean four 100-species packages produce exactly the same collection as one 400-species package. No merge logic, no partial-state tracking.
- **If even that will not fly, the app degrades honestly** — it says so before starting, rather than dying at 80%.
- **Making Everything desktop-only is not an option.** It would walk back this section.

[#34](https://github.com/Ian-Costa18/AviAnki/issues/34) is consequently a **prerequisite for the spec**, not a follow-up, and it must validate the incremental path as well as find the ceiling.

## 9. Accepted limitations

Written down deliberately, because an accepted gap behaves very differently from a forgotten one.

- **No route for bird watchers outside North America.** The catalog is NA-only and the CLI demands a terminal. Features may arrive later; this audience is not currently catered to. If non-NA demand appears, that is a **new effort**, not a patch.
- **Anki must be installed by the user.** We link and explain; we do not bundle or automate.
- **Per-deck Anki settings apply to everything**, since there is one deck. A user wanting separate scheduling for a trip list builds subdecks themselves.
- **Species with no open-licensed media are simply absent.** No placeholder, no apology.

## 10. Non-goals

Out of scope for this effort. Not bad ideas — just not this.

- **Review scheduling, difficulty ordering, confusion-pair sequencing.** Anki's job (§2).
- **A custom review UI.** A live idea for a future effort, and the reason §1 keeps the catalog format-neutral. Not part of this spec.
- **Accounts, sync, or any server.** The architecture is static by decision ([#7](https://github.com/Ian-Costa18/AviAnki/issues/7)).
- **A worldwide catalog** ([#11](https://github.com/Ian-Costa18/AviAnki/issues/11)).
- **Making the CLI non-technical** (§3).

## 11. What this document decides for other tickets

| Ticket | What it inherits |
| --- | --- |
| [#19 region selection](https://github.com/Ian-Costa18/AviAnki/issues/19) | One required decision; ~100-species default; season is a filter, not a question |
| [#23 card-type selection](https://github.com/Ian-Costa18/AviAnki/issues/23) | Deck identity answered — same deck, additive notes. Defaults over prompts; all types reachable under advanced |
| [#28 catalog layout](https://github.com/Ian-Costa18/AviAnki/issues/28) | A hard mobile-memory ceiling, and catalog-shape neutrality (§1) |
| [#34 phone build](https://github.com/Ian-Costa18/AviAnki/issues/34) | Promoted to prerequisite; must also validate incremental building |
| [#25 Description → Name](https://github.com/Ian-Costa18/AviAnki/issues/25) | Decidable by §7 — a leaked name is unshippable, absence is fine |
| [#30 redaction bug](https://github.com/Ian-Costa18/AviAnki/issues/30) | Reclassified as a ship-blocker |
| [#22 attribution](https://github.com/Ian-Costa18/AviAnki/issues/22) | Missing attribution is a legal failure, not a cosmetic one |
| [#33 audio ranking](https://github.com/Ian-Costa18/AviAnki/issues/33) | "Is the bird audible?" is the quality bar; quality beats coverage |
