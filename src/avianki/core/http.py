"""The one HTTP client every catalog source goes through (ADR 0007, Q6).

Sources are pure: they declare `Limits` and build requests; this module owns
everything that touches clocks, sleeps or disk — per-source throttling, a daily
request budget persisted on disk, retry that honours ``Retry-After``, an on-disk
response cache keyed by ``(source, request)``, and the one User-Agent.

Requests are made serially. ``Limits.max_concurrency`` is recorded but not yet
used to parallelise; serial satisfies every current source (Wikimedia and
iNaturalist both ask for 1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

import requests

log = logging.getLogger("bird_deck")

REPO_URL = "https://github.com/Ian-Costa18/AviAnki"
_SOURCE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Limits:
    """What a source declares about how it may be called (ADR 0007)."""

    requests_per_second: float
    max_concurrency: int  # Wikimedia: 1 (serial)
    daily_request_budget: int | None  # iNaturalist: 10_000
    needs_secret: str | None  # env var name; checked at startup


class SourceError(Exception):
    """Base for every failure a source call can raise. Never means "nothing found"."""


class BudgetExhausted(SourceError):
    """The source's daily request budget is spent; raised before sending."""


class HttpError(SourceError):
    """An HTTP error status (after retries, where retrying applies)."""

    def __init__(self, status: int, url: str, message: str = "") -> None:
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} for {url}" + (f": {message}" if message else ""))


def default_user_agent() -> str:
    """``AviAnki-catalog/<version> (<repo url>)`` — never an email address."""
    try:
        ver = version("avianki")
    except PackageNotFoundError:  # pragma: no cover - only when run from a bare checkout
        ver = "0+unknown"
    return f"AviAnki-catalog/{ver} ({REPO_URL})"


