"""Tests for avianki.catalog.pins: the reviewer-facing pins.toml, no I/O beyond tmp files."""

from __future__ import annotations

from pathlib import Path

import pytest

from avianki.catalog.pins import AssetRef, PinsError, load_pins, parse_pins, parse_ref
from avianki.sources.contract import AssetKind
from avianki.taxonomy import DATA_DIR
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

TABLE = SpeciesTable(
    [
        SpeciesRow("turdus-migratorius", "Turdus migratorius", "American Robin"),
        SpeciesRow("cyanocitta-cristata", "Cyanocitta cristata", "Blue Jay"),
        SpeciesRow("old-robin", "Turdus oldus", "Old Robin", alias_of="turdus-migratorius"),
    ]
)


def parse(text: str):
    return parse_pins(text, TABLE)


def test_a_valid_file_parses_every_key():
    pins = parse(
        """
[turdus-migratorius]
photo = "commons:M12345"
audio = "inaturalist:S987:654"
exclude = ["commons:M777", "inaturalist:P1:2"]
note = "The top recording has a second bird."

[cyanocitta-cristata]
exclude = ["commons:M5"]
note = "Creator asked for removal."
"""
    )
    robin = pins.get("turdus-migratorius")
    assert robin is not None
    assert robin.photo == AssetRef("commons", "M12345")
    assert robin.audio == AssetRef("inaturalist", "S987:654")  # split on the FIRST colon only
    assert robin.exclude == (AssetRef("commons", "M777"), AssetRef("inaturalist", "P1:2"))
    assert robin.note == "The top recording has a second bird."
    assert robin.forced(AssetKind.AUDIO) == robin.audio
    assert robin.forced(AssetKind.PHOTO) == robin.photo
    assert robin.excludes("commons", "M777") and not robin.excludes("inaturalist", "M777")
    jay = pins.get("cyanocitta-cristata")
    assert jay is not None and jay.photo is None and jay.audio is None
    assert len(pins) == 2 and pins


def test_an_empty_file_is_no_pins():
    pins = parse("")
    assert len(pins) == 0 and not pins and pins.get("turdus-migratorius") is None
    assert pins.for_validation() == {}


def test_the_shipped_pins_file_loads_and_is_empty():
    path = DATA_DIR / "pins.toml"
    assert path.is_file()
    assert len(load_pins(path, TABLE)) == 0


def test_a_missing_note_is_an_error_naming_the_species_and_line():
    with pytest.raises(PinsError, match=r"pins\.toml:2: \[turdus-migratorius\].*note"):
        parse('\n[turdus-migratorius]\naudio = "commons:M1"\n')


def test_a_table_with_no_keys_needs_a_note_too():
    with pytest.raises(PinsError, match="note"):
        parse("[turdus-migratorius]\n")


def test_a_blank_note_is_a_missing_note():
    with pytest.raises(PinsError, match="note"):
        parse('[turdus-migratorius]\nnote = "  "\n')


def test_an_unknown_species_is_an_error():
    with pytest.raises(PinsError, match=r"\[turdus-typo\].*unknown species"):
        parse('[turdus-typo]\nexclude = ["commons:M1"]\nnote = "x"\n')


def test_an_unknown_source_prefix_is_an_error():
    with pytest.raises(PinsError, match="unknown source 'flickr'"):
        parse('[turdus-migratorius]\nphoto = "flickr:123"\nnote = "x"\n')


def test_an_unknown_key_is_an_error():
    with pytest.raises(PinsError, match="unknown key.*photos"):
        parse('[turdus-migratorius]\nphotos = "commons:M1"\nnote = "x"\n')


@pytest.mark.parametrize("value", ['"M12345"', '"commons:"', '":M1"', "5"])
def test_a_malformed_reference_is_an_error(value):
    with pytest.raises(PinsError, match="`audio`"):
        parse('[turdus-migratorius]\naudio = ' + value + '\nnote = "x"\n')


def test_exclude_must_be_a_list_of_references():
    with pytest.raises(PinsError, match="exclude"):
        parse('[turdus-migratorius]\nexclude = "commons:M1"\nnote = "x"\n')
    with pytest.raises(PinsError, match="exclude"):
        parse('[turdus-migratorius]\nexclude = ["nonsense"]\nnote = "x"\n')


def test_pinning_and_excluding_the_same_asset_is_a_contradiction():
    with pytest.raises(PinsError, match="also lists"):
        parse('[turdus-migratorius]\nphoto = "commons:M1"\nexclude = ["commons:M1"]\nnote = "x"\n')


def test_an_alias_id_is_followed_to_its_canonical_species():
    pins = parse('[old-robin]\nexclude = ["commons:M1"]\nnote = "x"\n')
    assert pins.get("turdus-migratorius") is not None
    assert pins.get("old-robin") is None


def test_an_alias_and_its_canonical_id_both_having_tables_is_an_error():
    text = '[old-robin]\nnote = "a"\n\n[turdus-migratorius]\nnote = "b"\n'
    with pytest.raises(PinsError, match="alias"):
        parse(text)


def test_every_problem_is_reported_together():
    with pytest.raises(PinsError) as exc:
        parse('[nope]\nnote = "x"\n\n[turdus-migratorius]\naudio = "flickr:1"\n')
    message = str(exc.value)
    assert "[nope]" in message and "flickr" in message and "note" in message


def test_invalid_toml_is_a_pins_error():
    with pytest.raises(PinsError, match="not valid TOML"):
        parse("[turdus-migratorius\n")


def test_for_validation_gives_bare_tokens_in_the_shape_the_gate_reads():
    pins = parse('[turdus-migratorius]\naudio = "inaturalist:S1:2"\nexclude = ["commons:M9"]\nnote = "x"\n')
    assert pins.for_validation() == {
        "turdus-migratorius": {"photo": None, "audio": "S1:2", "exclude": ["M9"]}
    }


def test_load_pins_reads_a_file_and_names_it_in_errors(tmp_path: Path):
    path = tmp_path / "pins.toml"
    path.write_text('[turdus-migratorius]\nphoto = "commons:M1"\nnote = "x"\n', encoding="utf-8")
    assert load_pins(path, TABLE).get("turdus-migratorius") is not None
    path.write_text("[nope]\nnote = 'x'\n", encoding="utf-8")
    with pytest.raises(PinsError, match=r"pins\.toml:1"):
        load_pins(path, TABLE)


def test_a_missing_file_is_an_error_not_no_pins(tmp_path: Path):
    with pytest.raises(PinsError, match="not found"):
        load_pins(tmp_path / "absent.toml", TABLE)


def test_parse_ref_accepts_a_custom_source_set():
    assert parse_ref("xeno-canto:XC1", {"xeno-canto"}) == AssetRef("xeno-canto", "XC1")
    assert str(AssetRef("inaturalist", "S1:2")) == "inaturalist:S1:2"
