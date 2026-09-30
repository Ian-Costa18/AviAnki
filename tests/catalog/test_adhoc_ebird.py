"""Tests for avianki.catalog.adhoc: the upstream half of ``--ebird``, over fakes (no network).

eBird is a fake session, the asset sources are `FakeSource`s, BirdNET is a `ScriptedAnalyzer`;
images go through real Pillow and audio through real ffmpeg (as in the catalog build tests).
"""

from __future__ import annotations

import builtins
import dataclasses
from pathlib import Path

import pytest
from ebird_fakes import (
    FIXTURE_CATALOG,
    JAY_ID,
    NEW_CODE,
    NEW_ID,
    ROBIN_CODE,
    ROBIN_ID,
    TAXA,
    WREN_ID,
    EbirdSession,
    install,
    live_sources,
)
from avianki.catalog import adhoc
from avianki.catalog.client import CatalogClient
from avianki.catalog.format import SpeciesFile
from avianki.core.http import HttpError, SourceError
from avianki.taxonomy.species import load_species


@pytest.fixture
def catalog(tmp_path: Path) -> SpeciesFile:
    return CatalogClient(str(FIXTURE_CATALOG), cache_dir=tmp_path / "catalog-cache").species()


def build(catalog: SpeciesFile, tmp_path: Path, code: str = "US-MA-017", **kw) -> adhoc.AdhocSpecies:
    return adhoc.build_ebird_species(
        code, api_key="k3y", catalog_species=catalog, cache_dir=tmp_path / "cache", **kw
    )


