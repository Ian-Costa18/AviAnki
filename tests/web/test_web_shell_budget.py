"""The page's own code stays small (spec section 7): the HTML, the CSS and every script the app wrote,
under 150 KB together. The vendored libraries (sql.js and its wasm, fflate) are not counted.
"""

from __future__ import annotations

from web_support import WEB_DIR

BUDGET_BYTES = 150 * 1000


def _shell_files() -> list:
    files = [WEB_DIR / "index.html", *sorted((WEB_DIR / "css").rglob("*")), *sorted((WEB_DIR / "js").rglob("*"))]
    return [f for f in files if f.is_file()]


def test_the_shell_is_under_150_kb() -> None:
    files = _shell_files()
    sizes = {f.relative_to(WEB_DIR).as_posix(): f.stat().st_size for f in files}
    total = sum(sizes.values())
    print(f"\nshell size: {total / 1000:.1f} KB across {len(sizes)} files")
    for name, size in sorted(sizes.items(), key=lambda kv: -kv[1])[:5]:
        print(f"  {size / 1000:7.1f} KB  {name}")
    assert total < BUDGET_BYTES, f"web shell is {total} bytes; the budget is {BUDGET_BYTES}"


def test_the_budget_counts_the_files_that_matter() -> None:
    names = {f.relative_to(WEB_DIR).as_posix() for f in _shell_files()}
    assert {"index.html", "css/app.css", "js/app.js", "js/catalog.js", "js/lastmile.js", "js/parts.js"} <= names
    assert not [n for n in names if n.startswith("vendor/")]
