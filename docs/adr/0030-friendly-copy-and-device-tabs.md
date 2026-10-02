# 0030 — Friendlier wording, device tabs, and a study guide you can read before building

**Status:** Accepted, 2026-10-01 · **Amends:** [0016](0016-last-mile.md) (the steps move into device tabs, and are readable before the build) · **Related:** [0006](0006-browser-builds-the-apkg.md), [0012](0012-attribution.md) (the study text stays in the deck description) · **Closes:** #80

## Context

Three things were wrong with the website's wording and layout.

1. The "how to study" steps appeared only after a deck was built. Someone deciding whether to bother could not see what they would be asked to do.
2. The steps for the detected device came first and the others sat in a collapsed *"On a different device?"* section. Someone on a laptop who wanted to read the phone steps, or an iPhone user whose device was guessed wrongly, had to find that section.
3. The copy was curt ("Install it.", "Pick a state.") and the iPhone steps read as "pay US$24.99, or else a workaround".

## Decision

### One study guide, shown twice

`web/js/lastmile.js` exports `renderStudyGuide(container, platform, {id, heading})`. The **first screen** has it under the form (heading *"How to study your deck"*), reachable from the line under **Build my deck** (*"See how studying works"*). The **Done screen** has the same component (heading *"Next, open it in Anki"*). The words live in one place, so the two cannot drift apart. The `id` prefix keeps the two copies' element ids unique. The *"See how studying works"* link scrolls to the heading and focuses it, but does not change `location.hash`, because the hash carries the theme ([0028](0028-card-themes.md)).

### Device tabs

The guide is an ARIA tabs widget (WAI-ARIA Authoring Practices, *Tabs*): `role="tablist"` named *"Your device"*, `role="tab"` buttons with `aria-selected` and `aria-controls`, and `role="tabpanel"` panels with `aria-labelledby` and `tabindex="0"`. Only the selected tab is in the Tab order. Left and Right move between tabs and wrap, Home and End jump to the ends, and a tab is selected as soon as it gets focus. The tabs are **iPhone & iPad**, **Android** and **Computer**, in that order. The tab for the detected device is selected first, and anything undetected falls back to **Computer**, so the box is never blank. There is no *"On a different device?"* fold any more: every device is one tap away.

### The iPhone & iPad tab has two equal paths, free first

The two paths have the same heading level and the same styling, and the intro calls them *"two good ways"*.

1. **Free: study on AnkiWeb.** Anki on a computer, sync to a free AnkiWeb account, then study at ankiweb.net in Safari. The lead says why the computer is needed, once.
2. **Paid: the AnkiMobile app.** US$24.99, paid once, which *"helps fund Anki's development"* (the phrase apps.ankiweb.net uses). No computer needed.

The free path has more steps, because it really does involve more. We did not pad the paid path or squeeze the free one to make them look alike. We never assume people want to pay, and the free path never mentions the price.

### The words

- **One action per step**, or two that happen on the same screen ("Double-click your deck file, then click **Import**").
- **Button names exactly as the apps show them**, in bold, checked against the apps' source and manuals (findings below): **Import**, **Sync**, **Yes**, **Study Now**, **Add**, **Share**, **Show Answer**, **Good**, **Again**.
- **One name per thing.** The download is the *deck file* everywhere. A *place* is what you choose (the select still says *state or province*). *Deck* is explained once, in the line under the headline (*"a deck of flashcards"*), and *Anki* once, in the line under the button (*"a flashcard app that's free on computers, Android and the web"*).
- **American spelling**, matching the site's existing *Customize* (so *Colors*, not *Colours*, in the custom theme). The deck's own text, which the CLI shares, is unchanged apart from the study guidance below.
- **Plain labels.** *Advanced* became *More options*. The subdeck checkbox says what it does (*"Give this place its own deck inside AviAnki, which helps if you make more than one"*) instead of naming the feature.
- **Errors say what happened and what helps** (*"Your device ran out of memory. Closing other tabs, or choosing Standard under More options, usually helps."*), and the Building screen asks people to keep the page open, because a phone that leaves the tab can kill the build.

The *What you'll see* box is the deck description's study guidance, word for word ([0012](0012-attribution.md)); a test asserts they are equal. Its third line was wrong: it said Anki shows **20 new birds a day**, but Anki's limit counts cards, and a bird has a photo card and an audio card by default. It now says *"Anki starts you on 20 new cards a day so you're never swamped. The rest arrive day by day. That's normal, not broken."* in both places. This is description text, not identity ([0009](0009-note-identity.md)); re-importing updates it.

