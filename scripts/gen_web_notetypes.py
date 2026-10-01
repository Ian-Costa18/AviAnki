#!/usr/bin/env python3
"""Dump what the browser needs from ``avianki.deck`` into ``web/js/notetypes.json``.

Python is the single source of truth (ADR 0006, 0009): the three note types (ids, names,
fields, templates, CSS, sort field, ``req``) exactly as genanki serialises them, and the fixed
strings of the deck description. ``tests/scripts/test_gen_web_notetypes.py`` fails when the
checked-in file differs from a fresh dump, so the two cannot drift.

Usage:
    uv run python scripts/gen_web_notetypes.py           # rewrite web/js/notetypes.json
    uv run python scripts/gen_web_notetypes.py --check   # exit 1 if it is out of date
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from avianki.deck.credits import EBIRD_NOTICE, LICENCE_NOTICE, STUDY_GUIDANCE
from avianki.deck.notetypes import CARD_TYPES, FIELDS, MODEL_SEEDS, MODELS, back_for
from avianki.deck.themes import (
    BASE_CSS,
    CHOICES,
    COLOUR_KEYS,
    DEFAULT_THEME,
    NAME_ON_PHOTO_CSS,
    TEMPLATE_CSS,
    THEMES,
    tokens_as_dict,
)

OUT = Path(__file__).resolve().parents[1] / "web" / "js" / "notetypes.json"


def build_notetypes() -> dict[str, Any]:
    """The JSON document, as plain data.

    ``models[<card type>].json`` is genanki's ``Model.to_json`` with ``did`` and ``mod`` left
    at 0: the writer fills them in per build. Its key order is genanki's, which the browser
    keeps, so the note-type blob in the .apkg is serialised in the same order.
    """
    models: dict[str, Any] = {}
    for card_type in CARD_TYPES:
        model = MODELS[card_type]
        models[card_type] = {
            "seed": MODEL_SEEDS[card_type],
            "id": model.model_id,
            "json": json.loads(json.dumps(model.to_json(0, 0))),
        }
    return {
        "card_types": list(CARD_TYPES),
        "fields": list(FIELDS),
        "models": models,
        "look": build_look(),
        "description": {
            "study_guidance": list(STUDY_GUIDANCE),
            "licence_notice": LICENCE_NOTICE,
            "ebird_notice": EBIRD_NOTICE,
        },
    }


def build_look() -> dict[str, Any]:
    """Everything the page needs to compose a card's CSS and back like ``models_for`` does (ADR 0028).

    The composition rule itself (card.css, then the theme's CSS, then the layout's, each piece
    after a newline when it is not empty) is written once in ``avianki.deck.themes`` and once in
    ``web/js/themes.js``; ``tests/web/test_web_themes.py`` runs both over every theme and layout.
    A built-in theme ships as tokens plus its extra rules, not as finished CSS, so one code path
    in the browser serves built-in and custom themes alike.
    """
    return {
        "base_css": BASE_CSS,
        "template_css": TEMPLATE_CSS,
        "tables": {key: dict(table) for key, table in CHOICES.items()},
        "colour_keys": list(COLOUR_KEYS),
        "default_theme": DEFAULT_THEME,
        "themes": [
            {
                "name": theme.name,
                "description": theme.description,
                "generate": theme.generate,
                "tokens": tokens_as_dict(theme.tokens),
                "extra_css": theme.extra_css,
            }
            for theme in THEMES.values()
        ],
        "layout_css": {"name_on_photo": NAME_ON_PHOTO_CSS},
        "backs": {"default": back_for(False), "name_on_photo": back_for(True)},
    }


def render() -> str:
    return json.dumps(build_notetypes(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else None
        if current != text:
            print(f"{OUT} is out of date; run scripts/gen_web_notetypes.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
