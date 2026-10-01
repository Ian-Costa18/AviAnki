"""The three AviAnki note types (spec section 6, ADR 0009 and 0010).

Every string that decides how Anki recognises a note is FROZEN (ADR 0009): the card-type
names, the model seeds and the field list. ``tests/deck/test_identity.py`` pins them as
literals; changing one needs a new ADR and a major version, because existing users' notes
would stop matching on import.

Each card type is its own note type with one template. The front shows only the prompt
media, never Name, SciName or Credits: a credit line such as a file title can give the
species away (ADR 0012).

Each back is built from its front (ADR 0025): the front's markup repeated exactly, so the
prompt and the media stay where they were when the card flips, then the answer block under
it. The wrapper is ``.av``, not ``.card``, because Anki's ``<body>`` already has class
``card``. Templates stay self-contained and do not use ``{{FrontSide}}``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

import genanki

CARD_TYPES: Final[tuple[str, ...]] = ("photo", "audio", "photo_audio")

# Frozen (ADR 0009). The browser hashes the same seeds.
MODEL_SEEDS: Final[dict[str, str]] = {
    "photo": "AviAnki_Photo_v2",
    "audio": "AviAnki_Audio_v2",
    "photo_audio": "AviAnki_PhotoAudio_v2",
}

# Frozen and ordered (spec section 6). Photo2 and Audio2 are reserved and stay empty at 1.0.
FIELDS: Final[tuple[str, ...]] = (
    "SpeciesId",
    "Name",
    "SciName",
    "Photo",
    "Photo2",
    "Audio",
    "Audio2",
    "Credits",
)

CSS: Final[str] = (Path(__file__).with_name("card.css")).read_text(encoding="utf-8")

_PHOTO_BLOCK = '<div class="photo">{{Photo}}</div>'
_AUDIO_BLOCK = '<div class="sound">{{Audio}}</div>'

_CLOSE = "</div>"
_NL = "\n"


def _front(prompt: str, *blocks: str) -> str:
    """A front: the prompt, then the media it asks about, one block per line."""
    lines = ['<div class="av">', f'  <div class="prompt">{prompt}</div>', *(f"  {b}" for b in blocks), _CLOSE]
    return _NL.join(lines)


def _back(front: str, *extra: str) -> str:
    """The front's markup unchanged, then the answer: names, any medium the front lacked, credits.

    The extras are conditional so a note without that medium leaves no empty box; the
    fronts don't need that because their media always exists.
    """
    answer = [
        '  <div class="names">',
        '    <div class="name">{{Name}}</div>',
        '    <div class="sci">{{SciName}}</div>',
        "  </div>",
        *(f"  {e}" for e in extra),
        "  {{Credits}}",
    ]
    return front.removesuffix(_CLOSE) + _NL.join(answer) + _NL + _CLOSE


_PHOTO_FRONT = _front("What bird is this?", _PHOTO_BLOCK)
_AUDIO_FRONT = _front("Who's calling?", _AUDIO_BLOCK)
_BOTH_FRONT = _front("What bird is this?", _PHOTO_BLOCK, _AUDIO_BLOCK)

# Per card type: the note type's name, the name of its one template, its front and its back.
_NOTE_TYPES: Final[dict[str, tuple[str, str, str, str]]] = {
    "photo": (
        "AviAnki · Photo",
        "Photo → Name",
        _PHOTO_FRONT,
        _back(_PHOTO_FRONT, "{{#Audio}}" + _AUDIO_BLOCK + "{{/Audio}}"),
    ),
    "audio": (
        "AviAnki · Audio",
        "Audio → Name",
        _AUDIO_FRONT,
        _back(_AUDIO_FRONT, "{{#Photo}}" + _PHOTO_BLOCK + "{{/Photo}}"),
    ),
    "photo_audio": ("AviAnki · Photo + Audio", "Photo + Audio → Name", _BOTH_FRONT, _back(_BOTH_FRONT)),
}


def stable_id(seed: str) -> int:
    """``int(md5(seed).hexdigest()[:8], 16)``: how model and deck ids are derived."""
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)


def _model(card_type: str) -> genanki.Model:
    model_name, template_name, front, back = _NOTE_TYPES[card_type]
    return genanki.Model(
        stable_id(MODEL_SEEDS[card_type]),
        model_name,
        fields=[{"name": f} for f in FIELDS],
        templates=[{"name": template_name, "qfmt": front, "afmt": back}],
        css=CSS,
        # Sort by Name in Anki's browser (SpeciesId is index 0 and is the duplicate key).
        sort_field_index=1,
    )


MODELS: Final[dict[str, genanki.Model]] = {ct: _model(ct) for ct in CARD_TYPES}
