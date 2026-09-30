"""A deck built in the browser, imported by Anki's own backend (ADR 0019).

The same checks as ``tests/acceptance/test_acceptance_anki.py``, through the same helpers, on
packages the browser wrote: notes and cards arrive, the media checker finds nothing missing or
left over, no front gives the bird's name away, every answer credits its assets. On top of that
a deck the browser wrote and one genanki wrote must be the *same deck* to Anki: importing the
second after the first adds nothing.

Skipped when the ``anki`` package or the browsers are not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("anki.collection")

from acceptance_support import (  # noqa: E402
    assert_clean_media,
    assert_credits_on_answers,
    assert_no_name_leak,
    card_count,
    guids,
    import_apkg,
    note_count,
    open_collection,
    rendered_cards,
)
from web_support import CATALOG_DIR, Spec, build_in_browser, build_with_python  # noqa: E402

from avianki.catalog.format import load_catalog  # noqa: E402

ALL = ("photo", "audio", "photo_audio")

SPECS = {
    "us-ma default": Spec(),
    "us-ma all cards": Spec(cards=ALL),
    "ca-qc subdeck": Spec(region="ca-qc", subdeck="Québec", cards=ALL),
    "us-az everything": Spec(region="us-az", tier="everything", cards=ALL),
}


@pytest.fixture
def col(tmp_path):
    collection = open_collection(tmp_path / "anki")
    yield collection
    collection.close()


@pytest.fixture(scope="module")
def species():
    return load_catalog(CATALOG_DIR).species


@pytest.fixture
def browser_deck(chromium_page, tmp_path):
    def build(spec: Spec):
        built = build_in_browser(chromium_page, spec)
        path = tmp_path / "browser.apkg"
        path.write_bytes(built.apkg)
        return path, built

    return build


@pytest.mark.parametrize("name", list(SPECS))
def test_a_browser_deck_imports_cleanly_and_meets_the_card_rules(name, browser_deck, col, species) -> None:
    spec = SPECS[name]
    path, built = browser_deck(spec)

    log = import_apkg(col, path)

    assert note_count(col) == card_count(col) == built.note_count > 0  # one card per note
    assert len(log.log.new) == note_count(col)
    assert_clean_media(col)  # 1: nothing missing, nothing unused
    cards = rendered_cards(col)
    assert len(cards) == note_count(col)
    assert_no_name_leak(col, cards)  # 5: fronts do not give the name away
    assert_credits_on_answers(cards, species)  # 6: every answer credits its assets
    for card in cards:
        assert card.name in card.answer_html or card.name.replace("&", "&amp;") in card.answer_html

    deck_names = {d.name for d in col.decks.all_names_and_ids()}
    assert (f"AviAnki::{spec.subdeck}" if spec.subdeck else "AviAnki") in deck_names


@pytest.mark.parametrize("name", ["us-ma all cards", "ca-qc subdeck"])
def test_the_browser_deck_and_the_genanki_deck_are_the_same_deck_to_anki(name, browser_deck, col, tmp_path) -> None:
    """Same GUIDs and note-type ids: a deck built on the web updates one built on the command line."""
    spec = SPECS[name]
    path, _ = browser_deck(spec)
    python_deck = tmp_path / "genanki.apkg"
    build_with_python(spec, python_deck)

    import_apkg(col, python_deck)
    before = (note_count(col), card_count(col), guids(col))
    log = import_apkg(col, path)

    assert len(log.log.new) == 0
    assert (note_count(col), card_count(col), guids(col)) == before
    ours = [m.id for m in col.models.all_names_and_ids() if m.name.startswith("AviAnki")]
    assert len(ours) == len(set(ours)) == 3  # the same three note types, none duplicated
    assert_clean_media(col)


def test_a_browser_deck_imports_in_webkit_too(page, col, species, tmp_path) -> None:
    """Whichever engine wrote the package, Anki accepts it (both engines are in the matrix)."""
    built = build_in_browser(page, SPECS["ca-qc subdeck"])
    path = tmp_path / "engine.apkg"
    path.write_bytes(built.apkg)
    import_apkg(col, path)
    assert note_count(col) == built.note_count > 0
    assert_clean_media(col)
    assert_credits_on_answers(rendered_cards(col), species)
