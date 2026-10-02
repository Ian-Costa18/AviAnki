"""The "Customize your cards" section end to end, in a real browser (ADR 0028): the picker and
the checkbox redraw the preview, and the .apkg the page builds carries the same CSS Python's
`compose_css` writes. Runs in Chromium and WebKit against the fixture catalog.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from urllib.parse import quote

from app_support import ALL_CARDS, READY, build, choose, open_app

from avianki.deck import themes
from avianki.deck.notetypes import models_for

QUESTION = "#preview-question"
ANSWER = "#preview-answer"
# Stands in for the clipboard so the test can read what "Copy theme" wrote (read access is a permission).
CLIPBOARD_STUB = "window.__copied = null; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (t) => { window.__copied = t; } } });"
CLIPBOARD_DENIED = "Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('denied'); } } });"
CARD_CSS = "document.getElementById('card-css').textContent"


def frame_eval(page, frame_selector: str, script: str):
    """Run `script` in the document of the preview iframe (the sandbox keeps scripts out of it)."""
    return page.evaluate(
        "([sel, body]) => { const d = document.querySelector(sel).contentDocument;"
        " return new Function('document', 'return ' + body)(d); }",
        [frame_selector, script],
    )


def preview_ready(page) -> None:
    page.wait_for_function(
        "() => ['#preview-question', '#preview-answer'].every(s => {"
        " const d = document.querySelector(s).contentDocument;"
        " return d && d.querySelector('.av') && d.getElementById('card-css').textContent.length > 0; })"
    )


def models_css(apkg: Path, workdir: Path) -> dict[str, str]:
    """{note type name: css} from the package's collection."""
    db = workdir / "check.anki2"
    with zipfile.ZipFile(apkg) as zf:
        db.write_bytes(zf.read("collection.anki2"))
    con = sqlite3.connect(db)
    try:
        models = json.loads(con.execute("SELECT models FROM col").fetchone()[0])
    finally:
        con.close()
    return {m["name"]: m["css"] for m in models.values()}


def python_css(theme, name_on_photo: bool) -> dict[str, str]:
    return {m.name: m.css for m in models_for(theme, name_on_photo).values()}


