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


# --- themes and the name-on-photo layout change only styling and template HTML (ADR 0028) -----

from avianki.deck import themes  # noqa: E402

LOOKS = [(name, overlay) for name in themes.THEME_NAMES for overlay in (False, True)]
CUSTOM = themes.tokens_from_mapping({"font": "mono", "rule": "side", "corners": "round"})


def _identity(models: dict) -> dict:
    return {
        card_type: {
            "id": m.model_id,
            "name": m.name,
            "fields": [f["name"] for f in m.fields],
            "templates": [t["name"] for t in m.templates],
            "sort_field": m.sort_field_index,
            "type": m.model_type,
        }
        for card_type, m in models.items()
    }


@pytest.mark.parametrize(("theme", "overlay"), LOOKS)
def test_every_theme_and_layout_keeps_the_note_type_identity(theme: str, overlay: bool) -> None:
    models = notetypes.models_for(theme, overlay)
    assert _identity(models) == _identity(notetypes.MODELS)
    assert {ct: m.model_id for ct, m in models.items()} == {
        "photo": 717156105,
        "audio": 3710911882,
        "photo_audio": 327952205,
    }
    for card_type, model in models.items():
        assert [t["name"] for t in model.templates] == [t["name"] for t in notetypes.MODELS[card_type].templates]
        assert [t["qfmt"] for t in model.templates] == [t["qfmt"] for t in notetypes.MODELS[card_type].templates]


@pytest.mark.parametrize("overlay", [False, True])
def test_a_custom_theme_keeps_the_note_type_identity(overlay: bool) -> None:
    assert _identity(notetypes.models_for(CUSTOM, overlay)) == _identity(notetypes.MODELS)


def test_the_default_models_are_card_css_and_the_original_back_exactly() -> None:
    assert notetypes.CSS == themes.BASE_CSS
    assert themes.compose_css() == themes.BASE_CSS
    for model in notetypes.models_for("default", False).values():
        assert model.css == themes.BASE_CSS
        assert model.templates[0]["afmt"] == notetypes.back_for(False)


def test_the_theme_is_set_when_the_models_are_built_not_when_a_note_is() -> None:
    nord = notetypes.models_for("nord", True)
    assert nord["photo"].css == themes.compose_css("nord", True)
    assert nord["photo"].css != notetypes.MODELS["photo"].css
    assert notetypes.MODELS["photo"].css == themes.BASE_CSS  # building another look never touches the default
