/* PROTOTYPE — THROWAWAY. Not production code.
 *
 * A hand-written .apkg writer for the browser, deliberately reproducing
 * genanki 0.13.1's output field-for-field so the two can be compared.
 *
 * Everything here is stuff there is no library for. The count matters:
 * see README.md "How much had to be written by hand".
 */

// ---------------------------------------------------------------------------
// 1. md5 — hand-written. WebCrypto deliberately does NOT offer md5, and the
//    deck/model IDs in anki_model.py are md5-derived, so there is no way round
//    this. ~70 lines.
// ---------------------------------------------------------------------------
function md5(bytes) {
  const S = [7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,
             5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
             4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,
             6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21];
  const K = new Uint32Array(64);
  for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296);

  const len = bytes.length;
  const padded = new Uint8Array((((len + 8) >> 6) + 1) << 6);
  padded.set(bytes);
  padded[len] = 0x80;
  const bitLen = len * 8;
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 8, bitLen >>> 0, true);
  dv.setUint32(padded.length - 4, Math.floor(bitLen / 4294967296), true);

  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
  const M = new Uint32Array(16);
  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) M[i] = dv.getUint32(off + i * 4, true);
    let A = a0, B = b0, C = c0, D = d0;
    for (let i = 0; i < 64; i++) {
      let F, g;
      if (i < 16)      { F = (B & C) | (~B & D);          g = i; }
      else if (i < 32) { F = (D & B) | (~D & C);          g = (5 * i + 1) % 16; }
      else if (i < 48) { F = B ^ C ^ D;                   g = (3 * i + 5) % 16; }
      else             { F = C ^ (B | ~D);                g = (7 * i) % 16; }
      F = (F + A + K[i] + M[g]) >>> 0;
      A = D; D = C; C = B;
      B = (B + ((F << S[i]) | (F >>> (32 - S[i])))) >>> 0;
    }
    a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0;
    c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
  }
  const out = new Uint8Array(16);
  new DataView(out.buffer).setUint32(0, a0, true);
  new DataView(out.buffer).setUint32(4, b0, true);
  new DataView(out.buffer).setUint32(8, c0, true);
  new DataView(out.buffer).setUint32(12, d0, true);
  return [...out].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Mirror of anki_model._stable_id: int(md5(seed).hexdigest()[:8], 16) */
export function stableId(seed) {
  return parseInt(md5(new TextEncoder().encode(seed)).slice(0, 8), 16);
}

// ---------------------------------------------------------------------------
// 2. Note GUIDs — genanki.util.guid_for. sha256 is in WebCrypto but it is
//    async, which forces the whole build path async. The base91 alphabet and
//    the big-endian-first-8-bytes convention are Anki's own and have to be
//    transcribed.
// ---------------------------------------------------------------------------
const BASE91 = ('abcdefghijklmnopqrstuvwxyz' +
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ' +
                '0123456789!#$%&()*+,-./:;<=>?@[]^_`{|}~').split('');

export async function guidFor(...values) {
  const hashStr = values.map(String).join('__');
  const digest = new Uint8Array(
    await crypto.subtle.digest('SHA-256', new TextEncoder().encode(hashStr)));
  // first 8 bytes as a big-endian integer — needs BigInt, Number would lose bits
  let n = 0n;
  for (let i = 0; i < 8; i++) n = (n << 8n) + BigInt(digest[i]);
  const base = BigInt(BASE91.length);
  const out = [];
  while (n > 0n) {
    out.push(BASE91[Number(n % base)]);
    n /= base;
  }
  return out.reverse().join('');
}

// ---------------------------------------------------------------------------
// 3. Python-compatible JSON. JSON.stringify is NOT interchangeable with
//    json.dumps:
//      - Python's default separators are ', ' and ': ' (JS uses ',' and ':')
//      - Python defaults to ensure_ascii=True, escaping every non-ASCII char
//        (our templates contain 🖼 🔊 🎵, so this bites immediately)
//      - JS objects reorder integer-like keys ascending; the `models` blob is
//        keyed by numeric model IDs, so plain objects silently resort them.
//        Maps are used throughout to preserve insertion order.
// ---------------------------------------------------------------------------
const ESCAPES = { '\\': '\\\\', '"': '\\"', '\b': '\\b', '\f': '\\f',
                  '\n': '\\n', '\r': '\\r', '\t': '\\t' };

