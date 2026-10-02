#!/usr/bin/env python3
"""The README's card and theme images, in two stages.

**Stage one, the card studio** (``CardStudio``) renders cards. Given a theme and a card type it
screenshots the real thing: the template from ``notetypes.models_for``, the CSS from
``themes.compose_css``, filled with real media and credits from the published catalog. It hands
back a ``RenderedCard`` -- pixels, a size, and the labels the project itself owns (the template's
name, the theme's ``description``). It knows nothing about animation.

**Stage two, the compositor** (``Stage`` and the two loop builders) arranges ``RenderedCard``
pixels on a stage: backdrop, captions, progress bar, the equaliser behind an audio question, the
reveal and the dissolves, and the final GIF. It never looks inside a card and never styles one.

So a card can change -- a new theme, a fourth card type, a different layout -- and the graphics
follow without an edit here. The theme list comes from ``themes.THEMES``, the card types from
``notetypes.CARD_TYPES``, each caption from the theme's own ``description`` and the template's own
name, and every loop is a sequence, so any number of themes or card types works. ``--sync-readme``
rewrites the README's generated tables from the same lists.

The one thing drawn rather than taken from the deck is Anki's own chrome -- the body defaults and
the replay button it substitutes for ``[sound:...]`` -- which lives in Anki, not in our CSS;
``web/js/preview.js`` keeps the same lookalike for the website's preview.

Usage:
    uv run --extra catalog python scripts/gen_card_shots.py
    uv run --extra catalog python scripts/gen_card_shots.py --only themes

Writes into ``docs/examples/``:
    card-<type>-<side>.png, cards.gif    every card type, question and answer
    theme-<name>.png, themes.gif         every built-in theme, day beside night

Needs the ``catalog`` extra and Playwright's Chromium (``uv run playwright install chromium``).
"""

from __future__ import annotations

import argparse
import base64
import io
import math
import mimetypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from avianki.catalog.client import CatalogClient
from avianki.catalog.format import MediaRef, SpeciesEntry
from avianki.deck.credits import credits_field
from avianki.deck.notetypes import CARD_TYPES, models_for
from avianki.deck.themes import THEMES, compose_css

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image as PilImage

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "examples"
RAW = "https://raw.githubusercontent.com/Ian-Costa18/AviAnki/readme-rework/docs/examples"

# Widespread birds a reader is likely to recognise, in order of preference. Any species with
# both a photo and a recording stands in when none of these is in the region.
PREFERRED = (
    "American Robin",
    "Blue Jay",
    "Northern Cardinal",
    "Black-capped Chickadee",
    "Red-winged Blackbird",
    "American Goldfinch",
)

# Anki's chrome, kept the same as the website's preview (web/js/preview.js): its body
# defaults and the replay button it draws for a [sound:...] field.
ANKI_CHROME = """
.card { font-family: arial; font-size: 20px; text-align: center; color: #000; background: #fff; }
.card.nightMode { color: #fff; background-color: #2c2c2c; }
a.replay-button { display: inline-flex; text-decoration: none; cursor: pointer; }
.replay-button svg { width: 40px; height: 40px; }
.replay-button svg circle { fill: #fff; stroke: #8c8c8c; stroke-width: 2; }
.replay-button svg path { fill: #3a3a3a; }
.nightMode .replay-button svg circle { fill: #3a3a3a; stroke: #9a9a9a; }
.nightMode .replay-button svg path { fill: #eee; }
"""

PLAY_ICON = (
    '<svg class="playImage" viewBox="0 0 64 64" version="1.1"><circle cx="32" cy="32" r="29"/>'
    '<path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z"/></svg>'
)
REPLAY_BUTTON = f'<a class="replay-button soundLink" href="#">{PLAY_ICON}</a>'

_SECTION = re.compile(r"\{\{([#^])([A-Za-z0-9_]+)\}\}([\s\S]*?)\{\{/\2\}\}")


# =============================================================================================
#  The browser: the one thing both stages share. It turns HTML into pixels and nothing else.
# =============================================================================================


