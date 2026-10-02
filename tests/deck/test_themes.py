"""Card themes and the name-on-photo layout (ADR 0028): tokens, CSS generation, TOML, contrast, templates."""

from __future__ import annotations

import re

import pytest

from avianki.deck import themes
from avianki.deck.notetypes import FIELDS, MODELS, back_for, models_for
from avianki.deck.themes import (
    BASE_CSS,
    COLOUR_KEYS,
    DEFAULT_TOKENS,
    THEME_NAMES,
    THEMES,
    ThemeError,
    Tokens,
    compose_css,
    css_for,
    theme_css,
    tokens_from_mapping,
    tokens_from_toml,
    tokens_to_toml,
)

LOOKS = [(name, overlay) for name in THEME_NAMES for overlay in (False, True)]


# --- the registry ------------------------------------------------------------------------------


def test_the_registry_has_the_documented_themes() -> None:
    assert {"default", "serif", "field-guide", "nord"} <= set(THEME_NAMES)
    assert THEME_NAMES[0] == "default" == themes.DEFAULT_THEME
    assert len(THEME_NAMES) >= 8


@pytest.mark.parametrize("name", THEME_NAMES)
def test_every_theme_has_a_one_line_description(name: str) -> None:
    text = THEMES[name].description
    assert text and "\n" not in text and text.endswith(".") and len(text) < 120


def test_default_adds_no_css_at_all() -> None:
    assert theme_css("default") == ""
    assert compose_css("default", False) == BASE_CSS
    assert compose_css() == BASE_CSS


def test_the_composition_rule() -> None:
    assert compose_css("nord", False) == BASE_CSS + "\n" + theme_css("nord")
    assert compose_css("default", True) == BASE_CSS + "\n" + themes.NAME_ON_PHOTO_CSS
    assert compose_css("nord", True) == BASE_CSS + "\n" + theme_css("nord") + "\n" + themes.NAME_ON_PHOTO_CSS


def test_an_unknown_theme_is_refused() -> None:
    with pytest.raises(ThemeError, match="unknown theme"):
        compose_css("nope")


# --- the CSS every theme writes ---------------------------------------------------------------------


@pytest.mark.parametrize(("name", "overlay"), LOOKS)
def test_theme_css_is_safe_and_has_both_night_modes(name: str, overlay: bool) -> None:
    css = compose_css(name, overlay)
    assert not re.search(r"@import|url\(|expression\(|javascript:|<|>(?!\s*\.)|\\", themes_only(css)), name
    assert ".nightMode" in css and ".night_mode" in css
    assert "@" not in themes_only(css).replace("@media", "")  # no placeholder was left unfilled
    assert css.count("{") == css.count("}")


def themes_only(css: str) -> str:
    """The part of ``css`` a theme and layout added: everything after card.css."""
    assert css.startswith(BASE_CSS)
    return css[len(BASE_CSS) :]


@pytest.mark.parametrize("name", [n for n in THEME_NAMES if n != "default"])
def test_every_theme_redeclares_its_night_variables(name: str) -> None:
    css = theme_css(name)
    # .nightMode .av (0,2,0) beats .av, so a theme's day variables must be set again at night.
    assert re.search(r"\.nightMode \.av, \.night_mode \.av \{[^}]*--ink:", css)
    assert re.search(r"\.card\.nightMode, \.card\.night_mode \{[^}]*background:", css)


@pytest.mark.parametrize("name", [n for n in THEME_NAMES if n != "default"])
def test_themes_use_system_fonts_only(name: str) -> None:
    css = theme_css(name)
    assert "@font-face" not in css and "url(" not in css
    assert all(font.endswith(("sans-serif", "serif", "monospace")) for font in themes.FONTS.values())


@pytest.mark.parametrize("name", [n for n in THEME_NAMES if n != "default"])
def test_themes_never_hide_the_credits_or_the_tag(name: str) -> None:
    css = theme_css(name)
    assert not re.search(r"\.(credits|ioc-tag|ioc)\s*\{[^}]*display:\s*none", css)
    assert not re.search(r"\.(credits|ioc-tag|ioc)\s*\{[^}]*visibility:\s*hidden", css)
    assert not re.search(r"\.(credits|ioc-tag)\s*\{[^}]*font-size:\s*([0-9]|10)(\.\d+)?px", css), name  # never smaller than 11px


