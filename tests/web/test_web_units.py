"""Unit tests for the browser writer's pieces, each checked against the Python it mirrors:
md5, the GUID, Python-compatible JSON, HTML escaping, the description, and the media feed.
"""

from __future__ import annotations

import hashlib
import html
import json
import random
from dataclasses import replace

import genanki
import pytest
from deck_fakes import manifest

from avianki.deck.build import deck_id, package_media_name
from avianki.deck.credits import deck_description

# ---------------------------------------------------------------------------------------
# md5, the GUID and the ids
# ---------------------------------------------------------------------------------------


def test_md5_matches_hashlib_around_every_padding_boundary(page) -> None:
    rng = random.Random(7)
    lengths = [0, 1, 3, 55, 56, 57, 63, 64, 65, 119, 120, 121, 128, 1000, 4097]
    blobs = [[rng.randrange(256) for _ in range(n)] for n in lengths]
    got = page.evaluate(
        "async (blobs) => { const { md5Hex } = await import('/js/apkg/md5.js');"
        " return blobs.map((b) => md5Hex(Uint8Array.from(b))); }",
        blobs,
    )
    assert got == [hashlib.md5(bytes(b)).hexdigest() for b in blobs]


NAMES = ["AviAnki", "AviAnki::Massachusetts", "AviAnki::Québec", "AviAnki::東京", "", "a" * 200]


def test_stable_id_is_the_deck_id(page) -> None:
    got = page.evaluate(
        "async (names) => { const { deckId } = await import('/js/deck.js'); return names.map(deckId); }", NAMES
    )
    assert got == [deck_id(n) for n in NAMES]
    assert deck_id("AviAnki") == 2854063212  # frozen, ADR 0009


GUID_INPUTS = [
    ("turdus-migratorius", "photo"),
    ("cyanocitta-cristata", "audio"),
    ("x", "photo_audio"),
    ("übervogel-ñ", "photo"),
    ("", ""),
]


def test_note_guid_is_genanki_guid_for(page) -> None:
    got = page.evaluate(
        "async (pairs) => { const { noteGuid } = await import('/js/deck.js');"
        " return Promise.all(pairs.map(([s, c]) => noteGuid(s, c))); }",
        [list(p) for p in GUID_INPUTS],
    )
    assert got == [genanki.guid_for("avianki", s, c) for s, c in GUID_INPUTS]


def test_guid_for_takes_any_number_of_values(page) -> None:
    got = page.evaluate(
        "async () => { const { guidFor } = await import('/js/apkg/guid.js');"
        " return [await guidFor('a'), await guidFor('a', 'b', 3)]; }"
    )
    assert got == [genanki.guid_for("a"), genanki.guid_for("a", "b", 3)]


# ---------------------------------------------------------------------------------------
# Python-compatible JSON
# ---------------------------------------------------------------------------------------

JSON_VALUES = [
    None,
    True,
    False,
    0,
    -7,
    1425279151694,
    "",
    "plain",
    'quote " backslash \\ slash / ',
    "tab\t newline\n return\r formfeed\f backspace\b nul\x00 unit-sep\x1f del\x7f",
    "café ñ 東京    ",
    "astral \U0001f426 and \U0001d11e",
    [],
    [1, [2, [3, []]], {}],
    {},
    {"a": 1, "b": [True, None], "c": {"d": "é"}},
    {"z": 1, "a": 2, "m": {"y": 0, "b": 0}},  # insertion order, not sorted
]


def test_pyjson_equals_json_dumps(page) -> None:
    got = page.evaluate(
        "async (values) => { const { pyJson } = await import('/js/apkg/pyjson.js'); return values.map(pyJson); }",
        JSON_VALUES,
    )
    assert got == [json.dumps(v) for v in JSON_VALUES]


def test_pyjson_lone_surrogates_are_escaped_like_python(page) -> None:
    got = page.evaluate(
        "async () => { const { pyJson } = await import('/js/apkg/pyjson.js');"
        " return [pyJson(String.fromCharCode(0xd800)), pyJson('a' + String.fromCharCode(0xdc00) + 'b')]; }"
    )
    assert got == [json.dumps("\ud800"), json.dumps("a\udc00b")]


def test_pyjson_maps_keep_integer_like_keys_in_insertion_order(page) -> None:
    got = page.evaluate(
        "async () => { const { pyJson } = await import('/js/apkg/pyjson.js');"
        " return [pyJson(new Map([['717156105', 1], ['12', 2], ['3', 3]])),"
        "         pyJson({ '717156105': 1, '12': 2, '3': 3 })]; }"
    )
    assert got[0] == json.dumps({"717156105": 1, "12": 2, "3": 3})
    assert got[1] != got[0], "a plain object reorders integer-like keys, which is why the writer uses a Map"


