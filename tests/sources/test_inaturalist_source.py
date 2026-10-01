"""Tests for avianki.sources.inaturalist.INaturalistSource: replayed trimmed responses and synthetic
fakes, no network."""

from __future__ import annotations

from typing import Any

import pytest
from inat_fakes import (
    COMMON,
    CORMORANT,
    MILLERBIRD,
    OLD_NAME,
    TAXA,
    TODAY,
    WHIMBREL,
    InatSession,
    counts_page,
    load,
    make_client,
    observation,
    page,
    species_table,
)

from avianki.core.http import HttpError, Limits, SourceError
from avianki.core.licences import licence_url
from avianki.sources.contract import AssetKind, AssetSource, Candidate
from avianki.sources.inaturalist import PLAUSIBILITY_MIN_RATIO, INaturalistSource, PlausibilityFlag
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

FILE = "https://inaturalist-open-data.s3.amazonaws.com/photos/1001/large.jpg"


def make(routes: dict[str, Any] | None = None, *, files=None, table=None, expected=None, cache_dir=None, **kw):
    base: dict[str, Any] = {"/taxa": TAXA}
    session = InatSession(base | (routes or {}), files)
    source = INaturalistSource(make_client(session, cache_dir), table or species_table(), expected_counts=expected,
                               today=lambda: TODAY, **kw)
    return source, session


def cormorant_photos(**routes: Any):
    return make({"/observations": load("observations_photos_nannopterum_auritum.json"), **routes})


def cormorant_sounds(**routes: Any):
    return make({"/observations": load("observations_sounds_nannopterum_auritum.json"), **routes})


# ── contract ─────────────────────────────────────────────────────────────────


def test_declares_what_it_supplies_and_its_polite_limits():
    source, _ = make()
    assert isinstance(source, AssetSource)
    assert source.name == "inaturalist"
    assert source.supplies == {AssetKind.PHOTO, AssetKind.AUDIO}
    assert source.republishable is True
    assert source.limits == Limits(1, 1, 10_000, None)


def test_an_unsupplied_kind_is_a_programming_error():
    source, session = make()
    with pytest.raises(ValueError, match="description"):
        source.candidates([CORMORANT], AssetKind.DESCRIPTION, 3)
    assert session.calls == []


# ── taxon resolution ─────────────────────────────────────────────────────────


def test_taxa_resolve_by_exact_name_and_are_asked_for_active_bird_species():
    source, session = make()
    assert source.resolve_taxa([MILLERBIRD, WHIMBREL]) == {MILLERBIRD: 116756, WHIMBREL: 3901}
    # taxon_id 3 is Aves: unrestricted, a short name like "Alle alle" is buried under fuzzy matches.
    assert session.params_for("/taxa")[0] == {"q": "Acrocephalus familiaris", "taxon_id": 3, "rank": "species",
                                              "is_active": "true", "per_page": 30, "locale": "en"}
    assert source.resolution_methods() == {MILLERBIRD: "exact", WHIMBREL: "exact"}


def test_a_short_name_is_found_among_the_fuzzy_matches():
    dovekie = SpeciesRow(id="alle-alle", sci_name="Alle alle", common_name="Dovekie")
    source, _ = make(table=species_table(dovekie))
    assert source.resolve_taxa(["alle-alle"]) == {"alle-alle": 4524}


def test_a_synonym_resolves_to_the_taxon_inaturalist_now_uses():
    old = SpeciesRow(id=OLD_NAME, sci_name="Phalacrocorax auritus", common_name=COMMON)
    source, _ = make(table=species_table(old))
    assert source.resolve_taxa([OLD_NAME]) == {OLD_NAME: 1454382}
    assert source.resolution_methods() == {OLD_NAME: "synonym"}


def test_the_lumped_species_does_not_take_the_split_species_taxon():
    source, _ = make()
    assert source.resolve_taxa([WHIMBREL]) == {WHIMBREL: 3901}  # not 1188213, Hudsonian Whimbrel


