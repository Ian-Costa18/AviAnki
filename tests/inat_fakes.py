"""Fakes shared by the iNaturalist source tests: a session that answers API v1 paths from a routing
table and media downloads from a file table, a small species table, and synthetic observations."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from avianki.core.http import HttpClient
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

API = "https://api.inaturalist.org/v1"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "inaturalist"

COMMON = "Double-crested Cormorant"
CORMORANT = "nannopterum-auritum"  # iNaturalist taxon 1454382
WHIMBREL = "numenius-phaeopus"  # 3901
MILLERBIRD = "acrocephalus-familiaris"  # 116756
OLD_NAME = "phalacrocorax-auritus"  # our name for the cormorant if the table still used the old genus
TODAY = "2026-09-28"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Reply:
    def __init__(self, status: int, body: Any, content_type: str = "application/json") -> None:
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Type": content_type}


class InatSession:
    """Answers ``API + path`` from ``routes[path]`` and any other URL from ``files[url]``.

    A route is a JSON-able body, a ``(status, body)`` tuple, an exception to raise, or a callable
    taking the request params and returning one of those. A file is ``(status, bytes, content type)``.
    Unknown requests fail the test.
    """

    def __init__(self, routes: Mapping[str, Any] | None = None, files: Mapping[str, tuple[int, bytes, str]] | None = None) -> None:
        self.routes = dict(routes or {})
        self.files = dict(files or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]

    def params_for(self, path: str) -> list[dict[str, Any]]:
        return [p for q, p in self.calls if q == path]

    def get(self, url: str, params: Mapping[str, Any] | None = None, **_: Any) -> Reply:
        p = dict(params or {})
        if url in self.files:
            self.calls.append((url, p))
            status, data, ctype = self.files[url]
            return Reply(status, data, ctype)
        if not url.startswith(API):
            raise AssertionError(f"unexpected request: {url} {p}")
        path = url[len(API):]
        self.calls.append((path, p))
        if path not in self.routes:
            raise AssertionError(f"unexpected request: {path} {p}")
        answer = self.routes[path]
        if callable(answer):
            answer = answer(p)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):
            return Reply(*answer)
        return Reply(200, answer)


def make_client(session: InatSession, cache_dir: Path | None = None) -> HttpClient:
    return HttpClient(cache_dir=cache_dir, session=session, sleep=lambda _s: None, max_retries=0)


def species_table(*extra: SpeciesRow) -> SpeciesTable:
    return SpeciesTable([
        SpeciesRow(id=CORMORANT, sci_name="Nannopterum auritum", common_name=COMMON),
        SpeciesRow(id=WHIMBREL, sci_name="Numenius phaeopus", common_name="Eurasian Whimbrel"),
        SpeciesRow(id=MILLERBIRD, sci_name="Acrocephalus familiaris", common_name="Millerbird"),
        *extra,
    ])


def taxa_answers(**by_query: str) -> Callable[[dict[str, Any]], Any]:
    """A ``/taxa`` route: fixture name by query, and an empty result for any other query."""

    def answer(params: dict[str, Any]) -> Any:
        name = by_query.get(str(params["q"]).replace(" ", "_").lower())
        if name is None:
            return {"total_results": 0, "page": 1, "per_page": 5, "results": []}
        return load(name)

    return answer


TAXA = taxa_answers(
    numenius_phaeopus="taxa_numenius_phaeopus.json",
    nannopterum_auritum="taxa_nannopterum_auritum.json",
    acrocephalus_familiaris="taxa_acrocephalus_familiaris.json",
    alle_alle="taxa_alle_alle.json",
    phalacrocorax_auritus="taxa_phalacrocorax_auritus.json",
)


def counts_page(counts: Mapping[int, int]) -> dict[str, Any]:
    return {"total_results": len(counts), "page": 1, "per_page": 500, "results": [
        {"count": n, "taxon": {"id": tid, "name": f"taxon {tid}", "rank": "species"}} for tid, n in counts.items()]}


def page(observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_results": len(observations), "page": 1, "per_page": 200, "results": observations}


def observation(obs_id: int = 1000, *, taxon_id: int = 1454382, agreements: int = 3, licence: str = "cc-by",
                photo_id: int | None = None, sound_id: int | None = None, **changes: Any) -> dict[str, Any]:
    """A synthetic observation with one photo (id ``obs_id + 1``) and one sound (``obs_id + 2``)."""
    o: dict[str, Any] = {
        "id": obs_id,
        "quality_grade": "research",
        "captive": False,
        "num_identification_agreements": agreements,
        "identifications_most_disagree": False,
        "spam": False,
        "taxon": {"id": taxon_id, "name": "Nannopterum auritum", "rank": "species", "is_active": True,
                  "iconic_taxon_name": "Aves"},
        "user": {"id": 7, "login": "birder", "name": "Bea Birder", "spam": False, "suspended": False},
        "photos": [{
            "id": photo_id or obs_id + 1, "license_code": licence,
            "url": f"https://inaturalist-open-data.s3.amazonaws.com/photos/{photo_id or obs_id + 1}/square.jpg",
            "attribution": f"(c) Bea Birder, some rights reserved ({licence.upper().replace('-', ' ')})",
            "original_dimensions": {"width": 2048, "height": 1536}, "flags": [], "moderator_actions": [], "hidden": False}],
        "sounds": [{
            "id": sound_id or obs_id + 2, "license_code": licence,
            "file_url": f"https://static.inaturalist.org/sounds/{sound_id or obs_id + 2}.m4a?1",
            "file_content_type": "audio/mp4",
            "attribution": f"(c) Bea Birder, some rights reserved ({licence.upper().replace('-', ' ')})",
            "flags": [], "moderator_actions": [], "hidden": False}],
    }
    o.update(changes)
    return copy.deepcopy(o)
