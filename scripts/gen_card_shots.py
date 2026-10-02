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
    hero.gif                 the trailer: title, a card asked and answered, the recording as its
                             own waveform, every theme in turn, then where to get it
    card-<type>-<side>.png   a still of every card type, question and answer
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
from avianki.deck.themes import COLOUR_KEYS, THEMES, compose_css

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
    palette: tuple[str, ...]  # the theme's own day colours, for swatches drawn beside the card
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


def _palette(theme: str) -> tuple[str, ...]:
    """A theme's own day colours, in the order it declares them."""
    if theme not in THEMES:
        return ()
    light = THEMES[theme].tokens.light
    return tuple(getattr(light, key) for key in COLOUR_KEYS)


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
        self._audio = self._client.media(audio_ref.file)
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

    def envelope(self, buckets: int) -> tuple[tuple[float, ...], bool]:
        """The amplitude envelope of the very recording on the card, in ``buckets`` time slices.

        Peak per slice, not RMS: a bird's call is short and sharp, and RMS flattens it into
        nothing at this resolution. The values are raised to a power so a quiet call still shows
        beside a loud one, the way a level meter is not linear either, and scaled so the loudest
        slice is 1. Returns ``(values, True)``.

        ``soundfile`` is a dev dependency and its libsndfile reads MP3 directly -- no ffmpeg. If
        it is missing, or the clip will not decode, this FALLS BACK to a synthetic shape and
        returns ``(values, False)``, and the caller must not then claim the bars are real.
        """
        try:
            import numpy as np
            import soundfile as sf

            data, _ = sf.read(str(self._audio))
            mono = data.mean(axis=1) if data.ndim > 1 else data
            sliced = np.array_split(np.abs(np.asarray(mono, dtype="float64")), buckets)
            peaks = np.array([float(s.max()) if s.size else 0.0 for s in sliced])
            if not peaks.max():
                raise ValueError("silent clip")
            shaped = (peaks / peaks.max()) ** 0.6
            return tuple(float(v) for v in shaped), True
        except Exception as exc:  # noqa: BLE001 - any decode failure falls back, never crashes
            print(f"  (no waveform: {type(exc).__name__}: {exc}; drawing a synthetic one)")
            return (
                tuple(
                    max(0.04, math.exp(-2.4 * ((i - (buckets - 1) / 2) / (buckets / 2)) ** 2))
                    * (0.45 + 0.55 * abs(math.sin(i * 2.1 + 1.3)))
                    for i in range(buckets)
                ),
                False,
            )

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
            palette=_palette(spec.theme),
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
.lede {{ position:absolute; top:0; bottom:0; display:flex; flex-direction:column;
  justify-content:center; text-align:center; z-index:3; }}
.lede b {{ display:block; font:800 50px/1 {SANS}; letter-spacing:-.035em; color:{INK}; }}
.lede u {{ display:block; width:54px; height:3px; border-radius:2px; background:{ACCENT};
  margin:0 auto 22px; text-decoration:none; }}
.lede i {{ display:block; font:400 15.5px/1.5 {SANS}; font-style:normal; color:{DIM};
  margin-top:14px; }}
.lede code {{ display:inline-block; font:600 13px/1 ui-monospace, Menlo, Consolas, monospace;
  color:{INK}; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.12);
  border-radius:7px; padding:9px 13px; margin-top:20px; }}
.lede em {{ display:block; font-style:normal; font:600 14px/1 {SANS}; color:{ACCENT};
  letter-spacing:.01em; margin-top:16px; }}
.cap {{ position:absolute; text-align:center; z-index:3; }}
.cap b {{ display:block; font:600 14.5px/1.35 {SANS}; color:{INK}; }}
.cap i {{ display:block; font:400 12.5px/1.45 {SANS}; font-style:normal; color:{DIM};
  margin-top:5px; }}
.list {{ position:absolute; z-index:3; }}
.list b {{ display:block; font:600 11px/1 {SANS}; color:rgba(255,255,255,.26);
  padding:5px 0 5px 10px; border-left:2px solid transparent; letter-spacing:.01em; }}
