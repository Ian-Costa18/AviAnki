"""The study guide (ADRs 0016 and 0030): accessible device tabs with the detected device selected, readable
before anything is built and the same on the Done screen, and the Share button only where the browser can
share a file.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from app_support import build, open_app
from web_support import REPO


def _hosts(links: list[str]) -> set[str]:
    return {urlparse(link).hostname or "" for link in links}

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



RENDER = """async (platform) => {
  const { renderStudyGuide } = await import('/js/lastmile.js');
  const box = document.createElement('div');
  document.body.append(box);
  renderStudyGuide(box, platform, { id: 'unit', heading: 'Studying' });
  const tabs = [...box.querySelectorAll('[role=tab]')];
  const panels = [...box.querySelectorAll('[role=tabpanel]')];
  return {
    heading: box.querySelector('h3').textContent,
    list: box.querySelector('[role=tablist]').getAttribute('aria-label'),
    labels: tabs.map((t) => t.textContent),
    selected: tabs.filter((t) => t.getAttribute('aria-selected') === 'true').map((t) => t.dataset.platform),
    tabbable: tabs.filter((t) => t.tabIndex === 0).map((t) => t.dataset.platform),
    shown: panels.filter((p) => !p.hidden).map((p) => p.dataset.platform),
    wired: tabs.every((t) => {
      const panel = document.getElementById(t.getAttribute('aria-controls'));
      return panel && panel.getAttribute('role') === 'tabpanel' && panel.getAttribute('aria-labelledby') === t.id;
    }),
    seeBox: !!box.querySelector('.what-youll-see'),
  };
}"""


def test_render_study_guide_selects_the_detected_devices_tab(page) -> None:
    for platform, selected in [("android", "android"), ("ios", "ios"), ("desktop", "desktop"), ("nonsense", "desktop"),
                               (None, "desktop")]:
        got = page.evaluate(RENDER, platform)
        assert got["labels"] == ["iPhone & iPad", "Android", "Computer"]
        assert got["selected"] == [selected], platform  # never a blank box, whatever was detected
        assert got["tabbable"] == [selected]  # roving tabindex: only the selected tab is in the Tab order
        assert got["shown"] == [selected]
        assert got["wired"] is True
        assert got["list"] == "Your device"
        assert got["heading"] == "Studying"
        assert got["seeBox"] is True


def test_two_guides_on_one_page_do_not_share_ids(page) -> None:
    ids = page.evaluate(
        """async () => {
          const { renderStudyGuide } = await import('/js/lastmile.js');
          for (const id of ['one', 'two']) {
            const box = document.createElement('div');
            document.body.append(box);
            renderStudyGuide(box, 'ios', { id, heading: id });
          }
          const all = [...document.querySelectorAll('[id]')].map((e) => e.id);
          return { all: all.length, unique: new Set(all).size };
        }"""
    )
    assert ids["all"] == ids["unique"]


# ---------------------------------------------------------------------------------------
# In the app, on emulated devices
# ---------------------------------------------------------------------------------------

TABS = "#study-pick [role=tab]"


def _guide(page, where: str = "pick") -> dict:
    return page.evaluate(
        """(where) => {
          const box = document.getElementById('study-' + where);
          const tabs = [...box.querySelectorAll('[role=tab]')];
          const shown = [...box.querySelectorAll('[role=tabpanel]')].filter((p) => !p.hidden);
          return {
            selected: tabs.filter((t) => t.getAttribute('aria-selected') === 'true').map((t) => t.dataset.platform),
            shown: shown.map((p) => p.dataset.platform),
            text: shown.map((p) => p.innerText).join('\\n'),
            links: shown.flatMap((p) => [...p.querySelectorAll('a')].map((a) => a.href)),
            paths: shown.flatMap((p) => [...p.querySelectorAll('section.path h4')].map((h) => h.innerText)),
          };
        }""",
        where,
    )


def test_the_guide_is_readable_on_the_first_screen_before_anything_is_built(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    assert page.is_visible("#screen-pick")
    assert page.get_by_role("tablist", name="Your device").is_visible()
    assert [t.inner_text() for t in page.get_by_role("tab").all()] == ["iPhone & iPad", "Android", "Computer"]
    assert page.get_by_role("tabpanel").is_visible()
    assert page.locator("#study-pick .what-youll-see").is_visible()
    assert not page.is_visible("#screen-done")  # nothing was built, and nothing was downloaded
    # "See how studying works" goes to the guide and puts focus on its heading, without touching the address
    page.get_by_role("link", name="See how studying works").click()
    assert page.evaluate("document.activeElement.id") == "study-pick-title"
    assert page.evaluate("location.hash") == ""


def test_android_emulation_preselects_the_android_tab(new_context, base_url) -> None:
    page = open_app(new_context("chromium", device="Pixel 7"), base_url)
    guide = _guide(page)
    assert guide["selected"] == ["android"]
    assert guide["shown"] == ["android"]
    assert "AnkiDroid" in guide["text"]
    assert {"play.google.com"} <= _hosts(guide["links"])
    assert "tap Add" in guide["text"]  # AnkiDroid's import dialog
    page.click("#study-pick-tab-ios")  # the others are one tap away
    assert _guide(page)["selected"] == ["ios"]


def test_iphone_emulation_preselects_ios_and_shows_two_equal_paths_free_first(new_context, base_url) -> None:
    page = open_app(new_context("webkit", device="iPhone 14"), base_url)
    guide = _guide(page)
    assert guide["selected"] == ["ios"]
    assert guide["paths"] == ["Free: study on AnkiWeb", "Paid: the AnkiMobile app"]  # free first, both headed alike
    assert "US$24.99" in guide["text"]
    assert "helps fund Anki's development" in guide["text"]  # apps.ankiweb.net's own words
    assert "AnkiWeb" in guide["text"]
    # Anki's first sync to an empty AnkiWeb account asks this, with Yes and No (ADR 0030). There is no
    # "Upload" button on that dialog, and the one that has it would overwrite an account that has cards.
    assert "\u201cReplace it with local collection?\u201d, click Yes" in guide["text"]
    assert "Upload" not in guide["text"]
    assert {"apps.apple.com"} <= _hosts(guide["links"])
    assert any(href.rstrip("/") == "https://ankiweb.net" for href in guide["links"])
    # equal weight: the two paths are siblings with the same styling, neither inside the other
    sizes = page.eval_on_selector_all("#study-pick section.path", "els => els.map(e => e.className)")
    assert sizes == ["path", "path"]
    # nothing demands payment: the free path never mentions the price
    free = page.locator("#study-pick section.path").first.inner_text()
    assert "US$" not in free


def test_ipad_that_reports_a_mac_is_still_an_ios_device(new_context, base_url) -> None:
    context = new_context("chromium", user_agent=MAC_SAFARI)
    context.add_init_script(
        "Object.defineProperty(navigator, 'maxTouchPoints', { value: 5, configurable: true });"
        "Object.defineProperty(navigator, 'platform', { value: 'MacIntel', configurable: true });"
    )
    assert _guide(open_app(context, base_url))["selected"] == ["ios"]


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
def test_desktop_preselects_the_computer_tab(new_context, engine_name, base_url) -> None:
    page = open_app(new_context(engine_name), base_url)
    guide = _guide(page)
    assert guide["selected"] == ["desktop"]
    assert {"apps.ankiweb.net"} <= _hosts(guide["links"])
    assert "Study Now" in guide["text"]
    assert "then click Import" in guide["text"]  # Anki's import screen


@pytest.mark.parametrize("engine_name", ["chromium", "webkit"])
def test_tabs_work_with_the_keyboard(new_context, engine_name, base_url) -> None:
    page = open_app(new_context(engine_name), base_url)  # a desktop: Computer is selected
    page.focus("#study-pick-tab-desktop")

    def state() -> tuple[str, list[str]]:
        return page.evaluate("document.activeElement.dataset.platform"), _guide(page)["selected"]

    page.keyboard.press("ArrowRight")  # wraps from the last tab to the first
    assert state() == ("ios", ["ios"])
    page.keyboard.press("ArrowRight")
    assert state() == ("android", ["android"])
    page.keyboard.press("ArrowLeft")
    assert state() == ("ios", ["ios"])
    page.keyboard.press("ArrowLeft")  # wraps from the first to the last
    assert state() == ("desktop", ["desktop"])
    page.keyboard.press("Home")
    assert state() == ("ios", ["ios"])
    page.keyboard.press("End")
    assert state() == ("desktop", ["desktop"])
    # only the selected tab is a Tab stop, and the panel follows it
    assert page.eval_on_selector_all(TABS, "els => els.filter(e => e.tabIndex === 0).map(e => e.dataset.platform)") == ["desktop"]
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.getAttribute('role')") == "tabpanel"
    # clicking works as well, and sets aria-selected
    page.click("#study-pick-tab-android")
    assert page.get_attribute("#study-pick-tab-android", "aria-selected") == "true"
    assert page.get_attribute("#study-pick-tab-desktop", "aria-selected") == "false"


def test_the_done_screen_shows_the_same_guide(new_context, base_url, tmp_path) -> None:
    page = open_app(new_context("chromium", device="Pixel 7"), base_url)
    build(page, tmp_path, region="Arizona")
    assert _guide(page, "done")["selected"] == ["android"]
    # Both guides come from one component, so their markup is the same apart from the ids and the heading.
    html = """(id) => [...document.querySelectorAll('#study-' + id + ' [role=tabpanel], #study-' + id + ' .what-youll-see')]
        .map((e) => e.innerHTML.replaceAll(id === 'pick' ? 'study-pick' : 'study-done', 'study')).join('|')"""
    assert page.evaluate(html, "pick") == page.evaluate(html, "done")
    assert page.locator("#study-done h3").inner_text() == "Next, open it in Anki"
    page.click("#study-done-tab-ios")  # the guides are independent: the Pick screen's choice is unchanged
    assert _guide(page, "pick")["selected"] == ["android"]


def test_a_page_without_javascript_says_why() -> None:
    html = (REPO / "web" / "index.html").read_text(encoding="utf-8")
    assert "<noscript>" in html
    assert "needs JavaScript" in html.split("<noscript>")[1].split("</noscript>")[0]


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
