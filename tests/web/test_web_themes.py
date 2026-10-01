"""The website's themes against Python's (ADR 0028), and what a theme does to a card in a real browser.

* ``themes.js`` and ``deck/themes.py`` must write the same CSS, the same back templates, the same note
  type JSON and the same TOML, for every built-in theme and layout and for custom token sets; and
  refuse the same bad values.
* In Chromium and WebKit, every theme and layout leaves the photo exactly where it was between the
  question and the answer (ADR 0025), keeps the credits and the IOC tag visible on the answer, and (for
  "name on the photo") keeps the names on the picture, even a tall one, in light and in dark mode.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from avianki.deck import themes
from avianki.deck.notetypes import models_for

LOOKS = [(name, overlay) for name in themes.THEME_NAMES for overlay in (False, True)]

CUSTOMS = {
    "all choices changed": {
        "font": "mono", "name_style": "caps", "name_weight": "regular", "corners": "square", "rule": "side",
        "light": {"background": "#fff7e0", "text": "#3b2f00", "secondary": "#6a5a1a", "name": "#c2410c",
                  "accent": "#e11d48", "credits": "#6a5a1a"},
        "night": {"background": "#2a2208", "text": "#fff3c4", "secondary": "#e0cf8a", "name": "#fdba74",
                  "accent": "#fb7185", "credits": "#e0cf8a"},
    },
    "upper case colours are written in lower case": {
        "font": "humanist", "name_style": "normal", "name_weight": "bold", "corners": "round", "rule": "none",
        "light": {"background": "#ABCDEF", "text": "#000000", "secondary": "#333333", "name": "#112233",
                  "accent": "#AA00AA", "credits": "#444444"},
        "night": {"background": "#010203", "text": "#FFFFFF", "secondary": "#CCCCCC", "name": "#EEEEEE",
                  "accent": "#00FFFF", "credits": "#DDDDDD"},
    },
    "the default's own tokens": themes.tokens_as_dict(themes.DEFAULT_TOKENS),
}

BAD_COLOURS = ["red", "#fff", "#12345", "#1234567", "#12345g", "123456", "#123456\n", " #123456", "#123456;}", "url(x)", ""]
BAD_CHOICES = [
    ("font", "Comic Sans"), ("font", "serif; } body { display:none"), ("name_style", "italic"),
    ("name_weight", "900"), ("corners", "50%"), ("rule", "left"),
]


def _evaluate(page, script: str, arg=None):
    return page.evaluate("async (arg) => {" + "const nt = await (await fetch('/js/notetypes.json')).json();"
                         "const T = await import('/js/themes.js');" + script + "}", arg)


# --- the page writes what Python writes ----------------------------------------------------------------


def test_every_theme_and_layout_makes_the_same_note_types_as_python(page) -> None:
    got = _evaluate(
        page,
        "return arg.map(([theme, overlay]) => [theme, overlay, T.modelsFor(nt, theme, overlay)]);",
        [list(look) for look in LOOKS],
    )
    assert len(got) == len(LOOKS) >= 16
    for theme, overlay, models in got:
        want = [json.loads(json.dumps(m.to_json(0, 0))) for m in models_for(theme, overlay).values()]
        assert models == want, (theme, overlay)


@pytest.mark.parametrize("overlay", [False, True])
def test_the_composed_css_and_back_are_byte_identical(overlay, page) -> None:
    got = _evaluate(
        page,
        "return arg.map((theme) => [T.composeCss(nt.look, theme, " + ("true" if overlay else "false") + "), "
        "T.backFor(nt.look, " + ("true" if overlay else "false") + ")]);",
        list(themes.THEME_NAMES),
    )
    for name, (css, back) in zip(themes.THEME_NAMES, got, strict=True):
        assert css == themes.compose_css(name, overlay), name
        from avianki.deck.notetypes import back_for

        assert back == back_for(overlay), name


def test_a_default_page_build_carries_card_css_exactly(page) -> None:
    css = _evaluate(page, "return T.composeCss(nt.look);")
    assert css == themes.BASE_CSS


@pytest.mark.parametrize("name", list(CUSTOMS))
@pytest.mark.parametrize("overlay", [False, True])
def test_a_custom_theme_makes_the_same_css_as_python(name, overlay, page) -> None:
    tokens = CUSTOMS[name]
    js = _evaluate(
        page, "return T.composeCss(nt.look, arg.tokens, arg.overlay);", {"tokens": tokens, "overlay": overlay}
    )
    assert js == themes.compose_css(themes.tokens_from_mapping(tokens), overlay)
    assert js.startswith(themes.BASE_CSS)


def test_a_custom_theme_in_the_models_equals_models_for(page) -> None:
    tokens = CUSTOMS["all choices changed"]
    got = _evaluate(page, "return T.modelsFor(nt, arg, true);", tokens)
    want = [json.loads(json.dumps(m.to_json(0, 0))) for m in models_for(themes.tokens_from_mapping(tokens), True).values()]
    assert got == want


@pytest.mark.parametrize("name", list(themes.THEME_NAMES) + list(CUSTOMS))
def test_the_toml_the_page_copies_is_the_toml_python_writes(name, page) -> None:
    tokens = themes.THEMES[name].tokens if name in themes.THEMES else themes.tokens_from_mapping(CUSTOMS[name])
    text = _evaluate(page, "return T.tokensToToml(arg, nt.look);", themes.tokens_as_dict(tokens))
    assert text == themes.tokens_to_toml(tokens)
    assert themes.tokens_from_toml(text) == tokens  # and the CLI reads it back


# --- the page refuses what Python refuses --------------------------------------------------------------


@pytest.mark.parametrize("bad", BAD_COLOURS)
def test_the_page_and_python_refuse_the_same_colours(bad, page) -> None:
    tokens = themes.tokens_as_dict(themes.DEFAULT_TOKENS)
    tokens["light"]["name"] = bad
    message = _evaluate(
        page, "try { T.validateTokens(arg, nt.look); return null; } catch (e) { return e instanceof T.ThemeError ? e.message : 'other: ' + e; }", tokens
    )
    assert message and "colour" in message and not message.startswith("other"), (bad, message)
    with pytest.raises(themes.ThemeError):
        themes.tokens_from_mapping(tokens)


@pytest.mark.parametrize(("key", "bad"), BAD_CHOICES)
def test_the_page_and_python_refuse_the_same_choices(key, bad, page) -> None:
    tokens = themes.tokens_as_dict(themes.DEFAULT_TOKENS)
    tokens[key] = bad
    message = _evaluate(
        page, "try { T.validateTokens(arg, nt.look); return null; } catch (e) { return e instanceof T.ThemeError ? e.message : 'other: ' + e; }", tokens
    )
    assert message and key in message
    with pytest.raises(themes.ThemeError):
        themes.tokens_from_mapping(tokens)


def test_the_page_refuses_unknown_keys_and_unknown_themes(page) -> None:
    tokens = {**themes.tokens_as_dict(themes.DEFAULT_TOKENS), "extra": "x"}
    message = _evaluate(
        page, "try { T.validateTokens(arg, nt.look); return null; } catch (e) { return e.message; }", tokens
    )
    assert "unknown key" in message
    message = _evaluate(page, "try { T.composeCss(nt.look, 'neon'); return null; } catch (e) { return e.message; }")
    assert "unknown theme" in message


def test_nothing_but_a_colour_or_a_table_key_reaches_the_css(page) -> None:
    marker = "}body{display:none"
    tokens = themes.tokens_as_dict(themes.DEFAULT_TOKENS)
    tokens["light"]["name"] = "#abcdef"
    css = _evaluate(page, "return T.composeCss(nt.look, arg);", tokens)
    assert marker not in css and "#abcdef" in css
    tokens["font"] = marker
    message = _evaluate(page, "try { T.composeCss(nt.look, arg); return null; } catch (e) { return e.message; }", tokens)
    assert message and "font" in message


# --- the look in a link --------------------------------------------------------------------------------


def test_a_look_survives_the_page_address(page) -> None:
    state = {"theme": "custom", "custom": CUSTOMS["all choices changed"], "nameOnPhoto": True}
    out = _evaluate(
        page,
        "const hash = T.lookToHash(arg, nt.look); const back = T.lookFromHash(hash, nt.look);"
        "return {hash, back, again: T.lookToHash(back, nt.look)};",
        state,
    )
    assert out["back"] == state and out["again"] == out["hash"]
    assert out["hash"].startswith("#theme=custom&") and "photo=1" in out["hash"]
    assert "<" not in out["hash"] and " " not in out["hash"]


def test_a_built_in_look_is_a_short_link(page) -> None:
    out = _evaluate(
        page,
        "return [T.lookToHash({theme: 'nord', custom: null, nameOnPhoto: true}, nt.look),"
        " T.lookToHash({theme: 'default', custom: null, nameOnPhoto: false}, nt.look)];",
    )
    assert out == ["#theme=nord&photo=1", "#theme=default"]


@pytest.mark.parametrize(
    "hash_",
    [
        "", "#", "#photo=1", "#theme=neon", "#theme=custom", "#theme=custom&font=serif",
        "#theme=custom&font=serif&name_style=normal&name_weight=bold&corners=slight&rule=none&light=ffffff&night=000000",
        "#theme=custom&font=serif&name_style=normal&name_weight=bold&corners=slight&rule=none"
        "&light=ffffff,000000,111111,222222,333333,44444g&night=000000,ffffff,eeeeee,dddddd,cccccc,bbbbbb",
        "#theme=nord%00",
    ],
)
def test_a_bad_link_changes_nothing(hash_, page) -> None:
    got = _evaluate(page, "return T.lookFromHash(arg, nt.look);", hash_)
    assert got is None


# --- a theme in a real browser ------------------------------------------------------------------------


def _svg_photo(width: int, height: int) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7b8a5a"/>'
        '<stop offset="1" stop-color="#c9b48a"/></linearGradient></defs>'
        f'<rect width="{width}" height="{height}" fill="url(#g)"/></svg>'
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg)


PHOTOS = {"landscape": _svg_photo(800, 600), "portrait": _svg_photo(450, 600), "wide": _svg_photo(800, 300), "panorama": _svg_photo(1600, 240)}

CARD_JS = """
async ({theme, overlay, night, photo, withPhoto}) => {
  const nt = await (await fetch('/js/notetypes.json')).json();
  const { composeCss, backFor } = await import('/js/themes.js');
  const { renderTemplate, cardDocument, replayButton } = await import('/js/preview.js');
  const fields = {
    SpeciesId: 'columba-livia', Name: 'Rock Pigeon', SciName: 'Columba livia', IocName: 'Rock Dove',
    Photo: withPhoto ? `<img src="${photo}" alt="">` : '', Photo2: '', Audio: replayButton(''), Audio2: '',
    Credits: '<div class="credits">Photo: <i>A long file name for the photograph, Dunnet Head, Scotland</i> by ' +
      '<b>someone</b> · <a href="#">CC BY 4.0</a> · <a href="#">source</a>. Recording: <i>Rock Pigeon</i> by ' +
      '<b>another</b> · <a href="#">CC0 1.0</a></div>',
  };
  const css = composeCss(nt.look, theme, overlay);
  return {
    front: cardDocument({css, body: renderTemplate(nt.models.photo.json.tmpls[0].qfmt, fields), night}),
    back: cardDocument({css, body: renderTemplate(backFor(nt.look, overlay), fields), night}),
  };
}
"""

MEASURE_JS = """
() => {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom};
  };
  const visible = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0 && r.width > 0 && r.height > 0;
  };
  const q = (s) => document.querySelector(s);
  return {
    img: rect(q('.photo img')),
    names: rect(q('.photo .names')),
    namesAnywhere: rect(q('.names')),
    credits: rect(q('.credits')), creditsVisible: visible(q('.credits')),
    tag: rect(q('.ioc-tag')), tagVisible: visible(q('.ioc-tag')),
    name: visible(q('.name')), sci: visible(q('.sci')),
    play: rect(q('.replay-button svg')), playVisible: visible(q('.replay-button')),
    label: rect(q('.sound-label')),
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    docHeight: document.documentElement.scrollHeight,
    color: getComputedStyle(q('.credits') || document.body).color,
    background: getComputedStyle(document.body).backgroundColor,
  };
}
"""


def _measure(page, html: str) -> dict:
    page.set_content(html)
    page.wait_for_function("() => [...document.images].every((i) => i.complete)")
    return page.evaluate(MEASURE_JS)


def _approx(a: float, b: float, eps: float = 0.51) -> bool:
    return abs(a - b) <= eps


@pytest.fixture
def phone(page):
    page.set_viewport_size({"width": 390, "height": 844})
    return page


@pytest.mark.parametrize(("theme", "overlay"), LOOKS)
@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_the_photo_does_not_move_and_the_answer_keeps_credits_and_tag(theme, overlay, night, phone) -> None:
    for kind, photo in PHOTOS.items():
        docs = phone.evaluate(CARD_JS, {"theme": theme, "overlay": overlay, "night": night, "photo": photo, "withPhoto": True})
        front, back = _measure(phone, docs["front"]), _measure(phone, docs["back"])
        where = (theme, overlay, night, kind)
        # ADR 0025: the photo is in the same place, at the same size, before and after the flip.
        for key in ("x", "y", "w", "h"):
            assert _approx(front["img"][key], back["img"][key]), (where, key, front["img"], back["img"])
        assert front["img"]["y"] < 40, where  # nothing above the photo but the card's own padding
        # the answer: names, tag, credits and the play button, all there and on screen
        assert back["name"] and back["sci"] and back["tagVisible"] and back["creditsVisible"] and back["playVisible"], where
        assert back["play"]["w"] >= 32 and back["play"]["h"] >= 32, (where, back["play"])  # the button never shrinks
        assert back["label"] and back["label"]["x"] >= back["play"]["right"] - 1, where  # its label sits beside it
        assert back["credits"]["right"] <= 391 and back["credits"]["x"] >= -1, where
        assert back["scrollWidth"] <= back["innerWidth"], (where, "scrolls sideways")
        assert front["scrollWidth"] <= front["innerWidth"], where
        if overlay:
            # the names sit on the picture, inside it, and the picture is not clipped or overhung
            img, names = back["img"], back["names"]
            assert names is not None, where
            assert names["x"] >= img["x"] - 1 and names["right"] <= img["right"] + 1, (where, names, img)
            assert names["bottom"] <= img["bottom"] + 1 and names["y"] >= img["y"] - 1, (where, names, img)
            assert back["credits"]["y"] > img["bottom"] - 1, where  # credits stay below the photo
            assert back["play"]["y"] > img["bottom"] - 1, where
        else:
            assert back["names"] is None
            assert back["namesAnywhere"]["y"] >= back["img"]["bottom"] - 1, where


@pytest.mark.parametrize(("theme", "overlay"), LOOKS)
def test_a_note_with_no_photo_still_shows_the_names_below(theme, overlay, phone) -> None:
    docs = phone.evaluate(CARD_JS, {"theme": theme, "overlay": overlay, "night": False, "photo": "", "withPhoto": False})
    back = _measure(phone, docs["back"])
    assert back["img"] is None and back["names"] is None
    assert back["name"] and back["sci"] and back["tagVisible"] and back["creditsVisible"], (theme, overlay)
    assert back["namesAnywhere"]["x"] >= 0 and back["namesAnywhere"]["right"] <= 390


@pytest.mark.parametrize("overlay", [False, True])
def test_a_custom_theme_keeps_the_same_promises(overlay, phone) -> None:
    for kind, photo in PHOTOS.items():
        docs = phone.evaluate(
            CARD_JS,
            {"theme": CUSTOMS["all choices changed"], "overlay": overlay, "night": True, "photo": photo, "withPhoto": True},
        )
        front, back = _measure(phone, docs["front"]), _measure(phone, docs["back"])
        assert front["img"] == pytest.approx(back["img"], abs=0.51), kind
        assert back["tagVisible"] and back["creditsVisible"] and back["playVisible"], kind


def test_the_night_background_is_the_themes_own(phone) -> None:
    docs = phone.evaluate(CARD_JS, {"theme": "nord", "overlay": False, "night": True, "photo": PHOTOS["landscape"], "withPhoto": True})
    assert _measure(phone, docs["back"])["background"] == "rgb(46, 52, 64)"  # Nord Polar Night #2e3440
    docs = phone.evaluate(CARD_JS, {"theme": "nord", "overlay": False, "night": False, "photo": PHOTOS["landscape"], "withPhoto": True})
    assert _measure(phone, docs["back"])["background"] == "rgb(236, 239, 244)"  # Snow Storm #eceff4
