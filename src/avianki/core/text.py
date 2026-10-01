"""Text keys for matching what people type against names: one fold for every lookup."""

from __future__ import annotations

import sys
import unicodedata


def strip_accents(text: str) -> str:
    """``"Québec"`` -> ``"Quebec"``: NFKD, then drop the combining marks."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Case-, accent- and whitespace-insensitive key: ``" Québec"`` -> ``"quebec"``."""
    return " ".join(strip_accents(text).casefold().split())


def use_utf8_output() -> None:
    """Make stdout and stderr write UTF-8 and never raise on a character they can't encode.

    A redirected stream on Windows uses the ANSI code page (cp1252), so a message with a
    region or file name such as ``鳥.apkg`` would crash with UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
