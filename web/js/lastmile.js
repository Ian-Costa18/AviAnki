// The last mile (ADR 0016): which device is this, and what does it do with the downloaded file?
// `detectPlatform` is pure so the tests can feed it sample user agents; `renderLastMile` shows the
// detected platform's steps first and the others under a collapsed "On a different device?".

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

// A step is a list of pieces: plain strings, bold pieces and links.
const STEPS = {
  [ANDROID]: {
    title: "On your Android phone or tablet",
    steps: [
      ["Install ", link("AnkiDroid", "https://play.google.com/store/apps/details?id=com.ichi2.anki"),
        " from the Play Store. It is free."],
      ["Tap the file you just downloaded (or use ", bold("Share → AnkiDroid"), ")."],
      ["Tap ", bold("AviAnki"), ", then ", bold("Study"), "."],
    ],
  },
  [IOS]: {
    title: "On your iPhone or iPad",
    steps: [
      [link("AnkiMobile", "https://apps.apple.com/app/ankimobile-flashcards/id373493387"),
        " costs US$24.99, and the money funds Anki's development. Install it."],
      ["Tap ", bold("Share → AnkiMobile"), " (or open the file from Files)."],
      ["Tap ", bold("AviAnki"), "."],
    ],
    after: ["Free alternative: build the deck on a computer, import it into ",
      link("Anki Desktop", "https://apps.ankiweb.net"), ", sync it to a free ",
      link("AnkiWeb", "https://ankiweb.net"), " account, and study at ankiweb.net in Safari."],
  },
  [DESKTOP]: {
    title: "On Windows, macOS or Linux",
    steps: [
      ["Install ", link("Anki", "https://apps.ankiweb.net"), ". It is free."],
      ["Double-click the file you just downloaded."],
      ["Click ", bold("AviAnki"), ", then ", bold("Study Now"), "."],
    ],
  },
};

const ORDER = [ANDROID, IOS, DESKTOP];

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

function section(platform, level) {
  const { title, steps, after } = STEPS[platform];
  const el = document.createElement("section");
  el.dataset.platform = platform;
  el.className = "steps";
  const heading = document.createElement(level);
  heading.textContent = title;
  const list = document.createElement("ol");
  for (const pieces of steps) {
    const li = document.createElement("li");
    fill(li, pieces);
    list.append(li);
  }
  el.append(heading, list);
  if (after) {
    const p = document.createElement("p");
    fill(p, after);
    el.append(p);
  }
  return el;
}

/** Fill `container` with the detected platform's steps, then the rest under "On a different device?". */
export function renderLastMile(container, platform) {
  const first = ORDER.includes(platform) ? platform : DESKTOP;
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "On a different device?";
  details.append(summary, ...ORDER.filter((p) => p !== first).map((p) => section(p, "h4")));
  container.replaceChildren(section(first, "h3"), details);
}
