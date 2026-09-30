"""Acceptance tests (ADR 0019): built decks through Anki's own backend.

Each test builds .apkg files with ``avianki.cli.main`` from the fixture catalog and imports them
into a fresh collection with the ``anki`` package (the Rust backend the desktop app uses). They
check what a learner would experience, not what the writer intended: notes and cards arrive, the
media checker is satisfied, progress survives a re-import, fronts do not give the name away, and
every answer credits its assets.

Skipped when the ``anki`` package is not installed (it is a dev dependency).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("anki.collection")

from acceptance_support import (  # noqa: E402
    answer_some_cards,
    assert_clean_media,
    assert_credits_on_answers,
    assert_no_name_leak,
    card_count,
    guids,
    import_apkg,
    note_count,
    note_ids,
    open_collection,
    rendered_cards,
    revlog_count,
)
from cli_fakes import FIXTURE_CATALOG, run_cli  # noqa: E402

from avianki.catalog.client import CatalogClient  # noqa: E402
from avianki.deck import build as deck_build  # noqa: E402

ALL_CARDS = "photo,audio,photo-audio"


@pytest.fixture
def make_deck(tmp_path, monkeypatch, capsys):
    """Build a deck through the CLI and return its path."""
    counter = iter(range(1000))

    def make(*argv: str, catalog: Path = FIXTURE_CATALOG) -> Path:
        out = tmp_path / f"deck{next(counter)}.apkg"
        result = run_cli([*argv, "-o", str(out), "-q"], tmp_path, monkeypatch, capsys, catalog=catalog)
        assert result.code == 0, result.err
        return out

    return make


@pytest.fixture
def col(tmp_path):
    collection = open_collection(tmp_path / "anki")
    yield collection
    collection.close()


@pytest.fixture
def species(tmp_path):
    return CatalogClient(str(FIXTURE_CATALOG), cache_dir=tmp_path / "species-cache").species()


def newer_catalog(tmp_path: Path) -> Path:
    """A copy of the fixture catalog published later (a new catalog_version)."""
    copy = tmp_path / "catalog-v2"
    shutil.copytree(FIXTURE_CATALOG, copy, ignore=shutil.ignore_patterns("make_fixture.py", "__pycache__"))
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    manifest["catalog_version"] = "2026-02-01"
    (copy / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return copy


# 1 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "notes"),
    [
        (["us-ma"], 22),  # 12 species; Snowy Owl has no audio, Common Loon no photo
        (["us-ma", "--cards", "photo"], 11),
        (["us-ma", "--cards", "audio"], 11),
        (["us-ma", "--cards", ALL_CARDS], 32),  # photo + audio + 10 species with both
        (["quebec"], 12),  # 7 species: 6 with a photo, 6 with a recording
        (["us-az", "--cards", ALL_CARDS], None),
    ],
)
def test_the_deck_imports_with_the_expected_notes_and_cards_and_clean_media(argv, notes, make_deck, col):
    log = import_apkg(col, make_deck(*argv))
    assert note_count(col) == card_count(col) > 0  # one card per note
    if notes is not None:
        assert note_count(col) == notes
    assert len(log.log.new) == note_count(col)
    assert_clean_media(col)


# 2 -------------------------------------------------------------------------------------


def test_a_rebuilt_deck_reimports_onto_the_same_notes_and_keeps_progress(make_deck, col, tmp_path):
    import_apkg(col, make_deck("us-ma"))
    assert answer_some_cards(col, 6) == 6
    before = (note_count(col), note_ids(col), revlog_count(col), guids(col))
    reviewed = col.db.scalar("select count() from cards where type != 0")
    assert before[2] == 6 and reviewed == 6

    later = make_deck("us-ma", catalog=newer_catalog(tmp_path))  # a new catalog version, a new build
    log = import_apkg(col, later)

    assert len(log.log.new) == 0
    assert (note_count(col), note_ids(col), revlog_count(col), guids(col)) == before
    assert col.db.scalar("select count() from cards where type != 0") == reviewed
    assert_clean_media(col)


def test_the_same_build_twice_is_a_no_op(make_deck, col):
    deck = make_deck("us-az")
    import_apkg(col, deck)
    log = import_apkg(col, deck)
    assert len(log.log.new) == 0
    assert note_count(col) == 12  # us-az: 6 species, photo and audio each


# 3 -------------------------------------------------------------------------------------


def test_going_from_standard_to_everything_adds_only_the_extra_notes(make_deck, col, monkeypatch):
    monkeypatch.setattr(deck_build, "STANDARD_LIMIT", 5)
    import_apkg(col, make_deck("us-ma", "--cards", "photo"))
    assert note_count(col) == 5
    standard_ids = note_ids(col)
    answer_some_cards(col, 3)
    revlog = revlog_count(col)

    log = import_apkg(col, make_deck("us-ma", "--cards", "photo", "--tier", "everything"))

    assert len(log.log.new) == 6  # 11 species with a photo, 5 already there
    assert note_count(col) == 11 and standard_ids <= note_ids(col)
    assert len(guids(col)) == note_count(col)  # no duplicates
    assert revlog_count(col) == revlog
    assert_clean_media(col)


# 4 -------------------------------------------------------------------------------------


def test_photo_and_audio_parts_imported_separately_equal_one_combined_build(make_deck, col, tmp_path):
    photos = make_deck("us-ma", "--cards", "photo")
    audio = make_deck("us-ma", "--cards", "audio")
    import_apkg(col, photos)
    import_apkg(col, audio)
    assert_clean_media(col)

    other = open_collection(tmp_path / "anki-combined")
    try:
        import_apkg(other, make_deck("us-ma", "--cards", "photo,audio"))
        assert note_count(col) == note_count(other) == 22
        assert guids(col) == guids(other)
    finally:
        other.close()


# 5 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("region", ["us-ma", "ca-qc", "us-az"])
def test_no_front_gives_the_name_away(region, make_deck, col):
    import_apkg(col, make_deck(region, "--cards", ALL_CARDS))
    cards = rendered_cards(col)
    assert len(cards) == note_count(col) > 0
    assert_no_name_leak(col, cards)


def test_the_name_leak_check_would_catch_a_leak(make_deck, col):
    import_apkg(col, make_deck("us-az", "--cards", "photo"))
    cards = rendered_cards(col)
    cards[0].question_html += f"<div>{cards[0].name}</div>"
    with pytest.raises(AssertionError, match="the front shows"):
        assert_no_name_leak(col, cards)


# 6 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("region", ["us-ma", "ca-qc", "us-az"])
def test_every_answer_credits_every_asset_its_note_carries(region, make_deck, col, species):
    import_apkg(col, make_deck(region, "--cards", ALL_CARDS))
    cards = rendered_cards(col)
    assert cards
    assert_credits_on_answers(cards, species)
    # the answer also names the bird
    for card in cards:
        assert card.name in card.answer_html or card.name.replace("&", "&amp;") in card.answer_html


def test_the_credit_check_would_catch_a_missing_credit(make_deck, col, species):
    import_apkg(col, make_deck("us-az", "--cards", "photo"))
    cards = rendered_cards(col)
    cards[0].answer_html = "<div>no credit here</div>"
    with pytest.raises(AssertionError, match="credit missing"):
        assert_credits_on_answers(cards, species)
