"""Tests for avianki.sources.inaturalist.parse: pure gating over trimmed recorded responses and synthetic
observations, no network."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from inat_fakes import load, observation, page

from avianki.core.http import SourceError
from avianki.sources.contract import AssetKind
from avianki.sources.inaturalist import parse

CORMORANT_TAXON = 1454382


def taxon(tid: int, name: str, *, matched: str | None = None, rank: str = "species", active: bool = True,
          iconic: str = "Aves") -> dict[str, Any]:
    t = {"id": tid, "name": name, "rank": rank, "is_active": active, "iconic_taxon_name": iconic}
    if matched is not None:
        t["matched_term"] = matched
    return t


def taxa(*results: dict[str, Any]) -> dict[str, Any]:
    return {"total_results": len(results), "page": 1, "per_page": 5, "results": list(results)}


# ── taxa ─────────────────────────────────────────────────────────────────────


def test_exact_name_match():
    got = parse.pick_taxon("Acrocephalus familiaris", load("taxa_acrocephalus_familiaris.json"))
    assert got == parse.TaxonMatch(116756, "Acrocephalus familiaris", "exact")


def test_synonym_match_through_matched_term():
    # Recorded: iNaturalist answers the old name Phalacrocorax auritus with Nannopterum auritum.
    got = parse.pick_taxon("Phalacrocorax auritus", load("taxa_phalacrocorax_auritus.json"))
    assert got == parse.TaxonMatch(1454382, "Nannopterum auritum", "synonym")


def test_a_split_off_subspecies_is_not_the_lumped_species():
    # Recorded: "Numenius phaeopus" also returns N. hudsonicus, found through the trinomial
    # "Numenius phaeopus hudsonicus". Only the taxon actually named phaeopus is Numenius phaeopus.
    payload = load("taxa_numenius_phaeopus.json")
    assert {t["name"] for t in payload["results"]} == {"Numenius phaeopus", "Numenius hudsonicus"}
    assert parse.pick_taxon("Numenius phaeopus", payload).taxon_id == 3901
    assert parse.pick_taxon("Numenius hudsonicus", payload).taxon_id == 1188213


def test_a_fuzzy_result_list_yields_only_the_named_bird():
    # Recorded: the Aves-restricted search for "Alle alle" also returns Allenia fusca, Porphyrio alleni...
    payload = load("taxa_alle_alle.json")
    assert len(payload["results"]) > 1
    assert parse.pick_taxon("Alle alle", payload) == parse.TaxonMatch(4524, "Alle alle", "exact")


def test_the_exact_name_beats_a_synonym_claim():
    payload = taxa(taxon(1, "Genus new", matched="Genus old"), taxon(2, "Genus old"))
    assert parse.pick_taxon("Genus old", payload) == parse.TaxonMatch(2, "Genus old", "exact")


def test_name_comparison_ignores_case_and_spacing():
    assert parse.pick_taxon("acrocephalus   FAMILIARIS", taxa(taxon(5, "Acrocephalus familiaris"))).taxon_id == 5


@pytest.mark.parametrize("bad", [
    taxon(1, "Genus sp", rank="genus"),
    taxon(1, "Genus sp", active=False),
    taxon(1, "Genus sp", iconic="Mammalia"),
    taxon(1, "Genus other", matched="Genus sp", iconic="Insecta"),
    taxon(1, "Genus sp", matched="Genus sp", rank="subspecies"),
])
def test_only_active_bird_species_qualify(bad):
    assert parse.pick_taxon("Genus sp", taxa(bad)) is None


def test_two_live_taxa_claiming_one_name_is_no_match():
    assert parse.pick_taxon("Genus sp", taxa(taxon(1, "Genus sp"), taxon(2, "Genus sp"))) is None
    both = taxa(taxon(1, "Genus a", matched="Genus sp"), taxon(2, "Genus b", matched="Genus sp"))
    assert parse.pick_taxon("Genus sp", both) is None


def test_no_results_is_no_match_not_an_error():
    assert parse.pick_taxon("Genus sp", taxa()) is None


@pytest.mark.parametrize("payload", [None, [], {}, {"results": "x"}, {"results": [1]},
                                     {"results": [{"id": "1", "name": "x"}]}])
def test_malformed_taxa_raise(payload):
    with pytest.raises(SourceError):
        parse.pick_taxon("Genus sp", payload)


def test_species_counts():
    assert parse.species_counts(load("species_counts_numenius_phaeopus.json")) == {3901: 9}


def test_species_counts_absent_taxon_is_the_callers_zero():
    assert parse.species_counts({"total_results": 0, "results": []}) == {}


@pytest.mark.parametrize("payload", [
    {"total_results": 3, "results": [{"count": 1, "taxon": {"id": 1}}]},  # truncated
    {"results": []},
    {"total_results": 1, "results": [{"count": "1", "taxon": {"id": 1}}]},
    {"total_results": 1, "results": [{"count": 1, "taxon": None}]},
    {"total_results": 1, "results": [{"count": -1, "taxon": {"id": 1}}]},
])
def test_malformed_or_truncated_species_counts_raise(payload):
    with pytest.raises(SourceError):
        parse.species_counts(payload)


@pytest.mark.parametrize(("na", "expected", "ok"), [
    (5, 100, True),  # exactly the ratio passes
    (4, 100, False),
    (0, 100, False),
    (0, 0, True),  # an expected count of zero says nothing
    (0, -1, True),
])
def test_is_plausible(na, expected, ok):
    assert parse.is_plausible(na, expected, 0.05) is ok


# ── photos ───────────────────────────────────────────────────────────────────


def photo(obs: dict[str, Any], **kw: Any):
    return parse.photo_asset(obs, CORMORANT_TAXON, **kw)


def test_a_good_photo_is_found():
    got = photo(observation(1000, agreements=4))
    assert isinstance(got, parse.Found)
    assert got.kind is AssetKind.PHOTO
    assert (got.observation_id, got.asset_id, got.agreements) == (1000, 1001, 4)
    assert got.file_url == "https://inaturalist-open-data.s3.amazonaws.com/photos/1001/large.jpg"
    assert got.source_url == "https://www.inaturalist.org/photos/1001"
    assert (got.licence_id, got.licence_version_assumed) == ("CC-BY-4.0", True)
    assert (got.creator, got.creator_url) == ("Bea Birder", "https://www.inaturalist.org/people/birder")
    assert (got.width, got.height) == (1024, 768)  # the large rendition, not the original


def rejected(mutate):
    obs = observation(1000)
    mutate(obs)
    got = photo(obs)
    assert isinstance(got, parse.Reject)
    return got.reason


@pytest.mark.parametrize(("mutate", "why"), [
    (lambda o: o.update(quality_grade="needs_id"), "quality_grade"),
    (lambda o: o.update(captive=True), "captive"),
    (lambda o: o.pop("captive"), "captive"),
    (lambda o: o.update(num_identification_agreements=1), "agreements"),
    (lambda o: o.update(num_identification_agreements=None), "agreements"),
    (lambda o: o["taxon"].update(id=999), "is not species taxon"),
    (lambda o: o["taxon"].update(rank="subspecies"), "is not species taxon"),
    (lambda o: o.update(identifications_most_disagree=True), "disagree"),
    (lambda o: o.update(spam=True), "spam"),
    (lambda o: o.update(photos=[]), "no photos"),
    (lambda o: o["photos"][0].update(license_code="cc-by-nc"), "allowlist"),
    (lambda o: o["photos"][0].update(license_code="cc-by-nd"), "allowlist"),
    (lambda o: o["photos"][0].update(license_code=None), "allowlist"),
    (lambda o: o["photos"][0].update(hidden=True), "hidden or flagged"),
    (lambda o: o["photos"][0].update(flags=[{"flag": "copyright"}]), "hidden or flagged"),
    (lambda o: o["photos"][0].update(moderator_actions=[{"action": "hide"}]), "hidden or flagged"),
    (lambda o: o["photos"][0].update(url="https://example.com/photos/1001/square.jpg"), "photo url"),
    (lambda o: o["photos"][0].update(url="https://static.inaturalist.org/photos/1001/square.gif"), "photo url"),
    (lambda o: o["photos"][0].update(original_dimensions={"width": 799, "height": 500}), "800 px"),
    (lambda o: o["user"].update(suspended=True), "flagged"),
    (lambda o: (o.update(user={}), o["photos"][0].update(attribution=None)), "creator"),
])
def test_photo_gates(mutate, why):
    assert why in rejected(mutate)


def test_only_the_lead_photo_is_considered():
    obs = observation(1000)
    obs["photos"][0]["license_code"] = "cc-by-nc"
    obs["photos"].append(copy.deepcopy(observation(1000)["photos"][0]) | {"id": 5000, "url": obs["photos"][0]["url"].replace("1001", "5000")})
    assert isinstance(photo(obs), parse.Reject)


def test_the_photos_own_licence_decides_not_the_observations():
    obs = observation(1000, license_code="cc-by-nc")  # the observation's data licence, irrelevant
    assert isinstance(photo(obs), parse.Found)


def test_the_size_check_uses_the_long_side_and_tolerates_missing_dimensions():
    portrait = observation(1000)
    portrait["photos"][0]["original_dimensions"] = {"width": 1200, "height": 1800}
    got = photo(portrait)
    assert isinstance(got, parse.Found)
    assert (got.width, got.height) == (683, 1024)
    unknown = observation(1000)
    del unknown["photos"][0]["original_dimensions"]
    got = photo(unknown)
    assert isinstance(got, parse.Found)
    assert (got.width, got.height) == (None, None)


def test_a_small_original_is_not_upscaled():
    small = observation(1000)
    small["photos"][0]["original_dimensions"] = {"width": 900, "height": 800}
    got = photo(small)
    assert isinstance(got, parse.Found)
    assert (got.width, got.height) == (900, 800)


def test_photo_extension_is_kept_and_the_large_rendition_is_used():
    png = observation(1000)
    png["photos"][0]["url"] = "https://inaturalist-open-data.s3.amazonaws.com/photos/1001/square.PNG"
    assert photo(png).file_url.endswith("/photos/1001/large.png")


def test_a_pin_may_lift_the_agreement_floor_and_pick_the_photo():
    obs = observation(1000, agreements=1)
    second = copy.deepcopy(obs["photos"][0]) | {"id": 1500, "url": obs["photos"][0]["url"].replace("1001", "1500")}
    obs["photos"].append(second)
    assert isinstance(photo(obs), parse.Reject)
    got = photo(obs, min_agreements=None, photo_id=1500)
    assert isinstance(got, parse.Found)
    assert got.asset_id == 1500
    missing = photo(obs, min_agreements=None, photo_id=42)
    assert isinstance(missing, parse.Reject)


def test_the_pin_path_still_gates_the_licence():
    obs = observation(1000, agreements=1, licence="cc-by-nc")
    assert isinstance(photo(obs, min_agreements=None, photo_id=1001), parse.Reject)


def test_cc0_credits_the_observer_and_keeps_its_licence():
    obs = observation(1000, licence="cc0")
    obs["photos"][0]["attribution"] = "no rights reserved, uploaded by Bea Birder"
    got = photo(obs)
    assert isinstance(got, parse.Found)
    assert (got.licence_id, got.licence_version_assumed) == ("CC0-1.0", False)
    assert (got.creator, got.creator_url) == ("Bea Birder", "https://www.inaturalist.org/people/birder")


def test_the_credited_name_is_the_copyright_holders_not_the_observers():
    obs = observation(1000)
    obs["photos"][0]["attribution"] = "(c) Some Studio, some rights reserved (CC BY)"
    got = photo(obs)
    assert isinstance(got, parse.Found)
    assert got.creator == "Some Studio"
    assert got.creator_url is None  # the profile page is the observer's, not the studio's
    assert got.attribution_text == "(c) Some Studio, some rights reserved (CC BY)"


def test_an_observer_without_a_display_name_is_credited_by_login():
    obs = observation(1000)
    obs["user"]["name"] = ""
    obs["photos"][0]["attribution"] = None
    got = photo(obs)
    assert isinstance(got, parse.Found)
    assert (got.creator, got.creator_url) == ("birder", "https://www.inaturalist.org/people/birder")


def test_an_unsafe_login_gets_no_profile_link():
    obs = observation(1000)
    obs["user"].update(login="bad/../login", name="")
    obs["photos"][0]["attribution"] = None
    got = photo(obs)
    assert isinstance(got, parse.Found)
    assert got.creator_url is None


def test_recorded_photo_page_gates():
    obs = parse.observations(load("observations_photos_nannopterum_auritum.json"))
    outcomes = {o["id"]: parse.photo_asset(o, CORMORANT_TAXON) for o in obs}
    assert isinstance(outcomes[208623826], parse.Reject)  # a gif, and only 426 px
    assert "agreements" in outcomes[106714305].reason  # type: ignore[union-attr]
    assert outcomes[103834763].file_url.endswith("/photos/173884349/large.png")  # type: ignore[union-attr]
    kept = [o for o, r in outcomes.items() if isinstance(r, parse.Found)]
    assert kept == [148352422, 103834763, 15750943, 27656643, 170387479]


# ── sounds ───────────────────────────────────────────────────────────────────


def sound(obs: dict[str, Any], **kw: Any):
    return parse.sound_asset(obs, CORMORANT_TAXON, **kw)


def test_a_good_sound_is_found():
    got = sound(observation(2000, agreements=1))  # sounds have no agreement floor
    assert isinstance(got, parse.Found)
    assert got.kind is AssetKind.AUDIO
    assert (got.observation_id, got.asset_id) == (2000, 2002)
    assert got.file_url == "https://static.inaturalist.org/sounds/2002.m4a?1"
    assert got.source_url == "https://www.inaturalist.org/observations/2000"
    assert (got.width, got.height) == (None, None)


@pytest.mark.parametrize(("mutate", "why"), [
    (lambda o: o.update(quality_grade="casual"), "quality_grade"),
    (lambda o: o.update(captive=True), "captive"),
    (lambda o: o.update(sounds=[]), "no sounds"),
    (lambda o: o["sounds"][0].update(license_code="cc-by-nc-nd"), "allowlist"),
    (lambda o: o["sounds"][0].update(hidden=True), "hidden or flagged"),
    (lambda o: o["sounds"][0].update(file_content_type="text/html"), "content type"),
    (lambda o: o["sounds"][0].update(file_content_type=None), "content type"),
    (lambda o: o["sounds"][0].update(file_url="http://static.inaturalist.org/sounds/1.m4a"), "sound url"),
    (lambda o: o["sounds"][0].update(file_url="https://evil.example/sounds/1.m4a"), "sound url"),
    (lambda o: o["sounds"][0].update(file_url=None), "sound url"),
])
def test_sound_gates(mutate, why):
    obs = observation(2000)
    mutate(obs)
    got = sound(obs)
    assert isinstance(got, parse.Reject)
    assert why in got.reason


def test_the_first_usable_sound_wins():
    obs = observation(2000)
    obs["sounds"][0]["license_code"] = "cc-by-nc"
    obs["sounds"].append(observation(2000, sound_id=2900)["sounds"][0])
    got = sound(obs)
    assert isinstance(got, parse.Found)
    assert got.asset_id == 2900
    pinned = sound(obs, sound_id=2002)
    assert isinstance(pinned, parse.Reject)


def test_the_sounds_own_licence_decides_not_the_photos():
    # Recorded: observation 326733167 has a cc-by-nc-nd photo and a cc-by sound.
    obs = {o["id"]: o for o in parse.observations(load("observations_sounds_nannopterum_auritum.json"))}[326733167]
    assert obs["photos"][0]["license_code"] == "cc-by-nc-nd"
    got = sound(obs)
    assert isinstance(got, parse.Found)
    assert got.licence_id == "CC-BY-4.0"


def test_recorded_sound_page_yields_every_licensed_recording_in_the_three_audio_types():
    obs = parse.observations(load("observations_sounds_nannopterum_auritum.json"))
    found = [r for o in obs if isinstance(r := sound(o), parse.Found)]
    assert len(found) == len(obs) == 8
    assert {f.file_url.split("?")[0].rsplit(".", 1)[1] for f in found} == {"m4a", "mp3", "wav"}
    assert {f.licence_id for f in found} == {"CC-BY-4.0", "CC0-1.0"}


# ── ranking and shape ────────────────────────────────────────────────────────


def found(obs_id: int, agreements: int, licence: str) -> parse.Found:
    got = photo(observation(obs_id, agreements=agreements, licence=licence))
    assert isinstance(got, parse.Found)
    return got


def test_ranking_is_agreements_then_the_more_permissive_licence():
    a = found(1000, 3, "cc-by-sa")
    b = found(2000, 3, "cc-by")
    c = found(3000, 3, "cc0")
    d = found(4000, 9, "cc-by-sa")
    e = found(5000, 2, "cc0")
    assert [f.observation_id for f in parse.ranked([a, e, c, b, d])] == [4000, 3000, 2000, 1000, 5000]


def test_ranking_keeps_the_api_order_for_full_ties():
    x, y = found(1000, 3, "cc-by"), found(2000, 3, "cc-by")
    assert parse.ranked([y, x]) == [y, x]


@pytest.mark.parametrize("payload", [None, {}, {"results": [{"id": "x", "taxon": {}}]}, {"results": [{"id": 1}]}])
def test_malformed_observations_raise(payload):
    with pytest.raises(SourceError):
        parse.observations(payload)


def test_an_empty_page_is_not_an_error():
    assert parse.observations(page([])) == []
