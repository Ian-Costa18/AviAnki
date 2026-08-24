"""PROTOTYPE — THROWAWAY. Runs the randomiser cards in the real Anki desktop webview.

    <aqt venv python> drive_anki_desktop.py <file.apkg> [repeats]

Backend inspection (inspect_audio_card.py) can only say what HTML Anki hands the
webview. This drives the actual desktop app: it imports the package, opens each
of the prototype's two templates in the real reviewer, and reads back the
on-card diagnostic div — so what gets reported is what the card itself observed
about its own DOM, not what we predicted.

SILENT BY CONSTRUCTION. Two separate things would otherwise play out loud, and
both are stopped at the source rather than turned down:

  * `[sound:]` tags go to Anki's own player (mpv), outside the webview. The spy
    on `play_tags` records the queue and deliberately does NOT forward it — the
    queue contents are the evidence; hearing it adds nothing.
  * `<audio>` elements play inside the webview, so the page is muted via Qt's
    `setAudioMuted`.

Muting cannot weaken the autoplay finding: `play()` resolving and `paused=false`
are read back off the element either way. It could only ever make autoplay look
*easier* than it is, since browsers are more permissive about muted playback —
and the unmuted run has already been done, so that is not an open question.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

APKG = sys.argv[1]
REPEATS = int(sys.argv[2]) if len(sys.argv) > 2 else 6

BASE = Path(tempfile.mkdtemp(prefix="anki-base-"))
os.environ["ANKI_BASE"] = str(BASE)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")

import aqt  # noqa: E402
from aqt import gui_hooks  # noqa: E402
from anki.import_export_pb2 import (  # noqa: E402
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
)

RESULTS: list[str] = []
PLAYED: list[str] = []
OUT = Path(__file__).parent / "desktop-webview-result.txt"


def finish(reason: str) -> None:
    RESULTS.append(f"\n== {reason} ==")
    text = "\n".join(RESULTS)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    sys.stdout.flush()
    os._exit(0)


def silence() -> None:
    """Record the autoplay queue instead of playing it."""
    from aqt import sound

    def spy(tags):
        PLAYED.append("autoplay queue Anki would play: " + (", ".join(
            getattr(t, "filename", str(t)) for t in tags) or "(empty)"))
        # deliberately not forwarded — see module docstring

    sound.av_player.play_tags = spy


def run_when_ready() -> None:
    from aqt import mw
    from aqt.qt import QTimer

    silence()

    mw.col.import_anki_package(ImportAnkiPackageRequest(
        package_path=APKG,
        options=ImportAnkiPackageOptions(merge_notetypes=False, update_notes=0,
                                         update_notetypes=0, with_scheduling=False,
                                         with_deck_configs=False)))
    RESULTS.append(f"imported: {mw.col.note_count()} notes, {mw.col.card_count()} cards")

    cids = mw.col.find_cards('note:"PROTOTYPE*"')
    by_ord: dict[int, int] = {}
    for cid in cids:
        by_ord.setdefault(mw.col.get_card(cid).ord, cid)
    plan = [(o, by_ord[o], i) for o in sorted(by_ord) for i in range(REPEATS)]
    RESULTS.append(f"templates found: {sorted(by_ord)}; {REPEATS} renders each")

    # The reviewer only initialises its own state once Anki has entered review
    # mode; forcing a card in before that leaves _reps unset.
    mw.col.decks.select(mw.col.get_card(cids[0]).did)
    mw.moveToState("review")
    mw.reviewer.web.page().setAudioMuted(True)

    # never leave a GUI app running unattended
    QTimer.singleShot(30_000 + len(plan) * 5_000, lambda: finish("WATCHDOG TIMEOUT"))

    def step(n: int) -> None:
        if n >= len(plan):
            finish("DONE")
            return

        ord_, cid, rep = plan[n]
        card = mw.col.get_card(cid)
        tmpl = card.note_type()["tmpls"][ord_]["name"]
        played_before = len(PLAYED)

        mw.reviewer.card = card
        mw.reviewer._showQuestion()
        mw.reviewer.web.page().setAudioMuted(True)

        def collected(val, ord_=ord_, tmpl=tmpl, rep=rep, n=n,
                      played_before=played_before) -> None:
            queued = PLAYED[played_before:] or ["autoplay queue Anki would play: (nothing)"]
            RESULTS.append(f"\n--- template {ord_} [{tmpl}] render {rep + 1} ---\n"
                           + "\n".join(queued) + f"\n{val}")
            QTimer.singleShot(400, lambda: step(n + 1))

        def read() -> None:
            mw.reviewer.web.evalWithCallback(
                """(function(){
                     var d=document.getElementById('diag');
                     var a=document.querySelector('audio');
                     var extra = a ? ('\\n<audio> paused='+a.paused+' currentTime='+
                                      a.currentTime.toFixed(2)+' readyState='+a.readyState+
                                      ' src='+a.getAttribute('src')) : '\\nno <audio> element';
                     var btns=document.querySelectorAll('a.replay-button, .replay-button, a.soundLink');
                     return (d?d.textContent:'NO DIAG DIV') + extra +
                            '\\nreplay buttons in card: '+btns.length;
                   })()""",
                collected)

        # let Anki's own front-end substitute [anki:play:...] before reading
        QTimer.singleShot(1200, read)

    QTimer.singleShot(4000, lambda: step(0))


gui_hooks.main_window_did_init.append(run_when_ready)
try:
    aqt.run()
finally:
    shutil.rmtree(BASE, ignore_errors=True)
