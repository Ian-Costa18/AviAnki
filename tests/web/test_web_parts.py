"""Parts (ADR 0006): a big build on a constrained device arrives as several packages, each of
150 species, that together are exactly the single-package deck.

The unit tests drive ``web/js/parts.js`` directly; the end-to-end tests use ``?partSize=5`` so the
12-bird fixture region needs three parts.
"""

from __future__ import annotations

import re

import pytest
from app_support import (
    ALL_CARDS,
    CONSTRAINED,
    apkg_guids,
    build,
    expected_guids,
    import_and_check,
    open_app,
    visible_text,
)

# ---------------------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------------------

PLAN_JS = """
async ({ size, split, cards }) => {
  const { selectSpecies, planNotes } = await import('/js/select.js');
  const { planParts, fileName } = await import('/js/parts.js');
  const json = async (path) => (await fetch('/catalog/' + path)).json();
  const manifest = await json('manifest.json');
  const region = await json(manifest.regions.find((r) => r.slug === 'us-ma').file);
  const speciesFile = await json(manifest.species_file);
  const ids = selectSpecies(region, { tier: 'everything', month: null });
  const parts = planParts(ids, speciesFile, cards, { size, split });
  const whole = planNotes(ids, speciesFile, cards);
  const key = (n) => n.speciesId + '/' + n.cardType;
  return {
    ids: ids.length,
    counts: parts.map((p) => p.count),
    indexes: parts.map((p) => p.index),
    sizes: parts.map((p) => new Set(p.notes.map((n) => n.speciesId)).size),
    names: parts.map((p) => fileName('us-ma', p)),
    joined: parts.flatMap((p) => p.notes.map(key)),
    whole: whole.map(key),
  };
}
"""


@pytest.mark.parametrize(
    ("size", "split", "sizes"),
    [
        (5, "whenLarge", [5, 5, 2]),
        (150, "whenLarge", [12]),
        (5, "never", [12]),
        (150, "always", [6, 6]),
        (5, "always", [5, 5, 2]),
    ],
)
def test_plan_parts_splits_consecutive_species_and_loses_nothing(page, size, split, sizes) -> None:
    got = page.evaluate(PLAN_JS, {"size": size, "split": split, "cards": list(ALL_CARDS)})

    assert got["sizes"] == sizes
    assert got["counts"] == [len(sizes)] * len(sizes)
    assert got["indexes"] == list(range(1, len(sizes) + 1))
    assert got["joined"] == got["whole"]  # the same notes in the same order, none twice
    if len(sizes) > 1:
        assert got["names"] == [f"AviAnki-part-{i}-of-{len(sizes)}.apkg" for i in range(1, len(sizes) + 1)]
    else:
        assert got["names"] == ["AviAnki-us-ma.apkg"]


def test_plan_parts_drops_species_without_media_and_renumbers(page) -> None:
    got = page.evaluate(
        """async () => {
          const { planParts } = await import('/js/parts.js');
          const speciesFile = { a: { photo: [], audio: [] }, b: { photo: [], audio: [] } };
          return planParts(['a', 'b'], speciesFile, ['photo'], { size: 1, split: 'whenLarge' }).length;
        }"""
    )
    assert got == 0  # no media, no notes, no empty packages


def test_file_name_uses_the_slug_only_for_a_single_package(page) -> None:
    got = page.evaluate(
        """async () => {
          const { fileName } = await import('/js/parts.js');
          return [fileName('ca-qc', { index: 1, count: 1 }), fileName('ca-qc', { index: 2, count: 3 })];
        }"""
    )
    assert got == ["AviAnki-ca-qc.apkg", "AviAnki-part-2-of-3.apkg"]


def test_bird_counter_counts_birds_whose_media_has_arrived(page) -> None:
    got = page.evaluate(
        """async () => {
          const { selectSpecies, planNotes } = await import('/js/select.js');
          const { mediaFiles } = await import('/js/deck.js');
          const { birdCounter } = await import('/js/parts.js');
          const json = async (path) => (await fetch('/catalog/' + path)).json();
          const manifest = await json('manifest.json');
          const region = await json(manifest.regions.find((r) => r.slug === 'us-ma').file);
          const speciesFile = await json(manifest.species_file);
          const notes = planNotes(selectSpecies(region, { tier: 'standard', month: null }), speciesFile,
            ['photo', 'audio']);
          const files = mediaFiles(notes);
          const counter = birdCounter(notes, files);
          const steps = Array.from({ length: files.length + 1 }, (_, i) => counter.done(i));
          return { total: counter.total, steps, species: new Set(notes.map((n) => n.speciesId)).size };
        }"""
    )
    assert got["total"] == got["species"] == 12
    assert got["steps"][0] == 0
    assert got["steps"][-1] == got["total"]
    assert got["steps"] == sorted(got["steps"])  # never goes backwards


@pytest.mark.parametrize(
    ("memory", "platform", "expected"),
    [
        (4, "android", True),
        (2, "desktop", True),
        (8, "android", False),
        (None, "desktop", False),  # Safari and Firefox do not report memory
        (None, "ios", True),
        (8, "ios", True),
    ],
)
def test_is_constrained(page, memory, platform, expected) -> None:
    got = page.evaluate(
        "async (a) => { const m = await import('/js/parts.js');"
        " return m.isConstrained({ deviceMemory: a.memory ?? undefined, platform: a.platform }); }",
        {"memory": memory, "platform": platform},
    )
    assert got is expected