class Shooter:
    """A headless Chromium page. ``shoot`` returns the PNG bytes of one element."""

    def __init__(self, scale: float = 2) -> None:
        self.scale = scale
        self._pw = None
        self._browser = None

    def __enter__(self) -> Shooter:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def measure(self, html: str, viewport_h: int, selector: str) -> tuple[float, float]:
        """The drawn width and height of one element, in CSS px."""
        assert self._browser is not None, "use Shooter as a context manager"
        page = self._browser.new_page(viewport={"width": 1400, "height": viewport_h})
        try:
            page.set_content(html)
            page.wait_for_load_state("load")
            box = page.locator(selector).bounding_box()
            return (box["width"], box["height"]) if box else (0.0, 0.0)
        finally:
            page.close()

    def shoot(self, html: str, viewport_h: int, scale: float | None = None) -> bytes:
        """Render ``html`` (which must contain an element with id ``shot``) and clip to it.

        ``viewport_h`` matters: ``card.css`` caps a photo at ``46vh``, so the window's height is
        how tall the picture comes out. A card is shot at ``scale`` for sharpness; a finished
        frame is shot at 1, because resampling afterwards would smear the pixels that two frames
        have in common and cost the animation its small size.
        """
        assert self._browser is not None, "use Shooter as a context manager"
        page = self._browser.new_page(
            viewport={"width": 1400, "height": viewport_h},
            device_scale_factor=self.scale if scale is None else scale,
        )
        try:
            page.set_content(html)
            page.wait_for_load_state("load")
            return page.locator("#shot").screenshot()
        finally:
            page.close()


def _image(png: bytes) -> PilImage:
    from PIL import Image

    return Image.open(io.BytesIO(png)).convert("RGB")


# =============================================================================================
#  Stage one: the card studio. Real templates, real CSS, real media -- in, pixels out.
# =============================================================================================


@dataclass(frozen=True)
class CardSpec:
    """What to render. ``width`` is the card's window in CSS px; ``height`` fixes that window
    too, and ``None`` lets the card be exactly as tall as its own content."""

    theme: str
    card_type: str
    side: str  # "front" or "back"
    width: int
    viewport: int
    height: int | None = None
    night: bool = False


@dataclass(frozen=True)
class RenderedCard:
    """One card as pixels, with the labels the project itself owns. Stage two sees only this."""

    spec: CardSpec
    png: bytes
    size: tuple[int, int]  # as drawn, in CSS px
    label: str  # the template's own name, e.g. "Photo → Name"
    theme_label: str  # the theme's own one-line description
    has_photo: bool
    has_audio: bool

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]

    @property
    def data_uri(self) -> str:
        return f"data:image/png;base64,{base64.b64encode(self.png).decode()}"

    @property
    def key(self) -> str:
        return f"{self.spec.card_type.replace('_', '-')}-{self.spec.side}"


