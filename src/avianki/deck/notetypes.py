"""The three AviAnki note types (spec section 6, ADR 0009 and 0010).

Every string that decides how Anki recognises a note is FROZEN (ADR 0009): the card-type
names, the model seeds and the field list. ``tests/deck/test_identity.py`` pins them as
literals; changing one needs a new ADR and a major version, because existing users' notes
would stop matching on import.

Each card type is its own note type with one template. The front shows only the prompt
media, never Name, SciName or Credits: a credit line such as a file title can give the
species away (ADR 0012).
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

_PHOTO_BLOCK = '<div class="image-row">{{Photo}}</div>'
_AUDIO_BLOCK = '<div class="audio-row">{{Audio}}</div>'


def _front(prompt: str, *blocks: str) -> str:
    """A front: the prompt, then the media it asks about, one block per line."""
    return "\n".join(
        ['<div class="card">', f'  <div class="prompt-label">{prompt}</div>', *(f"  {b}" for b in blocks), "</div>"]
    )


# Per card type: the note type's name, the name of its one template, and that template's front.
_NOTE_TYPES: Final[dict[str, tuple[str, str, str]]] = {
    "photo": ("AviAnki · Photo", "Photo → Name", _front("What bird is this?", _PHOTO_BLOCK)),
    "audio": ("AviAnki · Audio", "Audio → Name", _front("Who's calling?", _AUDIO_BLOCK)),
    "photo_audio": (
        "AviAnki · Photo + Audio",
        "Photo + Audio → Name",
        _front("What bird is this?", _PHOTO_BLOCK, _AUDIO_BLOCK),
    ),
}

# One back for all three. Sections are conditional so a note without a photo (or without
# audio) leaves no empty box; the fronts don't need that because their media always exists.
BACK: Final[str] = """<div class="card">
  <div class="bird-name">{{Name}}</div>
  <div class="sci-name">{{SciName}}</div>
  {{#Photo}}<div class="image-row">{{Photo}}</div>{{/Photo}}
  {{#Audio}}<div class="audio-row">{{Audio}}</div>{{/Audio}}
  {{Credits}}
</div>"""


def stable_id(seed: str) -> int:
    """``int(md5(seed).hexdigest()[:8], 16)``: how model and deck ids are derived."""
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)


def _model(card_type: str) -> genanki.Model:
    model_name, template_name, front = _NOTE_TYPES[card_type]
    return genanki.Model(
        stable_id(MODEL_SEEDS[card_type]),
        model_name,
        fields=[{"name": f} for f in FIELDS],
        templates=[{"name": template_name, "qfmt": front, "afmt": BACK}],
        css=CSS,
        # Sort by Name in Anki's browser (SpeciesId is index 0 and is the duplicate key).
        sort_field_index=1,
    )


MODELS: Final[dict[str, genanki.Model]] = {ct: _model(ct) for ct in CARD_TYPES}
