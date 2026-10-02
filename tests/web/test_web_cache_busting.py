"""The published layout, in a real browser (ADR 0029, issue #79).

``scripts/assemble_site.py`` moves the app's files under ``v/<version>/``. These tests serve an
assembled site, build a deck from it, and check that every request the page makes for the app
itself lands in that directory. They also check the fallback for a stale cached ``index.html``:
reload once with a fresh query, never in a loop.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from app_support import READY, build, open_app
from web_support import CATALOG_DIR, WEB_DIR, serve

VERSION = "cafe123456"


def _assemble(into: Path) -> Path:
    path = Path(__file__).resolve().parents[2] / "scripts" / "assemble_site.py"
    spec = importlib.util.spec_from_file_location("assemble_site", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    site = into / "_site"
    module.assemble(CATALOG_DIR, site, WEB_DIR, version=VERSION)
    return site


@pytest.fixture(scope="module")
def site_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    site = _assemble(tmp_path_factory.mktemp("assembled"))
    with serve(site / "catalog", site) as url:
        yield url


def test_an_assembled_site_builds_a_deck_from_versioned_files_only(new_context, engine, site_url, tmp_path) -> None:
    context = new_context(engine)
    requested: list[str] = []
    context.on("request", lambda request: requested.append(urlparse(request.url).path))
    page = open_app(context, site_url)

    files = build(page, tmp_path, region="Massachusetts")

    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    assert page.errors == []
    app = [p for p in requested if not p.startswith("/catalog/")]
    assert "/" in app
    assert not [p for p in app if p != "/" and not p.startswith(f"/v/{VERSION}/")], app
    # The ones that are not imports: the note types and sql.js with its wasm.
    for needed in ("js/notetypes.json", "vendor/sql-wasm.js", "vendor/sql-wasm.wasm"):
        assert f"/v/{VERSION}/{needed}" in app, needed


def stale_index(page, site_url: str) -> str:
    """The page as a browser cached it before the last deploy: it names a version that is now deleted."""
    html = page.context.request.get(f"{site_url}/").text()
    stale = html.replace(f"v/{VERSION}/", "v/0ldde9101/")
    assert stale != html
    return stale


def _serve_stale_index(page, stale: str, times: int | None) -> list[str]:
    """Answer the page's own address with ``stale`` for the first ``times`` requests (always when None)."""
    seen: list[str] = []

    def handler(route) -> None:
        seen.append(route.request.url)
        if times is None or len(seen) <= times:
            route.fulfill(status=200, content_type="text/html", body=stale)
        else:
            route.continue_()

    page.route(lambda url: urlparse(url).path == "/", handler)
    return seen


def test_a_stale_page_reloads_once_and_recovers(new_context, engine, site_url) -> None:
    page = new_context(engine).new_page()
    seen = _serve_stale_index(page, stale_index(page, site_url), times=1)

    page.goto(f"{site_url}/#theme=serif")
    page.wait_for_selector(READY, timeout=30_000)

    assert len(seen) == 2
    assert re.search(r"[?&]_cb=\d+", seen[1]) and "_cb" not in seen[0]
    assert "_cb" not in page.url  # the retry's query is not left in the address
    assert page.url.endswith("#theme=serif")  # and the rest of it is kept
    assert page.evaluate("sessionStorage.getItem('avianki.cachebust')") is None  # cleared once the app loaded


def test_a_page_that_stays_stale_reloads_only_once(new_context, engine, site_url) -> None:
    page = new_context(engine).new_page()
    seen = _serve_stale_index(page, stale_index(page, site_url), times=None)

    page.goto(f"{site_url}/")
    page.wait_for_timeout(2_000)

    assert len(seen) == 2  # the first visit and the one retry, not a loop
    assert page.evaluate("sessionStorage.getItem('avianki.cachebust')") == "1"
    assert not page.is_enabled("#region")  # the app never started


def test_a_page_without_session_storage_does_not_reload(new_context, engine, site_url) -> None:
    context = new_context(engine)
    context.add_init_script(
        "Object.defineProperty(window, 'sessionStorage', {get() { throw new DOMException('blocked', 'SecurityError'); }});"
    )
    page = context.new_page()
    seen = _serve_stale_index(page, stale_index(page, site_url), times=None)

    page.goto(f"{site_url}/")
    page.wait_for_timeout(1_000)

    assert len(seen) == 1  # no way to guard against a loop, so no retry
