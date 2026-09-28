import re
from dataclasses import replace
from pathlib import Path

import pytest

from avianki.taxonomy import DATA_DIR
from avianki.taxonomy.species import (
    HEADER,
    SpeciesRow,
    SpeciesTable,
    load_species,
    mint_id,
    save_species,
)

HEADER_LINE = "id,sci_name,common_name,gbif_key,inat_taxon_id,wikipedia_title,ebird_code,birdnet_label,alias_of"

CARDINAL = SpeciesRow(
    id="cardinalis-cardinalis",
    sci_name="Cardinalis cardinalis",
    common_name="Northern Cardinal",
    gbif_key=9809229,
    inat_taxon_id=9083,
    wikipedia_title="Northern cardinal",
    ebird_code="norcar",
    birdnet_label="Cardinalis cardinalis_Northern Cardinal",
)
JAY = SpeciesRow(id="cyanocitta-cristata", sci_name="Cyanocitta cristata", common_name="Blue Jay", gbif_key=2482593)


def lumped_pair() -> tuple[SpeciesRow, SpeciesRow]:
    """A retired id pointing at its successor, as a lump leaves it (ADR 0008)."""
    successor = SpeciesRow(id="setophaga-coronata", sci_name="Setophaga coronata", common_name="Myrtle Warbler", gbif_key=1)
    retired = SpeciesRow(
        id="setophaga-auduboni",
        sci_name="Setophaga auduboni",
        common_name="Audubon's Warbler",
        gbif_key=2,
        alias_of="setophaga-coronata",
    )
    return successor, retired


# --- the real data/species.csv ---------------------------------------------------


def test_real_file_has_the_fixed_header():
    lines = (DATA_DIR / "species.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == HEADER_LINE
    assert ",".join(HEADER) == HEADER_LINE


def test_real_file_loads():
    table = load_species()
    for row in table.all_rows():
        assert re.fullmatch(r"[a-z]+(-[a-z]+)*", row.id), row.id


# --- mint_id ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sci_name", "expected"),
    [
        ("Cardinalis cardinalis", "cardinalis-cardinalis"),
        ("  Cardinalis   cardinalis\t", "cardinalis-cardinalis"),
        ("Poecile atricapillus", "poecile-atricapillus"),
        ("Aegithalos caudatus europaeus", "aegithalos-caudatus-europaeus"),
        ("Pyrrhula mürrhula", "pyrrhula-murrhula"),
        ("Tangara ç", "tangara-c"),
        ("Polygonia c-album", "polygonia-c-album"),
    ],
)
def test_mint_id(sci_name, expected):
    assert mint_id(sci_name) == expected


@pytest.mark.parametrize("sci_name", ["Anas platyrhynchos × Anas rubripes", "×Anas hybrida"])
def test_mint_id_rejects_hybrids(sci_name):
    with pytest.raises(ValueError, match="hybrid"):
        mint_id(sci_name)


@pytest.mark.parametrize("sci_name", ["", "   ", "Anas sp.", "Anas 2", "Anas/Aythya"])
def test_mint_id_rejects_non_binomials(sci_name):
    with pytest.raises(ValueError):
        mint_id(sci_name)


# --- SpeciesTable ----------------------------------------------------------------


def test_add_and_get():
    table = SpeciesTable([CARDINAL, JAY])
    assert table.get("cardinalis-cardinalis") is CARDINAL
    assert len(table) == 2
    assert "cyanocitta-cristata" in table


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError, match="no-such-bird"):
        SpeciesTable([CARDINAL]).get("no-such-bird")


def test_get_follows_alias_to_live_row():
    successor, retired = lumped_pair()
    table = SpeciesTable([retired, successor])  # alias before its successor is fine
    assert table.get("setophaga-auduboni") is successor
    assert table.get("setophaga-auduboni", follow_aliases=False) is retired


def test_get_follows_alias_chains():
    successor, retired = lumped_pair()
    older = SpeciesRow(id="dendroica-auduboni", sci_name="Dendroica auduboni", common_name="", alias_of="setophaga-auduboni")
    assert SpeciesTable([older, retired, successor]).get("dendroica-auduboni") is successor


def test_iteration_is_live_rows_in_id_order():
    successor, retired = lumped_pair()
    table = SpeciesTable([JAY, retired, CARDINAL, successor])
    assert [r.id for r in table] == ["cardinalis-cardinalis", "cyanocitta-cristata", "setophaga-coronata"]
    assert len(table) == 3
    assert [r.id for r in table.all_rows()] == [
        "cardinalis-cardinalis",
        "cyanocitta-cristata",
        "setophaga-auduboni",
        "setophaga-coronata",
    ]


def test_dangling_alias_is_refused():
    _, retired = lumped_pair()
    with pytest.raises(ValueError, match="setophaga-coronata"):
        SpeciesTable([retired])


def test_alias_cycle_is_refused():
    a = SpeciesRow(id="a-a", sci_name="A a", common_name="", alias_of="b-b")
    b = SpeciesRow(id="b-b", sci_name="B b", common_name="", alias_of="a-a")
    with pytest.raises(ValueError, match="cycle"):
        SpeciesTable([a, b])


def test_add_refuses_duplicate_id():
    table = SpeciesTable([CARDINAL])
    with pytest.raises(ValueError, match="cardinalis-cardinalis"):
        table.add(SpeciesRow(id="cardinalis-cardinalis", sci_name="Cardinalis cardinalis", common_name="x"))


def test_add_refuses_second_live_row_with_same_gbif_key():
    table = SpeciesTable([CARDINAL])
    clash = SpeciesRow(id="cardinalis-sinuatus", sci_name="Cardinalis sinuatus", common_name="Pyrrhuloxia", gbif_key=9809229)
    with pytest.raises(ValueError, match="9809229"):
        table.add(clash)


