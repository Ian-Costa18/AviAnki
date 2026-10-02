"""End-to-end tests for avianki.catalog.build against fake sources and a scripted BirdNET.

Images go through real Pillow and audio through real ffmpeg; only the network and the model are
faked. Nothing here touches the network.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from catalog_fakes import mutated_copy
from pipeline_fakes import (
    AUDIO,
    CHICKADEE,
    JAY,
    JUNK_AUDIO,
    LABELS,
    ROBIN_LABEL,
    PHOTO,
    REGION_DC,
    REGION_RI,
    ROBIN,
    WREN,
    FakeSource,
    FakeSourceNoSpecies,
    FakeSpeciesSource,
    ScriptedAnalyzer,
    image_bytes,
    make_fake_registry,
    make_table,
    small_image_bytes,
)

from avianki.catalog.build import BuildOptions, BuildResult, build_species, run_build
from avianki.catalog.format import ProvenanceFile
from avianki.catalog.pins import Pins, parse_pins
from avianki.core.http import HttpError, SourceError
from avianki.media.verify import VerifyUnavailable
from avianki.taxonomy.species import SpeciesTable

IDS = [ROBIN, JAY, CHICKADEE]
LISTS: dict[str, Any] = {"us-ri": [ROBIN, JAY, CHICKADEE], "us-dc": [JAY, CHICKADEE, ROBIN]}


def pins_for(text: str, *ids: str) -> Pins:
    return parse_pins(text, make_table(*(ids or (ROBIN, JAY, CHICKADEE))))


def full_sources() -> tuple[FakeSource, FakeSourceNoSpecies]:
    """Commons has a photo and a recording for every species; iNaturalist has nothing."""
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    for sid in IDS:
        commons.add(sid, PHOTO, f"{sid}-cp")
        commons.add(sid, AUDIO, f"{sid}-ca")
    return commons, inat


def species_build(commons: FakeSource, inat: FakeSource, *, analyzer=None, ids=None, **kw):
    return build_species(
        ids or IDS,
        table=kw.pop("table", None) or make_table(),
        registry=make_fake_registry(commons, inat),
        analyzer=analyzer or ScriptedAnalyzer([0.9]),
        labels=LABELS,
        **kw,
    )


# ---------------------------------------------------------------------------------------
# build_species: selection
# ---------------------------------------------------------------------------------------


def test_three_species_first_source_fallback_and_failure():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(ROBIN, PHOTO, "R-photo")  # A: photo from source 1
    commons.add(ROBIN, AUDIO, "R-audio")
    inat.add(JAY, PHOTO, "J-photo")  # B: source 1 says [] (nothing offered), source 2 has one
    inat.add(JAY, AUDIO, "J-audio")
    commons.candidate_errors[CHICKADEE] = SourceError("HTTP 503")  # C: source 1 can't say
    inat.add(CHICKADEE, PHOTO, "C-photo")  # must NOT be used: a failure is not absence
    analyzer = ScriptedAnalyzer([0.9], [0.8])

    built = species_build(commons, inat, analyzer=analyzer)

    sp, prov, rep = built.species, built.provenance, built.report
    assert len(sp[ROBIN].photo) == 1 and len(sp[JAY].photo) == 1
    assert prov.entries[sp[ROBIN].photo[0].file].record.source == "commons"
    assert prov.entries[sp[JAY].photo[0].file].record.source == "inaturalist"
    assert sp[CHICKADEE].photo == [] and sp[CHICKADEE].audio == []
    assert "C-photo" not in inat.fetched
    assert CHICKADEE not in inat.candidate_species()  # never asked: no fall-through on failure
    assert [(f.source, f.species_id) for f in rep.source_failures] == [("commons", CHICKADEE)] * 2  # photo, audio
    assert rep.unfinished_species == [CHICKADEE]
    assert CHICKADEE not in rep.species_without_photo  # unfinished, not absent
    assert rep.photos_by_source == {"commons": 1, "inaturalist": 1}
    audio = prov.entries[sp[ROBIN].audio[0].file]
    assert (audio.verified, audio.birdnet_confidence) == ("birdnet", 0.9)
    assert prov.entries[sp[JAY].audio[0].file].birdnet_confidence == 0.8
    assert prov.entries[sp[ROBIN].photo[0].file].verified is None
    # the output is what the pipeline produced, not the source's bytes
    assert all(name.startswith("media/") for name in built.media)
    assert built.media[sp[ROBIN].photo[0].file] != image_bytes(1)


def test_a_real_empty_answer_from_every_source_is_absence():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.offer_empty(ROBIN, PHOTO)
    inat.offer_empty(ROBIN, PHOTO)
    built = species_build(commons, inat, ids=[ROBIN])
    assert built.report.species_without_photo == [ROBIN]
    assert built.report.unfinished_species == []
    assert built.report.source_failures == []
    assert inat.candidate_species() == [ROBIN, ROBIN]  # asked for photo, then audio


def test_a_small_image_is_rejected_and_the_next_candidate_used():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(ROBIN, PHOTO, "tiny-advertised", width=500, height=300)  # screened out, never fetched
    commons.add(ROBIN, PHOTO, "tiny-real", small_image_bytes(3))  # only the pixels reveal it
    commons.add(ROBIN, PHOTO, "good")
    built = species_build(commons, inat, ids=[ROBIN])
    assert commons.fetched == ["tiny-real", "good"]
    reasons = {r.token: r.reason for r in built.report.rejections if r.kind == "photo"}
    assert "too small" in reasons["tiny-advertised"]
    assert reasons["tiny-real"].startswith("image:") and "800" in reasons["tiny-real"]
    assert built.provenance.entries[built.species[ROBIN].photo[0].file].token == "good"
    assert inat.calls_of("candidates") == [("candidates", (ROBIN,), AUDIO, 5)]  # photo not asked of source 2


def test_a_candidate_that_has_gone_is_skipped_but_other_errors_are_not_absence():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(ROBIN, PHOTO, "gone")
    commons.add(ROBIN, PHOTO, "next")
    commons.fetch_errors["gone"] = HttpError(404, "https://example.test/gone")
    commons.add(JAY, PHOTO, "broken")
    commons.add(JAY, PHOTO, "never-tried")
    commons.fetch_errors["broken"] = HttpError(503, "https://example.test/broken")
    inat.add(JAY, PHOTO, "elsewhere")
    built = species_build(commons, inat, ids=[ROBIN, JAY])
    assert built.provenance.entries[built.species[ROBIN].photo[0].file].token == "next"
    assert any(r.token == "gone" and "gone" in r.reason for r in built.report.rejections)
    assert built.species[JAY].photo == []  # a 503 is a failure: no next candidate, no next source
    assert "never-tried" not in commons.fetched and "elsewhere" not in inat.fetched
    assert JAY in built.report.unfinished_species and ROBIN not in built.report.unfinished_species
    assert [f.species_id for f in built.report.source_failures] == [JAY]


def test_audio_stops_at_the_first_pass_and_never_fetches_later_candidates():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    for token in ("a1", "a2", "a3"):
        commons.add(ROBIN, AUDIO, token)
    analyzer = ScriptedAnalyzer([0.2, 0.3], [0.7, 0.1], [0.99])
    built = species_build(commons, inat, analyzer=analyzer, ids=[ROBIN])
    assert commons.fetched == ["a1", "a2"]  # a3 was never downloaded
    entry = built.provenance.entries[built.species[ROBIN].audio[0].file]
    assert (entry.token, entry.verified, entry.birdnet_confidence) == ("a2", "birdnet", 0.7)
    assert [r.token for r in built.report.rejections if r.kind == "audio"] == ["a1"]
    assert analyzer.calls == [ROBIN_LABEL] * 2
    mp3 = built.media[built.species[ROBIN].audio[0].file]
    assert mp3[:3] == b"ID3" or mp3[0] == 0xFF  # an MP3 the pipeline encoded, not the source's WAV


def test_an_unreadable_recording_is_skipped_without_scoring_it():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(ROBIN, AUDIO, "junk", JUNK_AUDIO)
    commons.add(ROBIN, AUDIO, "fine")
    analyzer = ScriptedAnalyzer([0.9])
    built = species_build(commons, inat, analyzer=analyzer, ids=[ROBIN])
    assert commons.fetched == ["junk", "fine"]
    assert len(analyzer.calls) == 1
    assert any(r.token == "junk" and "unreadable" in r.reason for r in built.report.rejections)
    assert built.provenance.entries[built.species[ROBIN].audio[0].file].token == "fine"


def test_at_most_five_audio_candidates_across_all_sources():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    for i in range(3):
        commons.add(ROBIN, AUDIO, f"c{i}")
    for i in range(4):
        inat.add(ROBIN, AUDIO, f"i{i}")
    analyzer = ScriptedAnalyzer([0.1])
    built = species_build(commons, inat, analyzer=analyzer, ids=[ROBIN])
    assert len(commons.fetched) + len(inat.fetched) == 5
    assert len(analyzer.calls) == 5
    assert built.species[ROBIN].audio == []
    assert built.report.species_without_audio == [ROBIN]  # every source answered: real absence
    audio_limits = [c[3] for c in commons.calls_of("candidates") + inat.calls_of("candidates") if c[2] is AUDIO]
    assert audio_limits == [5, 2]  # the second source is only asked for the slots left


def test_no_birdnet_label_and_no_pin_means_no_audio_and_no_request():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(WREN, PHOTO, "w-photo")
    commons.add(WREN, AUDIO, "w-audio")
    analyzer = ScriptedAnalyzer([0.9])
    built = species_build(commons, inat, analyzer=analyzer, ids=[WREN], table=make_table(WREN))
    assert built.species[WREN].audio == [] and len(built.species[WREN].photo) == 1
    assert built.report.unmapped_species == {WREN: ["birdnet_label"]}
    assert analyzer.calls == [] and "w-audio" not in commons.fetched
    assert all(c[2] is not AUDIO for c in commons.calls_of("candidates"))


def test_a_label_found_in_the_label_list_is_reported_for_species_csv():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(WREN, AUDIO, "w-audio")
    labels = [*LABELS, "Troglodytes aedon_House Wren"]
    built = build_species(
        [WREN], table=make_table(WREN), registry=make_fake_registry(commons, inat),
        analyzer=ScriptedAnalyzer([0.9]), labels=labels,
    )  # fmt: skip
    assert len(built.species[WREN].audio) == 1
    assert built.report.new_ids_discovered[WREN]["birdnet_label"] == "Troglodytes aedon_House Wren"


def test_verification_unavailable_stops_the_build():
    commons, inat = full_sources()

    class NoModel:
        def predict(self, path, label):
            raise VerifyUnavailable("BirdNET is not installed")

    with pytest.raises(VerifyUnavailable):
        species_build(commons, inat, analyzer=NoModel(), ids=[ROBIN])


def test_no_verify_builds_audio_only_from_pins_and_says_so():
    commons, inat = full_sources()
    commons.add(ROBIN, AUDIO, "pinned-audio", offer=False)
    pins = pins_for('[turdus-migratorius]\naudio = "commons:pinned-audio"\nnote = "n"\n')
    analyzer = ScriptedAnalyzer([0.9])
    built = species_build(commons, inat, analyzer=analyzer, pins=pins, verify=False)
    assert analyzer.calls == []
    assert len(built.species[ROBIN].audio) == 1 and built.species[JAY].audio == []
    assert all(c[2] is not AUDIO for c in commons.calls_of("candidates"))
    assert any("AUDIO NOT VERIFIED" in n for n in built.report.notes)


def test_inaturalist_taxon_ids_are_reported_and_unmapped_species_listed():
    class Inat(FakeSourceNoSpecies):
        def resolve_taxa(self, species_ids):
            return {s: 900 + i for i, s in enumerate(species_ids) if s != CHICKADEE}

    commons, inat = FakeSource("commons"), Inat("inaturalist")
    for sid in IDS:
        commons.offer_empty(sid, PHOTO)
        inat.offer_empty(sid, PHOTO)
    built = species_build(commons, inat, analyzer=ScriptedAnalyzer([0.1]))
    assert built.report.new_ids_discovered[ROBIN]["inat_taxon_id"] == "900"
    assert built.report.unmapped_species[CHICKADEE] == ["inat_taxon_id"]


# ---------------------------------------------------------------------------------------
# build_species: pins
# ---------------------------------------------------------------------------------------


def test_a_pin_overrides_ranking_and_birdnet():
    commons, inat = full_sources()
    inat = FakeSourceNoSpecies("inaturalist")
    commons.add(ROBIN, PHOTO, "PIN-P", offer=False)
    inat.add(ROBIN, AUDIO, "PIN-S", offer=False)
    pins = pins_for('[turdus-migratorius]\nphoto = "commons:PIN-P"\naudio = "inaturalist:PIN-S"\nnote = "n"\n')
    analyzer = ScriptedAnalyzer([0.0])  # BirdNET would reject everything
    built = species_build(commons, inat, analyzer=analyzer, pins=pins, ids=[ROBIN])
    photo = built.provenance.entries[built.species[ROBIN].photo[0].file]
    audio = built.provenance.entries[built.species[ROBIN].audio[0].file]
    assert (photo.token, photo.verified) == ("PIN-P", "pinned")
    assert (audio.token, audio.verified, audio.birdnet_confidence) == ("PIN-S", "pinned", None)
    assert analyzer.calls == []
    assert commons.calls_of("candidates") == [] and inat.calls_of("candidates") == []  # no ranking at all
    assert commons.calls_of("resolve_pin") == [("resolve_pin", "PIN-P", ROBIN)]  # species id passed where accepted
    assert inat.calls_of("resolve_pin") == [("resolve_pin", "PIN-S", None)]
    assert built.report.pinned_used == 2


def test_a_pin_still_meets_the_licence_gate_and_a_bad_pin_is_a_hard_error():
    commons, inat = full_sources()
    commons.add(
        ROBIN, PHOTO, "NC", offer=False,
        licence_id="CC-BY-NC-4.0", licence_url="https://creativecommons.org/licenses/by-nc/4.0/",
    )  # fmt: skip
    pins = pins_for(
        '[turdus-migratorius]\nphoto = "commons:NC"\nnote = "n"\n'
        '[poecile-atricapillus]\nphoto = "commons:GHOST"\nnote = "n"\n'
    )
    built = species_build(commons, inat, pins=pins)
    errors = "\n".join(built.report.pin_errors)
    assert len(built.report.pin_errors) == 2
    assert "licence" in errors and "GHOST" in errors and "CC-BY-NC-4.0" in errors
    assert "NC" not in commons.fetched
    assert built.species[ROBIN].photo == []  # a failed pin is never replaced by the ranked choice
    assert {ROBIN, CHICKADEE} <= set(built.report.unfinished_species)
    assert built.report.pinned_used == 0


def test_a_pin_naming_the_wrong_species_is_an_error():
    commons, inat = full_sources()
    commons.add(JAY, PHOTO, "JAY-PHOTO", offer=False)
    pins = pins_for('[turdus-migratorius]\nphoto = "commons:JAY-PHOTO"\nnote = "n"\n')
    built = species_build(commons, inat, pins=pins, ids=[ROBIN])
    assert built.species[ROBIN].photo == []
    assert "resolves to" in built.report.pin_errors[0]


def test_an_excluded_candidate_is_never_used_and_widens_the_request():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    commons.add(ROBIN, PHOTO, "bad")
    commons.add(ROBIN, PHOTO, "good")
    pins = pins_for('[turdus-migratorius]\nexclude = ["commons:bad"]\nnote = "removal request"\n')
    built = species_build(commons, inat, pins=pins, ids=[ROBIN])
    assert "bad" not in commons.fetched
    assert built.provenance.entries[built.species[ROBIN].photo[0].file].token == "good"
    assert commons.calls_of("candidates")[0][3] == 6  # 5 + one exclusion, so the 5 usable ones still fit


# ---------------------------------------------------------------------------------------
# build_species: failures, budgets, time
# ---------------------------------------------------------------------------------------


def test_budget_exhausted_stops_that_source_and_nothing_falls_through():
    commons, inat = full_sources()
    inat.add(JAY, PHOTO, "J-inat")
    inat.add(CHICKADEE, PHOTO, "C-inat")
    commons.budget = 2  # the batch, then ROBIN's photo; JAY's fetch is over budget
    built = species_build(commons, inat)
    assert len(built.species[ROBIN].photo) == 1
    assert built.species[JAY].photo == [] and built.species[CHICKADEE].photo == []
    assert built.report.budget_exhausted
    assert {JAY, CHICKADEE} <= set(built.report.unfinished_species)
    assert inat.fetched == []  # the second source is not asked to stand in for a failure
    assert len(commons.calls) == 3  # nothing more is sent to an exhausted source
    assert any(isinstance(f.error, str) and "budget" in f.error for f in built.report.source_failures)


def test_a_failed_batch_is_retried_one_species_at_a_time_and_a_run_of_failures_trips_the_breaker():
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    ids = [ROBIN, JAY, CHICKADEE]
    commons.candidate_errors[JAY] = SourceError("boom")
    built = species_build(commons, inat, ids=ids, analyzer=ScriptedAnalyzer([0.1]))
    batches = [c[1] for c in commons.calls_of("candidates") if c[2] is PHOTO]
    assert batches == [(ROBIN, JAY, CHICKADEE), (ROBIN,), (JAY,), (CHICKADEE,)]
    assert JAY in built.report.unfinished_species


def test_the_time_budget_stops_the_run_and_lists_unfinished_species():
    now = [0.0]
    commons, inat = full_sources()
    commons.on_call = lambda: now.__setitem__(0, now[0] + 10)
    built = species_build(commons, inat, deadline=25.0, clock=lambda: now[0])
    assert len(built.species[ROBIN].photo) == 1  # done before the deadline
    assert built.species[CHICKADEE].photo == []  # cut off
    assert CHICKADEE in built.report.unfinished_species
    assert any("Time budget reached" in n for n in built.report.notes)
    assert inat.calls == []


# ---------------------------------------------------------------------------------------
# run_build: whole builds, sticky selections, output
# ---------------------------------------------------------------------------------------


def opts(out: Path, **kw: Any) -> BuildOptions:
    base: dict[str, Any] = {
        "out": out,
        "regions": [REGION_RI, REGION_DC],
        "gadm_version": "4.1",
        "eod_version": "eod-1",
        "catalog_version": "2026-09-28",
    }
    base.update(kw)
    return BuildOptions(**base)


def go(out: Path, commons: FakeSource, inat: FakeSource, *, lists=None, analyzer=None, clock=None, **kw: Any):
    """run_build with fakes. Returns (result, species source, what the registry factory was given)."""
    seen: dict[str, Any] = {}

    def factory(expected):
        seen["expected"] = expected
        return make_fake_registry(commons, inat)

    source = FakeSpeciesSource(lists or LISTS)
    extra = {"clock": clock} if clock else {}
    result = run_build(
        opts(out, **kw),
        species_source=source,
        species_table=make_table(),
        registry_factory=factory,
        analyzer=analyzer or ScriptedAnalyzer([0.9]),
        labels=LABELS,
        **extra,
    )
    return result, source, seen


@pytest.fixture
def first(tmp_path: Path) -> BuildResult:
    commons, inat = full_sources()
    result, _, _ = go(tmp_path / "one", commons, inat)
    assert result.ok, result.errors
    return result


def test_a_full_build_writes_the_site_report_and_contact_sheet(tmp_path: Path):
    commons, inat = full_sources()
    result, source, seen = go(tmp_path / "out", commons, inat)
    out = tmp_path / "out"
    assert result.ok and result.validation is not None and result.validation.ok
    for name in ("build-report.md", "contact-sheet.html", "site/manifest.json", "site/credits.html"):
        assert (out / name).is_file(), name
    assert (out / "site" / "media").is_dir()
    assert not (out / "site.new").exists()
    assert "site/" in (out / "contact-sheet.html").read_text(encoding="utf-8")
    assert "2026-09-28" in (out / "build-report.md").read_text(encoding="utf-8")
    cat = result.catalog
    assert cat is not None
    assert set(cat.regions) == {"us-ri", "us-dc"} and set(cat.species) == set(IDS)
    assert cat.manifest.eod_version == "eod-1" and cat.manifest.catalog_version == "2026-09-28"
    assert cat.manifest.base_url and cat.manifest.dataset_credits
    assert result.report.built == 3 and result.report.reused == 0
    assert result.report.photos == 3 and result.report.audio == 3
    assert source.calls == ["us-ri", "us-dc"]
    assert seen["expected"] == {ROBIN: 1996, JAY: 1997, CHICKADEE: 1995}  # ADR 0022 expected counts


def test_max_species_keeps_the_most_widespread_and_filters_region_lists(tmp_path: Path):
    commons, inat = full_sources()
    result, _, _ = go(tmp_path / "out", commons, inat, max_species=1)
    assert result.catalog is not None
    assert set(result.catalog.species) == {JAY}  # rank 2 and 1 beats robin's 1 and 3 on regions, then id
    assert all([s for s, _ in r.species] == [JAY] for r in result.catalog.regions.values())
    assert set(commons.candidate_species()) == {JAY}


def test_a_second_build_reuses_kept_assets_with_no_source_calls(tmp_path: Path, first: BuildResult):
    commons, inat = full_sources()
    analyzer = ScriptedAnalyzer([0.9])
    result, source, seen = go(tmp_path / "two", commons, inat, previous=first.catalog, analyzer=analyzer)
    assert commons.calls == [] and inat.calls == [] and analyzer.calls == []
    assert source.calls == [] and seen["expected"] is None  # species half reused: EOD unchanged
    rep = result.report
    assert (rep.reused, rep.built, rep.sticky_invalidated) == (3, 0, 0)
    assert result.catalog is not None and first.catalog is not None
    assert result.catalog.referenced_media() == first.catalog.referenced_media()
    for name in result.catalog.referenced_media():
        assert result.catalog.media_path(name).read_bytes() == first.catalog.media_path(name).read_bytes()
    assert result.ok


def test_a_new_eod_version_rebuilds_the_species_half_but_keeps_the_assets(tmp_path: Path, first: BuildResult):
    commons, inat = full_sources()
    result, source, seen = go(tmp_path / "two", commons, inat, previous=first.catalog, eod_version="eod-2")
    assert source.calls == ["us-ri", "us-dc"] and seen["expected"]
    assert commons.calls == [] and inat.calls == []
    assert result.report.reused == 3 and result.ok


def test_refresh_species_rebuilds_the_species_half_when_the_eod_version_is_unchanged(
    tmp_path: Path, first: BuildResult
):
    commons, inat = full_sources()
    result, source, seen = go(tmp_path / "two", commons, inat, previous=first.catalog, refresh_species=True)
    assert source.calls == ["us-ri", "us-dc"] and seen["expected"]
    assert commons.calls == [] and inat.calls == []
    assert result.report.reused == 3 and result.ok


def test_a_renamed_species_gets_its_kept_inaturalist_credit_and_provenance_retitled(
    tmp_path: Path, first: BuildResult
):
    assert first.catalog is not None and first.catalog.provenance is not None
    cat = first.catalog
    robin_file = cat.species[ROBIN].photo[0].file
    jay_file = cat.species[JAY].photo[0].file
    entries = dict(cat.provenance.entries)  # type: ignore[union-attr]
    entries[robin_file] = replace(
        entries[robin_file],
        record=replace(entries[robin_file].record, source="inaturalist", title="Old Robin (Turdus migratorius)"),
    )
    old_jay_title = entries[jay_file].record.title  # a Commons title: must stay as it is
    tampered = mutated_copy(cat, tmp_path / "tampered", provenance=ProvenanceFile(entries))
    renamed = SpeciesTable([replace(r, common_name="New Robin") if r.id == ROBIN else r for r in make_table()])
    commons, inat = full_sources()
    built = species_build(commons, inat, previous=tampered, table=renamed)
    assert commons.calls == [] and inat.calls == []  # kept, not rebuilt
    assert built.reused_media >= {robin_file, jay_file}
    robin = built.species[ROBIN].photo[0]
    assert robin.file == robin_file
    assert "New Robin (Turdus migratorius)" in robin.credit and "Old Robin" not in robin.credit
    assert built.provenance.entries[robin_file].record.title == "New Robin (Turdus migratorius)"
    assert built.provenance.entries[jay_file].record.title == old_jay_title
    assert old_jay_title in built.species[JAY].photo[0].credit


def test_an_excluded_token_invalidates_the_sticky_asset_and_only_that_role_is_rebuilt(
    tmp_path: Path, first: BuildResult
):
    assert first.catalog is not None
    old = first.catalog.species[ROBIN].photo[0].file
    old_token = first.catalog.provenance.entries[old].token  # type: ignore[union-attr]
    commons, inat = full_sources()
    commons.add(ROBIN, PHOTO, "replacement")
    pins = pins_for(f'[turdus-migratorius]\nexclude = ["commons:{old_token}"]\nnote = "removal request"\n')
    result, _, _ = go(tmp_path / "two", commons, inat, previous=first.catalog, pins=pins)
    assert result.catalog is not None
    new = result.catalog.species[ROBIN].photo[0].file
    assert new != old and result.catalog.provenance.entries[new].token == "replacement"  # type: ignore[union-attr]
    assert result.report.sticky_invalidated == 1
    assert commons.candidate_species() == [ROBIN] and commons.fetched == ["replacement"]  # nothing else touched
    assert (result.report.built, result.report.reused) == (1, 2)
    assert old not in result.catalog.referenced_media()
    assert result.validation is not None and not result.validation.errors, result.validation.errors
    assert result.ok


def test_a_previous_asset_whose_licence_is_no_longer_allowed_is_rebuilt(tmp_path: Path, first: BuildResult):
    assert first.catalog is not None and first.catalog.provenance is not None
    old = first.catalog.species[JAY].photo[0].file
    entry = first.catalog.provenance.entries[old]
    bad = replace(
        entry,
        record=replace(entry.record, licence_id="CC-BY-NC-4.0", licence_url="https://creativecommons.org/licenses/by-nc/4.0/"),
    )
    prov = ProvenanceFile({**first.catalog.provenance.entries, old: bad})
    tampered = mutated_copy(first.catalog, tmp_path / "tampered", provenance=prov)
    commons, inat = full_sources()
    commons.add(JAY, PHOTO, "fresh")
    result, _, _ = go(tmp_path / "two", commons, inat, previous=tampered)
    assert result.report.sticky_invalidated >= 1
    assert result.catalog is not None
    new = result.catalog.species[JAY].photo[0].file
    assert result.catalog.provenance.entries[new].record.licence_id != "CC-BY-NC-4.0"  # type: ignore[union-attr]
    assert set(commons.candidate_species()) <= {JAY}


def test_a_pin_failure_keeps_the_previous_entry_and_is_reported(tmp_path: Path, first: BuildResult):
    assert first.catalog is not None
    old = first.catalog.species[ROBIN].photo[0].file
    commons, inat = full_sources()
    commons.pin_errors["BAD"] = SourceError("HTTP 404: deleted from Commons")
    pins = pins_for('[turdus-migratorius]\nphoto = "commons:BAD"\nnote = "n"\n')
    result, _, _ = go(tmp_path / "two", commons, inat, previous=first.catalog, pins=pins)
    assert result.catalog is not None
    assert result.catalog.species[ROBIN].photo[0].file == old  # the previous entry stands
    assert (result.site_dir / old).is_file()  # type: ignore[operator]
    assert not result.ok and "BAD" in result.report.pin_errors[0]
    assert ROBIN in result.report.unfinished_species
    assert "PIN ERRORS" in (tmp_path / "two" / "build-report.md").read_text(encoding="utf-8")


def test_budget_exhaustion_still_publishes_what_exists(tmp_path: Path):
    commons, inat = full_sources()
    commons.budget = 2
    result, _, _ = go(tmp_path / "out", commons, inat)
    assert result.catalog is not None and result.report.budget_exhausted
    assert len(result.catalog.species[JAY].photo) == 1  # JAY ranks first, so it was built before the budget ran out
    assert {ROBIN, CHICKADEE} <= set(result.report.unfinished_species)
    assert (tmp_path / "out" / "site" / "manifest.json").is_file()
    assert "unfinished" in (tmp_path / "out" / "build-report.md").read_text(encoding="utf-8").lower()


def test_the_time_budget_stops_a_full_build_and_lists_unfinished_species(tmp_path: Path):
    now = [0.0]
    commons, inat = full_sources()
    commons.on_call = lambda: now.__setitem__(0, now[0] + 40)  # each call costs 40 s; the budget is 60 s
    result, _, _ = go(tmp_path / "out", commons, inat, time_budget_minutes=1, clock=lambda: now[0])
    assert result.catalog is not None
    assert len(result.report.unfinished_species) >= 1
    text = (tmp_path / "out" / "build-report.md").read_text(encoding="utf-8")
    assert "Time budget reached" in text
    assert (tmp_path / "out" / "site" / "manifest.json").is_file()


def test_the_shrink_gate_trips_and_allow_shrink_downgrades_it(tmp_path: Path, first: BuildResult):
    small = {"us-ri": [ROBIN], "us-dc": [ROBIN]}
    commons, inat = full_sources()
    blocked, _, _ = go(tmp_path / "blocked", commons, inat, lists=small, previous=first.catalog, eod_version="eod-2")
    assert blocked.validation is not None and not blocked.validation.ok and not blocked.ok
    assert any(p.code.startswith("shrink.") for p in blocked.validation.errors)
    assert (tmp_path / "blocked" / "site" / "manifest.json").is_file()  # written anyway, for inspection
    commons, inat = full_sources()
    allowed, _, _ = go(
        tmp_path / "allowed", commons, inat, lists=small, previous=first.catalog, eod_version="eod-2", allow_shrink=True
    )
    assert allowed.validation is not None and allowed.validation.ok and allowed.ok
    assert any(p.code.startswith("shrink.") for p in allowed.validation.warnings)


def test_a_failed_validation_never_replaces_a_previous_site_in_the_same_directory(tmp_path: Path):
    commons, inat = full_sources()
    out = tmp_path / "out"
    good, _, _ = go(out, commons, inat)
    assert good.ok and good.site_dir == out / "site"
    manifest_before = (out / "site" / "manifest.json").read_bytes()
    commons, inat = full_sources()
    bad, _, _ = go(out, commons, inat, lists={"us-ri": [ROBIN], "us-dc": [ROBIN]}, previous=good.catalog, eod_version="eod-2")
    assert not bad.ok and bad.site_dir == out / "site-rejected"
    assert (out / "site" / "manifest.json").read_bytes() == manifest_before
    assert any("site-rejected" in n for n in bad.report.notes)


def test_a_region_that_fails_with_no_previous_list_is_an_error(tmp_path: Path):
    commons, inat = full_sources()
    lists = {"us-ri": [ROBIN, JAY], "us-dc": SourceError("GBIF 503")}
    result, _, _ = go(tmp_path / "out", commons, inat, lists=lists)
    assert not result.ok and any("us-dc" in e for e in result.errors)
    assert result.catalog is not None and set(result.catalog.regions) == {"us-ri"}


def test_a_region_that_fails_keeps_its_previous_list(tmp_path: Path, first: BuildResult):
    commons, inat = full_sources()
    lists = {"us-ri": [ROBIN, JAY, CHICKADEE], "us-dc": SourceError("GBIF 503")}
    result, _, _ = go(tmp_path / "two", commons, inat, lists=lists, previous=first.catalog, eod_version="eod-2")
    assert result.ok
    assert result.catalog is not None and set(result.catalog.regions) == {"us-ri", "us-dc"}
    assert any(f.source == "gbif" and "us-dc" in f.error for f in result.report.source_failures)


def test_no_verify_is_reported_loudly_in_the_build_report(tmp_path: Path):
    commons, inat = full_sources()
    result, _, _ = go(tmp_path / "out", commons, inat, verify=False)
    assert result.catalog is not None and all(e.audio == [] for e in result.catalog.species.entries.values())
    assert "AUDIO NOT VERIFIED" in (tmp_path / "out" / "build-report.md").read_text(encoding="utf-8")


def test_dataset_credits_say_ebird_gives_the_english_names_and_ioc_the_scientific_ones():
    from avianki.catalog.build import dataset_credits

    ebird, ioc = dataset_credits()
    assert ebird.text == "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF"
    assert ebird.modifications == "filtered and ranked by region; English species names"
    assert ioc.text == "IOC World Bird List (Gill, Donsker and Rasmussen, eds.), for scientific names"
    assert ioc.modifications == "matched to GBIF taxa"


def test_a_source_s_notes_land_in_the_build_report():
    class Noting(FakeSource):
        def notes(self) -> list[str]:
            return ["xeno-canto: XC_API_KEY is not set; Commons audio candidates keep their default order (ADR 0031)"]

    commons = Noting("commons")
    _, inat = full_sources()
    for sid in IDS:
        commons.add(sid, PHOTO, f"{sid}-cp")
        commons.add(sid, AUDIO, f"{sid}-ca")
    built = species_build(commons, inat)
    assert sum("XC_API_KEY is not set" in n for n in built.report.notes) == 1
