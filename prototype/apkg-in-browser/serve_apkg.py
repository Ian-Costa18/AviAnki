"""PROTOTYPE — THROWAWAY. Hands a .apkg to a phone on the same network.

    uv run --with qrcode python prototype/apkg-in-browser/serve_apkg.py <file.apkg> [port]

Binds to every interface (not just localhost) and prints a LAN URL plus a QR
code. Open it in Chrome on the phone, download, then open the file — AnkiDroid
registers for the .apkg extension and the `application/vnd.anki` type, both of
which are served here.

`qrcode` is optional; without it you just get the URL.
"""

import http.server
import socket
import socketserver
import sys
from pathlib import Path

APKG = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8778

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AviAnki prototype deck</title>
<style>
 body {{ font: 17px/1.6 system-ui, sans-serif; margin: 0; padding: 1.5rem;
        max-width: 34rem; color: #1a1a1a; background: #fafaf7; }}
 h1 {{ font-size: 1.25rem; }}
 a.dl {{ display: block; text-align: center; background: #2c5f2e; color: #fff;
        text-decoration: none; padding: 1rem; border-radius: 10px;
        font-size: 1.1rem; font-weight: 600; margin: 1.4rem 0; }}
 code {{ background: #e8e8e4; padding: .1em .35em; border-radius: 4px; }}
 li {{ margin-bottom: .5rem; }}
 .note {{ background: #ffe9b3; border: 1px solid #d9a800; padding: .7rem .9rem;
         border-radius: 8px; font-size: .95rem; }}
</style></head><body>
<h1>AviAnki prototype deck</h1>
<p class="note"><strong>Throwaway test deck</strong> for
<a href="https://github.com/Ian-Costa18/AviAnki/issues/18">issue #18</a> — built
by a browser, not by the CLI. Delete the deck afterwards.</p>

<a class="dl" href="/{name}">Download {name} ({size:.1f} MB)</a>

<p>Then open the downloaded file and pick AnkiDroid, or use
<em>AnkiDroid &rarr; menu &rarr; Import</em>.</p>

<h2 style="font-size:1.05rem">What to look at</h2>
<ol>
<li><strong>Does it import at all?</strong> Expect a deck
<code>AviAnki – US-MA</code> with 9 notes / 12 cards.</li>
<li><strong>The 3 real bird cards</strong> — do photos render and does audio play?</li>
<li><strong>The two <code>PROTOTYPE – Random audio</code> templates.</strong> Each one
prints on the card what it observed about its own DOM, so just read it off:
  <ul>
  <li><em>A · sound-tag</em> — should say <code>player nodes found: 3</code> and
  show one button. On desktop Anki plays all three anyway; the question is
  whether AnkiDroid does too.</li>
  <li><em>B · html-audio</em> — should say <code>play() resolved</code> and name
  one clip. If it says <code>AUDIO ERROR</code> or <code>play() rejected</code>,
  that is the clear negative worth reporting.</li>
  </ul>
  Bury and re-show the card a few times to see whether the choice changes.</li>
</ol>
</body></html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = PAGE.format(name=APKG.name, size=APKG.stat().st_size / 1e6).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/" + APKG.name:
            self.send_response(200)
            # AnkiDroid's intent filter matches this type and the .apkg suffix
            self.send_header("Content-Type", "application/vnd.anki")
            self.send_header("Content-Disposition", f'attachment; filename="{APKG.name}"')
            self.send_header("Content-Length", str(APKG.stat().st_size))
            self.end_headers()
            with APKG.open("rb") as fh:
                while chunk := fh.read(1 << 20):
                    self.wfile.write(chunk)
            print(f"  served {APKG.name} to {self.client_address[0]}")
            return

        self.send_error(404)

    def log_message(self, fmt, *args):
        pass


def lan_ip() -> str:
    """The address this machine uses to reach the world — i.e. the one the
    phone can reach, rather than a VM or WSL virtual adapter."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


if __name__ == "__main__":
    url = f"http://{lan_ip()}:{PORT}/"
    print(f"\nserving {APKG.name} ({APKG.stat().st_size / 1e6:.1f} MB)")
    print(f"\n    {url}\n")
    try:
        import qrcode

        # the block characters are not cp1252, which is still the console
        # default on Windows
        sys.stdout.reconfigure(encoding="utf-8")
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        print("  (install qrcode for a scannable code: uv run --with qrcode ...)\n")
    except Exception as exc:  # a QR is a nicety; never let it stop the serving
        print(f"  (no QR: {exc})\n")
    print("phone must be on the same Wi-Fi.  ctrl-c to stop.\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