class CardStudio:
    """Renders real cards. Nothing in here knows that an animation exists."""

    def __init__(self, client: CatalogClient, region: str, shooter: Shooter) -> None:
        self._client = client
        self._shooter = shooter
        self._front, self._answer = self._fields(self._pick(region))

    # -- the catalog ---------------------------------------------------------------------
    def _pick(self, region: str) -> str:
        species = self._client.species()
        usable = [
            sid
            for sid, _ in self._client.region(self._client.find_region(region)).species
            if (e := species.entries.get(sid)) is not None and e.photo and e.audio
        ]
        by_name = {species.entries[sid].name: sid for sid in usable}
        for name in PREFERRED:
            if name in by_name:
                return by_name[name]
        if not usable:
            raise SystemExit(f"{region} has no species with both a photo and a recording")
        return usable[0]

    def _fields(self, sid: str) -> tuple[dict[str, str], dict[str, str]]:
        entry: SpeciesEntry = self._client.species()[sid]
        photo_ref: MediaRef = entry.photo[0]
        audio_ref: MediaRef = entry.audio[0]
        path = self._client.media(photo_ref.file)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        uri = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
        front = {
            "SpeciesId": "",
            "Name": entry.name,
            "SciName": entry.sci,
            "Photo": f'<img src="{uri}">',
            "Photo2": "",
            "Audio": REPLAY_BUTTON,
            "Audio2": "",
            "Credits": "",  # a credit on a question could give the bird away (ADR 0012)
            "IocName": entry.ioc_name,
        }
        return front, dict(front, Credits=credits_field(photo_ref, audio_ref))

    @property
    def species(self) -> str:
        return self._answer["Name"]

    # -- the templates -------------------------------------------------------------------
    @staticmethod
    def _fill(template: str, fields: dict[str, str]) -> str:
        """Anki's three mustache forms, the same rule as ``renderTemplate`` in preview.js."""

        def section(m: re.Match[str]) -> str:
            kind, name, inner = m.group(1), m.group(2), m.group(3)
            shown = bool(fields.get(name)) if kind == "#" else not fields.get(name)
            return CardStudio._fill(inner, fields) if shown else ""

        out = _SECTION.sub(section, template)
        for name, value in fields.items():
            out = out.replace("{{" + name + "}}", value)
        return out

    def fit_viewport(self, width: int, card_type: str, theme: str = "default") -> int:
        """The shortest window in which the photo still fills the card's width.

        ``card.css`` caps a picture at ``46vh`` and fits it inside the card, so too short a window
        leaves bars down either side. Measuring the drawn photo finds the height that just avoids
        them, whatever the picture's shape -- no number here to keep in step with the CSS.
        """
        spec = CardSpec(theme, card_type, "back", width, 2000)
        drawn, _ = self._html(spec)
        w, h = self._shooter.measure(drawn, 2000, "#shot .photo img")
        if not w or not h:
            return 600
        return math.ceil(h / 0.46) + 2

    def _html(self, spec: CardSpec) -> tuple[str, dict[str, str]]:
        template: dict[str, str] = models_for(spec.theme)[spec.card_type].templates[0]
        source = template["qfmt" if spec.side == "front" else "afmt"]
        fields = self._front if spec.side == "front" else self._answer
        body = self._fill(source, fields)
        cls = "card nightMode" if spec.night else "card"
        box = f"height:{spec.height}px;overflow:hidden;" if spec.height else ""
        html = (
            f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0}}'
            f"{ANKI_CHROME}{compose_css(spec.theme)}</style>"
            f'<div class="{cls}" id="shot" style="width:{spec.width}px;{box}">{body}</div>'
        )
        return html, template

    def render(self, spec: CardSpec) -> RenderedCard:
        html, template = self._html(spec)
        source = template["qfmt" if spec.side == "front" else "afmt"]
        png = self._shooter.shoot(html, spec.viewport)
        from PIL import Image

        with Image.open(io.BytesIO(png)) as probe:
            size = (round(probe.width / self._shooter.scale), round(probe.height / self._shooter.scale))
        return RenderedCard(
            spec=spec,
            png=png,
            size=size,
            label=str(template["name"]),
            theme_label=THEMES[spec.theme].description if spec.theme in THEMES else "",
            has_photo="{{Photo}}" in source,
            has_audio="{{Audio}}" in source,
        )


# =============================================================================================
#  Stage two: the compositor. Card pixels in, frames out. It never styles a card.
# =============================================================================================

INK = "#eef2f7"
DIM = "#8b98a8"
ACCENT = "#e6a452"
STAGE_TOP = "#1a2029"
STAGE_BOTTOM = "#0d1117"
SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'

STAGE_CSS = f"""
html, body {{ margin:0; padding:0; background:{STAGE_BOTTOM}; }}
#shot {{ position:relative; overflow:hidden; box-sizing:border-box;
  background:
    radial-gradient(120% 80% at 50% -12%, rgba(120,160,210,.10), transparent 62%),
    linear-gradient(168deg, {STAGE_TOP} 0%, {STAGE_BOTTOM} 100%);
  font-family:{SANS}; -webkit-font-smoothing:antialiased; }}
.pane {{ position:absolute; border-radius:16px; overflow:hidden; z-index:2;
  box-shadow:0 26px 50px -22px rgba(0,0,0,.9), 0 0 0 1px rgba(255,255,255,.11); }}
.pane img {{ display:block; }}
.stack {{ position:absolute; border-radius:16px; z-index:1; }}
.eyebrow {{ position:absolute; font:600 11.5px/1 {SANS}; letter-spacing:.18em;
  text-transform:uppercase; color:{INK}; z-index:3; white-space:nowrap; }}
.pips {{ position:absolute; display:flex; gap:7px; align-items:center; z-index:3; }}
.pips s {{ display:block; width:7px; height:7px; border-radius:50%;
  background:rgba(255,255,255,.18); }}
.pips s.on {{ background:{ACCENT}; box-shadow:0 0 0 4px rgba(230,164,82,.15); }}
.state {{ position:absolute; display:flex; align-items:center; justify-content:center; gap:13px;
  z-index:3; }}
.state i {{ display:block; height:1px; width:46px;
  background:linear-gradient(90deg, transparent, rgba(255,255,255,.26)); }}
.state i + i {{ background:linear-gradient(90deg, rgba(255,255,255,.26), transparent); }}
.state span {{ font:600 11px/1 {SANS}; letter-spacing:.22em; text-transform:uppercase;
  color:{ACCENT}; }}
.eq {{ position:absolute; display:flex; align-items:center; justify-content:center; gap:6px;
  z-index:1; }}
.eq b {{ display:block; width:5px; border-radius:3px;
  background:linear-gradient(180deg, rgba(230,164,82,.92), rgba(230,164,82,.20)); }}
.title {{ position:absolute; font:700 28px/1 {SANS}; letter-spacing:-.02em; color:{INK};
  z-index:3; }}
.desc {{ position:absolute; font:400 13.5px/1.4 {SANS}; color:{DIM}; z-index:3; }}
.count {{ position:absolute; font:600 12px/1 {SANS}; letter-spacing:.14em; color:{DIM};
  text-align:right; z-index:3; }}
.bar {{ position:absolute; height:2px; background:rgba(255,255,255,.09); z-index:3; }}
.bar i {{ display:block; height:100%; background:{ACCENT}; }}
.mode {{ position:absolute; font:600 10px/1 {SANS}; letter-spacing:.22em; text-transform:uppercase;
  color:{DIM}; z-index:3; }}
"""


