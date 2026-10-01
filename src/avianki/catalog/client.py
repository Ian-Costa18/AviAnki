"""Reads a published catalog (spec section 5): manifest -> region / species -> media.

This is what the 1.0 CLI is built on (ADR 0017). It downloads only what a deck needs into a
local cache and checks every file against the hash in its name. It needs nothing beyond the
base install: the format dataclasses parse the JSON, and neither jsonschema, Pillow nor the
pipeline is imported.

Where paths resolve from. Every catalog-relative path (``regions/us-ma.<hash>.json``,
``media/<hash>.webp``) is resolved against the location the *client was pointed at*, which is
where it reads ``manifest.json`` from, not against ``manifest.base_url``. That makes a local
directory, a mirror or a test server work without editing the manifest, and it keeps the
fixture catalog's placeholder ``base_url`` harmless. ``base_url`` stays informational for the
Python side (the browser, which is served from wherever the page is, uses it; ADR 0013). If the
catalog ever moves host, the change here is `DEFAULT_BASE_URL`, or the old host serves a
manifest until clients upgrade.

Only ``avianki.core`` and ``avianki.catalog.format`` may be imported here (dependency rule).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

import requests

from avianki.catalog.format import (
    DEFAULT_BASE_URL,
    FORMAT_VERSION,
    MANIFEST_NAME,
    Manifest,
    RegionFile,
    RegionRef,
    SpeciesFile,
    canonical_json,
    media_filename,
)
from avianki.core.http import default_user_agent
from avianki.core.text import fold

log = logging.getLogger("bird_deck")

__all__ = [
    "AmbiguousRegion",
    "CacheWriteError",
    "CatalogClient",
    "CatalogError",
    "CatalogFetchError",
    "MediaNotFound",
    "RegionNotFound",
    "default_cache_dir",
]

# Names come from a manifest we don't control: check them before they reach a path or a URL.
_JSON_NAME = re.compile(r"^(?:regions/)?[a-z0-9]+(?:-[a-z0-9]+)*\.([0-9a-f]{8})\.json$")
_MEDIA_NAME = re.compile(r"^media/[0-9a-f]{16}\.(webp|mp3)$")

_MAX_SUGGESTIONS = 5

# What people type for a region whose catalog name differs (keys are `_plain` forms). The
# District of Columbia is the one place where the common name is not the official one.
_ALIASES = {
    "dc": "us-dc",
    "washington dc": "us-dc",
    "washington district of columbia": "us-dc",
}
# Malformed JSON shapes surface as these from the format dataclasses' ``from_dict``.
_SHAPE_ERRORS = (KeyError, TypeError, ValueError, AttributeError, IndexError)


class CatalogError(Exception):
    """Anything that stops the catalog being read: network, bad or unsupported content."""


class CatalogFetchError(CatalogError):
    """The catalog (or one of its files) could not be fetched: no network, a timeout, a server
    error, or a local catalog directory that can't be read. ``status`` is the HTTP status,
    when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


class MediaNotFound(CatalogFetchError):
    """A media file the manifest's species file names isn't there (HTTP 404)."""


class CacheWriteError(CatalogError):
    """A downloaded file could not be written to the cache directory."""


class RegionNotFound(CatalogError):
    """No region matches ``query``; ``suggestions`` are the closest manifest rows."""

    def __init__(self, query: str, suggestions: Sequence[RegionRef] = ()) -> None:
        self.query = query
        self.suggestions = list(suggestions)
        message = f"unknown region {query!r}"
        if self.suggestions:
            message += "; did you mean: " + ", ".join(
                f"{r.slug} ({r.name})" for r in self.suggestions
            )
        super().__init__(message)


class AmbiguousRegion(CatalogError):
    """More than one region has this display name; use one of the slugs."""

    def __init__(self, query: str, matches: Sequence[RegionRef]) -> None:
        self.query = query
        self.matches = list(matches)
        slugs = ", ".join(r.slug for r in self.matches)
        super().__init__(f"{query!r} matches several regions ({slugs}); use one of those slugs")


