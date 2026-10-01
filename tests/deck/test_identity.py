"""Pins ADR 0009's frozen identity strings (deck name/id, note GUIDs, card types, model ids, fields).

Every expected value below is a literal on purpose: if anyone edits a seed, a card-type
string or the field list, an existing user's notes stop matching on import and this test
must fail. The literals were computed once from the ADR's own formulas:

* deck id      = int(md5(<deck name>).hexdigest()[:8], 16)
* model id     = int(md5(<seed>).hexdigest()[:8], 16)
* note GUID    = genanki.guid_for("avianki", species_id, card_type)

The browser (M6) ports the same formulas and checks against these numbers.
"""

from __future__ import annotations

import pytest

from avianki.deck import build, notetypes


def test_deck_name_is_avianki() -> None:
    assert build.DECK_NAME == "AviAnki"
    assert build.full_deck_name("AviAnki", None) == "AviAnki"


def test_subdeck_name_is_avianki_double_colon_region() -> None:
    assert build.full_deck_name("AviAnki", "Massachusetts") == "AviAnki::Massachusetts"


def test_deck_id_literals() -> None:
    assert build.deck_id("AviAnki") == 2854063212
    assert build.deck_id("AviAnki::Massachusetts") == 3074061584


@pytest.mark.parametrize(
    ("species_id", "card_type", "guid"),
    [
        ("turdus-migratorius", "photo", "y^.Qw>j5t"),
        ("turdus-migratorius", "audio", "sN^~,`kZon"),
        ("cardinalis-cardinalis", "photo_audio", "NQU<l[=_(X"),
    ],
)
def test_note_guid_literals(species_id: str, card_type: str, guid: str) -> None:
    assert build.note_guid(species_id, card_type) == guid


def test_card_types_are_exactly_these() -> None:
    assert tuple(notetypes.CARD_TYPES) == ("photo", "audio", "photo_audio")


def test_model_seeds_are_frozen() -> None:
    assert dict(notetypes.MODEL_SEEDS) == {
        "photo": "AviAnki_Photo_v2",
        "audio": "AviAnki_Audio_v2",
        "photo_audio": "AviAnki_PhotoAudio_v2",
    }


def test_model_ids_literals() -> None:
    assert {ct: m.model_id for ct, m in notetypes.MODELS.items()} == {
        "photo": 717156105,
        "audio": 3710911882,
        "photo_audio": 327952205,
    }


def test_model_names() -> None:
    assert {ct: m.name for ct, m in notetypes.MODELS.items()} == {
        "photo": "AviAnki · Photo",
        "audio": "AviAnki · Audio",
        "photo_audio": "AviAnki · Photo + Audio",
    }


def test_field_list_is_frozen_and_in_order() -> None:
    # IocName was appended as the ninth field, the one sanctioned change to this list
    # before the 1.0 announcement (ADR 0027, which amends ADR 0009). The first eight keep
    # their positions.
    expected = ["SpeciesId", "Name", "SciName", "Photo", "Photo2", "Audio", "Audio2", "Credits", "IocName"]
    assert list(notetypes.FIELDS) == expected
    for model in notetypes.MODELS.values():
        assert [f["name"] for f in model.fields] == expected
