"""Anki model definition for bird ID cards."""

import hashlib
from pathlib import Path

import genanki

CSS = (Path(__file__).parent / "card.css").read_text(encoding="utf-8")

# Fields shared by both card templates
FIELDS = [
    {"name": "BirdName"},
    {"name": "SciName"},
    {"name": "Image1"},              # <img src="..."> or ""
    {"name": "Image2"},              # <img src="..."> or ""
    {"name": "Call"},                # [sound:...] or ""
    {"name": "Song"},                # [sound:...] or ""
    {"name": "Description"},
    {"name": "DescriptionRedacted"}, # bird name replaced with [...]
]

_AUDIO_ROW = """<div class="audio-row">
  {{#Song}}<div class="audio-item"><div class="prompt-label">🎵 Song</div>{{Song}}</div>{{/Song}}
  {{#Call}}<div class="audio-item"><div class="prompt-label">🔊 Call</div>{{Call}}</div>{{/Call}}
</div>"""

# Shared answer side: name + both images + audio + description
_BACK = """
<div class="card">
  <div class="bird-name">{{BirdName}}</div>
  <div class="sci-name">{{SciName}}</div>
  <div class="image-row">{{Image1}}{{Image2}}</div>
  """ + _AUDIO_ROW + """
  <div class="divider"></div>
  <div class="desc-box">{{Description}}</div>
</div>"""

def _stable_id(seed: str) -> int:
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)


PHOTO_MODEL = genanki.Model(
    _stable_id("BirdDeck_PhotoModel_v1"),
    "Bird ID – Photo",
    fields=FIELDS,
    templates=[
        {
            "name": "Picture → Name",
            "qfmt": """
<div class="card">
  <div class="prompt-label">🖼 What bird is this?</div>
  <div class="image-row">{{Image1}}{{Image2}}</div>
  """ + _AUDIO_ROW + """
</div>""",
            "afmt": _BACK,
        }
    ],
    css=CSS,
)

DESC_MODEL = genanki.Model(
    _stable_id("BirdDeck_DescModel_v1"),
    "Bird ID – Description",
    fields=FIELDS,
    templates=[
        {
            "name": "Description → Name",
            "qfmt": """
<div class="card">
  <div class="prompt-label">🔊 What bird is this?</div>
  """ + _AUDIO_ROW + """
  <div class="divider"></div>
  <div class="desc-box">{{DescriptionRedacted}}</div>
</div>""",
            "afmt": _BACK,
        }
    ],
    css=CSS,
)
