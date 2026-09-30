"""web/vendor/ is pinned: every file's sha256 is the one web/vendor/README.md records."""

from __future__ import annotations

import hashlib
import re

from web_support import WEB_DIR

VENDOR = WEB_DIR / "vendor"
ROW = re.compile(r"^\| `([^`]+)` \|.*\| `([0-9a-f]{64})` \|$", re.M)
FILES = ["sql-wasm.js", "sql-wasm.wasm", "fflate.js", "LICENSE.sql.js", "LICENSE.fflate"]


def test_every_vendored_file_matches_its_recorded_hash() -> None:
    recorded = dict(ROW.findall((VENDOR / "README.md").read_text(encoding="utf-8")))
    for name in FILES:
        assert name in recorded, f"{name} has no hash in web/vendor/README.md"
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == recorded[name], name


def test_nothing_else_is_vendored() -> None:
    assert sorted(p.name for p in VENDOR.iterdir()) == sorted([*FILES, "README.md"])
