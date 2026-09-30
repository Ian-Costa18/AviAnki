"""The last mile (ADR 0016): the detected device's steps come first, and the Share button appears
only where the browser can share a file.
"""

from __future__ import annotations

import pytest
from app_support import build, open_app

ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)
IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1"
)
IPHONE_CHROME = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "CriOS/126.0.0.0 Mobile/15E148 Safari/604.1"
)
IPAD_OLD = (
    "Mozilla/5.0 (iPad; CPU OS 12_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/12.1.2 Mobile/15E148 Safari/604.1"
)
MAC_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Safari/605.1.15"
)
WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
LINUX_FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"
ANDROID_FIREFOX = "Mozilla/5.0 (Android 14; Mobile; rv:127.0) Gecko/127.0 Firefox/127.0"

SAMPLES = [
    ("Android Chrome", ANDROID_CHROME, "Linux armv81", 5, "android"),
    ("Android Firefox", ANDROID_FIREFOX, "Linux armv81", 5, "android"),
    ("iPhone Safari", IPHONE_SAFARI, "iPhone", 5, "ios"),
    ("iPhone Chrome", IPHONE_CHROME, "iPhone", 5, "ios"),
    ("old iPad", IPAD_OLD, "iPad", 5, "ios"),
    ("iPadOS reporting a Mac", MAC_SAFARI, "MacIntel", 5, "ios"),
    ("Mac", MAC_SAFARI, "MacIntel", 0, "desktop"),
    ("Windows", WINDOWS_CHROME, "Win32", 0, "desktop"),
    ("Windows touch laptop", WINDOWS_CHROME, "Win32", 10, "desktop"),
    ("Linux", LINUX_FIREFOX, "Linux x86_64", 0, "desktop"),
    ("nothing at all", "", "", 0, "desktop"),
]


@pytest.mark.parametrize(("label", "ua", "platform", "touch", "expected"), SAMPLES, ids=[s[0] for s in SAMPLES])
def test_detect_platform_from_sample_user_agents(page, label, ua, platform, touch, expected) -> None:
    got = page.evaluate(
        "async (nav) => { const { detectPlatform } = await import('/js/lastmile.js'); return detectPlatform(nav); }",
        {"userAgent": ua, "platform": platform, "maxTouchPoints": touch},
    )
    assert got == expected, label


def test_detect_platform_with_no_arguments_is_desktop(page) -> None:
    got = page.evaluate("async () => (await import('/js/lastmile.js')).detectPlatform()")
    assert got == "desktop"


def test_render_puts_the_detected_platform_first_and_the_rest_in_a_collapsed_section(page) -> None:
    got = page.evaluate(
        """async () => {
          const { renderLastMile } = await import('/js/lastmile.js');
          const out = {};
          for (const p of ['android', 'ios', 'desktop', 'nonsense']) {
            const box = document.createElement('div');
            renderLastMile(box, p);
            const details = box.querySelector(':scope > details');
            out[p] = {
              first: box.firstElementChild.dataset.platform,
              heading: box.firstElementChild.firstElementChild.tagName,
              others: [...details.querySelectorAll('section')].map((s) => s.dataset.platform),
              summary: details.querySelector('summary').textContent,
              open: details.open,
            };
          }
          return out;
        }"""
    )
    assert got["android"]["first"] == "android"
    assert got["android"]["others"] == ["ios", "desktop"]
    assert got["ios"]["first"] == "ios"
    assert got["ios"]["others"] == ["android", "desktop"]
    assert got["desktop"]["first"] == "desktop"
    assert got["desktop"]["others"] == ["android", "ios"]
    assert got["nonsense"]["first"] == "desktop"  # never a blank box
    for out in got.values():
        assert out["summary"] == "On a different device?"
        assert out["open"] is False
        assert out["heading"] == "H3"


# ---------------------------------------------------------------------------------------
# In the app, on emulated devices
# ---------------------------------------------------------------------------------------


