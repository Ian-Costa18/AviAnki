#!/usr/bin/env python3
"""Write a dummy Pages site shaped like the published catalog (M1 deploy spike, #39).

Fills SITE_DIR/catalog/media/ with random-byte files named like real catalog
media (first 16 hex chars of the content's sha256, ADR 0013), alternating
~45 KB ``.webp`` and ~100 KB ``.mp3`` until the target size is reached. Also
writes a stub manifest, a stub ``index.html`` and ``.nojekyll``.

Stdlib only, so the workflow can run it without installing the project.
M4 replaces this with ``avianki-catalog build``.

Usage:
    python scripts/dummy_catalog.py SITE_DIR [--megabytes 450] [--seed 0]
"""

import argparse
import datetime
import hashlib
import json
import random
from pathlib import Path

BASE_URL = "https://ian-costa18.github.io/AviAnki/catalog/"
MEGABYTE = 1_000_000
IMAGE_BYTES = 45_000
AUDIO_BYTES = 100_000
JITTER = 0.20

INDEX_HTML = """<!doctype html>
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


def write_media(media_dir: Path, target_bytes: int, rng: random.Random) -> list[Path]:
    """Write content-addressed random files until their total reaches target_bytes."""
    media_dir.mkdir(parents=True, exist_ok=True)
    for old in media_dir.iterdir():
        if old.is_file():
            old.unlink()

    written: list[Path] = []
    total = 0
    while total < target_bytes:
        is_image = len(written) % 2 == 0
        base, ext = (IMAGE_BYTES, "webp") if is_image else (AUDIO_BYTES, "mp3")
        size = round(base * rng.uniform(1 - JITTER, 1 + JITTER))
        data = rng.randbytes(size)
        path = media_dir / f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
        path.write_bytes(data)
        written.append(path)
        total += size
    return written


def build_site(site_dir: Path, megabytes: float, seed: int) -> tuple[int, int]:
    """Write the dummy site; return (media file count, media bytes)."""
    catalog = site_dir / "catalog"
    media = write_media(catalog / "media", round(megabytes * MEGABYTE), random.Random(seed))
    total_bytes = sum(p.stat().st_size for p in media)

    manifest = {
        "format": 1,
        "catalog_version": datetime.date.today().isoformat(),
        "base_url": BASE_URL,
        "regions": [],
        "dummy": True,
        "total_bytes": total_bytes,
    }
    (catalog / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (site_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    return len(media), total_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site_dir", type=Path, help="output directory (e.g. _site)")
    parser.add_argument(
        "--megabytes", type=float, default=450, help="media to generate, in MB of 10^6 bytes (default 450)"
    )
    parser.add_argument("--seed", type=int, default=0, help="RNG seed, for reproducible output (default 0)")
    args = parser.parse_args()

    count, total = build_site(args.site_dir, args.megabytes, args.seed)
    print(f"Wrote {count} media files, {total} bytes ({total / MEGABYTE:.1f} MB) to {args.site_dir}")


if __name__ == "__main__":
    main()