def test_pyjson_refuses_floats_and_unsupported_values(page) -> None:
    got = page.evaluate(
        """
        async () => {
          const { pyJson } = await import('/js/apkg/pyjson.js');
          const attempt = (v) => { try { pyJson(v); return null; } catch (e) { return e.name; } };
          return [attempt(1.5), attempt(NaN), attempt(Infinity)];
        }
        """
    )
    assert got == ["TypeError"] * 3


# ---------------------------------------------------------------------------------------
# Escaping and names
# ---------------------------------------------------------------------------------------

TEXTS = ["plain", "A & B", "<b>bold</b>", 'say "hi"', "it's", "&amp; already", "Vögel & <Fische> \"'", ""]


def test_escapes_equal_html_escape(page) -> None:
    got = page.evaluate(
        "async (texts) => { const { escapeText, escapeAttr } = await import('/js/deck.js');"
        " return texts.map((t) => [escapeText(t), escapeAttr(t)]); }",
        TEXTS,
    )
    assert got == [[html.escape(t, quote=False), html.escape(t, quote=True)] for t in TEXTS]


def test_package_media_name_equals_python(page) -> None:
    files = ["media/ab12cd.webp", "media/9f.mp3", "flat.jpg", "a/b/c/deep.mp3"]
    got = page.evaluate(
        "async (files) => { const { packageMediaName } = await import('/js/deck.js'); return files.map(packageMediaName); }",
        files,
    )
    assert got == [package_media_name(f) for f in files]


# ---------------------------------------------------------------------------------------
# The description
# ---------------------------------------------------------------------------------------


def _description_manifests():
    tricky = replace(
        manifest(ioc=True),
        dataset_credits=[
            *manifest(ioc=True).dataset_credits,
            type(manifest().dataset_credits[0])(
                "Bird's \"data\" <set> & co", "CC-BY-SA-4.0", "https://example.org/?a=1&b=2", "cropped, it's <small>"
            ),
        ],
    )
    return [manifest(), manifest(ioc=True), replace(manifest(), dataset_credits=[]), tricky]


@pytest.mark.parametrize("ebird", [False, True])
def test_deck_description_equals_python(page, ebird) -> None:
    manifests = _description_manifests()
    got = page.evaluate(
        """
        async ({ manifests, ebird }) => {
          const { deckDescription, loadNotetypes } = await import('/js/deck.js');
          const notetypes = await loadNotetypes();
          return manifests.map((m) => deckDescription(m, { ebird, notetypes }));
        }
        """,
        {"manifests": [m.to_dict() for m in manifests], "ebird": ebird},
    )
    assert got == [deck_description(m, ebird=ebird) for m in manifests]


# ---------------------------------------------------------------------------------------
# orderedPrefetch: the bounded, in-order media feed
# ---------------------------------------------------------------------------------------


def test_prefetch_yields_in_order_whatever_order_downloads_finish(page) -> None:
    got = page.evaluate(
        """
        async () => {
          const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
          const items = Array.from({ length: 15 }, (_, i) => `f${i}`);
          const delay = (i) => (i * 7) % 5 * 8; // later items often finish first
          const fetchOne = async (f) => {
            await new Promise((r) => setTimeout(r, delay(Number(f.slice(1)))));
            return Uint8Array.of(Number(f.slice(1)));
          };
          const out = [];
          for await (const item of orderedPrefetch(items, fetchOne)) out.push([item.name, item.data[0]]);
          return out;
        }
        """
    )
    assert got == [[f"f{i}", i] for i in range(15)]


def test_prefetch_keeps_at_most_six_downloads_in_flight_and_uses_all_six(page) -> None:
    got = page.evaluate(
        """
        async () => {
          const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
          let inFlight = 0, peak = 0, started = 0;
          const fetchOne = async () => {
            started++; inFlight++; peak = Math.max(peak, inFlight);
            await new Promise((r) => setTimeout(r, 15));
            inFlight--;
            return new Uint8Array(1);
          };
          const startedWhileConsuming = [];
          let n = 0;
          for await (const _ of orderedPrefetch(Array.from({ length: 30 }, (_, i) => `f${i}`), fetchOne)) {
            n++;
            // downloads started ahead of what the consumer has taken: never more than the window
            startedWhileConsuming.push(started - n);
          }
          return { peak, n, ahead: Math.max(...startedWhileConsuming) };
        }
        """
    )
    assert got["n"] == 30
    assert got["peak"] == 6
    assert got["ahead"] <= 6


