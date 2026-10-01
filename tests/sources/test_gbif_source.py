"""Tests for avianki.sources.gbif — replayed recorded responses and synthetic fakes, no network."""

from __future__ import annotations

import json

import pytest
from gbif_fakes import (
    API,
    EOD,
    FIXTURES,
    REGIONS,
    RI,
    TINY,
    TINY_IOC,
    RoutingSession,
    eod_record_route,
    ioc_entry,
    ioc_page,
    ioc_params,
    make_client,
    recorded_routes,
    request_key,
    tiny_routes,
)

from avianki.core.http import Limits, SourceError
from avianki.sources.contract import SpeciesRecord
from avianki.sources.gbif import GbifSpeciesSource, NameFallback


def tiny_source(routes=None, **kw) -> tuple[GbifSpeciesSource, RoutingSession]:
    session = RoutingSession(routes if routes is not None else tiny_routes())
    return GbifSpeciesSource(make_client(session), REGIONS, **kw), session


def test_species_are_ranked_by_annual_count_ties_by_species_key():
    source, _ = tiny_source()
    records = source.species_for(TINY.slug)
    assert [(r.rank, r.source_key, r.count) for r in records] == [
        (1, "10", 110),
        (2, "5", 102),  # ties with 20 on count; lower key first
        (3, "20", 102),
        (4, "30", 4),
    ]


