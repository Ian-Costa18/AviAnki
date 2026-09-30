"""Helpers for the CLI tests: run `avianki.cli.main` against the fixture catalog, offline."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from avianki import cli

FIXTURE_CATALOG = Path(__file__).parent / "fixtures" / "catalog"
__all__ = ["FIXTURE_CATALOG", "Result", "deck_info", "note_fields", "read_apkg", "run_cli"]


def read_apkg(path: Path) -> tuple[sqlite3.Connection, dict[str, str]]:
    """The collection database and media map inside an .apkg (genanki's own layout)."""
    with zipfile.ZipFile(path) as zf:
        db = path.with_suffix(".anki2")
        db.write_bytes(zf.read("collection.anki2"))
        media = json.loads(zf.read("media"))
    return sqlite3.connect(db), media


def note_fields(path: Path) -> list[list[str]]:
    conn, _ = read_apkg(path)
    try:
        return [row[0].split("\x1f") for row in conn.execute("SELECT flds FROM notes ORDER BY id")]
    finally:
        conn.close()


def deck_info(path: Path) -> list[dict]:
    conn, _ = read_apkg(path)
    try:
        decks = json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
    finally:
        conn.close()
    return [d for d in decks.values() if d["name"] != "Default"]


@dataclass
class Result:
    code: int
    out: str
    err: str
    cwd: Path


def run_cli(
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    catalog: Path | str | None = FIXTURE_CATALOG,
    env: dict[str, str | None] | None = None,
) -> Result:
    """Run the CLI in ``tmp_path`` (so default output names land there), with a private cache.

    ``env`` sets (or, for None, removes) environment variables. .env loading is switched off so
    a developer's real EBIRD_API_KEY never leaks into a test.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv(cli.EBIRD_KEY_VAR, raising=False)
    for name, value in (env or {}).items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    args = list(argv)
    if catalog is not None:
        args += ["--catalog-url", str(catalog)]
    args += ["--cache-dir", str(tmp_path / "cache")]
    code = cli.main(args)
    captured = capsys.readouterr()
    return Result(code, captured.out, captured.err, tmp_path)
