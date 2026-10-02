# 0030 — Friendlier wording, device tabs, and a study guide you can read before building

**Status:** Accepted, 2026-10-01 · **Amends:** [0016](0016-last-mile.md) (the steps move into device tabs, and are readable before the build) · **Related:** [0006](0006-browser-builds-the-apkg.md), [0012](0012-attribution.md) (the study text stays in the deck description) · **Closes:** #80

## Context

Three things were wrong with the website's wording and layout.

1. The "how to study" steps appeared only after a deck was built. Someone deciding whether to bother could not see what they would be asked to do.
2. The steps for the detected device came first and the others sat in a collapsed *"On a different device?"* section. Someone on a laptop who wanted to read the phone steps, or an iPhone user whose device was guessed wrongly, had to find that section.
3. The copy was curt ("Install it.", "Pick a state.") and the iPhone steps read as "pay US$24.99, or else a workaround".

## Decision

### One study guide, shown twice

`web/js/lastmile.js` exports `renderStudyGuide(container, platform, {id, heading})`. The **first screen** has it under the form (heading *"How to study your deck"*), reachable from the line under **Build my deck** (*"See how studying works"*). The **Done screen** has the same component (heading *"Now, open it in Anki"*). The words live in one place, so the two cannot drift apart. The `id` prefix keeps the two copies' element ids unique. The *"See how studying works"* link scrolls to the heading and focuses it, but does not change `location.hash`, because the hash carries the theme ([0028](0028-card-themes.md)).

### Device tabs

The guide is an ARIA tabs widget (WAI-ARIA Authoring Practices, *Tabs*): `role="tablist"` named *"Your device"*, `role="tab"` buttons with `aria-selected` and `aria-controls`, and `role="tabpanel"` panels with `aria-labelledby` and `tabindex="0"`. Only the selected tab is in the Tab order. Left and Right move between tabs and wrap, Home and End jump to the ends, and a tab is selected as soon as it gets focus. The tabs are **iPhone & iPad**, **Android** and **Computer**, in that order. The tab for the detected device is selected first, and anything undetected falls back to **Computer**, so the box is never blank. There is no *"On a different device?"* fold any more: every device is one tap away.

### The iPhone & iPad tab has two equal paths, free first

The paths have the same heading level, the same styling and the same length.

1. **Free, needs a computer once.** Anki on a computer, sync to AnkiWeb, then study at ankiweb.net in Safari.
2. **Paid app, phone only.** AnkiMobile, US$24.99, which supports Anki's development, straight on the phone.

We never assume people want to pay, and the free path never mentions the price. See the findings below for why the free path needs the computer.

### Tone

The copy is friendly, plain and short, with one action per step and no curt imperatives. The models we followed, and what we took from each:

- **Tailscale and Signal download pages.** One calm line per platform and a plain verb ("Get Anki for Windows, Mac or Linux. It's free."). The price is said in the same breath as the thing, not hidden or pushed.
- **Duolingo and Notion onboarding.** A short reason in "you" language and an encouraging heading ("Pick your state or province, and we'll find your birds."), so an error or an empty field reads as a nudge.
- **Apple setup copy.** One thing per step and the name of the button in bold, so the words on the screen and the words in the steps match.

Apply this to everything user-facing: headings, hints, button labels, errors and status text. "Install it." became "Get Anki on a computer. It's free." Errors say what happened and what helps ("Your device ran out of memory. Closing other tabs, or choosing the Standard size, usually helps."). We avoided words that differ between British and American spelling ("recognise", "colour" in prose we touched), and kept the existing site's American spelling elsewhere.

The *What you'll see* text is kept word for word, because it is also the deck description's study guidance ([0012](0012-attribution.md)) and a test asserts they are equal.

## Findings: can a deck be opened without an app?

We checked the official manuals before writing the iPhone steps. We looked for a way to get an `.apkg` onto an iPhone with no app and no computer.