function pyStr(s) {
  let out = '"';
  for (const ch of s) {
    const cp = ch.codePointAt(0);
    if (ESCAPES[ch]) out += ESCAPES[ch];
    else if (cp < 0x20) out += '\\u' + cp.toString(16).padStart(4, '0');
    else if (cp < 0x7f) out += ch;
    else if (cp <= 0xffff) out += '\\u' + cp.toString(16).padStart(4, '0');
    else {
      const v = cp - 0x10000;              // surrogate pair, as Python emits
      out += '\\u' + (0xd800 + (v >> 10)).toString(16).padStart(4, '0');
      out += '\\u' + (0xdc00 + (v & 0x3ff)).toString(16).padStart(4, '0');
    }
  }
  return out + '"';
}

export function pyJson(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v);
  if (typeof v === 'string') return pyStr(v);
  if (Array.isArray(v)) return '[' + v.map(pyJson).join(', ') + ']';
  const entries = v instanceof Map ? [...v.entries()] : Object.entries(v);
  return '{' + entries.map(([k, val]) => pyStr(String(k)) + ': ' + pyJson(val)).join(', ') + '}';
}

// ---------------------------------------------------------------------------
// 4. The `req` array. Anki's schema11 notetype JSON carries a list of which
//    fields each template needs. genanki derives it by rendering the template
//    with a sentinel; reproducing it means reimplementing enough of mustache.
// ---------------------------------------------------------------------------
function renderMustache(template, values) {
  let out = '', i = 0;
  while (i < template.length) {
    const open = template.indexOf('{{', i);
    if (open === -1) { out += template.slice(i); break; }
    out += template.slice(i, open);
    const close = template.indexOf('}}', open);
    if (close === -1) { out += template.slice(open); break; }
    const tag = template.slice(open + 2, close).trim();
    i = close + 2;
    if (tag.startsWith('!')) continue;                       // comment
    if (tag.startsWith('#') || tag.startsWith('^')) {
      const name = tag.slice(1).trim();
      const endTag = '{{/' + name + '}}';
      const end = template.indexOf(endTag, i);
      const inner = end === -1 ? template.slice(i) : template.slice(i, end);
      i = end === -1 ? template.length : end + endTag.length;
      const truthy = Boolean(values[name]);
      if ((tag[0] === '#') === truthy) out += renderMustache(inner, values);
      continue;
    }
    if (tag.startsWith('/')) continue;
    const name = tag.includes(':') ? tag.slice(tag.lastIndexOf(':') + 1) : tag;
    out += values[name] ?? '';
  }
  return out;
}

function computeReq(fields, templates) {
  const SENTINEL = 'SeNtInEl';
  const names = fields.map((f) => f.name);
  const req = [];
  templates.forEach((tmpl, tord) => {
    let required = [];
    names.forEach((field, ford) => {
      const values = Object.fromEntries(names.map((n) => [n, SENTINEL]));
      values[field] = '';
      if (!renderMustache(tmpl.qfmt, values).includes(SENTINEL)) required.push(ford);
    });
    if (required.length) { req.push([tord, 'all', required]); return; }
    required = [];
    names.forEach((field, ford) => {
      const values = Object.fromEntries(names.map((n) => [n, '']));
      values[field] = SENTINEL;
      if (renderMustache(tmpl.qfmt, values).includes(SENTINEL)) required.push(ford);
    });
    req.push([tord, 'any', required]);
  });
  return req;
}

