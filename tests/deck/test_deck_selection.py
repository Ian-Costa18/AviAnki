"""`select_species` against the shared selection fixture, plus `plan_notes`.

Fixture schema (``tests/fixtures/selection/cases.json``, language-neutral so the M6
browser tests reuse it): a JSON list of cases, each

    {
      "name":             str,   # what the case demonstrates
      "region":           {"slug": str, "species": [[species_id, [12 ints, January first]], ...]},
      "tier":             "standard" | "everything",
      "month":            int 1-12 | null,
      "expected_species": [species_id, ...]   # in region rank order
    }

``region`` has the published region-file shape (spec section 5). The rules under test
(spec section 6): the month filter first (keep a species when 10 * monthly[m-1] >= max(monthly);
an all-zero vector is dropped when a month is set), then the first 100 for ``standard`` or
all for ``everything``. Values are compared as integers so exactly 10% is kept.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from deck_fakes import species_file

from avianki.catalog.format import RegionFile
from avianki.deck.build import PlannedNote, plan_notes, select_species

CASES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "selection" / "cases.json").read_text(
        encoding="utf-8"
    )
)


def test_fixture_covers_the_required_situations() -> None:
    names = " | ".join(c["name"] for c in CASES)
    for needle in ("10 percent boundary", "all-zero", "first 100 of 150", "everything", "month null"):
        assert needle in names
    assert any(c["month"] is None for c in CASES)
    assert any(len(c["region"]["species"]) > 100 for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_select_species_matches_fixture(case: dict) -> None:
    region = RegionFile.from_dict(case["region"])
    got = select_species(region, tier=case["tier"], month=case["month"])
    assert got == case["expected_species"]


def test_select_species_rejects_bad_arguments() -> None:
    region = RegionFile("x", [("a", (1,) * 12)])
    with pytest.raises(ValueError, match="tier must be one of"):
        select_species(region, tier="huge", month=None)
    with pytest.raises(ValueError, match="month must be 1-12"):
        select_species(region, tier="standard", month=13)
    with pytest.raises(ValueError, match="month must be 1-12"):
        select_species(region, tier="standard", month=0)


# --- plan_notes ------------------------------------------------------------------------


def _kinds(notes: list[PlannedNote]) -> list[tuple[str, str]]:
    return [(n.species_id, n.card_type) for n in notes]


def test_species_with_only_a_photo_gets_only_a_photo_note() -> None:
    notes = plan_notes(["cyanocitta-cristata"], species_file(), {"photo", "audio", "photo_audio"})
    assert _kinds(notes) == [("cyanocitta-cristata", "photo")]
    assert notes[0].audio is None


def test_species_with_only_audio_gets_only_an_audio_note() -> None:
    notes = plan_notes(["troglodytes-aedon"], species_file(), {"photo", "audio", "photo_audio"})
    assert _kinds(notes) == [("troglodytes-aedon", "audio")]
    assert notes[0].photo is None


def test_every_note_carries_all_the_species_media_for_the_back() -> None:
    notes = plan_notes(["turdus-migratorius"], species_file(), {"photo", "audio"})
    assert _kinds(notes) == [("turdus-migratorius", "photo"), ("turdus-migratorius", "audio")]
    assert all(n.photo is not None and n.audio is not None for n in notes)


def test_photo_audio_needs_both() -> None:
    sp = species_file()
    both = plan_notes(["turdus-migratorius"], sp, {"photo_audio"})
    assert _kinds(both) == [("turdus-migratorius", "photo_audio")]
    assert both[0].photo is not None and both[0].audio is not None
    assert plan_notes(["cyanocitta-cristata", "troglodytes-aedon"], sp, {"photo_audio"}) == []


def test_species_without_any_media_makes_no_note() -> None:
    assert plan_notes(["empty-bird"], species_file(), {"photo", "audio", "photo_audio"}) == []


def test_only_the_selected_card_types_are_made() -> None:
    notes = plan_notes(["turdus-migratorius"], species_file(), {"audio"})
    assert _kinds(notes) == [("turdus-migratorius", "audio")]


def test_first_photo_and_first_audio_only() -> None:
    (note,) = plan_notes(["cyanocitta-cristata"], species_file(), {"photo"})
    assert note.photo is not None and note.photo.file == "media/1111111111111111.webp"


def test_unknown_species_is_skipped_with_a_warning() -> None:
    # Attach a handler directly: other tests may leave "bird_deck" with propagate=False.
    records: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    log = logging.getLogger("bird_deck")
    handler = Grab(level=logging.WARNING)
    log.addHandler(handler)
    try:
        notes = plan_notes(["no-such-bird", "turdus-migratorius"], species_file(), {"photo"})
    finally:
        log.removeHandler(handler)
    assert _kinds(notes) == [("turdus-migratorius", "photo")]
    assert any("no-such-bird" in r.getMessage() for r in records)


def test_order_is_rank_then_photo_audio_photo_audio_whatever_the_cards_set_order() -> None:
    ids = ["cardinalis-cardinalis", "turdus-migratorius"]
    for cards in ({"photo_audio", "audio", "photo"}, {"photo", "photo_audio", "audio"}):
        notes = plan_notes(ids, species_file(), cards)
        assert _kinds(notes) == [
            ("cardinalis-cardinalis", "photo"),
            ("cardinalis-cardinalis", "audio"),
            ("cardinalis-cardinalis", "photo_audio"),
            ("turdus-migratorius", "photo"),
            ("turdus-migratorius", "audio"),
            ("turdus-migratorius", "photo_audio"),
        ]


def test_repeated_species_ids_are_planned_once() -> None:
    notes = plan_notes(["cyanocitta-cristata"] * 3, species_file(), {"photo"})
    assert len(notes) == 1


def test_unknown_card_type_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown card types"):
        plan_notes(["turdus-migratorius"], species_file(), {"description"})