class _Session(Protocol):
    def get(self, url: str | bytes, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class Response:
    status: int
    url: str
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Parse the body as JSON; a malformed body is a `SourceError`, not an empty result."""
        try:
            return json.loads(self.content)
        except (ValueError, UnicodeDecodeError) as e:
            raise SourceError(f"malformed JSON from {self.url}: {e}") from e


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HttpClient:
    """Throttled, budgeted, retrying, caching GET client.

    ``cache_dir=None`` disables both the response cache and the on-disk budget
    ledger (the budget is then tracked in memory for this process only).
    ``clock``/``sleep``/``now`` are injectable so tests run instantly.
    """

    def __init__(
        self,
        cache_dir: Path | None,
        user_agent: str | None = None,
        *,
        session: _Session | None = None,
        timeout: float = 30.0,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        max_retry_after: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.cache_dir = cache_dir
        self.user_agent = user_agent or default_user_agent()
        self._session: _Session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_retry_after = max_retry_after
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._last_sent: dict[str, float] = {}
        self._memory_ledger: dict[str, dict[str, int]] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def today(self) -> str:
        """Today's UTC date as ISO 8601 (``2026-09-28``), from the injected clock.

        Sources are pure and may not read the clock; this is how they stamp
        ``AssetRecord.retrieved_at``.
        """
        return self._now().astimezone(timezone.utc).date().isoformat()

    def get(
        self,
        source: str,
        limits: Limits,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        cache: bool = True,
    ) -> Response:
        """GET ``url`` on behalf of ``source``. Returns a 2xx response or raises `SourceError`."""
        if not _SOURCE_NAME.match(source):
            raise ValueError(f"invalid source name: {source!r}")
        key = _cache_key(source, "GET", url, params)
        if cache:
            hit = self._cache_read(source, key)
            if hit is not None:
                return hit
        resp = self._send_with_retry(source, limits, url, params)
        if cache:
            self._cache_write(source, key, resp)
        return resp

    def get_json(
        self,
        source: str,
        limits: Limits,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        cache: bool = True,
    ) -> Any:
        """`get` then parse JSON. A malformed body raises and is evicted from the cache."""
        resp = self.get(source, limits, url, params, cache=cache)
        try:
            return resp.json()
        except SourceError:
            self._cache_evict(source, _cache_key(source, "GET", url, params))
            raise

    # ── sending ───────────────────────────────────────────────────────────────

    def _send_with_retry(
        self, source: str, limits: Limits, url: str, params: Mapping[str, Any] | None
    ) -> Response:
        attempt = 0
        while True:
            self._spend_budget(source, limits)
            self._throttle(source, limits)
            log.debug("GET %s %s (source=%s, attempt %d)", url, sorted(params or {}), source, attempt + 1)
            try:
                raw = self._session.get(
                    url,
                    params=dict(params) if params else None,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                if attempt >= self.max_retries:
                    raise SourceError(f"{source}: request to {url} failed after {attempt + 1} attempts: {e}") from e
                wait = self._backoff(attempt)
                log.warning("%s: %s on %s; retry %d/%d in %.1fs", source, type(e).__name__, url,
                            attempt + 1, self.max_retries, wait)
                self._sleep(wait)
                attempt += 1
                continue

            status = int(raw.status_code)
            headers = {str(k): str(v) for k, v in dict(raw.headers or {}).items()}
            if 200 <= status < 300:
                return Response(status=status, url=url, content=bytes(raw.content), headers=headers)
            if status not in _RETRY_STATUSES:
                raise HttpError(status, url, _snippet(raw.content))
            if attempt >= self.max_retries:
                raise HttpError(status, url, f"gave up after {attempt + 1} attempts")
            wait = self._backoff(attempt)
            retry_after = self._retry_after(headers)
            if retry_after is not None:
                if retry_after > self.max_retry_after:
                    raise HttpError(status, url, f"Retry-After {retry_after:.0f}s exceeds cap")
                wait = max(wait, retry_after)
            log.warning("%s: HTTP %d on %s; retry %d/%d in %.1fs", source, status, url,
                        attempt + 1, self.max_retries, wait)
            self._sleep(wait)
            attempt += 1

    def _backoff(self, attempt: int) -> float:
        return self.backoff_base * (2**attempt)

    def _retry_after(self, headers: Mapping[str, str]) -> float | None:
        value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
        if value is None:
            return None
        value = value.strip()
        if value.isdigit():
            return float(value)
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - self._now()).total_seconds())

    def _throttle(self, source: str, limits: Limits) -> None:
        interval = 1.0 / limits.requests_per_second if limits.requests_per_second > 0 else 0.0
        last = self._last_sent.get(source)
        if last is not None:
            wait = last + interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_sent[source] = self._clock()

    # ── daily budget ──────────────────────────────────────────────────────────

    def _ledger_path(self, day: str) -> Path | None:
        return self.cache_dir / "_budget" / f"{day}.json" if self.cache_dir is not None else None

    def _read_ledger(self, day: str) -> dict[str, int]:
        path = self._ledger_path(day)
        if path is None:
            return self._memory_ledger.setdefault(day, {})
        if not path.exists():
            return {}
        return {str(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}

    def _write_ledger(self, day: str, ledger: dict[str, int]) -> None:
        path = self._ledger_path(day)
        if path is None:
            self._memory_ledger[day] = ledger
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _spend_budget(self, source: str, limits: Limits) -> None:
        """Count one real request against today's (UTC) budget, or raise before sending."""
        day = self._now().astimezone(timezone.utc).date().isoformat()
        ledger = self._read_ledger(day)
        used = ledger.get(source, 0)
        budget = limits.daily_request_budget
        if budget is not None and used >= budget:
            raise BudgetExhausted(f"{source}: daily budget of {budget} requests spent for {day}")
        ledger[source] = used + 1
        self._write_ledger(day, ledger)

    # ── cache ─────────────────────────────────────────────────────────────────

    def _cache_paths(self, source: str, key: str) -> tuple[Path, Path] | None:
        if self.cache_dir is None:
            return None
        base = self.cache_dir / source
        return base / f"{key}.body", base / f"{key}.meta.json"

    def _cache_read(self, source: str, key: str) -> Response | None:
        paths = self._cache_paths(source, key)
        if paths is None or not (paths[0].exists() and paths[1].exists()):
            return None
        body, meta_path = paths
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return Response(
                status=int(meta["status"]),
                url=str(meta["url"]),
                content=body.read_bytes(),
                headers=dict(meta.get("headers", {})),
                from_cache=True,
            )
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("%s: unreadable cache entry %s; refetching", source, key)
            return None

    def _cache_write(self, source: str, key: str, resp: Response) -> None:
        paths = self._cache_paths(source, key)
        if paths is None:
            return
        body, meta_path = paths
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_bytes(resp.content)
        # Params are deliberately left out: they may carry a secret (Limits.needs_secret).
        keep = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "etag", "last-modified")}
        meta = {
            "source": source,
            "url": resp.url,
            "status": resp.status,
            "headers": keep,
            "fetched_at": self._now().isoformat(),
        }
        meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")

    def _cache_evict(self, source: str, key: str) -> None:
        paths = self._cache_paths(source, key)
        if paths is not None:
            for p in paths:
                p.unlink(missing_ok=True)


def _cache_key(source: str, method: str, url: str, params: Mapping[str, Any] | None) -> str:
    items = sorted((str(k), _param_value(v)) for k, v in (params or {}).items())
    blob = json.dumps([source, method, url, items], separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _param_value(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return str(v)


def _snippet(content: Any, n: int = 200) -> str:
    try:
        return bytes(content[:n]).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