def test_a_species_with_no_taxon_is_absent_not_an_error():
    ghost = SpeciesRow(id="ghost-bird", sci_name="Ghostus birdus", common_name="Ghost Bird")
    source, _ = make(table=species_table(ghost))
    assert source.resolve_taxa([ghost.id, MILLERBIRD]) == {MILLERBIRD: 116756}
    assert source.resolution_methods()[ghost.id] == "none"


def test_resolution_is_remembered_within_a_run():
    source, session = make()
    source.resolve_taxa([MILLERBIRD, MILLERBIRD])
    source.resolve_taxa([MILLERBIRD])
    assert session.paths() == ["/taxa"]


def test_an_id_already_in_the_table_is_used_without_a_lookup():
    row = SpeciesRow(id=MILLERBIRD, sci_name="Acrocephalus familiaris", common_name="Millerbird", inat_taxon_id=116756)
    source, session = make(table=SpeciesTable([row]))
    assert source.resolve_taxa([MILLERBIRD]) == {MILLERBIRD: 116756}
    assert source.resolution_methods() == {MILLERBIRD: "table"}
    assert session.calls == []


def test_two_species_landing_on_one_taxon_keep_only_the_exact_name():
    old = SpeciesRow(id=OLD_NAME, sci_name="Phalacrocorax auritus", common_name=COMMON)
    source, _ = make(table=species_table(old))
    assert source.resolve_taxa([OLD_NAME, CORMORANT]) == {CORMORANT: 1454382}


def test_two_synonyms_on_one_taxon_keep_neither():
    # Two of our names both reach the cormorant only through synonyms; neither may claim it.
    old = SpeciesRow(id=OLD_NAME, sci_name="Phalacrocorax auritus", common_name=COMMON)
    twin = SpeciesRow(id="phalacrocorax-twin", sci_name="Phalacrocorax twinus", common_name="Twin Cormorant")
    payload = load("taxa_phalacrocorax_auritus.json")
    twin_payload = {**payload, "results": [{**payload["results"][0], "matched_term": "Phalacrocorax twinus"}]}
    session = InatSession({"/taxa": lambda p: payload if p["q"] == old.sci_name else twin_payload})
    source = INaturalistSource(make_client(session), species_table(old, twin))
    assert source.resolve_taxa([OLD_NAME, twin.id]) == {}


def test_an_unknown_species_id_is_a_programming_error():
    source, _ = make()
    with pytest.raises(ValueError, match="unknown species"):
        source.resolve_taxa(["no-such-bird"])


def test_a_failed_lookup_raises_never_empty():
    source, _ = make({"/taxa": (500, {"error": "down"})})
    with pytest.raises(HttpError):
        source.resolve_taxa([MILLERBIRD])


def test_a_malformed_taxa_response_raises():
    source, _ = make({"/taxa": {"nope": []}})
    with pytest.raises(SourceError):
        source.resolve_taxa([MILLERBIRD])


# ── plausibility (ADR 0008) ──────────────────────────────────────────────────


def counts_route(counts: dict[int, int]):
    return {"/observations/species_counts": lambda p: counts_page(counts)}


def test_a_taxon_far_below_the_expected_count_is_flagged_and_dropped():
    # Measured live: iNaturalist's Numenius phaeopus (Eurasian only) has 9 research-grade North
    # American observations; EOD's lumped Whimbrel has 657,609 North American records.
    source, session = make(counts_route({3901: 9, 116756: 60}), expected={WHIMBREL: 657_609, MILLERBIRD: 50})
    assert source.resolve_taxa([WHIMBREL, MILLERBIRD]) == {MILLERBIRD: 116756}
    assert source.flagged() == [PlausibilityFlag(WHIMBREL, 3901, 9, 657_609)]
    assert source.flagged()[0].ratio == pytest.approx(9 / 657_609)
    assert source.na_ratios()[WHIMBREL] == pytest.approx(9 / 657_609)


