"""Pure parsing and gating for the Commons source: no requests, no clock, no disk.

Everything here takes already-decoded JSON (or a string) and returns plain data, so
the rules that decide whether a Commons file may become a candidate can be tested
without a network. A response whose shape isn't recognised raises `SourceError`
(ADR 0007): only a well-formed response saying "nothing here" means absence.

Two kinds of function live here:

* parsers (`parse_lead_pages`, `parse_entities`, `parse_files_*`) that turn API
  payloads into small frozen dataclasses;
* gates (`photo_record`, `audio_record`) that turn a `FileInfo` into an
  `AssetRecord` or a `Reject` carrying a short stable reason code.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

from avianki.core import licences
from avianki.core.http import SourceError
from avianki.core.licences import AssetRecord

SOURCE = "commons"
COMMONS_URL = "https://commons.wikimedia.org"

# ADR 0011: a lead image whose long side is under 800 px is rejected.
MIN_PHOTO_LONG_SIDE = 800

PHOTO_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
# What ffmpeg can read. Commons reports Ogg audio as ``application/ogg`` (verified live),
# so that is accepted alongside the audio/* spellings; every audio file must also be
# classed ``mediatype=AUDIO`` by Commons, which keeps ``video/ogg`` videos out.
AUDIO_MIMES = frozenset(
    {
        "audio/ogg",
        "application/ogg",
        "video/ogg",
        "audio/opus",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mpeg",
        "audio/mp3",
        "audio/flac",
        "audio/x-flac",
    }
)
# Shorter than this can't hold a useful vocalisation; longer is a bulk download for a
# 10 s excerpt (ADR 0011 trims to a 10 s window).
MIN_AUDIO_SECONDS = 3.0
MAX_AUDIO_SECONDS = 600.0

# Categories that say a Commons "file" of a bird is not a photograph of a live one. A
# whole-word match on any category name rejects the file; a false positive only costs
# absence ("absence is acceptable, wrongness is not"). Kept short on purpose.
NOT_A_PHOTO = re.compile(
    r"\b(?:drawings?|illustrations?|paintings?|engravings?|lithographs?|plates?|"
    r"taxidermy|specimens?|skeletons?|skulls?|eggs?|nests?|"
    r"maps?|stamps?|coins?|logos?)\b",
    re.IGNORECASE,
)
# Audio in a species category that is not that species singing: a person saying the name
# (Lingua Libre pronunciations, which research measured on Commons), choruses and
# soundscapes with many birds.
NOT_A_RECORDING = re.compile(r"lingua libre|pronunciation|spoken|chorus|soundscape", re.IGNORECASE)
_AUDIO_CATEGORY = re.compile(r"^audio files of ([a-z-]+(?: [a-z-]+){1,2})$", re.IGNORECASE)
_XC_ID = re.compile(r"\bXC\s?(\d+)\b")

# The name a licensor gave is worthless as a credit when it's one of these.
_NO_CREATOR = frozenset(
    {"", "unknown", "unknown author", "anonymous", "anon", "n/a", "none", "?", "not specified", "own work"}
)
# MediaWiki's own wording when it guessed the author from the uploader.
_ARTIST_BOILERPLATE = re.compile(
    r"no machine-readable author provided\.?|\bassumed \(based on copyright claims\)\.?", re.IGNORECASE
)
_OWN_WORK = re.compile(r"\bown work\b", re.IGNORECASE)

# extmetadata fields the gates read. Asked for by name, so the payload stays small.
EXTMETADATA_FIELDS = (
    "License",
    "LicenseShortName",
    "Artist",
    "Attribution",
    "Credit",
    "Restrictions",
    "Categories",
    "ObjectName",
)


def _malformed(what: str) -> SourceError:
    return SourceError(f"commons: malformed response: {what}")


def normalise_name(name: str) -> str:
    """Whitespace-normalised, case-folded: how scientific names are compared."""
    return " ".join(name.split()).casefold()


# ── generic response handling ─────────────────────────────────────────────────


def check_api(payload: Any, what: str) -> dict[str, Any]:
    """The body of an Action API call, or `SourceError`.

    The API reports failures (``maxlag``, bad parameters) as HTTP 200 with an ``error``
    member; those are failures, never "no results". Retrying maxlag needs a sleep, which
    a source may not do, so it surfaces as a `SourceError` for the pipeline to handle.
    """
    if not isinstance(payload, dict):
        raise _malformed(f"{what}: expected a JSON object, got {type(payload).__name__}")
    error = payload.get("error")
    if error is not None:
        if isinstance(error, dict):
            raise SourceError(f"commons: {what}: API error {error.get('code')!r}: {error.get('info')!r}")
        raise SourceError(f"commons: {what}: API error {error!r}")
    return payload


def _query_pages(payload: dict[str, Any], what: str) -> list[dict[str, Any]]:
    query = payload.get("query")
    if not isinstance(query, dict) or not isinstance(query.get("pages"), list):
        raise _malformed(f"{what}: no query.pages")
    pages = query["pages"]
    if not all(isinstance(p, dict) for p in pages):
        raise _malformed(f"{what}: query.pages holds non-objects")
    return pages


def _title_hops(payload: dict[str, Any]) -> dict[str, str]:
    """``from -> to`` for the API's title normalisation, conversion and redirects."""
    query = payload.get("query")
    hops: dict[str, str] = {}
    if isinstance(query, dict):
        for key in ("normalized", "converted", "redirects"):
            for item in query.get(key) or []:
                if isinstance(item, dict) and isinstance(item.get("from"), str) and isinstance(item.get("to"), str):
                    hops[item["from"]] = item["to"]
    return hops


