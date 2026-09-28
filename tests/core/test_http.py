"""Tests for avianki.core.http — no network; a fake session stands in for requests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from avianki.core.http import (
    BudgetExhausted,
    HttpClient,
    HttpError,
    Limits,
    SourceError,
    default_user_agent,
)

URL = "https://api.example.org/v1/things"
FAST = Limits(requests_per_second=1000.0, max_concurrency=1, daily_request_budget=None, needs_secret=None)
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status: int = 200, content: bytes = b'{"ok": true}', headers: dict | None = None):
        self.status_code = status
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected request")
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


class FakeTime:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []
        self.now = NOW

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s
        self.now += timedelta(seconds=s)

    def wall(self) -> datetime:
        return self.now


def make_client(session, tmp_path=None, ft=None, **kw):
    ft = ft or FakeTime()
    client = HttpClient(
        cache_dir=tmp_path,
        session=session,
        clock=ft.clock,
        sleep=ft.sleep,
        now=ft.wall,
        **kw,
    )
    return client, ft


# ── User-Agent ───────────────────────────────────────────────────────────────


def test_default_user_agent_format():
    assert re.fullmatch(
        r"AviAnki-catalog/[0-9][0-9A-Za-z.+-]* \(https://github\.com/Ian-Costa18/AviAnki\)",
        default_user_agent(),
    )


def test_user_agent_and_timeout_sent_on_every_request():
    session = FakeSession(FakeResponse())
    client, _ = make_client(session)
    client.get("src", FAST, URL, {"q": "x"})
    call = session.calls[0]
    assert call["headers"]["User-Agent"] == default_user_agent()
    assert call["timeout"] == 30.0
    assert call["params"] == {"q": "x"}
    assert "@" not in call["headers"]["User-Agent"]


def test_response_parses_json_and_text():
    session = FakeSession(FakeResponse(content=b'{"a": [1, 2]}'))
    client, _ = make_client(session)
    r = client.get("src", FAST, URL)
    assert r.status == 200
    assert r.json() == {"a": [1, 2]}
    assert r.text == '{"a": [1, 2]}'
    assert r.content == b'{"a": [1, 2]}'
    assert r.from_cache is False


def test_malformed_json_raises_source_error():
    session = FakeSession(FakeResponse(content=b"<html>oops"))
    client, _ = make_client(session)
    with pytest.raises(SourceError):
        client.get_json("src", FAST, URL)


# ── Throttle ─────────────────────────────────────────────────────────────────


def test_throttle_spaces_requests_for_same_source():
    slow = Limits(requests_per_second=1.0, max_concurrency=1, daily_request_budget=None, needs_secret=None)
    session = FakeSession(FakeResponse(), FakeResponse(), FakeResponse())
    client, ft = make_client(session)
    client.get("inat", slow, URL, {"p": 1}, cache=False)
    assert ft.sleeps == []
    ft.t += 0.25
    client.get("inat", slow, URL, {"p": 2}, cache=False)
    assert ft.sleeps == [pytest.approx(0.75)]
    client.get("inat", slow, URL, {"p": 3}, cache=False)
    assert ft.sleeps == [pytest.approx(0.75), pytest.approx(1.0)]


def test_throttle_is_per_source():
    slow = Limits(requests_per_second=1.0, max_concurrency=1, daily_request_budget=None, needs_secret=None)
    session = FakeSession(FakeResponse(), FakeResponse())
    client, ft = make_client(session)
    client.get("a", slow, URL, cache=False)
    client.get("b", slow, URL, cache=False)
    assert ft.sleeps == []


# ── Budget ───────────────────────────────────────────────────────────────────


def test_budget_exhaustion_raises_before_sending_and_persists(tmp_path):
    limits = Limits(requests_per_second=1000.0, max_concurrency=1, daily_request_budget=2, needs_secret=None)
    session = FakeSession(FakeResponse(), FakeResponse())
    client, ft = make_client(session, tmp_path)
    client.get("inat", limits, URL, {"p": 1})
    client.get("inat", limits, URL, {"p": 2})
    with pytest.raises(BudgetExhausted):
        client.get("inat", limits, URL, {"p": 3})
    assert len(session.calls) == 2

    # A new process on the same UTC day sees the same ledger.
    session2 = FakeSession(FakeResponse())
    client2, _ = make_client(session2, tmp_path, ft=ft)
    with pytest.raises(BudgetExhausted):
        client2.get("inat", limits, URL, {"p": 4})
    assert session2.calls == []

    # Another source has its own budget.
    client2.get("commons", limits, URL, {"p": 4})
    assert len(session2.calls) == 1


def test_budget_resets_on_next_utc_day(tmp_path):
    limits = Limits(requests_per_second=1000.0, max_concurrency=1, daily_request_budget=1, needs_secret=None)
    session = FakeSession(FakeResponse(), FakeResponse())
    client, ft = make_client(session, tmp_path)
    client.get("inat", limits, URL, {"p": 1})
    ft.now += timedelta(days=1)
    client.get("inat", limits, URL, {"p": 2})
    assert len(session.calls) == 2


def test_budget_exhausted_is_a_source_error():
    assert issubclass(BudgetExhausted, SourceError)
    assert issubclass(HttpError, SourceError)


# ── Retry ────────────────────────────────────────────────────────────────────


def test_retry_after_seconds_is_honoured():
    session = FakeSession(FakeResponse(429, b"slow down", {"Retry-After": "7"}), FakeResponse())
    client, ft = make_client(session, backoff_base=0.5)
    r = client.get("src", FAST, URL)
    assert r.status == 200
    assert len(session.calls) == 2
    assert sum(ft.sleeps) >= 7


def test_retry_after_http_date_is_honoured():
    when = format_datetime(NOW + timedelta(seconds=20), usegmt=True)
    session = FakeSession(FakeResponse(503, b"", {"Retry-After": when}), FakeResponse())
    client, ft = make_client(session, backoff_base=0.5)
    client.get("src", FAST, URL)
    assert sum(ft.sleeps) >= 20


def test_retry_after_beyond_cap_raises_instead_of_waiting():
    session = FakeSession(FakeResponse(429, b"", {"Retry-After": "86400"}))
    client, ft = make_client(session, max_retry_after=300)
    with pytest.raises(HttpError) as exc:
        client.get("src", FAST, URL)
    assert exc.value.status == 429
    assert sum(ft.sleeps) < 300


def test_5xx_retried_then_raised():
    session = FakeSession(*[FakeResponse(502, b"bad gateway") for _ in range(5)])
    client, ft = make_client(session, max_retries=4, backoff_base=1.0)
    with pytest.raises(HttpError) as exc:
        client.get("src", FAST, URL)
    assert exc.value.status == 502
    assert exc.value.url == URL
    assert len(session.calls) == 5
    # exponential backoff: 1, 2, 4, 8
    assert ft.sleeps == [pytest.approx(1.0), pytest.approx(2.0), pytest.approx(4.0), pytest.approx(8.0)]


def test_connection_error_retried_then_raised():
    session = FakeSession(requests.ConnectionError("boom"), requests.Timeout("slow"), requests.ConnectionError("x"))
    client, _ = make_client(session, max_retries=2, backoff_base=0.1)
    with pytest.raises(SourceError):
        client.get("src", FAST, URL)
    assert len(session.calls) == 3


def test_other_transport_errors_are_source_errors():
    session = FakeSession(requests.exceptions.ChunkedEncodingError("cut"))
    client, _ = make_client(session, max_retries=0)
    with pytest.raises(SourceError):
        client.get("src", FAST, URL)


def test_corrupt_cache_metadata_is_a_miss(tmp_path):
    client, _ = make_client(FakeSession(FakeResponse(content=b"one")), tmp_path)
    client.get("src", FAST, URL)
    for meta in tmp_path.rglob("*.meta.json"):
        meta.write_text("{not json", encoding="utf-8")
    client2, _ = make_client(FakeSession(FakeResponse(content=b"two")), tmp_path)
    assert client2.get("src", FAST, URL).content == b"two"


def test_connection_error_then_success():
    session = FakeSession(requests.Timeout("slow"), FakeResponse())
    client, _ = make_client(session, backoff_base=0.1)
    assert client.get("src", FAST, URL).status == 200


def test_404_raised_without_retry():
    session = FakeSession(FakeResponse(404, b"nope"))
    client, ft = make_client(session)
    with pytest.raises(HttpError) as exc:
        client.get("src", FAST, URL)
    assert exc.value.status == 404
    assert len(session.calls) == 1
    assert ft.sleeps == []


def test_retries_count_against_budget(tmp_path):
    limits = Limits(requests_per_second=1000.0, max_concurrency=1, daily_request_budget=2, needs_secret=None)
    session = FakeSession(FakeResponse(500, b""), FakeResponse(500, b""), FakeResponse())
    client, _ = make_client(session, tmp_path, backoff_base=0.1)
    with pytest.raises(BudgetExhausted):
        client.get("inat", limits, URL)
    assert len(session.calls) == 2


# ── Cache ────────────────────────────────────────────────────────────────────


def test_cache_hit_skips_session_and_budget(tmp_path):
    limits = Limits(requests_per_second=1000.0, max_concurrency=1, daily_request_budget=1, needs_secret=None)
    session = FakeSession(FakeResponse(content=b'{"n": 1}'))
    client, _ = make_client(session, tmp_path)
    assert client.get_json("inat", limits, URL, {"b": 2, "a": 1}) == {"n": 1}
    # Param order doesn't matter; budget (1) is already spent, so this must be a hit.
    r = client.get("inat", limits, URL, {"a": 1, "b": 2})
    assert r.from_cache is True
    assert r.json() == {"n": 1}
    assert len(session.calls) == 1
    assert (tmp_path / "inat").is_dir()


def test_cache_survives_new_client(tmp_path):
    session = FakeSession(FakeResponse(content=b"\x89PNG bytes", headers={"Content-Type": "image/png"}))
    client, _ = make_client(session, tmp_path)
    client.get("commons", FAST, URL)
    client2, _ = make_client(FakeSession(), tmp_path)
    r = client2.get("commons", FAST, URL)
    assert r.content == b"\x89PNG bytes"
    assert r.headers["Content-Type"] == "image/png"


def test_cache_is_keyed_by_source(tmp_path):
    session = FakeSession(FakeResponse(content=b"1"), FakeResponse(content=b"2"))
    client, _ = make_client(session, tmp_path)
    assert client.get("a", FAST, URL).content == b"1"
    assert client.get("b", FAST, URL).content == b"2"


def test_cache_false_bypasses(tmp_path):
    session = FakeSession(FakeResponse(content=b"1"), FakeResponse(content=b"2"))
    client, _ = make_client(session, tmp_path)
    client.get("a", FAST, URL)
    assert client.get("a", FAST, URL, cache=False).content == b"2"
    assert len(session.calls) == 2


def test_no_cache_dir_disables_caching():
    session = FakeSession(FakeResponse(content=b"1"), FakeResponse(content=b"2"))
    client, _ = make_client(session, None)
    client.get("a", FAST, URL)
    assert client.get("a", FAST, URL).content == b"2"


def test_errors_are_never_cached(tmp_path):
    session = FakeSession(FakeResponse(404, b"nope"), FakeResponse(content=b"ok"))
    client, _ = make_client(session, tmp_path)
    with pytest.raises(HttpError):
        client.get("a", FAST, URL)
    assert client.get("a", FAST, URL).content == b"ok"
    assert len(session.calls) == 2


def test_malformed_json_is_evicted_from_cache(tmp_path):
    session = FakeSession(FakeResponse(content=b"not json"), FakeResponse(content=b'{"ok": 1}'))
    client, _ = make_client(session, tmp_path)
    with pytest.raises(SourceError):
        client.get_json("a", FAST, URL)
    assert client.get_json("a", FAST, URL) == {"ok": 1}


def test_cache_metadata_holds_no_params(tmp_path):
    session = FakeSession(FakeResponse())
    client, _ = make_client(session, tmp_path)
    client.get("a", FAST, URL, {"key": "sekrit"})
    for f in (tmp_path / "a").iterdir():
        if f.suffix == ".json" and f.name.endswith(".meta.json"):
            assert "sekrit" not in f.read_text(encoding="utf-8")
            assert json.loads(f.read_text(encoding="utf-8"))["status"] == 200


def test_invalid_source_name_rejected(tmp_path):
    client, _ = make_client(FakeSession(), tmp_path)
    with pytest.raises(ValueError):
        client.get("../etc", FAST, URL)


# ── Logging ──────────────────────────────────────────────────────────────────


def test_logs_requests_at_debug_and_retries_at_warning(caplog):
    session = FakeSession(FakeResponse(503, b""), FakeResponse())
    client, _ = make_client(session, backoff_base=0.1)
    logger = __import__("logging").getLogger("bird_deck")
    old = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level("DEBUG", logger="bird_deck"):
            client.get("src", FAST, URL)
    finally:
        logger.propagate = old
    levels = [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "bird_deck"]
    assert any(lvl == "DEBUG" and URL in msg for lvl, msg in levels)
    assert any(lvl == "WARNING" and "503" in msg for lvl, msg in levels)