@pytest.mark.parametrize("name", [n for n in THEME_NAMES if n != "default"])
def test_themes_leave_the_photo_alone(name: str) -> None:
    # ADR 0025: the photo is in the same place on both sides, and nothing sits above it.
    css = theme_css(name)
    assert not re.search(r"\.photo[^{]*\{[^}]*(margin-top|padding-top|position|(?<![a-z-])order)\s*:", css)
    assert not re.search(r"\.(av|prompt|sound)[^{]*\{[^}]*order\s*:", css)


# --- contrast (WCAG 2.x) -----------------------------------------------------------------------------


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_contrast_function_matches_known_values() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)  # the classic AA grey


@pytest.mark.parametrize("name", THEME_NAMES)
@pytest.mark.parametrize("mode", ["light", "night"])
def test_every_theme_meets_aa_in_both_modes(name: str, mode: str) -> None:
    colours = getattr(THEMES[name].tokens, mode)
    # Small text: 4.5. The name is 24px or more (1.6em of 17px, or 1.45em in capitals) and so is
    # "large text" (3:1). The accent colours the IOC tag's outline and the rule: graphics, 3:1.
    for key in ("text", "secondary", "credits"):
        assert contrast(getattr(colours, key), colours.background) >= 4.5, (name, mode, key)
    for key in ("name", "accent"):
        assert contrast(getattr(colours, key), colours.background) >= 3.0, (name, mode, key)


@pytest.mark.parametrize("mode", ["light", "night"])
def test_nord_uses_the_official_palette_and_passes(mode: str) -> None:
    official = {
        "#2e3440", "#3b4252", "#434c5e", "#4c566a", "#d8dee9", "#e5e9f0", "#eceff4",
        "#8fbcbb", "#88c0d0", "#81a1c1", "#5e81ac",
    }  # fmt: skip
    colours = getattr(THEMES["nord"].tokens, mode)
    for key in COLOUR_KEYS:
        assert getattr(colours, key) in official, (mode, key)
    assert THEMES["nord"].tokens.light.background == "#eceff4" and THEMES["nord"].tokens.night.background == "#2e3440"
    assert contrast(colours.text, colours.background) >= 7


def test_the_nord_credit_box_keeps_the_credit_text_readable() -> None:
    css = theme_css("nord")
    light = re.search(r"\.credits \{[^}]*background:(#[0-9a-f]{6})", css)
    night = re.search(r"\.night_mode \.credits \{[^}]*background:(#[0-9a-f]{6})", css)
    assert light and night
    assert contrast(THEMES["nord"].tokens.light.credits, light.group(1)) >= 4.5
    assert contrast(THEMES["nord"].tokens.night.credits, night.group(1)) >= 4.5


# --- tokens: validation -------------------------------------------------------------------------------


def _mapping(**overrides: object) -> dict:
    data: dict = {
        "font": "serif",
        "light": {"background": "#ffffff", "text": "#000000"},
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "bad",
    ["red", "#fff", "#12345", "#1234567", "#12345g", "123456", "#123456\n", " #123456", "#123456;}", "url(x)", "", None, 5],
)
def test_a_colour_must_be_exactly_rrggbb(bad: object) -> None:
    with pytest.raises(ThemeError, match="colour"):
        tokens_from_mapping({"light": {"text": bad}})


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("font", "Comic Sans"),
        ("font", "serif; } body { display:none"),
        ("name_style", "italic"),
        ("name_weight", "900"),
        ("corners", "50%"),
        ("rule", "left"),
        ("font", None),
        ("font", ["sans"]),
    ],
)
def test_a_choice_must_be_a_key_of_its_table(key: str, bad: object) -> None:
    with pytest.raises(ThemeError, match=key):
        tokens_from_mapping({key: bad})


def test_unknown_keys_are_errors() -> None:
    with pytest.raises(ThemeError, match="unknown key"):
        tokens_from_mapping({"colour": "#ffffff"})
    with pytest.raises(ThemeError, match="unknown key"):
        tokens_from_mapping({"light": {"textt": "#ffffff"}})
    with pytest.raises(ThemeError, match="table"):
        tokens_from_mapping({"light": "#ffffff"})


def test_colours_are_normalised_to_lower_case() -> None:
    assert tokens_from_mapping({"light": {"text": "#AABBCC"}}).light.text == "#aabbcc"


def test_values_left_out_keep_the_base() -> None:
    tokens = tokens_from_mapping({"font": "mono"})
    assert tokens.font == "mono" and tokens.light == DEFAULT_TOKENS.light
    base = THEMES["nord"].tokens
    assert tokens_from_mapping({"corners": "square"}, base).light == base.light


