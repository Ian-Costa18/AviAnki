// Parts (ADR 0006): a big build on a device that may not have the memory is written as several
// packages of PART_SIZE species each. Pure functions, so tests can drive them without the page.

import { planNotes } from "./select.js";

export const PART_SIZE = 150;

/** Test hook: `?partSize=5` makes the small fixture catalog exercise parts. */
export function partSizeOverride(search = "") {
  const n = Number.parseInt(new URLSearchParams(search).get("partSize") ?? "", 10);
  return Number.isInteger(n) && n >= 1 ? n : PART_SIZE;
}

/** Any iOS device, or a browser that reports 4 GB of memory or less (Chromium only). */
export function isConstrained({ deviceMemory, platform } = {}) {
  return platform === "ios" || (typeof deviceMemory === "number" && deviceMemory <= 4);
}

/**
 * A `RangeError` (array buffer or invalid length) or a wasm/host allocation failure. Browsers word
 * these differently, so the message is checked as well.
 */
export function isOutOfMemory(err) {
  if (err instanceof RangeError) return true;
  return /\b(OOM|out of memory|allocation failed|memory allocation)\b/i.test(String(err?.message ?? err));
}

/**
 * Split the selected species into consecutive parts and plan each part's notes.
 *
 * @param {string[]} ids species ids in rank order
 * @param {object} speciesFile
 * @param {string[]} cards
 * @param {{size?: number, split?: "never"|"whenLarge"|"always", warn?: Function}} [options]
 *   "whenLarge" splits only above `size` species; "always" (after an out-of-memory) splits even
 *   a small build, into halves at the least
 * @returns {Array<{index: number, count: number, notes: object[]}>} parts that have at least one note
 */
export function planParts(ids, speciesFile, cards, { size = PART_SIZE, split = "whenLarge", warn } = {}) {
  let each = Math.max(1, ids.length);
  if (split === "whenLarge" && ids.length > size) each = size;
  else if (split === "always") each = ids.length > size ? size : Math.max(1, Math.ceil(ids.length / 2));
  const planned = [];
  for (let i = 0; i < ids.length; i += each) {
    const notes = planNotes(ids.slice(i, i + each), speciesFile, cards, warn ? { warn } : undefined);
    if (notes.length) planned.push(notes);
  }
  return planned.map((notes, i) => ({ index: i + 1, count: planned.length, notes }));
}

/** `AviAnki-us-ma.apkg`, or `AviAnki-part-2-of-3.apkg` for one of several. */
export function fileName(slug, part) {
  return part.count > 1 ? `AviAnki-part-${part.index}-of-${part.count}.apkg` : `AviAnki-${slug}.apkg`;
}

/**
 * "How many birds are finished" for the download progress. `files` is the media feed order
 * (mediaFiles(notes)); a bird is finished once every file its notes use has arrived.
 * @returns {{total: number, done: (filesDone: number) => number}}
 */
export function birdCounter(notes, files) {
  const at = new Map(files.map((f, i) => [f, i]));
  const readyAt = new Map();
  for (const note of notes) {
    for (const ref of [note.photo, note.audio]) {
      if (ref) readyAt.set(note.speciesId, Math.max(readyAt.get(note.speciesId) ?? -1, at.get(ref.file)));
    }
  }
  const ready = [...readyAt.values()].sort((a, b) => a - b);
  return {
    total: ready.length,
    done(filesDone) {
      let lo = 0;
      let hi = ready.length; // the count of ready[i] < filesDone
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (ready[mid] < filesDone) lo = mid + 1;
        else hi = mid;
      }
      return lo;
    },
  };
}