### Examples we followed

- **Tailscale and Signal download pages.** Tabs for the operating system with the visitor's own preselected, and one calm line per platform with a plain verb ("Get Anki for Windows, Mac or Linux. It's free."). The price is stated plainly, next to the thing, and not pushed.
- **Duolingo and Notion onboarding.** Short "you" language and a one-line promise of what you'll get before any choice (*"Pick a place, and we'll make you a deck of flashcards of its birds, with photos and sounds."*). An empty field reads as a nudge (*"Pick your state or province, and we'll find your birds."*).
- **Apple's setup and support articles.** One action per numbered step, the button's exact name in bold, and the place to find something named (*"In the Files app, open Downloads and tap your deck file."*).
- **The GOV.UK content style guide.** Plain words, short sentences, no jargon left unexplained, and cutting any word that doesn't help someone do the task.

## Findings: what the apps actually do

We checked each step against the official manuals and, where a manual was silent or out of date, against the apps' own source code (the English UI strings). Checked 2026-10-01.

- **AnkiWeb cannot import a deck file.** The Anki Manual: *"It's not currently possible to add shared decks directly to your AnkiWeb account. You need to first import them to the desktop app, AnkiMobile, or AnkiDroid, then synchronize to upload the decks to AnkiWeb."* ([Getting Started, Shared Decks](https://docs.ankiweb.net/getting-started.html#shared-decks)). A forum answer quoting AnkiWeb's own help says the same ([AnkiWeb without app](https://forums.ankiweb.net/t/ankiweb-without-app/20820)). So the free iPhone route needs a computer once.
- **Opening a deck file on a computer.** The manual: *"Double-click the downloaded package to import it into Anki, or go to File > Import."* (same page). Since Anki 23.10 that opens an import screen whose button is **Import** (`actions-import` in [`ts/routes/import-page/StickyHeader.svelte`](https://github.com/ankitects/anki/blob/main/ts/routes/import-page/StickyHeader.svelte)). The earlier copy skipped this click.
- **The first sync asks "Replace it with local collection?", with Yes and No, not "Upload".** The manual describes the choice loosely (*"Anki will ask you if you want to upload or download … choose **Upload**"*, [Syncing](https://docs.ankiweb.net/syncing.html#setup)). In the app, when AnkiWeb is empty and the computer has cards, the sync code needs a full upload ([`rslib/src/sync/collection/meta.rs`](https://github.com/ankitects/anki/blob/main/rslib/src/sync/collection/meta.rs)), and [`qt/aqt/sync.py`](https://github.com/ankitects/anki/blob/main/qt/aqt/sync.py) asks `sync-confirm-empty-upload`: *"AnkiWeb collection has no cards. Replace it with local collection?"* with the default **Yes** and **No** buttons. A dialog with an **Upload to AnkiWeb** button appears only when both sides already have different cards, and choosing it there overwrites the account. So the step quotes the question and says **Yes**, and never says *Upload*. The sign-in dialog asks for **Email** and **Password** and links to sign-up (`sync.ftl`), so the step says *"sign in to AnkiWeb, or sign up there for free"*.
- **Studying at ankiweb.net.** AnkiWeb's [terms](https://ankiweb.net/account/terms): *"You may access AnkiWeb directly through your browser"*, and the Syncing manual says AnkiWeb lets you *"study online"*. We found no statement either way about offline use of the website, so the note says only that it is a website and needs a connection.
- **AnkiMobile price and what it funds.** The [App Store listing](https://apps.apple.com/us/app/ankimobile-flashcards/id373493387) shows US$24.99 and says *"Sales of this app support the development of both the computer and mobile version"*. [apps.ankiweb.net](https://apps.ankiweb.net/): *"AnkiMobile is the official iOS app and all purchases help fund Anki's development."* The AnkiWeb terms add that AnkiWeb's hosting *"costs are supported by sales of the iPhone app"*.
- **AnkiMobile opens a deck file from Files with Share.** *"Tap on the file. Locate the 'Open In' or 'Share' icon, and select AnkiMobile"* ([AnkiMobile manual, Shared Decks](https://docs.ankimobile.net/shared-decks.html)). Safari saves downloads to **Downloads** in the Files app, so the steps say where to look. Tapping a deck *"will switch to study mode"* ([Deck List](https://docs.ankimobile.net/deck-list.html)).
- **AnkiDroid asks to add the file, and the button is Add.** The [AnkiDroid manual](https://docs.ankidroid.org/manual.html) says apkg files *"are automatically associated with AnkiDroid"* and to *"click OK"*, but that text is out of date: the app shows *"Add “…” to collection? This may take a long time"* with an **Add** button (`import_dialog_message_add` and `import_message_add` in AnkiDroid's [`02-strings.xml`](https://github.com/ankidroid/Anki-Android/blob/main/AnkiDroid/src/main/res/values/02-strings.xml), used by `ImportDialog.kt`).
- **Desktop and AnkiDroid are free.** apps.ankiweb.net: *"The free computer version is available for all major platforms"* and *"AnkiDroid for Android is free and developed by contributors."*
- **20 new cards a day is Anki's default.** `new_per_day: 20` in [`rslib/src/deckconfig/mod.rs`](https://github.com/ankitects/anki/blob/main/rslib/src/deckconfig/mod.rs). An AviAnki deck uses the collection's Default preset ([0016](0016-last-mile.md) keeps Anki's defaults), so a new user sees 20 new *cards* a day. The manual's [New Cards/Day](https://docs.ankiweb.net/deck-options.html#new-cardsday) explains why the limit exists.
- **Button names while studying.** **Study Now**, **Show Answer**, **Again** and **Good** are the manual's ([Studying](https://docs.ankiweb.net/studying.html)) and the app's (`studying.ftl`).

### Is there a free, browser-only path for iPhone?

We found none that goes through official Anki. Third-party sites claim to import Anki decks in a browser (for example [Repetrax](https://repetrax.com/blog/how-to-import-anki-deck-to-web)). We did not evaluate any of them for price, privacy or licence, and they do not sync with Anki. A reviewer built into AviAnki is a PRD §10 non-goal ([0016](0016-last-mile.md)). We have not built or recommended either.

### Decision: do not publish AnkiWeb shared decks

Publishing our decks as AnkiWeb shared decks would not help iPhone users, which was the point, and our licences don't fit AnkiWeb's terms:

- **A shared deck still has to be imported in an app.** The manual above says so. A free iPhone user would gain nothing over the file we already give them.
- **The licences conflict.** AnkiWeb's [terms](https://ankiweb.net/account/terms) give everyone who downloads a shared deck a *"Shared Deck License"* that is *"for personal use only, and the deck may not be redistributed, re-uploaded, published, or used for any other purposes"*. Most of our photos and recordings are CC BY or CC BY-SA, from many authors, and both licences forbid adding restrictions like that when you share the work ([0012](0012-attribution.md)). The sharer must also *"assert that it is entirely your own work, or that you have obtained a license"*. (We read the terms page rendered in a browser, last updated 2018-10-17.)
- **One shared deck cannot carry the options.** Tier, month, cards and theme are the whole point of the builder.
- **Little-downloaded decks are removed.** The terms: *"The system will automatically remove shared decks that receive very few downloads after 3 months."* A long tail of regions would keep vanishing.

`--ebird` decks are personal use and must never be republished anywhere ([0017](0017-cli-reads-the-catalog.md)). If AnkiWeb's terms change, this can be revisited in a new ADR with a licence review.

## Consequences

- The first screen is longer by one section and one line. The shell stays well under its 150 KB gzipped budget (`test_web_shell_budget.py`).
- Every tab, link and summary still has a tap target of at least 44px on a phone (tested for all three tabs on both screens).
- The browser tests cover the tab roles, keyboard use, the detected tab (Android, iPhone, an iPad that says it is a Mac, desktop, nothing), the guide being readable before a build, and the button names the findings rest on (**Import**, **Add**, the *"Replace it with local collection?"* question with **Yes**, and no *Upload*).
- The deck description's third line changed (*cards*, not *birds*). Nothing in the CLI's options changed, and the README does not quote the site's copy.
- Some steps rest on source code and manuals, not on a real device: the AnkiMobile Share sheet from Files, AnkiWeb's deck list on an iPhone (*"Tap AviAnki"*), and where Safari puts downloads. Re-check them against the apps when Anki or iOS changes these screens.
- AnkiWeb deletes decks in accounts not used for 6 months (terms, *Account Expiry*). The free path doesn't say so; anyone studying there uses the account, so it rarely matters.
