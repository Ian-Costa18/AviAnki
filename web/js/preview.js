/**
 * The live card preview (ADR 0028): a mock Rock Pigeon card drawn from the REAL note-type
 * templates and the CSS `themes.js` composes, so what you see is what the .apkg will carry.
 *
 * Each side is a sandboxed `srcdoc` iframe (`sandbox="allow-same-origin"`: no scripts run in it)
 * whose `<body class="card">` stands in for Anki's. The page, not the card, plays the sound and
 * opens credit links, by listening on the frame's document.
 *
 * Templates use only Anki's `{{Field}}`, `{{#Field}}...{{/Field}}` and `{{^Field}}...{{/Field}}`,
 * which `renderTemplate` implements. A `[sound:...]` field becomes the replay button Anki draws.
 *
 * The preview carries the Rock Pigeon's photo, recording and credits from the catalog when the
 * species file has it, and a plain placeholder when it does not (or has not loaded yet).
 */

import { escapeAttr, noteFields } from "./deck.js";
import { composeCss, backFor } from "./themes.js";
import { mediaUrl } from "./catalog.js";

export const PREVIEW_SPECIES = "columba-livia";

// --- templates ------------------------------------------------------------------------------

const SECTION = /\{\{([#^])([A-Za-z0-9_]+)\}\}([\s\S]*?)\{\{\/\2\}\}/g;
const FIELD = /\{\{([A-Za-z0-9_]+)\}\}/g;

/**
 * Render an Anki template with `fields` ({name: html}): `{{#F}}x{{/F}}` keeps x when F is not
 * empty, `{{^F}}x{{/F}}` when it is, and `{{F}}` is replaced by F's HTML as it is.
 */
export function renderTemplate(template, fields) {
  const filled = (name) => (fields[name] ?? "").trim() !== "";
  const withSections = template.replace(SECTION, (_, kind, name, inner) =>
    filled(name) === (kind === "#") ? renderTemplate(inner, fields) : "");
  return withSections.replace(FIELD, (_, name) => fields[name] ?? "");
}

// Anki's own SVG for the replay button (the play circle), so the lookalike has its shape.
const PLAY_ICON = '<svg class="playImage" viewBox="0 0 64 64" version="1.1"><circle cx="32" cy="32" r="29"/>' +
  '<path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z"/></svg>';

/** The button Anki draws for `[sound:...]`; `url` (or "") is what the page plays when it is pressed. */
export function replayButton(url) {
  return `<a class="replay-button soundLink" href="#" role="button" aria-label="Play the recording" ` +
    `data-audio="${escapeAttr(url)}">${PLAY_ICON}</a>`;
}

// What Anki itself adds around a card, approximated: its body defaults and the replay button.
// Card CSS comes after this and wins wherever the two meet, as in Anki.
const ANKI_DEFAULTS = `
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; }
.card { font-family: arial; font-size: 20px; text-align: center; color: #000; background-color: #fff; }
.card.nightMode, .card.night_mode { color: #fff; background-color: #2c2c2c; }
a.replay-button { display: inline-flex; text-decoration: none; cursor: pointer; }
.replay-button svg { width: 40px; height: 40px; }
.replay-button svg circle { fill: #fff; stroke: #8c8c8c; stroke-width: 2; }
.replay-button svg path { fill: #3a3a3a; }
.nightMode .replay-button svg circle, .night_mode .replay-button svg circle { fill: #3a3a3a; stroke: #9a9a9a; }
.nightMode .replay-button svg path, .night_mode .replay-button svg path { fill: #eee; }
`;

/** A whole HTML document for one card side: `css` is the note type's CSS, `body` the rendered template. */
export function cardDocument({ css, body, night = false }) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<style id="anki">${ANKI_DEFAULTS}</style><style id="card-css">${css}</style></head>` +
    `<body class="card${night ? " nightMode" : ""}">${body}</body></html>`;
}

// --- the mock note ----------------------------------------------------------------------------

function placeholderPhoto() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">' +
    '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9db7cc"/>' +
    '<stop offset="1" stop-color="#e3dccb"/></linearGradient></defs><rect width="800" height="600" fill="url(#g)"/>' +
    '<ellipse cx="400" cy="360" rx="150" ry="110" fill="#76808b"/><circle cx="520" cy="270" r="62" fill="#76808b"/>' +
    '<path d="M570 262l70 14-70 18z" fill="#c8a24a"/><circle cx="535" cy="258" r="8" fill="#fff"/></svg>';
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

const PLACEHOLDER_ENTRY = {
  name: "Rock Pigeon",
  sci: "Columba livia",
  ioc_name: "Rock Dove",
  photo: [{ file: "", credit: "Photo: an example, not a real photograph" }],
  audio: [{ file: "", credit: "Recording: an example, with no sound" }],
};

/**
 * The note's fields as the templates see them, for card type `cardType`. They come from the same
 * `noteFields` the deck builder uses; only the media names are swapped for something the preview
 * can load (the catalog's URL, or the placeholder picture).
 */
export function previewFields({ entry, manifest, notetypes, cardType = "photo" }) {
  const real = entry && manifest;
  const source = entry ?? PLACEHOLDER_ENTRY;
  const photo = source.photo?.[0] ?? null;
  const audio = source.audio?.[0] ?? null;
  const fields = noteFields({ speciesId: PREVIEW_SPECIES, cardType, photo, audio }, source, notetypes.fields);
  const byName = Object.fromEntries(notetypes.fields.map((name, i) => [name, fields[i]]));
  if (photo) {
    const url = real && photo.file ? mediaUrl(manifest, photo.file) : placeholderPhoto();
    byName.Photo = `<img src="${escapeAttr(url)}" alt="">`;
  }
  if (audio) byName.Audio = replayButton(real && audio.file ? mediaUrl(manifest, audio.file) : "");
  return byName;
}

// --- the frames ----------------------------------------------------------------------------------

/**
 * Wire two iframes (question and answer) to draw the card. `update(state)` takes
 * `{theme, nameOnPhoto, cardType, night, entry, manifest}` and redraws in place, without reloading
 * the frames, so dragging a colour picker stays smooth.
 *
 * The page plays the recording and opens credit links: the card itself cannot run scripts.
 */
export function mountPreview({ questionFrame, answerFrame, notetypes }) {
  const frames = [questionFrame, answerFrame];
  const look = notetypes.look;
  let audio = null;
  let latest = null;

  const play = (url) => {
    if (!url) return;
    audio?.pause();
    audio = new Audio(url);
    audio.play().catch(() => { /* no sound is not an error: autoplay rules, or a missing file */ });
  };

  const onClick = (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const button = target?.closest(".replay-button");
    const link = target?.closest("a[href]");
    if (button) {
      event.preventDefault();
      play(button.getAttribute("data-audio"));
    } else if (link) {
      event.preventDefault();
      const href = link.getAttribute("href") ?? "";
      if (/^https:\/\//i.test(href)) window.open(href, "_blank", "noopener,noreferrer");
    }
  };

  const loaded = new Map();
  for (const frame of frames) {
    loaded.set(frame, false);
    frame.addEventListener("load", () => {
      frame.contentDocument?.addEventListener("click", onClick);
      loaded.set(frame, true);
      if (latest) apply();
    });
    frame.srcdoc = cardDocument({ css: composeCss(look), body: "" });
  }

  function apply() {
    const { theme, nameOnPhoto, cardType, night, entry, manifest } = latest;
    const fields = previewFields({ entry, manifest, notetypes, cardType });
    const css = composeCss(look, theme, nameOnPhoto);
    const front = renderTemplate(notetypes.models[cardType].json.tmpls[0].qfmt, fields);
    const back = renderTemplate(backFor(look, nameOnPhoto), fields);
    [front, back].forEach((body, i) => {
      const doc = frames[i].contentDocument;
      if (!doc?.body || !loaded.get(frames[i])) return;
      doc.getElementById("card-css").textContent = css;
      doc.body.classList.toggle("nightMode", night);
      if (doc.body.innerHTML !== body) doc.body.innerHTML = body;
    });
  }

  return {
    update(state) {
      latest = state;
      apply();
    },
    /** The frame's document, for tests and for the page to read what was drawn. */
    documents: () => frames.map((f) => f.contentDocument),
    stop() { audio?.pause(); },
  };
}