def test_monthly_is_effort_normalised_and_scaled_to_the_peak_month():
    source, _ = tiny_source()
    monthly = {r.source_key: r.monthly for r in source.species_for(TINY.slug)}
    # A: 50/1000, 50/200, 10/100 -> 0.05, 0.25 (peak), 0.10 -> 51, 255, 102
    assert monthly["10"] == (51, 255, 0, 0, 0, 0, 102, 0, 0, 0, 0, 0)
    assert monthly["5"] == (255,) + (0,) * 11
    # B: May 1/10000 would round to 0 but the bird was there -> 1; June 2.55 -> 3
    assert monthly["20"] == (0, 0, 0, 0, 1, 3, 0, 0, 0, 0, 0, 255)
    # D: Feb 2/200 = 0.01 vs peak Mar 0.02 -> 127.5 rounds half up to 128
    assert monthly["30"] == (0, 128, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def test_names_come_from_the_ioc_checklist():
    source, _ = tiny_source()
    records = source.species_for(TINY.slug)
    assert [(r.sci_name, r.common_name) for r in records[:2]] == [
        ("Alpha alpha", "Alpha Bird"),
        ("Gamma gamma", "Gamma Bird"),
    ]
    assert all(r.species_id is None for r in records)
    assert source.name_fallbacks() == []


def test_regions_come_from_the_region_table_not_gbif():
    source, session = tiny_source()
    assert [(r.slug, r.gadm_gid) for r in source.regions()] == [("us-ri", "USA.40_1"), ("xx-tiny", "TST.1_1")]
    assert session.calls == []


def test_region_without_records_is_empty_not_an_error():
    empty = {"offset": 0, "limit": 0, "endOfRecords": True, "count": 0, "results": [], "facets": []}
    routes = {
        k: (empty if "gadmGid=TST.1_1" in k and "facet=speciesKey" in k and "month=" not in k else v)
        for k, v in tiny_routes().items()
    }
    source, _ = tiny_source(routes)
    assert source.species_for(TINY.slug) == []


def test_a_facet_that_fills_its_limit_raises_instead_of_truncating():
    # the tiny region has exactly 4 species, so a limit of 4 might be hiding a fifth
    source, _ = tiny_source(tiny_routes(facet_limit=4), facet_limit=4)
    with pytest.raises(SourceError, match="truncated"):
        source.species_for(TINY.slug)


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_raises_never_empty(status):
    routes = tiny_routes()
    for k in routes:
        if "month=7" in k:
            routes[k] = (status, b"boom")
    source, _ = tiny_source(routes)
    with pytest.raises(SourceError):
        source.species_for(TINY.slug)


def test_malformed_facet_raises():
    routes = tiny_routes()
    for k in routes:
        if "facet=month" in k:
            routes[k] = {"facets": [{"field": "MONTH", "counts": [{"name": "jan"}]}]}
    source, _ = tiny_source(routes)
    with pytest.raises(SourceError):
        source.species_for(TINY.slug)


def test_ioc_checklist_paging_that_comes_up_short_raises():
    routes = tiny_routes()
    routes[request_key(f"{API}/species/search", ioc_params())] = ioc_page(TINY_IOC, count=5)
    source, _ = tiny_source(routes)
    with pytest.raises(SourceError, match="IOC checklist"):
        source.species_for(TINY.slug)


def test_ioc_checklist_is_paged_and_fetched_once():
    routes = tiny_routes()
    routes[request_key(f"{API}/species/search", ioc_params())] = ioc_page(TINY_IOC[:3], end=False, count=4)
    routes[request_key(f"{API}/species/search", ioc_params(offset=3))] = ioc_page(TINY_IOC[3:], offset=3, count=4)
    source, session = tiny_source(routes)
    source.species_for(TINY.slug)
    source.species_for(TINY.slug)
    assert sum("/species/search" in c for c in session.calls) == 2


def _unmatched_routes(**extra):
    """Species 30 is missing from the checklist; the fallback lookups for it."""
    routes = tiny_routes()
    routes[request_key(f"{API}/species/search", ioc_params())] = ioc_page(TINY_IOC[:3])
    routes[request_key(f"{API}/species/30", None)] = {
        "key": 30,
        "canonicalName": "Delta oldgenus",
        "vernacularName": "delta bird",
    }
    routes[request_key(f"{API}/species/30/synonyms", {"limit": 100})] = {"results": []}
    routes[request_key(f"{API}/species/30/vernacularNames", {"limit": 1000})] = {
        "results": [{"vernacularName": "Clements Delta", "language": "eng", "source": "The Clements Checklist"}]
    }
    routes[request_key(f"{API}/occurrence/search", {"datasetKey": EOD, "speciesKey": 30, "limit": 1})] = {
        "results": [{"speciesKey": 30, "vernacularName": "Record Delta"}]
    }
    routes.update(extra)
    return routes


def _record(common: str, key: str = "10", sci: str = "Alpha alpha") -> SpeciesRecord:
    return SpeciesRecord(None, sci, common, key, 1, (0,) * 12, 5)


def test_mint_name_is_ebirds_name_from_an_eod_record():
    source, session = tiny_source()
    assert source.mint_name(_record("Alpha Bird")) == ("Alpha Birdie", "eod-record")
    assert session.calls == [eod_record_route(10)]


def test_mint_name_falls_back_to_the_ioc_name_then_the_scientific_name():
    routes = tiny_routes()
    routes[eod_record_route(10)] = {"results": []}
    routes[eod_record_route(5)] = {"results": [{"speciesKey": 5}]}  # a record with no vernacularName
    source, _ = tiny_source(routes)
    assert source.mint_name(_record("Alpha Bird")) == ("Alpha Bird", "ioc")
    assert source.mint_name(_record("Gamma gamma", "5", "Gamma gamma")) == ("Gamma gamma", "sci-name")


def test_listing_a_region_makes_no_eod_record_requests():
    source, session = tiny_source()
    source.species_for(TINY.slug)
    assert not [c for c in session.calls if "limit=1&" in c and "speciesKey" in c and "facet" not in c]


def test_no_ioc_match_falls_back_to_the_eod_record_name_and_is_reported():
    source, _ = tiny_source(_unmatched_routes())
    d = source.species_for(TINY.slug)[3]
    assert (d.sci_name, d.common_name) == ("Delta oldgenus", "Record Delta")
    assert source.name_fallbacks() == [NameFallback("30", "Delta oldgenus", "Record Delta", "eod-record")]


def test_no_ioc_match_prefers_an_ioc_sourced_vernacular():
    vern = {
        "results": [
            {"vernacularName": "Clements Delta", "language": "eng", "source": "The Clements Checklist"},
            {"vernacularName": "IOC Delta", "language": "eng", "source": "IOC World Bird List, v"},
        ]
    }
    routes = _unmatched_routes(**{request_key(f"{API}/species/30/vernacularNames", {"limit": 1000}): vern})
    source, _ = tiny_source(routes)
    assert source.species_for(TINY.slug)[3].common_name == "IOC Delta"
    assert source.name_fallbacks()[0].common_name_from == "gbif-ioc-vernacular"


def test_backbone_synonym_matches_the_ioc_name():
    # the backbone keeps "Delta oldgenus"; its synonym 99 is the IOC entry's backbone key
    synonyms = {"results": [{"key": 99, "canonicalName": "Delta newgenus"}]}
    routes = _unmatched_routes(**{request_key(f"{API}/species/30/synonyms", {"limit": 100}): synonyms})
    routes[request_key(f"{API}/species/search", ioc_params())] = ioc_page(
        TINY_IOC[:3] + [ioc_entry(99, "Delta newgenus", "Delta Bird")]
    )
    source, _ = tiny_source(routes)
    d = source.species_for(TINY.slug)[3]
    assert (d.sci_name, d.common_name, d.source_key) == ("Delta newgenus", "Delta Bird", "30")
    assert source.name_fallbacks() == []


def test_backbone_keys_resolving_to_one_ioc_species_are_merged():
    # species 30's backbone name is the IOC name of species 20
    routes = _unmatched_routes(**{request_key(f"{API}/species/30", None): {"key": 30, "canonicalName": "Beta beta"}})
    source, _ = tiny_source(routes)
    records = source.species_for(TINY.slug)
    assert len(records) == 3
    (beta,) = [r for r in records if r.sci_name == "Beta beta"]
    assert (beta.count, beta.source_key, beta.rank) == (106, "20", 2)
    # 30's Feb 2/200 and Mar 2/100 join 20's months; the peak is still Dec 100/100
    assert beta.monthly == (0, 3, 5, 0, 1, 3, 0, 0, 0, 0, 0, 255)


def test_dataset_version_is_uncached_and_checks_the_licence():
    meta = json.loads((FIXTURES / "eod_dataset.json").read_text(encoding="utf-8"))
    url = f"{API}/dataset/{EOD}"
    source, session = tiny_source({request_key(url, None): meta})
    assert source.dataset_version() == "2025-08-08 2024-eBird-dwca-1.0.zip ingested 2025-10-29T11:56:35.996+00:00"
    source.dataset_version()
    assert session.calls == [url, url]
    nc = {**meta, "license": "http://creativecommons.org/licenses/by-nc/4.0/legalcode"}
    source, _ = tiny_source({request_key(url, None): nc})
    with pytest.raises(SourceError, match="licence"):
        source.dataset_version()


def test_declares_polite_limits():
    assert GbifSpeciesSource.limits == Limits(2, 1, None, None)
    assert GbifSpeciesSource.republishable is True


# ── recorded: Rhode Island, EOD 2024 release, as served 2026-09-28 ──────────────


@pytest.fixture(scope="module")
def ri():
    session = RoutingSession(recorded_routes())
    source = GbifSpeciesSource(make_client(session), REGIONS)
    return source.species_for(RI.slug), source


def test_recorded_ri_top_ten(ri):
    records, _ = ri
    assert len(records) == 429
    assert [r.common_name for r in records[:10]] == [
        "Song Sparrow",
        "American Robin",
        "Northern Cardinal",
        "Black-capped Chickadee",
        "American Herring Gull",
        "Blue Jay",
        "American Crow",
        "Mourning Dove",
        "Tufted Titmouse",
        "American Goldfinch",
    ]
    assert (records[0].source_key, records[0].count) == ("2492196", 106394)
    assert [r.rank for r in records] == list(range(1, 430))
    assert all(a.count >= b.count for a, b in zip(records, records[1:]))


def test_recorded_ri_ioc_names_replace_backbone_genera(ri):
    records, source = ri
    by_key = {r.source_key: r for r in records}
    assert (by_key["2481875"].sci_name, by_key["2481875"].common_name) == (
        "Nannopterum auritum",
        "Double-crested Cormorant",
    )
    assert by_key["2484597"].sci_name == "Corthylio calendula"  # via a backbone synonym
    assert by_key["2474953"].sci_name == "Antigone canadensis"
    assert [f.sci_name for f in source.name_fallbacks()] == ["Falco atricapillus"]
    assert by_key["10542232"].common_name == "American Goshawk"


def test_recorded_ri_monthly_is_seasonal(ri):
    records, _ = ri
    by_name = {r.common_name: r.monthly for r in records}
    cardinal, ovenbird, bunting = by_name["Northern Cardinal"], by_name["Ovenbird"], by_name["Snow Bunting"]
    assert min(cardinal) > 100  # resident all year
    assert ovenbird.index(255) == 4 and ovenbird[0] == ovenbird[11] == 0  # May peak, gone in winter
    assert bunting.index(255) == 10 and bunting[5:9] == (0, 0, 0, 0)  # winter visitor, absent in summer
