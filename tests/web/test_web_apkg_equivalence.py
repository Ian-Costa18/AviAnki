"""The browser writer against genanki (ADR 0006, 0019).

For a fixed timestamp the browser and ``avianki.deck.build.write_deck`` must produce the same
deck. Like the prototype's ``compare_apkg.py``, but stricter: every column of every row, its
SQLite storage class too, and the exact text of the JSON blobs. What is not compared, and why:

* The SQLite file bytes and the zip container bytes. Page layout, the file-change counter and
  the SQLite version stamp belong to the SQLite build, and zip entries carry the writer's own
  timestamps (genanki uses the temp file's mtime) and an optional data descriptor. The tests
  check what both writers control: the entry names and order, the store method, the sizes and
  CRCs, and everything inside the database.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from web_support import CATALOG_DIR, Spec, build_in_browser, build_with_python, parsed, read_package

from avianki.catalog.format import load_catalog

SPECS = {
    "us-ma standard, default cards": Spec(),
    "us-ma standard, all three card types": Spec(cards=("photo", "audio", "photo_audio")),
    "ca-qc with a subdeck": Spec(region="ca-qc", subdeck="Québec"),
    "ebird description": Spec(ebird=True, cards=("photo_audio",)),
    "month filter (June)": Spec(month=6, tier="everything"),
    "month filter (January, photos)": Spec(month=1, cards=("photo",)),
    "us-az everything, all cards, a whole-second timestamp": Spec(
        region="us-az", tier="everything", cards=("photo", "audio", "photo_audio"), timestamp=1_600_000_000.0
    ),
}


def compare(browser_apkg: bytes, python_apkg: Path, tmp_path: Path) -> tuple:
    a = read_package(browser_apkg, tmp_path, "browser")
    b = read_package(python_apkg, tmp_path, "genanki")

    # the container: same entries in the same order, stored, same content
    assert a.names == b.names
    assert a.compress_types == b.compress_types == {zipfile.ZIP_STORED}
    with zipfile.ZipFile(tmp_path / "browser.apkg") as za, zipfile.ZipFile(python_apkg) as zb:
        for name in a.names:
            ia, ib = za.getinfo(name), zb.getinfo(name)
            if name != "collection.anki2":  # the database bytes are compared through its rows
                assert (ia.file_size, ia.CRC) == (ib.file_size, ib.CRC), name

    # the media map (exact text) and the media bytes
    assert a.media_json == b.media_json
    assert a.media_files == b.media_files

    # the col row: exact strings, then parsed
    for key in ("conf", "models", "decks", "dconf", "tags"):
        assert a.col[key] == b.col[key], f"col.{key} differs as text"
        assert parsed(a, key) == parsed(b, key)

    # every row of every table, column by column with its storage class
    for table in a.tables:
        assert a.tables[table] == b.tables[table], table
    assert a.schema == b.schema
    return a, b


@pytest.mark.parametrize("name", list(SPECS))
def test_browser_deck_equals_genanki_deck(name, page, tmp_path) -> None:
    spec = SPECS[name]
    built = build_in_browser(page, spec)
    python = build_with_python(spec, tmp_path / "genanki.apkg")
    a, _ = compare(built.apkg, tmp_path / "genanki.apkg", tmp_path)

    assert built.summary["notesByType"] == python["notes_by_type"]
    assert built.summary["mediaCount"] == python["media_count"] == len(a.media_files)
    assert built.summary["bytes"] == len(built.apkg)
    assert built.summary["noteCount"] == built.note_count == len(a.tables["notes"]) > 0
    assert built.type == "application/octet-stream"


@pytest.mark.parametrize("name", ["us-ma standard, all three card types", "ca-qc with a subdeck"])
def test_the_database_bytes_are_recorded(name, chromium_page, tmp_path) -> None:
    """Informational: are the two SQLite files byte-identical? (No assertion; see the docstring.)"""
    spec = SPECS[name]
    built = build_in_browser(chromium_page, spec)
    build_with_python(spec, tmp_path / "genanki.apkg")
    a = read_package(built.apkg, tmp_path, "browser")
    b = read_package(tmp_path / "genanki.apkg", tmp_path, "genanki")
    print(f"\n{name}: sqlite bytes browser={len(a.db_bytes)} genanki={len(b.db_bytes)} identical={a.db_bytes == b.db_bytes}")


def test_the_same_build_twice_is_the_same_package(chromium_page) -> None:
    """Fixed timestamp in, byte-identical package out (zip entries carry no wall-clock time)."""
    one = build_in_browser(chromium_page, SPECS["ca-qc with a subdeck"])
    two = build_in_browser(chromium_page, SPECS["ca-qc with a subdeck"])
    assert one.apkg == two.apkg


def test_ids_and_identity_match_the_frozen_strings(chromium_page, tmp_path) -> None:
    """Independent of genanki's writer: ADR 0009's deck id, model ids and note GUIDs, from Python's helpers."""
    from avianki.deck.build import deck_id, note_guid, plan_notes, select_species
    from avianki.deck.notetypes import MODELS

    spec = Spec(region="ca-qc", subdeck="Québec", cards=("photo", "audio", "photo_audio"))
    pkg = read_package(build_in_browser(chromium_page, spec).apkg, tmp_path, "browser")

    decks = parsed(pkg, "decks")
    assert set(decks) == {"1", str(deck_id("AviAnki::Québec"))}
    assert deck_id("AviAnki") == 2854063212
    assert set(parsed(pkg, "models")) == {str(m.model_id) for m in MODELS.values()}

    catalog = load_catalog(CATALOG_DIR)
    ids = select_species(catalog.regions["ca-qc"], catalog.species, spec.cards, tier="standard", month=None)
    expected = {note_guid(n.species_id, n.card_type) for n in plan_notes(ids, catalog.species, spec.cards)}
    assert {row[3] for row in pkg.tables["notes"]} == expected  # rows are (typeof, value) pairs: id, guid, ...


def test_media_names_are_package_names(chromium_page, tmp_path) -> None:
    built = build_in_browser(chromium_page, Spec(cards=("photo", "audio")))
    pkg = read_package(built.apkg, tmp_path, "browser")
    mapping = json.loads(pkg.media_json)
    assert list(mapping) == [str(i) for i in range(len(mapping))]
    assert all(v.startswith("avianki_") and "/" not in v for v in mapping.values())


def test_the_ioc_name_is_filled_only_where_the_catalog_has_one(chromium_page, tmp_path) -> None:
    """IocName is the ninth field (ADR 0027): the fixture's Mallard has one, every other species is empty."""
    spec = Spec(tier="everything", cards=("photo",))
    pkg = read_package(build_in_browser(chromium_page, spec).apkg, tmp_path, "browser")
    by_id = {}
    for row in pkg.tables["notes"]:
        fields = row[13].split("\x1f")  # flds: column 6, as a (typeof, value) pair
        assert len(fields) == 9
        by_id[fields[0]] = fields[8]
    assert by_id["anas-platyrhynchos"] == "Wild Duck"
    assert {v for k, v in by_id.items() if k != "anas-platyrhynchos"} == {""}