def test_prefetch_concurrency_is_configurable(page) -> None:
    peak = page.evaluate(
        """
        async () => {
          const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
          let inFlight = 0, peak = 0;
          const fetchOne = async () => {
            inFlight++; peak = Math.max(peak, inFlight);
            await new Promise((r) => setTimeout(r, 5));
            inFlight--;
            return new Uint8Array(1);
          };
          for await (const _ of orderedPrefetch(Array.from({ length: 12 }, (_, i) => `f${i}`), fetchOne, { concurrency: 2 }));
          return peak;
        }
        """
    )
    assert peak == 2


def test_prefetch_edge_cases(page) -> None:
    got = page.evaluate(
        """
        async () => {
          const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
          const collect = async (it) => { const out = []; for await (const x of it) out.push(x.name); return out; };
          const fewer = await collect(orderedPrefetch(['a', 'b'], async () => new Uint8Array(1))); // < concurrency
          const none = await collect(orderedPrefetch([], async () => new Uint8Array(1)));
          const bad = [];
          for (const concurrency of [0, -1, NaN]) {
            try { await collect(orderedPrefetch(['a'], async () => new Uint8Array(1), { concurrency })); bad.push(null); }
            catch (e) { bad.push(e.name); }
          }
          const sync = await collect(orderedPrefetch(['a'], () => new Uint8Array(1))); // a non-async fetcher
          return { fewer, none, bad, sync };
        }
        """
    )
    assert got == {"fewer": ["a", "b"], "none": [], "bad": ["RangeError"] * 3, "sync": ["a"]}


def test_prefetch_reports_a_failure_at_its_turn_and_cancels_the_rest(page) -> None:
    got = page.evaluate(
        """
        async () => {
          const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
          const aborted = [];
          const fetchOne = (f, signal) => new Promise((resolve, reject) => {
            signal.addEventListener('abort', () => aborted.push(f));
            if (f === 'f2') setTimeout(() => reject(new Error('boom')), 5);
            else if (Number(f.slice(1)) < 2) setTimeout(() => resolve(new Uint8Array(1)), 1);
            // everything else never finishes on its own
          });
          const seen = [];
          let error = null;
          try {
            for await (const item of orderedPrefetch(Array.from({ length: 9 }, (_, i) => `f${i}`), fetchOne)) seen.push(item.name);
          } catch (e) { error = e.message; }
          return { seen, error, aborted: aborted.length > 0 };
        }
        """
    )
    assert got == {"seen": ["f0", "f1"], "error": "boom", "aborted": True}


def test_prefetch_aborts_in_flight_downloads_when_the_consumer_stops(page) -> None:
    got = page.evaluate(
        """
        async () => {
          const { orderedPrefetch } = await import('/js/apkg/prefetch.js');
          let aborts = 0;
          const fetchOne = (f, signal) => new Promise((resolve) => {
            signal.addEventListener('abort', () => aborts++);
            setTimeout(() => resolve(new Uint8Array(1)), 3);
          });
          for await (const item of orderedPrefetch(Array.from({ length: 20 }, (_, i) => `f${i}`), fetchOne)) break;
          return aborts > 0;
        }
        """
    )
    assert got is True


# ---------------------------------------------------------------------------------------
# buildDeck: media feed misuse and small inputs
# ---------------------------------------------------------------------------------------

BUILD_HELPERS = """
async function setup(cards = ['photo', 'audio']) {
  const { selectSpecies, planNotes } = await import('/js/select.js');
  const { buildDeck, mediaFiles } = await import('/js/deck.js');
  const json = async (p) => (await fetch('/catalog/' + p)).json();
  const manifest = await json('manifest.json');
  const region = await json(manifest.regions.find((r) => r.slug === 'us-ma').file);
  const speciesFile = await json(manifest.species_file);
  const ids = selectSpecies(region, speciesFile, cards, { tier: 'standard', month: null }).slice(0, 3);
  const notes = planNotes(ids, speciesFile, cards);
  const files = mediaFiles(notes);
  const data = (name) => ({ name, data: Uint8Array.of(1, 2, 3) });
  const build = (media, extra = {}) =>
    buildDeck({ manifest, speciesFile, notes, media, timestamp: 1700000000, ...extra });
  return { build, files, data, notes, manifest, speciesFile, buildDeck };
}
const outcome = async (promise) => {
  try { const r = await promise; return { ok: true, summary: r.summary }; }
  catch (e) { return { ok: false, name: e.name, message: e.message }; }
};
"""


