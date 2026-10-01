"""The identity tables ship in the wheel (issue #51).

``taxonomy.DATA_DIR`` is ``<package>/data``, so an installed avianki finds species.csv,
regions.csv and pins.toml without a source checkout. This builds the real wheel and checks
what is inside it.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILES = ("species.csv", "regions.csv", "pins.toml")


def test_data_dir_is_inside_the_package() -> None:
    from avianki.taxonomy import DATA_DIR

    assert DATA_DIR.parent.name == "avianki"
    for name in DATA_FILES:
        assert (DATA_DIR / name).is_file(), name


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to build the wheel")
def test_built_wheel_contains_the_data_tables(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(REPO_ROOT)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    (wheel,) = out.glob("avianki-*.whl")
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        for name in DATA_FILES:
            assert f"avianki/data/{name}" in names, f"{name} missing from {wheel.name}"
        # The wheel carries the checked-in tables, not something stale.
        for name in ("species.csv", "regions.csv"):
            packaged = zf.read(f"avianki/data/{name}").replace(b"\r\n", b"\n")
            checked_in = (REPO_ROOT / "src" / "avianki" / "data" / name).read_bytes().replace(b"\r\n", b"\n")
            assert packaged == checked_in
        # The card CSS (base, layout, theme template and each theme's extra rules) is read at import time.
        deck = REPO_ROOT / "src" / "avianki" / "deck"
        for css in [*deck.glob("*.css"), *(deck / "themes").glob("*.css")]:
            member = f"avianki/deck/{css.relative_to(deck).as_posix()}"
            assert member in names, f"{member} missing from {wheel.name}"
