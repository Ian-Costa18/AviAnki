// Python-compatible JSON. `JSON.stringify` is not interchangeable with `json.dumps`, and
// the differences corrupt the collection silently:
//   - Python's default separators are ", " and ": " (JS uses "," and ":").
//   - Python defaults to ensure_ascii=True: every character outside space..~ is escaped
//     (the card templates hold non-ASCII text), astral characters as surrogate pairs.
//   - JS objects reorder integer-like keys ascending. The `models` blob is keyed by numeric
//     note-type ids, so it is built from a Map, which keeps insertion order.

const ESCAPES = {
  "\\": "\\\\", '"': '\\"', "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t",
};

const hex4 = (n) => "\\u" + n.toString(16).padStart(4, "0");

function pyString(s) {
  let out = '"';
  // for..of walks code points; a lone surrogate arrives as itself and is escaped as Python does.
  for (const ch of s) {
    const cp = ch.codePointAt(0);
    if (ESCAPES[ch]) out += ESCAPES[ch];
    else if (cp >= 0x20 && cp < 0x7f) out += ch;
    else if (cp <= 0xffff) out += hex4(cp);
    else {
      const v = cp - 0x10000;
      out += hex4(0xd800 + (v >> 10)) + hex4(0xdc00 + (v & 0x3ff));
    }
  }
  return out + '"';
}

/**
 * `json.dumps(value)` for null, booleans, integers, strings, arrays, Maps and plain objects.
 * Object and Map entries keep their insertion order. Non-integer numbers are refused rather
 * than risk a float repr that differs from Python's.
 * @param {unknown} v
 * @returns {string}
 */
export function pyJson(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") {
    if (!Number.isInteger(v)) throw new TypeError(`pyJson: only integers are supported, got ${v}`);
    return String(v);
  }
  if (typeof v === "string") return pyString(v);
  if (Array.isArray(v)) return "[" + v.map(pyJson).join(", ") + "]";
  const entries = v instanceof Map ? [...v.entries()] : Object.entries(v);
  return "{" + entries.map(([k, val]) => pyString(String(k)) + ": " + pyJson(val)).join(", ") + "}";
}