- **AnkiWeb cannot import a deck file.** The Anki Manual says: *"It's not currently possible to add shared decks directly to your AnkiWeb account. You need to first import them to the desktop app, AnkiMobile, or AnkiDroid, then synchronize to upload the decks to AnkiWeb."* ([Getting Started, Shared decks](https://docs.ankiweb.net/getting-started.html)). A community moderator says the same: ["I don't think you can import into AnkiWeb"](https://forums.ankiweb.net/t/i-want-to-import-a-deck-to-the-app-withusing-a-desktop/40198).
- **So the free iPhone route needs a computer once.** Import into Anki on a computer, **Sync** to upload to AnkiWeb (choose *Upload* if asked), then study at ankiweb.net in Safari ([AnkiMobile syncing](https://docs.ankimobile.net/syncing.html) describes the same upload-then-download flow, and warns to let media finish syncing). That is what the free path says.
- **AnkiMobile opens a file directly.** *"Tap on the file. Locate the 'Open In' or 'Share' icon, and select AnkiMobile"* ([AnkiMobile, Shared decks](https://docs.ankimobile.net/shared-decks.html)).
- **The price funds Anki.** [apps.ankiweb.net](https://apps.ankiweb.net/): *"AnkiMobile is the official iOS app and all purchases help fund Anki's development."* The [FAQ](https://faqs.ankiweb.net/how-can-i-donate.html): *"the proceeds from it go towards supporting Anki's development."* The same page says AnkiDroid is free and developed by contributors. That is why the paid path says "supports Anki's development" and nothing pushier.
- **AnkiDroid opens `.apkg` files directly.** It is associated with the extension and asks to confirm the import: tap **Add** ([AnkiDroid manual](https://docs.ankidroid.org/manual.html)). That is the Android tab.
- **Studying on AnkiWeb in Safari needs a connection.** Community reports call it workable but clunky, and it has no offline mode. The note under the free path says an internet connection is needed. We found no official statement on this beyond the sync manuals, so the wording is cautious.

### Is there a free, browser-only path for iPhone?

We found none that goes through official Anki. Third-party sites claim to import Anki decks in a browser (for example [Repetrax](https://repetrax.com/blog/how-to-import-anki-deck-to-web)). We did not evaluate any of them for price, privacy or licence, and they do not sync with Anki. A reviewer built into AviAnki is a PRD §10 non-goal ([0016](0016-last-mile.md)). We have not built or recommended either.

### Decision: do not publish AnkiWeb shared decks now

Publishing our decks as AnkiWeb shared decks would not help iPhone users, which was the point:

- **A shared deck still has to be imported in an app.** The manual above says so. A free iPhone user would gain nothing over the file we already give them.
- **Licensing needs care.** Our media are CC BY and CC BY-SA from many authors. AnkiWeb's [terms](https://ankiweb.net/account/terms) have the sharer assert the deck is entirely their own work or licensed for sharing, grant AnkiWeb a licence, and allow no extra restrictions, and they threaten removal for infringement. We could meet that, but it needs a deliberate review of attribution on AnkiWeb's page, not a side effect of a copy change. (The terms page is rendered by JavaScript, so we read it through a search excerpt, not a direct fetch. Check it again before acting.)
- **One shared deck cannot carry the options.** Tier, month, cards and theme are the whole point of the builder.
- **Little-downloaded decks are removed** after about three months, so a long tail of regions would keep vanishing.

**Possible follow-up:** shared decks for popular catalog regions only, with their own ADR and a licence review. Never for `--ebird` decks, which are for personal use and must not be republished ([0017](0017-cli-reads-the-catalog.md)).

## Consequences

- The first screen is longer by one section. The shell stays well under its 150 KB gzipped budget (`test_web_shell_budget.py`).
- Every tab, link and summary still has a tap target of at least 44px on a phone (tested for all three tabs on both screens).
- The browser tests cover the tab roles, keyboard use, the detected tab (Android, iPhone, an iPad that says it is a Mac, desktop, nothing) and the guide being readable before a build.
- Nothing in the CLI changed, and the README does not quote the site's copy.
- Some claims rest on the manuals and not on a real iPhone: the sign-in and *Upload* prompts, and AnkiMobile's *Share* sheet. They should be re-checked against the apps when Anki releases a new major version.
