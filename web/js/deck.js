/**
 * The deck: notes, fields, credits, description, identity and `buildDeck`. The browser twin of
 * src/avianki/deck/build.py and credits.py (spec section 6, ADR 0006/0009/0012); the equivalence
 * tests in tests/web/ build the same selection here and with genanki and compare the two.
 *
 * ## buildDeck
 *
 *     const { blob, summary } = await buildDeck({
 *       manifest,      // parsed manifest.json (only `dataset_credits` is read)
 *       speciesFile,   // parsed species.<hash>.json: { [speciesId]: { name, sci, photo, audio } }
 *       notes,         // planNotes(...) output, in the order to write them
 *       deckName,      // default "AviAnki" (frozen, ADR 0009)
 *       subdeck,       // e.g. the region's name -> "AviAnki::Massachusetts", or null
 *       ebird,         // true adds the not-for-redistribution notice to the description
 *       timestamp,     // seconds since the epoch; default now. Fix it to compare with genanki
 *       media,         // the media feed, below
 *       notetypes,     // optional: a parsed notetypes.json (default: fetched next to this file)
 *       onProgress,    // optional: ({stage, done, total}) => void
 *     });
 *     // blob: application/octet-stream, the .apkg. summary: { notesByType: {photo, audio,
 *     // photo_audio}, mediaCount, bytes, noteCount, deckName }
 *
 * ## The media feed
 *
 * `media` is a function `(files) => feed` (it may be async) or a feed itself. `files` is the
 * list of catalog media names the deck needs (e.g. "media/ab12....webp"), each once, in the
 * order the writer will consume them: first use by the notes, photo before audio. A feed is an
 * async (or sync) iterable that yields exactly those files, in exactly that order, as
 *
 *     { name: "media/ab12....webp", data: Uint8Array }
 *
 * The writer pulls one item at a time and drops its buffer once written, so what stays in
 * memory is whatever the feed itself has in flight. `orderedPrefetch` (apkg/prefetch.js) turns
 * a `fetch` function into such a feed with a bounded window (6 downloads in flight by default):
 *
 *     media: (files) => orderedPrefetch(files, (f, signal) => fetchBytes(base + f, signal))
 *
 * A feed that yields the wrong name, too few items or too many makes buildDeck throw. Inside
 * the package the files are named `avianki_<basename>` and numbered "0", "1", ... as genanki's are.
 */

import { stableId } from "./apkg/md5.js";
import { guidFor } from "./apkg/guid.js";
import { writeApkg } from "./apkg/writer.js";
import { CARD_TYPES } from "./select.js";

export const DECK_NAME = "AviAnki"; // frozen (ADR 0009)
export const MEDIA_PREFIX = "avianki_";

// --- identity (frozen, ADR 0009) -------------------------------------------------------

/** `AviAnki`, or `AviAnki::<Region name>` when a subdeck is asked for. */
export function fullDeckName(deckName, subdeck) {
  return subdeck ? `${deckName}::${subdeck}` : deckName;
}

/** `int(md5(name).hexdigest()[:8], 16)`. */
export function deckId(name) {
  return stableId(name);
}

/** `genanki.guid_for("avianki", species_id, card_type)`. */
export function noteGuid(speciesId, cardType) {
  return guidFor("avianki", speciesId, cardType);
}

/** `media/1a2b.webp` -> `avianki_1a2b.webp`: the name inside the .apkg. */
export function packageMediaName(catalogFile) {
  return MEDIA_PREFIX + catalogFile.slice(catalogFile.lastIndexOf("/") + 1);
}

// --- escaping, as Python's html.escape ---------------------------------------------------

