"""Species and region identity (ADR 0008): the checked-in tables under ``data/``."""

from __future__ import annotations

from pathlib import Path

# data/ sits at the repo root, outside the package, so this only resolves in a source
# checkout. Every loader also takes an explicit path.
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