def test_the_threshold_is_calibrated_not_the_adrs_five_percent():
    # Measured live over 28 species: 18 correct mappings sat below 5% (median 2.8%; the lowest,
    # Crested Myna, was 3 observations against 2,514 records), and the one wrong mapping, the
    # Whimbrel above, sat at 0.0014%. The default has to fall between the two.
    assert 3 / 2514 > PLAUSIBILITY_MIN_RATIO > 9 / 657_609
    myna = SpeciesRow(id="acridotheres-cristatellus", sci_name="Acridotheres cristatellus", common_name="Crested Myna",
                      inat_taxon_id=14872)
    source, _ = make(counts_route({14872: 3}), table=SpeciesTable([myna]), expected={myna.id: 2514})
    assert source.resolve_taxa([myna.id]) == {myna.id: 14872}
    assert source.flagged() == []


def test_the_check_is_one_batched_north_american_research_grade_count():
    source, session = make(counts_route({3901: 500, 116756: 60}), expected={WHIMBREL: 1000, MILLERBIRD: 100})
    source.resolve_taxa([WHIMBREL, MILLERBIRD])
    assert session.paths().count("/observations/species_counts") == 1
    assert session.params_for("/observations/species_counts")[0] == {
        "taxon_id": "3901,116756", "place_id": "1,6712", "quality_grade": "research", "rank": "species",
        "per_page": 500, "locale": "en"}
    assert source.flagged() == []


def test_the_ratio_boundary_passes_and_just_under_fails():
    source, _ = make(counts_route({3901: 2, 116756: 1}), expected={WHIMBREL: 10_000, MILLERBIRD: 10_000})
    assert source.resolve_taxa([WHIMBREL, MILLERBIRD]) == {WHIMBREL: 3901}  # 2 / 10,000 is exactly 0.0002


def test_a_taxon_missing_from_the_counts_has_zero_observations():
    source, _ = make(counts_route({}), expected={WHIMBREL: 10})
    assert source.resolve_taxa([WHIMBREL]) == {}
    assert source.flagged()[0].na_count == 0


def test_species_without_an_expected_count_are_not_checked():
    source, session = make()
    assert source.resolve_taxa([WHIMBREL]) == {WHIMBREL: 3901}
    assert "/observations/species_counts" not in session.paths()


def test_the_threshold_can_be_recalibrated():
    source, _ = make(counts_route({3901: 9}), expected={WHIMBREL: 657_609}, min_ratio=0.00001)
    assert source.resolve_taxa([WHIMBREL]) == {WHIMBREL: 3901}


def test_counts_are_fetched_in_batches_and_only_once_per_species():
    rows = [SpeciesRow(id=f"bird-{chr(97 + i // 26)}{chr(97 + i % 26)}", sci_name=f"Genus sp{chr(97 + i // 26)}{chr(97 + i % 26)}",
                       common_name=f"Bird {i}") for i in range(120)]
    taxon_of = {r.sci_name: 10_000 + i for i, r in enumerate(rows)}

    def taxa(p: dict[str, Any]) -> dict[str, Any]:
        name = p["q"]
        return {"total_results": 1, "results": [{"id": taxon_of[name], "name": name, "rank": "species",
                                                 "is_active": True, "iconic_taxon_name": "Aves"}]}

    session = InatSession({"/taxa": taxa, "/observations/species_counts":
                           lambda p: counts_page({int(t): 100 for t in p["taxon_id"].split(",")})})
    source = INaturalistSource(make_client(session), SpeciesTable(rows), expected_counts={r.id: 100 for r in rows})
    assert len(source.resolve_taxa([r.id for r in rows])) == 120
    assert session.paths().count("/observations/species_counts") == 3  # 50 + 50 + 20
    source.resolve_taxa([r.id for r in rows])
    assert session.paths().count("/observations/species_counts") == 3


def test_a_failed_count_lookup_raises():
    source, _ = make({"/observations/species_counts": (503, {})}, expected={WHIMBREL: 10})
    with pytest.raises(SourceError):
        source.resolve_taxa([WHIMBREL])


