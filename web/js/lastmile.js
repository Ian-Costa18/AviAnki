// Studying the deck (ADR 0016, amended by ADR 0029): which device is this, and how does the deck get
// onto it? `detectPlatform` is pure so the tests can feed it sample user agents. `renderStudyGuide`
// is the one component behind both the Pick screen (before anyone builds anything) and the Done
// screen: ARIA tabs for iPhone & iPad, Android and Computer, the detected device's tab selected, then
// the "What you'll see" box.

const ANDROID = "android";
const IOS = "ios";
const DESKTOP = "desktop";

/**
 * "android", "ios" (iPhone, iPod, iPad) or "desktop" (Windows, macOS, Linux, anything else).
 * iPadOS 13+ sends a Mac user agent, so a "Mac" with a touch screen is an iPad.
 *
 * @param {{userAgent?: string, platform?: string, maxTouchPoints?: number}} nav a slice of `navigator`
 */
export function detectPlatform({ userAgent = "", platform = "", maxTouchPoints = 0 } = {}) {
  if (/Android/i.test(userAgent)) return ANDROID;
  if (/iPhone|iPad|iPod/i.test(userAgent)) return IOS;
  if ((/Macintosh/i.test(userAgent) || platform === "MacIntel") && maxTouchPoints > 1) return IOS;
  return DESKTOP;
}

const link = (text, href) => ({ text, href });
const bold = (text) => ({ text, bold: true });

const ANKIDROID = "https://play.google.com/store/apps/details?id=com.ichi2.anki";
const ANKIMOBILE = "https://apps.apple.com/app/ankimobile-flashcards/id373493387";
const ANKI_DESKTOP = "https://apps.ankiweb.net";
const ANKIWEB = "https://ankiweb.net";

const TABS = [
  { platform: IOS, label: "iPhone & iPad" },
  { platform: ANDROID, label: "Android" },
  { platform: DESKTOP, label: "Computer" },
];

// Text is a list of pieces: plain strings, bold pieces and links. The copy follows ADR 0029: friendly,
// one action per step, and never an assumption that anyone will pay.
const PANELS = {
  [IOS]: {
    intro: ["There are two ways to study on an iPhone or iPad. Pick whichever suits you."],
    paths: [
      {
        title: "Free, needs a computer once",
        lead: ["AnkiWeb, Anki's free website, can't open a deck file on its own, so a computer helps get your deck there. After that, you can study on your phone."],
        steps: [
          ["Get ", link("Anki", ANKI_DESKTOP), " on a computer. It's free."],
          ["On that computer, build your deck on this page and open the file. Anki adds it."],
          ["In Anki, click ", bold("Sync"), " and sign in to ", link("AnkiWeb", ANKIWEB),
            ". You can sign up there for free. If Anki asks, choose ", bold("Upload"), "."],
          ["On your iPhone or iPad, open Safari, go to ", link("ankiweb.net", ANKIWEB), " and sign in."],
          ["Open ", bold("AviAnki"), " to start studying."],
        ],
        note: ["You'll need an internet connection to study this way."],
      },
      {
        title: "Paid app, phone only",
        lead: [link("AnkiMobile", ANKIMOBILE), " is Anki's own app for iPhone and iPad. It costs US$24.99, and that supports Anki's development."],
        steps: [
          ["Get ", link("AnkiMobile", ANKIMOBILE), " from the App Store."],
          ["Find the file you downloaded, tap ", bold("Share"), ", then choose ", bold("AnkiMobile"), "."],
          ["Tap ", bold("AviAnki"), " to start studying."],
        ],
      },
    ],
  },
  [ANDROID]: {
    steps: [
      ["Get ", link("AnkiDroid", ANKIDROID), " from the Play Store. It's free."],
      ["Open the file you downloaded. If your phone asks, choose ", bold("AnkiDroid"), ", then tap ", bold("Add"), "."],
      ["Tap ", bold("AviAnki"), " to start studying."],
    ],
  },
  [DESKTOP]: {
    steps: [
      ["Get ", link("Anki", ANKI_DESKTOP), " for Windows, Mac or Linux. It's free."],
      ["Open the file you downloaded. Anki adds your deck."],
      ["Click ", bold("AviAnki"), ", then ", bold("Study Now"), "."],
    ],
  },
};

// The same words as the deck description (deck/credits.py, ADR 0016), so a closed page loses nothing.
const WHAT_YOULL_SEE = [
  "Look at the photo or listen, think of the name, then tap ", bold("Show Answer"), ". Tap ", bold("Good"),
  " if you knew it and ", bold("Again"), " if you didn't. Anki shows you ", bold("20 new birds a day"),
  " so you're never swamped. The rest arrive over the next few days. That's normal, not broken.",
];

