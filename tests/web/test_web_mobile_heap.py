"""The memory cap (ADR 0019): a realistic-size build on a phone-like browser.

The catalog is synthetic (400 species, one photo of ~60 KB and one recording of ~100 KB each,
random bytes, made at test time with the real writers) so Standard is ~16 MB and Everything ~64 MB
like the real thing. Chromium runs with ``--js-flags=--max-old-space-size=256``, a Pixel 7
profile and a 4x CPU throttle; the page samples ``performance.memory.usedJSHeapSize`` while it
builds. A build that dies, or a JS heap peak above 200 MB, fails the test.

What the number is: the JS heap only. Typed-array backing stores and Blob data live outside it (and
outside ``--max-old-space-size``), which is exactly why the writer streams media one file at a time.
WebKit reports no heap size, so the iPhone 14 runs check success and time only.

Run with ``-s`` to see the numbers.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from app_support import (
    CONSTRAINED,
    DONE,
    ERROR,
    HEAP_SAMPLER,
    apkg_guids,
    build,
    expected_guids,
    import_and_check,
    open_app,
)
from synthetic_catalog import SPECIES_COUNT, build_synthetic_catalog
from web_support import serve

MB = 1024 * 1024
HEAP_LIMIT = 200 * MB
CPU_THROTTLE = 4

@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory) -> Iterator[Path]:
    pytest.importorskip("jsonschema")  # the catalog writers validate with it (the catalog extra)
    out = tmp_path_factory.mktemp("synthetic-catalog")
    manifest = build_synthetic_catalog(out)
    print(f"\nsynthetic catalog: {SPECIES_COUNT} species, {manifest.total_bytes / MB:.1f} MB")
    yield out


@pytest.fixture(scope="session")
def synthetic_url(synthetic_dir) -> Iterator[str]:
    with serve(synthetic_dir) as url:
        yield url


@pytest.fixture(scope="module")
def mobile_chromium(_playwright) -> Iterator[object]:
    try:
        browser = _playwright.chromium.launch(
            args=["--js-flags=--max-old-space-size=256", "--enable-precise-memory-info"]
        )
    except Exception as exc:  # noqa: BLE001 - a missing browser build is a skip, not a failure
        pytest.skip(f"chromium is not available: {str(exc).splitlines()[0]}")
    yield browser
    browser.close()


def _mobile_page(playwright, browser, url: str, *, constrained: bool):
    """A Pixel 7 page with the heap sampler, and the CPU slowed down 4x."""
    context = browser.new_context(accept_downloads=True, **playwright.devices["Pixel 7"])
    context.add_init_script(HEAP_SAMPLER)
    if constrained:
        context.add_init_script(CONSTRAINED)
    page = open_app(context, url)
    page.crashed = False
    page.on("crash", lambda: setattr(page, "crashed", True))
    cdp = context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU_THROTTLE})
    return context, page


def _build(page, tmp_path: Path, tier: str) -> tuple[list[Path], float, float]:
    page.evaluate("window.__peak = 0")
    started = time.monotonic()
    files = build(page, tmp_path, region="Massachusetts", tier=tier, timeout=900_000)
    elapsed = time.monotonic() - started
    assert not page.crashed, "the page crashed while building"
    assert not page.is_visible(ERROR), page.inner_text("#error-text")
    return files, elapsed, page.evaluate("window.__peak") / MB


def test_standard_build_stays_inside_the_mobile_heap(_playwright, mobile_chromium, synthetic_dir, synthetic_url, tmp_path) -> None:
    context, page = _mobile_page(_playwright, mobile_chromium, synthetic_url, constrained=False)
    try:
        files, seconds, peak = _build(page, tmp_path, "standard")
    finally:
        context.close()

    size = sum(f.stat().st_size for f in files)
    print(
        f"\nmobile Standard: {len(files)} file(s), {size / MB:.1f} MB, {seconds:.1f} s "
        f"at {CPU_THROTTLE}x CPU throttle, peak JS heap {peak:.1f} MB (limit {HEAP_LIMIT / MB:.0f} MB)"
    )
    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    assert 0 < peak * MB <= HEAP_LIMIT
    assert size > 100 * (60_000 + 100_000) * 0.8  # the media really went in

    got = import_and_check(tmp_path, files, catalog_dir=synthetic_dir)
    assert got["guids"] == expected_guids("us-ma", catalog_dir=synthetic_dir)


def test_everything_in_parts_stays_inside_the_mobile_heap(
    _playwright, mobile_chromium, synthetic_dir, synthetic_url, tmp_path) -> None:
    context, page = _mobile_page(_playwright, mobile_chromium, synthetic_url, constrained=True)  # a 4 GB phone
    try:
        files, seconds, peak = _build(page, tmp_path, "everything")
    finally:
        context.close()

    size = sum(f.stat().st_size for f in files)
    print(
        f"\nmobile Everything in parts: {len(files)} files, {size / MB:.1f} MB total, "
        f"largest {max(f.stat().st_size for f in files) / MB:.1f} MB, {seconds:.1f} s at {CPU_THROTTLE}x CPU "
        f"throttle, peak JS heap {peak:.1f} MB (limit {HEAP_LIMIT / MB:.0f} MB)"
    )
    assert [f.name for f in files] == [f"AviAnki-us-ma-part-{i}-of-3.apkg" for i in (1, 2, 3)]
    assert 0 < peak * MB <= HEAP_LIMIT

    per_part = [apkg_guids(f, tmp_path) for f in files]
    assert [len(g) for g in per_part] == [300, 300, 200]  # 150 + 150 + 100 species, two cards each
    wanted = expected_guids("us-ma", tier="everything", catalog_dir=synthetic_dir)
    assert set().union(*per_part) == wanted
    assert len(wanted) == 2 * SPECIES_COUNT


@pytest.mark.parametrize("tier", ["standard", "everything"])
def test_iphone_builds_standard_and_everything(new_context, synthetic_url, tmp_path, tier) -> None:
    context = new_context("webkit", device="iPhone 14")
    page = open_app(context, synthetic_url)
    started = time.monotonic()
    files = build(page, tmp_path, region="Massachusetts", tier=tier, timeout=900_000)
    seconds = time.monotonic() - started

    size = sum(f.stat().st_size for f in files)
    print(f"\niPhone 14 (WebKit) {tier}: {len(files)} file(s), {size / MB:.1f} MB, {seconds:.1f} s")
    assert page.is_visible(DONE)
    if tier == "standard":
        assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    else:
        assert [f.name for f in files] == [f"AviAnki-us-ma-part-{i}-of-3.apkg" for i in (1, 2, 3)]
