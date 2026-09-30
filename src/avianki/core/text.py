"""Text keys for matching what people type against names: one fold for every lookup."""

from __future__ import annotations

import unicodedata


def strip_accents(text: str) -> str:
    """``"Québec"`` -> ``"Quebec"``: NFKD, then drop the combining marks."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Case-, accent- and whitespace-insensitive key: ``" Québec"`` -> ``"quebec"``."""
    return " ".join(strip_accents(text).casefold().split())
