"""PROTOTYPE — THROWAWAY. Diffs two .apkg files where it actually matters.

    uv run python prototype/apkg-in-browser/compare_apkg.py browser.apkg reference.apkg

Byte-identity of the whole file is not the question — SQLite page layout and zip
ordering are free to differ. What has to match is everything Anki keys on when
it decides whether a re-import is the same deck: deck id, notetype ids, the
notetype JSON, and the note guids.
"""

import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


def load(path: str) -> dict:
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        z.extract("collection.anki2", tmp)
        media = json.loads(z.read("media"))
        sizes = {n: z.getinfo(n).file_size for n in names}
        compress = {z.getinfo(n).compress_type for n in names}
    con = sqlite3.connect(tmp / "collection.anki2")
    conf, models, decks, dconf = con.execute(
        "SELECT conf, models, decks, dconf FROM col").fetchone()
    notes = con.execute("SELECT guid, mid, flds, sfld, tags FROM notes ORDER BY guid").fetchall()
    cards = con.execute("SELECT nid, did, ord FROM cards ORDER BY nid, ord").fetchall()
    con.close()
    return {
        "zip_names": names, "media": media, "sizes": sizes, "compress": compress,
        "conf": conf, "models_raw": models, "decks_raw": decks, "dconf": dconf,
        "notes": notes, "cards": cards, "path": path,
    }


def report(a: dict, b: dict) -> None:
    def line(name, ok, extra=""):
        print(f"  {'MATCH   ' if ok else 'DIFFERS '} {name:<38} {extra}")

    print(f"\nA = {a['path']}\nB = {b['path']}\n")

    da, db = json.loads(a["decks_raw"]), json.loads(b["decks_raw"])
    ida = sorted(k for k in da if k != "1")
    idb = sorted(k for k in db if k != "1")
    line("deck ids", ida == idb, f"A={ida} B={idb}")
    line("deck names", [da[k]["name"] for k in ida] == [db[k]["name"] for k in idb],
         f"A={[da[k]['name'] for k in ida]}")
    line("decks JSON (byte-exact)", a["decks_raw"] == b["decks_raw"])

    ma, mb = json.loads(a["models_raw"]), json.loads(b["models_raw"])
    shared = sorted(set(ma) & set(mb))
    line("notetype ids", sorted(ma) == sorted(mb), f"A={sorted(ma)} B={sorted(mb)}")
    for mid in shared:
        for key in ("name", "css", "flds", "tmpls", "req", "sortf", "type",
                    "latexPre", "latexPost", "latexsvg", "vers", "tags"):
            line(f"notetype {mid} .{key}", ma[mid][key] == mb[mid][key])
    line("models JSON (byte-exact)", a["models_raw"] == b["models_raw"])
    line("conf blob (byte-exact)", a["conf"] == b["conf"])
    line("dconf blob (byte-exact)", a["dconf"] == b["dconf"])

    ga = {n[0] for n in a["notes"]}
    gb = {n[0] for n in b["notes"]}
    line("note guids", ga == gb, f"A only={sorted(ga - gb)[:3]} B only={sorted(gb - ga)[:3]}")
    common = ga & gb
    fa = {n[0]: n[2] for n in a["notes"] if n[0] in common}
    fb = {n[0]: n[2] for n in b["notes"] if n[0] in common}
    line("note field contents", fa == fb,
         f"{sum(1 for g in common if fa[g] != fb[g])} of {len(common)} differ")
    line("card count", len(a["cards"]) == len(b["cards"]),
         f"A={len(a['cards'])} B={len(b['cards'])}")

    line("media manifest (name set)", set(a["media"].values()) == set(b["media"].values()),
         f"A={len(a['media'])} B={len(b['media'])}")
    line("media manifest (index order)", a["media"] == b["media"])
    ca = {0: "STORE", 8: "DEFLATE"}
    print(f"  --       zip compression                    "
          f"A={[ca.get(c, c) for c in a['compress']]} B={[ca.get(c, c) for c in b['compress']]}")
    print(f"  --       collection.anki2 size              "
          f"A={a['sizes']['collection.anki2']:,} B={b['sizes']['collection.anki2']:,}")


if __name__ == "__main__":
    report(load(sys.argv[1]), load(sys.argv[2]))