.list b.on {{ color:{INK}; border-left-color:{ACCENT}; }}
.sw {{ position:absolute; z-index:3; border-radius:6px; overflow:hidden;
  box-shadow:0 0 0 1px rgba(255,255,255,.12); }}
.sw s {{ display:block; height:21px; }}
.wave {{ position:absolute; display:flex; align-items:center; justify-content:space-between;
  z-index:1; }}
.wave b {{ display:block; border-radius:2px; }}
.base {{ position:absolute; height:1px; background:rgba(146,164,186,.22); z-index:2; }}
.base i {{ display:block; height:100%; background:{ACCENT}; }}
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
        u = i / (steps + 1)
        x = round(a.width * u * u * (3 - 2 * u))
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


def write_gif(timeline: list[tuple[PilImage, int]], out: Path, width: int, colors: int = 230,
              amplitude: int = 6) -> None:
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
CARD_WAVE_BARS = 52

# The themes loop: a short window, so the photo is a band and the typography is the subject.
THEME_W = 330
THEME_PAD, THEME_GAP, THEME_HEAD, THEME_LABEL, THEME_FOOT = 32, 20, 104, 20, 30


def _cards_stage(card: RenderedCard, index: int, total: int, state: str, wave: str,
                 body: int) -> Stage:
    width = CARD_W + 2 * CARD_PAD
    stage = Stage(width, CARD_TOP + body + CARD_FOOT)
    stage.text("eyebrow", card.label.replace("\u2192", "&rarr;"), top=22, left=CARD_PAD)
    pips = "".join(f'<s class="{"on" if i == index else ""}"></s>' for i in range(total))
    stage.add(f'<div class="pips" style="top:19px;right:{CARD_PAD}px">{pips}</div>')
    if wave:
        stage.add(wave)
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
    """A still of every card type, question and answer, for the README's gallery."""
    types = list(CARD_TYPES)
    cards = {
        (card_type, side): studio.render(CardSpec("default", card_type, side, CARD_W, CARD_VIEWPORT))
        for card_type in types
        for side in ("front", "back")
    }
    body = max(c.height for c in cards.values())  # one stage height for every card type
    values, _ = studio.envelope(CARD_WAVE_BARS)
    for index, card_type in enumerate(types):
        for side, state in (("front", "Question"), ("back", "Answer")):
            card = cards[card_type, side]
            # A question that plays a recording gets its waveform; an answer never does.
            top = CARD_TOP + card.height + 36
            room = CARD_TOP + body - top - 6
            wave = ""
            if side == "front" and card.has_audio and room > 40:
                wave = waveform(values, 18, CARD_W + 2 * CARD_PAD - 36, top, room, 1.0)
            stage = _cards_stage(card, index, len(types), state, wave, body)
            _save(
                _image(shooter.shoot(stage.html(), CARD_VIEWPORT, scale=1)),
                out / f"card-{card.key}.png",
            )


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
        timeline.append((img, 950))
    timeline = timeline[4:] + timeline[:4]  # land on a held frame, not mid-sweep
    write_gif(timeline, out / "themes.gif", width)


# =============================================================================================
#  The hero: a short trailer. Title, a card asked and answered, the real recording, the themes,
#  then where to get it. Every act is the same stage, so one sweep carries you between them.
# =============================================================================================

HERO_W = 600
HERO_CARD_W = 352
HERO_TOP, HERO_FOOT = 58, 78
HERO_VIEWPORT = 600
WAVE_BARS = 68


def _hero(body: int) -> Stage:
    return Stage(HERO_W, HERO_TOP + body + HERO_FOOT)


def _caption(stage: Stage, body: int, title: str, note: str) -> None:
    stage.add(
        f'<div class="cap" style="top:{HERO_TOP + body + 22}px;left:40px;width:{HERO_W - 80}px">'
        f"<b>{title}</b><i>{note}</i></div>"
    )