def test_a_flagged_species_gets_no_candidates_and_no_observation_request():
    source, session = make(counts_route({3901: 9}), expected={WHIMBREL: 657_609})
    assert source.candidates([WHIMBREL], AssetKind.PHOTO, 3) == {WHIMBREL: []}
    assert "/observations" not in session.paths()


# ── photo candidates ─────────────────────────────────────────────────────────


def test_photo_candidates_are_gated_and_ranked_by_agreements():
    source, session = cormorant_photos()
    got = source.candidates([CORMORANT], AssetKind.PHOTO, 3)[CORMORANT]
    assert [(c.token, c.agreements) for c in got] == [
        ("P148352422:255454786", 14),
        ("P15750943:23524935", 10),
        ("P170387479:295517750", 6),
    ]
    assert all(c.kind is AssetKind.PHOTO and c.species_id == CORMORANT for c in got)
    assert [(c.width, c.height) for c in got] == [(1024, 768)] * 3


def test_only_the_wanted_number_of_photos_is_returned_and_all_five_pass_the_gates_when_asked():
    source, _ = cormorant_photos()
    assert len(source.candidates([CORMORANT], AssetKind.PHOTO, 2)[CORMORANT]) == 2
    everything = source.candidates([CORMORANT], AssetKind.PHOTO, 50)[CORMORANT]
    assert [c.token.split(":")[0] for c in everything] == ["P148352422", "P15750943", "P170387479", "P103834763", "P27656643"]


def test_the_photo_query_asks_for_research_grade_wild_licensed_species_level_observations():
    source, session = cormorant_photos()
    source.candidates([CORMORANT], AssetKind.PHOTO, 3)
    (params,) = session.params_for("/observations")
    assert params == {
        "photos": "true", "photo_license": "cc0,cc-by,cc-by-sa", "per_page": 10, "taxon_id": 1454382,
        "quality_grade": "research", "captive": "false", "lrank": "species", "hrank": "species",
        "order_by": "votes", "locale": "en"}


def test_the_photo_record_carries_everything_the_credit_needs():
    source, _ = cormorant_photos()
    c = source.candidates([CORMORANT], AssetKind.PHOTO, 1)[CORMORANT][0]
    r = c.record
    assert r.source == "inaturalist"
    assert r.source_asset_id == "255454786"
    assert r.source_url == "https://www.inaturalist.org/photos/255454786"
    assert r.file_url == "https://inaturalist-open-data.s3.amazonaws.com/photos/255454786/large.jpg"
    assert (r.licence_id, r.licence_url) == ("CC-BY-4.0", licence_url("CC-BY-4.0"))
    assert r.licence_version_assumed is True
    assert r.creator == "Peter Abrahamsen"
    assert r.creator_url == "https://www.inaturalist.org/people/rainhead"
    assert r.attribution_text and "Peter Abrahamsen" in r.attribution_text
    assert r.title == f"{COMMON} (Nannopterum auritum)"  # required because the licence version is assumed
    assert r.retrieved_at == TODAY
    assert r.missing_required_fields() == []


def test_a_cc0_photo_is_versioned_and_still_credited():
    obs = observation(1000, licence="cc0")
    obs["photos"][0]["attribution"] = "no rights reserved, uploaded by Bea Birder"
    source, _ = make({"/observations": page([obs])})
    (c,) = source.candidates([CORMORANT], AssetKind.PHOTO, 3)[CORMORANT]
    assert (c.record.licence_id, c.record.licence_version_assumed) == ("CC0-1.0", False)
    assert c.record.creator == "Bea Birder"
    assert c.record.missing_required_fields() == []


def test_ties_prefer_the_more_permissive_licence():
    a = observation(1000, agreements=5, licence="cc-by-sa")
    b = observation(2000, agreements=5, licence="cc0")
    c = observation(3000, agreements=5, licence="cc-by")
    source, _ = make({"/observations": page([a, b, c])})
    got = source.candidates([CORMORANT], AssetKind.PHOTO, 3)[CORMORANT]
    assert [x.record.licence_id for x in got] == ["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"]