def _final_title(title: str, hops: Mapping[str, str]) -> str:
    seen: set[str] = set()
    while title in hops and title not in seen:
        seen.add(title)
        title = hops[title]
    return title


# ── en.wikipedia lead images ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LeadPage:
    """What ``prop=pageimages|pageprops`` says about one resolved article."""

    pageid: int
    title: str
    image: str | None  # Commons file name, without the ``File:`` prefix
    wikidata_id: str | None
    disambiguation: bool


def parse_lead_pages(payload: Any, titles: list[str]) -> dict[str, LeadPage | None]:
    """Each requested title -> its resolved page, or None when it has no such article."""
    body = check_api(payload, "wikipedia lead images")
    pages = _query_pages(body, "wikipedia lead images")
    hops = _title_hops(body)
    by_title: dict[str, LeadPage | None] = {}
    for page in pages:
        title = page.get("title")
        if not isinstance(title, str):
            raise _malformed("wikipedia page without a title")
        if page.get("missing") or page.get("invalid"):
            by_title[title] = None
            continue
        pageid = page.get("pageid")
        if not isinstance(pageid, int):
            raise _malformed(f"wikipedia page {title!r} has no pageid")
        props = page.get("pageprops") or {}
        image = page.get("pageimage")
        item = props.get("wikibase_item") if isinstance(props, dict) else None
        by_title[title] = LeadPage(
            pageid=pageid,
            title=title,
            image=image if isinstance(image, str) and image else None,
            wikidata_id=item if isinstance(item, str) and item else None,
            disambiguation=isinstance(props, dict) and "disambiguation" in props,
        )
    found: dict[str, LeadPage | None] = {}
    for requested in titles:
        final = _final_title(requested, hops)
        if final not in by_title:
            raise _malformed(f"wikipedia response has no page for {requested!r}")
        found[requested] = by_title[final]
    return found


# ── Wikidata taxon names ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaxonNames:
    """A Wikidata item's taxon-name claims (P225)."""

    names: frozenset[str]  # normalised, non-deprecated P225 values


def _claim_strings(claims: Any, prop: str) -> frozenset[str]:
    out: set[str] = set()
    statements = claims.get(prop, []) if isinstance(claims, dict) else []
    for statement in statements if isinstance(statements, list) else []:
        if not isinstance(statement, dict) or statement.get("rank") == "deprecated":
            continue
        snak = statement.get("mainsnak")
        if not isinstance(snak, dict) or snak.get("snaktype") != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value")
        if isinstance(value, str) and value.strip():
            out.add(normalise_name(value))
    return frozenset(out)


