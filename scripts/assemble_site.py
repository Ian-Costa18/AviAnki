#!/usr/bin/env python3
"""Assemble the GitHub Pages tree from a built catalog (spec §4 step 7, ADR 0003, ADR 0013).

Layout written under SITE_DIR:

    catalog/        the catalog directory's contents (manifest.json, species.*.json,
                    regions/, provenance.*.json, media/, credits.html)
    <web/ contents> at the root, or a stub index.html until the web app exists (M6)
    .nojekyll       empty, so Pages serves the files as they are

Refuses (exit 1) when CATALOG_DIR has no manifest.json, when SITE_DIR already holds
files, or when the assembled site would exceed 900 MB (ADR 0003 and 0014; the build's
own validation gate checks this too, this is the belt-and-braces guard).

Stdlib only, so workflows can run it without installing the project.

Usage:
    python scripts/assemble_site.py CATALOG_DIR SITE_DIR [--web-dir web]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Same limit as avianki.catalog.validate.MAX_SITE_BYTES; not imported so this script
# stays stdlib-only. Pages' own cap is 1 GB.
MAX_SITE_BYTES = 900_000_000

STUB_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AviAnki</title>
</head>
<body>
<h1>AviAnki &mdash; coming soon</h1>
</body>
</html>
"""


class AssembleError(Exception):
    """The site can't be assembled; the message says why."""


def tree_size(root: Path) -> tuple[int, int]:
    """(file count, total bytes) of the files under ``root``."""
    files = [p for p in root.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def assemble(
    catalog_dir: Path,
    site_dir: Path,
    web_dir: Path,
    max_bytes: int = MAX_SITE_BYTES,
) -> tuple[int, int]:
    """Write the Pages tree to ``site_dir``; return (file count, total bytes)."""
    if not (catalog_dir / "manifest.json").is_file():
        raise AssembleError(f"{catalog_dir} has no manifest.json; it is not a built catalog")
    if site_dir.exists() and any(site_dir.iterdir()):
        raise AssembleError(f"{site_dir} already exists and is not empty; refusing to overwrite it")
    if (web_dir / "catalog").exists():
        raise AssembleError(f"{web_dir}/catalog would collide with the published catalog directory")

    # Check the size of what is about to be copied first, so an oversize catalog fails
    # before it is duplicated onto the runner's disk.
    expected = tree_size(catalog_dir)[1]
    has_web = web_dir.is_dir()
    if has_web:
        expected += tree_size(web_dir)[1]
    else:
        expected += len(STUB_INDEX_HTML.encode("utf-8"))
    if expected > max_bytes:
        raise AssembleError(
            f"the site would be {expected:,} bytes, over the {max_bytes:,} byte limit (ADR 0003)"
        )

    site_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(catalog_dir, site_dir / "catalog")
    if has_web:
        shutil.copytree(web_dir, site_dir, dirs_exist_ok=True)
    else:
        (site_dir / "index.html").write_text(STUB_INDEX_HTML, encoding="utf-8")
    (site_dir / ".nojekyll").write_bytes(b"")

    count, total = tree_size(site_dir)
    if total > max_bytes:  # not reachable unless the sizes above were wrong; cheap to be sure
        raise AssembleError(f"the assembled site is {total:,} bytes, over the {max_bytes:,} byte limit")
    return count, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("catalog_dir", type=Path, help="a built catalog (e.g. build/site)")
    parser.add_argument("site_dir", type=Path, help="output directory (e.g. _site)")
    parser.add_argument(
        "--web-dir", type=Path, default=Path("web"), help="the web app to publish at the site root (default: web)"
    )
    args = parser.parse_args(argv)

    try:
        count, total = assemble(args.catalog_dir, args.site_dir, args.web_dir)
    except AssembleError as e:
        print(f"assemble_site: {e}", file=sys.stderr)
        return 1
    print(f"Assembled {count} files, {total} bytes ({total / 1_000_000:.1f} MB) in {args.site_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
