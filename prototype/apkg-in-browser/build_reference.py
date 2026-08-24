"""PROTOTYPE — THROWAWAY. Builds the same deck with genanki, for comparison.

    uv run python prototype/apkg-in-browser/build_reference.py

Same catalog, same note types, same guids, same fixed timestamp as the browser
build, so any difference between the two files is a real difference.
"""

import hashlib
import json
import sys
from pathlib import Path

import genanki

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "src"))

from avianki import anki_model  # noqa: E402

DECK_SEED = "US-MA"
DECK_ID = int(hashlib.md5(DECK_SEED.encode()).hexdigest()[:8], 16)
DECK_NAME = "AviAnki – US-MA"
TIMESTAMP = 1700000000

manifest = json.loads((HERE / "catalog" / "manifest.json").read_text(encoding="utf-8"))
deck = genanki.Deck(DECK_ID, DECK_NAME)
media_files: list[str] = []

for sp in manifest:
    for m in sp["images"] + sp["audio"]:
        media_files.append(str(HERE / "catalog" / m["file"]))

    def img(i):
        return f'<img src="{sp["images"][i]["file"]}">' if i < len(sp["images"]) else ""

    def snd(i):
        return f'[sound:{sp["audio"][i]["file"]}]' if i < len(sp["audio"]) else ""

    credits = " · ".join(m.get("licence") or m.get("attribution") or ""
                         for m in sp["images"] + sp["audio"])
    desc = f'A {sp["name"]} is a bird. {credits}'
    fields = [sp["name"], sp["sciName"], img(0), img(1), snd(0), snd(1),
              desc, desc.replace(sp["name"], "<em>[redacted]</em>")]

    deck.add_note(genanki.Note(model=anki_model.PHOTO_MODEL, fields=fields,
                               guid=genanki.guid_for(DECK_SEED, sp["name"], "v1_photo")))
    deck.add_note(genanki.Note(model=anki_model.DESC_MODEL, fields=fields,
                               guid=genanki.guid_for(DECK_SEED, sp["name"], "v1_desc")))

pkg = genanki.Package(deck)
pkg.media_files = media_files
out = HERE / "reference-genanki.apkg"
pkg.write_to_file(str(out), timestamp=TIMESTAMP)
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB), deck id {DECK_ID}")