/** `html.escape(s, quote=False)`: for SpeciesId, Name and SciName. */
export function escapeText(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** `html.escape(s, quote=True)`: for manifest values in the description. */
export function escapeAttr(s) {
  return escapeText(s).replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

// --- fields and credits (deck/credits.py, deck/build.py::_note_fields) ---------------------

/**
 * One `<div class="credits">` with the credit line of each asset the note uses (photo, then
 * recording), or "" when it uses none. Credits arrive as escaped HTML from the catalog and
 * are joined as they are.
 */
export function creditsField(photo, audio) {
  const lines = [photo, audio].filter(Boolean).map((m) => m.credit);
  return lines.length ? '<div class="credits">' + lines.join("<br>") + "</div>" : "";
}

/** The note's field values in the note type's order (`fieldNames` from notetypes.json). */
export function noteFields(note, entry, fieldNames) {
  const values = {
    SpeciesId: escapeText(note.speciesId),
    Name: escapeText(entry.name),
    SciName: escapeText(entry.sci),
    Photo: note.photo ? `<img src="${packageMediaName(note.photo.file)}">` : "",
    Photo2: "",
    Audio: note.audio ? `[sound:${packageMediaName(note.audio.file)}]` : "",
    Audio2: "",
    Credits: creditsField(note.photo, note.audio),
  };
  return fieldNames.map((name) => values[name]);
}

function datasetCredit(c) {
  let line = `${escapeAttr(c.text)}, ${escapeAttr(c.licence_id)}, ` +
    `<a href="${escapeAttr(c.url)}">${escapeAttr(c.url)}</a>`;
  if (c.modifications) line += ` (modified: ${escapeAttr(c.modifications)})`;
  return `<p>${line}</p>`;
}

/**
 * The HTML on the deck overview (ADR 0012): study guidance, each dataset credit from the
 * manifest, the licence notice and, for an eBird build, the not-for-redistribution line.
 * The fixed strings come from notetypes.json, generated from deck/credits.py.
 */
export function deckDescription(manifest, { ebird = false, notetypes }) {
  const d = notetypes.description;
  const parts = ["<p>" + d.study_guidance.join("<br>") + "</p>"];
  parts.push(...(manifest.dataset_credits ?? []).map(datasetCredit));
  parts.push(`<p>${d.licence_notice}</p>`);
  if (ebird) parts.push(`<p>${d.ebird_notice}</p>`);
  return parts.join("\n");
}

// --- note types ---------------------------------------------------------------------------

let notetypesPromise = null;

/** notetypes.json (generated by scripts/gen_web_notetypes.py), fetched once. */
export function loadNotetypes() {
  notetypesPromise ??= fetch(new URL("./notetypes.json", import.meta.url)).then((response) => {
    if (!response.ok) throw new Error(`notetypes.json: HTTP ${response.status}`);
    return response.json();
  });
  notetypesPromise.catch(() => { notetypesPromise = null; });
  return notetypesPromise;
}

// --- building -----------------------------------------------------------------------------

/**
 * The catalog media files a note list needs, each once, in first-use order (photo before
 * audio within a note): the order of the media feed and of the package's numbered entries.
 */
export function mediaFiles(notes) {
  const files = new Map(); // package name -> catalog file
  for (const note of notes) {
    for (const ref of [note.photo, note.audio]) {
      if (ref && !files.has(packageMediaName(ref.file))) files.set(packageMediaName(ref.file), ref.file);
    }
  }
  return [...files.values()];
}

/** Re-yield the caller's feed under package names, checking it follows `files`. */
async function* packageFeed(feed, files) {
  let i = 0;
  for await (const item of feed) {
    if (i >= files.length) throw new Error(`media feed yielded more than the ${files.length} files asked for`);
    if (item.name !== files[i]) throw new Error(`media feed yielded ${item.name} where ${files[i]} was expected`);
    yield { name: packageMediaName(item.name), data: item.data };
    i++;
  }
}

/**
 * Build the .apkg for `notes`. See the header of this file for the media feed.
 * @returns {Promise<{blob: Blob, summary: {notesByType: Object<string, number>, mediaCount: number,
 *           bytes: number, noteCount: number, deckName: string}}>}
 */
export async function buildDeck({
  manifest, speciesFile, notes, deckName = DECK_NAME, subdeck = null, ebird = false,
  timestamp = Date.now() / 1000, media, notetypes, onProgress,
}) {
  const nt = notetypes ?? (await loadNotetypes());
  const name = fullDeckName(deckName, subdeck);

  const notesByType = Object.fromEntries(CARD_TYPES.map((t) => [t, 0]));
  const rows = [];
  for (const note of notes) {
    const model = nt.models[note.cardType];
    if (!model) throw new RangeError(`unknown card type ${JSON.stringify(note.cardType)}`);
    rows.push({
      modelId: model.id,
      guid: await noteGuid(note.speciesId, note.cardType),
      fields: noteFields(note, speciesFile[note.speciesId], nt.fields),
    });
    notesByType[note.cardType]++;
  }

  const files = mediaFiles(notes);
  let feed = [];
  if (files.length) {
    if (!media) throw new TypeError("buildDeck needs a media feed for a deck with media");
    feed = packageFeed(await (typeof media === "function" ? media(files) : media), files);
  }

  const blob = await writeApkg({
    deckId: deckId(name),
    deckName: name,
    deckDescription: deckDescription(manifest, { ebird, notetypes: nt }),
    models: Object.values(nt.models).map((m) => m.json), // json.id is the string form genanki writes
    notes: rows,
    mediaNames: files.map(packageMediaName),
    media: feed,
    timestamp,
    onProgress,
  });

  const noteCount = Object.values(notesByType).reduce((a, b) => a + b, 0);
  return {
    blob,
    summary: { notesByType, mediaCount: files.length, bytes: blob.size, noteCount, deckName: name },
  };
}
