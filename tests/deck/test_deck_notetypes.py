"""Templates: fronts show only the prompt; one standard back answers (ADR 0025)."""

from __future__ import annotations

import re

import pytest

from avianki.deck.notetypes import CSS, FIELDS, MODELS

NAME = "American Robin"
SCI = "Turdus migratorius"
CREDIT = "Photo: <i>Robin File</i> by <b>Someone</b> · CC BY-SA 3.0"

FILLED = {
    "SpeciesId": "turdus-migratorius",
    "Name": NAME,
    "SciName": SCI,
    "Photo": '<img src="avianki_1a2b.webp">',
    "Photo2": "",
    "Audio": "[sound:avianki_9f8e.mp3]",
    "Audio2": "",
    "Credits": f'<div class="credits">{CREDIT}</div>',
}


def render(template: str, fields: dict[str, str]) -> str:
    """Plain substitution of ``{{Field}}`` tokens; section tags are dropped, not evaluated."""
    template = re.sub(r"\{\{[#/^]\w+\}\}", "", template)
    return re.sub(r"\{\{(\w+)\}\}", lambda m: fields[m.group(1)], template)


CARD_TYPES = ["photo", "audio", "photo_audio"]


def _front(card_type: str) -> str:
    return MODELS[card_type].templates[0]["qfmt"]


def _back(card_type: str) -> str:
    return MODELS[card_type].templates[0]["afmt"]


def test_every_model_has_one_template() -> None:
    for model in MODELS.values():
        assert len(model.templates) == 1


@pytest.mark.parametrize("card_type", ["photo", "audio", "photo_audio"])
def test_front_leaks_nothing_from_the_answer(card_type: str) -> None:
    text = render(_front(card_type), FILLED)
    assert NAME not in text and SCI not in text
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", f"{NAME} {SCI}")}
    visible = re.sub(r"<[^>]+>", " ", text)  # markup and attribute values aren't shown
    visible_words = {w.lower() for w in re.findall(r"[A-Za-z]+", visible)}
    assert not words & visible_words, words & visible_words
    assert "Someone" not in text and "Robin File" not in text and "credits" not in text
    assert "SpeciesId" not in _front(card_type)


@pytest.mark.parametrize("card_type", ["photo", "audio", "photo_audio"])
def test_front_references_only_prompt_media(card_type: str) -> None:
    used = set(re.findall(r"\{\{[#/^]?(\w+)\}\}", _front(card_type)))
    allowed = {
        "photo": {"Photo"},
        "audio": {"Audio"},
        "photo_audio": {"Photo", "Audio"},
    }[card_type]
    assert used == allowed


def test_front_prompts() -> None:
    assert "What bird is this?" in _front("photo")
    assert "Who's calling?" in _front("audio")
    front = _front("photo_audio")
    assert "{{Photo}}" in front and "{{Audio}}" in front


def test_every_model_shares_one_identical_back() -> None:
    backs = {_back(ct) for ct in CARD_TYPES}
    assert len(backs) == 1


@pytest.mark.parametrize("card_type", CARD_TYPES)
def test_back_is_photo_then_names_then_recording_then_credits(card_type: str) -> None:
    back = _back(card_type)
    photo = '{{#Photo}}<div class="photo">{{Photo}}</div>{{/Photo}}'
    audio = '{{#Audio}}<div class="sound">{{Audio}}<span class="sound-label">Hear the call</span></div>{{/Audio}}'
    assert back.startswith("\n  ".join(['<div class="av">', photo]))
    assert back.endswith("</div>") and back.count("<div") == back.count("</div>")
    assert '<div class="name">{{Name}}</div>' in back
    assert '<div class="sci">{{SciName}}</div>' in back
    positions = [back.index(x) for x in (photo, 'class="names"', audio, "{{Credits}}")]
    assert positions == sorted(positions)
    assert "{{FrontSide}}" not in back


@pytest.mark.parametrize("card_type", CARD_TYPES)
def test_back_asks_no_question(card_type: str) -> None:
    back = _back(card_type)
    assert "?" not in back
    assert "prompt" not in back


@pytest.mark.parametrize("card_type", ["photo", "photo_audio"])
def test_photo_is_first_on_the_front_so_it_matches_the_back(card_type: str) -> None:
    front = _front(card_type)
    assert front.startswith("\n  ".join(['<div class="av">', '<div class="photo">{{Photo}}</div>']))


def test_front_layouts() -> None:
    def sound(label: str) -> str:
        return f'<div class="sound">{{{{Audio}}}}<span class="sound-label">{label}</span></div>'

    assert _front("photo").endswith("\n".join(['  <div class="prompt">What bird is this?</div>', "</div>"]))
    assert _front("audio") == "\n".join(['<div class="av">', "  " + sound("Who's calling?"), "</div>"])
    assert _front("photo_audio").endswith("\n".join(["  " + sound("What bird is this?"), "</div>"]))


@pytest.mark.parametrize("card_type", CARD_TYPES)
def test_front_never_has_the_answer(card_type: str) -> None:
    front = _front(card_type)
    for token in ("{{Name}}", "{{SciName}}", "{{Credits}}"):
        assert token not in front


@pytest.mark.parametrize("card_type", CARD_TYPES)
def test_back_fills_in(card_type: str) -> None:
    back = render(_back(card_type), FILLED)
    for needle in (NAME, SCI, CREDIT):
        assert needle in back
    assert FILLED["Photo"] in back and FILLED["Audio"] in back


def test_no_template_wraps_in_class_card() -> None:
    # Anki's <body> already has class "card" (ADR 0025).
    for model in MODELS.values():
        for text in (model.templates[0]["qfmt"], model.templates[0]["afmt"]):
            assert 'class="card"' not in text
            assert text.startswith('<div class="av">')


def test_templates_only_use_real_fields() -> None:
    for model in MODELS.values():
        tpl = model.templates[0]
        for text in (tpl["qfmt"], tpl["afmt"]):
            assert set(re.findall(r"\{\{[#/^]?(\w+)\}\}", text)) <= set(FIELDS)


def test_css_has_night_mode_for_desktop_ios_and_ankidroid() -> None:
    assert ".nightMode" in CSS and ".night_mode" in CSS
    assert re.search(r"\.card\.nightMode[^{]*\{[^}]*background", CSS)
    assert re.search(r"\.night_mode \.av\s*\{[^}]*--ink", CSS)


def test_css_styles_the_card_design() -> None:
    for selector in (".av", ".prompt", ".photo", ".sound", ".names", ".name", ".sci", ".credits"):
        assert re.search(rf"^{re.escape(selector)}[ ,.{{]", CSS, re.M), selector
    assert re.search(r"\.credits\s*\{[^}]*font-size:\s*11\.5px", CSS)
    assert re.search(r"\.credits a\s*\{[^}]*text-decoration:\s*underline", CSS)
    assert "max-height:46vh" in CSS
    for old in (".bird-name", ".sci-name", ".image-row", ".audio-row", ".prompt-label"):
        assert old not in CSS
    assert all(m.css == CSS for m in MODELS.values())
