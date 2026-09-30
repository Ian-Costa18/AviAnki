"""Heap use while the browser writes a deck (ADR 0006's memory cap). Records, never asserts a limit.

Chromium's ``performance.memory.usedJSHeapSize`` (the fixture starts it with
``--enable-precise-memory-info``) before and after a build. Two builds:

* us-ma "everything" from the fixture catalog: the real path, but the fixture media are a few
  bytes each, so it says little about scale.
* a synthetic deck of many multi-megabyte media files fed one at a time, sampled while the
  build runs, to see that the heap follows one file at a time and not the package. Typed-array
  backing stores and Blob contents live outside the JS heap, so this number is the JS side only.

Run with ``-s`` to see the numbers. The tests assert only what must hold for the numbers to
mean anything: the build succeeded and the package has every file.
"""

from __future__ import annotations

from web_support import Spec, build_in_browser

MB = 1024 * 1024

SYNTHETIC = """
async ({ files, size }) => {
  const { buildDeck } = await import('/js/deck.js');
  const speciesFile = {};
  const region = [];
  for (let i = 0; i < files; i++) {
    speciesFile['bird-' + i] = { name: 'Bird ' + i, sci: 'Avis ' + i,
      photo: [{ file: 'media/p' + i + '.jpg', credit: 'c' }], audio: [] };
    region.push('bird-' + i);
  }
  const notes = region.map((id) => ({ speciesId: id, cardType: 'photo', photo: speciesFile[id].photo[0], audio: null }));
  const manifest = { dataset_credits: [] };
  let peak = 0;
  const sample = () => { if (performance.memory) peak = Math.max(peak, performance.memory.usedJSHeapSize); };
  async function* feed() {
    for (let i = 0; i < files; i++) {
      const data = new Uint8Array(size);
      data[0] = i & 255;
      sample();
      yield { name: 'media/p' + i + '.jpg', data };
    }
  }
  const before = performance.memory ? performance.memory.usedJSHeapSize : null;
  const { blob, summary } = await buildDeck({ manifest, speciesFile, notes, media: () => feed(), timestamp: 1700000000 });
  sample();
  const after = performance.memory ? performance.memory.usedJSHeapSize : null;
  return { before, after, peak, bytes: blob.size, mediaCount: summary.mediaCount };
}
"""


def test_heap_us_ma_everything(chromium_page) -> None:
    built = build_in_browser(chromium_page, Spec(tier="everything", cards=("photo", "audio", "photo_audio")))
    assert built.summary["mediaCount"] > 0
    assert built.heap_before is not None and built.heap_after is not None, "precise memory info is off"
    print(
        f"\nheap us-ma everything (fixture catalog): before={built.heap_before / MB:.1f} MB "
        f"after={built.heap_after / MB:.1f} MB package={built.summary['bytes']} bytes "
        f"notes={built.note_count} media={built.summary['mediaCount']}"
    )


def test_heap_with_many_large_media_files(chromium_page) -> None:
    files, size = 150, 2 * MB  # a 300 MB package
    out = chromium_page.evaluate(SYNTHETIC, {"files": files, "size": size})
    assert out["mediaCount"] == files
    assert out["bytes"] > files * size
    print(
        f"\nheap synthetic {files} x {size // MB} MB: before={out['before'] / MB:.1f} MB "
        f"peak={out['peak'] / MB:.1f} MB after={out['after'] / MB:.1f} MB package={out['bytes'] / MB:.0f} MB"
    )
