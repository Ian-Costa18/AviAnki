#!/usr/bin/env python3
"""Assemble the GitHub Pages tree from a built catalog (spec §4 step 7, ADR 0003, ADR 0013, ADR 0029).

Layout written under SITE_DIR:

    catalog/        the catalog directory's contents (manifest.json, species.*.json,
                    regions/, provenance.*.json, media/, credits.html)
    index.html      web/index.html at the root, its local stylesheet and script URLs rewritten
                    to v/<version>/..., or a stub index.html until the web app exists (M6)
    v/<version>/    every other file under web/ (css/, js/, vendor/) at the same relative paths
    .nojekyll       empty, so Pages serves the files as they are

Pages serves every file with cache-control max-age=600, so right after a deploy a browser can hold
the new index.html next to old modules. The app's own files therefore live in a per-deploy
directory (ADR 0029): its module imports and the fetches that resolve against import.meta.url all
land inside it, so a page and its files always come from the same deploy. The version is the
commit SHA from --version (shortened), or a hash of web/'s contents when none is given. Only
index.html stays at a fixed URL; it carries the reload-once fallback for a stale copy of itself.
The catalog is not versioned: it already has content-addressed names (ADR 0013).

Refuses (exit 1) when CATALOG_DIR has no manifest.json, when SITE_DIR already holds
files, or when the assembled site would exceed 900 MB (ADR 0003 and 0014; the build's
own validation gate checks this too, this is the belt-and-braces guard).

Stdlib only, so workflows can run it without installing the project.

Usage:
    python scripts/assemble_site.py CATALOG_DIR SITE_DIR [--web-dir web] [--version SHA]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

# Same limit as avianki.catalog.validate.MAX_SITE_BYTES; not imported so this script
# stays stdlib-only. Pages' own cap is 1 GB.
MAX_SITE_BYTES = 900_000_000

SHORT_SHA_LENGTH = 10
VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")

# index.html's own tags that load the app's files, and the attribute that names each one.
_TAG_RE = re.compile(r"<(link|script)\b[^>]*>", re.IGNORECASE)
_URL_ATTRS = {"link": "href", "script": "src"}

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


def content_version(web_dir: Path) -> str:
    """A short hash of the web app's files (paths and bytes): the version when no commit is given."""
    digest = hashlib.sha256()
    for path in sorted(p for p in web_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(web_dir).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:SHORT_SHA_LENGTH]


def normalise_version(version: str | None, web_dir: Path) -> str:
    """The directory name for this deploy: a full commit SHA shortened, anything else as given."""
    if not version:
        return content_version(web_dir)
    if re.fullmatch(r"[0-9a-fA-F]{40}", version):
        version = version[:SHORT_SHA_LENGTH]
    if not VERSION_RE.fullmatch(version):
        raise AssembleError(f"{version!r} is not a usable version; use letters, digits, '.', '_' and '-'")
    return version


def _is_local(url: str) -> bool:
    """A URL naming a file on this site: not empty, not a fragment, and with no scheme or host."""
    return bool(url) and not (re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url) or url.startswith(("//", "#")))


def version_index(html: str, version: str, web_dir: Path) -> str:
    """``html`` with every local stylesheet and script URL moved under ``v/<version>/``.

    Refuses a local URL that names nothing in ``web_dir``, and a root-absolute one (it would
    escape the version directory, and cannot work from a project site's sub-path anyway).
    """

    def rewrite_tag(tag_match: re.Match[str]) -> str:
        attr = _URL_ATTRS[tag_match.group(1).lower()]

        def rewrite_attr(m: re.Match[str]) -> str:
            url = m.group("url")
            if not _is_local(url):
                return m.group(0)
            if url.startswith("/"):
                raise AssembleError(f"index.html loads {url!r}; use a relative URL so it can be versioned")
            target = url.split("?", 1)[0].split("#", 1)[0].removeprefix("./")
            if not (web_dir / target).is_file():
                raise AssembleError(f"index.html loads {url!r}, which is not a file under {web_dir}")
            quote = m.group("quote")
            return f"{m.group('attr')}={quote}v/{version}/{target}{quote}"

        pattern = rf"(?P<attr>\b{attr})=(?P<quote>[\"'])(?P<url>[^\"']*)(?P=quote)"
        return re.sub(pattern, rewrite_attr, tag_match.group(0), flags=re.IGNORECASE)

    return _TAG_RE.sub(rewrite_tag, html)


def assemble(
    catalog_dir: Path,
    site_dir: Path,
    web_dir: Path,
    max_bytes: int = MAX_SITE_BYTES,
    version: str | None = None,
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
        if not (web_dir / "index.html").is_file():
            raise AssembleError(f"{web_dir} has no index.html")
        version = normalise_version(version, web_dir)
        original = (web_dir / "index.html").read_text(encoding="utf-8")
        index_html = version_index(original, version, web_dir)
        expected += tree_size(web_dir)[1] - len(original.encode("utf-8")) + len(index_html.encode("utf-8"))
    else:
        index_html = STUB_INDEX_HTML
        expected += len(STUB_INDEX_HTML.encode("utf-8"))
    if expected > max_bytes:
        raise AssembleError(
            f"the site would be {expected:,} bytes, over the {max_bytes:,} byte limit (ADR 0003)"
        )

    site_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(catalog_dir, site_dir / "catalog")
    if has_web:
        # index.html stays at the root (rewritten); everything else goes under the version.
        def skip_root_index(directory: str, names: list[str]) -> list[str]:
            return ["index.html"] if Path(directory) == web_dir else []

        shutil.copytree(web_dir, site_dir / "v" / str(version), ignore=skip_root_index)
    (site_dir / "index.html").write_text(index_html, encoding="utf-8")
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
    parser.add_argument(
        "--version",
        help="this deploy's id, normally the commit SHA (default: a hash of the web app's files)",
    )
    args = parser.parse_args(argv)

    try:
        count, total = assemble(args.catalog_dir, args.site_dir, args.web_dir, version=args.version)
    except AssembleError as e:
        print(f"assemble_site: {e}", file=sys.stderr)
        return 1
    print(f"Assembled {count} files, {total} bytes ({total / 1_000_000:.1f} MB) in {args.site_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
