"""Tests for scripts/dummy_catalog.py, the M1 Pages deploy spike data generator.

The script is exercised through its command line, the same way the workflow runs it.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "dummy_catalog.py"
MEDIA_NAME = re.compile(r"^[0-9a-f]{16}\.(webp|mp3)$")


def run_script(site: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(site), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def media_files(site: Path) -> list[Path]:
    media = site / "catalog" / "media"
    return sorted(media.iterdir()) if media.exists() else []


def test_zero_megabytes_writes_stub_site_without_media(tmp_path: Path) -> None:
    site = tmp_path / "_site"
    run_script(site, "--megabytes", "0")

    assert media_files(site) == []
    assert (site / ".nojekyll").exists()

    index = (site / "index.html").read_text(encoding="utf-8")
    assert index.lower().startswith("<!doctype html>")
    assert "AviAnki" in index and "coming soon" in index

    manifest = json.loads((site / "catalog" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", manifest["catalog_version"])
    assert manifest["base_url"] == "https://ian-costa18.github.io/AviAnki/catalog/"
    assert manifest["regions"] == []
    assert manifest["dummy"] is True
    assert manifest["total_bytes"] == 0


def test_media_is_content_addressed_and_close_to_target(tmp_path: Path) -> None:
    site = tmp_path / "_site"
    result = run_script(site, "--megabytes", "2", "--seed", "1")

    files = media_files(site)
    assert files, "expected media files"
    for f in files:
        assert MEDIA_NAME.match(f.name), f.name
        assert hashlib.sha256(f.read_bytes()).hexdigest()[:16] == f.stem

    total = sum(f.stat().st_size for f in files)
    target = 2 * 1_000_000
    assert abs(total - target) <= target * 0.10

    manifest = json.loads((site / "catalog" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_bytes"] == total

    assert {f.suffix for f in files} == {".webp", ".mp3"}
    assert str(len(files)) in result.stdout and str(total) in result.stdout


def test_same_seed_reproduces_same_files(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    run_script(a, "--megabytes", "1", "--seed", "7")
    run_script(b, "--megabytes", "1", "--seed", "7")

    assert [f.name for f in media_files(a)] == [f.name for f in media_files(b)]
