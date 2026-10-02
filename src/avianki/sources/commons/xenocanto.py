"""xeno-canto metadata for Commons audio candidates (ADR 0031, section 3).

About four in five Commons bird recordings mirror a xeno-canto recording, and xeno-canto
records two things per recording that Commons doesn't: a quality grade (A to E) and the list of
background species (``also``). This module looks both up so `CommonsSource` can order its audio
candidates. It is **metadata only**: nothing is ever downloaded from xeno-canto, and the answer
orders candidates, it never rejects one.

The API (v3) wants a key in the URL, ``?query=nr:<number>&key=<key>``. The key is therefore
passed to `HttpClient` as a *secret param*, which keeps it out of the response-cache key and out
of every error message; this module scrubs it from its own notes and log lines as well. Several
recordings go in one request as ``nr:1,2,3`` (checked live; ``OR`` and ``|`` are refused), at most
`BATCH` per request.

No key, or any failure (HTTP error, timeout, malformed answer): nothing is looked up for the rest
of the run, one warning is logged and one note is left for the build report. Candidates then keep
their existing order. A lookup can never fail a build.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from avianki.core.http import HttpClient, Limits, SourceError

log = logging.getLogger("bird_deck")

NAME = "xeno-canto"  # the HttpClient source name: its own throttle and cache folder
API = "https://xeno-canto.org/api/3/recordings"
SECRET = "XC_API_KEY"
BATCH = 50  # recordings per request (keeps the URL short)
GRADES = "ABCDE"

# One request a second is the pace xeno-canto's API terms ask for; a species costs one or two.
LIMITS = Limits(requests_per_second=1, max_concurrency=1, daily_request_budget=None, needs_secret=SECRET)


@dataclass(frozen=True)
class XcInfo:
    """What xeno-canto says about one recording."""

    quality: str | None  # "A" to "E"; None for "no score" or anything else
    background: int | None  # background species named in ``also``; None when the answer has no list


def order_key(info: XcInfo | None) -> tuple[int, int]:
    """Sort key, best first: ``(0 or 1, grade)``.

    ``0`` only for a recording xeno-canto says has no background species. Everything else is
    ``1``: a recording with background species, and a recording nothing is known about. Within
    that, grade A to E, then no grade. So an unknown recording sorts after every known-clean one,
    and (because the existing rank key breaks ties) keeps its relative place among the rest.
    """
    if info is None:
        return (1, len(GRADES))
    clean = 0 if info.background == 0 else 1
    grade = GRADES.index(info.quality) if info.quality in tuple(GRADES) else len(GRADES)
    return (clean, grade)


class XenoCantoLookup:
    """Per-run lookup of xeno-canto recordings by number, cached by number.

    ``api_key=None`` is a lookup that is already off: it notes why on first use.
    """

    def __init__(self, client: HttpClient, api_key: str | None) -> None:
        self._client = client
        self._key = api_key or None
        self._known: dict[str, XcInfo] = {}
        self._asked: set[str] = set()  # numbers sent, found or not: never asked twice
        self._off: str | None = None if self._key else f"{SECRET} is not set"
        self._warned = False
        self.requests = 0

    @property
    def active(self) -> bool:
        return self._off is None

    def metadata(self, numbers: Iterable[str]) -> dict[str, XcInfo]:
        """What xeno-canto knows of each number (as in ``parse.recording_key``).

        Numbers it has no record of, and every number once the lookup is off, are left out.
        Never raises.
        """
        wanted = list(dict.fromkeys(n for n in numbers if n))
        todo = sorted((n for n in wanted if n not in self._asked), key=lambda n: int(n))
        if todo and self._off is not None and not self._warned:
            self._warn()
        if todo and self._off is None:
            for i in range(0, len(todo), BATCH):
                if not self._fetch(todo[i : i + BATCH]):
                    break
        return {n: self._known[n] for n in wanted if n in self._known}

    def notes(self) -> list[str]:
        """Zero or one lines for the build report."""
        if self._off is not None:
            if not self._warned:
                return []  # never needed: a build with no Commons audio says nothing
            return [f"xeno-canto: {self._off}; Commons audio candidates keep their default order (ADR 0031)"]
        if self.requests:
            return [f"xeno-canto: metadata for {len(self._known)} of {len(self._asked)} Commons recordings "
                    f"looked up in {self.requests} requests (ADR 0031)"]
        return []

    # ── internals ────────────────────────────────────────────────────────────

    def _fetch(self, numbers: Sequence[str]) -> bool:
        assert self._key is not None
        self.requests += 1
        try:
            payload = self._client.get_json(
                NAME, LIMITS, API, {"query": "nr:" + ",".join(numbers), "key": self._key}, secret_params=("key",)
            )
            found = parse_recordings(payload)
        except (SourceError, ValueError, TypeError, KeyError) as exc:
            # The client already scrubs; this covers a parse error that quotes the answer.
            reason = str(exc).replace(self._key, "<redacted>") or type(exc).__name__
            self._off = f"the lookup failed ({type(exc).__name__}: {reason})"
            self._warn()
            return False
        self._asked.update(numbers)
        self._known.update({n: info for n, info in found.items() if n in numbers})
        return True

    def _warn(self) -> None:
        self._warned = True
        log.warning("xeno-canto: %s; Commons audio keeps its default order for this run", self._off)


def parse_recordings(payload: Any) -> dict[str, XcInfo]:
    """``{number: XcInfo}`` from an API v3 answer. A body without ``recordings`` is an error.

    Entries that aren't objects or have no id are skipped: a missing recording is not an error.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("recordings"), list):
        error = payload.get("message") if isinstance(payload, dict) else None
        raise SourceError(f"xeno-canto: unexpected answer{f': {error}' if isinstance(error, str) else ''}")
    out: dict[str, XcInfo] = {}
    for rec in payload["recordings"]:
        if not isinstance(rec, dict):
            continue
        try:
            number = str(int(str(rec.get("id")).strip()))
        except ValueError:
            continue
        grade = str(rec.get("q") or "").strip().upper()
        also = rec.get("also")
        background = (
            sum(1 for name in also if isinstance(name, str) and name.strip()) if isinstance(also, list) else None
        )
        out[number] = XcInfo(quality=grade if grade in tuple(GRADES) else None, background=background)
    return out
