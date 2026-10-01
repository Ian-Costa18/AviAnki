"""web/js/select.js against the shared, language-neutral selection cases and against plan_notes."""

from __future__ import annotations

import json

import pytest
from web_support import CATALOG_DIR, REPO

from avianki.catalog.format import load_catalog
from avianki.deck.build import plan_notes, select_species

CASES = json.loads((REPO / "tests" / "fixtures" / "selection" / "cases.json").read_text(encoding="utf-8"))

# The species file a case describes: one photo and/or recording per species from `media`
# (every species has both when `media` is omitted). Schema: tests/deck/test_deck_selection.py.
SELECT = """
async (cases) => {
  const { selectSpecies } = await import('/js/select.js');
  return cases.map((c) => {
    const speciesFile = {};
    for (const [id] of c.region.species) {
      const kinds = c.media ? (c.media[id] ?? []) : ['photo', 'audio'];
      speciesFile[id] = { name: id, sci: id,
        photo: kinds.includes('photo') ? [{ file: 'media/' + id }] : [],
        audio: kinds.includes('audio') ? [{ file: 'media/' + id }] : [] };
    }
    return selectSpecies(c.region, speciesFile, c.cards, { tier: c.tier, month: c.month });
  });
}
"""


def test_every_selection_case(chromium_page) -> None:
    got = chromium_page.evaluate(SELECT, CASES)
    for case, ids in zip(CASES, got, strict=True):
        assert ids == case["expected_species"], case["name"]


def test_selection_cases_in_webkit(page) -> None:
    got = page.evaluate(SELECT, CASES)
    assert got == [c["expected_species"] for c in CASES]


def test_bad_tier_and_month_are_rejected(chromium_page) -> None:
    bad = chromium_page.evaluate(
        """
        async () => {
          const { selectSpecies } = await import('/js/select.js');
          const region = { species: [['a', Array(12).fill(1)]] };
          const file = { a: { photo: [{ file: 'p' }], audio: [] } };
          const attempt = (options, cards = ['photo']) => {
            try { selectSpecies(region, file, cards, options); return null; } catch (e) { return e.name; }
          };
          return [attempt({ tier: 'huge' }), attempt({ tier: 'standard', month: 0 }),
                  attempt({ tier: 'standard', month: 13 }), attempt({ tier: 'standard', month: 1.5 }),
                  attempt({ tier: 'standard' }, ['video'])];
        }
        """
    )
    assert bad == ["RangeError"] * 5


def test_plan_notes_matches_python(chromium_page) -> None:
    """Card order, first assets on every note, skipped species and dedup, for every card subset."""
    catalog = load_catalog(CATALOG_DIR)
    ids = [
        *select_species(catalog.regions["us-ma"], catalog.species, ["photo", "audio"], tier="everything", month=None),
        "nope",
        "gavia-immer",
    ]
    subsets = [
        ["photo"], ["audio"], ["photo_audio"], ["photo", "audio"],
        ["photo_audio", "photo"], ["audio", "photo_audio", "photo"],
    ]
    expected = [
        [
            {"speciesId": n.species_id, "cardType": n.card_type,
             "photo": n.photo.file if n.photo else None, "audio": n.audio.file if n.audio else None}
            for n in plan_notes(ids, catalog.species, set(cards))
        ]
        for cards in subsets
    ]
    got = chromium_page.evaluate(
        """
        async ({ ids, subsets }) => {
          const { planNotes } = await import('/js/select.js');
          const manifest = await (await fetch('/catalog/manifest.json')).json();
          const speciesFile = await (await fetch('/catalog/' + manifest.species_file)).json();
          return subsets.map((cards) => planNotes(ids, speciesFile, cards, { warn: () => {} }).map((n) => ({
            speciesId: n.speciesId, cardType: n.cardType,
            photo: n.photo ? n.photo.file : null, audio: n.audio ? n.audio.file : null })));
        }
        """,
        {"ids": ids, "subsets": subsets},
    )
    assert got == expected
    assert any(n["photo"] and n["audio"] for n in got[0]), "photo notes must also carry the recording"


def test_plan_notes_rejects_unknown_card_types(chromium_page) -> None:
    name = chromium_page.evaluate(
        """
        async () => {
          const { planNotes } = await import('/js/select.js');
          try { planNotes(['a'], {}, ['video']); return null; } catch (e) { return e.name; }
        }
        """
    )
    assert name == "RangeError"


@pytest.mark.parametrize("cards", [["photo"], ["photo", "audio", "photo_audio"]])
def test_repeated_ids_are_planned_once(chromium_page, cards) -> None:
    n = chromium_page.evaluate(
        """
        async (cards) => {
          const { planNotes } = await import('/js/select.js');
          const s = (id) => ({ [id]: { name: id, sci: id, photo: [{ file: 'p' }], audio: [{ file: 'a' }] } });
          const file = { ...s('x'), ...s('y') };
          return planNotes(['x', 'y', 'x'], file, cards).length;
        }
        """,
        cards,
    )
    assert n == 2 * len(cards)


def test_a_species_missing_from_the_species_file_is_dropped_with_a_warning(chromium_page) -> None:
    got = chromium_page.evaluate(
        """
        async () => {
          const { selectSpecies } = await import('/js/select.js');
          const warnings = [];
          const region = { species: [['ghost', Array(12).fill(1)], ['real', Array(12).fill(1)]] };
          const file = { real: { photo: [{ file: 'p' }], audio: [] } };
          const ids = selectSpecies(region, file, ['photo'], { tier: 'everything', warn: (m) => warnings.push(m) });
          return { ids, warnings };
        }
        """
    )
    assert got["ids"] == ["real"]
    assert len(got["warnings"]) == 1 and "ghost" in got["warnings"][0]
