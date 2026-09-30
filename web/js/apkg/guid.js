// genanki.util.guid_for: the first 8 bytes of SHA-256 of the values joined with "__",
// read as a big-endian integer and written in Anki's base-91 alphabet. AviAnki's note GUID
// is guidFor("avianki", speciesId, cardType) and is frozen (ADR 0009).

const BASE91 = (
  "abcdefghijklmnopqrstuvwxyz" +
  "ABCDEFGHIJKLMNOPQRSTUVWXYZ" +
  "0123456789!#$%&()*+,-./:;<=>?@[]^_`{|}~"
).split("");

/**
 * WebCrypto's digest is async, so this is too. It needs a secure context (https or
 * localhost), which GitHub Pages and the local test server both are.
 * @param {...(string|number)} values
 * @returns {Promise<string>}
 */
export async function guidFor(...values) {
  const hashStr = values.map(String).join("__");
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(hashStr)),
  );
  // Eight bytes do not fit a double exactly, hence BigInt.
  let n = 0n;
  for (let i = 0; i < 8; i++) n = (n << 8n) + BigInt(digest[i]);
  const base = BigInt(BASE91.length);
  const out = [];
  while (n > 0n) {
    out.push(BASE91[Number(n % base)]);
    n /= base;
  }
  return out.reverse().join("");
}