def test_free_text_never_reaches_the_css() -> None:
    tokens = tokens_from_mapping({"font": "mono", "light": {"name": "#abcdef"}})
    css = css_for(tokens)
    assert "#abcdef" in css and themes.FONTS["mono"] in css
    assert "@" not in css


# --- tokens: the TOML form ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", THEME_NAMES)
def test_toml_round_trips_every_theme(name: str) -> None:
    tokens = THEMES[name].tokens
    text = tokens_to_toml(tokens)
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert tokens_from_toml(text) == tokens
    assert tokens_to_toml(tokens_from_toml(text)) == text


def test_toml_example_in_the_docs_is_valid() -> None:
    text = """
    font = "rounded"
    name_style = "caps"
    name_weight = "regular"
    corners = "round"
    rule = "side"

    [light]
    background = "#fff7e0"
    name = "#c2410c"

    [night]
    background = "#2a2208"
    """
    text = "\n".join(line.strip() for line in text.splitlines())
    tokens = tokens_from_toml(text)
    assert tokens.light.background == "#fff7e0" and tokens.light.text == DEFAULT_TOKENS.light.text
    assert tokens.corners == "round" and tokens.rule == "side"


@pytest.mark.parametrize("text", ["font = ", "[light", 'font = "serif" "x"', "x = 1\nx = 2"])
def test_bad_toml_is_a_theme_error(text: str) -> None:
    with pytest.raises(ThemeError, match="TOML"):
        tokens_from_toml(text)


# --- the layout ----------------------------------------------------------------------------------------


def test_the_overlay_back_keeps_everything_the_normal_back_has() -> None:
    plain, overlay = back_for(False), back_for(True)
    for needle in ("{{Name}}", "{{SciName}}", "{{IocName}}", "{{Photo}}", "{{Audio}}", "{{Credits}}", "ioc-tag"):
        assert needle in plain and needle in overlay, needle
    assert plain.count('class="names"') == 1
    # Names appear twice in the overlay template: over the photo, and again when there is no photo.
    assert overlay.count('class="names"') == 2
    assert "{{#Photo}}" in overlay and "{{^Photo}}" in overlay
    assert set(re.findall(r"\{\{[#/^]?(\w+)\}\}", overlay)) <= set(FIELDS)
    assert overlay.startswith('<div class="av">') and 'class="card"' not in overlay


def test_the_overlay_names_sit_inside_the_photo_block() -> None:
    overlay = back_for(True)
    photo_block = overlay[overlay.index("{{#Photo}}") : overlay.index("{{/Photo}}")]
    assert 'class="photo"' in photo_block and "{{Photo}}" in photo_block
    assert photo_block.index("{{Photo}}") < photo_block.index('class="names"')
    assert "{{Credits}}" not in photo_block and "{{Audio}}" not in photo_block  # those stay below the picture
    assert overlay.index("{{Credits}}") > overlay.index("{{/Photo}}")


def test_the_front_does_not_change_with_the_layout() -> None:
    for card_type, model in MODELS.items():
        assert models_for("nord", True)[card_type].templates[0]["qfmt"] == model.templates[0]["qfmt"]


def test_the_layout_sizes_the_photo_by_the_picture_so_the_overlay_cannot_overhang() -> None:
    css = themes.NAME_ON_PHOTO_CSS
    assert re.search(r"\.av \.photo \{[^}]*width:fit-content", css)
    assert re.search(r"\.av \.photo img \{[^}]*max-height:46vh", css)
    assert re.search(r"\.names \{[^}]*position:absolute[^}]*bottom:0", css)
    assert "overflow" not in css  # clipping would hide a tall picture's gradient instead of fitting it


@pytest.mark.parametrize(("name", "overlay"), LOOKS)
def test_models_for_carries_the_composed_css(name: str, overlay: bool) -> None:
    models = models_for(name, overlay)
    assert set(models) == set(MODELS)
    for model in models.values():
        assert model.css == compose_css(name, overlay)
        assert model.templates[0]["afmt"] == back_for(overlay)


def test_models_for_accepts_custom_tokens() -> None:
    custom = Tokens(light=DEFAULT_TOKENS.light, night=DEFAULT_TOKENS.night, font="mono")
    assert models_for(custom, False)["photo"].css == compose_css(custom, False)
    assert themes.FONTS["mono"] in models_for(custom, False)["photo"].css
