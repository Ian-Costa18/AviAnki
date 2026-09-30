"""Species and region identity (ADR 0008): the tables shipped in ``avianki/data/``."""

from __future__ import annotations

from pathlib import Path

# The tables live inside the package, so an installed wheel has them too (issue #51):
# src/avianki/taxonomy/__init__.py -> parents[1] is the avianki package directory.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
