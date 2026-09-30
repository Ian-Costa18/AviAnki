"""Tests for avianki.sources.ebird: the eBird species list, over a fake session (no network)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from avianki.core.http import HttpClient, HttpError, SourceError
from avianki.sources.contract import SpeciesSource
from avianki.sources.ebird import EbirdSpeciesSource, is_region_code
from avianki.sources.ebird import parse
from avianki.sources.registry import Registry

SPPLIST = "https://api.ebird.org/v2/product/spplist/US-MA"
TAXONOMY = "https://api.ebird.org/v2/ref/taxonomy/ebird"

TAXA = [
    {"speciesCode": "bkcchi", "comName": "Black-capped Chickadee", "sciName": "Poecile atricapillus", "category": "species"},
    {"speciesCode": "amerob", "comName": "American Robin", "sciName": "Turdus migratorius", "category": "species"},
    {"speciesCode": "y00934", "comName": "Herring x Lesser Black-backed Gull (hybrid)", "sciName": "Larus argentatus x fuscus", "category": "hybrid"},
]


class Reply:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.status_code = status
        self.content = json.dumps(body).encode()
        self.headers = {"Content-Type": "application/json"}


class Session:
    """Answers by URL; records every call (url, params, headers)."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict | None, dict]] = []

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: float | None = None):
        self.calls.append((url, params, headers or {}))
        answer = self.routes[url]
        if callable(answer):
            answer = answer(params)
        return answer if isinstance(answer, Reply) else Reply(answer)


def source(session: Session, key: str = "k3y") -> EbirdSpeciesSource:
    client = HttpClient(cache_dir=None, session=session, sleep=lambda _s: None, max_retries=0)
    return EbirdSpeciesSource(client, key)


def test_it_is_not_republishable_and_cannot_be_registered() -> None:
    src = source(Session({}))
    assert isinstance(src, SpeciesSource)
    assert src.name == "ebird" and src.republishable is False
    assert src.limits.needs_secret == "EBIRD_API_KEY"
    with pytest.raises(ValueError, match="not republishable"):
        Registry().register(src)


def test_species_come_back_in_ebird_order_with_ranks() -> None:
    session = Session({SPPLIST: ["amerob", "bkcchi"], TAXONOMY: TAXA})
    records = source(session).species_for("US-MA")
    assert [(r.rank, r.source_key, r.sci_name, r.common_name) for r in records] == [
        (1, "amerob", "Turdus migratorius", "American Robin"),
        (2, "bkcchi", "Poecile atricapillus", "Black-capped Chickadee"),
    ]
    assert all(r.species_id is None and r.monthly == (0,) * 12 for r in records)


def test_the_token_goes_in_a_header_and_never_in_the_url_or_params() -> None:
    session = Session({SPPLIST: ["amerob"], TAXONOMY: TAXA})
    source(session, "sekrit").species_for("us-ma")  # lower case is normalised
    assert len(session.calls) == 2
    for url, params, headers in session.calls:
        assert headers["X-eBirdApiToken"] == "sekrit"
        assert "sekrit" not in url and "sekrit" not in json.dumps(params)


def test_non_species_taxa_are_left_out() -> None:
    session = Session({SPPLIST: ["bkcchi", "y00934", "amerob"], TAXONOMY: TAXA})
    records = source(session).species_for("US-MA")
    assert [r.source_key for r in records] == ["bkcchi", "amerob"]
    assert [r.rank for r in records] == [1, 2]  # ranks stay dense


def test_a_code_missing_from_the_taxonomy_is_skipped_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    session = Session({SPPLIST: ["bkcchi", "zzzzzz"], TAXONOMY: TAXA[:1]})
    with caplog.at_level("WARNING", logger="bird_deck"):
        records = source(session).species_for("US-MA")
    assert [r.source_key for r in records] == ["bkcchi"]
    assert "zzzzzz" in caplog.text


def test_an_empty_taxonomy_answer_is_a_failure_not_an_empty_list() -> None:
    session = Session({SPPLIST: ["bkcchi"], TAXONOMY: []})
    with pytest.raises(SourceError, match="no rows"):
        source(session).species_for("US-MA")


def test_a_region_with_no_species_is_an_empty_list() -> None:
    session = Session({SPPLIST: []})
    assert source(session).species_for("US-MA") == []
    assert len(session.calls) == 1  # no taxonomy request for nothing


def test_taxonomy_is_requested_in_batches_of_200() -> None:
    codes = [f"sp{i:03d}" for i in range(201)]
    taxa = [{"speciesCode": c, "comName": c, "sciName": f"Genus {c}", "category": "species"} for c in codes]

    def taxonomy(params: dict | None) -> list[dict]:
        wanted = set((params or {})["species"].split(","))
        return [t for t in taxa if t["speciesCode"] in wanted]

    session = Session({SPPLIST: codes, TAXONOMY: taxonomy})
    records = source(session).species_for("US-MA")
    assert len(records) == 201
    assert [len(c[1]["species"].split(",")) for c in session.calls[1:]] == [200, 1]
    assert [r.source_key for r in records] == codes


def test_http_errors_raise_rather_than_return_nothing() -> None:
    session = Session({SPPLIST: Reply({"error": "no such region"}, status=404)})
    with pytest.raises(HttpError):
        source(session).species_for("US-MA")


@pytest.mark.parametrize(
    "payload", [{"error": "x"}, "text", [1, 2], [""]],
)
def test_a_malformed_species_list_is_a_source_error(payload: Any) -> None:
    with pytest.raises(SourceError):
        source(Session({SPPLIST: payload})).species_for("US-MA")


@pytest.mark.parametrize("payload", [{"a": 1}, [1], [{"speciesCode": "x", "comName": "X"}]])
def test_a_malformed_taxonomy_is_a_source_error(payload: Any) -> None:
    with pytest.raises(SourceError):
        source(Session({SPPLIST: ["x"], TAXONOMY: payload})).species_for("US-MA")


def test_a_bad_region_code_is_rejected_before_any_request() -> None:
    session = Session({})
    with pytest.raises(ValueError, match="eBird region code"):
        source(session).species_for("../etc")
    assert session.calls == []


def test_an_api_key_is_required() -> None:
    with pytest.raises(ValueError, match="EBIRD_API_KEY"):
        EbirdSpeciesSource(HttpClient(cache_dir=None, session=Session({})), "")


@pytest.mark.parametrize("code", ["US", "US-MA", "US-MA-017", "CA-QC", "MX-ROO", "AU-NSW"])
def test_region_codes(code: str) -> None:
    assert is_region_code(code)


@pytest.mark.parametrize("code", ["", "us-ma", "Massachusetts", "US-", "U", "US-MA-017-1", "US MA"])
def test_not_region_codes(code: str) -> None:
    assert not is_region_code(code)


def test_parse_keeps_the_first_of_duplicate_codes() -> None:
    assert parse.species_codes(["a", "b", "a"], "US") == ["a", "b"]