def parse_entities(payload: Any, ids: list[str]) -> dict[str, TaxonNames | None]:
    """Each requested item id -> its taxon names, or None when the item doesn't exist."""
    body = check_api(payload, "wikidata entities")
    entities = body.get("entities")
    if not isinstance(entities, dict):
        raise _malformed("wikidata entities: no entities object")
    by_id: dict[str, TaxonNames | None] = {}
    for key, entity in entities.items():
        if not isinstance(entity, dict):
            raise _malformed(f"wikidata entity {key!r} is not an object")
        if "missing" in entity:
            by_id[key] = None
            continue
        claims = entity.get("claims")
        if not isinstance(claims, (dict, list)):  # an item with no claims has [] in some responses
            raise _malformed(f"wikidata entity {key!r} has no claims")
        if isinstance(claims, list):
            claims = {}
        by_id[key] = TaxonNames(_claim_strings(claims, "P225"))
    out: dict[str, TaxonNames | None] = {}
    for i in ids:
        if i not in by_id:  # a response that drops a requested item is malformed, not "no such item"
            raise _malformed(f"wikidata response has no entity for {i!r}")
        out[i] = by_id[i]
    return out


def taxon_match(sci_name: str, names: TaxonNames | None) -> bool:
    """Whether a Wikidata item's taxon name is exactly this species.

    PRD section 7: the article a scientific name redirects to must really be that
    species. ``"Acanthis flammea"`` redirects to the article "Redpoll", whose item's
    taxon name is the genus ``"Acanthis"``, so it fails and the species gets no photo.
    """
    return names is not None and normalise_name(sci_name) in names.names


# ── Commons file metadata ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class FileInfo:
    """One Commons file, as ``prop=imageinfo`` describes its current revision."""

    pageid: int
    title: str  # "File:Foo bar.jpg"
    page_url: str
    url: str  # the original
    thumb_url: str | None  # the 960 px bucket
    width: int
    height: int
    duration: float | None
    mime: str
    mediatype: str
    user: str | None
    meta: Mapping[str, str]  # extmetadata field -> raw value (HTML in some fields)

    @property
    def long_side(self) -> int:
        return max(self.width, self.height)

    @property
    def categories(self) -> list[str]:
        raw = self.meta.get("Categories", "")
        return [c.strip() for c in raw.split("|") if c.strip()]


