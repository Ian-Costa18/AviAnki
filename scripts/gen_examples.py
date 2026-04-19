#!/usr/bin/env python3
"""Generate PNG card example screenshots into examples/ for the README.

Also copies tests/tmp/birds.json to examples/example-birds.json.

Usage:
    uv run python scripts/gen_examples.py

Requires: playwright (dev dep) + browser installed via `playwright install chromium`
Media source: tests/media/ and tests/tmp/birds.json (populated by the integration test)
"""

import base64
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from avianki.anki_model import CSS, DESC_MODEL, PHOTO_MODEL
from avianki.redact import redact_name

REPO_ROOT = Path(__file__).parent.parent
MEDIA_DIR = REPO_ROOT / "tests" / "media"
OUTPUT_DIR = REPO_ROOT / "examples"
BIRDS_JSON_SRC = REPO_ROOT / "tests" / "tmp" / "birds.json"
BIRDS_JSON_DST = OUTPUT_DIR / "example-birds.json"


def _data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _img_tag(path: Path) -> str:
    return f'<img src="{_data_uri(path, "image/jpeg")}">' if path.exists() else ""


def _audio_tag(path: Path) -> str:
    if not path.exists():
        return ""
    return f'<audio controls><source src="{_data_uri(path, "audio/mpeg")}" type="audio/mpeg"></audio>'


def _render(template_str: str, fields: dict) -> str:
    """Evaluate Anki {{#Field}}...{{/Field}} conditionals then substitute fields."""
    def eval_cond(m):
        return m.group(2) if fields.get(m.group(1)) else ""

    result = re.sub(
        r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", eval_cond, template_str, flags=re.DOTALL
    )
    for name, value in fields.items():
        result = result.replace("{{" + name + "}}", value or "")
    return result


def _full_html(card_html: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ margin: 0; padding: 20px; background: #fafaf7; }}
{CSS}
</style></head><body>{card_html}</body></html>"""


def build_fields(bird: dict) -> dict:
    name = bird["name"]
    desc = bird.get("description", "")
    images = bird.get("images", [])
    img1 = MEDIA_DIR / images[0] if len(images) > 0 else Path("/nonexistent")
    img2 = MEDIA_DIR / images[1] if len(images) > 1 else Path("/nonexistent")
    call = MEDIA_DIR / bird["call"] if bird.get("call") else Path("/nonexistent")
    song = MEDIA_DIR / bird["song"] if bird.get("song") else Path("/nonexistent")

    return {
        "BirdName": name,
        "SciName": bird.get("sci_name", ""),
        "Image1": _img_tag(img1),
        "Image2": _img_tag(img2),
        "Call":   _audio_tag(call),
        "Song":   _audio_tag(song),
        "Description": desc,
        "DescriptionRedacted": redact_name(desc, name),
    }


def screenshot(page, html: str, out: Path, width: int = 660) -> None:
    page.set_viewport_size({"width": width, "height": 800})
    page.set_content(html, wait_until="load")
    height = page.evaluate("document.body.scrollHeight")
    page.set_viewport_size({"width": width, "height": max(height, 100)})
    page.screenshot(path=str(out), full_page=False)


def main() -> None:
    if not BIRDS_JSON_SRC.exists():
        print(f"Error: {BIRDS_JSON_SRC.relative_to(REPO_ROOT)} not found — run the integration test first")
        sys.exit(1)

    birds = json.loads(BIRDS_JSON_SRC.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        for bird in birds:
            print(f"  {bird['name']}…")
            fields = build_fields(bird)
            slug = bird["name"].replace(" ", "_")

            for tmpl in PHOTO_MODEL.templates + DESC_MODEL.templates:
                tmpl_key = tmpl["name"].lower().replace(" → ", "_").replace(" ", "_")

                front_html = _full_html(_render(tmpl["qfmt"], fields))
                back_html  = _full_html(_render(tmpl["afmt"], fields))

                screenshot(page, front_html, OUTPUT_DIR / f"{slug}_{tmpl_key}_front.png")
                screenshot(page, back_html,  OUTPUT_DIR / f"{slug}_{tmpl_key}_back.png")

        browser.close()

    saved = sorted(OUTPUT_DIR.glob("*.png"))
    print(f"\nSaved {len(saved)} images to examples/:")
    for p in saved:
        print(f"  {p.name}")

    shutil.copy(BIRDS_JSON_SRC, BIRDS_JSON_DST)
    print(f"\nCopied birds.json → {BIRDS_JSON_DST.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
