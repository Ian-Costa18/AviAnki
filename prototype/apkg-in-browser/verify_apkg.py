"""PROTOTYPE — THROWAWAY. Imports a .apkg with Anki's own backend.

    ANKIPY=<venv python> python verify_apkg.py <file.apkg> [<second.apkg> ...]

This is not a lookalike parser — it is the same Rust import path the desktop
app runs when you double-click a deck, so "it imports clean here" means the
desktop app imports it clean. Each extra .apkg is imported into the *same*
collection afterwards, which is how the re-import / duplicate-deck question
gets answered.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from anki.collection import Collection
from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest


def summarise(col: Collection, label: str) -> dict:
    decks = [(d.id, d.name) for d in col.decks.all_names_and_ids()]
    notetypes = [(n.id, n.name) for n in col.models.all_names_and_ids()]
    stats = {
        "decks": decks,
        "notetypes": notetypes,
        "notes": col.note_count(),
        "cards": col.card_count(),
        "media": len(list((Path(col.path).parent / "collection.media").glob("*"))),
    }
    print(f"\n--- {label} ---")
    print(f"  decks      : {decks}")
    print(f"  notetypes  : {notetypes}")
    print(f"  notes      : {stats['notes']}   cards: {stats['cards']}")
    print(f"  media files: {stats['media']}")
    return stats


def main(paths: list[str]) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="avianki-verify-"))
    col = Collection(str(tmp / "collection.anki2"))
    try:
        for path in paths:
            print(f"\n=== importing {path} ({Path(path).stat().st_size / 1e6:.1f} MB) ===")
            resp = col.import_anki_package(
                ImportAnkiPackageRequest(
                    package_path=path,
                    options=ImportAnkiPackageOptions(
                        merge_notetypes=False, update_notes=0,
                        update_notetypes=0, with_scheduling=False,
                        with_deck_configs=False,
                    ),
                )
            )
            log = resp.log
            print(f"  new={len(log.new)} updated={len(log.updated)} "
                  f"duplicate={len(log.duplicate)} conflicting={len(log.conflicting)} "
                  f"first_field_match={len(log.first_field_match)}")
            if log.found_notes:
                print(f"  found_notes={log.found_notes}")
            summarise(col, f"collection after {Path(path).name}")

        # render every card through Anki's real template engine and report
        # anything that would show up broken
        print("\n=== rendering all cards through Anki's template engine ===")
        missing: list[str] = []
        media_dir = Path(col.path).parent / "collection.media"
        for cid in col.find_cards(""):
            card = col.get_card(cid)
            out = card.render_output()
            for side in (out.question_text, out.answer_text):
                for ref in col.media.files_in_str(card.note().mid, side):
                    if not (media_dir / ref).exists():
                        missing.append(f"{card.note().fields[0]}: {ref}")
            _ = out.question_av_tags, out.answer_av_tags
        print(f"  cards rendered : {len(col.find_cards(''))}")
        print(f"  missing media  : {len(missing)}")
        for m in missing[:10]:
            print("    ", m)

        print("\n=== anki's own media check ===")
        report = col.media.check()
        print(f"  missing: {len(report.missing)}  unused: {len(report.unused)}")
        for m in list(report.missing)[:10]:
            print("     missing:", m)

        print("\n=== db integrity check ===")
        print(" ", col.fix_integrity()[0].replace("\n", " | ")[:400])
    finally:
        col.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
