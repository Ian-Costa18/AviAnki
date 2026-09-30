# Vendored libraries

Checked in, pinned, never fetched from a CDN at run time (spec section 6, ADR 0006). Files are
byte-for-byte copies from the npm tarballs below; nothing is patched. `.gitattributes` marks this
directory `-text` so a checkout never rewrites line endings and breaks the hashes.

| Library | Version | Used for | Licence |
|---|---|---|---|
| [sql.js](https://github.com/sql-js/sql.js) | 1.14.2 | SQLite in WebAssembly: writes the `collection.anki2` database | MIT (`LICENSE.sql.js`) |
| [fflate](https://github.com/101arrowz/fflate) | 0.8.3 | Streaming zip writer (`Zip`, `ZipPassThrough`, store mode) | MIT (`LICENSE.fflate`) |

## Sources

| Tarball | sha256 |
|---|---|
| `https://registry.npmjs.org/sql.js/-/sql.js-1.14.2.tgz` | `9d491337e1850df39362be640c23f9751bf0fbd33fc232c2a580bb87b70d62fd` |
| `https://registry.npmjs.org/fflate/-/fflate-0.8.3.tgz` | `38c2cd824402407b43153c782274aec2ea83ea688e4aa0b743c5f2c305857d92` |

## Files

| File | From the tarball | sha256 |
|---|---|---|
| `sql-wasm.js` | `sql.js/dist/sql-wasm.js` | `f1c84000dbc856c9d87f4f3aabc4d3654bd436165db4be3da13751db3a9c20d7` |
| `sql-wasm.wasm` | `sql.js/dist/sql-wasm.wasm` | `38c14f6e379210bc942bdc4ebca44e7bfdb4318ecc1c72ca666a28fdce96670a` |
| `fflate.js` | `fflate/esm/browser.js` (the ES-module browser build) | `b7ca4450b19559a1d50eb381adcee94b82449674be4cd17789d9beba7e6122a1` |
| `LICENSE.sql.js` | `sql.js/LICENSE` | `60a3f6e4d7b29b4321359e683b36cf198d24f58e24582070f56e6fa89d5ee2be` |
| `LICENSE.fflate` | `fflate/LICENSE` | `0a1df3a083d0c010560aa342e87959c8c1070e6fd54545741f083f22d0c8b551` |

`sql-wasm.js` is a classic script (UMD) that defines `initSqlJs`; `web/js/apkg/writer.js` loads it
by script injection and points `locateFile` at this directory for the `.wasm`. `fflate.js` is an
ES module and is imported directly.

## Upgrading

Download the new tarballs, copy the same five files, update the versions and hashes above, and
run `uv run pytest tests/web`: the equivalence tests compare the resulting `.apkg` with genanki's,
so a library change that alters the output fails there.