// ---------------------------------------------------------------------------
// 5. The collection schema and the seed `col` row. Copied verbatim out of
//    genanki's apkg_schema.py / apkg_col.py — there is no JS source for these.
// ---------------------------------------------------------------------------
const APKG_SCHEMA = `
CREATE TABLE col (
    id              integer primary key,
    crt             integer not null,
    mod             integer not null,
    scm             integer not null,
    ver             integer not null,
    dty             integer not null,
    usn             integer not null,
    ls              integer not null,
    conf            text not null,
    models          text not null,
    decks           text not null,
    dconf           text not null,
    tags            text not null
);
CREATE TABLE notes (
    id              integer primary key,
    guid            text not null,
    mid             integer not null,
    mod             integer not null,
    usn             integer not null,
    tags            text not null,
    flds            text not null,
    sfld            integer not null,
    csum            integer not null,
    flags           integer not null,
    data            text not null
);
CREATE TABLE cards (
    id              integer primary key,
    nid             integer not null,
    did             integer not null,
    ord             integer not null,
    mod             integer not null,
    usn             integer not null,
    type            integer not null,
    queue           integer not null,
    due             integer not null,
    ivl             integer not null,
    factor          integer not null,
    reps            integer not null,
    lapses          integer not null,
    left            integer not null,
    odue            integer not null,
    odid            integer not null,
    flags           integer not null,
    data            text not null
);
CREATE TABLE revlog (
    id              integer primary key,
    cid             integer not null,
    usn             integer not null,
    ease            integer not null,
    ivl             integer not null,
    lastIvl         integer not null,
    factor          integer not null,
    time            integer not null,
    type            integer not null
);
CREATE TABLE graves (
    usn             integer not null,
    oid             integer not null,
    type            integer not null
);
CREATE INDEX ix_notes_usn on notes (usn);
CREATE INDEX ix_cards_usn on cards (usn);
CREATE INDEX ix_revlog_usn on revlog (usn);
CREATE INDEX ix_cards_nid on cards (nid);
CREATE INDEX ix_cards_sched on cards (did, queue, due);
CREATE INDEX ix_revlog_cid on revlog (cid);
CREATE INDEX ix_notes_csum on notes (csum);
`;

// These four blobs are inserted as literal text, exactly as genanki does —
// they are never re-serialised, so their whitespace must survive untouched.
const COL_CONF = `{
        "activeDecks": [
            1
        ],
        "addToCur": true,
        "collapseTime": 1200,
        "curDeck": 1,
        "curModel": "1425279151691",
        "dueCounts": true,
        "estTimes": true,
        "newBury": true,
        "newSpread": 0,
        "nextPos": 1,
        "sortBackwards": false,
        "sortType": "noteFld",
        "timeLim": 0
    }`;

const COL_DECKS_DEFAULT = new Map([['1', new Map(Object.entries({
  collapsed: false, conf: 1, desc: '', dyn: 0, extendNew: 10, extendRev: 50,
  id: 1, lrnToday: [0, 0], mod: 1425279151, name: 'Default', newToday: [0, 0],
  revToday: [0, 0], timeToday: [0, 0], usn: 0,
}))]]);

const COL_DCONF = `{
        "1": {
            "autoplay": true,
            "id": 1,
            "lapse": {
                "delays": [
                    10
                ],
                "leechAction": 0,
                "leechFails": 8,
                "minInt": 1,
                "mult": 0
            },
            "maxTaken": 60,
            "mod": 0,
            "name": "Default",
            "new": {
                "bury": true,
                "delays": [
                    1,
                    10
                ],
                "initialFactor": 2500,
                "ints": [
                    1,
                    4,
                    7
                ],
                "order": 1,
                "perDay": 20,
                "separate": true
            },
            "replayq": true,
            "rev": {
                "bury": true,
                "ease4": 1.3,
                "fuzz": 0.05,
                "ivlFct": 1,
                "maxIvl": 36500,
                "minSpace": 1,
                "perDay": 100
            },
            "timer": 0,
            "usn": 0
        }
    }`;

const LATEX_PRE = '\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n' +
  '\\usepackage[utf8]{inputenc}\n\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n' +
  '\\setlength{\\parindent}{0in}\n\\begin{document}\n';
const LATEX_POST = '\\end{document}';

// ---------------------------------------------------------------------------
// 6. The builder.
// ---------------------------------------------------------------------------
function modelJson(model, timestamp, deckId) {
  const flds = model.fields.map((f, ord) => new Map(Object.entries({
    name: f.name, ord, font: 'Liberation Sans', media: [], rtl: false,
    size: 20, sticky: false,
  })));
  const tmpls = model.templates.map((t, ord) => new Map(Object.entries({
    name: t.name, qfmt: t.qfmt, afmt: t.afmt, ord,
    bafmt: '', bqfmt: '', bfont: '', bsize: 0, did: null,
  })));
  return new Map(Object.entries({
    css: model.css, did: deckId, flds, id: String(model.id),
    latexPost: LATEX_POST, latexPre: LATEX_PRE, latexsvg: false,
    mod: Math.floor(timestamp), name: model.name,
    req: computeReq(model.fields, model.templates),
    sortf: 0, tags: [], tmpls, type: 0, usn: -1, vers: [],
  }));
}

