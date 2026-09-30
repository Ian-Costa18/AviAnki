"""ADR 0024: a GBIF backbone key takes the name eBird gives its records, not the backbone's.

Recorded worldwide and regional ``verbatimScientificName`` facets (as served 2026-09-30) for the
lumped keys the first full build got wrong; synthetic annual lists and IOC entries around them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from gbif_fakes import (
    API,
    FIXTURES,
    RoutingSession,
    facet_response,
    ioc_entry,
    ioc_page,
    ioc_params,
    make_client,
    occurrence_params,
    request_key,
    verbatim_response,
    verbatim_route,
)

from avianki.core.http import SourceError
from avianki.sources.gbif import DroppedMinority, GbifSpeciesSource, NameFallback, ReResolved
from avianki.taxonomy.regions import RegionRow, RegionTable

MA = RegionRow("us-ma", "Massachusetts", "US", "USA.22_1", "4.1", "US-MA")
FL = RegionRow("us-fl", "Florida", "US", "USA.10_1", "4.1", "US-FL")
AZ = RegionRow("us-az", "Arizona", "US", "USA.3_1", "4.1", "US-AZ")

HARRIER, DOVE, HAWK, SWAMPHEN = 2480487, 2495414, 2480556, 2474416

# the IOC checklist entries with their real backbone keys: the harrier key is the *older* species'
IOC = [
    ioc_entry(2480487, "Circus cyaneus", "Hen Harrier"),
    ioc_entry(6101217, "Circus hudsonius", "Northern Harrier"),
    ioc_entry(2495414, "Columba livia", "Rock Dove"),
    ioc_entry(2480556, "Buteo nitidus", "Grey-lined Hawk"),
    ioc_entry(7853540, "Buteo plagiatus", "Grey Hawk"),
    ioc_entry(2474416, "Porphyrio porphyrio", "Western Swamphen"),
    ioc_entry(5739284, "Porphyrio poliocephalus", "Grey-headed Swamphen"),
    ioc_entry(6101147, "Porphyrio madagascariensis", "African Swamphen"),
]


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"verbatim_{name}.json").read_text(encoding="utf-8"))


def region_routes(row: RegionRow, counts: Mapping[int, int]) -> dict[str, Any]:
    """A region whose records all fall in January, so the monthly vectors are trivial."""
    gid = row.gadm_gid
    search = f"{API}/occurrence/search"
    routes = {
        request_key(search, occurrence_params(gid, facet="speciesKey", facetLimit=3000)):
            facet_response("SPECIES_KEY", counts),
        request_key(search, occurrence_params(gid, facet="month", facetLimit=13)):
            facet_response("MONTH", {1: sum(counts.values())}),
    }
    for month in range(1, 13):
        routes[request_key(search, occurrence_params(gid, facet="speciesKey", facetLimit=3000, month=month))] = (
            facet_response("SPECIES_KEY", counts if month == 1 else {})
        )
    return routes


class Fixture:
    def __init__(self, regions: Mapping[RegionRow, Mapping[int, int]], ioc: list[dict] = IOC) -> None:
        self.routes: dict[str, Any] = {request_key(f"{API}/species/search", ioc_params()): ioc_page(ioc)}
        for row, counts in regions.items():
            self.routes.update(region_routes(row, counts))
        self.table = RegionTable(list(regions))

    def worldwide(self, key: int, answer: Any) -> Fixture:
        self.routes[verbatim_route(key)] = answer
        return self

    def regional(self, key: int, row: RegionRow, answer: Any) -> Fixture:
        self.routes[verbatim_route(key, row.gadm_gid)] = answer
        return self

    def source(self) -> tuple[GbifSpeciesSource, RoutingSession]:
        session = RoutingSession(self.routes)
        return GbifSpeciesSource(make_client(session), self.table), session


def verbatim_calls(session: RoutingSession, *, regional: bool) -> list[str]:
    return [c for c in session.calls if "facet=verbatimScientificName" in c and ("gadmGid" in c) == regional]


def by_name(records) -> dict[str, Any]:
    return {r.sci_name: r for r in records}


# ── a key that eBird names as one IOC species ────────────────────────────────────


def test_a_key_whose_names_all_resolve_to_one_species_keeps_it_with_no_regional_request():
    fx = Fixture({MA: {DOVE: 500}}).worldwide(DOVE, recorded("2495414"))
    source, session = fx.source()
    (record,) = source.species_for("us-ma")
    assert (record.sci_name, record.common_name, record.source_key, record.count) == (
        "Columba livia", "Rock Dove", "2495414", 500,
    )
    assert len(verbatim_calls(session, regional=False)) == 1
    assert verbatim_calls(session, regional=True) == []
    assert source.re_resolved() == []
    assert source.dropped_minorities() == []


def test_the_worldwide_names_are_asked_once_per_key_however_many_regions_use_them():
    fx = Fixture({MA: {DOVE: 500}, FL: {DOVE: 900}}).worldwide(DOVE, recorded("2495414"))
    source, session = fx.source()
    source.species_for("us-ma")
    source.species_for("us-fl")
    source.species_for("us-ma")
    assert len(verbatim_calls(session, regional=False)) == 1


def test_names_that_resolve_to_the_backbones_own_species_are_not_re_resolved():
    # key 2480556 is Buteo nitidus in the backbone; a region where eBird only says nitidus agrees
    fx = Fixture({AZ: {HAWK: 40}}).worldwide(HAWK, verbatim_response({"buteo nitidus": 40}))
    source, _ = fx.source()
    (record,) = source.species_for("us-az")
    assert (record.sci_name, record.source_key) == ("Buteo nitidus", str(HAWK))
    assert source.re_resolved() == []


def test_a_key_that_eBird_names_by_another_single_species_is_re_resolved_worldwide():
    fx = Fixture({MA: {HARRIER: 1000}}).worldwide(HARRIER, verbatim_response({"circus hudsonius": 900}))
    source, session = fx.source()
    (record,) = source.species_for("us-ma")
    assert (record.sci_name, record.common_name) == ("Circus hudsonius", "Northern Harrier")
    assert verbatim_calls(session, regional=True) == []
    assert source.re_resolved() == [
        ReResolved(str(HARRIER), "us-ma", "Circus cyaneus", "Hen Harrier", "Circus hudsonius", "Northern Harrier", 1.0)
    ]


# ── a key that holds several IOC species ──────────────────────────────────────────


def test_circus_the_key_takes_the_species_most_of_its_records_are_in_the_region():
    fx = (Fixture({MA: {HARRIER: 116_344, DOVE: 50}})
          .worldwide(HARRIER, recorded("2480487")).regional(HARRIER, MA, recorded("2480487_us-ma"))
          .worldwide(DOVE, recorded("2495414")))
    source, session = fx.source()
    records = source.species_for("us-ma")
    named = by_name(records)
    assert "Circus cyaneus" not in named
    harrier = named["Circus hudsonius"]
    assert (harrier.common_name, harrier.count, harrier.rank) == ("Northern Harrier", 116_344, 1)
    assert harrier.monthly == (255,) + (0,) * 11  # the key's own monthly counts go to the species
    # the record is the species' own backbone key: the harrier key belongs to Circus cyaneus in species.csv
    assert harrier.source_key == "6101217"
    assert len(verbatim_calls(session, regional=True)) == 1
    assert source.re_resolved() == [
        ReResolved("2480487", "us-ma", "Circus cyaneus", "Hen Harrier", "Circus hudsonius", "Northern Harrier", 1.0)
    ]
    assert source.dropped_minorities() == []


def test_porphyrio_the_regional_winner_can_differ_from_the_backbones_species():
    fx = (Fixture({FL: {SWAMPHEN: 54_567}})
          .worldwide(SWAMPHEN, recorded("2474416")).regional(SWAMPHEN, FL, recorded("2474416_us-fl")))
    source, _ = fx.source()
    (record,) = source.species_for("us-fl")
    assert (record.sci_name, record.common_name, record.count) == (
        "Porphyrio poliocephalus", "Grey-headed Swamphen", 54_567,
    )
    (moved,) = source.re_resolved()
    assert (moved.old_common_name, moved.common_name, moved.share) == ("Western Swamphen", "Grey-headed Swamphen", 1.0)


def test_each_region_gets_the_species_that_wins_there_and_the_losers_are_dropped():
    fx = (Fixture({FL: {SWAMPHEN: 1000}, AZ: {SWAMPHEN: 1000}})
          .worldwide(SWAMPHEN, recorded("2474416"))
          .regional(SWAMPHEN, FL, verbatim_response({"porphyrio poliocephalus": 950, "porphyrio porphyrio": 50}))
          .regional(SWAMPHEN, AZ, verbatim_response({"porphyrio poliocephalus": 300, "porphyrio porphyrio": 700})))
    source, _ = fx.source()
    (in_fl,) = source.species_for("us-fl")
    (in_az,) = source.species_for("us-az")
    assert (in_fl.sci_name, in_fl.count) == ("Porphyrio poliocephalus", 1000)
    assert (in_az.sci_name, in_az.count) == ("Porphyrio porphyrio", 1000)  # the backbone's own species
    # only the region where the key moved is a re-resolution
    assert [(r.region, r.sci_name, round(r.share, 2)) for r in source.re_resolved()] == [
        ("us-fl", "Porphyrio poliocephalus", 0.95)
    ]
    # the 30% dropped in Arizona is over 10%; the 5% dropped in Florida is not
    assert source.dropped_minorities() == [
        DroppedMinority(str(SWAMPHEN), "us-az", "Porphyrio porphyrio", "Western Swamphen", 0.7,
                        ("Porphyrio poliocephalus",))
    ]


def test_a_key_is_never_cached_under_one_species_for_all_regions():
    fx = (Fixture({FL: {SWAMPHEN: 10}, AZ: {SWAMPHEN: 10}})
          .worldwide(SWAMPHEN, recorded("2474416"))
          .regional(SWAMPHEN, FL, verbatim_response({"porphyrio poliocephalus": 10}))
          .regional(SWAMPHEN, AZ, verbatim_response({"porphyrio madagascariensis": 10})))
    source, session = fx.source()
    assert source.species_for("us-fl")[0].sci_name == "Porphyrio poliocephalus"
    assert source.species_for("us-az")[0].sci_name == "Porphyrio madagascariensis"
    assert source.species_for("us-fl")[0].sci_name == "Porphyrio poliocephalus"
    assert len(verbatim_calls(session, regional=False)) == 1


def test_a_tie_between_species_goes_to_the_name_that_sorts_first():
    fx = (Fixture({FL: {SWAMPHEN: 10}}).worldwide(SWAMPHEN, recorded("2474416"))
          .regional(SWAMPHEN, FL, verbatim_response({"porphyrio poliocephalus": 5, "porphyrio porphyrio": 5})))
    source, _ = fx.source()
    assert source.species_for("us-fl")[0].sci_name == "Porphyrio poliocephalus"


def test_subspecies_names_are_summed_into_their_species():
    names = {"circus hudsonius": 10, "circus hudsonius hudsonius": 20, "circus cyaneus": 25}
    fx = Fixture({MA: {HARRIER: 55}}).worldwide(HARRIER, verbatim_response(names)).regional(
        HARRIER, MA, verbatim_response(names))
    source, _ = fx.source()
    (record,) = source.species_for("us-ma")
    assert record.sci_name == "Circus hudsonius"  # 30 records beat 25
    assert round(source.re_resolved()[0].share, 2) == 0.55
    assert source.dropped_minorities()[0].dropped == ("Circus cyaneus",)


# ── names that aren't IOC species ─────────────────────────────────────────────────


def _fallback_routes(fx: Fixture, key: int, canonical: str) -> Fixture:
    fx.routes[request_key(f"{API}/species/{key}", None)] = {"key": key, "canonicalName": canonical}
    fx.routes[request_key(f"{API}/species/{key}/synonyms", {"limit": 100})] = {"results": []}
    fx.routes[request_key(f"{API}/species/{key}/vernacularNames", {"limit": 1000})] = {"results": []}
    fx.routes[request_key(f"{API}/occurrence/search", {"datasetKey": FL_EOD, "speciesKey": key, "limit": 1})] = {
        "results": [{"speciesKey": key, "vernacularName": "Record Bird"}]
    }
    return fx


FL_EOD = "4fa7b334-ce0d-4e88-aaae-2e0c138d049e"


def test_a_name_not_in_the_ioc_list_falls_back_to_the_backbone_path():
    # eBird's "astur atricapillus" is not an IOC species in this checklist; the backbone says Falco
    fx = _fallback_routes(Fixture({MA: {10542232: 700}}), 10542232, "Falco atricapillus")
    fx.worldwide(10542232, recorded("10542232"))
    source, session = fx.source()
    (record,) = source.species_for("us-ma")
    assert (record.sci_name, record.common_name, record.source_key) == ("Falco atricapillus", "Record Bird", "10542232")
    assert source.name_fallbacks() == [NameFallback("10542232", "Falco atricapillus", "Record Bird", "eod-record")]
    assert source.re_resolved() == []
    assert verbatim_calls(session, regional=True) == []


def test_a_name_that_is_not_a_species_counts_as_the_backbones_species():
    # "circus sp." (unidentified harrier) and a hybrid are the backbone's Circus cyaneus, not names of their own
    names = {"circus hudsonius": 100, "circus sp.": 30, "circus cyaneus x hudsonius": 20, "circus": 5}
    fx = Fixture({MA: {HARRIER: 155}}).worldwide(HARRIER, verbatim_response(names)).regional(
        HARRIER, MA, verbatim_response(names))
    source, _ = fx.source()
    (record,) = source.species_for("us-ma")
    assert record.sci_name == "Circus hudsonius"
    (dropped,) = source.dropped_minorities()
    assert dropped.dropped == ("Circus cyaneus",)
    assert round(dropped.kept_share, 2) == 0.65


def test_names_that_all_fail_to_parse_use_the_backbones_species_with_no_re_resolution():
    fx = Fixture({MA: {HARRIER: 10}}).worldwide(HARRIER, verbatim_response({"circus sp.": 10}))
    source, _ = fx.source()
    (record,) = source.species_for("us-ma")
    assert (record.sci_name, record.source_key) == ("Circus cyaneus", str(HARRIER))
    assert source.re_resolved() == []


def test_a_key_the_backbone_cannot_name_takes_the_ioc_species_eBird_names_and_is_not_held_back():
    ioc = [e for e in IOC if e["canonicalName"] != "Buteo plagiatus"]
    ioc.append(ioc_entry(7853540, "Buteo plagiatus", "Grey Hawk"))
    # remove the hawk's backbone key from the checklist so the backbone path would need a fallback
    ioc = [e for e in ioc if e["nubKey"] != HAWK] + [ioc_entry(99, "Buteo nitidus", "Grey-lined Hawk")]
    fx = _fallback_routes(Fixture({AZ: {HAWK: 90}}, ioc=ioc), HAWK, "Buteo nitidus lumped")
    fx.worldwide(HAWK, verbatim_response({"buteo plagiatus": 90}))
    source, _ = fx.source()
    (record,) = source.species_for("us-az")
    assert (record.sci_name, record.common_name, record.source_key) == ("Buteo plagiatus", "Grey Hawk", "7853540")
    assert source.name_fallbacks() == []  # eBird's name is an IOC species, so nothing is held back
    assert (source.re_resolved()[0].old_sci_name, source.re_resolved()[0].sci_name) == (
        "Buteo nitidus lumped", "Buteo plagiatus")


# ── merging several keys into one species still works ─────────────────────────────


def test_a_re_resolved_key_merges_with_the_species_own_key():
    fx = (Fixture({MA: {HARRIER: 100, 6101217: 50}})
          .worldwide(HARRIER, verbatim_response({"circus hudsonius": 100}))
          .worldwide(6101217, verbatim_response({"circus hudsonius": 50})))
    source, _ = fx.source()
    (record,) = source.species_for("us-ma")
    assert (record.sci_name, record.count, record.source_key) == ("Circus hudsonius", 150, "6101217")


# ── failure is never absence ──────────────────────────────────────────────────────


@pytest.mark.parametrize("answer", [
    {"facets": []},  # a key with records always has names
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": []}]},
    {"facets": [{"field": "SPECIES_KEY", "counts": [{"name": "circus cyaneus", "count": 4}]}]},
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": [{"name": "circus cyaneus"}]}]},
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": [{"name": "circus cyaneus", "count": "many"}]}]},
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": [{"name": "circus cyaneus", "count": 0}]}]},
    {"nothing": "here"},
    [],
    (500, b"boom"),
])
def test_a_malformed_worldwide_facet_raises_never_an_empty_or_backbone_result(answer):
    fx = Fixture({MA: {HARRIER: 10}}).worldwide(HARRIER, answer)
    source, _ = fx.source()
    with pytest.raises(SourceError):
        source.species_for("us-ma")


def test_a_malformed_regional_facet_raises():
    fx = (Fixture({MA: {HARRIER: 10}}).worldwide(HARRIER, recorded("2480487"))
          .regional(HARRIER, MA, {"facets": []}))
    source, _ = fx.source()
    with pytest.raises(SourceError):
        source.species_for("us-ma")


def test_a_facet_that_fills_its_limit_raises_instead_of_dropping_names():
    names = {f"genus species{'abcdefghij'[i % 10]}{'abcdefghij'[i // 10]}": 1 for i in range(100)}
    fx = Fixture({MA: {HARRIER: 100}}).worldwide(HARRIER, {"facets": [{
        "field": "VERBATIM_SCIENTIFIC_NAME", "counts": [{"name": n, "count": c} for n, c in names.items()]}]})
    source, _ = fx.source()
    with pytest.raises(SourceError, match="truncated"):
        source.species_for("us-ma")