def _steps(page) -> dict:
    return page.evaluate(
        """() => {
          const box = document.getElementById('lastmile');
          const details = box.querySelector(':scope > details');
          return {
            first: box.querySelector(':scope > section').dataset.platform,
            firstText: box.querySelector(':scope > section').textContent,
            others: [...details.querySelectorAll('section')].map((s) => s.dataset.platform),
            open: details.open,
            firstLinks: [...box.querySelectorAll(':scope > section a')].map((a) => a.href),
          };
        }"""
    )


def test_android_emulation_shows_ankidroid_first(new_context, base_url) -> None:
    page = open_app(new_context("chromium", device="Pixel 7"), base_url)
    steps = _steps(page)
    assert steps["first"] == "android"
    assert steps["others"] == ["ios", "desktop"]
    assert steps["open"] is False
    assert "AnkiDroid" in steps["firstText"]
    assert any("play.google.com" in href for href in steps["firstLinks"])


def test_iphone_emulation_shows_ankimobile_first_with_the_price_and_the_free_route(new_context, base_url) -> None:
    page = open_app(new_context("webkit", device="iPhone 14"), base_url)
    steps = _steps(page)
    assert steps["first"] == "ios"
    assert steps["others"] == ["android", "desktop"]
    assert "US$24.99" in steps["firstText"]
    assert "AnkiWeb" in steps["firstText"]
    assert any("apps.apple.com" in href for href in steps["firstLinks"])


def test_ipad_that_reports_a_mac_is_still_an_ios_device(new_context, base_url) -> None:
    context = new_context("chromium", user_agent=MAC_SAFARI)
    context.add_init_script(
        "Object.defineProperty(navigator, 'maxTouchPoints', { value: 5, configurable: true });"
        "Object.defineProperty(navigator, 'platform', { value: 'MacIntel', configurable: true });"
    )
    assert _steps(open_app(context, base_url))["first"] == "ios"


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
def test_desktop_shows_anki_first(new_context, engine, base_url) -> None:
    steps = _steps(open_app(new_context(engine), base_url))
    assert steps["first"] == "desktop"
    assert steps["others"] == ["android", "ios"]
    assert "apps.ankiweb.net" in "".join(steps["firstLinks"])


# ---------------------------------------------------------------------------------------
# Share
# ---------------------------------------------------------------------------------------

SHARE_OK = """
window.__shared = null;
navigator.canShare = (data) => Boolean(data && data.files && data.files.length);
navigator.share = async (data) => { window.__shared = data.files.map((f) => [f.name, f.size]); };
"""
SHARE_REFUSES = "navigator.canShare = () => false; navigator.share = async () => {};"
SHARE_MISSING = "Object.defineProperty(navigator, 'canShare', { value: undefined, configurable: true });"


def test_share_button_appears_when_the_browser_can_share_the_file_and_shares_it(new_context, base_url, tmp_path) -> None:
    context = new_context("chromium")
    context.add_init_script(SHARE_OK)
    page = open_app(context, base_url)
    files = build(page, tmp_path, region="Arizona")

    button = page.get_by_role("button", name="Share AviAnki-us-az.apkg")
    assert button.is_visible()
    button.click()
    page.wait_for_function("window.__shared !== null")
    assert page.evaluate("window.__shared") == [["AviAnki-us-az.apkg", files[0].stat().st_size]]


@pytest.mark.parametrize("script", [SHARE_REFUSES, SHARE_MISSING], ids=["canShare-false", "canShare-missing"])
def test_no_share_button_when_the_browser_cannot_share_files(new_context, base_url, tmp_path, script) -> None:
    context = new_context("chromium")
    context.add_init_script(script)
    page = open_app(context, base_url)
    build(page, tmp_path, region="Arizona")

    assert page.get_by_role("button", name="Share", exact=False).count() == 0
    assert page.get_by_role("link", name="Save AviAnki-us-az.apkg again").is_visible()
