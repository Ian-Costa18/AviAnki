"""Fixes from the exploratory test of the web app: reload, stale messages, double submit, missing
media, wording, favicon, tap targets and field alignment. Each test fails on the code before the fix.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

import pytest
from app_support import (
    ALL_CARDS,
    CONSTRAINED,
    DONE,
    ERROR,
    NETWORK_MESSAGE,
    READY,
    RECORD_TEXT,
    build,
    choose,
    open_app,
    visible_text,
)
from web_support import WEB_DIR

CHANGED_MESSAGE = "The bird catalog was updated while you were building. Please try again."
BUILDING = "sessionStorage.getItem('avianki.building')"


# ---------------------------------------------------------------------------------------
# 1. A reload mid-build is not an out-of-memory
# ---------------------------------------------------------------------------------------


def test_reloading_mid_build_does_not_split_the_next_build_into_parts(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url)
    held: list[object] = []
    page.route("**/catalog/media/**", lambda route: held.append(route))  # the build stalls on its first file

    choose(page, "Massachusetts")
    page.click("#build")
    page.wait_for_function(f"{BUILDING} === '1'")
    for _ in range(100):  # wait until the build is really stalled on a media request
        if held:
            break
        page.wait_for_timeout(50)
    assert held

    page.reload()
    page.wait_for_selector(READY)
    assert page.evaluate(BUILDING) is None  # pagehide cleared it
    page.unroute("**/catalog/media/**")

    files = build(page, tmp_path, region="Massachusetts")
    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]  # one file, not parts
    assert "memory" not in (page.text_content("#parts-announce") or "")
    assert page.get_attribute("#parts-announce", "hidden") is not None  # never announced


def test_a_flag_that_survives_is_still_a_killed_tab(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script("sessionStorage.setItem('avianki.building', '1');")  # what a killed tab leaves
    page = open_app(context, base_url)
    files = build(page, tmp_path, region="Massachusetts")
    assert [f.name for f in files] == ["AviAnki-us-ma-part-1-of-2.apkg", "AviAnki-us-ma-part-2-of-2.apkg"]
    assert "ran out of memory" in (page.text_content("#parts-announce") or "")


# ---------------------------------------------------------------------------------------
# 3. Validation messages go when the input is fixed
# ---------------------------------------------------------------------------------------


def test_validation_messages_hide_as_soon_as_the_input_is_valid(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)

    page.click("#build")
    assert page.is_visible("#region-problem")
    page.select_option("#region", label="Arizona")
    assert not page.is_visible("#region-problem")

    choose(page, cards=())
    page.click("#build")
    assert page.is_visible("#cards-problem")
    page.check('input[name="cards"][value="audio"]')
    assert not page.is_visible("#cards-problem")

    # Still one problem at a time: unticking everything again and submitting brings it back.
    page.uncheck('input[name="cards"][value="audio"]')
    page.click("#build")
    assert page.is_visible("#cards-problem")
    assert not page.is_visible("#region-problem")


# ---------------------------------------------------------------------------------------
# 4. A second submit while a build runs is ignored
# ---------------------------------------------------------------------------------------


def test_a_second_submit_while_building_is_ignored(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url)
    choose(page, "Arizona")
    downloads: list[object] = []
    page.on("download", lambda d: downloads.append(d))  # noqa: PLW0108
    manifests: list[str] = []
    page.on("request", lambda r: manifests.append(r.url) if r.url.endswith("/catalog/manifest.json") else None)
    before = len(manifests)

    page.evaluate("() => { const f = document.getElementById('form'); f.requestSubmit(); f.requestSubmit(); f.requestSubmit(); }")
    page.wait_for_selector(DONE, timeout=60_000)
    page.wait_for_timeout(500)

    assert len(downloads) == 1
    assert len(manifests) - before == 1  # one build, one fresh manifest read


# ---------------------------------------------------------------------------------------
# 5. A missing file is not a connection problem
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 403])
def test_a_4xx_on_media_says_the_catalog_was_updated_and_is_not_retried(new_context, engine, base_url, status) -> None:
    page = open_app(new_context(engine), base_url)
    attempts: list[str] = []

    def refuse(route) -> None:
        attempts.append(route.request.url)
        route.fulfill(status=status, body="nope")

    page.route("**/catalog/media/**", refuse)
    choose(page, "Arizona")
    page.click("#build")
    page.wait_for_selector(ERROR, timeout=30_000)

    assert visible_text(page, "#error-text") == CHANGED_MESSAGE
    assert page.is_visible("#screen-pick")
    assert len(set(attempts)) == len(attempts)  # no file was asked for twice

    page.unroute("**/catalog/media/**")
    page.click("#error-action")  # Try again: a fresh manifest, and the files are there
    page.wait_for_selector(DONE, timeout=60_000)


def test_a_5xx_on_media_is_still_retried_and_says_the_network_message(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    attempts: list[str] = []

    def refuse(route) -> None:
        attempts.append(route.request.url)
        route.fulfill(status=503, body="busy")

    page.route("**/catalog/media/**", refuse)
    choose(page, "Arizona")
    page.click("#build")
    page.wait_for_selector(ERROR, timeout=30_000)

    assert visible_text(page, "#error-text") == NETWORK_MESSAGE
    assert len(attempts) > len(set(attempts))  # at least one file was tried again


# ---------------------------------------------------------------------------------------
# 6 and 7. Part names, progress wording and plurals
# ---------------------------------------------------------------------------------------


def test_part_files_carry_the_region(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(CONSTRAINED)
    page = open_app(context, base_url, "?partSize=5")
    files = build(page, tmp_path, region="Québec", tier="everything", cards=ALL_CARDS)
    assert [f.name for f in files] == ["AviAnki-ca-qc-part-1-of-2.apkg", "AviAnki-ca-qc-part-2-of-2.apkg"]
    assert "ca-qc-part-1-of-2" in visible_text(page, "#downloads")


@pytest.mark.parametrize(
    ("notes", "expected"),
    [
        ([{"photo": {}, "audio": {}}], "photos and recordings"),
        ([{"photo": {}, "audio": None}, {"photo": {}, "audio": None}], "photos"),
        ([{"photo": None, "audio": {}}], "recordings"),
        ([{"photo": {}, "audio": None}, {"photo": None, "audio": {}}], "photos and recordings"),
    ],
)
def test_download_wording_names_what_is_downloaded(chromium_page, notes, expected) -> None:
    got = chromium_page.evaluate(
        "async (notes) => (await import('/js/parts.js')).downloadWhat(notes)", notes
    )
    assert got == expected


def test_plural_is_singular_only_for_one(chromium_page) -> None:
    got = chromium_page.evaluate(
        """async () => {
          const { plural } = await import('/js/parts.js');
          return [plural(0, 'bird'), plural(1, 'bird'), plural(2, 'card'), plural(1, 'file'), plural(190, 'file')];
        }"""
    )
    assert got == ["0 birds", "1 bird", "2 cards", "1 file", "190 files"]


def test_progress_text_names_photos_and_recordings(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(RECORD_TEXT)
    page = open_app(context, base_url)
    build(page, tmp_path, region="Massachusetts")
    texts = page.evaluate("window.__texts")
    assert any(re.fullmatch(r"Downloading photos and recordings \(\d+ of 12\)…", t) for t in texts)
    assert not any("calls" in t for t in texts)


def test_a_one_bird_one_card_deck_reads_in_the_singular(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(RECORD_TEXT)
    page = open_app(context, base_url)

    def one_bird(route) -> None:  # the region file with only its first species
        response = route.fetch()
        body = response.json()
        body["species"] = body["species"][:1]
        route.fulfill(response=response, json=body)

    def one_in_manifest(route) -> None:
        response = route.fetch()
        body = response.json()
        for region in body["regions"]:
            region["species_count"] = 1
        route.fulfill(response=response, json=body)

    page.route("**/catalog/regions/us-ma.*.json", one_bird)
    page.route("**/catalog/manifest.json", one_in_manifest)
    page.reload()
    page.wait_for_selector(READY)
    build(page, tmp_path, region="Massachusetts", tier="standard", cards=("photo",))

    assert "Massachusetts: 1 bird, 1 card," in visible_text(page, "#done-summary")
    assert "Finding the 1 bird most seen in Massachusetts…" in page.evaluate("window.__texts")


# ---------------------------------------------------------------------------------------
# 8. A favicon
# ---------------------------------------------------------------------------------------


def test_the_page_has_an_inline_svg_favicon(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    href = page.get_attribute('link[rel="icon"]', "href")
    assert href and href.startswith("data:image/svg+xml,")
    svg = urllib.parse.unquote(href.split(",", 1)[1])
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert len(href) < 1500
    # It really is an image the browser can decode.
    ok = page.evaluate(
        "href => new Promise((res) => { const i = new Image(); i.onload = () => res(i.naturalWidth > 0);"
        " i.onerror = () => res(false); i.src = href; })",
        href,
    )
    assert ok is True
    assert "favicon" not in (WEB_DIR / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------
# 9. Tap targets on a phone
# ---------------------------------------------------------------------------------------

TARGETS = """
() => [...document.querySelectorAll('a, button, summary')]
  .filter((el) => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
  .map((el) => ({ text: (el.textContent || '').trim().slice(0, 40), h: el.getBoundingClientRect().height }))
"""


def _short(page) -> list[str]:
    return [f"{t['text']!r} is {t['h']:.1f}px" for t in page.evaluate(TARGETS) if t["h"] < 43.99]


def test_every_link_and_button_is_44px_tall_on_a_phone(new_context, base_url, tmp_path) -> None:
    context = new_context("chromium", device="Pixel 7")
    page = open_app(context, base_url)
    page.wait_for_function("document.getElementById('licence-notice').textContent.length > 0")
    assert page.evaluate("innerWidth") < 500
    assert _short(page) == []  # the pick screen, footer included

    page.click("#advanced > summary")
    assert _short(page) == []
    for tab in ("ios", "android", "desktop"):  # every device's steps, with their store links
        page.click(f"#study-pick-tab-{tab}")
        assert _short(page) == [], tab

    build(page, tmp_path, region="Arizona")
    assert page.evaluate(TARGETS)  # something was measured
    for tab in ("ios", "android", "desktop"):
        page.click(f"#study-done-tab-{tab}")
        assert _short(page) == [], tab


# ---------------------------------------------------------------------------------------
# 10. The Advanced fields line up
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("device", [None, "Pixel 7"])
def test_the_month_select_lines_up_with_the_other_indented_fields(new_context, base_url, device) -> None:
    page = open_app(new_context("chromium", device=device), base_url)
    page.click("#advanced > summary")
    edges = page.evaluate(
        """() => {
          const box = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left * 10) / 10, Math.round(r.right * 10) / 10]; };
          const details = document.getElementById('advanced');
          return {
            select: box(document.getElementById('month')),
            label: box(document.querySelector('label[for="month"]')),
            fieldset: box(document.querySelector('#advanced fieldset')),
            choice: box(document.querySelector('#advanced .choice')),
            details: box(details),
          };
        }"""
    )
    assert edges["select"] == edges["fieldset"] == edges["label"]
    assert edges["select"][0] > edges["details"][0]  # indented, not flush with the box
    assert edges["select"][1] < edges["details"][1]


# ---------------------------------------------------------------------------------------
# A WebAssembly trap inside sql.js is retried once
# ---------------------------------------------------------------------------------------

# Make the first `SQL.Database.run` throw what WebKit has been seen to throw intermittently inside the
# sql.js wasm ("access to a null reference"), then behave normally. `__sqlInits` counts how many sql.js
# instances the page created, so the test can see the retry used a fresh one.
TRAP_SQL_ONCE = """
(() => {
  let real;
  window.__trapped = false;
  window.__sqlInits = 0;
  Object.defineProperty(window, "initSqlJs", {
    configurable: true,
    get: () => real && ((...args) => {
      window.__sqlInits += 1;
      return real(...args).then((SQL) => {
        const run = SQL.Database.prototype.run;
        SQL.Database.prototype.run = function (...a) {
          if (!window.__trapped) {
            window.__trapped = true;
            throw new WebAssembly.RuntimeError("access to a null reference");
          }
          return run.apply(this, a);
        };
        return SQL;
      });
    }),
    set: (value) => { real = value; },
  });
})();
"""


def test_a_wasm_trap_in_sql_js_is_retried_on_a_fresh_instance(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(TRAP_SQL_ONCE)
    page = open_app(context, base_url)

    files = build(page, tmp_path, region="Massachusetts")

    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    assert page.evaluate("window.__trapped") is True
    assert page.evaluate("window.__sqlInits") == 2  # the trapped instance was dropped, not reused
    assert page.get_attribute("#error", "hidden") is not None