def _title_stage(body: int, title: str, lines: str) -> Stage:
    stage = _hero(body)
    stage.add(
        f'<div class="lede" style="left:50px;width:{HERO_W - 100}px">'
        f"<u></u><b>{title}</b>{lines}</div>"
    )
    return stage


def waveform(values: tuple[float, ...], left: int, width: int, top: int, height: int,
             cursor: float) -> str:
    """The recording's own envelope, drawn on the stage under the card, mirrored about a baseline.

    ``cursor`` is how far through the clip the lit part has reached, so a run of frames reads as
    the clip playing; 1 lights the whole thing for a still. The bars are the stage's decoration
    and never touch the card -- but they are that card's recording, not an invented shape.
    """
    bars = []
    last = max(1, len(values) - 1)
    for i, v in enumerate(values):
        lit = i / last <= cursor
        head = lit and cursor < 1 and (i + 1) / last > cursor
        colour = "#f8cd91" if head else (ACCENT if lit else "rgba(146,164,186,.28)")
        glow = ";box-shadow:0 0 12px rgba(248,205,145,.6)" if head else ""
        bars.append(
            f'<b style="height:{max(3.0, height * v):.1f}px;width:4px;background:{colour}{glow}">'
            "</b>"
        )
    return (
        f'<div class="wave" style="top:{top}px;left:{left}px;width:{width}px;height:{height}px">'
        + "".join(bars)
        + "</div>"
        f'<div class="base" style="top:{top + height // 2}px;left:{left}px;width:{width}px">'
        f'<i style="width:{cursor * 100:.1f}%"></i></div>'
    )


def _hero_card_stage(card: RenderedCard, body: int, title: str, note: str, wave: str = "") -> Stage:
    stage = _hero(body)
    left = (HERO_W - HERO_CARD_W) // 2
    stage.text("eyebrow", card.label.replace("\u2192", "&rarr;"), top=24, left=left)
    if wave:
        stage.add(wave)
    for inset, drop in ((11, 9), (24, 17)):
        stage.add(
            f'<div class="stack" style="top:{HERO_TOP + card.height - 24}px;'
            f"left:{left + inset}px;width:{HERO_CARD_W - 2 * inset}px;height:{24 + drop}px;"
            f'background:rgba(255,255,255,{0.26 - inset * 0.006:.2f})"></div>'
        )
    stage.card(card, HERO_TOP, left)
    _caption(stage, body, title, note)
    return stage


def _hero_theme_stage(card: RenderedCard, names: list[str], index: int, body: int) -> Stage:
    """The climax: one card restyling itself, with every theme's name listed beside it and the
    theme's own colours as swatches. Both are laid out from ``THEMES``, so the list grows."""
    stage = _hero(body)
    left = (HERO_W - HERO_CARD_W) // 2
    rows = "".join(f'<b class="{"on" if i == index else ""}">{n}</b>' for i, n in enumerate(names))
    span = 21 * len(card.palette)
    stage.add(f'<div class="list" style="top:{HERO_TOP + 2}px;left:12px;width:{left - 26}px">{rows}</div>')
    stage.text(
        "mode", "Palette", top=HERO_TOP + (body - span) // 2 - 20, left=left + HERO_CARD_W + 22
    )
    stage.add(
        f'<div class="sw" style="top:{HERO_TOP + (body - span) // 2}px;'
        f'left:{left + HERO_CARD_W + 22}px;width:44px">'
        + "".join(f'<s style="background:{c}"></s>' for c in card.palette)
        + "</div>"
    )
    stage.text("eyebrow", f"Theme {index + 1:02d} / {len(names):02d}", top=24, left=left)
    stage.card(card, HERO_TOP, left)
    _caption(stage, body, f"--theme {card.spec.theme}", card.theme_label)
    return stage


