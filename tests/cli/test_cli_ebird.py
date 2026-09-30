"""`avianki --ebird CODE`: the CLI over fake eBird, fake sources and a scripted BirdNET (offline)."""

from __future__ import annotations

import pytest
from cli_fakes import deck_info, note_fields, read_apkg, run_cli
from ebird_fakes import EbirdSession, install

from avianki import cli
from avianki.catalog import adhoc
from avianki.deck.credits import EBIRD_NOTICE

KEY = {"EBIRD_API_KEY": "k3y"}


def run(argv, tmp_path, monkeypatch, capsys, **kw):
    kw.setdefault("env", KEY)
    return run_cli(argv, tmp_path, monkeypatch, capsys, **kw)


def test_a_missing_key_exits_2_and_says_where_to_get_one(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run(["--ebird", "US-MA"], tmp_path, monkeypatch, capsys, env={})
    assert r.code == 2
    assert "EBIRD_API_KEY" in r.err and "ebird.org/api/keygen" in r.err
    assert not list(tmp_path.glob("*.apkg"))


def test_a_blank_key_counts_as_missing(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run(["--ebird", "US-MA"], tmp_path, monkeypatch, capsys, env={"EBIRD_API_KEY": "  "})
    assert r.code == 2


def test_month_cannot_be_combined_with_ebird(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run(["--ebird", "US-MA", "--month", "5"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "--month" in capsys.readouterr().err


def test_a_bad_code_exits_2(tmp_path, monkeypatch, capsys):
    session, *_ = install(monkeypatch)
    r = run(["--ebird", "Massachusetts"], tmp_path, monkeypatch, capsys)
    assert r.code == 2 and "eBird region code" in r.err
    assert session.calls == []


def test_the_default_output_is_named_for_the_code(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run(["--ebird", "us-ma-017"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert (tmp_path / "AviAnki-US-MA-017.apkg").is_file()
    assert "Next: open AviAnki-US-MA-017.apkg in Anki" in r.out


def test_the_deck_has_catalog_and_live_species_and_every_credit(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run(["--ebird", "US-MA-017", "-o", "e.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    rows = note_fields(tmp_path / "e.apkg")
    text = "\n".join("\x1f".join(f) for f in rows)
    for name in ("American Robin", "House Wren", "Zzyzx Fakebird", "Blue Jay"):
        assert name in text
    # four species, a photo note and an audio note each (the jay's fixture audio included)
    assert len(rows) == 8
    conn, media = read_apkg(tmp_path / "e.apkg")
    conn.close()
    assert len(media) >= 8


def test_the_notice_is_printed_and_the_deck_says_it_is_for_personal_use(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run(["--ebird", "US-MA-017", "-o", "e.apkg"], tmp_path, monkeypatch, capsys)
    assert EBIRD_NOTICE in r.out
    decks = deck_info(tmp_path / "e.apkg")
    assert any(EBIRD_NOTICE.split(".")[0] in d.get("desc", "") for d in decks)


def test_the_notice_survives_quiet(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run(["--ebird", "US-MA-017", "-q", "-o", "e.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0
    assert r.out.strip() == EBIRD_NOTICE.strip()


def test_the_catalog_deck_does_not_carry_the_notice(tmp_path, monkeypatch, capsys):
    r = run(["us-az"], tmp_path, monkeypatch, capsys)
    assert EBIRD_NOTICE not in r.out
    assert all(EBIRD_NOTICE.split(".")[0] not in d.get("desc", "") for d in deck_info(tmp_path / "AviAnki-us-az.apkg"))


def test_the_standard_tier_keeps_the_first_species_in_ebirds_order(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    monkeypatch.setattr(cli, "STANDARD_LIMIT", 2)
    r = run(["--ebird", "US-MA-017", "--cards", "photo", "-o", "s.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    text = "\n".join("\x1f".join(f) for f in note_fields(tmp_path / "s.apkg"))
    assert "American Robin" in text and "House Wren" in text
    assert "Zzyzx" not in text and "Blue Jay" not in text


def test_the_everything_tier_keeps_them_all(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    monkeypatch.setattr(cli, "STANDARD_LIMIT", 2)
    r = run(
        ["--ebird", "US-MA-017", "--tier", "everything", "--cards", "photo", "-o", "a.apkg"],
        tmp_path, monkeypatch, capsys,
    )
    assert r.code == 0, r.err
    assert len(note_fields(tmp_path / "a.apkg")) == 4


def test_a_subdeck_is_named_for_the_code_when_it_has_no_display_name(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    run(["--ebird", "US-MA-017", "--subdeck", "-o", "s.apkg"], tmp_path, monkeypatch, capsys)
    assert [d["name"] for d in deck_info(tmp_path / "s.apkg")] == ["AviAnki::US-MA-017"]


def test_a_subdeck_uses_the_regions_csv_name_when_there_is_one(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    run(["--ebird", "CA-ON", "--subdeck", "-o", "s.apkg"], tmp_path, monkeypatch, capsys)
    assert [d["name"] for d in deck_info(tmp_path / "s.apkg")] == ["AviAnki::Ontario"]


def test_missing_tools_are_reported_but_the_photos_are_still_built(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    monkeypatch.setattr(adhoc.shutil, "which", lambda name: None)
    r = run(["--ebird", "US-MA-017", "-o", "e.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert "ffmpeg" in r.err and "warning" in r.err


def test_a_missing_catalog_extra_exits_2_with_the_install_command(tmp_path, monkeypatch, capsys):
    install(monkeypatch)

    def unavailable(*a, **k):
        raise adhoc.AdhocUnavailable("needs the catalog extra. Install it with: pip install 'avianki[catalog]'")

    monkeypatch.setattr(adhoc, "build_ebird_species", unavailable)
    r = run(["--ebird", "US-MA-017"], tmp_path, monkeypatch, capsys)
    assert r.code == 2 and "pip install 'avianki[catalog]'" in r.err


def test_an_ebird_failure_exits_1_without_a_traceback(tmp_path, monkeypatch, capsys):
    install(monkeypatch, session=EbirdSession(status=403))
    r = run(["--ebird", "US-MA-017"], tmp_path, monkeypatch, capsys)
    assert r.code == 1
    assert r.err.startswith("avianki: error:") or "avianki: error:" in r.err
    assert "Traceback" not in r.err
    assert "k3y" not in r.err and "k3y" not in r.out
    assert not list(tmp_path.glob("*.apkg"))


def test_a_source_failure_is_a_warning_naming_the_unfinished_species(tmp_path, monkeypatch, capsys):
    from ebird_fakes import WREN_ID, live_sources

    from avianki.core.http import SourceError

    commons, inat = live_sources()
    commons.candidate_errors[WREN_ID] = SourceError("commons: 503")
    install(monkeypatch, sources=(commons, inat))
    r = run(["--ebird", "US-MA-017", "-o", "e.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0
    assert "a source failed" in r.err and WREN_ID in r.err


def test_a_region_with_no_species_is_an_error(tmp_path, monkeypatch, capsys):
    install(monkeypatch, session=EbirdSession(order=[]))
    r = run(["--ebird", "US-MA-017"], tmp_path, monkeypatch, capsys)
    assert r.code == 1 and "nothing to write" in r.err


def test_the_ebird_deck_is_built_with_the_ebird_flag(tmp_path, monkeypatch, capsys):
    seen = {}
    real = cli.write_deck

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)

    monkeypatch.setattr(cli, "write_deck", spy)
    install(monkeypatch)
    run(["--ebird", "US-MA-017", "-o", "e.apkg"], tmp_path, monkeypatch, capsys)
    assert seen["ebird"] is True
    run(["us-az", "-o", "c.apkg"], tmp_path, monkeypatch, capsys)
    assert seen["ebird"] is False
