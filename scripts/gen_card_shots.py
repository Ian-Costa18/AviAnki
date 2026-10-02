#!/usr/bin/env python3
"""Screenshot the real cards for the README: the three card types, and every theme.

Nothing here describes a card: the templates come from ``notetypes.models_for`` and the CSS
from ``themes.compose_css``, exactly as a built deck carries them, filled with real media and
credits from the published catalog. A README image therefore cannot drift from what Anki
shows. The one thing drawn rather than taken from the deck is Anki's own chrome -- the body
defaults and the replay button it substitutes for ``[sound:...]`` -- which lives in Anki, not
in our CSS; ``web/js/preview.js`` keeps the same lookalike for the website's preview.

Usage:
    uv run --extra catalog python scripts/gen_card_shots.py
    uv run --extra catalog python scripts/gen_card_shots.py --only cards

Writes into ``docs/examples/``:
    card-<type>-<side>.png, cards.gif    the three card types, front and answer (default theme)
    theme-<name>.png, themes.gif         every built-in theme, day beside night

Needs the ``catalog`` extra and Playwright's Chromium (``uv run playwright install chromium``).
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from avianki.catalog.client import CatalogClient
from avianki.catalog.format import MediaRef, SpeciesEntry
from avianki.deck.credits import credits_field
from avianki.deck.notetypes import CARD_TYPES, models_for
from avianki.deck.themes import THEMES, compose_css

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "examples"

CARD_TYPE_LABELS = {
    "photo": "Photo &rarr; Name",
    "audio": "Audio &rarr; Name",
    "photo_audio": "Photo + Audio &rarr; Name",
}

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

# The page around the cards: a caption bar and, for the theme shots, two columns.
SHELL_CSS = """
html, body { margin: 0; padding: 0; background: #e9e9e4; }
.shot { width: var(--shot-width); }
.caption {
  font: 600 13px/1.35 -apple-system, "Segoe UI", Roboto, sans-serif;
  letter-spacing: .04em; color: #f4f4ef; background: #26303a; padding: 11px 14px;
  display: flex; gap: 14px; justify-content: space-between; align-items: baseline;
}
.caption .what { text-transform: uppercase; letter-spacing: .08em; white-space: nowrap; }
.caption .note { font-weight: 400; opacity: .78; text-align: right; }
.cols { display: flex; }
.cols > * { flex: 1 1 0; min-width: 0; }
"""

# The viewport the theme shots are taken in: `card.css` caps a photo at 46vh, so a shorter
# page gives the pair a smaller picture and more room for what actually differs.
THEME_SHOT_HEIGHT = 620

_SECTION = re.compile(r"\{\{([#^])([A-Za-z0-9_]+)\}\}([\s\S]*?)\{\{/\2\}\}")


@dataclass(frozen=True)
class Card:
    """One rendered card: the note type's CSS and the filled template body."""

    css: str
    body: str


@dataclass(frozen=True)
class Shot:
    """One screenshot: its file name, caption, card width and the cards to show."""

    name: str
    what: str
    note: str
    width: int
    cards: tuple[tuple[Card, bool], ...]  # (card, night)


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _render(template: str, fields: dict[str, str]) -> str:
    """Anki's three mustache forms, the same rule as ``renderTemplate`` in web/js/preview.js."""

    def section(m: re.Match[str]) -> str:
        kind, name, inner = m.group(1), m.group(2), m.group(3)
        shown = bool(fields.get(name)) if kind == "#" else not fields.get(name)
        return _render(inner, fields) if shown else ""

    out = _SECTION.sub(section, template)
    for name, value in fields.items():
        out = out.replace("{{" + name + "}}", value)
    return out


def _fields(entry: SpeciesEntry, photo: Path | None, audio: bool) -> dict[str, str]:
    """The note's fields as ``deck/build.py`` writes them, with media inlined for the browser."""
    return {
        "SpeciesId": "",
        "Name": entry.name,
        "SciName": entry.sci,
        "Photo": f'<img src="{_data_uri(photo)}">' if photo else "",
        "Photo2": "",
        "Audio": REPLAY_BUTTON if audio else "",
        "Audio2": "",
        "Credits": "",  # set by the caller, which knows which assets were used
        "IocName": entry.ioc_name,
    }


def _card(card_type: str, side: str, fields: dict[str, str], theme: str) -> Card:
    model = models_for(theme)[card_type]
    template = model.templates[0]["qfmt" if side == "front" else "afmt"]
    return Card(compose_css(theme), _render(template, fields))


def _page(shot: Shot) -> str:
    css = "\n".join(c.css for c, _ in shot.cards[:1])
    columns = "".join(
        f'<div class="card{" nightMode" if night else ""}">{card.body}</div>'
        for card, night in shot.cards
    )
    return f"""<!doctype html><meta charset="utf-8">
<style>{ANKI_CHROME}{css}{SHELL_CSS}</style>
<div class="shot" id="shot" style="--shot-width: {shot.width}px">
  <div class="caption"><span class="what">{shot.what}</span>
    <span class="note">{shot.note}</span></div>
  <div class="cols">{columns}</div>
</div>"""


def _pick(client: CatalogClient, region: str, count: int) -> list[str]:
    """Species ids from the region that have both a photo and a recording."""
    species = client.species()
    usable = [
        sid
        for sid, _ in client.region(client.find_region(region)).species
        if (e := species.entries.get(sid)) is not None and e.photo and e.audio
    ]
    by_name = {species.entries[sid].name: sid for sid in usable}
    chosen = [by_name[n] for n in PREFERRED if n in by_name]
    chosen += [sid for sid in usable if sid not in chosen]
    if len(chosen) < count:
        raise SystemExit(f"{region} has only {len(chosen)} species with a photo and a recording")
    return chosen[:count]


def _filled(client: CatalogClient, sid: str) -> tuple[dict[str, str], dict[str, str]]:
    """``(front fields, answer fields)`` for one species, with its real media and credits."""
    entry = client.species()[sid]
    photo_ref: MediaRef = entry.photo[0]
    audio_ref: MediaRef = entry.audio[0]
    photo = client.media(photo_ref.file)
    front = _fields(entry, photo, audio=True)
    answer = dict(front, Credits=credits_field(photo_ref, audio_ref))
    return front, answer


def _card_shots(client: CatalogClient, region: str) -> list[Shot]:
    """The three card types, front and answer, in the default theme: one species each."""
    shots: list[Shot] = []
    for sid, card_type in zip(_pick(client, region, len(CARD_TYPES)), CARD_TYPES):
        front, answer = _filled(client, sid)
        if card_type == "photo":
            front = dict(front, Audio="")
        elif card_type == "audio":
            front = dict(front, Photo="")
        name = card_type.replace("_", "-")
        shots.append(
            Shot(
                f"card-{name}-front",
                CARD_TYPE_LABELS[card_type],
                "the question",
                440,
                ((_card(card_type, "front", front, "default"), False),),
            )
        )
        shots.append(
            Shot(
                f"card-{name}-back",
                CARD_TYPE_LABELS[card_type],
                "the answer",
                440,
                ((_card(card_type, "back", answer, "default"), False),),
            )
        )
    return shots


def _theme_shots(client: CatalogClient, region: str) -> list[Shot]:
    """Every built-in theme: the same answer card, day beside night."""
    sid = _pick(client, region, 1)[0]
    _, answer = _filled(client, sid)
    shots = []
    for name, theme in THEMES.items():
        card = _card("photo", "back", answer, name)
        shots.append(Shot(f"theme-{name}", name, theme.description, 820, ((card, False), (card, True))))
    return shots


def _shoot(shots: list[Shot], out_dir: Path, scale: float, height: int = 900) -> list[Path]:
    from playwright.sync_api import sync_playwright

    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": height}, device_scale_factor=scale)
        for shot in shots:
            page.set_content(_page(shot))
            page.wait_for_load_state("load")
            target = out_dir / f"{shot.name}.png"
            page.locator("#shot").screenshot(path=str(target))
            paths.append(target)
            print(f"wrote {target.relative_to(ROOT)}")
        browser.close()
    return paths


def _slideshow(frames: list[Path], out: Path, ms: int, width: int) -> None:
    """One animated GIF cycling the frames, each padded to a common canvas (GitHub plays it)."""
    from PIL import Image

    images = []
    for path in frames:
        img = Image.open(path).convert("RGB")
        if img.width != width:
            img = img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
        images.append(img)
    canvas = (max(i.width for i in images), max(i.height for i in images))
    pages = []
    for img in images:
        page = Image.new("RGB", canvas, (233, 233, 228))
        page.paste(img, ((canvas[0] - img.width) // 2, (canvas[1] - img.height) // 2))
        pages.append(page.convert("P", palette=Image.Palette.ADAPTIVE, colors=200))
    pages[0].save(out, save_all=True, append_images=pages[1:], duration=ms, loop=0, optimize=True)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--region", default="us-ma", help="catalog region to take media from")
    parser.add_argument("--catalog-url", default=None, help="a URL or a local catalog directory")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="where the images go")
    parser.add_argument(
        "--only",
        choices=("cards", "themes"),
        help="only the card types, or only the themes (default: both)",
    )
    parser.add_argument("--scale", type=float, default=2, help="device scale factor (default: 2)")
    parser.add_argument("--frame-ms", type=int, default=2200, help="slideshow frame duration")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    client = CatalogClient(base_url=args.catalog_url) if args.catalog_url else CatalogClient()

    if args.only != "themes":
        frames = _shoot(_card_shots(client, args.region), args.out, args.scale)
        _slideshow(frames, args.out / "cards.gif", args.frame_ms, 480)
    if args.only != "cards":
        frames = _shoot(_theme_shots(client, args.region), args.out, args.scale, THEME_SHOT_HEIGHT)
        _slideshow(frames, args.out / "themes.gif", args.frame_ms, 720)
    return 0


if __name__ == "__main__":
    sys.exit(main())
