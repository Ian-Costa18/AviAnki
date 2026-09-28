"""Fakes shared by the GBIF source, species-list and catalog CLI tests: a session that
answers GBIF requests from a routing table, and a tiny synthetic region."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from avianki.core.http import HttpClient
from avianki.taxonomy.regions import RegionRow, RegionTable

API = "https://api.gbif.org/v1"
EOD = "4fa7b334-ce0d-4e88-aaae-2e0c138d049e"
IOC = "c696e5ee-9088-4d11-bdae-ab88daffab78"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gbif"


def request_key(url: str, params: Mapping[str, Any] | None) -> str:
    """``url?sorted-query``: how recorded fixtures are indexed."""
    query = urlencode(sorted((str(k), str(v)) for k, v in (params or {}).items()))
    return f"{url}?{query}" if query else url


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}


class RoutingSession:
    """Answers each request from ``routes[request_key(url, params)]``: a JSON-able body,
    a ``(status, body)`` tuple, or an exception to raise. Unknown requests fail the test."""

    def __init__(self, routes: Mapping[str, Any]) -> None:
        self.routes = dict(routes)
        self.calls: list[str] = []

    def get(self, url: str, params: Mapping[str, Any] | None = None, **_: Any) -> FakeResponse:
        key = request_key(url, params)
        self.calls.append(key)
        if key not in self.routes:
            raise AssertionError(f"unexpected request: {key}")
        answer = self.routes[key]
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):
            return FakeResponse(*answer)
        return FakeResponse(200, answer)


def make_client(session: RoutingSession) -> HttpClient:
    return HttpClient(cache_dir=None, session=session, sleep=lambda _s: None, max_retries=0)


def recorded_routes() -> dict[str, Any]:
    """The recorded live responses (Rhode Island + an IOC checklist slice)."""
    index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
    return {
        key: json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for key, name in index.items()
    }


# ── a tiny synthetic region with hand-computed expectations ─────────────────────

TINY = RegionRow("xx-tiny", "Tiny", "US", "TST.1_1", "4.1", "US-TT")
RI = RegionRow("us-ri", "Rhode Island", "US", "USA.40_1", "4.1", "US-RI")
REGIONS = RegionTable([TINY, RI])


def facet_response(field: str, counts: Mapping[int, int], total: int | None = None) -> dict:
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "offset": 0,
        "limit": 0,
        "endOfRecords": False,
        "count": total if total is not None else sum(counts.values()),
        "results": [],
        "facets": [{"field": field, "counts": [{"name": str(k), "count": c} for k, c in ordered]}],
    }


def occurrence_params(gid: str, **extra: Any) -> dict[str, Any]:
    return {"datasetKey": EOD, "gadmGid": gid, "limit": 0, **extra}


def ioc_entry(nub: int, sci: str, common: str | None) -> dict:
    vern = [{"vernacularName": common, "language": "eng"}] if common else []
    return {
        "key": 100_000 + nub,
        "nubKey": nub,
        "canonicalName": sci,
        "rank": "SPECIES",
        "taxonomicStatus": "ACCEPTED",
        "vernacularNames": vern,
    }


def ioc_page(entries: list[dict], offset: int = 0, count: int | None = None, end: bool = True) -> dict:
    return {
        "offset": offset,
        "limit": 1000,
        "endOfRecords": end,
        "count": len(entries) if count is None else count,
        "results": entries,
    }


def ioc_params(offset: int = 0) -> dict[str, Any]:
    return {"datasetKey": IOC, "rank": "SPECIES", "status": "ACCEPTED", "limit": 1000, "offset": offset}


# Month totals (all records in the region, per month) and per-species monthly counts.
TINY_TOTALS = {1: 1000, 2: 200, 3: 100, 4: 100, 5: 10_000, 6: 100, 7: 100, 8: 100, 9: 100, 10: 100, 11: 100, 12: 100}
TINY_MONTHLY: dict[int, dict[int, int]] = {
    10: {1: 50, 2: 50, 7: 10},  # A: 110
    5: {1: 102},  # C: 102
    20: {5: 1, 6: 1, 12: 100},  # B: 102, ties with C
    30: {2: 2, 3: 2},  # D: 4
}
TINY_IOC = [
    ioc_entry(10, "Alpha alpha", "Alpha Bird"),
    ioc_entry(5, "Gamma gamma", "Gamma Bird"),
    ioc_entry(20, "Beta beta", "Beta Bird"),
    ioc_entry(30, "Delta delta", "Delta Bird"),
]


def tiny_routes(facet_limit: int = 3000) -> dict[str, Any]:
    gid = TINY.gadm_gid
    annual = {k: sum(m.values()) for k, m in TINY_MONTHLY.items()}
    routes: dict[str, Any] = {
        request_key(f"{API}/occurrence/search", occurrence_params(gid, facet="speciesKey", facetLimit=facet_limit)):
            facet_response("SPECIES_KEY", annual),
        request_key(f"{API}/occurrence/search", occurrence_params(gid, facet="month", facetLimit=13)):
            facet_response("MONTH", TINY_TOTALS),
        request_key(f"{API}/species/search", ioc_params()): ioc_page(TINY_IOC),
    }
    for month in range(1, 13):
        counts = {k: m[month] for k, m in TINY_MONTHLY.items() if month in m}
        routes[request_key(f"{API}/occurrence/search",
                           occurrence_params(gid, facet="speciesKey", facetLimit=facet_limit, month=month))] = (
            facet_response("SPECIES_KEY", counts)
        )
    return routes
