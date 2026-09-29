"""Tests for scripts/assemble_site.py, which builds the GitHub Pages tree from a catalog.

The script isn't a package (and is stdlib-only), so it's imported from its path.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "assemble_site.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("assemble_site", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assemble_site = _load()


def make_catalog(root: Path) -> Path:
    catalog = root / "catalog_in"
    (catalog / "media").mkdir(parents=True)
    (catalog / "regions").mkdir()
    (catalog / "manifest.json").write_text(json.dumps({"format": 1}), encoding="utf-8")
    (catalog / "species.abc.json").write_text("{}", encoding="utf-8")
    (catalog / "regions" / "us-ri.abc.json").write_text("{}", encoding="utf-8")
    (catalog / "credits.html").write_text("<p>credits</p>", encoding="utf-8")
    (catalog / "media" / "0123456789abcdef.webp").write_bytes(b"x" * 100)
    return catalog


def make_web(root: Path) -> Path:
    web = root / "web"
    (web / "js").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>real app</title>", encoding="utf-8")
    (web / "js" / "app.js").write_text("// app", encoding="utf-8")
    return web


def test_layout_with_web_dir(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    web = make_web(tmp_path)
    site = tmp_path / "_site"

    count, total = assemble_site.assemble(catalog, site, web)

    assert (site / "catalog" / "manifest.json").is_file()
    assert (site / "catalog" / "regions" / "us-ri.abc.json").is_file()
    assert (site / "catalog" / "media" / "0123456789abcdef.webp").read_bytes() == b"x" * 100
    assert (site / "catalog" / "credits.html").is_file()
    assert "real app" in (site / "index.html").read_text(encoding="utf-8")
    assert (site / "js" / "app.js").is_file()
    assert (site / ".nojekyll").read_bytes() == b""
    files = [p for p in site.rglob("*") if p.is_file()]
    assert count == len(files)
    assert total == sum(p.stat().st_size for p in files)


def test_stub_index_without_web_dir(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    site = tmp_path / "_site"

    assemble_site.assemble(catalog, site, tmp_path / "no-such-web")

    index = (site / "index.html").read_text(encoding="utf-8")
    assert index.lower().startswith("<!doctype html>")
    assert "AviAnki" in index
    assert (site / "catalog" / "manifest.json").is_file()
    assert (site / ".nojekyll").is_file()


def test_missing_manifest_is_refused(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    (catalog / "manifest.json").unlink()
    site = tmp_path / "_site"

    with pytest.raises(assemble_site.AssembleError, match="manifest.json"):
        assemble_site.assemble(catalog, site, tmp_path / "web")
    assert not site.exists()


def test_oversize_is_refused_before_copying(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    site = tmp_path / "_site"

    with pytest.raises(assemble_site.AssembleError, match="limit"):
        assemble_site.assemble(catalog, site, tmp_path / "web", max_bytes=50)
    assert not site.exists()


def test_size_at_the_limit_is_accepted(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    web = make_web(tmp_path)
    exact = assemble_site.tree_size(catalog)[1] + assemble_site.tree_size(web)[1]

    _, total = assemble_site.assemble(catalog, tmp_path / "_site", web, max_bytes=exact)
    assert total == exact


def test_the_limit_is_the_adr_900_mb() -> None:
    assert assemble_site.MAX_SITE_BYTES == 900_000_000


def test_non_empty_site_dir_is_refused(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    site = tmp_path / "_site"
    site.mkdir()
    (site / "old.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(assemble_site.AssembleError, match="not empty"):
        assemble_site.assemble(catalog, site, tmp_path / "web")
    assert (site / "old.txt").read_text(encoding="utf-8") == "keep me"


def test_web_catalog_directory_collision_is_refused(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    web = make_web(tmp_path)
    (web / "catalog").mkdir()

    with pytest.raises(assemble_site.AssembleError, match="collide"):
        assemble_site.assemble(catalog, tmp_path / "_site", web)


def test_command_line_reports_counts_and_exit_codes(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    site = tmp_path / "_site"
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), str(catalog), str(site), "--web-dir", str(tmp_path / "web")],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    assert "Assembled" in ok.stdout and "files" in ok.stdout and "bytes" in ok.stdout

    (catalog / "manifest.json").unlink()
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), str(catalog), str(tmp_path / "_site2")], capture_output=True, text=True
    )
    assert bad.returncode == 1
    assert "manifest.json" in bad.stderr
