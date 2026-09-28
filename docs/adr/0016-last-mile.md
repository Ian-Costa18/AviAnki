# 0016 — Explain Anki before the build and give per-platform steps after it

**Status:** Accepted, 2026-09-28 · **Ticket:** [#36](https://github.com/Ian-Costa18/AviAnki/issues/36) · **Amends:** PRD §9

## Decision

### Before the build

A single line under the Build button:

> You'll study these in **Anki**, a free flashcard app. We'll show you how once your deck is ready.

It's said once, in plain words, before the wait, and it doesn't come across as a barrier.

### After the download

- **Detect the platform** from the user agent. The steps for the detected platform are shown first, and a collapsed *"On a different device?"* section holds the others. There's no picker.

| Platform | Steps shown |
|---|---|
| Android | Install **AnkiDroid** (free, Play Store link) → tap the downloaded file (or **Share → AnkiDroid**) → tap **AviAnki** → **Study**. |
| iPhone / iPad | **AnkiMobile** costs US$24.99 and funds Anki's development. Install it → tap **Share → AnkiMobile** (or open the file from Files) → **AviAnki**. *Free alternative:* build the deck on a computer, import it into Anki Desktop, sync to a free AnkiWeb account, and study at ankiweb.net in Safari. |
| Windows / macOS / Linux | Install **Anki** (free, apps.ankiweb.net) → double-click the downloaded file → click **AviAnki** → **Study Now**. |

- The page ends with a **"What you'll see"** box:
  > Look at the photo or listen, think of the name, then tap **Show Answer**. Tap **Good** if you knew it and **Again** if you didn't. Anki shows you **20 new birds a day** so you're never swamped. The rest arrive over the next few days. That's normal, not broken.

  The same text goes in the deck description, so a user who closed the page still sees it on their first card ([0012](0012-attribution.md)).

### PRD amendment (§9)

- **iOS has no free native app.** That's an accepted limitation: AviAnki names the cost honestly and points to the free AnkiWeb route. Building a web reviewer to avoid it is a non-goal (PRD §10).
- We don't change Anki's default deck options. The page explains them instead.