def test_is_out_of_memory_recognises_the_usual_failures(page) -> None:
    got = page.evaluate(
        """async () => {
          const { isOutOfMemory } = await import('/js/parts.js');
          return [
            isOutOfMemory(new RangeError('Array buffer allocation failed')),
            isOutOfMemory(new RangeError('Invalid array length')),
            isOutOfMemory(new Error('Out of memory')),
            isOutOfMemory(new Error('memory allocation of 1048576 bytes failed')),
            isOutOfMemory(new Error('Failed to fetch')),
            isOutOfMemory(new TypeError('x is not a function')),
            isOutOfMemory(undefined),
          ];
        }"""
    )
    assert got == [True, True, True, True, False, False, False]


def test_part_size_override_reads_the_query(page) -> None:
    got = page.evaluate(
        """async () => {
          const { partSizeOverride, PART_SIZE } = await import('/js/parts.js');
          return [PART_SIZE, partSizeOverride(''), partSizeOverride('?partSize=5'), partSizeOverride('?partSize=0'),
            partSizeOverride('?partSize=x'), partSizeOverride('?a=1&partSize=7')];
        }"""
    )
    assert got == [150, 150, 5, 150, 150, 7]


# ---------------------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------------------


def test_constrained_device_gets_the_everything_deck_in_three_parts(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    context.add_init_script(CONSTRAINED)
    page = open_app(context, base_url, "?partSize=5")

    # The hint appears as soon as the choice is a big one, before anything is built.
    page.select_option("#region", label="Massachusetts")
    page.click("#advanced > summary")
    assert not page.is_visible("#parts-hint")
    page.check('input[name="tier"][value="everything"]')
    assert "smaller files" in visible_text(page, "#parts-hint")

    files = build(page, tmp_path, tier="everything", cards=ALL_CARDS)

    assert [f.name for f in files] == [f"AviAnki-part-{i}-of-3.apkg" for i in (1, 2, 3)]
    assert "in 3 files" in visible_text(page, "#done-summary")

    # Each part is its own package; together they are exactly the single-package deck.
    per_part = [apkg_guids(f, tmp_path) for f in files]
    assert sum(len(g) for g in per_part) == len(set().union(*per_part))  # no note in two parts
    wanted = expected_guids("us-ma", tier="everything", cards=ALL_CARDS)
    assert set().union(*per_part) == wanted

    got = import_and_check(tmp_path, files)  # all three into one collection
    assert got["guids"] == wanted
    assert got["notes"] == len(wanted)  # no duplicates


def test_unconstrained_device_gets_one_package(new_context, engine, base_url, tmp_path) -> None:
    page = open_app(new_context(engine), base_url, "?partSize=5")
    page.select_option("#region", label="Massachusetts")
    page.click("#advanced > summary")
    page.check('input[name="tier"][value="everything"]')
    assert not page.is_visible("#parts-hint")

    files = build(page, tmp_path, tier="everything", cards=ALL_CARDS)
    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    assert import_and_check(tmp_path, files)["guids"] == expected_guids("us-ma", tier="everything", cards=ALL_CARDS)


def test_parts_are_announced_before_the_first_one_is_built(new_context, base_url, tmp_path) -> None:
    context = new_context("chromium")
    context.add_init_script(CONSTRAINED)
    context.add_init_script(
        """
        window.__firstAnnounce = null;
        addEventListener('DOMContentLoaded', () => {
          const el = document.getElementById('parts-announce');
          new MutationObserver(() => {
            if (window.__firstAnnounce === null && !el.hidden) {
              window.__firstAnnounce = { text: el.textContent, downloads: document.querySelectorAll('#downloads li').length };
            }
          }).observe(el, { childList: true, attributes: true, characterData: true, subtree: true });
        });
        """
    )
    page = open_app(context, base_url, "?partSize=5")
    build(page, tmp_path, region="Massachusetts", tier="everything")
    first = page.evaluate("window.__firstAnnounce")
    assert first is not None
    assert re.search(r"big deck.*3 smaller files", first["text"])
    assert first["downloads"] == 0


def test_iphone_gets_parts_without_being_told_about_memory(new_context, base_url, tmp_path) -> None:
    context = new_context("webkit", device="iPhone 14")
    page = open_app(context, base_url, "?partSize=5")
    files = build(page, tmp_path, region="Massachusetts", tier="everything")
    assert [f.name for f in files] == [f"AviAnki-part-{i}-of-3.apkg" for i in (1, 2, 3)]
    assert import_and_check(tmp_path, files)["guids"] == expected_guids("us-ma", tier="everything")


def test_out_of_memory_switches_the_next_attempt_to_parts(new_context, engine, base_url, tmp_path) -> None:
    context = new_context(engine)
    # The first media response we read runs out of memory, the way a low-memory phone does.
    context.add_init_script(
        """
        (() => {
          const original = Response.prototype.arrayBuffer;
          let failed = false;
          Response.prototype.arrayBuffer = function () {
            if (!failed && this.url.includes('/media/')) {
              failed = true;
              return Promise.reject(new RangeError('Array buffer allocation failed'));
            }
            return original.call(this);
          };
        })();
        """
    )
    page = open_app(context, base_url)
    files = build(page, tmp_path, region="Massachusetts")

    assert [f.name for f in files] == ["AviAnki-part-1-of-2.apkg", "AviAnki-part-2-of-2.apkg"]
    assert "ran out of memory" in (page.text_content("#parts-announce") or "")
    got = import_and_check(tmp_path, files)
    assert got["guids"] == expected_guids("us-ma")
    assert got["notes"] == len(expected_guids("us-ma"))