def test_alias_may_share_gbif_key_with_live_row():
    successor, retired = lumped_pair()
    table = SpeciesTable([successor, replace(retired, gbif_key=successor.gbif_key)])
    assert table.by_gbif_key(1) is successor


def test_add_refuses_second_live_row_with_same_sci_name():
    table = SpeciesTable([CARDINAL])
    with pytest.raises(ValueError, match="already belongs to live species .cardinalis-cardinalis."):
        table.add(SpeciesRow(id="cardinalis-cardinalis-2", sci_name="cardinalis CARDINALIS", common_name=""))


def test_by_gbif_key():
    table = SpeciesTable([CARDINAL, JAY])
    assert table.by_gbif_key(2482593) is JAY
    with pytest.raises(KeyError, match="42"):
        table.by_gbif_key(42)


def test_by_gbif_key_of_retired_row_follows_alias():
    successor, retired = lumped_pair()
    assert SpeciesTable([successor, retired]).by_gbif_key(2) is successor


def test_by_sci_name_is_case_insensitive():
    table = SpeciesTable([CARDINAL, JAY])
    assert table.by_sci_name("cardinalis CARDINALIS") is CARDINAL
    assert table.by_sci_name(" Cyanocitta   cristata ") is JAY
    with pytest.raises(KeyError, match="Corvus corax"):
        table.by_sci_name("Corvus corax")


def test_by_sci_name_of_retired_row_follows_alias():
    successor, retired = lumped_pair()
    assert SpeciesTable([successor, retired]).by_sci_name("Setophaga auduboni") is successor


# --- mint ------------------------------------------------------------------------


def test_mint_creates_a_new_row():
    table = SpeciesTable()
    minted = table.mint("Cardinalis cardinalis", "Northern Cardinal", 9809229)
    assert minted.created
    assert minted.row == SpeciesRow(
        id="cardinalis-cardinalis", sci_name="Cardinalis cardinalis", common_name="Northern Cardinal", gbif_key=9809229
    )
    assert table.get("cardinalis-cardinalis") == minted.row


def test_mint_is_idempotent():
    table = SpeciesTable()
    first = table.mint("Cardinalis cardinalis", "Northern Cardinal", 9809229)
    again = table.mint("Cardinalis cardinalis", "Northern Cardinal", 9809229)
    assert not again.created
    assert again.row is first.row
    assert len(table) == 1


def test_mint_matches_existing_by_gbif_key_despite_rename():
    table = SpeciesTable([CARDINAL])
    minted = table.mint("Cardinalis renamed", "Renamed Cardinal", 9809229)
    assert not minted.created
    assert minted.row is CARDINAL  # the id never changes after minting


def test_mint_matches_existing_by_sci_name():
    table = SpeciesTable([CARDINAL])
    minted = table.mint("Cardinalis cardinalis", "Northern Cardinal", 123)
    assert not minted.created
    assert minted.row is CARDINAL


def test_mint_of_retired_name_returns_successor():
    successor, retired = lumped_pair()
    table = SpeciesTable([successor, retired])
    minted = table.mint("Setophaga auduboni", "Audubon's Warbler", 2)
    assert not minted.created
    assert minted.row is successor


# --- load / save -----------------------------------------------------------------


def test_save_then_load_round_trips(tmp_path: Path):
    successor, retired = lumped_pair()
    table = SpeciesTable([JAY, retired, CARDINAL, successor])
    p = tmp_path / "species.csv"
    save_species(table, p)
    loaded = load_species(p)
    assert list(loaded.all_rows()) == list(table.all_rows())
    assert loaded.get("setophaga-auduboni") is loaded.get("setophaga-coronata")


def test_save_is_sorted_stable_and_uses_lf(tmp_path: Path):
    p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
    save_species(SpeciesTable([JAY, CARDINAL]), p1)
    save_species(SpeciesTable([CARDINAL, JAY]), p2)
    data = p1.read_bytes()
    assert data == p2.read_bytes()
    assert b"\r" not in data
    assert data.decode("utf-8").splitlines() == [
        HEADER_LINE,
        "cardinalis-cardinalis,Cardinalis cardinalis,Northern Cardinal,9809229,9083,Northern cardinal,norcar,"
        "Cardinalis cardinalis_Northern Cardinal,",
        "cyanocitta-cristata,Cyanocitta cristata,Blue Jay,2482593,,,,,",
    ]


def test_save_quotes_and_keeps_utf8(tmp_path: Path):
    row = SpeciesRow(id="aa-bb", sci_name="Aa bb", common_name="Bird, Pîed", wikipedia_title="Pîed bird")
    p = tmp_path / "species.csv"
    save_species(SpeciesTable([row]), p)
    assert '"Bird, Pîed"' in p.read_text(encoding="utf-8")
    assert load_species(p).get("aa-bb") == row


def test_empty_table_saves_header_only(tmp_path: Path):
    p = tmp_path / "species.csv"
    save_species(SpeciesTable(), p)
    assert p.read_text(encoding="utf-8") == HEADER_LINE + "\n"
    assert len(load_species(p)) == 0


def test_wrong_header_raises(tmp_path: Path):
    p = tmp_path / "species.csv"
    p.write_text("id,sci_name,common_name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        load_species(p)


def test_non_integer_key_raises(tmp_path: Path):
    p = tmp_path / "species.csv"
    p.write_text(HEADER_LINE + "\naa-bb,Aa bb,,notanumber,,,,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gbif_key"):
        load_species(p)
