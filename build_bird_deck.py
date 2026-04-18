#!/usr/bin/env python3
"""
build_bird_deck.py — CLI entry point.

Scrapes images, audio, and descriptions from allaboutbirds.org and packages
everything into an Anki .apkg deck. Accepts three location formats:

Usage:
    python build_bird_deck.py "https://www.allaboutbirds.org/guide/browse/..."
    python build_bird_deck.py ChIJGzE9DS1l44kRoOhiASS_fHg   # Google Place ID
    python build_bird_deck.py US-MA                           # eBird region code
    python build_bird_deck.py US-MA --limit 40

Output:
    Birds_<location>.apkg — import into Anki via File > Import
"""

import argparse
import hashlib
import logging
import os
import re
import shutil
import sys
import time

import genanki
from dotenv import load_dotenv

import allaboutbirds
import anki_model
import ebird
import media

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE = "build_bird_deck.log"
_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("bird_deck")
log.handlers.clear()  # avoid duplicate handlers if rerun in same Python session
log.setLevel(logging.DEBUG)
log.propagate = False

_fh = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w")
_fh.setFormatter(_fmt)
_fh.setLevel(logging.DEBUG)
log.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_sh.setLevel(logging.INFO)
log.addHandler(_sh)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_name(com_name: str) -> str:
    """Filesystem-safe version of a common name for use in filenames."""
    return re.sub(r"[^A-Za-z0-9_]", "_", com_name)


def _get_audio(
    sounds: dict, kind: str, safe: str, media_dir: str
) -> tuple[str, list[str]]:
    """
    Download, trim, and cache one audio clip (call or song).
    Returns ([sound:file] field value, [absolute path]) tuple.
    """
    base = f"bird_{safe}_{kind}"
    cached = media.find_cached_audio(media_dir, base)
    if cached:
        log.info("  ✓ %s (cached)", kind)
        return f"[sound:{cached}]", [os.path.join(media_dir, cached)]

    urls = sounds.get(kind + "s", [])  # "calls" or "songs"
    if not urls:
        log.warning("  no %s audio found", kind)
        return "", []

    raw_path = os.path.join(media_dir, f"{base}_raw.mp3")
    out_file = f"{base}.mp3"
    out_path = os.path.join(media_dir, out_file)

    if media.download_file(urls[0], raw_path) and media.trim_to_mp3(raw_path, out_path):
        os.remove(raw_path)
        log.info("  ✓ %s  %.1f KB", kind, os.path.getsize(out_path) / 1024)
        return f"[sound:{out_file}]", [out_path]

    log.warning("  %s download/trim failed", kind)
    return "", []


def _get_images(
    img_urls: list[str], safe: str, media_dir: str
) -> tuple[list[str], list[str]]:
    """
    Download and cache up to 2 images.
    Returns (img_fields, media_paths) where img_fields are '<img src="...">' strings.
    """
    img_fields = []
    media_paths = []

    for idx, img_url in enumerate(img_urls, 1):
        ext = os.path.splitext(img_url.split("?")[0])[1].lower() or ".jpg"
        img_base = f"bird_{safe}_img{idx}"
        cached = media.find_cached_image(media_dir, img_base)
        if cached:
            log.info("  ✓ image %d (cached)", idx)
            img_fields.append(f'<img src="{cached}">')
            media_paths.append(os.path.join(media_dir, cached))
        else:
            img_file = img_base + ext
            img_path = os.path.join(media_dir, img_file)
            if media.download_file(img_url, img_path):
                log.info("  ✓ image %d  %.1f KB", idx, os.path.getsize(img_path) / 1024)
                img_fields.append(f'<img src="{img_file}">')
                media_paths.append(img_path)
            time.sleep(0.5)

    while len(img_fields) < 2:
        img_fields.append("")

    return img_fields, media_paths


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an Anki bird ID deck from allaboutbirds.org",
        epilog=(
            "LOCATION can be:\n"
            "  - An allaboutbirds.org browse URL  (copy from your browser)\n"
            "  - A Google Place ID                (e.g. ChIJGzE9DS1l44kRoOhiASS_fHg)\n"
            "  - An eBird region code             (e.g. US-MA or US-MA-017)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "location", help="allaboutbirds.org URL, Google Place ID, or eBird region code"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max number of species to include"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Delete cached media before running"
    )
    args = parser.parse_args()

    location = args.location
    media_dir = "media"
    os.makedirs(media_dir, exist_ok=True)

    if args.clear_cache:
        shutil.rmtree(media_dir)
        os.makedirs(media_dir)
        log.info("Media cache cleared.")

    # Determine species source: allaboutbirds URL/place ID, or eBird region code
    use_ebird = re.match(r"^[A-Z]{2}(-[A-Z]{2}(-\d+)?)?$", location.upper())
    if use_ebird:
        region = location.upper()
        if not os.getenv("EBIRD_API_KEY"):
            log.error("EBIRD_API_KEY not set — add it to .env")
            sys.exit(1)
        raw = ebird.fetch_species(region, limit=args.limit)
        slugs = [allaboutbirds.species_slug(b["comName"]) for b in raw]
        names = {allaboutbirds.species_slug(b["comName"]): b for b in raw}
        deck_name = f"Birds – {region}"
        deck_seed = region
    else:
        slugs = allaboutbirds.fetch_browse_species(location, limit=args.limit)
        names = {}  # resolved lazily from each overview page
        deck_name = "Birds – Local"
        deck_seed = location

    if not slugs:
        log.error("No species found for: %s", location)
        sys.exit(1)

    deck_id = int(hashlib.md5(deck_seed.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, deck_name)
    all_media = []
    skipped = 0

    for slug in slugs:
        # Resolve common + scientific name
        if slug in names:
            name = names[slug]["comName"]
            sci = names[slug]["sciName"]
        else:
            resolved = allaboutbirds.slug_to_names(slug)
            name = resolved["comName"]
            sci = resolved["sciName"]

        safe = _safe_name(name)
        log.info("── %s ──", name)

        overview = allaboutbirds.fetch_overview(slug)
        if not overview["desc"] and not overview["images"]:
            log.warning("  no allaboutbirds page found — skipping")
            skipped += 1
            time.sleep(0.5)
            continue

        if not sci:
            sci = overview.get("sciName", "")

        img_fields, img_paths = _get_images(overview["images"], safe, media_dir)
        all_media.extend(img_paths)

        time.sleep(0.5)
        sounds = allaboutbirds.fetch_sounds(slug)

        call_field, call_paths = _get_audio(sounds, "call", safe, media_dir)
        all_media.extend(call_paths)
        time.sleep(0.5)

        song_field, song_paths = _get_audio(sounds, "song", safe, media_dir)
        all_media.extend(song_paths)
        time.sleep(0.5)

        note = genanki.Note(
            model=anki_model.MODEL,
            fields=[
                name,
                sci,
                img_fields[0],
                img_fields[1],
                call_field,
                song_field,
                overview["desc"],
            ],
            guid=genanki.guid_for(deck_seed, name, "v1"),
        )
        deck.add_note(note)

    pkg = genanki.Package(deck)
    pkg.media_files = all_media
    output = f"Birds_{re.sub(r'[^A-Za-z0-9]', '_', deck_seed[:30])}.apkg"
    pkg.write_to_file(output)

    log.info("✅  Saved → %s", output)
    log.info(
        "    %d species, %d skipped, %d notes, %d media files",
        len(slugs),
        skipped,
        len(deck.notes),
        len(all_media),
    )
    log.info("    File > Import > %s", output)

    _fh.close()
    log.removeHandler(_fh)


if __name__ == "__main__":
    main()