def test_a_response_that_ignores_our_filters_is_still_gated():
    bad = [observation(1000, licence="cc-by-nc"), observation(2000, quality_grade="needs_id"),
           observation(3000, captive=True), observation(4000, taxon_id=999), observation(5000, agreements=1)]
    source, _ = make({"/observations": page(bad)})
    assert source.candidates([CORMORANT], AssetKind.PHOTO, 5) == {CORMORANT: []}


def test_no_observations_is_absence_not_failure():
    source, _ = make({"/observations": page([])})
    assert source.candidates([CORMORANT], AssetKind.PHOTO, 3) == {CORMORANT: []}


def test_every_requested_species_is_answered_even_without_a_taxon():
    ghost = SpeciesRow(id="ghost-bird", sci_name="Ghostus birdus", common_name="Ghost Bird")
    source, session = make({"/observations": page([observation(1000)])}, table=species_table(ghost))
    got = source.candidates([ghost.id, CORMORANT], AssetKind.PHOTO, 3)
    assert got[ghost.id] == []
    assert [c.token for c in got[CORMORANT]] == ["P1000:1001"]
    assert len(session.params_for("/observations")) == 1


def test_a_limit_of_zero_asks_for_nothing():
    source, session = make()
    assert source.candidates([CORMORANT], AssetKind.PHOTO, 0) == {CORMORANT: []}
    assert "/observations" not in session.paths()


def test_an_incomplete_credit_is_not_offered():
    obs = observation(1000)
    obs["user"].update(name="", login="")
    obs["photos"][0]["attribution"] = None
    good = observation(2000)
    source, _ = make({"/observations": page([obs, good])})
    assert [c.token for c in source.candidates([CORMORANT], AssetKind.PHOTO, 3)[CORMORANT]] == ["P2000:2001"]


def test_an_http_failure_raises_never_empty():
    source, _ = make({"/observations": (500, {})})
    with pytest.raises(SourceError):
        source.candidates([CORMORANT], AssetKind.PHOTO, 3)


def test_a_malformed_observations_response_raises():
    source, _ = make({"/observations": {"results": "nope"}})
    with pytest.raises(SourceError):
        source.candidates([CORMORANT], AssetKind.PHOTO, 3)


# ── audio candidates ─────────────────────────────────────────────────────────


def test_audio_candidates_from_recorded_observations():
    source, session = cormorant_sounds()
    got = source.candidates([CORMORANT], AssetKind.AUDIO, 3)[CORMORANT]
    assert len(got) == 3
    assert all(c.kind is AssetKind.AUDIO and c.width is None and c.height is None for c in got)
    # Every recorded observation has one agreement, so the three cc0 recordings lead.
    assert [c.token for c in got] == ["S3381847:6918", "S131386681:522707", "S102956779:337074"]
    (params,) = session.params_for("/observations")
    assert params["sounds"] == "true"
    assert params["sound_license"] == "cc0,cc-by,cc-by-sa"
    assert params["quality_grade"] == "research"
    assert params["captive"] == "false"
    assert "photos" not in params


def test_audio_records_use_the_observation_page_and_the_sounds_own_licence():
    source, _ = cormorant_sounds()
    got = {c.token: c for c in source.candidates([CORMORANT], AssetKind.AUDIO, 8)[CORMORANT]}
    assert len(got) == 8
    c = got["S313618956:1635136"]
    assert c.record.source_url == "https://www.inaturalist.org/observations/313618956"
    assert c.record.file_url.startswith("https://static.inaturalist.org/sounds/1635136.m4a")
    assert c.record.licence_id == "CC-BY-4.0"
    assert c.record.creator == "Justin Donahue"
    assert c.record.missing_required_fields() == []
    assert got["S3381847:6918"].record.licence_id == "CC0-1.0"  # a recorded cc0 sound


def test_audio_is_ranked_by_agreements():
    a, b, c = observation(1000, agreements=1), observation(2000, agreements=7), observation(3000, agreements=3)
    source, _ = make({"/observations": page([a, b, c])})
    got = source.candidates([CORMORANT], AssetKind.AUDIO, 3)[CORMORANT]
    assert [x.agreements for x in got] == [7, 3, 1]


