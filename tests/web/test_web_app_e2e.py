"""The app end to end, in a real browser: pick a region, build, download, and check the .apkg
with Anki's own backend. Runs in Chromium and WebKit against the fixture catalog.
"""

from __future__ import annotations

import json

from app_support import (
    ALL_CARDS,
    DONE,
    ERROR,
    NETWORK_MESSAGE,
    READY,
    RECORD_TEXT,
    UPDATED_MESSAGE,
    build,
    choose,
    expected_guids,
    import_and_check,
    open_app,
    visible_text,
)
from web_support import REPO, serve

NOTETYPES = json.loads((REPO / "web" / "js" / "notetypes.json").read_text(encoding="utf-8"))
FOCUSED = "document.activeElement && document.activeElement.id"


# ---------------------------------------------------------------------------------------
# The main path
# ---------------------------------------------------------------------------------------


def test_massachusetts_default_build_passes_the_acceptance_checks(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(RECORD_TEXT)
    page = open_app(context, base_url)

    files = build(page, tmp_path, region="Massachusetts")

    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    got = import_and_check(tmp_path, files)
    assert got["guids"] == expected_guids("us-ma")
    assert "AviAnki" in got["decks"]
    assert not any(d.startswith("AviAnki::") for d in got["decks"])  # no subdeck unless asked

    texts = page.evaluate("window.__texts")
    assert "Finding the 12 birds most seen in Massachusetts…" in texts
    assert any(t.startswith("Downloading photos and recordings (") and " of 12)" in t for t in texts)
    assert "Packing your deck…" in texts
    assert page.errors == []

    # The Done screen: a Save again link, a summary, the steps, and focus on the new heading.
    assert page.evaluate(FOCUSED) == "done-title"
    assert "Massachusetts: 12 birds" in visible_text(page, "#done-summary")
    assert page.get_by_role("link", name="Save AviAnki-us-ma.apkg again").is_visible()

    page.click("#again")
    assert page.is_visible("#screen-pick")
    assert page.evaluate(FOCUSED) == "pick-title"


def test_advanced_options_all_cards_subdeck_and_month(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url)

    files = build(page, tmp_path, region="Massachusetts", tier="everything", month=7, cards=ALL_CARDS, subdeck=True)

    got = import_and_check(tmp_path, files)
    wanted = expected_guids("us-ma", tier="everything", month=7, cards=ALL_CARDS)
    assert got["guids"] == wanted
    assert wanted != expected_guids("us-ma", tier="everything", cards=ALL_CARDS)  # the month really filtered
    assert "AviAnki::Massachusetts" in got["decks"]


def test_quebec_by_display_name_keeps_its_accent(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url)

    files = build(page, tmp_path, region="Québec", subdeck=True)

    assert [f.name for f in files] == ["AviAnki-ca-qc.apkg"]
    got = import_and_check(tmp_path, files)
    assert "AviAnki::Québec" in got["decks"]
    assert got["guids"] == expected_guids("ca-qc")

    # The region is remembered for next time (in localStorage, by slug, shown by name).
    page.reload()
    page.wait_for_selector(READY)
    assert page.input_value("#region") == "ca-qc"
    assert page.locator("#region option:checked").inner_text() == "Québec"


# ---------------------------------------------------------------------------------------
# The Pick screen
# ---------------------------------------------------------------------------------------


def test_pick_screen_content_and_defaults(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)

    assert "birds where you live" in visible_text(page, "#pick-title")
    assert page.get_by_label("Where do you go birding?").is_visible()
    assert page.get_by_role("button", name="Build my deck").is_enabled()

    # Display names only, grouped by country; never a slug or a region code.
    groups = page.eval_on_selector_all("#region optgroup", "els => els.map(e => e.label)")
    assert groups == ["United States", "Canada"]
    options = page.eval_on_selector_all("#region option", "els => els.map(e => e.textContent)")
    assert {"Massachusetts", "Arizona", "Québec"} <= set(options)
    assert not [o for o in options if o.startswith(("us-", "ca-", "US-", "CA-"))]

    # ADR 0016: the line under the button, and ADR 0015: the "Not in the list?" line.
    assert "free flashcard app" in visible_text(page, "#anki-line")
    not_listed = page.locator("#not-listed")
    assert "Not in the list?" in not_listed.inner_text()
    assert "readme" in not_listed.locator("a").first.get_attribute("href").lower()

    # Advanced is collapsed, and its defaults are ADR 0010's.
    assert page.locator("#advanced").evaluate("el => el.open") is False
    assert not page.is_visible('input[name="tier"]')
    page.click("#advanced > summary")
    assert page.is_checked('input[name="tier"][value="standard"]')
    assert page.is_checked('input[name="cards"][value="photo"]')
    assert page.is_checked('input[name="cards"][value="audio"]')
    assert not page.is_checked('input[name="cards"][value="photo_audio"]')
    assert not page.is_checked("#subdeck")
    assert page.get_by_label("Only birds seen here in:").is_visible()


def test_footer_carries_credits_and_the_licence_notice(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    page.wait_for_function("document.getElementById('licence-notice').textContent.length > 0")

    footer = visible_text(page, "footer")
    assert "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF (fixture)" in footer
    assert "CC-BY-4.0" in footer
    assert visible_text(page, "#licence-notice") == NOTETYPES["description"]["licence_notice"]
    assert page.get_attribute("#credits-link", "href") == f"{base_url}/catalog/credits.html"
    assert "github.com" in page.get_attribute('footer a[href*="github.com"]', "href")


def test_what_youll_see_matches_the_study_guidance(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    text = page.locator("#what-youll-see").evaluate("el => el.textContent.split(/\\s+/).join(' ')")
    assert text == " ".join(NOTETYPES["description"]["study_guidance"])


def test_missing_card_type_or_region_stops_before_building(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)

    page.click("#build")  # nothing chosen
    assert page.is_visible("#region-problem")
    assert page.is_visible("#screen-pick")

    choose(page, "Arizona", cards=())
    page.click("#build")
    assert page.is_visible("#cards-problem")
    assert page.is_visible("#screen-pick")
    assert page.evaluate("document.activeElement.name") == "cards"


def test_keyboard_alone_builds_a_deck(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    page.focus("#region")
    page.select_option("#region", label="Arizona")
    page.focus("#build")
    page.keyboard.press("Enter")
    page.wait_for_selector(DONE, timeout=60_000)
    assert page.evaluate(FOCUSED) == "done-title"
    # ... and comes back with the keyboard too.
    page.focus("#again")
    page.keyboard.press("Enter")
    assert page.evaluate(FOCUSED) == "pick-title"


def test_progress_is_announced_to_screen_readers(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    assert page.get_attribute("#announce", "aria-live") == "polite"
    assert page.get_attribute("#error", "role") == "alert"
    assert page.get_attribute("#parts-hint", "aria-live") == "polite"
    for label in ("Where do you go birding?", "Only birds seen here in:"):
        assert page.get_by_label(label).count() == 1


# ---------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------


def test_manifest_unreachable_shows_the_network_message_after_two_retries(new_context, engine, base_url) -> None:
    context = new_context(engine)
    attempts: list[str] = []

    def refuse(route) -> None:
        attempts.append(route.request.url)
        route.abort()

    page = context.new_page()
    page.route("**/catalog/manifest.json", refuse)
    page.goto(f"{base_url}/")
    page.wait_for_selector(ERROR, timeout=15_000)

    assert visible_text(page, "#error-text") == NETWORK_MESSAGE
    assert len(attempts) == 3  # the first try and two retries
    assert page.is_disabled("#region")

    page.unroute("**/catalog/manifest.json")
    page.click("#error-action")  # "Try again"
    page.wait_for_selector(READY)
    assert not page.is_visible(ERROR)


def test_unknown_catalog_format_asks_for_a_reload(new_context, engine, base_url) -> None:
    context = new_context(engine)
    attempts: list[str] = []

    def newer(route) -> None:
        attempts.append(route.request.url)
        response = route.fetch()
        route.fulfill(response=response, json={**response.json(), "format": 99})

    page = context.new_page()
    page.route("**/catalog/manifest.json", newer)
    page.goto(f"{base_url}/")
    page.wait_for_selector(ERROR)

    assert visible_text(page, "#error-text") == UPDATED_MESSAGE
    assert len(attempts) == 1  # a newer format will not fix itself, so no retries
    assert page.get_by_role("button", name="Reload").is_visible()


def test_media_failure_mid_build_returns_to_pick_with_the_network_message(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    page.route("**/catalog/media/**", lambda route: route.abort())

    choose(page, "Arizona")
    page.click("#build")
    page.wait_for_selector(ERROR, timeout=30_000)

    assert visible_text(page, "#error-text") == NETWORK_MESSAGE
    assert page.is_visible("#screen-pick")
    assert not page.is_visible("#screen-done")

    page.unroute("**/catalog/media/**")
    page.click("#error-action")  # Try again, now that the network is back
    page.wait_for_selector(DONE, timeout=60_000)


# ---------------------------------------------------------------------------------------
# Cache Storage and the ?catalog= override
# ---------------------------------------------------------------------------------------


def test_second_build_reads_media_from_cache_storage(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url)
    media_requests: list[str] = []
    page.on("request", lambda req: media_requests.append(req.url) if "/catalog/media/" in req.url else None)

    build(page, tmp_path, region="Arizona")
    first = len(media_requests)
    assert first > 0
    assert page.evaluate("caches.keys()") != []

    page.click("#again")
    page.click("#build")
    page.wait_for_selector(DONE)
    assert len(media_requests) == first  # nothing fetched twice


def test_catalog_query_overrides_the_default_location(new_context, engine, base_url, tmp_path) -> None:
    with serve() as other:
        context = new_context(engine)
        page = context.new_page()
        page.errors = []
        seen: list[str] = []
        page.on("request", lambda req: seen.append(req.url) if "/catalog/" in req.url.split("?")[0] else None)
        page.route(f"{base_url}/catalog/**", lambda route: route.abort())  # the default must not be touched
        page.goto(f"{base_url}/?catalog={other}/catalog/manifest.json")
        page.wait_for_selector(READY)

        assert page.get_attribute("#credits-link", "href") == f"{other}/catalog/credits.html"
        files = build(page, tmp_path, region="Arizona")
        assert [f.name for f in files] == ["AviAnki-us-az.apkg"]
        assert seen
        assert all(url.startswith(f"{other}/catalog/") for url in seen)


def test_cache_storage_unavailable_falls_back_to_plain_fetches(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(
        "Object.defineProperty(window, 'caches', { get() { throw new Error('no cache storage'); }, configurable: true });"
    )
    page = open_app(context, base_url)
    files = build(page, tmp_path, region="Arizona")
    assert [f.name for f in files] == ["AviAnki-us-az.apkg"]
    import_and_check(tmp_path, files)