function fill(parent, pieces) {
  for (const piece of pieces) {
    if (typeof piece === "string") parent.append(piece);
    else if (piece.href) {
      const a = document.createElement("a");
      a.href = piece.href;
      a.textContent = piece.text;
      a.rel = "noopener";
      parent.append(a);
    } else {
      const b = document.createElement("strong");
      b.textContent = piece.text;
      parent.append(b);
    }
  }
}

function el(tag, { className, text, pieces, attrs } = {}) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  if (pieces) fill(node, pieces);
  for (const [name, value] of Object.entries(attrs ?? {})) node.setAttribute(name, value);
  return node;
}

function stepList(steps) {
  const list = el("ol");
  for (const pieces of steps) list.append(el("li", { pieces }));
  return list;
}

function buildPanel(id, platform) {
  const { intro, paths, steps } = PANELS[platform];
  const panel = el("div", {
    className: "steps",
    attrs: { role: "tabpanel", id: `${id}-panel-${platform}`, "aria-labelledby": `${id}-tab-${platform}`, tabindex: "0" },
  });
  panel.dataset.platform = platform;
  panel.hidden = true;
  if (intro) panel.append(el("p", { pieces: intro }));
  if (steps) panel.append(stepList(steps));
  paths?.forEach((path, i) => {
    const headingId = `${id}-${platform}-path-${i + 1}`;
    const box = el("section", { className: "path", attrs: { "aria-labelledby": headingId } });
    box.append(el("h4", { text: path.title, attrs: { id: headingId } }));
    box.append(el("p", { pieces: path.lead }), stepList(path.steps));
    if (path.note) box.append(el("p", { className: "hint", pieces: path.note }));
    panel.append(box);
  });
  return panel;
}

/**
 * Fill `container` with the study guide: a heading, a tablist (iPhone & iPad, Android, Computer) with
 * the detected device's tab selected, and the "What you'll see" box. Any other platform falls back
 * to Computer, so there is never an empty box. Tabs follow the WAI-ARIA tabs pattern: Left and Right
 * (wrapping), Home and End move and select; only the selected tab is in the Tab order.
 *
 * @param {HTMLElement} container
 * @param {string} platform what `detectPlatform` returned
 * @param {{id: string, heading: string}} options `id` prefixes every element id, so two guides can share a page
 * @returns {{select: (platform: string) => void}}
 */
export function renderStudyGuide(container, platform, { id, heading }) {
  const first = TABS.some((t) => t.platform === platform) ? platform : DESKTOP;
  const title = el("h3", { text: heading, attrs: { id: `${id}-title`, tabindex: "-1" } });
  const hint = el("p", { className: "hint", text: "Your deck is one AviAnki file. Choose your device to see how to open it." });
  const list = el("div", { className: "tabs", attrs: { role: "tablist", "aria-label": "Your device" } });
  const tabs = new Map();
  const panels = new Map();
  for (const { platform: p, label } of TABS) {
    const tab = el("button", {
      text: label,
      attrs: { type: "button", role: "tab", id: `${id}-tab-${p}`, "aria-controls": `${id}-panel-${p}` },
    });
    tab.dataset.platform = p;
    tabs.set(p, tab);
    panels.set(p, buildPanel(id, p));
    list.append(tab);
  }

  function select(p, { focus = false } = {}) {
    for (const [name, tab] of tabs) {
      const on = name === p;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      panels.get(name).hidden = !on;
    }
    if (focus) tabs.get(p).focus();
  }

  const order = TABS.map((t) => t.platform);
  list.addEventListener("keydown", (event) => {
    const at = order.indexOf(event.target.dataset?.platform);
    if (at < 0 || event.altKey || event.ctrlKey || event.metaKey) return;
    const to = {
      ArrowRight: (at + 1) % order.length,
      ArrowLeft: (at + order.length - 1) % order.length,
      Home: 0,
      End: order.length - 1,
    }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    select(order[to], { focus: true });
  });
  list.addEventListener("click", (event) => {
    const tab = event.target.closest?.('[role="tab"]');
    if (tab) select(tab.dataset.platform);
  });

  const see = el("aside", { className: "box what-youll-see", attrs: { "aria-labelledby": `${id}-see` } });
  see.append(el("h4", { text: "What you'll see", attrs: { id: `${id}-see` } }), el("p", { pieces: WHAT_YOULL_SEE }));

  container.replaceChildren(title, hint, list, ...panels.values(), see);
  container.setAttribute("aria-labelledby", `${id}-title`);
  select(first);
  return { select };
}
