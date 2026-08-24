"""PROTOTYPE — THROWAWAY. What does Anki actually do with three [sound:] tags?

    <anki venv python> inspect_audio_card.py <file.apkg>

Renders the prototype's two randomiser variants through Anki's real template
engine and prints (a) the HTML the webview receives and (b) the av_tags list —
the autoplay queue, which is computed from the template output *before* any
template JS runs, and is therefore the thing JS cannot reach.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from anki.collection import Collection
from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

tmp = Path(tempfile.mkdtemp(prefix="avianki-audio-"))
col = Collection(str(tmp / "collection.anki2"))
try:
    col.import_anki_package(ImportAnkiPackageRequest(
        package_path=sys.argv[1],
        options=ImportAnkiPackageOptions(merge_notetypes=False, update_notes=0,
                                         update_notetypes=0, with_scheduling=False,
                                         with_deck_configs=False)))

    seen: set[tuple[int, int]] = set()
    for cid in col.find_cards('note:"PROTOTYPE*"'):
        card = col.get_card(cid)
        nt = card.note_type()
        key = (nt["id"], card.ord)
        if key in seen:
            continue
        seen.add(key)
        out = card.render_output()
        tmpl = nt["tmpls"][card.ord]["name"]
        print("=" * 72)
        print(f"template: {tmpl}   (note: {card.note().fields[0]})")
        print("-" * 72)
        print("QUESTION HTML AS THE WEBVIEW RECEIVES IT:")
        print(out.question_text)
        print("-" * 72)
        print(f"question av_tags (the autoplay queue): {len(out.question_av_tags)}")
        for t in out.question_av_tags:
            print("   ", t)
        print(f"answer av_tags: {len(out.answer_av_tags)}")
finally:
    col.close()
    shutil.rmtree(tmp, ignore_errors=True)