def build_hero(studio: CardStudio, shooter: Shooter, out: Path) -> None:
    """The README's hero: five acts on one stage, joined by sweeps."""
    types = list(CARD_TYPES)
    themes = list(THEMES)

    def shot(stage: Stage) -> PilImage:
        return _image(shooter.shoot(stage.html(), HERO_VIEWPORT, scale=1))

    cards = {
        (ct, side): studio.render(CardSpec("default", ct, side, HERO_CARD_W, HERO_VIEWPORT))
        for ct in types
        for side in ("front", "back")
    }
    body = max(c.height for c in cards.values())

    opening = shot(
        _title_stage(
            body,
            "AviAnki",
            "<i>Anki flashcard decks for the birds of your state or province,<br>"
            "by sight and by sound.</i>",
        )
    )
    timeline: list[tuple[PilImage, int]] = [(opening, 1200)]

    def act(stage: Stage, hold: int, steps: int = 7, ms: int = 48) -> PilImage:
        img = shot(stage)
        timeline.extend((f, ms) for f in sweep(timeline[-1][0], img, steps=steps))
        timeline.append((img, hold))
        return img

    # Act two: a photo asked, then answered. The photo stays put and the answer wipes in below it.
    photo = types[0]
    asked = act(
        _hero_card_stage(
            cards[photo, "front"],
            body,
            "A photo on the front.",
            "The commonest birds of your region first.",
        ),
        1200,
    )
    told = shot(
        _hero_card_stage(
            cards[photo, "back"],
            body,
            "The name on the back.",
            "With the scientific name, the recording, and a credit for every asset.",
        )
    )
    timeline.extend((f, 48) for f in reveal(asked, told, steps=7))
    timeline.append((told, 1500))

    # Act three: the recording, drawn as its own waveform with a cursor running through it.
    values, real = studio.envelope(WAVE_BARS)
    sung = [ct for ct in types if cards[ct, "front"].has_audio and not cards[ct, "front"].has_photo]
    if sung:
        card = cards[sung[0], "front"]
        top = HERO_TOP + card.height + 46
        height = body - card.height - 66
        note = (
            "The bars are that clip's own waveform, read off the mp3."
            if real
            else "Audio cards play a recording of the bird."
        )
        # Every bar is the whole clip; the playhead simply runs faster than real time, so the
        # beat lasts a few seconds instead of the recording's ten.
        steps, step_ms = 22, 145
        stages = [
            _hero_card_stage(
                card, body, "A recording on the front.", note,
                waveform(values, 28, HERO_W - 56, top, height, i / (steps - 1)),
            )
            for i in range(steps)
        ]
        act(stages[0], step_ms)
        for stage in stages[1:]:
            timeline.append((shot(stage), step_ms))
        answer = shot(
            _hero_card_stage(
                cards[sung[0], "back"], body, "Then the bird.", "Every card type shares one answer."
            )
        )
        timeline.extend((f, 48) for f in reveal(timeline[-1][0], answer, steps=7))
        timeline.append((answer, 1300))

    # Act four, the climax: one card walking through every theme, the photo never moving.
    for index, theme in enumerate(themes):
        card = studio.render(CardSpec(theme, photo, "back", HERO_CARD_W, HERO_VIEWPORT, body))
        act(_hero_theme_stage(card, themes, index, body), 460, steps=4, ms=52)

    # Act five: where to get it, and round to the title again.
    act(
        _title_stage(
            body,
            "AviAnki",
            "<i>Free. No account, no API key.<br>Openly licensed media, rebuilt every month.</i>"
            "<code>pip install avianki</code>"
            "<em>ian-costa18.github.io/AviAnki</em>",
        ),
        1600,
    )
    timeline.extend((f, 48) for f in sweep(timeline[-1][0], opening, steps=7))

    write_gif(timeline, out / "hero.gif", HERO_W)


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
        "--only",
        choices=("hero", "cards", "themes"),
        help="only the hero, the card stills or the themes (default: all three)",
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
        if args.only in (None, "hero"):
            build_hero(studio, shooter, args.out)
        if args.only in (None, "cards"):
            build_cards(studio, shooter, args.out)
        if args.only in (None, "themes"):
            build_themes(studio, shooter, args.out)
    if not args.no_readme:
        sync_readme(ROOT / "README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
