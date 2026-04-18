"""Anki model definition for bird ID cards."""

import hashlib

import genanki

CSS = """
.card {
  font-family: Georgia, serif;
  font-size: 16px;
  color: #1a1a1a;
  background-color: #fafaf7;
  max-width: 600px;
  margin: 0 auto;
  padding: 16px;
  line-height: 1.5;
}
.bird-name { font-size: 1.6em; font-weight: bold; color: #2c5f2e; margin: 12px 0 4px 0; }
.sci-name  { font-style: italic; color: #666; font-size: 0.9em; margin-bottom: 14px; }
.image-row {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}
.image-row img {
  flex: 1;
  width: 0;
  height: 190px;
  object-fit: contain;
  background: #e8e8e4;
  border-radius: 8px;
}
.audio-row {
  display: flex;
  gap: 12px;
  margin: 8px 0;
}
.audio-item {
  flex: 1;
}
.audio-item audio { width: 100%; }
.desc-box {
  background: #f0f4f0;
  border-left: 4px solid #2c5f2e;
  padding: 10px 14px;
  border-radius: 0 6px 6px 0;
  margin: 10px 0;
  font-size: 0.95em;
}
.prompt-label {
  font-size: 0.85em; font-weight: bold; color: #888;
  text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px;
}
.divider { border-top: 1px solid #ddd; margin: 14px 0; }
"""

# Fields shared by both card templates
FIELDS = [
    {"name": "BirdName"},
    {"name": "SciName"},
    {"name": "Image1"},    # <img src="..."> or ""
    {"name": "Image2"},    # <img src="..."> or ""
    {"name": "Call"},      # [sound:...] or ""
    {"name": "Song"},      # [sound:...] or ""
    {"name": "Description"},
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

TEMPLATES = [
    {
        "name": "Picture → Name",
        "qfmt": """
<div class="card">
  <div class="prompt-label">🖼 What bird is this?</div>
  <div class="image-row">{{Image1}}{{Image2}}</div>
  """ + _AUDIO_ROW + """
</div>""",
        "afmt": _BACK,
    },
    {
        "name": "Description → Name",
        "qfmt": """
<div class="card">
  <div class="prompt-label">🔊 What bird is this?</div>
  """ + _AUDIO_ROW + """
  <div class="divider"></div>
  <div class="desc-box">{{Description}}</div>
</div>""",
        "afmt": _BACK,
    },
]


def _stable_id(seed: str) -> int:
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)


MODEL = genanki.Model(
    _stable_id("BirdDeck_Model_v2"),
    "Bird ID",
    fields=FIELDS,
    templates=TEMPLATES,
    css=CSS,
)
