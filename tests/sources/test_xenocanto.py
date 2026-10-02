"""Tests for the xeno-canto lookup and the Commons audio ordering it drives (ADR 0031, section 3).

No network: a fake session stands in for requests. The key goes in the URL, so several tests
prove it never reaches a cache entry, an error message, a log line or a build-report note.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import requests
from commons_fakes import CommonsSession, Pool, audio_page, make_client, table_of

from avianki.core.http import HttpClient
from avianki.sources.commons import CommonsSource
from avianki.sources.commons import xenocanto as xc
from avianki.sources.commons.xenocanto import XcInfo, XenoCantoLookup, order_key, parse_recordings
from avianki.sources.contract import AssetKind

KEY = "sekrit-xc-key-0123456789"
SCI = "Turdus migratorius"


def rec(number: int, q: str = "A", also: list[str] | None = None) -> dict[str, Any]:
    return {"id": str(number), "q": q, "also": [] if also is None else also, "gen": "Turdus"}


class XcSession:
    """A requests-like session answering the xeno-canto API from ``db`` (number -> recording)."""

    def __init__(self, db: Mapping[int, dict[str, Any]], *, fail: BaseException | tuple[int, bytes] | None = None):
        self.db = db
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: Mapping[str, Any] | None = None, **_: Any) -> Any:
        params = dict(params or {})
        self.calls.append((url, params))
        assert url == xc.API, url
        if isinstance(self.fail, BaseException):
            # What requests does: the full URL, key included, in the message.
            raise requests.ConnectionError(f"HTTPSConnectionPool: {self.fail} for {url}?query={params['query']}&key={params['key']}")
        if self.fail is not None:
            status, body = self.fail
            return _Reply(status, body)
        query = str(params["query"])
        assert query.startswith("nr:")
        numbers = [int(n) for n in query[3:].split(",")]
        assert len(numbers) <= xc.BATCH
        found = [self.db[n] for n in numbers if n in self.db]
        return _Reply(200, json.dumps({"numRecordings": str(len(found)), "recordings": found}).encode())


class _Reply:
    def __init__(self, status: int, body: bytes) -> None:
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": "application/json"}


def lookup(session: XcSession, key: str | None = KEY, cache_dir: Path | None = None) -> XenoCantoLookup:
    client = HttpClient(cache_dir=cache_dir, session=session, sleep=lambda _s: None, max_retries=0)  # type: ignore[arg-type]
    return XenoCantoLookup(client, key)


# ── parsing and the order key ────────────────────────────────────────────────


def test_parse_reads_grade_and_background_count():
    got = parse_recordings({"recordings": [rec(86756, "A", ["Dumetella carolinensis"]), rec(5, "E"), rec(6, "no score")]})
    assert got["86756"] == XcInfo("A", 1)
    assert got["5"] == XcInfo("E", 0)
    assert got["6"] == XcInfo(None, 0)


def test_parse_skips_junk_entries_and_tolerates_a_missing_also():
    got = parse_recordings({"recordings": ["x", {"q": "A"}, {"id": "abc"}, {"id": "9", "q": "b"}]})
    assert got == {"9": XcInfo("B", None)}


@pytest.mark.parametrize("payload", [[], {"error": "client_error", "message": "bad"}, {"recordings": "none"}, None])
def test_parse_refuses_an_answer_with_no_recordings_list(payload):
    from avianki.core.http import SourceError

    with pytest.raises(SourceError):
        parse_recordings(payload)


def test_order_key_puts_clean_first_then_grade_then_unknown():
    infos = {
        "clean-B": XcInfo("B", 0),
        "clean-A": XcInfo("A", 0),
        "clean-none": XcInfo(None, 0),
        "dirty-A": XcInfo("A", 2),
        "dirty-E": XcInfo("E", 1),
        "unlisted": XcInfo("A", None),
    }
    ordered = sorted([*infos, "unknown"], key=lambda n: order_key(infos.get(n)))
    assert ordered == ["clean-A", "clean-B", "clean-none", "dirty-A", "unlisted", "dirty-E", "unknown"]


# ── the lookup ───────────────────────────────────────────────────────────────


def test_lookup_batches_by_number_and_caches_by_number():
    session = XcSession({n: rec(n) for n in range(1, 121)})
    look = lookup(session)
    got = look.metadata([str(n) for n in range(1, 121)])
    assert len(got) == 120
    assert len(session.calls) == 3  # 50 + 50 + 20
    assert session.calls[0][1]["query"].startswith("nr:1,2,3,")
    look.metadata(["3", "70", "500"])  # 500 is unknown to xeno-canto; asked once, never again
    look.metadata(["500"])
    assert len(session.calls) == 4
    assert look.metadata(["500"]) == {}


def test_a_recording_xeno_canto_does_not_know_is_left_out_not_an_error():
    look = lookup(XcSession({1: rec(1)}))
    assert look.metadata(["1", "2"]) == {"1": XcInfo("A", 0)}
    assert look.active


def test_no_key_means_no_request_one_warning_and_one_note(caplog):
    session = XcSession({1: rec(1)})
    look = lookup(session, key=None)
    with caplog.at_level(logging.WARNING, logger="bird_deck"):
        assert look.metadata(["1"]) == {}
        assert look.metadata(["2"]) == {}
    assert session.calls == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    [note] = look.notes()
    assert "XC_API_KEY is not set" in note and "default order" in note


def test_no_key_and_nothing_to_look_up_is_silent(caplog):
    look = lookup(XcSession({}), key="")
    with caplog.at_level(logging.WARNING, logger="bird_deck"):
        assert look.metadata([]) == {}
    assert caplog.records == [] and look.notes() == []


@pytest.mark.parametrize(
    "fail",
    [
        requests.ReadTimeout("timed out"),
        (401, b'{"error":"client_error","message":"Missing or invalid key"}'),
        (500, b"upstream broke"),
        (200, b"<html>not json</html>"),
        (200, b'{"error":"client_error","message":"nope"}'),
    ],
    ids=["timeout", "401", "500", "bad-json", "no-recordings"],
)
def test_any_failure_falls_back_with_one_warning_one_note_and_no_more_requests(fail, caplog):
    session = XcSession({1: rec(1)}, fail=fail)
    look = lookup(session)
    with caplog.at_level(logging.DEBUG, logger="bird_deck"):
        assert look.metadata(["1"]) == {}  # never raises
        assert look.metadata(["2"]) == {}
    assert len(session.calls) == 1  # off for the rest of the run
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    [note] = look.notes()
    assert "lookup failed" in note and "default order" in note
    assert not look.active


def test_a_success_leaves_a_count_note():
    look = lookup(XcSession({1: rec(1)}))
    look.metadata(["1", "2"])
    assert look.notes() == ["xeno-canto: metadata for 1 of 2 Commons recordings looked up in 1 requests (ADR 0031)"]


# ── the key stays out of caches, errors, logs and notes ──────────────────────


def _everything_on_disk(root: Path) -> str:
    """All file names and contents under ``root``, as one string."""
    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        parts.append(str(path.relative_to(root)))
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def test_the_key_is_in_the_request_but_not_in_a_cache_entry(tmp_path):
    session = XcSession({1: rec(1)})
    look = lookup(session, cache_dir=tmp_path)
    look.metadata(["1"])
    assert session.calls[0][1]["key"] == KEY  # it is sent
    on_disk = _everything_on_disk(tmp_path)
    assert (tmp_path / "xeno-canto").is_dir() and "meta.json" in on_disk  # something was cached
    assert KEY not in on_disk


def test_the_cache_key_does_not_depend_on_the_key(tmp_path):
    first = XcSession({1: rec(1)})
    lookup(first, key="first-key", cache_dir=tmp_path).metadata(["1"])
    second = XcSession({1: rec(1)})
    got = lookup(second, key="rotated-key", cache_dir=tmp_path).metadata(["1"])
    assert got == {"1": XcInfo("A", 0)}
    assert second.calls == []  # answered from the entry the first key wrote


@pytest.mark.parametrize(
    "fail",
    [requests.ConnectionError("boom"), (401, f'{{"message": "bad key {KEY}"}}'.encode())],
    ids=["transport-error", "error-body-echoes-key"],
)
def test_the_key_is_in_no_error_message_log_line_or_note(fail, caplog, tmp_path):
    session = XcSession({}, fail=fail)
    look = lookup(session, cache_dir=tmp_path)
    with caplog.at_level(logging.DEBUG, logger="bird_deck"):
        look.metadata(["1"])
    assert session.calls
    texts = [r.getMessage() for r in caplog.records] + look.notes()
    assert texts and all(KEY not in t for t in texts)
    assert KEY not in _everything_on_disk(tmp_path)


def test_a_raised_http_error_carries_no_key_in_message_cause_or_context():
    from avianki.core.http import SourceError

    session = XcSession({}, fail=requests.ConnectionError("boom"))
    client = HttpClient(cache_dir=None, session=session, sleep=lambda _s: None, max_retries=0)  # type: ignore[arg-type]
    with pytest.raises(SourceError) as info:
        client.get_json(xc.NAME, xc.LIMITS, xc.API, {"query": "nr:1", "key": KEY}, secret_params=("key",))
    err = info.value
    assert KEY not in str(err) and "<redacted>" in str(err)
    assert err.__cause__ is None and err.__context__ is None


def test_a_raised_status_error_scrubs_an_echoed_key():
    from avianki.core.http import HttpError

    session = XcSession({}, fail=(403, f"forbidden for key={KEY}".encode()))
    client = HttpClient(cache_dir=None, session=session, sleep=lambda _s: None, max_retries=0)  # type: ignore[arg-type]
    with pytest.raises(HttpError) as info:
        client.get(xc.NAME, xc.LIMITS, xc.API, {"query": "nr:1", "key": KEY}, secret_params=["key"])
    assert KEY not in str(info.value) and info.value.status == 403


# ── Commons audio ordering ───────────────────────────────────────────────────


def xc_title(n: int | None, label: str = "x") -> str:
    return f"Turdus migratorius - American Robin - XC{n}.ogg" if n is not None else f"Robin {label}.ogg"


def commons_with(files: list[dict[str, Any]], session: XcSession, key: str | None = KEY, cache_dir: Path | None = None):
    pool = Pool()
    pool.categoryinfo.append({"pageid": 1, "ns": 14, "title": f"Category:Audio files of {SCI}",
                              "categoryinfo": {"size": len(files), "pages": 0, "files": len(files), "subcats": 0,
                                               "hidden": False}})
    pool.members[f"Category:Audio files of {SCI}"] = [files]  # type: ignore[assignment]
    pool.commons_pages += files
    client = HttpClient(
        cache_dir=cache_dir, session=_Router(CommonsSession(pool), session), sleep=lambda _s: None, max_retries=0  # type: ignore[arg-type]
    )
    look = XenoCantoLookup(client, key)
    return CommonsSource(client, table_of((SCI, "Robin")), look), look


class _Router:
    """Sends xeno-canto URLs to the xeno-canto session and the rest to the Commons fake."""

    def __init__(self, commons: CommonsSession, xcs: XcSession) -> None:
        self.commons, self.xcs = commons, xcs

    def get(self, url: str, **kw: Any) -> Any:
        return (self.xcs if url == xc.API else self.commons).get(url, **kw)


def audio(src: CommonsSource, limit: int = 10):
    return src.candidates(["turdus-migratorius"], AssetKind.AUDIO, limit)["turdus-migratorius"]


def files() -> list[dict[str, Any]]:
    # Existing rank (page id, equal duration and licence): 11 (dirty A), 12 (clean B), 13 (unknown),
    # 14 (clean A), 15 (no xeno-canto number), 16 (dirty, grade D), 17 (the .mp3 twin of 12).
    return [
        audio_page(11, xc_title(1001), SCI),
        audio_page(12, xc_title(1002), SCI),
        audio_page(13, xc_title(1003), SCI),
        audio_page(14, xc_title(1004), SCI),
        audio_page(15, xc_title(None), SCI),
        audio_page(16, xc_title(1006), SCI),
        audio_page(17, xc_title(1002).replace(".ogg", ".mp3"), SCI, mime="audio/mpeg"),
    ]


DB = {
    1001: rec(1001, "A", ["Cyanocitta cristata"]),
    1002: rec(1002, "B"),
    1004: rec(1004, "A"),
    1006: rec(1006, "D", ["Poecile atricapillus", "Sitta carolinensis"]),
}


def test_commons_audio_is_ordered_clean_first_then_grade_then_the_existing_rank():
    src, _ = commons_with(files(), XcSession(DB))
    got = audio(src)
    # Clean A (1004), clean B (1002; its .mp3 twin is dropped), then the rest by grade:
    # dirty A (1001), dirty D (1006), then unknown (1003), then no number at all (page 15).
    assert [c.token for c in got] == ["M14", "M12", "M11", "M16", "M13", "M15"]
    by_token = {c.token: c for c in got}
    assert (by_token["M14"].xc_quality, by_token["M14"].xc_background) == ("A", 0)
    assert (by_token["M11"].xc_quality, by_token["M11"].xc_background) == ("A", 1)
    assert (by_token["M16"].xc_quality, by_token["M16"].xc_background) == ("D", 2)
    assert (by_token["M13"].xc_quality, by_token["M13"].xc_background) == (None, None)
    assert (by_token["M15"].xc_quality, by_token["M15"].xc_background) == (None, None)


def test_the_limit_applies_after_the_xeno_canto_order():
    src, _ = commons_with(files(), XcSession(DB))
    assert [c.token for c in audio(src, limit=2)] == ["M14", "M12"]


def test_it_orders_and_never_gates():
    src, _ = commons_with(files(), XcSession(DB))
    assert {c.token for c in audio(src)} == {"M11", "M12", "M13", "M14", "M15", "M16"}  # all but the twin


def test_without_a_key_the_existing_order_stands_and_a_note_says_so(caplog):
    session = XcSession(DB)
    src, look = commons_with(files(), session, key=None)
    with caplog.at_level(logging.WARNING, logger="bird_deck"):
        got = audio(src)
    assert [c.token for c in got] == ["M11", "M12", "M13", "M14", "M15", "M16"]
    assert all(c.xc_quality is None and c.xc_background is None for c in got)
    assert session.calls == []
    assert len(src.notes()) == 1 and "XC_API_KEY is not set" in src.notes()[0]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_when_the_api_fails_the_existing_order_stands():
    src, _ = commons_with(files(), XcSession(DB, fail=requests.ReadTimeout("slow")))
    assert [c.token for c in audio(src)] == ["M11", "M12", "M13", "M14", "M15", "M16"]
    assert len(src.notes()) == 1 and "lookup failed" in src.notes()[0]


def test_a_commons_source_with_no_lookup_is_unchanged_and_has_no_notes():
    pool = Pool()
    src = CommonsSource(make_client(CommonsSession(pool)), table_of((SCI, "Robin")))  # type: ignore[arg-type]
    assert src.notes() == []


def test_the_hints_never_reach_the_catalog_record():
    src, _ = commons_with(files(), XcSession(DB))
    for c in audio(src):
        assert "xc_" not in json.dumps(c.record.to_dict())


# ── live ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_the_live_api_knows_the_blue_jay_recording() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("XC_API_KEY", "").strip()
    if not key:
        pytest.skip("XC_API_KEY is not set")
    look = XenoCantoLookup(HttpClient(cache_dir=None), key)
    got = look.metadata(["86756"])
    assert got["86756"] == XcInfo("A", 1)  # q=A, also=["Dumetella carolinensis"]
    assert look.active
