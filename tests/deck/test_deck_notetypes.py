"""Templates: fronts show only the prompt media; backs show the answer (spec section 6)."""

from __future__ import annotations

import re

import pytest

from avianki.deck.notetypes import BACK, CSS, FIELDS, MODELS

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


def _front(card_type: str) -> str:
    return MODELS[card_type].templates[0]["qfmt"]


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


def test_every_back_is_the_answer_side() -> None:
    for model in MODELS.values():
        assert model.templates[0]["afmt"] == BACK
    used = set(re.findall(r"\{\{[#/^]?(\w+)\}\}", BACK))
    assert used == {"Name", "SciName", "Photo", "Audio", "Credits"}
    back = render(BACK, FILLED)
    for needle in (NAME, SCI, FILLED["Photo"], FILLED["Audio"], CREDIT):
        assert needle in back


def test_templates_only_use_real_fields() -> None:
    for model in MODELS.values():
        tpl = model.templates[0]
        for text in (tpl["qfmt"], tpl["afmt"]):
            assert set(re.findall(r"\{\{[#/^]?(\w+)\}\}", text)) <= set(FIELDS)


def test_css_keeps_the_old_styling_and_adds_credits() -> None:
    assert ".card" in CSS and ".bird-name" in CSS and ".image-row" in CSS
    assert re.search(r"\.credits\s*\{[^}]*font-size:\s*\.75em[^}]*opacity:\s*\.7", CSS)
    assert re.search(r"\.credits a\s*\{[^}]*text-decoration:\s*underline", CSS)
    assert all(m.css == CSS for m in MODELS.values())
