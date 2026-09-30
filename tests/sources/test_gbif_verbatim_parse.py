"""ADR 0024: parsing eBird's own names (the ``verbatimScientificName`` facet) and cutting them to binomials."""

from __future__ import annotations

import pytest

from avianki.core.http import SourceError
from avianki.sources.gbif.parse import binomial, verbatim_name_counts


@pytest.mark.parametrize(("name", "expected"), [
    ("Circus hudsonius", "circus hudsonius"),
    ("  circus   hudsonius ", "circus hudsonius"),
    ("circus cyaneus hudsonius", "circus cyaneus"),  # a subspecies group is its species
    ("larus argentatus-cachinnans", "larus argentatus-cachinnans"),
    ("circus sp.", None),
    ("circus", None),
    ("", None),
    ("circus hudsonius/cyaneus", None),
    ("circus cyaneus x hudsonius", None),
    ("circus (cyaneus)", None),
    ("circus hudsonius 2", None),
])
def test_binomial(name, expected):
    assert binomial(name) == expected


def facet(*buckets, field="VERBATIM_SCIENTIFIC_NAME"):
    return {"facets": [{"field": field, "counts": [{"name": n, "count": c} for n, c in buckets]}]}


def test_counts_are_summed_by_binomial_and_non_species_names_are_kept_whole():
    payload = facet(("circus hudsonius", 10), ("Circus hudsonius hudsonius", 5), ("circus sp.", 3), ("circus", 1))
    assert verbatim_name_counts(payload, 100, "key 1") == {"circus hudsonius": 15, "circus sp.": 3, "circus": 1}


def test_counts_accept_string_counts_as_the_api_may_serve_them():
    assert verbatim_name_counts(facet(("a b", "7")), 100, "key 1") == {"a b": 7}


@pytest.mark.parametrize("payload", [
    None,
    [],
    {},
    {"facets": None},
    {"facets": []},
    {"facets": [{"field": "SPECIES_KEY", "counts": []}]},
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME"}]},
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": None}]},
    facet(),
    facet(("a b", 0)),
    facet(("a b", -3)),
    facet(("", 3)),
    facet(("a b", "many")),
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": [{"count": 3}]}]},
    {"facets": [{"field": "VERBATIM_SCIENTIFIC_NAME", "counts": [{"name": "a b"}]}]},
    {"facets": [facet(("a b", 1))["facets"][0], facet(("c d", 1))["facets"][0]]},  # two facets of one field
])
def test_a_malformed_facet_raises_source_error(payload):
    with pytest.raises(SourceError):
        verbatim_name_counts(payload, 100, "key 1")


def test_a_facet_as_long_as_its_limit_may_be_truncated_and_raises():
    payload = facet(*((f"a b{i}", 1) for i in range(3)))
    with pytest.raises(SourceError, match="truncated"):
        verbatim_name_counts(payload, 3, "key 1")
    assert len(verbatim_name_counts(payload, 4, "key 1")) == 3
