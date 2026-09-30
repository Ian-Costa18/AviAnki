"""Shared helpers for the browser tests: a static server for ``web/`` plus the fixture catalog,
a driver that builds a deck in the page, and the same build through the Python writer.

The server answers ``/catalog/...`` from ``tests/fixtures/catalog`` (or another directory) and
everything else from ``web/``, which is the layout ``scripts/assemble_site.py`` publishes. The
manifest it serves has its ``base_url`` rewritten to point back at the server, because the
fixture's is a placeholder and the app resolves every catalog path against it (ADR 0013).

Run ``uv run python tests/web/web_support.py`` to serve the app locally on the fixture catalog.
"""

from __future__ import annotations

import base64
import http.server
import json
import sqlite3
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
WEB_DIR = REPO / "web"
CATALOG_DIR = REPO / "tests" / "fixtures" / "catalog"

# Fixed so a browser build and a genanki build are comparable to the millisecond. The fraction
# checks that note ids use int(timestamp * 1000) and `mod` uses int(timestamp).
TIMESTAMP = 1_700_000_000.123

# Windows' registry can map .js to text/plain, which browsers refuse as a module script.
MIME_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".html": "text/html",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
}

BLANK_PAGE = b"<!doctype html><meta charset=utf-8><title>web test</title><body></body>"


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **MIME_TYPES}
    # Keep-alive: with HTTP/1.0 every module is a new connection, and on Windows one of a
    # burst is occasionally refused, failing a dynamic import at random.
    protocol_version = "HTTP/1.1"

    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/catalog/"):
            root, rel = self.server.catalog_dir, path[len("/catalog/") :]  # type: ignore[attr-defined]
        else:
            root, rel = WEB_DIR, path.lstrip("/")
        return str((root / rel).resolve())

    def end_headers(self) -> None:
        # The published catalog sends this too, which is what lets ?catalog=<url> work cross-origin.
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        if self.path.split("?", 1)[0] == "/__blank.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(BLANK_PAGE)))
            self.end_headers()
            self.wfile.write(BLANK_PAGE)
            return
        if self.path.split("?", 1)[0] == "/catalog/manifest.json":
            self._send_manifest()
            return
        super().do_GET()

    def _send_manifest(self) -> None:
        catalog_dir: Path = self.server.catalog_dir  # type: ignore[attr-defined]
        manifest = json.loads((catalog_dir / "manifest.json").read_text(encoding="utf-8"))
        host, port = self.server.server_address[:2]
        manifest["base_url"] = f"http://{host}:{port}/catalog/"
        body = json.dumps(manifest).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class _Server(http.server.ThreadingHTTPServer):
    request_queue_size = 128  # a browser opens many connections at once; the default of 5 refuses some
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A browser closing a kept-alive connection isn't a server error.
        import sys

        if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            super().handle_error(request, client_address)


@contextmanager
def serve(catalog_dir: Path = CATALOG_DIR) -> Iterator[str]:
    """Serve ``web/`` and a catalog (the fixture's by default) on 127.0.0.1, a secure context.

    Secure, so WebCrypto and Cache Storage work as they do on the deployed site.
    """
    server = _Server(("127.0.0.1", 0), partial(_Handler))
    server.catalog_dir = catalog_dir  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@dataclass
class Spec:
    """One deck: what to select and how to write it (the same for the browser and Python)."""

    region: str = "us-ma"
    tier: str = "standard"
    month: int | None = None
    cards: tuple[str, ...] = ("photo", "audio")  # the CLI's default
    subdeck: str | None = None
    ebird: bool = False
    timestamp: float = TIMESTAMP

    def js(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "tier": self.tier,
            "month": self.month,
            "cards": list(self.cards),
            "subdeck": self.subdeck,
            "ebird": self.ebird,
            "timestamp": self.timestamp,
        }


