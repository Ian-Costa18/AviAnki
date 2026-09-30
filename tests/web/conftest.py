"""Fixtures for the browser tests: one static server, and one browser per engine.

Everything here skips (never fails) when Playwright or a browser build is not installed;
CI installs them (``playwright install --with-deps chromium webkit``).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from web_support import serve

ENGINES = ("chromium", "webkit")


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    with serve() as url:
        yield url


@pytest.fixture(scope="session")
def _playwright() -> Iterator[object]:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def _browsers(_playwright) -> Iterator[dict[str, object]]:
    """Launched browsers by engine, started lazily; an engine that cannot start is skipped."""
    launched: dict[str, object] = {}
    try:
        yield launched
    finally:
        for browser in launched.values():
            browser.close()  # type: ignore[attr-defined]


def _browser(name: str, _playwright, _browsers):
    if name not in _browsers:
        args = ["--enable-precise-memory-info"] if name == "chromium" else []
        try:
            _browsers[name] = getattr(_playwright, name).launch(args=args)
        except Exception as exc:  # noqa: BLE001 - Playwright raises its own Error for a missing build
            pytest.skip(f"{name} is not available: {str(exc).splitlines()[0]}")
    return _browsers[name]


def _page(browser, base_url: str):
    page = browser.new_page()
    page.on("pageerror", lambda exc: (_ for _ in ()).throw(AssertionError(f"page error: {exc}")))
    page.goto(f"{base_url}/__blank.html")
    return page


@pytest.fixture
def chromium_page(base_url, _playwright, _browsers) -> Iterator[object]:
    page = _page(_browser("chromium", _playwright, _browsers), base_url)
    yield page
    page.close()


@pytest.fixture(params=ENGINES)
def page(request, base_url, _playwright, _browsers) -> Iterator[object]:
    """A blank page on the app's origin, in each engine."""
    page = _page(_browser(request.param, _playwright, _browsers), base_url)
    yield page
    page.close()
