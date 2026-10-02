"""`CommonsSource`: Wikipedia lead photographs and Commons bird recordings (ADR 0011, 0021).

**Photos** (ADR 0011 step 1). For each species: the en.wikipedia article
(``species.csv`` ``wikipedia_title``, else the scientific name, redirects followed), its
lead image (``pageimages``), the taxon guard (the article's Wikidata item must name the
same species, P225), then the Commons file's licence and credit. Each species gets at
most one photo candidate: the lead image is the only one Wikipedia curates.

**Audio.** The reliable query, chosen by a live probe of ten species: batched
``categoryinfo`` for ``Category:Audio files of <scientific name>`` (the category
Commons' own bird-sound uploaders, mostly xeno-canto mirrors, file recordings under),
then ``generator=categorymembers`` over each category that holds files. ``list=search``
with ``incategory:`` and ``filemime:audio`` was tried and found unreliable: it missed
files the categories listed. Only files in the exact species category (and in no other
species' audio category) are considered, which is the taxon-safety rule for audio.

Audio candidates are ranked best first by `parse.audio_rank_key`: (1) duration bucket,
10 to 120 s best, then up to 300 s, then under 10 s, then over 300 s, unknown last;
(2) licence, CC0/PDM before BY before BY-SA (ADR 0005, least strict first); (3) longer
first up to 120 s; (4) lower page id. The same xeno-canto recording is often uploaded
both as ``.ogg`` and ``.mp3``; only the best-ranked copy is kept.

When a `XenoCantoLookup` is given, that rank is refined first by xeno-canto's own metadata for
the recordings that mirror it (ADR 0031): recordings with no background species, then by quality
grade A to E, then the order above. It orders and never rejects; without a key or when the API
fails, the order above stands and the lookup leaves a note for the build report (`notes`).

**Failure versus absence** (ADR 0007). No article, no lead image, a disambiguation page,
a failed taxon guard, no audio category: absence. Any HTTP error, exhausted ``maxlag``
retry, exhausted budget, or a response without the structure the parser expects:
`SourceError`, for the whole batch.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, TypeVar

from avianki.core.http import HttpClient, Limits, SourceError
from avianki.core.licences import AssetRecord
from avianki.sources.commons import parse
from avianki.sources.commons.xenocanto import XcInfo, XenoCantoLookup, order_key
from avianki.sources.contract import AssetKind, AssetSource, Candidate, FetchedAsset, SpeciesId
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

log = logging.getLogger("bird_deck")

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

BATCH = 50  # titles or ids per query (the API maximum for a normal client)
MAXLAG = 5  # seconds; the Wikimedia etiquette value for bots
THUMB_WIDTH = 960  # one of the sizes Wikimedia serves; arbitrary widths are refused with 400
AUDIO_PAGE = 50
MAX_AUDIO_PAGES = 3  # files read per species category: 150, then ranked

# Wikimedia: serial requests, one at a time, GET only; 1 req/s is well inside their bot
# guidance (up to 200 req/s read for anonymous clients with a descriptive User-Agent, but
# a 1000-species catalog build doesn't need speed). No key, no quota.
LIMITS = Limits(requests_per_second=1, max_concurrency=1, daily_request_budget=None, needs_secret=None)

_TOKEN = re.compile(r"^M[1-9][0-9]*$")
_T = TypeVar("_T")


def _chunks(items: Sequence[_T], size: int) -> Iterator[list[_T]]:
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _xc_number(title: str) -> str | None:
    """The xeno-canto number a Commons file name mirrors, without leading zeros."""
    key = parse.recording_key(title)
    return str(int(key)) if key is not None else None


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


class CommonsSource(AssetSource):
    name = "commons"
    supplies = frozenset({AssetKind.PHOTO, AssetKind.AUDIO})
    republishable = True
    limits = LIMITS

    def __init__(self, client: HttpClient, species: SpeciesTable, xc: XenoCantoLookup | None = None) -> None:
        self._client = client
        self._species = species
        self._xc = xc
        self.stats: Counter[str] = Counter()
        """Files and species turned away so far, by reason code (for the build report)."""
        self.guard_drops: dict[SpeciesId, str] = {}
        """Species whose Wikipedia article failed the taxon guard, with why."""

    # ── contract ─────────────────────────────────────────────────────────────

    def candidates(
        self, species: list[SpeciesId], kind: AssetKind, limit: int
    ) -> dict[SpeciesId, list[Candidate]]:
        if kind not in self.supplies:
            raise ValueError(f"commons does not supply {kind.value}")
        if limit < 1 or not species:
            return {}
        rows = {sid: self._species.get(sid) for sid in dict.fromkeys(species)}
        if kind is AssetKind.PHOTO:
            return self._photos(rows)
        return self._audio(rows, limit)

    def notes(self) -> list[str]:
        return self._xc.notes() if self._xc is not None else []

    def fetch(self, candidate: Candidate) -> FetchedAsset:
        record = candidate.record
        resp = self._client.get(self.name, self.limits, record.file_url, cache=False)
        content_type = next((v for k, v in resp.headers.items() if k.lower() == "content-type"), "")
        media = _media_type(content_type)
        if not resp.content:
            raise SourceError(f"commons: empty download for {record.file_url}")
        if candidate.kind is AssetKind.PHOTO:
            ok = media in parse.PHOTO_MIMES
        else:
            ok = media in parse.AUDIO_MIMES
        if not ok:
            raise SourceError(f"commons: {record.file_url} came back as {media or 'no content type'!r}, not {candidate.kind.value}")
        return FetchedAsset(candidate=candidate, data=resp.content, content_type=media, record=record)

    def resolve_pin(self, token: str, species_id: SpeciesId | None = None) -> Candidate:
        """Rebuild the candidate for a pinned Commons file (``M<page id>``).

        A pin skips ranking and the size, category and duration heuristics, never the
        mime, restrictions, licence or credit gates. The token doesn't say which species
        the file shows, so the species is read from the file's own categories (its
        species category, or ``Audio files of <species>``); pass ``species_id`` when the
        categories don't say. If they name a different species, the pin is refused.
        """
        if not _TOKEN.match(token):
            raise SourceError(f"commons: not a Commons pin token: {token!r}")
        pageid = int(token[1:])
        payload = self._commons({"pageids": pageid, "prop": "imageinfo", **self._imageinfo_params()})
        info = parse.parse_file_by_pageid(payload, pageid)
        if info is None:
            raise SourceError(f"commons: pinned file {token} no longer exists")
        retrieved_at = self._client.today()
        if info.mediatype == "AUDIO":
            kind = AssetKind.AUDIO
            gated = parse.audio_record(info, retrieved_at, strict=False)
        else:
            kind = AssetKind.PHOTO
            gated = parse.photo_record(info, retrieved_at, strict=False)
        if isinstance(gated, parse.Reject):
            raise SourceError(f"commons: pinned file {token} is not usable: {gated}")
        sid = self._pin_species(token, info, species_id)
        return self._candidate(sid, kind, info, gated)

    # ── photos ───────────────────────────────────────────────────────────────

    def _photos(self, rows: Mapping[SpeciesId, SpeciesRow]) -> dict[SpeciesId, list[Candidate]]:
        want: dict[SpeciesId, str] = {sid: row.wikipedia_title or row.sci_name for sid, row in rows.items()}
        pages = self._lead_pages(list(dict.fromkeys(want.values())))

        leads: dict[SpeciesId, parse.LeadPage] = {}
        for sid, title in want.items():
            page = pages[title]
            if page is None:
                self._skip(sid, "no-article", title)
            elif page.disambiguation:
                self._skip(sid, "disambiguation", page.title)
            elif page.image is None:
                self._skip(sid, "no-lead-image", page.title)
            elif page.wikidata_id is None:
                self._skip(sid, "no-wikidata-item", page.title)
            else:
                leads[sid] = page

        names = self._taxon_names(list(dict.fromkeys(p.wikidata_id for p in leads.values() if p.wikidata_id)))
        guarded: dict[SpeciesId, parse.LeadPage] = {}
        for sid, page in leads.items():
            assert page.wikidata_id is not None
            taxon = names[page.wikidata_id]
            if not parse.taxon_match(rows[sid].sci_name, taxon):
                have = sorted(taxon.names) if taxon else "no such item"
                self.guard_drops[sid] = f"{page.title} ({page.wikidata_id}): P225 {have}"
                self._skip(sid, "taxon-guard", f"{rows[sid].sci_name!r} vs article {page.title!r}, P225 {have}")
            else:
                guarded[sid] = page

        file_titles = sorted({f"File:{p.image}" for p in guarded.values() if p.image})
        files = self._files_by_title(file_titles)
        retrieved_at = self._client.today()

        out: dict[SpeciesId, list[Candidate]] = {}
        for sid, page in guarded.items():
            info = files[f"File:{page.image}"]
            if info is None:
                # A lead image can be a local en.wikipedia upload (fair use), not on Commons.
                self._skip(sid, "not-on-commons", str(page.image))
                continue
            gated = parse.photo_record(info, retrieved_at)
            if isinstance(gated, parse.Reject):
                self._skip(sid, f"photo-{gated.reason}", f"{info.title}: {gated.detail}")
                continue
            out[sid] = [self._candidate(sid, AssetKind.PHOTO, info, gated)]
        return out

    def _lead_pages(self, titles: list[str]) -> dict[str, parse.LeadPage | None]:
        found: dict[str, parse.LeadPage | None] = {}
        for batch in _chunks(titles, BATCH):
            payload = self._get(
                WIKIPEDIA_API,
                {
                    "action": "query",
                    "titles": "|".join(batch),
                    "redirects": 1,
                    "prop": "pageimages|pageprops",
                    "piprop": "name",
                    "pilimit": BATCH,
                    "ppprop": "disambiguation|wikibase_item",
                },
            )
            found.update(parse.parse_lead_pages(payload, batch))
        return found

    def _taxon_names(self, ids: list[str]) -> dict[str, parse.TaxonNames | None]:
        found: dict[str, parse.TaxonNames | None] = {}
        for batch in _chunks(ids, BATCH):
            payload = self._get(
                WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(batch), "props": "claims"}, maxlag=False
            )
            found.update(parse.parse_entities(payload, batch))
        return found

    def _files_by_title(self, titles: list[str]) -> dict[str, parse.FileInfo | None]:
        found: dict[str, parse.FileInfo | None] = {}
        for batch in _chunks(titles, BATCH):
            payload = self._commons({"titles": "|".join(batch), "prop": "imageinfo", **self._imageinfo_params()})
            found.update(parse.parse_files_by_title(payload, batch))
        return found

    # ── audio ────────────────────────────────────────────────────────────────

    def _audio(self, rows: Mapping[SpeciesId, SpeciesRow], limit: int) -> dict[SpeciesId, list[Candidate]]:
        cats = {sid: f"Category:Audio files of {row.sci_name}" for sid, row in rows.items()}
        sizes: dict[str, int] = {}
        for batch in _chunks(list(dict.fromkeys(cats.values())), BATCH):
            payload = self._commons({"titles": "|".join(batch), "prop": "categoryinfo"})
            sizes.update(parse.parse_category_sizes(payload))

        retrieved_at = self._client.today()
        out: dict[SpeciesId, list[Candidate]] = {}
        for sid, row in rows.items():
            category = cats[sid]
            if category not in sizes:
                self._skip(sid, "no-audio-category", category)
                continue
            gated_files: list[tuple[parse.FileInfo, AssetRecord]] = []
            for info in self._category_files(category):
                gated = parse.audio_record(info, retrieved_at, species_name=row.sci_name)
                if isinstance(gated, parse.Reject):
                    self.stats[f"audio-{gated.reason}"] += 1
                    log.debug("commons: %s: %s rejected: %s", sid, info.title, gated)
                    continue
                gated_files.append((info, gated))
            xc = self._xeno_canto([info for info, _ in gated_files])
            ranked: list[tuple[tuple[Any, ...], parse.FileInfo, AssetRecord]] = []
            for info, gated in gated_files:
                key = parse.audio_rank_key(info.duration, gated.licence_id, info.pageid)
                recording = _xc_number(info.title)
                ranked.append(((*order_key(xc.get(recording) if recording else None), *key), info, gated))
            ranked.sort(key=lambda t: t[0])
            picked: list[Candidate] = []
            seen_recordings: set[str] = set()
            for _, info, record in ranked:
                recording = parse.recording_key(info.title)
                if recording is not None:
                    if recording in seen_recordings:
                        self.stats["audio-duplicate"] += 1
                        continue
                    seen_recordings.add(recording)
                number = _xc_number(info.title)
                picked.append(self._candidate(sid, AssetKind.AUDIO, info, record, xc.get(number) if number else None))
                if len(picked) == limit:
                    break
            if picked:
                out[sid] = picked
            else:
                self._skip(sid, "no-usable-audio", f"{sizes[category]} files in {category}, none passed")
        return out

    def _xeno_canto(self, files: Sequence[parse.FileInfo]) -> dict[str, XcInfo]:
        """xeno-canto's metadata for the files that mirror a recording there; ``{}`` when off."""
        if self._xc is None:
            return {}
        numbers = [n for n in (_xc_number(info.title) for info in files) if n]
        return self._xc.metadata(numbers) if numbers else {}

    def _category_files(self, category: str) -> list[parse.FileInfo]:
        """Up to ``MAX_AUDIO_PAGES`` pages of the category's files, each once."""
        params: dict[str, Any] = {
            "generator": "categorymembers",
            "gcmtitle": category,
            "gcmtype": "file",
            "gcmlimit": AUDIO_PAGE,
            "prop": "imageinfo",
            **self._imageinfo_params(thumb=False),
        }
        files: dict[int, parse.FileInfo] = {}
        cont: dict[str, Any] = {}
        for _ in range(MAX_AUDIO_PAGES):
            body = self._get(COMMONS_API, {**params, **cont})
            for info in parse.parse_files(body):
                files.setdefault(info.pageid, info)
            nxt = body.get("continue") if isinstance(body, dict) else None
            if not isinstance(nxt, dict) or not nxt:
                break
            cont = {str(k): v for k, v in nxt.items()}
        else:
            log.debug("commons: %s has more than %d files; ranking the first %d",
                      category, MAX_AUDIO_PAGES * AUDIO_PAGE, len(files))
        return list(files.values())

    # ── pins ─────────────────────────────────────────────────────────────────

    def _pin_species(self, token: str, info: parse.FileInfo, species_id: SpeciesId | None) -> SpeciesId:
        named: dict[SpeciesId, SpeciesRow] = {}
        for category in info.categories:
            for text in (category, category.removeprefix("Audio files of ")):
                try:
                    row = self._species.by_sci_name(text)
                except KeyError:
                    continue
                named[row.id] = row
        if species_id is not None:
            row = self._species.get(species_id)  # KeyError for an unknown id is the caller's bug
            if named and row.id not in named:
                raise SourceError(
                    f"commons: pinned file {token} is categorised as {sorted(named)}, not {species_id!r}"
                )
            return species_id
        if len(named) != 1:
            raise SourceError(
                f"commons: cannot tell which species pinned file {token} shows "
                f"(categories name {sorted(named) or 'none'}); pass species_id"
            )
        return next(iter(named))

    # ── plumbing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _imageinfo_params(*, thumb: bool = True) -> dict[str, Any]:
        params: dict[str, Any] = {
            "iiprop": "url|size|mime|extmetadata|user|mediatype",
            "iiextmetadatafilter": "|".join(parse.EXTMETADATA_FIELDS),
        }
        if thumb:
            params["iiurlwidth"] = THUMB_WIDTH
        return params

    def _get(self, url: str, params: Mapping[str, Any], *, maxlag: bool = True) -> Any:
        query: dict[str, Any] = {"action": "query", "format": "json", "formatversion": 2, **params}
        if maxlag:
            query["maxlag"] = MAXLAG
        return self._client.get_json(self.name, self.limits, url, query)

    def _commons(self, params: Mapping[str, Any]) -> Any:
        return self._get(COMMONS_API, params)

    def _skip(self, sid: SpeciesId, reason: str, detail: str) -> None:
        self.stats[reason] += 1
        log.debug("commons: %s: no candidate (%s): %s", sid, reason, detail)

    @staticmethod
    def _candidate(
        sid: SpeciesId, kind: AssetKind, info: parse.FileInfo, record: AssetRecord, xc: XcInfo | None = None
    ) -> Candidate:
        if kind is AssetKind.PHOTO:
            return Candidate(sid, kind, record.source_asset_id, record, width=info.width, height=info.height)
        # Candidate has no duration field: it is used for ranking here and not carried on.
        if xc is not None:
            return Candidate(sid, kind, record.source_asset_id, record, xc_quality=xc.quality, xc_background=xc.background)
        return Candidate(sid, kind, record.source_asset_id, record)
