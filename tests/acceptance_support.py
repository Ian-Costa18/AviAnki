"""Helpers for the acceptance tests (ADR 0019): open a collection with Anki's own backend, import
an .apkg into it, render cards, and check the six properties a built deck must have.

Importing this module needs the ``anki`` package, so tests call ``pytest.importorskip("anki")``
first. Nothing here builds decks; the tests do that through ``avianki.cli.main``.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from anki.collection import Collection, ImportAnkiPackageRequest
from anki.import_export_pb2 import ImportAnkiPackageOptions

from avianki.catalog.format import SpeciesFile

STRIP_BLOCKS = re.compile(r"<(style|script)\b.*?</\1>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")
IMG_SRC = re.compile(r"<img\b[^>]*?\bsrc=[\"']([^\"']+)[\"']", re.I)
WORD = re.compile(r"[^\W\d_]+", re.U)


def open_collection(folder: Path) -> Collection:
    """A fresh, empty collection in ``folder`` (its media folder sits beside it)."""
    folder.mkdir(parents=True, exist_ok=True)
    return Collection(str(folder / "collection.anki2"))


def import_apkg(col: Collection, apkg: Path):
    """Import like the desktop app's File > Import: update notes that are newer, keep scheduling."""
    options = ImportAnkiPackageOptions(merge_notetypes=True, update_notes=0, update_notetypes=0)
    return col.import_anki_package(ImportAnkiPackageRequest(package_path=str(apkg), options=options))


def note_count(col: Collection) -> int:
    return int(col.db.scalar("select count() from notes"))


def card_count(col: Collection) -> int:
    return int(col.db.scalar("select count() from cards"))


def revlog_count(col: Collection) -> int:
    return int(col.db.scalar("select count() from revlog"))


def note_ids(col: Collection) -> set[int]:
    return set(col.db.list("select id from notes"))


def guids(col: Collection) -> set[str]:
    return set(col.db.list("select guid from notes"))


def media_problems(col: Collection) -> tuple[list[str], list[str]]:
    """``(missing, unused)`` from Anki's own media check."""
    report = col.media.check()
    return list(report.missing), list(report.unused)


def plain(text: str) -> str:
    """The visible text of rendered card HTML: no style blocks or tags, entities decoded."""
    text = STRIP_BLOCKS.sub(" ", text)
    text = TAGS.sub(" ", text)
    return " ".join(html.unescape(text).split())


def name_words(*names: str) -> set[str]:
    """Words of a bird's names that would give the answer away: 3 letters or more, lower case."""
    return {w.lower() for n in names for w in WORD.findall(n) if len(w) > 2}


@dataclass
class Rendered:
    """One card, rendered by Anki."""

    name: str
    sci: str
    species_id: str
    template: str
    question_html: str
    answer_html: str
    question_files: list[str]  # media the front references: <img> sources and audio tags
    answer_files: list[str]
    has_photo: bool  # the note's Photo field is filled
    has_audio: bool


def _audio_files(tags: Iterable) -> list[str]:
    return [t.filename for t in tags if hasattr(t, "filename")]


def rendered_cards(col: Collection) -> list[Rendered]:
    out: list[Rendered] = []
    for cid in sorted(col.db.list("select id from cards")):
        card = col.get_card(cid)
        note = card.note()
        q, a = card.question(), card.answer()
        out.append(
            Rendered(
                name=note["Name"],
                sci=note["SciName"],
                species_id=note["SpeciesId"],
                template=card.template()["name"],
                question_html=q,
                answer_html=a,
                question_files=IMG_SRC.findall(q) + _audio_files(card.question_av_tags()),
                answer_files=IMG_SRC.findall(a) + _audio_files(card.answer_av_tags()),
                has_photo=bool(note["Photo"].strip()),
                has_audio=bool(note["Audio"].strip()),
            )
        )
    return out


def answer_some_cards(col: Collection, count: int) -> int:
    """Review ``count`` cards through the scheduler (Good), returning how many were answered."""
    deck = col.decks.by_name("AviAnki")
    assert deck is not None, "the AviAnki deck was not imported"
    col.decks.set_current(deck["id"])
    answered = 0
    for _ in range(count):
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            break
        item = queued.cards[0]
        card = col.get_card(item.card.id)
        card.start_timer()
        states = item.states
        col.sched.answer_card(col.sched.build_answer(card=card, states=states, rating=3))
        answered += 1
    return answered


# ---------------------------------------------------------------------------------------
# The checks the live and fixture tests share
# ---------------------------------------------------------------------------------------


def assert_clean_media(col: Collection) -> None:
    """Check 1 (media half): nothing the notes reference is missing and nothing is left over."""
    missing, unused = media_problems(col)
    assert missing == [], f"media the notes reference but the collection lacks: {missing[:5]}"
    assert unused == [], f"media in the collection that no note uses: {unused[:5]}"


def assert_no_name_leak(col: Collection, cards: list[Rendered]) -> None:
    """Check 5: the front, as text, has no word of the bird's names, and its media exists."""
    media_dir = Path(col.media.dir())
    for card in cards:
        words = name_words(card.name, card.sci)
        leaked = words & {w.lower() for w in WORD.findall(plain(card.question_html))}
        assert not leaked, f"{card.species_id} ({card.template}): the front shows {sorted(leaked)}"
        assert card.question_files, f"{card.species_id} ({card.template}): the front has no media"
        for name in card.question_files:
            assert (media_dir / name).is_file(), f"{card.species_id}: front media {name!r} is not in the collection"


def assert_credits_on_answers(cards: list[Rendered], species: SpeciesFile) -> None:
    """Check 6: every answer shows the credit line of each asset its note carries."""
    for card in cards:
        entry = species[card.species_id]
        expected = []
        if card.has_photo:
            expected.append(entry.photo[0].credit)
        if card.has_audio:
            expected.append(entry.audio[0].credit)
        assert expected, f"{card.species_id} ({card.template}): a note with no media"
        shown = plain(card.answer_html)
        for credit in expected:
            assert plain(credit) in shown, f"{card.species_id} ({card.template}): credit missing: {plain(credit)!r}"
