#!/usr/bin/env python3
"""Generate PNG card example screenshots into examples/ for the README.

Also copies tests/tmp/birds.json to examples/example-birds.json.

Usage:
    uv run python scripts/gen_examples.py

Requires: playwright (dev dep) + browser installed via `playwright install chromium`
Requires: network access to fetch descriptions from allaboutbirds.org
Media source: tests/media/ (populated by the integration test)
"""

import base64
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from avianki.allaboutbirds import fetch_overview
from avianki.anki_model import CSS, TEMPLATES
from avianki.redact import redact_name

REPO_ROOT = Path(__file__).parent.parent
MEDIA_DIR = REPO_ROOT / "tests" / "media"
OUTPUT_DIR = REPO_ROOT / "examples"
BIRDS_JSON_SRC = REPO_ROOT / "tests" / "tmp" / "birds.json"
BIRDS_JSON_DST = OUTPUT_DIR / "example-birds.json"

# Birds from the Boston-area integration test, in deck order
BIRDS = [
    {"slug": "House_Sparrow",        "name": "House Sparrow"},
    {"slug": "American_Robin",       "name": "American Robin"},
    {"slug": "American_Herring_Gull","name": "American Herring Gull"},
]


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
    slug = bird["slug"]
    name = bird["name"]

    overview = fetch_overview(slug)
    desc = overview.get("desc", "")
    sci_name = overview.get("sciName", "")

    return {
        "BirdName": name,
        "SciName": sci_name,
        "Image1": _img_tag(MEDIA_DIR / f"bird_{slug}_img1.jpg"),
        "Image2": _img_tag(MEDIA_DIR / f"bird_{slug}_img2.jpg"),
        "Call":   _audio_tag(MEDIA_DIR / f"bird_{slug}_call.mp3"),
        "Song":   _audio_tag(MEDIA_DIR / f"bird_{slug}_song.mp3"),
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
    OUTPUT_DIR.mkdir(exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        for bird in BIRDS:
            print(f"  {bird['name']}…")
            fields = build_fields(bird)
            slug_lower = bird["slug"].lower()

            for tmpl in TEMPLATES:
                tmpl_key = tmpl["name"].lower().replace(" → ", "_").replace(" ", "_")

                front_html = _full_html(_render(tmpl["qfmt"], fields))
                back_html  = _full_html(_render(tmpl["afmt"], fields))

                screenshot(page, front_html, OUTPUT_DIR / f"{slug_lower}_{tmpl_key}_front.png")
                screenshot(page, back_html,  OUTPUT_DIR / f"{slug_lower}_{tmpl_key}_back.png")

        browser.close()

    saved = sorted(OUTPUT_DIR.glob("*.png"))
    print(f"\nSaved {len(saved)} images to examples/:")
    for p in saved:
        print(f"  {p.name}")

    if BIRDS_JSON_SRC.exists():
        shutil.copy(BIRDS_JSON_SRC, BIRDS_JSON_DST)
        print(f"\nCopied birds.json → {BIRDS_JSON_DST.relative_to(REPO_ROOT)}")
    else:
        print(f"\nWarning: {BIRDS_JSON_SRC.relative_to(REPO_ROOT)} not found — run the integration test first")


if __name__ == "__main__":
    main()