class Stage:
    """A fixed-size backdrop that absolutely positioned pieces are dropped onto."""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self._parts: list[str] = []

    def add(self, html: str) -> Stage:
        self._parts.append(html)
        return self

    def card(self, card: RenderedCard, top: int, left: int) -> Stage:
        w, h = card.size
        return self.add(
            f'<div class="pane" style="top:{top}px;left:{left}px;width:{w}px;height:{h}px">'
            f'<img src="{card.data_uri}" width="{w}" height="{h}"></div>'
        )

    def text(self, cls: str, html: str, **style: object) -> Stage:
        css = ";".join(f"{k.replace('_', '-')}:{v}px" if isinstance(v, int) else f"{k.replace('_','-')}:{v}" for k, v in style.items())
        return self.add(f'<div class="{cls}" style="{css}">{html}</div>')

    def html(self) -> str:
        return (
            f'<!doctype html><meta charset="utf-8"><style>{STAGE_CSS}</style>'
            f'<div id="shot" style="width:{self.width}px;height:{self.height}px">'
            f'{"".join(self._parts)}</div>'
        )


def equaliser(width: int, height: int, top: int, left: int, phase: float, gap: int = 6) -> str:
    """Sound made visible *behind* the card: our decoration, never part of the card."""
    count = max(6, (width + gap) // (5 + gap))
    bars = []
    for i in range(count):
        x = (i - (count - 1) / 2) / max(1.0, count / 2)
        envelope = math.exp(-2.4 * x * x)  # loudest in the middle, fading out to the edges
        beat = 0.5 + 0.5 * math.sin(phase * math.tau * 2 + i * 0.8) * math.sin(i * 2.1 + 1.3)
        h = max(4.0, height * envelope * (0.18 + 0.82 * beat))
        bars.append(f'<b style="height:{h:.1f}px"></b>')
    return (
        f'<div class="eq" style="top:{top}px;left:{left}px;width:{width}px;height:{height}px">'
        f'{"".join(bars)}</div>'
    )


# -- the timeline -------------------------------------------------------------------------


def reveal(front: PilImage, answer: PilImage, steps: int = 6) -> list[PilImage]:
    """The answer wiping down over the question, starting at the first row that differs -- under
    the photo when the photo stays put, from the top when it does not. Each step changes only the
    band it just swept, which is also what keeps the GIF small."""
    from PIL import ImageChops

    diff = ImageChops.difference(front, answer).convert("L").point(lambda v: 255 if v > 14 else 0)
    box = diff.getbbox()
    y0, y1 = (box[1], box[3]) if box else (0, front.height)
    out = []
    for i in range(1, steps + 1):
        t = i / (steps + 1)
        split = y0 + round((y1 - y0) * (t * t * (3 - 2 * t)))
        img = front.copy()
        img.paste(answer.crop((0, 0, answer.width, split)), (0, 0))
        out.append(img)
    return out


def sweep(a: PilImage, b: PilImage, steps: int = 8, edge: str = "#e6a452") -> list[PilImage]:
    """``b`` painted over ``a`` left to right behind a bright edge: a curtain, not a cut. A cross
    dissolve would redraw every pixel of every frame; a sweep redraws one narrow column."""
    from PIL import ImageDraw

    out = []
    for i in range(1, steps + 1):
        x = round(a.width * i / (steps + 1))
        img = a.copy()
        img.paste(b.crop((0, 0, x, b.height)), (0, 0))
        ImageDraw.Draw(img).rectangle([x - 2, 0, x, img.height], fill=edge)
        out.append(img)
    return out


# An 8x8 Bayer matrix. GIF needs a 256-colour palette, and a photograph quantised flat shows
# contour bands; Floyd-Steinberg hides them but spreads its error sideways, so one swept column
# changes every pixel to its right and the encoder can no longer store just what moved -- it
# tripled the file. An ordered dither depends only on where a pixel is, so identical regions stay
# identical between frames and the diff survives.
BAYER = (0, 32, 8, 40, 2, 34, 10, 42, 48, 16, 56, 24, 50, 18, 58, 26,
         12, 44, 4, 36, 14, 46, 6, 38, 60, 28, 52, 20, 62, 30, 54, 22,
         3, 35, 11, 43, 1, 33, 9, 41, 51, 19, 59, 27, 49, 17, 57, 25,
         15, 47, 7, 39, 13, 45, 5, 37, 63, 31, 55, 23, 61, 29, 53, 21)
_MASKS: dict[tuple[int, int, int], object] = {}


def _bayer(size: tuple[int, int], amplitude: int):
    from PIL import Image

    key = (*size, amplitude)
    if key not in _MASKS:
        tile = Image.new("L", (8, 8))
        tile.putdata([round((v / 63 - 0.5) * 2 * amplitude) + 128 for v in BAYER])
        w, h = size
        row = Image.new("L", (w, 8))
        for x in range(0, w, 8):
            row.paste(tile, (x, 0))
        full = Image.new("L", size)
        for y in range(0, h, 8):
            full.paste(row, (0, y))
        _MASKS[key] = Image.merge("RGB", (full, full, full))
    return _MASKS[key]


def write_gif(timeline: list[tuple[PilImage, int]], out: Path, width: int, colors: int = 180,
              amplitude: int = 4) -> None:
    """One animated GIF. Every frame is ordered-dithered and quantised to one shared palette, so
    the encoder can store just the pixels that changed -- which is what keeps a loop small."""
    from PIL import Image, ImageChops

    frames = []
    for img, ms in timeline:
        if img.width != width:
            img = img.resize(
                (width, round(img.height * width / img.width)), Image.Resampling.LANCZOS
            )
        frames.append((ImageChops.add(img, _bayer(img.size, amplitude), 1, -128), ms))

    w, h = frames[0][0].size
    picks = frames[:: max(1, len(frames) // 8)][:8]
    sample = Image.new("RGB", (w, h * len(picks)))
    for i, (img, _) in enumerate(picks):
        sample.paste(img, (0, i * h))
    palette = sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    pages = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img, _ in frames]
    pages[0].save(
        out,
        save_all=True,
        append_images=pages[1:],
        duration=[ms for _, ms in frames],
        loop=0,
        optimize=True,
        disposal=1,
    )
    seconds = sum(ms for _, ms in frames) / 1000
    kb = out.stat().st_size // 1024
    print(f"wrote {out.relative_to(ROOT)} ({kb} KB, {len(pages)} frames, {seconds:.1f}s)")


# =============================================================================================
#  The two loops
# =============================================================================================

# The cards loop: one card, as tall as its own content, on a stage sized for the longest.
CARD_W = 352
CARD_VIEWPORT = 600
CARD_PAD, CARD_TOP, CARD_FOOT = 36, 56, 58

# The themes loop: a short window, so the photo is a band and the typography is the subject.
THEME_W = 330
THEME_PAD, THEME_GAP, THEME_HEAD, THEME_LABEL, THEME_FOOT = 32, 20, 104, 20, 30


def _cards_stage(card: RenderedCard, index: int, total: int, state: str, phase: float | None,
                 body: int) -> Stage:
    width = CARD_W + 2 * CARD_PAD
    stage = Stage(width, CARD_TOP + body + CARD_FOOT)
    stage.text("eyebrow", card.label.replace("→", "&rarr;"), top=22, left=CARD_PAD)
    pips = "".join(f'<s class="{"on" if i == index else ""}"></s>' for i in range(total))
    stage.add(f'<div class="pips" style="top:19px;right:{CARD_PAD}px">{pips}</div>')
    if phase is not None:
        # The equaliser fills the air beneath a question that plays a recording: our drawing,
        # outside the card, saying a sound is what is being asked.
        top = CARD_TOP + card.height + 36
        room = CARD_TOP + body - top - 6
        if room > 40:
            stage.add(equaliser(width - 36, room, top, 18, phase))
    # Two paper edges peeking out below: a card is one of a deck.
    for inset, drop in ((11, 9), (24, 17)):
        stage.add(
            f'<div class="stack" style="top:{CARD_TOP + card.height - 24}px;'
            f"left:{CARD_PAD + inset}px;width:{CARD_W - 2 * inset}px;height:{24 + drop}px;"
            f'background:rgba(255,255,255,{0.26 - inset * 0.006:.2f})"></div>'
        )
    stage.card(card, CARD_TOP, CARD_PAD)
    stage.add(
        f'<div class="state" style="top:{CARD_TOP + body + 24}px;left:0;width:{width}px">'
        f"<i></i><span>{state}</span><i></i></div>"
    )
    return stage


def _themes_stage(day: RenderedCard, night: RenderedCard, index: int, total: int) -> Stage:
    width = 2 * THEME_W + THEME_GAP + 2 * THEME_PAD
    top = THEME_HEAD + THEME_LABEL
    stage = Stage(width, top + day.height + THEME_FOOT)
    right = THEME_PAD + THEME_W + THEME_GAP
    inner = width - 2 * THEME_PAD
    stage.text("title", day.spec.theme, top=26, left=THEME_PAD)
    stage.text("desc", day.theme_label, top=64, left=THEME_PAD, width=inner - 96)
    stage.text("count", f"{index + 1:02d} / {total:02d}", top=30, right=THEME_PAD, width=96)
    stage.add(
        f'<div class="bar" style="top:{THEME_HEAD - 12}px;left:{THEME_PAD}px;width:{inner}px">'
        f'<i style="width:{100 * (index + 1) / total:.1f}%"></i></div>'
    )
    stage.text("mode", "Day", top=THEME_HEAD + 6, left=THEME_PAD)
    stage.text("mode", "Night", top=THEME_HEAD + 6, left=right)
    stage.card(day, top, THEME_PAD)
    stage.card(night, top, right)
    return stage


def _save(img: PilImage, path: Path) -> None:
    """A still for the README's galleries."""
    img.save(path, optimize=True)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


def build_cards(studio: CardStudio, shooter: Shooter, out: Path) -> None:
    """Every card type: the question held, then the answer wiping in beneath the photo."""
    types = list(CARD_TYPES)
    cards = {
        (card_type, side): studio.render(CardSpec("default", card_type, side, CARD_W, CARD_VIEWPORT))
        for card_type in types
        for side in ("front", "back")
    }
    body = max(c.height for c in cards.values())  # one stage height for every card type
    width = CARD_W + 2 * CARD_PAD

    timeline: list[tuple[PilImage, int]] = []
    previous: PilImage | None = None
    for index, card_type in enumerate(types):
        question, answer = cards[card_type, "front"], cards[card_type, "back"]
        sings = question.has_audio
        quiet = sings and not question.has_photo  # a play button alone: the equaliser carries it
        phases = [i / 8 for i in range(8)] if sings else [None]

        asked = [
            _image(shooter.shoot(
                _cards_stage(question, index, len(types), "Question", p, body).html(),
                CARD_VIEWPORT, scale=1,
            ))
            for p in phases
        ]
        told = _image(shooter.shoot(
            _cards_stage(answer, index, len(types), "Answer", None, body).html(),
            CARD_VIEWPORT, scale=1,
        ))

        _save(asked[0], out / f"card-{question.key}.png")
        _save(told, out / f"card-{answer.key}.png")

        if previous is not None:
            timeline += [(f, 55) for f in sweep(previous, asked[0])]
        timeline += [(f, 135) for f in asked * (2 if quiet else 1)]
        if not quiet:
            timeline[-1] = (timeline[-1][0], 1700 - 135 * (len(asked) - 1))
        timeline += [(f, 50) for f in reveal(asked[-1], told)]
        timeline.append((told, 2200))
        previous = told

    write_gif(timeline, out / "cards.gif", width)


def build_themes(studio: CardStudio, shooter: Shooter, out: Path) -> None:
    """Every theme in turn, day beside night: one card restyling itself as many times as there
    are themes. It is a sequence, not a grid, so nine themes or fourteen work unchanged."""
    names = list(THEMES)
    card_type = CARD_TYPES[0]
    width = 2 * THEME_W + THEME_GAP + 2 * THEME_PAD
    viewport = studio.fit_viewport(THEME_W, card_type)

    def spec(theme: str, night: bool, height: int | None) -> CardSpec:
        return CardSpec(theme, card_type, "back", THEME_W, viewport, height, night)

    # Themes differ in type size, so measure them all first and give every one the same window:
    # the panes then line up frame to frame and only the styling moves.
    window = max(studio.render(spec(name, False, None)).height for name in names)

    stills: list[PilImage] = []
    for index, theme in enumerate(names):
        day = studio.render(spec(theme, False, window))
        night = studio.render(spec(theme, True, window))
        img = _image(
            shooter.shoot(_themes_stage(day, night, index, len(names)).html(), viewport, scale=1)
        )
        _save(img, out / f"theme-{theme}.png")
        stills.append(img)

    timeline: list[tuple[PilImage, int]] = []
    for i, img in enumerate(stills):
        timeline += [(f, 70) for f in sweep(stills[i - 1], img, steps=4)]
        timeline.append((img, 1150))
    timeline = timeline[4:] + timeline[:4]  # land on a held frame, not mid-sweep
    write_gif(timeline, out / "themes.gif", width)


# =============================================================================================
#  The README's generated tables
# =============================================================================================

NUMBER = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight",
          9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve"}


def _block(name: str, body: str, text: str) -> str:
    start, end = f"<!-- gen:{name} -->", f"<!-- /gen:{name} -->"
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    if not pattern.search(text):
        raise SystemExit(f"README.md has no {start} ... {end} block")
    return pattern.sub(lambda _: f"{start}{body}{end}", text)


def sync_readme(readme: Path) -> None:
    """Rewrite the generated tables from ``THEMES`` and ``CARD_TYPES``, so a new theme or card
    type needs no hand edit."""
    text = readme.read_text(encoding="utf-8")
    models = models_for()

    rows = ["|               | Front                           | Answer                          |",
            "| ------------- | ------------------------------- | ------------------------------- |"]
    for card_type in CARD_TYPES:
        label = str(models[card_type].templates[0]["name"]).split("→")[0].strip()
        key = card_type.replace("_", "-")
        rows.append(
            f"| {label} "
            f"| ![{label} card, front]({RAW}/card-{key}-front.png) "
            f"| ![{label} card, answer]({RAW}/card-{key}-back.png) |"
        )
    text = _block("card-shots", "\n" + "\n".join(rows) + "\n", text)

    gallery = ["| Theme | Day and night |", "| --- | --- |"]
    for name, theme in THEMES.items():
        gallery.append(
            f"| **`{name}`** — {theme.description.rstrip('.')} "
            f"| ![The {name} theme]({RAW}/theme-{name}.png) |"
        )
    text = _block("theme-gallery", "\n" + "\n".join(gallery) + "\n", text)
    count = NUMBER.get(len(THEMES), str(len(THEMES)))
    text = _block("theme-count", count, text)
    text = _block("theme-count-lower", count.lower(), text)
    readme.write_text(text, encoding="utf-8")
    print(f"wrote {readme.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--region", default="us-ma", help="catalog region to take media from")
    parser.add_argument("--catalog-url", default=None, help="a URL or a local catalog directory")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="where the images go")
    parser.add_argument(
        "--only", choices=("cards", "themes"), help="only one loop (default: both)"
    )
    parser.add_argument("--scale", type=float, default=2, help="device scale factor (default: 2)")
    parser.add_argument(
        "--no-readme", action="store_true", help="leave the README's generated tables alone"
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    client = CatalogClient(base_url=args.catalog_url) if args.catalog_url else CatalogClient()

    with Shooter(args.scale) as shooter:
        studio = CardStudio(client, args.region, shooter)
        print(f"using {studio.species}")
        if args.only != "themes":
            build_cards(studio, shooter, args.out)
        if args.only != "cards":
            build_themes(studio, shooter, args.out)
    if not args.no_readme:
        sync_readme(ROOT / "README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