# ── fetch ────────────────────────────────────────────────────────────────────


def candidate_for(source: INaturalistSource, kind: AssetKind = AssetKind.PHOTO) -> Candidate:
    return source.candidates([CORMORANT], kind, 1)[CORMORANT][0]


def test_fetch_returns_the_bytes_and_type():
    url = "https://inaturalist-open-data.s3.amazonaws.com/photos/255454786/large.jpg"
    source, session = make({"/observations": load("observations_photos_nannopterum_auritum.json")},
                           files={url: (200, b"\xff\xd8jpeg", "image/jpeg")})
    c = candidate_for(source)
    got = source.fetch(c)
    assert (got.data, got.content_type, got.candidate, got.record) == (b"\xff\xd8jpeg", "image/jpeg", c, c.record)
    assert session.calls[-1][0] == url


def test_fetch_ignores_a_content_type_parameter():
    url = "https://static.inaturalist.org/sounds/6918.wav?1502902272"
    source, _ = make({"/observations": load("observations_sounds_nannopterum_auritum.json")},
                     files={url: (200, b"audio", "Audio/Wav; charset=binary")})
    assert source.fetch(candidate_for(source, AssetKind.AUDIO)).content_type == "audio/wav"


@pytest.mark.parametrize(("status", "body", "ctype"), [
    (200, b"<html>login</html>", "text/html"),
    (200, b"x", ""),
    (200, b"", "image/jpeg"),
    (404, b"gone", "text/plain"),
    (403, b"denied", "image/jpeg"),
])
def test_fetch_failures_raise(status, body, ctype):
    url = "https://inaturalist-open-data.s3.amazonaws.com/photos/255454786/large.jpg"
    source, _ = make({"/observations": load("observations_photos_nannopterum_auritum.json")},
                     files={url: (status, body, ctype)})
    with pytest.raises(SourceError):
        source.fetch(candidate_for(source))


def test_a_photo_url_that_serves_audio_is_refused():
    url = "https://inaturalist-open-data.s3.amazonaws.com/photos/255454786/large.jpg"
    source, _ = make({"/observations": load("observations_photos_nannopterum_auritum.json")},
                     files={url: (200, b"x", "audio/mp4")})
    with pytest.raises(SourceError, match="expected photo"):
        source.fetch(candidate_for(source))


def test_media_is_never_cached_but_api_answers_are(tmp_path):
    url = "https://inaturalist-open-data.s3.amazonaws.com/photos/255454786/large.jpg"
    source, session = make({"/observations": load("observations_photos_nannopterum_auritum.json")},
                           files={url: (200, b"jpeg", "image/jpeg")}, cache_dir=tmp_path)
    c = candidate_for(source)
    source.fetch(c)
    source.fetch(c)
    assert session.paths().count(url) == 2
    fresh = INaturalistSource(make_client(session, tmp_path), species_table(), today=lambda: TODAY)
    fresh.candidates([CORMORANT], AssetKind.PHOTO, 1)
    assert session.paths().count("/observations") == 1  # the second run replayed it from the cache
    assert session.paths().count("/taxa") == 1


# ── pins ─────────────────────────────────────────────────────────────────────


def pin_source(obs: dict[str, Any] | None, obs_id: int = 1000, **kw: Any):
    body = page([obs] if obs else [])
    return make({f"/observations/{obs_id}": body}, **kw)


def test_a_photo_pin_round_trips_to_the_same_candidate():
    source, _ = cormorant_photos(**{"/observations/148352422": load("observation_148352422.json")})
    c = candidate_for(source)
    assert c.token == "P148352422:255454786"
    fresh, _ = make({"/observations/148352422": load("observation_148352422.json")})
    assert fresh.resolve_pin(c.token) == c