def _run(page, body: str):
    return page.evaluate("async () => {" + BUILD_HELPERS + body + "}")


def test_a_correct_feed_builds_in_every_shape(page) -> None:
    got = _run(
        page,
        """
        const { build, files, data } = await setup();
        const list = files.map(data);
        async function* gen() { for (const item of list) yield item; }
        return {
          count: files.length,
          array: (await outcome(build(list))).ok,             // a feed itself: a sync iterable
          generator: (await outcome(build(gen()))).ok,        // an async iterable
          fn: (await outcome(build(() => list))).ok,          // a function returning a feed
          asyncFn: (await outcome(build(async () => gen()))).ok,
          received: await (async () => { let got; await build((f) => { got = f; return f.map(data); }); return got; })() ,
        };
        """,
    )
    assert got["count"] > 0
    assert got["array"] and got["generator"] and got["fn"] and got["asyncFn"]
    assert got["received"] and all(f.startswith("media/") for f in got["received"])


def test_a_feed_that_breaks_the_contract_is_an_error(page) -> None:
    got = _run(
        page,
        """
        const { build, files, data } = await setup();
        const list = files.map(data);
        return {
          wrongName: await outcome(build([{ name: 'media/other.webp', data: new Uint8Array(1) }, ...list.slice(1)])),
          swapped: await outcome(build([list[1], list[0], ...list.slice(2)])),
          tooFew: await outcome(build(list.slice(0, -1))),
          tooMany: await outcome(build([...list, data('media/extra.webp')])),
          empty: await outcome(build([])),
          missing: await outcome(build(undefined)),
        };
        """,
    )
    assert all(not r["ok"] for r in got.values()), got
    assert "expected" in got["wrongName"]["message"]
    assert "expected" in got["swapped"]["message"]
    assert "ended after" in got["tooFew"]["message"]
    assert "more than" in got["tooMany"]["message"]
    assert got["missing"]["name"] == "TypeError"


def test_a_feed_that_fails_part_way_fails_the_build(page) -> None:
    got = _run(
        page,
        """
        const { build, files, data } = await setup();
        async function* gen() { yield data(files[0]); throw new Error('network down'); }
        return await outcome(build(gen()));
        """,
    )
    assert got["ok"] is False and got["message"] == "network down"


def test_a_deck_without_media_needs_no_feed_and_an_empty_deck_is_valid(page) -> None:
    got = _run(
        page,
        """
        const { build, notes, buildDeck, manifest, speciesFile } = await setup();
        const noMedia = notes.map((n) => ({ ...n, photo: null, audio: null }));
        const bare = await outcome(buildDeck({ manifest, speciesFile, notes: noMedia, timestamp: 1700000000 }));
        const empty = await buildDeck({ manifest, speciesFile, notes: [], timestamp: 1700000000 });
        const head = new Uint8Array(await empty.blob.slice(0, 4).arrayBuffer());
        return { bare, emptySummary: empty.summary, zipMagic: Array.from(head) };
        """,
    )
    assert got["bare"]["ok"] and got["bare"]["summary"]["mediaCount"] == 0
    assert got["emptySummary"]["noteCount"] == 0 and got["emptySummary"]["mediaCount"] == 0
    assert got["zipMagic"] == [0x50, 0x4B, 0x03, 0x04]


def test_build_deck_rejects_an_unknown_card_type(page) -> None:
    got = _run(
        page,
        """
        const { buildDeck, manifest, speciesFile, notes } = await setup();
        return await outcome(buildDeck({ manifest, speciesFile, notes: [{ ...notes[0], cardType: 'video' }] }));
        """,
    )
    assert got["ok"] is False and got["name"] == "RangeError"


def test_progress_is_reported(page) -> None:
    got = _run(
        page,
        """
        const { build, files, data, notes } = await setup();
        const events = [];
        await build(files.map(data), { onProgress: (e) => events.push(e) });
        const stages = [...new Set(events.map((e) => e.stage))];
        const last = events.filter((e) => e.stage === 'media').at(-1);
        return { stages, last, noteEvents: events.filter((e) => e.stage === 'notes').length, notes: notes.length };
        """,
    )
    assert got["stages"] == ["database", "notes", "media", "done"]
    assert got["last"]["done"] == got["last"]["total"]
    assert got["noteEvents"] == got["notes"]
