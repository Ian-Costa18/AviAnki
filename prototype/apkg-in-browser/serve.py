"""PROTOTYPE — THROWAWAY. One command to run the prototype.

    uv run python prototype/apkg-in-browser/serve.py

Serves the prototype dir on http://localhost:8777 (localhost counts as a secure
context, which `crypto.subtle` requires). Before serving it exports the *real*
note-type definitions out of `avianki.anki_model` to `model.generated.json`, so
the browser is fed exactly what the CLI uses and transcription drift cannot be
mistaken for a real difference.
"""

import functools
import http.server
import json
import shutil
import socketserver
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from avianki import anki_model  # noqa: E402

PORT = 8777


def dump_models() -> None:
    shutil.copyfile(ROOT / "src" / "avianki" / "card.css", HERE / "card.css")
    out = []
    for model in (anki_model.PHOTO_MODEL, anki_model.DESC_MODEL):
        out.append({
            "id": model.model_id,
            "name": model.name,
            "css": model.css,
            "fields": [{"name": f["name"]} for f in model.fields],
            "templates": [
                {"name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]}
                for t in model.templates
            ],
        })
    (HERE / "model.generated.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print(f"exported {len(out)} note types from avianki.anki_model")


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # never cache — the whole point is editing and reloading
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    dump_models()
    handler = functools.partial(Handler, directory=str(HERE))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        url = f"http://localhost:{PORT}/"
        print(f"prototype on {url}  (ctrl-c to stop)")
        if "--no-open" not in sys.argv:
            webbrowser.open(url)
        httpd.serve_forever()