def test_customize_sits_below_the_build_button_and_outside_advanced(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    box = page.locator("#customize").bounding_box()
    build_box = page.locator("#build").bounding_box()
    assert box["y"] > build_box["y"]  # below the Generate button
    assert page.locator("#customize").evaluate("el => !el.closest('details')")
    assert page.locator("#customize h3").inner_text() == "Customize your cards"
    assert not page.locator("#advanced").evaluate("el => el.open")  # the preview shows without opening it
    assert page.locator("#preview").is_visible()
    # Advanced keeps the deck options only
    assert page.locator("#advanced #theme").count() == 0
    assert page.locator("#advanced #name-on-photo").count() == 0
    assert page.errors == []


def test_the_preview_uses_a_placeholder_without_the_rock_pigeon(new_context, engine, base_url) -> None:
    """The fixture catalog has no columba-livia, so the preview draws its example card."""
    page = open_app(new_context(engine), base_url)
    preview_ready(page)
    answer = frame_eval(page, ANSWER, "document.body.innerText")
    assert "Rock Pigeon" in answer
    assert "an example, not a real photograph" in answer  # credits are visible even on the placeholder
    assert frame_eval(page, ANSWER, "!!document.querySelector('.replay-button')")
    assert frame_eval(page, QUESTION, "!document.body.innerText.includes('Rock Pigeon')")  # no name leak


def test_the_picker_and_the_checkbox_redraw_the_preview(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    preview_ready(page)
    default_css = frame_eval(page, ANSWER, CARD_CSS)
    assert default_css == themes.compose_css("default")

    page.select_option("#theme", "nord")
    page.wait_for_function(
        "(css) => document.querySelector('#preview-answer').contentDocument"
        ".getElementById('card-css').textContent !== css", arg=default_css)
    nord_css = frame_eval(page, ANSWER, CARD_CSS)
    assert nord_css == frame_eval(page, QUESTION, CARD_CSS)  # both sides share the note type's CSS
    assert nord_css == themes.compose_css("nord")
    assert frame_eval(page, ANSWER, "getComputedStyle(document.body).backgroundColor") \
        == "rgb(236, 239, 244)"  # Nord's Snow Storm
    assert page.locator("#theme-desc").inner_text().strip()  # the one-line description

    assert frame_eval(page, ANSWER, "!document.querySelector('.photo .names')")
    page.check("#name-on-photo")
    page.wait_for_function(
        "() => document.querySelector('#preview-answer').contentDocument.querySelector('.photo .names')")
    # the names are on the picture, the credits still below it
    inside = frame_eval(
        page, ANSWER,
        "(() => { const p = document.querySelector('.photo').getBoundingClientRect();"
        " const n = document.querySelector('.photo .names').getBoundingClientRect();"
        " return n.top >= p.top - 1 && n.bottom <= p.bottom + 1; })()",
    )
    assert inside
    assert frame_eval(page, ANSWER, "!document.querySelector('.photo').contains(document.querySelector('.credits'))")
    assert frame_eval(page, ANSWER, "document.body.innerText.includes('an example, not a real photograph')")

    page.check("#preview-dark")
    page.wait_for_function(
        "() => document.querySelector('#preview-answer').contentDocument.body.classList.contains('nightMode')")
    assert frame_eval(page, ANSWER, "getComputedStyle(document.body).backgroundColor") \
        == "rgb(46, 52, 64)"  # Nord's Polar Night
    assert page.errors == []


def test_the_question_card_switcher_follows_the_ticked_card_types(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url)
    preview_ready(page)
    assert page.locator("#preview-card-wrap").is_visible()  # photo and audio are ticked by default
    choose(page, cards=("photo",))
    page.wait_for_selector("#preview-card-wrap", state="hidden")  # one type ticked, nothing to switch
    choose(page, cards=("photo", "audio"))
    page.wait_for_selector("#preview-card-wrap:not([hidden])")
    page.select_option("#preview-card", "audio")
    page.wait_for_function(
        "() => document.querySelector('#preview-question').contentDocument.querySelector('.replay-button')")
    assert frame_eval(page, QUESTION, "!document.querySelector('.photo')")  # an audio question has no picture


def test_the_built_deck_carries_the_css_the_preview_showed(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url)
    preview_ready(page)
    page.select_option("#theme", "field-guide")
    page.check("#name-on-photo")
    shown = frame_eval(page, ANSWER, CARD_CSS)

    files = build(page, tmp_path, region="Massachusetts", cards=ALL_CARDS)
    got = models_css(files[0], tmp_path)
    want = python_css("field-guide", True)
    assert got == want
    assert set(got.values()) == {shown}  # one look for every note type, and it is what was previewed
    assert page.errors == []


def test_a_custom_theme_updates_the_preview_and_the_built_deck(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(CLIPBOARD_STUB)
    page = open_app(context, base_url)
    preview_ready(page)
    assert page.locator("#custom").is_hidden()
    page.select_option("#theme", "custom")
    page.wait_for_selector("#custom:not([hidden])")
    page.select_option("#custom-from", "nord")

    page.fill("#custom-light-background", "#fff7e0")  # colour inputs take a value like a picker would set
    page.select_option("#custom-font", "mono")
    page.select_option("#custom-name_style", "caps")
    page.select_option("#custom-corners", "round")
    page.wait_for_function(
        "() => document.querySelector('#preview-answer').contentDocument"
        ".querySelector('.av') && getComputedStyle(document.querySelector('#preview-answer')"
        ".contentDocument.body).backgroundColor === 'rgb(255, 247, 224)'")
    assert "monospace" in frame_eval(page, ANSWER, "getComputedStyle(document.querySelector('.av')).fontFamily")

    # Copy theme: a TOML snippet the CLI reads back to the same tokens
    page.click("#copy-theme")
    page.wait_for_function("() => document.getElementById('copy-status').textContent.length > 0")
    text = page.evaluate("window.__copied")
    assert text and page.locator("#theme-text").is_hidden()
    tokens = themes.tokens_from_toml(text)
    assert tokens.font == "mono"
    assert tokens.name_style == "caps"
    assert tokens.corners == "round"
    assert tokens.light.background == "#fff7e0"

    files = build(page, tmp_path, region="Massachusetts", cards=ALL_CARDS)
    assert models_css(files[0], tmp_path) == python_css(tokens, False)
    assert page.errors == []


def test_copy_theme_shows_the_text_when_the_clipboard_is_denied(new_context, engine, base_url) -> None:
    context = new_context(engine)
    context.add_init_script(CLIPBOARD_DENIED)
    page = open_app(context, base_url)
    page.select_option("#theme", "custom")
    page.click("#copy-theme")
    page.wait_for_selector("#theme-text:not([hidden])")
    assert themes.tokens_from_toml(page.input_value("#theme-text")).font == "sans"
    assert "--theme-file" in page.inner_text("#copy-status")


def test_the_look_lives_in_the_address_and_in_local_storage(new_context, engine, base_url) -> None:
    context = new_context(engine)
    page = open_app(context, base_url)
    preview_ready(page)
    page.select_option("#theme", "slate")
    page.check("#name-on-photo")
    page.wait_for_function("() => location.hash.length > 1")
    link = page.url

    # the link reproduces the look
    other = open_app(new_context(engine), base_url)
    other.goto(link)
    other.reload()
    other.wait_for_selector(READY)
    preview_ready(other)
    assert other.input_value("#theme") == "slate"
    assert other.is_checked("#name-on-photo")
    assert frame_eval(other, ANSWER, "!!document.querySelector('.photo .names')")

    # and so does the same browser profile with no hash (localStorage)
    again = open_app(context, base_url)
    preview_ready(again)
    assert again.input_value("#theme") == "slate"
    assert again.is_checked("#name-on-photo")


def test_a_bad_link_falls_back_to_the_default_look(new_context, engine, base_url) -> None:
    page = open_app(new_context(engine), base_url, "#theme=" + quote("nope; } body{display:none"))
    preview_ready(page)
    assert page.input_value("#theme") == "default"
    assert not page.is_checked("#name-on-photo")
    assert page.errors == []


def test_no_horizontal_scroll_on_a_phone(new_context, engine, base_url) -> None:
    for width in (360, 390):
        context = new_context(engine, viewport={"width": width, "height": 800})
        page = open_app(context, base_url)
        preview_ready(page)
        page.select_option("#theme", "custom")
        page.wait_for_selector("#custom:not([hidden])")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
        # the two sides stack on a phone
        q = page.locator("#preview-question").bounding_box()
        a = page.locator("#preview-answer").bounding_box()
        assert a["y"] > q["y"] + q["height"] - 1, width
