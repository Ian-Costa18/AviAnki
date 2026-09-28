"""Fakes for the Commons source tests: a miniature Wikipedia + Wikidata + Commons.

`Pool` holds pages the way the real APIs return them (recorded fixtures, or pages built
with the helpers below); `CommonsSession` answers HTTP requests from it, honouring
``titles=a|b`` batching, title normalisation and redirects, so the source is exercised
against realistic response shapes without a network.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avianki.core.http import HttpClient
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "commons"
TODAY = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status: int, body: Any, content_type: str = "application/json") -> None:
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Type": content_type}


Override = Callable[[str, Mapping[str, Any]], Any]


class Pool:
    """What the fake wikis know. Every attribute mirrors a real response member."""

    def __init__(self) -> None:
        self.wikipedia_pages: list[dict[str, Any]] = []
        self.wikipedia_hops: dict[str, str] = {}
        self.entities: dict[str, dict[str, Any]] = {}
        self.commons_pages: list[dict[str, Any]] = []
        self.commons_hops: dict[str, str] = {}
        self.categoryinfo: list[dict[str, Any]] = []
        self.members: dict[str, list[list[dict[str, Any]]]] = {}  # category -> pages of pages
        self.downloads: dict[str, tuple[int, bytes, str]] = {}

    @classmethod
    def recorded(cls) -> Pool:
        """The trimmed live responses in tests/fixtures/commons."""
        pool = cls()
        lead = recorded("wikipedia_lead.json")["query"]
        pool.wikipedia_pages = lead["pages"]
        pool.wikipedia_hops = {h["from"]: h["to"] for h in lead.get("redirects", [])}
        pool.entities = recorded("wikidata_claims.json")["entities"]
        photos = recorded("commons_photos.json")["query"]
        pool.commons_pages = photos["pages"]
        pool.commons_hops = {h["from"]: h["to"] for h in photos.get("normalized", [])}
        pool.categoryinfo = recorded("commons_categoryinfo.json")["query"]["pages"]
        for category, body in recorded("commons_audio_members.json").items():
            pool.members[category] = [body["query"]["pages"]]
            pool.commons_pages += body["query"]["pages"]
        return pool


class CommonsSession:
    """A requests-like session answering from a `Pool`. Every request is kept in ``calls``."""

    def __init__(self, pool: Pool, override: Override | None = None) -> None:
        self.pool = pool
        self.override = override
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def requests_to(self, url: str) -> list[dict[str, Any]]:
        return [p for u, p in self.calls if u == url]

    def get(self, url: str, params: Mapping[str, Any] | None = None, **_: Any) -> FakeResponse:
        params = dict(params or {})
        self.calls.append((url, params))
        if self.override is not None:
            answer = self.override(url, params)
            if answer is not None:
                if isinstance(answer, BaseException):
                    raise answer
                if isinstance(answer, tuple):
                    return FakeResponse(*answer)
                return FakeResponse(200, answer)
        if url in self.pool.downloads:
            status, body, content_type = self.pool.downloads[url]
            return FakeResponse(status, body, content_type)
        if url == WIKIPEDIA:
            return FakeResponse(200, self._titles(params, self.pool.wikipedia_pages, self.pool.wikipedia_hops))
        if url == WIKIDATA:
            return FakeResponse(200, self._entities(params))
        if url == COMMONS:
            return FakeResponse(200, self._commons(params))
        raise AssertionError(f"unexpected request: {url} {params}")

    # ── the three APIs ───────────────────────────────────────────────────────

    @staticmethod
    def _titles(params: Mapping[str, Any], pages: list[dict[str, Any]], known_hops: Mapping[str, str]) -> dict[str, Any]:
        titles = str(params["titles"]).split("|")
        by_title = {p["title"]: p for p in pages if "title" in p}
        normalized, redirects, out = [], [], []
        for requested in titles:
            title = requested
            if "_" in title:
                normalized.append({"from": title, "to": title.replace("_", " ")})
                title = title.replace("_", " ")
            if title in known_hops:
                redirects.append({"from": title, "to": known_hops[title]})
                title = known_hops[title]
            page = by_title.get(title, {"ns": 0, "title": title, "missing": True})
            if page not in out:
                out.append(page)
        query: dict[str, Any] = {"pages": out}
        if normalized:
            query["normalized"] = normalized
        if redirects:
            query["redirects"] = redirects
        return {"batchcomplete": True, "query": query}

    def _entities(self, params: Mapping[str, Any]) -> dict[str, Any]:
        ids = str(params["ids"]).split("|")
        assert len(ids) <= 50, "more than 50 ids in one request"
        return {"entities": {i: self.pool.entities.get(i, {"id": i, "missing": ""}) for i in ids}, "success": 1}

    def _commons(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if "generator" in params:
            category = str(params["gcmtitle"])
            batches = self.pool.members.get(category, [[]])
            index = int(str(params.get("gcmcontinue", "0")).split("|")[-1] or 0)
            pages = batches[index] if index < len(batches) else []
            if not pages:  # an empty generator result has no query member
                return {"batchcomplete": True}
            body: dict[str, Any] = {"query": {"pages": pages}}
            if index + 1 < len(batches):
                body["continue"] = {"gcmcontinue": f"file|{index + 1}", "continue": "gcmcontinue||"}
            else:
                body["batchcomplete"] = True
            return body
        if params.get("prop") == "categoryinfo":
            titles = str(params["titles"]).split("|")
            assert len(titles) <= 50, "more than 50 titles in one request"
            known = {p["title"]: p for p in self.pool.categoryinfo}
            return {"batchcomplete": True, "query": {"pages": [
                known.get(t, {"ns": 14, "title": t, "missing": True}) for t in titles]}}
        if "pageids" in params:
            wanted = int(params["pageids"])
            pages = [p for p in self.pool.commons_pages if p.get("pageid") == wanted]
            return {"batchcomplete": True, "query": {"pages": pages or [{"pageid": wanted, "missing": True}]}}
        titles = str(params["titles"]).split("|")
        assert len(titles) <= 50, "more than 50 titles in one request"
        return self._titles(params, self.pool.commons_pages, self.pool.commons_hops)


def make_client(session: CommonsSession, *, now: datetime = TODAY) -> HttpClient:
    return HttpClient(cache_dir=None, session=session, sleep=lambda _s: None, max_retries=0, now=lambda: now)


def table_of(*rows: tuple[str, str] | tuple[str, str, str]) -> SpeciesTable:
    """A species table from ``(sci name, common name[, wikipedia title])`` tuples."""
    from avianki.taxonomy.species import mint_id

    return SpeciesTable(
        SpeciesRow(mint_id(r[0]), r[0], r[1], wikipedia_title=r[2] if len(r) > 2 else None) for r in rows
    )


# ── page builders (real response shapes) ─────────────────────────────────────

ARTIST_LINK = '<a href="//commons.wikimedia.org/wiki/User:Jane_Doe" title="User:Jane Doe">Jane Doe</a>'


def lead_page(pageid: int, title: str, image: str | None, qid: str | None, *, disambiguation: bool = False) -> dict[str, Any]:
    page: dict[str, Any] = {"pageid": pageid, "ns": 0, "title": title}
    if image:
        page["pageimage"] = image.replace(" ", "_")
    props: dict[str, str] = {}
    if qid:
        props["wikibase_item"] = qid
    if disambiguation:
        props["disambiguation"] = ""
    if props:
        page["pageprops"] = props
    return page


def entity(qid: str, *names: str, rank: str = "normal") -> dict[str, Any]:
    stmts = [
        {
            "mainsnak": {"snaktype": "value", "property": "P225", "datatype": "string",
                         "datavalue": {"value": n, "type": "string"}},
            "type": "statement",
            "rank": rank,
        }
        for n in names
    ]
    return {"type": "item", "id": qid, "claims": {"P225": stmts} if stmts else {}}


def file_page(
    pageid: int,
    name: str,
    *,
    mime: str = "image/jpeg",
    mediatype: str = "BITMAP",
    width: int = 1600,
    height: int = 1200,
    duration: float | None = None,
    licence: str | None = "cc-by-sa-4.0",
    short: str | None = "CC BY-SA 4.0",
    artist: str | None = ARTIST_LINK,
    credit: str | None = "<span class=\"int-own-work\" lang=\"en\">Own work</span>",
    attribution: str | None = None,
    restrictions: str = "",
    categories: str = "Birds of Ontario|Turdus migratorius",
    object_name: str | None = None,
    user: str | None = "Jane Doe",
) -> dict[str, Any]:
    title = f"File:{name}"
    slug = name.replace(" ", "_")
    meta: dict[str, dict[str, str]] = {"Restrictions": {"value": restrictions}, "Categories": {"value": categories}}
    for key, value in (
        ("License", licence), ("LicenseShortName", short), ("Artist", artist), ("Credit", credit),
        ("Attribution", attribution), ("ObjectName", object_name),
    ):
        if value is not None:
            meta[key] = {"value": value}
    info: dict[str, Any] = {
        "size": 12345,
        "width": width,
        "height": height,
        "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{slug}",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
        "extmetadata": meta,
        "mime": mime,
        "mediatype": mediatype,
    }
    if user:
        info["user"] = user
    if duration is not None:
        info["duration"] = duration
    if mediatype == "BITMAP":
        info["thumburl"] = f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{slug}/960px-{slug}"
        info["thumbwidth"] = 960
    return {"pageid": pageid, "ns": 6, "title": title, "imagerepository": "local", "imageinfo": [info]}


def audio_page(pageid: int, name: str, species: str, **kw: Any) -> dict[str, Any]:
    kw.setdefault("mime", "application/ogg")
    kw.setdefault("mediatype", "AUDIO")
    kw.setdefault("width", 0)
    kw.setdefault("height", 0)
    kw.setdefault("duration", 45.0)
    kw.setdefault("categories", f"Audio files of {species}|Birds of Ontario")
    return file_page(pageid, name, **kw)


def add_species(
    pool: Pool, sci: str, *, article: str | None = None, image: str | None = None, qid: str | None = None,
    pageid: int = 1000, **file_kw: Any,
) -> None:
    """A species with a Wikipedia article, its lead image, and a well-formed Wikidata item."""
    article = article or sci
    image = image or f"{sci} 1.jpg"
    qid = qid or f"Q{pageid}"
    pool.wikipedia_pages.append(lead_page(pageid, article, image, qid))
    pool.entities[qid] = entity(qid, sci)
    pool.commons_pages.append(file_page(pageid + 5_000_000, image, **file_kw))
