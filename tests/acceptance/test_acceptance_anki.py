"""Acceptance tests (ADR 0019): built decks through Anki's own backend.

Each test builds .apkg files with ``avianki.cli.main`` from the fixture catalog and imports them
into a fresh collection with the ``anki`` package (the Rust backend the desktop app uses). They
check what a learner would experience, not what the writer intended: notes and cards arrive, the
media checker is satisfied, progress survives a re-import, fronts do not give the name away, and
every answer credits its assets.

Skipped when the ``anki`` package is not installed (it is a dev dependency).
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import genanki
import pytest

pytest.importorskip("anki.collection")

from acceptance_support import (  # noqa: E402
    answer_some_cards,
    assert_clean_media,
    assert_credits_on_answers,
    assert_no_name_leak,
    card_count,
    guids,
    import_apkg,
    note_count,
    note_ids,
    open_collection,
    plain,
    rendered_cards,
    revlog_count,
)
from cli_fakes import FIXTURE_CATALOG, run_cli  # noqa: E402

from avianki.catalog.client import CatalogClient  # noqa: E402
from avianki.catalog.format import load_catalog  # noqa: E402
from avianki.deck import build as deck_build  # noqa: E402
from avianki.deck import notetypes  # noqa: E402

ALL_CARDS = "photo,audio,photo-audio"


@pytest.fixture
def make_deck(tmp_path, monkeypatch, capsys):
    """Build a deck through the CLI and return its path."""
    counter = iter(range(1000))

    def make(*argv: str, catalog: Path = FIXTURE_CATALOG) -> Path:
        out = tmp_path / f"deck{next(counter)}.apkg"
        result = run_cli([*argv, "-o", str(out), "-q"], tmp_path, monkeypatch, capsys, catalog=catalog)
        assert result.code == 0, result.err
        return out

    return make


@pytest.fixture
def col(tmp_path):
    collection = open_collection(tmp_path / "anki")
    yield collection
    collection.close()


@pytest.fixture
def species(tmp_path):
    return CatalogClient(str(FIXTURE_CATALOG), cache_dir=tmp_path / "species-cache").species()


def newer_catalog(tmp_path: Path) -> Path:
    """A copy of the fixture catalog published later (a new catalog_version)."""
    copy = tmp_path / "catalog-v2"
    shutil.copytree(FIXTURE_CATALOG, copy, ignore=shutil.ignore_patterns("make_fixture.py", "__pycache__"))
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    manifest["catalog_version"] = "2026-02-01"
    (copy / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return copy


# 1 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "notes"),
    [
        (["us-ma"], 22),  # 12 species; Snowy Owl has no audio, Common Loon no photo
        (["us-ma", "--cards", "photo"], 11),
        (["us-ma", "--cards", "audio"], 11),
        (["us-ma", "--cards", ALL_CARDS], 32),  # photo + audio + 10 species with both
        (["quebec"], 12),  # 7 species: 6 with a photo, 6 with a recording
        (["us-az", "--cards", ALL_CARDS], None),
    ],
)
def test_the_deck_imports_with_the_expected_notes_and_cards_and_clean_media(argv, notes, make_deck, col):
    log = import_apkg(col, make_deck(*argv))
    assert note_count(col) == card_count(col) > 0  # one card per note
    if notes is not None:
        assert note_count(col) == notes
    assert len(log.log.new) == note_count(col)
    assert_clean_media(col)


# 2 -------------------------------------------------------------------------------------


def test_a_rebuilt_deck_reimports_onto_the_same_notes_and_keeps_progress(make_deck, col, tmp_path):
    import_apkg(col, make_deck("us-ma"))
    assert answer_some_cards(col, 6) == 6
    before = (note_count(col), note_ids(col), revlog_count(col), guids(col))
    reviewed = col.db.scalar("select count() from cards where type != 0")
    assert before[2] == 6 and reviewed == 6

    later = make_deck("us-ma", catalog=newer_catalog(tmp_path))  # a new catalog version, a new build
    log = import_apkg(col, later)

    assert len(log.log.new) == 0
    assert (note_count(col), note_ids(col), revlog_count(col), guids(col)) == before
    assert col.db.scalar("select count() from cards where type != 0") == reviewed
    assert_clean_media(col)


def test_the_same_build_twice_is_a_no_op(make_deck, col):
    deck = make_deck("us-az")
    import_apkg(col, deck)
    log = import_apkg(col, deck)
    assert len(log.log.new) == 0
    assert note_count(col) == 12  # us-az: 6 species, photo and audio each


# 3 -------------------------------------------------------------------------------------


def test_going_from_standard_to_everything_adds_only_the_extra_notes(make_deck, col, monkeypatch):
    monkeypatch.setattr(deck_build, "STANDARD_LIMIT", 5)
    import_apkg(col, make_deck("us-ma", "--cards", "photo"))
    assert note_count(col) == 5
    standard_ids = note_ids(col)
    answer_some_cards(col, 3)
    revlog = revlog_count(col)

    log = import_apkg(col, make_deck("us-ma", "--cards", "photo", "--tier", "everything"))

    assert len(log.log.new) == 6  # 11 species with a photo, 5 already there
    assert note_count(col) == 11 and standard_ids <= note_ids(col)
    assert len(guids(col)) == note_count(col)  # no duplicates
    assert revlog_count(col) == revlog
    assert_clean_media(col)


# 4 -------------------------------------------------------------------------------------


def test_photo_and_audio_parts_imported_separately_equal_one_combined_build(make_deck, col, tmp_path):
    photos = make_deck("us-ma", "--cards", "photo")
    audio = make_deck("us-ma", "--cards", "audio")
    import_apkg(col, photos)
    import_apkg(col, audio)
    assert_clean_media(col)

    other = open_collection(tmp_path / "anki-combined")
    try:
        import_apkg(other, make_deck("us-ma", "--cards", "photo,audio"))
        assert note_count(col) == note_count(other) == 22
        assert guids(col) == guids(other)
    finally:
        other.close()


# 5 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("region", ["us-ma", "ca-qc", "us-az"])
def test_no_front_gives_the_name_away(region, make_deck, col):
    import_apkg(col, make_deck(region, "--cards", ALL_CARDS))
    cards = rendered_cards(col)
    assert len(cards) == note_count(col) > 0
    assert_no_name_leak(col, cards)


def test_the_name_leak_check_would_catch_a_leak(make_deck, col):
    import_apkg(col, make_deck("us-az", "--cards", "photo"))
    cards = rendered_cards(col)
    cards[0].question_html += f"<div>{cards[0].name}</div>"
    with pytest.raises(AssertionError, match="the front shows"):
        assert_no_name_leak(col, cards)


# 6 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("region", ["us-ma", "ca-qc", "us-az"])
def test_every_answer_credits_every_asset_its_note_carries(region, make_deck, col, species):
    import_apkg(col, make_deck(region, "--cards", ALL_CARDS))
    cards = rendered_cards(col)
    assert cards
    assert_credits_on_answers(cards, species)
    for card in cards:
        # the answer also names the bird, and shows the photo and plays the recording its note carries
        assert card.name in card.answer_html or card.name.replace("&", "&amp;") in card.answer_html
        assert len(card.answer_files) == card.has_photo + card.has_audio, (card.species_id, card.answer_files)


def test_the_credit_check_would_catch_a_missing_credit(make_deck, col, species):
    import_apkg(col, make_deck("us-az", "--cards", "photo"))
    cards = rendered_cards(col)
    cards[0].answer_html = "<div>no credit here</div>"
    with pytest.raises(AssertionError, match="credit missing"):
        assert_credits_on_answers(cards, species)


# 7 (ADR 0027) --------------------------------------------------------------------------


def _eight_field_models() -> dict[str, genanki.Model]:
    """The AviAnki note types as 0.9/early-0.10 shipped them: same ids, names and templates, no IocName."""
    tag = notetypes.MODELS["photo"].templates[0]["afmt"]
    old_back = tag.replace(
        '    {{#IocName}}<div class="ioc"><span class="ioc-tag"><b>IOC</b> {{IocName}}</span></div>{{/IocName}}\n', ""
    )
    assert old_back != tag and "IocName" not in old_back
    models = {}
    for card_type, model in notetypes.MODELS.items():
        templates = [{**t, "afmt": old_back} for t in model.templates]
        models[card_type] = genanki.Model(
            model.model_id,
            model.name,
            fields=[{"name": f} for f in notetypes.FIELDS if f != "IocName"],
            templates=templates,
            css=model.css,
            sort_field_index=model.sort_field_index,
        )
    return models


def _field_names(col, model_id: int) -> tuple[str, ...]:
    return tuple(col.db.list("select name from fields where ntid = ? order by ord", model_id))


def _write_us_ma(path: Path, tmp_path: Path, *, timestamp: float) -> None:
    catalog = load_catalog(FIXTURE_CATALOG)
    ids = deck_build.select_species(
        catalog.regions["us-ma"], catalog.species, set(deck_build.CARD_TYPES), tier="everything", month=None
    )
    notes = deck_build.plan_notes(ids, catalog.species, set(deck_build.CARD_TYPES))
    deck_build.write_deck(
        notes,
        catalog.species,
        catalog.manifest,
        media=lambda f: FIXTURE_CATALOG / f,
        out=path,
        timestamp=timestamp,
    )


def test_a_nine_field_deck_imports_over_the_old_eight_field_note_types_and_keeps_progress(
    col, tmp_path, monkeypatch
):
    """The 0.10 upgrade path: Anki updates the note types in place, keeps every card and its reviews, fills IocName."""
    old_models = _eight_field_models()
    old_fields = [f for f in notetypes.FIELDS if f != "IocName"]
    with monkeypatch.context() as m:
        m.setattr(deck_build, "models_for", lambda theme="default", name_on_photo=False: old_models)
        m.setattr(deck_build, "FIELDS", tuple(f for f in notetypes.FIELDS if f != "IocName"))
        _write_us_ma(tmp_path / "old.apkg", tmp_path, timestamp=1_700_000_000.0)
    import_apkg(col, tmp_path / "old.apkg")
    assert {_field_names(col, m.model_id) for m in notetypes.MODELS.values()} == {tuple(old_fields)}
    assert answer_some_cards(col, 6) == 6
    cards_before = set(col.db.list("select id from cards"))
    reviewed = {cid: col.get_card(cid).reps for cid in col.db.list("select id from cards where type != 0")}
    before = (note_count(col), note_ids(col), guids(col), revlog_count(col))
    schema_before = col.db.scalar("select scm from col")

    _write_us_ma(tmp_path / "new.apkg", tmp_path, timestamp=time.time() + 3600)
    log = import_apkg(col, tmp_path / "new.apkg")

    assert len(log.log.new) == 0
    assert (note_count(col), note_ids(col), guids(col), revlog_count(col)) == before
    assert set(col.db.list("select id from cards")) == cards_before
    assert {cid: col.get_card(cid).reps for cid in reviewed} == reviewed  # scheduling is untouched
    assert len(reviewed) == 6
    # Changing a note type's fields is a schema change: the next AnkiWeb sync asks which side wins (ADR 0027).
    assert col.db.scalar("select scm from col") > schema_before

    # Read the tables, not col.models.get(): the Python wrapper keeps serving the cached 8-field type
    # for the rest of the session, although the collection itself has been updated.
    for model in notetypes.MODELS.values():
        assert _field_names(col, model.model_id) == tuple(notetypes.FIELDS)
    by_species = {c.species_id: c for c in rendered_cards(col)}
    assert by_species["anas-platyrhynchos"].ioc_name == "Wild Duck"
    assert 'class="ioc-tag"' in by_species["anas-platyrhynchos"].answer_html
    assert "Wild Duck" in plain(by_species["anas-platyrhynchos"].answer_html)
    assert all(c.ioc_name == "" for k, c in by_species.items() if k != "anas-platyrhynchos")
    assert all('class="ioc-tag"' not in c.answer_html for k, c in by_species.items() if k != "anas-platyrhynchos")
    assert_no_name_leak(col, list(by_species.values()))
    assert_clean_media(col)


def test_the_ioc_tag_shows_on_the_answer_above_the_name_and_never_on_the_front(make_deck, col):
    import_apkg(col, make_deck("us-ma", "--cards", ALL_CARDS))
    mallards = [c for c in rendered_cards(col) if c.species_id == "anas-platyrhynchos"]
    assert len(mallards) == 3
    for card in mallards:
        assert plain(card.answer_html).index("IOC Wild Duck") < plain(card.answer_html).index("Mallard")
        assert "IOC" not in plain(card.question_html) and "Wild Duck" not in card.question_html


# 8 (ADR 0028) --------------------------------------------------------------------------


def _model_css(col, model_id: int) -> str:
    return col.models.get(model_id)["css"]


@pytest.mark.parametrize(
    "look",
    [["--theme", "nord"], ["--theme", "field-guide", "--name-on-photo"], ["--name-on-photo"]],
    ids=["nord", "field-guide-overlay", "default-overlay"],
)
def test_a_themed_deck_imports_cleanly_with_the_same_note_type_ids(look, make_deck, col):
    log = import_apkg(col, make_deck("us-ma", "--cards", ALL_CARDS, *look))
    assert note_count(col) == card_count(col) == 32 and len(log.log.new) == 32
    assert_clean_media(col)
    for card_type, model in notetypes.MODELS.items():
        assert col.models.get(model.model_id) is not None, card_type  # the frozen id (ADR 0009)
        assert col.models.get(model.model_id)["name"] == model.name
        assert _field_names(col, model.model_id) == tuple(notetypes.FIELDS)
    # What a learner sees: the answer carries the names, the tag and every credit; the front gives nothing away.
    cards = rendered_cards(col)
    assert_no_name_leak(col, cards)
    assert_credits_on_answers(cards, CatalogClient(str(FIXTURE_CATALOG)).species())
    assert 'class="ioc-tag"' in next(c for c in cards if c.species_id == "anas-platyrhynchos").answer_html


def test_the_theme_is_in_the_imported_note_types_css(make_deck, col):
    from avianki.deck import themes

    import_apkg(col, make_deck("us-ma", "--cards", "photo", "--theme", "nord", "--name-on-photo"))
    expected = themes.compose_css("nord", True)
    assert _model_css(col, notetypes.MODELS["photo"].model_id) == expected
    answer = next(iter(rendered_cards(col))).answer_html
    assert 'class="photo"' in answer and answer.index('class="photo"') < answer.index('class="names"')


def test_changing_the_theme_and_reimporting_keeps_every_note_and_all_progress(make_deck, col, tmp_path):
    import_apkg(col, make_deck("us-ma", "--cards", "photo"))
    assert answer_some_cards(col, 6) == 6
    before = (note_count(col), note_ids(col), revlog_count(col), guids(col))
    cards_before = set(col.db.list("select id from cards"))

    log = import_apkg(col, make_deck("us-ma", "--cards", "photo", "--theme", "forest", "--name-on-photo"))

    assert len(log.log.new) == 0
    assert (note_count(col), note_ids(col), revlog_count(col), guids(col)) == before
    assert set(col.db.list("select id from cards")) == cards_before
    assert col.db.scalar("select count() from cards where type != 0") == 6
    assert_clean_media(col)