def test_a_sound_pin_round_trips_to_the_same_candidate():
    source, _ = cormorant_sounds()
    c = candidate_for(source, AssetKind.AUDIO)
    assert c.token == "S3381847:6918"
    fresh, session = make({"/observations/3381847": load("observation_3381847.json")})
    assert fresh.resolve_pin(c.token) == c
    assert session.params_for("/observations/3381847") == [{"locale": "en"}]


def test_the_recorded_single_observation_pin_resolves():
    source, _ = make({"/observations/3381847": load("observation_3381847.json")})
    c = source.resolve_pin("S3381847:6918")
    assert (c.species_id, c.record.licence_id) == (CORMORANT, "CC0-1.0")


def test_a_pin_is_exempt_from_the_agreement_floor_only():
    source, _ = pin_source(observation(1000, agreements=1))
    assert source.resolve_pin("P1000:1001").agreements == 1
    strict, _ = make({"/observations": page([observation(1000, agreements=1)])})
    assert strict.candidates([CORMORANT], AssetKind.PHOTO, 3) == {CORMORANT: []}


def test_a_pin_still_needs_an_allowlisted_licence():
    source, _ = pin_source(observation(1000, licence="cc-by-nc"))
    with pytest.raises(SourceError, match="allowlist"):
        source.resolve_pin("P1000:1001")


@pytest.mark.parametrize("change", [
    {"quality_grade": "casual"}, {"captive": True}, {"spam": True},
])
def test_a_pin_to_an_observation_that_lost_its_standing_is_refused(change):
    source, _ = pin_source(observation(1000, **change))
    with pytest.raises(SourceError, match="no longer eligible"):
        source.resolve_pin("P1000:1001")


@pytest.mark.parametrize("token", ["", "1000:1001", "X1000:1001", "P1000", "P1000:", "Pabc:1", "P1000:1001:2", "P-1:2"])
def test_malformed_pin_tokens_raise(token):
    source, session = make()
    with pytest.raises(SourceError, match="malformed pin"):
        source.resolve_pin(token)
    assert session.calls == []


def test_a_pin_to_a_deleted_observation_raises():
    source, _ = pin_source(None)
    with pytest.raises(SourceError, match="no longer resolves"):
        source.resolve_pin("P1000:1001")
    gone, _ = make({"/observations/1000": (404, {})})
    with pytest.raises(SourceError):
        gone.resolve_pin("P1000:1001")


def test_a_pin_to_a_photo_no_longer_on_the_observation_raises():
    source, _ = pin_source(observation(1000))
    with pytest.raises(SourceError, match="not found"):
        source.resolve_pin("P1000:4242")
    with pytest.raises(SourceError, match="not found"):
        source.resolve_pin("S1000:4242")


def test_a_pin_whose_observation_was_reidentified_elsewhere_is_refused():
    obs = observation(1000, taxon_id=555)
    obs["taxon"]["name"] = "Someother bird"
    source, _ = pin_source(obs)
    with pytest.raises(SourceError, match="not a known species"):
        source.resolve_pin("P1000:1001")


def test_a_pin_finds_its_species_by_name_when_it_was_not_resolved_first():
    obs = observation(1000, taxon_id=777)
    obs["taxon"]["name"] = "nannopterum  AURITUM"
    source, _ = pin_source(obs)
    assert source.resolve_pin("P1000:1001").species_id == CORMORANT


def test_a_pin_finds_its_species_by_a_table_taxon_id():
    row = SpeciesRow(id=MILLERBIRD, sci_name="Acrocephalus familiaris", common_name="Millerbird", inat_taxon_id=116756)
    obs = observation(1000, taxon_id=116756)
    obs["taxon"]["name"] = "Renamed familiaris"
    source, _ = pin_source(obs, table=SpeciesTable([row]))
    assert source.resolve_pin("P1000:1001").species_id == MILLERBIRD


def test_a_pin_uses_the_observation_id_because_there_is_no_photo_endpoint():
    source, session = pin_source(observation(1000))
    source.resolve_pin("P1000:1001")
    assert session.paths() == ["/observations/1000"]
