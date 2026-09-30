"""The page stays small (spec section 7): everything a first visit downloads, measured gzipped as GitHub
Pages serves it, is under 150 KB. Only the sql.js wasm is left out, as the spec says.
"""

from __future__ import annotations

import gzip

from web_support import WEB_DIR

BUDGET_BYTES = 150 * 1000


def _shell_files() -> list:
    files = [WEB_DIR / "index.html", *sorted((WEB_DIR / "css").rglob("*")), *sorted((WEB_DIR / "js").rglob("*")),
             *sorted((WEB_DIR / "vendor").glob("*.js"))]
    return [f for f in files if f.is_file()]


def test_the_shell_is_under_150_kb_gzipped() -> None:
    files = _shell_files()
    sizes = {f.relative_to(WEB_DIR).as_posix(): len(gzip.compress(f.read_bytes(), 9)) for f in files}
    total = sum(sizes.values())
    raw = sum(f.stat().st_size for f in files)
    print(f"\nshell size: {total / 1000:.1f} KB gzipped ({raw / 1000:.1f} KB raw) across {len(sizes)} files")
    for name, size in sorted(sizes.items(), key=lambda kv: -kv[1])[:5]:
        print(f"  {size / 1000:7.1f} KB  {name}")
    assert total < BUDGET_BYTES, f"web shell is {total} bytes gzipped; the budget is {BUDGET_BYTES}"


def test_the_budget_counts_the_files_that_matter() -> None:
    names = {f.relative_to(WEB_DIR).as_posix() for f in _shell_files()}
    assert {"index.html", "css/app.css", "js/app.js", "js/catalog.js", "js/lastmile.js", "js/parts.js",
            "vendor/sql-wasm.js", "vendor/fflate.js"} <= names
    assert not [n for n in names if n.endswith(".wasm")]
