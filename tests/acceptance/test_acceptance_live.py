"""Acceptance against the LIVE published catalog (run with --integration).

Builds the Standard us-ma deck from the real catalog on GitHub Pages, imports it into a fresh
Anki collection and runs checks 1, 5 and 6 (imports cleanly, fronts do not leak the name, every
answer credits its assets). This is what catches a published catalog that the fixture cannot.
It downloads about 200 media files.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("anki.collection")

from acceptance_support import (  # noqa: E402
    assert_clean_media,
    assert_credits_on_answers,
    assert_no_name_leak,
    card_count,
    import_apkg,
    note_count,
    open_collection,
    rendered_cards,
)
from cli_fakes import run_cli  # noqa: E402

from avianki.catalog.client import CatalogClient  # noqa: E402
from avianki.catalog.format import DEFAULT_BASE_URL  # noqa: E402

LIVE_CATALOG = "https://ian-costa18.github.io/AviAnki/catalog/"


@pytest.mark.integration
def test_the_live_us_ma_deck_imports_cleanly_with_no_leaks_and_full_credits(tmp_path, monkeypatch, capsys):
    assert LIVE_CATALOG == DEFAULT_BASE_URL  # the CLI default is the catalog under test
    out = tmp_path / "AviAnki-us-ma.apkg"
    started = time.monotonic()
    result = run_cli(["us-ma", "-o", str(out), "-q"], tmp_path, monkeypatch, capsys, catalog=LIVE_CATALOG)
    built = time.monotonic() - started
    assert result.code == 0, result.err

    col = open_collection(tmp_path / "anki")
    try:
        import_apkg(col, out)
        notes, cards = note_count(col), card_count(col)
        assert notes == cards > 0
        assert_clean_media(col)  # check 1

        rendered = rendered_cards(col)
        assert len(rendered) == cards
        assert_no_name_leak(col, rendered)  # check 5

        species = CatalogClient(LIVE_CATALOG, cache_dir=tmp_path / "cache").species()
        assert_credits_on_answers(rendered, species)  # check 6

        media_files = len(list((tmp_path / "anki" / "collection.media").iterdir()))
    finally:
        col.close()
    size_mb = out.stat().st_size / 1_000_000
    print(f"\nlive us-ma: {notes} notes, {media_files} media files, {size_mb:.1f} MB .apkg, built in {built:.0f} s")
