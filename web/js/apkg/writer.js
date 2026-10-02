// The .apkg writer: SQLite (sql.js) plus a streamed zip (fflate), reproducing genanki 0.13.1's
// output row for row (ADR 0006; see the equivalence tests in tests/web/).
//
// Memory (ADR 0006): the zip is written in store mode through fflate's streaming `Zip`, each
// output chunk goes straight into a `Blob`, and every media buffer is dropped once it has been
// written. Peak heap is one media file (plus whatever the caller's feed holds in flight)
// and the SQLite database, never the whole package twice.

import { Zip, ZipPassThrough } from "../../vendor/fflate.js";
import { APKG_SCHEMA, COL_CONF, COL_DCONF, COL_HEAD, DEFAULT_DECK } from "./schema.js";
import { pyJson } from "./pyjson.js";

// A .apkg has no registered MIME type. The extension is what Anki and the OS go by, and
// application/octet-stream is the one type every browser downloads and never sniffs or
// rewrites, so it is the type of every package this writes.
const MIME_TYPE = "application/octet-stream";

const SQL_BASE_URL = new URL("../../vendor/", import.meta.url).href;
const MIN_ZIP_MTIME_MS = Date.UTC(1980, 0, 2); // the zip format cannot store earlier dates

let sqlPromise = null;

/** Load the vendored sql.js once; it is a classic UMD script that defines `initSqlJs`. */
function loadSql() {
  sqlPromise ??= (async () => {
    if (typeof globalThis.initSqlJs !== "function") {
      const src = SQL_BASE_URL + "sql-wasm.js";
      if (typeof globalThis.importScripts === "function") {
        globalThis.importScripts(src);
      } else {
        await new Promise((resolve, reject) => {
          const script = document.createElement("script");
          script.src = src;
          script.onload = resolve;
          script.onerror = () => reject(new Error(`could not load ${src}`));
          document.head.append(script);
        });
      }
    }
    return globalThis.initSqlJs({ locateFile: (file) => SQL_BASE_URL + file });
  })();
  sqlPromise.catch(() => { sqlPromise = null; }); // allow a retry after a failed load
  return sqlPromise;
}

/** Which of a note-type's templates make a card for these field values (genanki `_front_back_cards`). */
function cardOrdinals(model, fields) {
  const ords = [];
  for (const [tmplOrd, anyOrAll, required] of model.req) {
    const present = required.map((o) => Boolean(fields[o]));
    const ok = anyOrAll === "any" ? present.some(Boolean) : present.every(Boolean);
    if (ok) ords.push(tmplOrd);
  }
  return ords;
}

function deckJson(deckId, name, description) {
  return new Map(Object.entries({
    collapsed: false, conf: 1, desc: description, dyn: 0, extendNew: 0,
    extendRev: 50, id: deckId, lrnToday: [163, 2], mod: 1425278051, name,
    newToday: [163, 2], revToday: [163, 0], timeToday: [163, 23598], usn: -1,
  }));
}

/**
 * Build the collection.anki2 bytes. A WebAssembly trap (a `WebAssembly.RuntimeError`) is an engine
 * fault, not a bad input: WebKit has been seen to trap intermittently inside sql.js ("access to a
 * null reference") on input that builds fine the next time. Nothing is half-written, so the build
 * is tried once more on a fresh sql.js instance (the trapped one is dropped: a trap skips the
 * module's own stack bookkeeping). A second trap is a real failure and propagates.
 */
async function buildDatabase(options) {
  try {
    return await buildDatabaseOnce(options);
  } catch (err) {
    if (typeof WebAssembly === "undefined" || !(err instanceof WebAssembly.RuntimeError)) throw err;
    console.warn("sql.js trapped, building the database again on a fresh instance:", err);
    sqlPromise = null;
    return buildDatabaseOnce(options);
  }
}