def _file_info(page: dict[str, Any]) -> FileInfo | None:
    if page.get("missing") or page.get("invalid"):
        return None
    infos = page.get("imageinfo")
    if not infos:  # a file page whose file is gone
        return None
    if not isinstance(infos, list) or not isinstance(infos[0], dict):
        raise _malformed(f"imageinfo of {page.get('title')!r} is not a list of objects")
    info = infos[0]
    try:
        pageid = int(page["pageid"])
        title = str(page["title"])
        meta_raw = info.get("extmetadata") or {}
        meta = {
            str(k): str(v["value"])
            for k, v in meta_raw.items()
            if isinstance(v, dict) and v.get("value") is not None
        }
        duration = info.get("duration")
        thumb = info.get("thumburl")
        return FileInfo(
            pageid=pageid,
            title=title,
            page_url=str(info["descriptionurl"]),
            url=str(info["url"]),
            thumb_url=str(thumb) if thumb else None,
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            duration=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
            mime=str(info["mime"]),
            mediatype=str(info["mediatype"]),
            user=str(info["user"]) if info.get("user") else None,
            meta=meta,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise _malformed(f"imageinfo of {page.get('title')!r}: {e!r}") from e


def parse_files_by_title(payload: Any, titles: list[str]) -> dict[str, FileInfo | None]:
    """Each requested ``File:`` title -> its info, or None when the file is gone."""
    body = check_api(payload, "commons imageinfo")
    pages = _query_pages(body, "commons imageinfo")
    hops = _title_hops(body)
    by_title: dict[str, FileInfo | None] = {}
    for page in pages:
        title = page.get("title")
        if not isinstance(title, str):
            raise _malformed("commons page without a title")
        by_title[title] = _file_info(page)
    out: dict[str, FileInfo | None] = {}
    for requested in titles:
        final = _final_title(requested, hops)
        if final not in by_title:
            raise _malformed(f"commons response has no page for {requested!r}")
        out[requested] = by_title[final]
    return out


def parse_files(payload: Any) -> list[FileInfo]:
    """Every existing file in a ``generator=categorymembers`` response."""
    body = check_api(payload, "commons category members")
    if "query" not in body:  # an empty generator result carries no query member
        if "batchcomplete" in body or "continue" in body:
            return []
        raise _malformed("commons category members: neither query nor batchcomplete")
    pages = _query_pages(body, "commons category members")
    files = [_file_info(p) for p in pages]
    return [f for f in files if f is not None]


def parse_file_by_pageid(payload: Any, pageid: int) -> FileInfo | None:
    """The file with this page id, or None when the page is missing."""
    body = check_api(payload, "commons imageinfo")
    for page in _query_pages(body, "commons imageinfo"):
        if page.get("pageid") == pageid:
            if page.get("ns") not in (6, None):
                return None  # not a File: page
            return _file_info(page)
    raise _malformed(f"commons response has no page {pageid}")


def parse_category_sizes(payload: Any) -> dict[str, int]:
    """Category title -> file count, for the categories that exist and hold files."""
    body = check_api(payload, "commons category info")
    sizes: dict[str, int] = {}
    for page in _query_pages(body, "commons category info"):
        title = page.get("title")
        if not isinstance(title, str):
            raise _malformed("commons category without a title")
        if page.get("missing"):
            continue
        info = page.get("categoryinfo")
        files = info.get("files") if isinstance(info, dict) else 0  # no categoryinfo: an empty category
        if not isinstance(files, int):
            raise _malformed(f"category {title!r} has a non-numeric file count")
        if files > 0:
            sizes[title] = files
    return sizes


# ── HTML reduced to text ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Link:
    href: str
    text: str


class _Reader(HTMLParser):
    """Collects visible text and ``<a>`` links. Markup never survives; entities are decoded."""

    _BLOCK = frozenset({"br", "p", "div", "li", "dd", "dt", "tr", "td"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[_Link] = []
        self._skip = 0
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append(" ")
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href is not None:
            self.links.append(_Link(self._href, clean_text("".join(self._anchor))))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data)


def clean_text(text: str) -> str:
    """Collapse whitespace and drop control and format characters."""
    kept = "".join(" " if c.isspace() else c for c in text if unicodedata.category(c) not in ("Cc", "Cf", "Cs"))
    return " ".join(kept.split())


def _read_html(value: str) -> _Reader:
    reader = _Reader()
    reader.feed(value)
    reader.close()
    return reader


def plain_text(value: str | None) -> str:
    """HTML reduced to plain text: tags dropped, entities decoded, whitespace collapsed."""
    if not value:
        return ""
    return clean_text("".join(_read_html(value).parts))


def _absolute(href: str) -> str | None:
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/") and not href.startswith("//"):
        return COMMONS_URL + href
    if href.lower().startswith(("https://", "http://")):
        return href
    return None  # mailto:, javascript:, relative junk: not a link we will store


def _is_user_page(href: str) -> bool:
    return bool(re.search(r"/(?:wiki/|w/index\.php\?title=)User:", href, re.IGNORECASE))


def parse_artist(value: str | None) -> tuple[str | None, str | None]:
    """The creator name and profile URL from an ``Artist`` extmetadata value.

    ``Artist`` is wiki-authored HTML. The name is the text of the user-page link when
    there is one (else of the first link), otherwise the plain text minus MediaWiki's
    own "assumed" boilerplate. Returns ``(None, None)`` for empty or "unknown" values.
    """
    if not value:
        return None, None
    reader = _read_html(value)
    links = [link for link in reader.links if link.text]
    if links:
        link = next((li for li in links if _is_user_page(li.href)), links[0])
        name, url = link.text, _absolute(link.href)
    else:
        name = clean_text(_ARTIST_BOILERPLATE.sub("", "".join(reader.parts))).strip(" .,;:")
        url = None
    name = name.removeprefix("User:").strip()
    if name.casefold() in _NO_CREATOR:
        return None, None
    return name, url


def user_page_url(user: str) -> str:
    return f"{COMMONS_URL}/wiki/User:{quote(user.replace(' ', '_'), safe='(),:@!*~')}"


# ── licence and credit ────────────────────────────────────────────────────────


def resolve_file_licence(meta: Mapping[str, str]) -> licences.ResolvedLicence | None:
    """The one allowlisted licence a Commons file carries, or None to reject.

    ``License`` (machine-readable, e.g. ``cc-by-sa-3.0``) and ``LicenseShortName`` (e.g.
    ``CC BY-SA 3.0``) must each resolve to an exact allowed id, and agree. Anything
    unresolved, disagreeing or missing rejects: public-domain templates, GFDL, ported
    (``-de``) and NC/ND licences, and dual-licensed files whose displayed licence isn't
    on the allowlist.
    """
    resolved: set[str] = set()
    for key in ("License", "LicenseShortName"):
        raw = plain_text(meta.get(key))
        if not raw:
            continue
        hit = licences.resolve_licence(raw, SOURCE)
        if hit is None or not licences.is_allowed(hit.licence_id):
            return None
        resolved.add(hit.licence_id)
    if len(resolved) != 1:
        return None
    return licences.ResolvedLicence(next(iter(resolved)), False)


def _creator(info: FileInfo) -> tuple[str | None, str | None, str]:
    """(creator, creator_url, which rule supplied it).

    The credit goes to the creator, not the uploader (Commons: Reusing content). The
    chain: ``Artist``; then the licensor's own ``Attribution`` string; then the uploader,
    but only when the file says it is the uploader's own work (or says nothing about a
    source), because otherwise the uploader may just be the person who copied it here.
    """
    name, url = parse_artist(info.meta.get("Artist"))
    if name:
        return name, url, "artist"
    attribution = plain_text(info.meta.get("Attribution"))
    if attribution and attribution.casefold() not in _NO_CREATOR:
        return attribution, None, "attribution"
    credit = plain_text(info.meta.get("Credit"))
    if info.user and (not credit or _OWN_WORK.search(credit)):
        return info.user, user_page_url(info.user), "uploader"
    return None, None, "none"


def _title(info: FileInfo) -> str | None:
    name = plain_text(info.meta.get("ObjectName"))
    if name:
        return name
    stem = info.title.removeprefix("File:")
    return stem.rsplit(".", 1)[0].replace("_", " ").strip() or None


@dataclass(frozen=True)
class Reject:
    """A file that may not be offered. ``reason`` is a short, stable code used as a stat key."""

    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.reason}: {self.detail}" if self.detail else self.reason


def _common_gates(info: FileInfo, file_url: str, retrieved_at: str) -> AssetRecord | Reject:
    """Restrictions, licence and credit: gates that even a pin cannot skip."""
    restrictions = plain_text(info.meta.get("Restrictions"))
    if restrictions:
        return Reject("restrictions", restrictions)
    licence = resolve_file_licence(info.meta)
    if licence is None:
        seen = "/".join(filter(None, (plain_text(info.meta.get(k)) for k in ("License", "LicenseShortName"))))
        return Reject("licence", seen or "no licence field")
    creator, creator_url, how = _creator(info)
    record = AssetRecord(
        source=SOURCE,
        source_asset_id=f"M{info.pageid}",
        source_url=info.page_url,
        file_url=file_url,
        licence_id=licence.licence_id,
        licence_url=licences.licence_url(licence.licence_id),
        creator=creator,
        creator_url=creator_url,
        attribution_text=plain_text(info.meta.get("Attribution")) or None,
        title=_title(info),
        copyright_notice=None,  # Commons carries no separate notice
        restrictions=None,  # non-empty ones were rejected above
        retrieved_at=retrieved_at,
        source_terms_version=None,  # the research cites no dated revision of the WMF terms
        licence_version_assumed=licence.version_assumed,
    )
    missing = record.missing_required_fields()
    if missing:
        return Reject("credit", f"missing {', '.join(missing)} (creator from {how})")
    return record


def photo_record(info: FileInfo, retrieved_at: str, *, strict: bool = True) -> AssetRecord | Reject:
    """Gate a file as a photograph. ``strict=False`` (pins) skips the size and category
    heuristics but never the mime, restrictions, licence or credit gates."""
    if info.mediatype != "BITMAP" or info.mime not in PHOTO_MIMES:
        return Reject("mime", f"{info.mediatype} {info.mime}")
    if not info.thumb_url or not info.thumb_url.startswith("https://"):
        return Reject("no-thumb", "imageinfo gave no https thumbnail")
    if strict:
        if info.long_side < MIN_PHOTO_LONG_SIDE:
            return Reject("small", f"{info.width}x{info.height}")
        for category in info.categories:
            if NOT_A_PHOTO.search(category):
                return Reject("not-photo", category)
    return _common_gates(info, info.thumb_url, retrieved_at)


def audio_record(
    info: FileInfo, retrieved_at: str, *, species_name: str | None = None, strict: bool = True
) -> AssetRecord | Reject:
    """Gate a file as a recording.

    With ``species_name`` (candidate search) the file must be in that species' audio
    category and no other species' one. ``strict=False`` (pins) skips the duration,
    category and speech heuristics, but never the mime, restrictions, licence or credit.
    """
    if info.mediatype != "AUDIO" or info.mime not in AUDIO_MIMES:
        return Reject("mime", f"{info.mediatype} {info.mime}")
    if strict:
        if info.duration is not None and not MIN_AUDIO_SECONDS <= info.duration <= MAX_AUDIO_SECONDS:
            return Reject("duration", f"{info.duration:.1f} s")
        if info.title.removeprefix("File:").startswith("LL-"):
            return Reject("not-recording", "Lingua Libre file name")
        for category in info.categories:
            if NOT_A_RECORDING.search(category):
                return Reject("not-recording", category)
        if species_name is not None:
            want = normalise_name(species_name)
            audio_cats = {
                normalise_name(m.group(1)) for c in info.categories if (m := _AUDIO_CATEGORY.match(c.strip()))
            }
            if want not in audio_cats:
                return Reject("category", f"not in 'Audio files of {species_name}'")
            if audio_cats - {want}:
                return Reject("mixed-species", ", ".join(sorted(audio_cats - {want})))
    return _common_gates(info, info.url, retrieved_at)


# ── audio ranking ─────────────────────────────────────────────────────────────

_LICENCE_TIER = {"CC0": 0, "PDM": 0, "CC-BY": 1, "CC-BY-SA": 2}


def licence_tier(licence_id: str) -> int:
    """0 for CC0/PDM, 1 for BY, 2 for BY-SA: less strict first (ADR 0005)."""
    family = licence_id.rsplit("-", 1)[0]
    return _LICENCE_TIER.get(family, 3)


def duration_bucket(duration: float | None) -> int:
    """0 is best. 10 to 120 s holds several 10 s windows and is cheap to download."""
    if duration is None:
        return 4
    if 10 <= duration <= 120:
        return 0
    if 120 < duration <= 300:
        return 1
    if duration < 10:
        return 2
    return 3


def audio_rank_key(duration: float | None, licence_id: str, pageid: int) -> tuple[int, int, float, int]:
    """Sort key, best first: duration bucket, then licence, then longer (up to 120 s)."""
    return (duration_bucket(duration), licence_tier(licence_id), -min(duration or 0.0, 120.0), pageid)


def recording_key(title: str) -> str | None:
    """The xeno-canto number in a mirror's file name: the same recording uploaded as
    ``.ogg`` and ``.mp3`` shares it."""
    m = _XC_ID.search(title)
    return m.group(1) if m else None