function deckJson(deckId, name, description) {
  return new Map(Object.entries({
    collapsed: false, conf: 1, desc: description, dyn: 0, extendNew: 0,
    extendRev: 50, id: deckId, lrnToday: [163, 2], mod: 1425278051, name,
    newToday: [163, 2], revToday: [163, 0], timeToday: [163, 23598], usn: -1,
  }));
}

/**
 * Build a .apkg.
 *
 * @param {object}   opts
 * @param {number}   opts.deckId
 * @param {string}   opts.deckName
 * @param {object[]} opts.models      {id, name, fields:[{name}], templates:[{name,qfmt,afmt}], css}
 * @param {object[]} opts.notes       {modelId, fields: string[]}
 * @param {Map<string, Uint8Array>} opts.media  filename -> bytes
 * @param {number}   opts.timestamp   seconds since epoch (fixed for hermetic builds)
 * @param {function} opts.onProgress
 * @returns {Promise<Blob>}
 */
export async function buildApkg(opts) {
  const {
    deckId, deckName, deckDescription = '', models, notes, media,
    timestamp = Date.now() / 1000, onProgress = () => {},
  } = opts;

  onProgress('opening sqlite');
  const SQL = await initSqlJs({ locateFile: (f) => 'vendor/' + f });
  const db = new SQL.Database();
  db.run(APKG_SCHEMA);

  // The seed col row. genanki executes a literal INSERT; parameters are used
  // here so the blobs stay byte-exact without SQL-escaping games.
  db.run(
    'INSERT INTO col VALUES(null,1411124400,1425279151694,1425279151690,11,0,0,0,?,?,?,?,?)',
    [COL_CONF, '{}', pyJson(COL_DECKS_DEFAULT), COL_DCONF, '{}']);

  const decks = new Map(COL_DECKS_DEFAULT);
  decks.set(String(deckId), deckJson(deckId, deckName, deckDescription));
  db.run('UPDATE col SET decks = ?', [pyJson(decks)]);

  // Only models actually referenced by a note, in first-use order — matching
  // genanki, which collects models off the notes as it writes them.
  const usedModels = new Map();
  for (const note of notes) {
    const m = models.find((x) => x.id === note.modelId);
    if (!usedModels.has(m.id)) usedModels.set(m.id, m);
  }
  const modelsBlob = new Map();
  for (const m of usedModels.values()) {
    modelsBlob.set(String(m.id), modelJson(m, timestamp, deckId));
  }
  db.run('UPDATE col SET models = ?', [pyJson(modelsBlob)]);

  onProgress('writing notes');
  let nextId = Math.floor(timestamp * 1000);
  const insertNote = db.prepare('INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?,?)');
  const insertCard = db.prepare('INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)');
  const mod = Math.floor(timestamp);

  for (const note of notes) {
    const model = usedModels.get(note.modelId);
    const req = computeReq(model.fields, model.templates);
    const guid = note.guid ?? await guidFor(...note.fields);
    const noteId = nextId++;
    insertNote.run([noteId, guid, model.id, mod, -1, ' ' + (note.tags ?? []).join(' ') + ' ',
                    note.fields.join('\x1f'), note.fields[0], 0, 0, '']);
    for (const [cardOrd, anyOrAll, fieldOrds] of req) {
      const vals = fieldOrds.map((o) => Boolean(note.fields[o]));
      const ok = anyOrAll === 'any' ? vals.some(Boolean) : vals.every(Boolean);
      if (!ok) continue;
      insertCard.run([nextId++, noteId, deckId, cardOrd, mod, -1, 0, 0, 0,
                      0, 0, 0, 0, 0, 0, 0, 0, '']);
    }
  }
  insertNote.free();
  insertCard.free();

  onProgress('exporting sqlite');
  const dbBytes = db.export();
  db.close();

  onProgress('zipping');
  const zip = new JSZip();
  zip.file('collection.anki2', dbBytes);
  const mediaMap = new Map();
  let idx = 0;
  for (const [filename, bytes] of media) {
    mediaMap.set(String(idx), filename);
    zip.file(String(idx), bytes);
    idx++;
  }
  zip.file('media', pyJson(mediaMap));

  // STORE, not DEFLATE: jpeg and mp3 are already compressed, and deflating a
  // few hundred MB in JS is the slowest thing in the whole pipeline.
  return zip.generateAsync(
    { type: 'blob', compression: 'STORE' },
    (meta) => onProgress(`zipping ${meta.percent.toFixed(0)}%`));
}