def test_species_come_back_in_ebirds_order_with_hybrids_left_out(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    got = build(catalog, tmp_path)
    assert got.species_ids == [ROBIN_ID, WREN_ID, NEW_ID, JAY_ID]


def test_catalog_species_keep_the_catalogs_media_and_are_not_rebuilt(monkeypatch, tmp_path, catalog):
    _session, (commons, _inat), _analyzer = install(monkeypatch)
    got = build(catalog, tmp_path)
    assert got.from_catalog == 2  # the robin and the jay are in the fixture catalog
    assert set(got.entries) == {WREN_ID, NEW_ID}
    asked = commons.candidate_species()
    assert ROBIN_ID not in asked and JAY_ID not in asked


def test_live_species_get_names_photo_audio_and_credits(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    got = build(catalog, tmp_path)
    wren = got.entries[WREN_ID]
    assert (wren.name, wren.sci) == ("House Wren", "Troglodytes aedon")
    assert len(wren.photo) == 1 and len(wren.audio) == 1
    assert "Creator" in wren.photo[0].credit and "Creator" in wren.audio[0].credit
    # every referenced file was written under the cache dir, in the catalog's layout
    for ref in (wren.photo[0], wren.audio[0]):
        assert ref.file.startswith("media/")
        assert got.media[ref.file] == tmp_path / "cache" / ref.file
        assert got.media[ref.file].is_file()


def test_a_species_not_in_the_tables_gets_a_transient_id_and_is_built(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    before = [r.id for r in load_species()]
    got = build(catalog, tmp_path)
    assert NEW_ID in got.entries and got.entries[NEW_ID].name == "Zzyzx Fakebird"
    assert [r.id for r in load_species()] == before  # nothing was written back
    assert NEW_ID not in before


def test_the_ebird_code_column_is_used_before_the_scientific_name(monkeypatch, tmp_path, catalog):
    real = load_species()
    # Give the wren's row the code "zzyzx1". That taxon has an unknown scientific name, so it can
    # only become the wren through the code; its own "houwre" taxon then repeats the same species.
    coded = [
        dataclasses.replace(r, ebird_code=NEW_CODE) if r.id == WREN_ID else r for r in real.all_rows()
    ]
    monkeypatch.setattr(adhoc, "load_species", lambda: type(real)(coded))
    install(monkeypatch)
    got = build(catalog, tmp_path)
    assert got.species_ids == [ROBIN_ID, WREN_ID, JAY_ID]
    assert NEW_ID not in got.species_ids


def test_names_that_cannot_be_an_id_are_skipped_with_a_reason(monkeypatch, tmp_path, catalog):
    odd = {"speciesCode": "odd001", "comName": "Odd Bird", "sciName": "Turdus 3", "category": "species"}
    session = EbirdSession(order=[ROBIN_CODE, "odd001"], taxa=[*TAXA, odd])
    install(monkeypatch, session=session)
    got = build(catalog, tmp_path)
    assert got.species_ids == [ROBIN_ID]
    assert len(got.skipped) == 1 and "Odd Bird" in got.skipped[0]


def test_two_taxa_on_one_species_make_one_species(monkeypatch, tmp_path, catalog):
    dup = {"speciesCode": "amerob2", "comName": "American Robin (x)", "sciName": "Turdus migratorius", "category": "species"}
    session = EbirdSession(order=[ROBIN_CODE, "amerob2"], taxa=[*TAXA, dup])
    install(monkeypatch, session=session)
    assert build(catalog, tmp_path).species_ids == [ROBIN_ID]


def test_limit_keeps_the_first_n_before_anything_is_built(monkeypatch, tmp_path, catalog):
    _s, (commons, _i), _a = install(monkeypatch)
    got = build(catalog, tmp_path, limit=2)
    assert got.species_ids == [ROBIN_ID, WREN_ID]
    assert commons.candidate_species().count(NEW_ID) == 0
    assert set(got.entries) == {WREN_ID}


def test_when_the_catalog_has_everything_nothing_is_built_and_no_tools_are_needed(monkeypatch, tmp_path, catalog):
    session = EbirdSession(order=[ROBIN_CODE, "blujay"])
    install(monkeypatch, session=session)
    monkeypatch.setattr(adhoc, "new_registry", lambda *a: pytest.fail("built something"))
    monkeypatch.setattr(adhoc.shutil, "which", lambda name: None)  # no ffmpeg: must not matter
    got = build(catalog, tmp_path)
    assert got.entries == {} and got.media == {} and got.from_catalog == 2 and got.notes == []


def test_progress_counts_the_species_built_live(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    ticks: list[tuple[int, int]] = []
    build(catalog, tmp_path, progress=lambda done, total: ticks.append((done, total)))
    assert ticks[0] == (0, 2) and ticks[-1] == (2, 2)


def test_a_source_that_failed_leaves_the_species_unfinished_not_absent(monkeypatch, tmp_path, catalog):
    commons, inat = live_sources()
    commons.candidate_errors[WREN_ID] = SourceError("commons: 503")
    install(monkeypatch, sources=(commons, inat))
    got = build(catalog, tmp_path)
    assert WREN_ID in got.unfinished
    assert NEW_ID not in got.unfinished


def test_a_species_with_no_media_anywhere_has_an_empty_entry(monkeypatch, tmp_path, catalog):
    commons, inat = live_sources()
    commons.offers.clear()
    install(monkeypatch, sources=(commons, inat))
    got = build(catalog, tmp_path)
    for sid in (WREN_ID, NEW_ID):
        entry = got.entries.get(sid)
        assert entry is None or (not entry.photo and not entry.audio)
    assert got.unfinished == []  # a real, empty answer is absence, not failure


def test_without_ffmpeg_recordings_are_dropped_and_photos_kept_with_a_note(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    monkeypatch.setattr(adhoc.shutil, "which", lambda name: None)
    got = build(catalog, tmp_path)
    assert got.entries[WREN_ID].photo and not got.entries[WREN_ID].audio
    assert any("ffmpeg" in n for n in got.notes)


def test_without_birdnet_recordings_are_dropped_and_photos_kept_with_a_note(monkeypatch, tmp_path, catalog):
    from avianki.media.verify import VerifyUnavailable

    install(monkeypatch)

    def missing():
        raise VerifyUnavailable("birdnet is not installed")

    monkeypatch.setattr(adhoc, "new_analyzer", missing)
    got = build(catalog, tmp_path)
    assert got.entries[WREN_ID].photo and not got.entries[WREN_ID].audio
    assert any("avianki[verify]" in n for n in got.notes)


def test_verify_true_makes_missing_audio_tools_an_error(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    monkeypatch.setattr(adhoc.shutil, "which", lambda name: None)
    with pytest.raises(adhoc.AdhocUnavailable, match="ffmpeg"):
        build(catalog, tmp_path, verify=True)


def test_verify_false_skips_live_audio_with_a_note(monkeypatch, tmp_path, catalog):
    _s, _src, analyzer = install(monkeypatch)
    got = build(catalog, tmp_path, verify=False)
    assert not got.entries[WREN_ID].audio and got.entries[WREN_ID].photo
    assert analyzer.calls == []
    assert got.notes


def test_the_audio_that_fails_the_birdnet_check_is_not_kept(monkeypatch, tmp_path, catalog):
    from pipeline_fakes import ScriptedAnalyzer

    from ebird_fakes import LABELS

    install(monkeypatch, analyzer=ScriptedAnalyzer([0.0], labels=LABELS))
    got = build(catalog, tmp_path)
    assert got.entries[WREN_ID].photo and not got.entries[WREN_ID].audio


def test_a_missing_catalog_extra_says_what_to_install(monkeypatch, tmp_path, catalog):
    install(monkeypatch)
    real_import = builtins.__import__

    def deny(name, *args, **kwargs):
        if name == "avianki.catalog.build":
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    with pytest.raises(adhoc.AdhocUnavailable, match=r"pip install 'avianki\[catalog\]'"):
        build(catalog, tmp_path)


@pytest.mark.parametrize("bad", ["", "Massachusetts", "us ma", "../x", "US-MA-017-1"])
def test_a_bad_region_code_is_rejected_before_any_request(bad, monkeypatch, tmp_path, catalog):
    session, *_ = install(monkeypatch)
    with pytest.raises(adhoc.InvalidRegionCode):
        build(catalog, tmp_path, code=bad)
    assert session.calls == []


def test_a_lower_case_code_is_accepted(monkeypatch, tmp_path, catalog):
    session, *_ = install(monkeypatch)
    build(catalog, tmp_path, code="us-ma")
    assert session.calls[0][0].endswith("/US-MA")


def test_the_api_key_goes_in_a_header_only(monkeypatch, tmp_path, catalog):
    session, *_ = install(monkeypatch)
    build(catalog, tmp_path)
    assert all(h.get("X-eBirdApiToken") == "k3y" for _u, _p, h in session.calls)
    assert all("k3y" not in u for u, _p, _h in session.calls)


def test_an_ebird_http_error_propagates_for_the_caller_to_report(monkeypatch, tmp_path, catalog):
    install(monkeypatch, session=EbirdSession(status=403))
    with pytest.raises(HttpError):
        build(catalog, tmp_path)


def test_an_empty_region_is_an_empty_result(monkeypatch, tmp_path, catalog):
    install(monkeypatch, session=EbirdSession(order=[]))
    got = build(catalog, tmp_path)
    assert got.species_ids == [] and got.entries == {}


def test_the_registry_is_given_the_transient_row_but_the_table_is_not_changed(monkeypatch, tmp_path, catalog):
    seen: dict[str, list[str]] = {}
    install(monkeypatch)
    fake_registry = adhoc.new_registry

    def registry(client, table):
        seen["ids"] = [r.id for r in table]
        return fake_registry(client, table)

    monkeypatch.setattr(adhoc, "new_registry", registry)
    build(catalog, tmp_path)
    assert NEW_ID in seen["ids"]
    assert NEW_ID not in [r.id for r in load_species()]
