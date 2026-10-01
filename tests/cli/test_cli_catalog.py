"""`avianki REGION`: the catalog path of the CLI, run against the fixture catalog (offline)."""

from __future__ import annotations

import pytest
from cli_fakes import FIXTURE_CATALOG, deck_info, note_fields, read_apkg, run_cli

from avianki import cli, taxonomy
from avianki.deck import build as deck_build


def test_the_default_run_writes_a_named_deck_and_says_what_next(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-ma"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    out = tmp_path / "AviAnki-us-ma.apkg"
    assert out.is_file()
    # 12 species; Snowy Owl has no audio, Common Loon no photo: 11 photo + 11 audio notes.
    assert "22 notes (11 photo, 11 audio) for 12 species" in r.out
    assert "Next: open AviAnki-us-ma.apkg in Anki" in r.out
    assert len(note_fields(out)) == 22


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Massachusetts", "AviAnki-us-ma.apkg"),
        ("massachusetts", "AviAnki-us-ma.apkg"),
        ("quebec", "AviAnki-ca-qc.apkg"),
        ("Québec", "AviAnki-ca-qc.apkg"),
        ("US-AZ", "AviAnki-us-az.apkg"),
    ],
)
def test_a_region_can_be_given_by_slug_or_display_name(query, expected, tmp_path, monkeypatch, capsys):
    r = run_cli([query], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert (tmp_path / expected).is_file()


def test_output_can_be_chosen(tmp_path, monkeypatch, capsys):
    target = tmp_path / "sub" / "mine.apkg"
    target.parent.mkdir()
    r = run_cli(["us-az", "-o", str(target)], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert target.is_file() and not (tmp_path / "AviAnki-us-az.apkg").exists()


def test_photo_only_and_audio_only_differ(tmp_path, monkeypatch, capsys):
    a = run_cli(["us-ma", "--cards", "photo", "-o", "p.apkg"], tmp_path, monkeypatch, capsys)
    b = run_cli(["us-ma", "--cards", "audio", "-o", "a.apkg"], tmp_path, monkeypatch, capsys)
    assert a.code == b.code == 0
    assert "11 photo)" in a.out and "11 audio)" in b.out


def test_photo_audio_is_spelled_with_a_hyphen(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az", "--cards", "photo-audio"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert "photo-audio" in r.out
    assert len(note_fields(tmp_path / "AviAnki-us-az.apkg")) > 0


def test_an_unknown_card_type_is_a_usage_error(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "--cards", "photo,video"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "unknown card type" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["0", "13", "may"])
def test_a_bad_month_is_a_usage_error(bad, tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "--month", bad], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2


def test_month_selects_what_select_species_selects(tmp_path, monkeypatch, capsys):
    from avianki.catalog.client import CatalogClient

    client = CatalogClient(str(FIXTURE_CATALOG), cache_dir=tmp_path / "cache")
    region = client.region(client.find_region("us-az"))
    cards = ("photo",)
    every = deck_build.select_species(region, client.species(), cards, tier="everything", month=None)
    june = deck_build.select_species(region, client.species(), cards, tier="everything", month=6)
    assert 0 < len(june) <= len(every)

    r = run_cli(["us-az", "--month", "6", "--cards", "photo", "-o", "june.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    names = {client.species().entries[s].name for s in june}
    text = " ".join(" ".join(f) for f in note_fields(tmp_path / "june.apkg"))
    assert all(n in text for n in names)


def test_the_standard_tier_caps_the_species_and_everything_does_not(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deck_build, "STANDARD_LIMIT", 3)
    std = run_cli(["us-ma", "--cards", "photo", "-o", "std.apkg"], tmp_path, monkeypatch, capsys)
    full = run_cli(
        ["us-ma", "--cards", "photo", "--tier", "everything", "-o", "all.apkg"], tmp_path, monkeypatch, capsys
    )
    assert std.code == full.code == 0
    assert len(note_fields(tmp_path / "std.apkg")) == 3
    assert len(note_fields(tmp_path / "all.apkg")) == 11


def test_subdeck_and_deck_name(tmp_path, monkeypatch, capsys):
    plain = run_cli(["us-ma", "-o", "plain.apkg"], tmp_path, monkeypatch, capsys)
    sub = run_cli(["us-ma", "--subdeck", "-o", "sub.apkg"], tmp_path, monkeypatch, capsys)
    named = run_cli(["us-ma", "--deck-name", "Birds", "-o", "named.apkg"], tmp_path, monkeypatch, capsys)
    assert plain.code == sub.code == named.code == 0
    assert [d["name"] for d in deck_info(tmp_path / "plain.apkg")] == ["AviAnki"]
    assert [d["name"] for d in deck_info(tmp_path / "sub.apkg")] == ["AviAnki::Massachusetts"]
    assert [d["name"] for d in deck_info(tmp_path / "named.apkg")] == ["Birds"]


def test_quiet_prints_nothing_on_success(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az", "-q"], tmp_path, monkeypatch, capsys)
    assert r.code == 0 and r.out == "" and r.err == ""
    assert (tmp_path / "AviAnki-us-az.apkg").is_file()


def test_verbose_and_quiet_exclude_each_other(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-az", "-v", "-q"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2


def test_an_unknown_region_exits_2_with_suggestions(tmp_path, monkeypatch, capsys):
    r = run_cli(["Massachusets"], tmp_path, monkeypatch, capsys)
    assert r.code == 2
    assert "Massachusetts" in r.err
    assert "--ebird" in r.err
    assert not list(tmp_path.glob("*.apkg"))


def test_a_region_only_in_regions_csv_points_at_its_ebird_code(tmp_path, monkeypatch, capsys):
    for query in ("Ontario", "CA-ON"):
        r = run_cli([query], tmp_path, monkeypatch, capsys)
        assert r.code == 2
        assert "avianki --ebird CA-ON" in r.err


def test_the_ebird_hint_folds_accents_like_the_catalog_lookup():
    # The same fold as CatalogClient.find_region, so "quebec" names Québec in both places.
    assert cli._known_ebird_region("  QUEBEC ") == ("CA-QC", "Québec")


def test_no_region_is_a_usage_error(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli([], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "REGION" in capsys.readouterr().err


def test_a_region_and_ebird_together_is_a_usage_error(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "--ebird", "US-MA"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2


def test_urls_are_no_longer_regions(tmp_path, monkeypatch, capsys):
    r = run_cli(["https://www.allaboutbirds.org/guide/browse"], tmp_path, monkeypatch, capsys)
    assert r.code == 2  # just an unknown region now


def test_a_broken_catalog_exits_1_without_a_traceback(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run_cli(["us-ma"], tmp_path, monkeypatch, capsys, catalog=empty)
    assert r.code == 1
    assert r.err.startswith("avianki: error:")
    assert "Traceback" not in r.err
    assert "-v" in r.err


def test_verbose_shows_the_traceback_of_a_failure(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run_cli(["us-ma", "-v"], tmp_path, monkeypatch, capsys, catalog=empty)
    assert r.code == 1
    assert "Traceback" in r.err


def test_a_region_with_no_usable_media_is_an_error_not_an_empty_deck(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "plan_notes", lambda *a, **k: [])
    r = run_cli(["us-ma"], tmp_path, monkeypatch, capsys)
    assert r.code == 1
    assert "nothing to write" in r.err
    assert not list(tmp_path.glob("*.apkg"))


def test_species_without_media_for_the_chosen_cards_are_left_out_before_the_limit(
    tmp_path, monkeypatch, capsys
):
    # Common Loon has no photo. It is chosen out up front, so the deck has the other 11 and the
    # old "N selected species have no media" afterthought has nothing to say.
    r = run_cli(["us-ma", "--cards", "photo", "-o", "p.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert "for 11 species" in r.out
    assert "have no media" not in r.out


def test_help_lists_every_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    for flag in (
        "--tier", "--cards", "--month", "--subdeck", "--ebird", "--output", "--catalog-url",
        "--deck-name", "--cache-dir", "--verbose", "--quiet",
    ):
        assert flag in text
    assert "different deck" in text


def test_the_bundled_regions_csv_is_the_taxonomy_one():
    assert taxonomy.DATA_DIR / "regions.csv" == cli.REGIONS_CSV
    assert cli.REGIONS_CSV.is_file()


def test_the_run_leaves_only_the_deck_in_the_working_directory(tmp_path, monkeypatch, capsys):
    run_cli(["us-az"], tmp_path, monkeypatch, capsys)
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["AviAnki-us-az.apkg"]


def test_the_apkg_media_map_matches_its_notes(tmp_path, monkeypatch, capsys):
    run_cli(["us-az"], tmp_path, monkeypatch, capsys)
    conn, media = read_apkg(tmp_path / "AviAnki-us-az.apkg")
    conn.close()
    assert media and all(v.startswith("avianki_") for v in media.values())
