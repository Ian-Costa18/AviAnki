"""Card themes and layouts (ADR 0028).

A *theme* is colours and typography. A *layout* is where things sit. Both are chosen when the
deck is built and change only a note type's CSS and template HTML, never its identity (ADR 0009).

The CSS of a card is a plain concatenation, documented once here and mirrored in
``web/js/themes.js``:

    css = card.css  +  "\\n" + <theme css>  +  "\\n" + <layout css>

where a piece that is empty is left out. The default theme and the default layout are empty, so
a deck built with no options carries ``card.css`` byte for byte.

A theme is a set of **tokens**: six colours for day and six for night, a font from a fixed list
and four small choices. ``css_for`` turns tokens into CSS by filling the placeholders of
``themes/_template.css``; the web app does the same with the same template and tables, so the
page and the command line write identical CSS. A built-in theme may add a few rules of its own
(``themes/<name>.css``) on top of its tokens.

Safety: the CSS is generated from validated values only. A colour must match ``#rrggbb``; every
other value is a key of a fixed table. Nothing else is ever put into CSS, whether the tokens came
from the built-in list, a ``--theme-file`` or a link to the website.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Final

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the project supports 3.10, which has no tomllib
    import tomli as tomllib  # ty: ignore[unresolved-import]

HERE: Final = Path(__file__).parent
BASE_CSS: Final[str] = (HERE / "card.css").read_text(encoding="utf-8")
NAME_ON_PHOTO_CSS: Final[str] = (HERE / "name-on-photo.css").read_text(encoding="utf-8")
TEMPLATE_CSS: Final[str] = (HERE / "themes" / "_template.css").read_text(encoding="utf-8")

DEFAULT_THEME: Final = "default"

# --- the fixed tables: the only text a theme can put into CSS besides colours ---------------

FONTS: Final[dict[str, str]] = {
    "sans": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif',
    "serif": 'Georgia, "Iowan Old Style", "Palatino Linotype", Palatino, "Times New Roman", serif',
    "rounded": 'ui-rounded, "SF Pro Rounded", "Hiragino Maru Gothic ProN", "Arial Rounded MT Bold", '
    '"Segoe UI", Roboto, sans-serif',
    "mono": 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
    "humanist": 'Seravek, "Gill Sans Nova", Ubuntu, Calibri, "Gill Sans", "Trebuchet MS", "Segoe UI", sans-serif',
}
NAME_STYLES: Final[dict[str, str]] = {
    "normal": "letter-spacing:-.01em;",
    "caps": "font-variant:small-caps; letter-spacing:.12em; font-size:1.45em;",
}
NAME_WEIGHTS: Final[dict[str, str]] = {"regular": "400", "bold": "700"}
CORNERS: Final[dict[str, str]] = {"square": "2px", "slight": "10px", "round": "22px"}
RULES: Final[dict[str, str]] = {
    "none": "",
    "side": ".av .names { border-left:3px solid var(--accent); padding-left:12px; }",
}
CHOICES: Final[dict[str, dict[str, str]]] = {
    "font": FONTS,
    "name_style": NAME_STYLES,
    "name_weight": NAME_WEIGHTS,
    "corners": CORNERS,
    "rule": RULES,
}

COLOUR_KEYS: Final = ("background", "text", "secondary", "name", "accent", "credits")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")  # used with fullmatch: `$` would let a trailing newline through
_PLACEHOLDER = re.compile(r"@([a-z_.]+)@")


class ThemeError(ValueError):
    """A theme value that is not allowed (a colour that is not #rrggbb, a name not in a table)."""


@dataclass(frozen=True)
class Colours:
    """The colours of one mode: all ``#rrggbb``, normalised to lower case."""

    background: str
    text: str
    secondary: str
    name: str
    accent: str
    credits: str

    def __post_init__(self) -> None:
        for key in COLOUR_KEYS:
            value = getattr(self, key)
            if not isinstance(value, str) or not _HEX.fullmatch(value):
                raise ThemeError(f"{key}: {value!r} is not a colour like #1a2b3c")
            object.__setattr__(self, key, value.lower())


@dataclass(frozen=True)
class Tokens:
    """Everything a theme is made of."""

    light: Colours
    night: Colours
    font: str = "sans"
    name_style: str = "normal"
    name_weight: str = "bold"
    corners: str = "slight"
    rule: str = "none"

    def __post_init__(self) -> None:
        for key, table in CHOICES.items():
            value = getattr(self, key)
            if not isinstance(value, str) or value not in table:
                raise ThemeError(f"{key}: {value!r} is not one of {', '.join(table)}")


@dataclass(frozen=True)
class Theme:
    """A built-in theme: a name, a one-line description, tokens and optional extra rules.

    ``generate`` is False only for ``default``, whose CSS is empty because card.css *is* the
    default look; its tokens are what "Start from default" fills in.
    """

    name: str
    description: str
    tokens: Tokens
    generate: bool = True

    @property
    def extra_css(self) -> str:
        path = HERE / "themes" / f"{self.name}.css"
        return path.read_text(encoding="utf-8") if path.is_file() else ""


def _c(background: str, text: str, secondary: str, name: str, accent: str, credits: str | None = None) -> Colours:
    return Colours(background, text, secondary, name, accent, credits or secondary)


DEFAULT_TOKENS: Final = Tokens(
    light=_c("#ffffff", "#111111", "#5f6368", "#111111", "#5f6368"),
    night=_c("#1c1c1e", "#f1f1f1", "#a0a4a8", "#f1f1f1", "#a0a4a8"),
)

_THEME_LIST: Final[tuple[Theme, ...]] = (
    Theme("default", "Photo first, the system font of whatever you study on, a black name.", DEFAULT_TOKENS, generate=False),
    Theme(
        "serif",
        "A green serif name over the usual layout.",
        Tokens(
            light=_c("#ffffff", "#111111", "#5f6368", "#1d6b40", "#1d6b40"),
            night=_c("#1c1c1e", "#f1f1f1", "#a0a4a8", "#7fd1a0", "#7fd1a0"),
        ),
    ),
    Theme(
        "field-guide",
        "Warm paper, the name in spaced small capitals and an accent rule beside the names.",
        Tokens(
            light=_c("#f4ecd8", "#2c2218", "#695742", "#2c2218", "#9a4a22"),
            night=_c("#1d1913", "#efe5d1", "#b8a68a", "#efe5d1", "#d99a5b"),
            font="serif",
            name_style="caps",
            rule="side",
        ),
    ),
    Theme(
        "nord",
        "The Nord palette: cool Snow Storm paper by day, Polar Night by night, Frost blue accents.",
        Tokens(
            light=_c("#eceff4", "#2e3440", "#4c566a", "#5e81ac", "#5e81ac"),
            night=_c("#2e3440", "#eceff4", "#d8dee9", "#88c0d0", "#88c0d0"),
        ),
    ),
    Theme(
        "slate",
        "Cool blue-grey with square corners and the credits in a thin box.",
        Tokens(
            light=_c("#eef1f5", "#1d2733", "#4f5d6c", "#1d2733", "#3a6490"),
            night=_c("#151a21", "#e6ebf1", "#9aa7b5", "#e6ebf1", "#7fb2e0"),
            corners="square",
        ),
    ),
    Theme(
        "forest",
        "Sage green with round corners and the names on a soft green panel.",
        Tokens(
            light=_c("#edf3ea", "#14281c", "#4b6455", "#1b5e3a", "#2f7a4f"),
            night=_c("#101a14", "#e3efe6", "#9dbba8", "#8fd6a8", "#6cc890"),
            corners="round",
        ),
    ),
    Theme(
        "plate",
        "A vintage plate print: sepia paper, an italic serif name, centred between double rules.",
        Tokens(
            light=_c("#eadfc2", "#3a2815", "#5f4a2e", "#3a2815", "#7a3b1b"),
            night=_c("#221a11", "#ecddbe", "#bda57d", "#f0e2c4", "#d6a06a"),
            font="serif",
            name_weight="regular",
            corners="square",
        ),
    ),
    Theme(
        "minimal",
        "Everything centred on plain paper with a light name and lots of air.",
        Tokens(
            light=_c("#ffffff", "#1a1a1a", "#6a6a6a", "#1a1a1a", "#1a1a1a"),
            night=_c("#161616", "#ececec", "#9a9a9a", "#ececec", "#ececec"),
            name_weight="regular",
            corners="square",
        ),
    ),
    Theme(
        "midnight",
        "Always dark, by day and by night, with a soft blue accent.",
        Tokens(
            light=_c("#0f1422", "#e8ecf6", "#9fabc6", "#ffffff", "#8ab4ff"),
            night=_c("#0f1422", "#e8ecf6", "#9fabc6", "#ffffff", "#8ab4ff"),
        ),
    ),
    Theme(
        "high-contrast",
        "Larger type, pure black on white (white on black at night), strong outlines.",
        Tokens(
            light=_c("#ffffff", "#000000", "#1f1f1f", "#000000", "#000000"),
            night=_c("#000000", "#ffffff", "#e6e6e6", "#ffffff", "#ffe14d"),
            corners="square",
            rule="side",
        ),
    ),
)

THEMES: Final[dict[str, Theme]] = {t.name: t for t in _THEME_LIST}
THEME_NAMES: Final[tuple[str, ...]] = tuple(THEMES)


# --- generating CSS -------------------------------------------------------------------------


def _substitutions(tokens: Tokens) -> dict[str, str]:
    subs = {key: CHOICES[key][getattr(tokens, key)] for key in CHOICES}
    for mode in ("light", "night"):
        colours = getattr(tokens, mode)
        subs.update({f"{mode}.{key}": getattr(colours, key) for key in COLOUR_KEYS})
    return subs


def css_for(tokens: Tokens) -> str:
    """The CSS a set of tokens stands for: ``themes/_template.css`` with its placeholders filled."""
    subs = _substitutions(tokens)
    return _PLACEHOLDER.sub(lambda m: subs[m.group(1)], TEMPLATE_CSS)


def theme_css(theme: str | Tokens) -> str:
    """The theme's CSS piece: "" for ``default``, the generated tokens and extra rules otherwise."""
    if isinstance(theme, Tokens):
        return css_for(theme)
    if theme not in THEMES:
        raise ThemeError(f"unknown theme {theme!r}; expected one of {', '.join(THEME_NAMES)}")
    built = THEMES[theme]
    if not built.generate:
        return ""
    return css_for(built.tokens) + built.extra_css


def compose_css(theme: str | Tokens = DEFAULT_THEME, name_on_photo: bool = False) -> str:
    """card.css, then the theme's CSS, then the layout's, each non-empty piece after a newline."""
    css = BASE_CSS
    for piece in (theme_css(theme), NAME_ON_PHOTO_CSS if name_on_photo else ""):
        if piece:
            css += "\n" + piece
    return css


# --- reading and writing a theme file (TOML) -------------------------------------------------

_SCALARS = tuple(CHOICES)


def tokens_from_mapping(data: Mapping[str, Any], base: Tokens = DEFAULT_TOKENS) -> Tokens:
    """Tokens from parsed TOML (or JSON): anything left out keeps ``base``'s value.

    Unknown keys are an error, so a typo is never silently ignored.
    """
    allowed = {*_SCALARS, "light", "night"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ThemeError(f"unknown key(s) {', '.join(unknown)}; expected {', '.join(sorted(allowed))}")
    changes: dict[str, Any] = {key: data[key] for key in _SCALARS if key in data}
    for mode in ("light", "night"):
        if mode not in data:
            continue
        table = data[mode]
        if not isinstance(table, Mapping):
            raise ThemeError(f"{mode} must be a table of colours")
        bad = sorted(set(table) - set(COLOUR_KEYS))
        if bad:
            raise ThemeError(f"[{mode}] has unknown key(s) {', '.join(bad)}; expected {', '.join(COLOUR_KEYS)}")
        changes[mode] = replace(getattr(base, mode), **table)
    return replace(base, **changes)


def tokens_from_toml(text: str, base: Tokens = DEFAULT_TOKENS) -> Tokens:
    """Parse a theme file. Raises ``ThemeError`` for bad TOML and for any value that is not allowed."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ThemeError(f"not valid TOML: {exc}") from exc
    return tokens_from_mapping(data, base)


def tokens_to_toml(tokens: Tokens) -> str:
    """The shareable form of a theme: what the website's "Copy theme" gives and ``--theme-file`` reads."""
    lines = ["# An AviAnki card theme. Use it with: avianki REGION --theme-file this-file.toml"]
    lines += [f'{key} = "{getattr(tokens, key)}"' for key in _SCALARS]
    for mode in ("light", "night"):
        lines += ["", f"[{mode}]"]
        lines += [f'{key} = "{getattr(getattr(tokens, mode), key)}"' for key in COLOUR_KEYS]
    return "\n".join(lines) + "\n"


def tokens_as_dict(tokens: Tokens) -> dict[str, Any]:
    """Plain data for the web export (field names as in the TOML)."""
    out: dict[str, Any] = {key: getattr(tokens, key) for key in _SCALARS}
    for mode in ("light", "night"):
        out[mode] = {f.name: getattr(getattr(tokens, mode), f.name) for f in fields(Colours)}
    return out