def default_cache_dir(
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """The per-user cache directory: ``%LOCALAPPDATA%\\avianki\\cache`` on Windows,
    ``~/Library/Caches/avianki`` on macOS, ``$XDG_CACHE_HOME/avianki`` or ``~/.cache/avianki``
    elsewhere. The arguments exist for tests and default to this machine."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "avianki" / "cache"
    if platform == "darwin":
        return home / "Library" / "Caches" / "avianki"
    xdg = env.get("XDG_CACHE_HOME", "")
    # The XDG spec says a relative value is invalid and must be ignored.
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".cache"
    return base / "avianki"


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, then rename, so a reader never sees a
    partial file and an interrupted write leaves nothing behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _plain(key: str) -> str:
    """A folded query without punctuation: ``"washington, d.c."`` -> ``"washington dc"``."""
    return " ".join(re.sub(r"[^a-z0-9 ]", "", key.replace(",", " ")).split())


def _hash_matches(name: str, obj: Any) -> bool:
    m = _JSON_NAME.match(name)
    return m is not None and m.group(1) == hashlib.sha256(canonical_json(obj)).hexdigest()[:8]


class CatalogClient:
    """A read-only view of one published catalog, with an on-disk cache for what it fetches.

    ``base_url`` is an ``http(s)://`` URL of the directory holding ``manifest.json``, or a
    local directory (path or ``file://`` URL). ``cache_dir`` defaults to `default_cache_dir`.
    Cached files are content-addressed (a hashed name never changes content), so a cached
    file is used without asking the server; only the manifest is always fetched fresh.
    """

    def __init__(
        self,
        base_url: str | Path = DEFAULT_BASE_URL,
        *,
        cache_dir: Path | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        backoff: float = 0.5,
    ) -> None:
        self.cache_dir = default_cache_dir() if cache_dir is None else cache_dir
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff
        self._session = session
        self._local_root: Path | None = None
        self._http_base = ""
        text = str(base_url)
        if text.lower().startswith(("http://", "https://")):
            self._http_base = text.rstrip("/") + "/"
        elif text.lower().startswith("file:"):
            self._local_root = Path(url2pathname(urlsplit(text).path))
        else:
            self._local_root = Path(text).expanduser()
        self._manifest: Manifest | None = None
        self._json: dict[str, Any] = {}
        self._parsed: dict[str, RegionFile | SpeciesFile] = {}

    def _where(self, name: str) -> str:
        return self._http_base + name if self._local_root is None else str(self._local_root / name)

    # -- transport ------------------------------------------------------------------

    def _read(self, name: str) -> bytes:
        """The bytes of a catalog-relative path. ``name`` must already be validated."""
        if self._local_root is not None:
            path = self._local_root / name
            try:
                return path.read_bytes()
            except OSError as exc:
                status = 404 if isinstance(exc, FileNotFoundError) else None
                raise CatalogFetchError(f"cannot read {path}: {exc}", status) from exc
        return self._http_get(self._http_base + name)

    def _http_get(self, url: str) -> bytes:
        if self._session is None:
            self._session = requests.Session()
        headers = {"User-Agent": default_user_agent()}
        last = ""
        for attempt in range(self._retries + 1):
            try:
                resp = self._session.get(url, timeout=self._timeout, headers=headers)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last = f"{type(exc).__name__}: {exc}"
            except requests.RequestException as exc:
                raise CatalogFetchError(f"GET {url} failed: {exc}") from exc
            else:
                if 200 <= resp.status_code < 300:
                    return resp.content
                last = f"HTTP {resp.status_code}"
                if resp.status_code < 500 and resp.status_code != 429:
                    raise CatalogFetchError(f"GET {url} failed: {last}", resp.status_code)
            if attempt < self._retries:
                log.debug("GET %s: %s, retrying", url, last)
                time.sleep(self._backoff * 2**attempt)
        raise CatalogFetchError(f"GET {url} failed after {self._retries + 1} attempts: {last}")

    # -- manifest and regions -------------------------------------------------------

    def manifest(self) -> Manifest:
        """Fetch and parse ``manifest.json``. Never cached: it's small and it's the one file
        that changes (ADR 0013)."""
        raw = self._read(MANIFEST_NAME)
        where = self._where(MANIFEST_NAME)
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CatalogError(f"{where} is not valid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise CatalogError(f"{where} is not a catalog manifest (expected a JSON object)")
        fmt = obj.get("format")
        # Check the version before the shape: a newer format may not parse as this one.
        if isinstance(fmt, int) and not isinstance(fmt, bool) and fmt > FORMAT_VERSION:
            raise CatalogError(
                f"this catalog needs a newer avianki (catalog format {fmt}, this version reads "
                f"{FORMAT_VERSION}); run pip install -U avianki"
            )
        if fmt != FORMAT_VERSION or isinstance(fmt, bool):
            raise CatalogError(f"{where}: unsupported catalog format {fmt!r}")
        try:
            manifest = Manifest.from_dict(obj)
        except _SHAPE_ERRORS as exc:
            raise CatalogError(f"{where} is malformed: {type(exc).__name__}: {exc}") from exc
        self._manifest = manifest
        return manifest

    def _current_manifest(self) -> Manifest:
        return self._manifest if self._manifest is not None else self.manifest()

    def find_region(self, query: str) -> RegionRef:
        """The region whose slug (``us-ma``, any case) or display name (``Massachusetts``,
        case- and accent-insensitive) is ``query``.

        Two shorthands are also accepted, after the exact matches: a well-known alias
        (``DC``, ``Washington DC``) and a bare state or province code (``ma``, ``qc``) when
        exactly one region ends in it.

        Raises `RegionNotFound` (with close matches) or `AmbiguousRegion` (two regions share
        the name or the code).
        """
        regions = self._current_manifest().regions
        key = fold(query)
        for ref in regions:
            if ref.slug == key:
                return ref
        by_name = [ref for ref in regions if fold(ref.name) == key]
        if len(by_name) == 1:
            return by_name[0]
        if by_name:
            raise AmbiguousRegion(query, by_name)
        alias = _ALIASES.get(_plain(key))
        if alias is not None:
            for ref in regions:
                if ref.slug == alias:
                    return ref
        if len(key) == 2 and key.isalpha():
            by_code = [ref for ref in regions if ref.slug.partition("-")[2] == key]
            if len(by_code) == 1:
                return by_code[0]
            if by_code:
                raise AmbiguousRegion(query, by_code)
        raise RegionNotFound(query, self._suggest(key, regions))

    @staticmethod
    def _suggest(key: str, regions: Sequence[RegionRef]) -> list[RegionRef]:
        labels: dict[str, RegionRef] = {}
        for ref in regions:
            labels.setdefault(ref.slug, ref)
            labels.setdefault(fold(ref.name), ref)
        found: list[RegionRef] = []
        if len(key) >= 3:
            found += [ref for label, ref in labels.items() if key in label]
        for label in difflib.get_close_matches(key, list(labels), n=_MAX_SUGGESTIONS, cutoff=0.6):
            found.append(labels[label])
        unique = list(dict.fromkeys(found))  # keeps order; rows are hashable (frozen)
        return unique[:_MAX_SUGGESTIONS]

    def _load_json(self, name: str) -> Any:
        """A hashed JSON file (region or species), memoised, and cached on disk by name.

        The name embeds a hash of the canonical content, so a mismatch is corruption (or the
        wrong file) and is never trusted: a bad cached copy is dropped and re-fetched, a bad
        download raises.
        """
        if name in self._json:
            return self._json[name]
        if not _JSON_NAME.match(name):
            raise CatalogError(f"not a catalog file name: {name!r}")
        cached = self.cache_dir / name
        obj: Any = None
        if cached.is_file():
            try:
                candidate = json.loads(cached.read_bytes())
            except (OSError, ValueError):
                candidate = None
            if candidate is not None and _hash_matches(name, candidate):
                obj = candidate
            else:
                log.warning("cached %s is damaged; fetching it again", cached)
        if obj is None:
            data = self._read(name)
            try:
                obj = json.loads(data)
            except (ValueError, UnicodeDecodeError) as exc:
                raise CatalogError(f"{self._where(name)} is not valid JSON: {exc}") from exc
            if not _hash_matches(name, obj):
                raise CatalogError(
                    f"{self._where(name)}: content does not match the hash in its name"
                )
            try:
                _write_atomic(cached, data)
            except OSError as exc:  # the cache is an optimisation here
                log.warning("could not cache %s: %s", cached, exc)
        self._json[name] = obj
        return obj

    def region(self, ref: RegionRef) -> RegionFile:
        """A region's species in rank order with monthly frequencies. Fetched once per client."""
        cached = self._parsed.get(ref.file)
        if isinstance(cached, RegionFile) and cached.slug == ref.slug:
            return cached
        obj = self._load_json(ref.file)
        try:
            region = RegionFile.from_dict(obj)
        except _SHAPE_ERRORS as exc:
            raise CatalogError(f"{ref.file} is malformed: {type(exc).__name__}: {exc}") from exc
        if region.slug != ref.slug:
            raise CatalogError(
                f"{ref.file} has slug {region.slug!r} but the manifest lists {ref.slug!r}"
            )
        self._parsed[ref.file] = region
        return region

    def species(self) -> SpeciesFile:
        """Every species' names and chosen media. Fetched once per client."""
        name = self._current_manifest().species_file
        cached = self._parsed.get(name)
        if isinstance(cached, SpeciesFile):
            return cached
        obj = self._load_json(name)
        try:
            species = SpeciesFile.from_dict(obj)
        except _SHAPE_ERRORS as exc:
            raise CatalogError(f"{name} is malformed: {type(exc).__name__}: {exc}") from exc
        self._parsed[name] = species
        return species

    # -- media ----------------------------------------------------------------------

    def media(self, file: str) -> Path:
        """The local path of ``media/<hash>.<ext>``, downloading it into the cache if needed.

        The bytes must hash to the name (`format.media_filename`); otherwise nothing is
        written and `CatalogError` is raised. A file already in the cache is hashed again
        before it is used (about 16 MB for a full deck, which is cheap): a copy that no longer
        matches its name, from a disk fault or a half-finished edit, is deleted and fetched
        again, so damaged media never goes into a deck.
        """
        m = _MEDIA_NAME.match(file)
        if m is None:
            raise CatalogError(f"not a catalog media file name: {file!r}")
        dest = self.cache_dir / file
        if dest.is_file():
            if self._cached_media_ok(dest, file, m.group(1)):
                return dest
            log.warning("cached %s is damaged; downloading it again", dest)
            try:
                dest.unlink()
            except OSError:
                pass  # the download below replaces it atomically
        try:
            data = self._read(file)
        except CatalogFetchError as exc:
            if exc.status == 404:
                raise MediaNotFound(
                    f"{self._where(file)} was not found (HTTP 404). The catalog was probably "
                    "updated while your deck was being built; try again",
                    404,
                ) from exc
            raise
        actual = media_filename(data, m.group(1))
        if actual != file:
            raise CatalogError(
                f"{self._where(file)}: bytes do not match the digest in the name "
                f"(they hash to {actual})"
            )
        try:
            _write_atomic(dest, data)
        except OSError as exc:
            raise CacheWriteError(f"cannot write {dest}: {exc}") from exc
        return dest

    @staticmethod
    def _cached_media_ok(path: Path, file: str, ext: str) -> bool:
        try:
            return media_filename(path.read_bytes(), ext) == file
        except OSError:
            return False

    def media_many(
        self,
        files: Iterable[str],
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Path]:
        """`media` for each distinct file, in order, one at a time.

        ``progress(done, total)`` is called once with ``done=0`` and again after each file, so
        a bar can be drawn from the start. Files already cached count as done immediately.
        """
        names = list(dict.fromkeys(files))
        total = len(names)
        if progress is not None:
            progress(0, total)
        out: dict[str, Path] = {}
        for done, name in enumerate(names, start=1):
            out[name] = self.media(name)
            if progress is not None:
                progress(done, total)
        return out
