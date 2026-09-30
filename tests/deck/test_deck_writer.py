"""`write_deck`: the .apkg is a zip of ``collection.anki2`` (sqlite) and a ``media`` json map."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from deck_fakes import manifest, species_file

from avianki.deck.build import DeckSummary, plan_notes, write_deck

ALL_CARDS = {"photo", "audio", "photo_audio"}
IDS = ["turdus-migratorius", "cyanocitta-cristata", "troglodytes-aedon", "tom-and-jerry"]
SEP = "\x1f"  # Anki's field separator


def make_media(root: Path) -> "callable":
    """A ``media(catalog_file)`` callable over tiny synthesized files (genanki never reads them)."""
    root.mkdir(parents=True, exist_ok=True)

    def media(catalog_file: str) -> Path:
        path = root / Path(catalog_file).name
        if not path.exists():
            path.write_bytes(b"x-" + catalog_file.encode())
        return path

    return media


def build(tmp_path: Path, name: str = "deck.apkg", *, ids=IDS, cards=ALL_CARDS, **kwargs):
    sp = species_file()
    notes = plan_notes(ids, sp, cards)
    summary = write_deck(
        notes,
        sp,
        manifest(),
        media=make_media(tmp_path / "cache"),
        out=tmp_path / name,
        timestamp=1_700_000_000.0,
        **kwargs,
    )
    return summary, notes


def read_apkg(path: Path) -> tuple[sqlite3.Connection, dict[str, str], zipfile.ZipFile]:
    zf = zipfile.ZipFile(path)
    db_path = path.parent / (path.stem + ".anki2")
    db_path.write_bytes(zf.read("collection.anki2"))
    conn = sqlite3.connect(db_path)
    return conn, json.loads(zf.read("media")), zf


def notes_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT guid, mid, flds, sfld, tags FROM notes ORDER BY id").fetchall()


def test_summary(tmp_path: Path) -> None:
    summary, notes = build(tmp_path)
    assert isinstance(summary, DeckSummary)
    assert summary.path == tmp_path / "deck.apkg" and summary.path.is_file()
    assert summary.deck_name == "AviAnki"
    assert summary.note_count == len(notes) == 6
    assert summary.notes_by_type == {"photo": 3, "audio": 2, "photo_audio": 1}
    # robin photo+audio, jay photo (tom shares it: counted once), wren audio
    assert summary.media_count == 4


def test_deck_name_id_and_description(tmp_path: Path) -> None:
    build(tmp_path)
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    decks = json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
    ours = [d for d in decks.values() if d["name"] != "Default"]
    assert len(ours) == 1
    assert ours[0]["name"] == "AviAnki" and ours[0]["id"] == 2854063212
    desc = ours[0]["desc"]
    assert "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF" in desc
    assert "This deck is a compilation. AviAnki's templates and selection are MIT-licensed." in desc
    assert "Built from eBird data" not in desc


def test_ebird_flag_adds_the_redistribution_line(tmp_path: Path) -> None:
    build(tmp_path, ebird=True)
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    decks = json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
    desc = next(d["desc"] for d in decks.values() if d["name"] != "Default")
    assert "eBird's terms don't allow redistributing this deck." in desc


def test_subdeck_name_and_id(tmp_path: Path) -> None:
    summary, _ = build(tmp_path, subdeck="Massachusetts")
    assert summary.deck_name == "AviAnki::Massachusetts"
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    decks = json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
    (ours,) = [d for d in decks.values() if d["name"] != "Default"]
    assert ours["name"] == "AviAnki::Massachusetts" and ours["id"] == 3074061584


def test_models_and_guids(tmp_path: Path) -> None:
    build(tmp_path)
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    models = json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
    assert {m["name"]: int(mid) for mid, m in models.items()} == {
        "AviAnki · Photo": 717156105,
        "AviAnki · Audio": 3710911882,
        "AviAnki · Photo + Audio": 327952205,
    }
    rows = {(r[0]): r for r in notes_rows(conn)}
    assert "y^.Qw>j5t" in rows  # turdus-migratorius, photo
    assert "sN^~,`kZon" in rows  # turdus-migratorius, audio
    photo_row = rows["y^.Qw>j5t"]
    assert photo_row[1] == 717156105


def test_fields(tmp_path: Path) -> None:
    build(tmp_path, ids=["turdus-migratorius"])
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    by_guid = {r[0]: r[2].split(SEP) for r in notes_rows(conn)}
    sp = species_file()["turdus-migratorius"]

    photo = by_guid["y^.Qw>j5t"]
    assert photo[:3] == ["turdus-migratorius", "American Robin", "Turdus migratorius"]
    assert photo[3] == '<img src="avianki_1a2b3c4d5e6f7a8b.webp">'
    # Every back shows the photo and plays the recording, so every note carries both (spec §6).
    assert photo[5] == "[sound:avianki_9f8e7d6c5b4a3921.mp3]" and photo[4] == "" and photo[6] == ""
    assert sp.photo[0].credit in photo[7] and sp.audio[0].credit in photo[7]

    audio = by_guid["sN^~,`kZon"]
    assert audio[3:] == photo[3:]

    assert len(by_guid) == 3 and all(f[3:] == photo[3:] for f in by_guid.values())


def test_names_are_escaped(tmp_path: Path) -> None:
    build(tmp_path, ids=["tom-and-jerry"], cards={"photo"})
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    (row,) = notes_rows(conn)
    fields = row[2].split(SEP)
    assert fields[1] == "Tom &amp; &lt;Jerry&gt;"
    assert fields[2] == "Muris &lt;x&gt; &amp; y"


def test_media_names_and_contents(tmp_path: Path) -> None:
    build(tmp_path)
    conn, media_map, zf = read_apkg(tmp_path / "deck.apkg")
    assert sorted(media_map.values()) == sorted(
        [
            "avianki_1a2b3c4d5e6f7a8b.webp",
            "avianki_9f8e7d6c5b4a3921.mp3",
            "avianki_1111111111111111.webp",
            "avianki_3333333333333333.mp3",
        ]
    )
    # The second jay photo is never used.
    assert "avianki_2222222222222222.webp" not in media_map.values()
    idx = {v: k for k, v in media_map.items()}
    assert zf.read(idx["avianki_1a2b3c4d5e6f7a8b.webp"]) == b"x-media/1a2b3c4d5e6f7a8b.webp"


def test_notes_are_ordered_by_rank_then_card_type(tmp_path: Path) -> None:
    build(tmp_path, ids=["troglodytes-aedon", "turdus-migratorius"])
    conn, _, _ = read_apkg(tmp_path / "deck.apkg")
    ids = [r[2].split(SEP)[0] for r in notes_rows(conn)]
    mids = [r[1] for r in notes_rows(conn)]
    assert ids == ["troglodytes-aedon", "turdus-migratorius", "turdus-migratorius", "turdus-migratorius"]
    assert mids == [3710911882, 717156105, 3710911882, 327952205]


def test_two_writes_give_identical_notes(tmp_path: Path) -> None:
    build(tmp_path, "a.apkg")
    build(tmp_path, "b.apkg", ids=list(IDS))
    ca, _, _ = read_apkg(tmp_path / "a.apkg")
    cb, _, _ = read_apkg(tmp_path / "b.apkg")
    assert notes_rows(ca) == notes_rows(cb)
    assert ca.execute("SELECT * FROM notes ORDER BY id").fetchall() == cb.execute(
        "SELECT * FROM notes ORDER BY id"
    ).fetchall()


def test_output_does_not_depend_on_cards_set_order(tmp_path: Path) -> None:
    build(tmp_path, "a.apkg", cards={"photo", "audio", "photo_audio"})
    build(tmp_path, "b.apkg", cards={"photo_audio", "photo", "audio"})
    ca, _, _ = read_apkg(tmp_path / "a.apkg")
    cb, _, _ = read_apkg(tmp_path / "b.apkg")
    assert notes_rows(ca) == notes_rows(cb)


def test_without_a_timestamp_rows_still_match_apart_from_ids(tmp_path: Path) -> None:
    sp = species_file()
    notes = plan_notes(IDS, sp, ALL_CARDS)
    for name in ("a.apkg", "b.apkg"):
        write_deck(notes, sp, manifest(), media=make_media(tmp_path / "cache"), out=tmp_path / name)
    ca, _, _ = read_apkg(tmp_path / "a.apkg")
    cb, _, _ = read_apkg(tmp_path / "b.apkg")
    assert notes_rows(ca) == notes_rows(cb)


def test_missing_media_is_an_error_not_a_silent_skip(tmp_path: Path) -> None:
    sp = species_file()
    notes = plan_notes(["turdus-migratorius"], sp, {"photo"})

    def missing(_: str) -> Path:
        return tmp_path / "nope.webp"

    with pytest.raises(FileNotFoundError):
        write_deck(notes, sp, manifest(), media=missing, out=tmp_path / "x.apkg")


def test_creates_the_output_directory(tmp_path: Path) -> None:
    sp = species_file()
    out = tmp_path / "new" / "dir" / "deck.apkg"
    write_deck(
        plan_notes(["turdus-migratorius"], sp, {"photo"}),
        sp,
        manifest(),
        media=make_media(tmp_path / "cache"),
        out=out,
    )
    assert out.is_file()
