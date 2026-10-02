#!/usr/bin/env python3
"""Draw the README's pictures: the website, and real cards in every built-in theme.

The cards are rendered by Anki itself. The script builds a deck for one region with the CLI,
imports it into a scratch collection with Anki's own backend (the ``anki`` dev dependency, as in
``tests/acceptance/``), then restyles the note types once per theme with ``models_for`` and asks
Anki for each side's HTML. Only Anki's replay button and its body defaults are drawn here, the
same approximation as the website's preview (``web/js/preview.js``).

Writes into ``docs/images/``:

- ``website.png``: the website's first screen, where you pick a region and build.
- ``themes.gif``: every built-in theme in turn, each frame the question, the answer, and the
  answer in night mode. The stills are discarded unless ``--themes-out`` is given.
- ``name-on-photo.png``: the same three sides, in the default theme with ``--name-on-photo``.

Usage (needs the network, the published catalog and ``playwright install chromium``):

    uv run --extra catalog python scripts/gen_readme_images.py
    uv run --extra catalog python scripts/gen_readme_images.py --region us-az --species "Gambel's Quail"
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
from pathlib import Path

from anki.collection import Collection, ImportAnkiPackageRequest
from anki.import_export_pb2 import ImportAnkiPackageOptions
from PIL import Image
from playwright.sync_api import Page, sync_playwright

from avianki import cli
from avianki.catalog.client import CatalogClient
from avianki.deck.notetypes import models_for
from avianki.deck.themes import THEME_NAMES

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "images"
SITE_URL = "https://ian-costa18.github.io/AviAnki/"

PANEL_WIDTH, PANEL_HEIGHT = (
    360,
    700,
)  # a phone's screen, in CSS pixels; card.css sizes photos in vh
SCALE = 2  # device pixels per CSS pixel for the stills
GIF_WIDTH = 960  # the slideshow is scaled down to this
GIF_FRAME_MS = 2200

# Anki's replay button and body defaults, copied from web/js/preview.js (keep the two in step).
PLAY_ICON = (
    '<svg class="playImage" viewBox="0 0 64 64" version="1.1"><circle cx="32" cy="32" r="29"/>'
    '<path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z"/></svg>'
)
REPLAY_BUTTON = f'<a class="replay-button soundLink" href="#">{PLAY_ICON}</a>'
ANKI_DEFAULTS = """
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; }
.card { font-family: arial; font-size: 20px; text-align: center; color: #000; background-color: #fff; }
.card.nightMode, .card.night_mode { color: #fff; background-color: #2c2c2c; }
a.replay-button { display: inline-flex; text-decoration: none; cursor: pointer; }
.replay-button svg { width: 40px; height: 40px; }
.replay-button svg circle { fill: #fff; stroke: #8c8c8c; stroke-width: 2; }
.replay-button svg path { fill: #3a3a3a; }
.nightMode .replay-button svg circle, .night_mode .replay-button svg circle { fill: #3a3a3a; stroke: #9a9a9a; }
.nightMode .replay-button svg path, .night_mode .replay-button svg path { fill: #eee; }
"""
PLAY_TAG = re.compile(r"\[anki:play:[qa]:\d+\]")

# The sheet the three sides sit on: neutral grey, so no theme's background blends into it.
SHEET_CSS = f"""
body {{ margin: 0; background: #e5e7eb; font: 600 15px system-ui, sans-serif; color: #374151; }}
.sheet {{ display: inline-flex; gap: 20px; padding: 18px 22px 22px; }}
.side {{ display: flex; flex-direction: column; gap: 8px; align-items: center; margin: 0; }}
figcaption {{ letter-spacing: .02em; }}
figcaption b {{ font-weight: 800; }}
iframe {{ width: {PANEL_WIDTH}px; height: {PANEL_HEIGHT}px; border: 0; border-radius: 22px; display: block;
  box-shadow: 0 1px 2px rgb(0 0 0 / .12), 0 6px 18px rgb(0 0 0 / .12); }}
"""


def side_document(rendered: str, media_dir: Path, night: bool) -> str:
    """One card side as Anki shows it: ``rendered`` is Anki's own HTML, style block included."""
    body = PLAY_TAG.sub(REPLAY_BUTTON, rendered)
    night_class = " nightMode" if night else ""
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><base href="{media_dir.as_uri()}/">'
        f"<style>{ANKI_DEFAULTS}</style></head>"
        f'<body class="card{night_class}">{body}</body></html>'
    )


def sheet_document(sides: list[tuple[str, str]]) -> str:
    figures = "".join(
        f'<figure class="side"><figcaption>{label}</figcaption>'
        f'<iframe srcdoc="{html.escape(doc, quote=True)}"></iframe></figure>'
        for label, doc in sides
    )
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{SHEET_CSS}</style></head>'
        f'<body><div class="sheet">{figures}</div></body></html>'
    )


def build_collection(region: str, workdir: Path) -> Collection:
    """Build ``region`` with every card type through the CLI and import it like Anki's File > Import."""
    apkg = workdir / "examples.apkg"
    status = cli.main(
        [region, "--cards", "photo,audio,photo-audio", "-o", str(apkg), "-q"]
    )
    if status != 0:
        sys.exit(f"building {region} failed with exit status {status}")
    col = Collection(str(workdir / "collection.anki2"))
    options = ImportAnkiPackageOptions(
        merge_notetypes=True, update_notes=0, update_notetypes=0
    )
    col.import_anki_package(
        ImportAnkiPackageRequest(package_path=str(apkg), options=options)
    )
    return col


def restyle(col: Collection, theme: str, name_on_photo: bool) -> None:
    """Give the imported note types a theme's CSS and back, as importing a deck built with it would."""
    for model in models_for(theme, name_on_photo).values():
        notetype = col.models.by_name(model.name)
        assert notetype is not None, f"note type {model.name!r} was not imported"
        notetype["css"] = model.css
        notetype["tmpls"][0]["afmt"] = model.templates[0]["afmt"]
        col.models.update_dict(notetype)


def card_sides(col: Collection, species: str, template: str) -> tuple[str, str]:
    cid = col.db.scalar(
        "select c.id from cards c join notes n on n.id = c.nid join notetypes t on t.id = n.mid "
        "where n.sfld = ? and t.name = ?",
        species,
        template,
    )
    if cid is None:
        sys.exit(
            f"no {template!r} card for {species!r} in the deck; pick another --species"
        )
    card = col.get_card(cid)
    return card.question(), card.answer()


def shoot_sheet(page: Page, document: str, out: Path, media_dir: Path) -> None:
    """Draw one sheet into ``out``, warning when a side is longer than the phone screen.

    The sheet is opened from a file beside the media: Chromium only lets a file:// page load
    file:// images.
    """
    sheet = media_dir / "_sheet.html"
    sheet.write_text(document, encoding="utf-8")
    page.goto(sheet.as_uri(), wait_until="load")
    page.wait_for_function(
        "() => [...document.querySelectorAll('iframe')].every("
        "f => f.contentDocument && [...f.contentDocument.images].every(i => i.complete))"
    )
    tallest = page.evaluate(
        "() => Math.max(...[...document.querySelectorAll('iframe')].map("
        "f => f.contentDocument.documentElement.scrollHeight))"
    )
    if tallest > PANEL_HEIGHT:
        print(
            f"warning: {out.name}: a side is {tallest}px tall and is cut at {PANEL_HEIGHT}px",
            file=sys.stderr,
        )
    page.locator(".sheet").screenshot(path=str(out))


def draw_cards(
    col: Collection, media_dir: Path, species: str, out_dir: Path, themes_dir: Path
) -> list[Path]:
    """Draw every theme into ``themes_dir`` and the name-on-photo layout into ``out_dir``."""
    themes_dir.mkdir(parents=True, exist_ok=True)
    looks = [(theme, False, themes_dir / f"{theme}.png") for theme in THEME_NAMES]
    looks.append(("default", True, out_dir / "name-on-photo.png"))

    sheets = []
    for theme, name_on_photo, out in looks:
        restyle(col, theme, name_on_photo)
        question, answer = card_sides(col, species, "AviAnki · Photo")
        title = f"<b>{theme}</b>" + (" + --name-on-photo" if name_on_photo else "")
        sides = [
            (f"{title} · question", side_document(question, media_dir, night=False)),
            ("answer", side_document(answer, media_dir, night=False)),
            ("answer, night mode", side_document(answer, media_dir, night=True)),
        ]
        sheets.append((sheet_document(sides), out))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            device_scale_factor=SCALE, viewport={"width": 1400, "height": 900}
        )
        for doc, out in sheets:
            shoot_sheet(page, doc, out, media_dir)
        browser.close()
    return [out for _, out in sheets[: len(THEME_NAMES)]]


def draw_website(url: str, region_name: str, out: Path) -> None:
    """The site's first screen: its title down to the note under the Build button."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            device_scale_factor=SCALE, viewport={"width": 760, "height": 900}
        )
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#region:enabled")
        page.select_option("#region", label=region_name)
        top = page.locator("h1").bounding_box()
        bottom = page.locator("#anki-line").bounding_box()
        assert top and bottom, "the site's title or preview is missing"
        clip = {
            "x": 0,
            "y": top["y"] - 24,
            "width": 760,
            "height": bottom["y"] + bottom["height"] - top["y"] + 48,
        }
        page.screenshot(path=str(out), clip=clip, full_page=True)
        browser.close()


def write_gif(stills: list[Path], out: Path) -> None:
    """The stills as a looping slideshow, each frame with its own palette so the photo survives."""
    frames = []
    for still in stills:
        image = Image.open(still).convert("RGB")
        size = (GIF_WIDTH, round(image.height * GIF_WIDTH / image.width))
        frames.append(
            image.resize(size, Image.Resampling.LANCZOS).quantize(
                colors=256, method=Image.Quantize.MEDIANCUT
            )
        )
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=GIF_FRAME_MS,
        loop=0,
        optimize=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--region", default="us-ma", help="catalog region to build (default: us-ma)"
    )
    parser.add_argument(
        "--themes-out",
        type=Path,
        help="also keep each theme's still here (default: discarded)",
    )
    parser.add_argument(
        "--species",
        default="Northern Cardinal",
        help="English name of the bird to show",
    )
    parser.add_argument("--site-url", default=SITE_URL, help="the website to capture")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR,
        help="where to write (default: docs/images)",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        col = build_collection(args.region, Path(tmp))
        try:
            region_name = CatalogClient().find_region(args.region).name
            themes_dir = args.themes_out or Path(tmp) / "themes"
            stills = draw_cards(
                col, Path(col.media.dir()), args.species, args.out, themes_dir
            )
        finally:
            col.close()
        write_gif(stills, args.out / "themes.gif")
    draw_website(args.site_url, region_name, args.out / "website.png")
    for path in sorted(args.out.rglob("*.*")):
        print(f"{path.relative_to(REPO_ROOT)}  {path.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