async function buildDatabaseOnce({ deckId, deckName, deckDescription, models, notes, timestamp, onProgress }) {
  const SQL = await loadSql();
  const db = new SQL.Database();
  try {
    db.run(APKG_SCHEMA);

    const byId = new Map(models.map((m) => [String(m.id), m]));
    // Only note types a note uses, in first-use order (genanki collects them off the notes).
    const used = new Map();
    for (const note of notes) {
      const key = String(note.modelId);
      const model = byId.get(key);
      if (!model) throw new Error(`note uses unknown model ${key}`);
      if (!used.has(key)) used.set(key, model);
    }
    const mod = Math.trunc(timestamp);
    const modelsBlob = new Map();
    for (const [key, model] of used) modelsBlob.set(key, { ...model, did: deckId, mod });

    const decks = new Map([["1", DEFAULT_DECK], [String(deckId), deckJson(deckId, deckName, deckDescription)]]);
    db.run("INSERT INTO col VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", [
      ...COL_HEAD, COL_CONF, pyJson(modelsBlob), pyJson(decks), COL_DCONF, "{}",
    ]);

    let nextId = Math.trunc(timestamp * 1000);
    const insertNote = db.prepare("INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?,?)");
    const insertCard = db.prepare("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
    try {
      let done = 0;
      for (const note of notes) {
        const model = used.get(String(note.modelId));
        if (note.fields.length !== model.flds.length) {
          throw new Error(`note has ${note.fields.length} fields, model ${model.name} has ${model.flds.length}`);
        }
        const noteId = nextId++;
        const tags = note.tags ?? [];
        insertNote.run([
          noteId, note.guid, Number(model.id), mod, -1, " " + tags.join(" ") + " ",
          note.fields.join("\x1f"), note.fields[model.sortf], 0, 0, "",
        ]);
        for (const ord of cardOrdinals(model, note.fields)) {
          insertCard.run([nextId++, noteId, deckId, ord, mod, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ""]);
        }
        onProgress?.({ stage: "notes", done: ++done, total: notes.length });
      }
    } finally {
      insertNote.free();
      insertCard.free();
    }
    return db.export();
  } finally {
    db.close();
  }
}

const asBytes = (data) =>
  data instanceof Uint8Array ? data
    : ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
      : new Uint8Array(data);

/**
 * Write a .apkg.
 *
 * @param {object} opts
 * @param {number} opts.deckId
 * @param {string} opts.deckName  full name, `::` separating a subdeck
 * @param {string} [opts.deckDescription]
 * @param {object[]} opts.models  note-type JSON as in notetypes.json (`did` and `mod` are set here)
 * @param {Array<{modelId: string|number, guid: string, fields: string[], tags?: string[]}>} opts.notes
 *        in the order they are written; note and card ids count up from the timestamp in that order
 * @param {string[]} opts.mediaNames  names inside the package, in zip order (the JSON map's
 *        keys "0", "1", ... follow this order, as genanki's do)
 * @param {AsyncIterable<{name: string, data: Uint8Array}>|Iterable<{name: string, data: Uint8Array}>} [opts.media]
 *        yields exactly `mediaNames`, in that order; pulled one at a time, so a feed that
 *        fetches ahead by a bounded window keeps memory bounded
 * @param {number} [opts.timestamp]  seconds since the epoch; fix it for reproducible output
 * @param {(p: {stage: string, done?: number, total?: number}) => void} [opts.onProgress]
 * @returns {Promise<Blob>}
 */
export async function writeApkg({
  deckId, deckName, deckDescription = "", models, notes, mediaNames, media = [],
  timestamp = Date.now() / 1000, onProgress,
}) {
  onProgress?.({ stage: "database" });
  const dbBytes = await buildDatabase({
    deckId, deckName, deckDescription, models, notes, timestamp, onProgress,
  });

  const parts = [];
  let failure = null;
  const zip = new Zip((err, chunk) => {
    if (err) failure = err;
    else parts.push(new Blob([chunk])); // Blob copies, so `chunk` can be collected at once
  });
  const mtime = Math.max(Math.trunc(timestamp * 1000), MIN_ZIP_MTIME_MS);
  const addFile = (name, data) => {
    const entry = new ZipPassThrough(name); // store: jpeg, webp and mp3 are already compressed
    entry.mtime = mtime;
    zip.add(entry);
    entry.push(data, true);
    if (failure) throw failure;
  };

  addFile("collection.anki2", dbBytes);
  const mediaMap = new Map(mediaNames.map((name, i) => [String(i), name]));
  addFile("media", new TextEncoder().encode(pyJson(mediaMap)));

  onProgress?.({ stage: "media", done: 0, total: mediaNames.length });
  let written = 0;
  for await (const item of media) {
    if (written >= mediaNames.length) {
      throw new Error(`media feed yielded more than the ${mediaNames.length} files asked for`);
    }
    if (item.name !== mediaNames[written]) {
      throw new Error(`media feed yielded ${item.name} where ${mediaNames[written]} was expected`);
    }
    addFile(String(written), asBytes(item.data));
    written++; // the item and its buffer are unreferenced from here on
    onProgress?.({ stage: "media", done: written, total: mediaNames.length });
  }
  if (written !== mediaNames.length) {
    throw new Error(`media feed ended after ${written} of ${mediaNames.length} files`);
  }

  zip.end();
  if (failure) throw failure;
  onProgress?.({ stage: "done" });
  return new Blob(parts, { type: MIME_TYPE });
}