# Runs in the page: load the catalog files the way the app will, select, plan, build.
BUILD_JS = """
async (spec) => {
  const { selectSpecies, planNotes } = await import('/js/select.js');
  const { buildDeck } = await import('/js/deck.js');
  const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
  const json = async (path) => (await fetch('/catalog/' + path)).json();
  const manifest = await json('manifest.json');
  const ref = manifest.regions.find((r) => r.slug === spec.region);
  const region = await json(ref.file);
  const speciesFile = await json(manifest.species_file);
  const ids = selectSpecies(region, { tier: spec.tier, month: spec.month });
  const notes = planNotes(ids, speciesFile, spec.cards);
  const before = performance.memory ? performance.memory.usedJSHeapSize : null;
  const fetchBytes = async (file, signal) => {
    const response = await fetch('/catalog/' + file, { signal });
    return new Uint8Array(await response.arrayBuffer());
  };
  const { blob, summary } = await buildDeck({
    manifest, speciesFile, notes,
    subdeck: spec.subdeck, ebird: spec.ebird, timestamp: spec.timestamp,
    media: (files) => orderedPrefetch(files, fetchBytes),
  });
  const after = performance.memory ? performance.memory.usedJSHeapSize : null;
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return {
    b64: btoa(binary), summary, type: blob.type, before, after,
    noteCount: notes.length,
  };
}
"""


@dataclass
class BrowserBuild:
    apkg: bytes
    summary: dict[str, Any]
    type: str
    heap_before: int | None
    heap_after: int | None
    note_count: int


def build_in_browser(page: Any, spec: Spec) -> BrowserBuild:
    out = page.evaluate(BUILD_JS, spec.js())
    return BrowserBuild(
        base64.b64decode(out["b64"]),
        out["summary"],
        out["type"],
        out["before"],
        out["after"],
        out["noteCount"],
    )


def build_with_python(spec: Spec, out: Path) -> dict[str, Any]:
    """The same deck through ``avianki.deck.build.write_deck`` (genanki), from the same files."""
    from avianki.catalog.format import load_catalog
    from avianki.deck.build import plan_notes, select_species, write_deck

    catalog = load_catalog(CATALOG_DIR)
    ids = select_species(catalog.regions[spec.region], tier=spec.tier, month=spec.month)
    notes = plan_notes(ids, catalog.species, spec.cards)
    summary = write_deck(
        notes,
        catalog.species,
        catalog.manifest,
        media=catalog.media_path,
        out=out,
        subdeck=spec.subdeck,
        ebird=spec.ebird,
        timestamp=spec.timestamp,
    )
    return {"notes_by_type": summary.notes_by_type, "media_count": summary.media_count}


# ---------------------------------------------------------------------------------------
# Reading a package the way compare_apkg.py did
# ---------------------------------------------------------------------------------------

TABLES = ("col", "notes", "cards", "revlog", "graves")


@dataclass
class Package:
    names: list[str]
    media_json: str
    media_files: dict[str, bytes]
    compress_types: set[int]
    db_bytes: bytes
    tables: dict[str, list[tuple]]  # every row, every column as (typeof, value)
    schema: list[tuple]
    col: dict[str, Any]  # the col row's text columns, by name


def read_package(apkg: bytes | Path, workdir: Path, label: str) -> Package:
    path = workdir / f"{label}.apkg"
    if isinstance(apkg, bytes):
        path.write_bytes(apkg)
    else:
        path = Path(apkg)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        db_bytes = zf.read("collection.anki2")
        media_json = zf.read("media").decode("utf-8")
        media_files = {n: zf.read(n) for n in names if n not in ("collection.anki2", "media")}
        compress = {zf.getinfo(n).compress_type for n in names}
    db_path = workdir / f"{label}.anki2"
    db_path.write_bytes(db_bytes)
    con = sqlite3.connect(db_path)
    tables: dict[str, list[tuple]] = {}
    for table in TABLES:
        columns = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        select = ", ".join(f"typeof({c}), {c}" for c in columns)
        order = "" if table in ("col", "graves") else " ORDER BY id"
        tables[table] = con.execute(f"SELECT {select} FROM {table}{order}").fetchall()
    schema = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name").fetchall()
    col_names = ("conf", "models", "decks", "dconf", "tags")
    col = dict(zip(col_names, con.execute("SELECT conf, models, decks, dconf, tags FROM col").fetchone()))
    con.close()
    return Package(names, media_json, media_files, compress, db_bytes, tables, schema, col)


def parsed(package: Package, key: str) -> Any:
    return json.loads(package.col[key])


if __name__ == "__main__":  # a local copy of the site, on the fixture catalog
    import time

    with serve() as url:
        print(f"AviAnki is at {url}/  (fixture catalog; Ctrl+C to stop)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
