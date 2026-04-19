"""
Integration test: runs the real CLI against allaboutbirds.org and verifies
the output deck contains the expected birds.

Run with:  uv run pytest --integration
Skipped by default to avoid network access in normal test runs.
"""

import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from avianki import cli

PLACE_ID = "ChIJGzE9DS1l44kRoOhiASS_fHg"
EXPECTED_BIRDS = ["House Sparrow", "American Robin", "American Herring Gull"]
EXPECTED_MEDIA_COUNT = 11  # 2 img + 1 call + 1 song per bird, except Herring Gull has no song


TMP_DIR = Path(__file__).parent / "tmp"
MEDIA_DIR = Path(__file__).parent / "media"


@pytest.mark.integration
def test_place_id_deck_end_to_end():
    shutil.rmtree(MEDIA_DIR, ignore_errors=True)
    TMP_DIR.mkdir(exist_ok=True)
    apkg = TMP_DIR / f"Birds_{PLACE_ID}.apkg"
    sys.argv = [
        "avianki", PLACE_ID,
        "--limit", "3",
        "--output", str(apkg),
        "--media-dir", str(MEDIA_DIR),
        "--json-file", str(TMP_DIR / "birds.json"),
        "--log-file", str(TMP_DIR / "avianki.log"),
    ]
    cli.main()

    assert apkg.exists(), f"{apkg.name} not created"
    assert zipfile.is_zipfile(apkg), "Output is not a valid zip/apkg"

    with zipfile.ZipFile(apkg) as zf:
        names_in_zip = zf.namelist()
        assert "collection.anki2" in names_in_zip, "Missing collection.anki2"

        media_files = [n for n in names_in_zip if n not in ("collection.anki2", "media")]
        assert len(media_files) == EXPECTED_MEDIA_COUNT, (
            f"Expected {EXPECTED_MEDIA_COUNT} media files, got {len(media_files)}: {media_files}"
        )

        db_bytes = zf.read("collection.anki2")

    db_path = TMP_DIR / "collection.anki2"
    db_path.write_bytes(db_bytes)

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT flds FROM notes ORDER BY id").fetchall()
    con.close()

    # 2 notes per species: one Photo card and one Audio ID card
    assert len(rows) == len(EXPECTED_BIRDS) * 2, f"Expected {len(EXPECTED_BIRDS) * 2} notes, got {len(rows)}"

    bird_names_in_deck = sorted({row[0].split("\x1f")[0] for row in rows})
    assert bird_names_in_deck == sorted(EXPECTED_BIRDS), (
        f"Bird names mismatch.\nExpected: {sorted(EXPECTED_BIRDS)}\nGot:      {bird_names_in_deck}"
    )
