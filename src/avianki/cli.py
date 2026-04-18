#!/usr/bin/env python3
"""
avianki.py — CLI entry point.

Scrapes images, audio, and descriptions from allaboutbirds.org and packages
everything into an Anki .apkg deck. Accepts three location formats:

Usage:
    avianki "https://www.allaboutbirds.org/guide/browse/..."
    avianki ChIJGzE9DS1l44kRoOhiASS_fHg   # Google Place ID
    avianki US-MA                           # eBird region code
    avianki US-MA --limit 40

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
import tempfile
import time
from pathlib import Path

import genanki
from dotenv import load_dotenv

from . import allaboutbirds, anki_model, ebird, media

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("bird_deck")
log.handlers.clear()  # avoid duplicate handlers if rerun in same Python session
log.setLevel(logging.DEBUG)
log.propagate = False

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_sh.setLevel(logging.INFO)
log.addHandler(_sh)



def _setup_logging(log_file: str, verbose: bool, quiet: bool) -> logging.FileHandler:
    fh = logging.FileHandler(log_file, encoding="utf-8", mode="w")
    fh.setFormatter(_fmt)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    if verbose:
        _sh.setLevel(logging.DEBUG)
    elif quiet:
        _sh.setLevel(logging.WARNING)
    return fh


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_name(com_name: str) -> str:
    """Filesystem-safe version of a common name for use in filenames."""
    return re.sub(r"[^A-Za-z0-9_]", "_", com_name)


def _pluralize(word: str) -> str:
    low = word.lower()
    if low.endswith("mouse"):
        return word[:-5] + "mice"
    if low.endswith("goose"):
        return word[:-5] + "geese"
    if low.endswith(("ch", "sh", "x", "s", "z")):
        return word + "es"
    return word + "s"


def _redact_name(desc: str, com_name: str) -> str:
    """Replace the bird's common name (and variants) with 'this/these bird(s)'."""
    parts = com_name.split()
    last = parts[-1]
    plural_full = _pluralize(com_name)
    plural_last = _pluralize(last)
    replacements: dict[str, str] = {
        com_name.lower(): "this bird",
        plural_full.lower(): "these birds",
        last.lower(): "this bird",
        plural_last.lower(): "these birds",
    }
    seen: set[str] = set()
    candidates: list[str] = []
    for c in [com_name, plural_full, last, plural_last]:
        if c.lower() not in seen:
            seen.add(c.lower())
            candidates.append(c)
    candidates.sort(key=len, reverse=True)
    pattern = r"\b(" + "|".join(re.escape(c) for c in candidates) + r")\b"

    def _replace(m: re.Match[str]) -> str:
        rep = replacements[m.group(0).lower()]
        return rep[0].upper() + rep[1:] if m.group(0)[0].isupper() else rep

    return re.sub(pattern, _replace, desc, flags=re.IGNORECASE)


def _get_audio(
    sounds: dict, kind: str, safe: str, media_dir: Path, no_cache: bool = False
) -> tuple[str, list[Path]]:
    """
    Download, trim, and cache one audio clip (call or song).
    Returns ([sound:file] field value, [absolute path]) tuple.
    """
    base = f"bird_{safe}_{kind}"
    if not no_cache:
        cached = media.find_cached_audio(media_dir, base)
        if cached:
            log.info("  ✓ %s (cached)", kind)
            return f"[sound:{cached}]", [media_dir / cached]

    urls = sounds.get(kind + "s", [])  # "calls" or "songs"
    if not urls:
        log.warning("  no %s audio found", kind)
        return "", []

    raw_path = media_dir / f"{base}_raw.mp3"
    out_file = f"{base}.mp3"
    out_path = media_dir / out_file

    if media.download_file(urls[0], raw_path) and media.trim_to_mp3(raw_path, out_path):
        raw_path.unlink()
        log.info("  ✓ %s  %.1f KB", kind, out_path.stat().st_size / 1024)
        return f"[sound:{out_file}]", [out_path]

    log.warning("  %s download/trim failed", kind)
    return "", []


def _get_images(
    img_urls: list[str], safe: str, media_dir: Path, no_cache: bool = False
) -> tuple[list[str], list[Path]]:
    """
    Download and cache up to 2 images.
    Returns (img_fields, media_paths) where img_fields are '<img src="...">' strings.
    """
    img_fields = []
    media_paths = []

    for idx, img_url in enumerate(img_urls, 1):
        ext = Path(img_url.split("?")[0]).suffix.lower() or ".jpg"
        img_base = f"bird_{safe}_img{idx}"
        cached = None if no_cache else media.find_cached_image(media_dir, img_base)
        if cached:
            log.info("  ✓ image %d (cached)", idx)
            img_fields.append(f'<img src="{cached}">')
            media_paths.append(media_dir / cached)
        else:
            img_file = img_base + ext
            img_path = media_dir / img_file
            if media.download_file(img_url, img_path):
                log.info("  ✓ image %d  %.1f KB", idx, img_path.stat().st_size / 1024)
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
        "-n", "--limit", type=int, default=None, help="Max number of species to include"
    )
    parser.add_argument(
        "-o", "--output", default=None, help="Output .apkg filename (default: auto-generated)"
    )
    parser.add_argument(
        "-d", "--deck-name", default=None, help="Override the deck name shown in Anki"
    )
    parser.add_argument(
        "-A", "--no-audio", action="store_true", help="Skip downloading audio clips"
    )
    parser.add_argument(
        "-I", "--no-images", action="store_true", help="Skip downloading images"
    )
    parser.add_argument(
        "-D", "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between requests (default: 0.5)",
    )
    parser.add_argument(
        "-w", "--work-dir",
        default=str(Path(tempfile.gettempdir()) / "avianki"),
        help="Directory for cached media and logs (default: <tmp>/avianki)",
    )
    parser.add_argument(
        "-m", "--media-dir",
        default=None,
        help="Directory for cached media files (default: <work-dir>/media)",
    )
    parser.add_argument(
        "-e", "--ephemeral",
        action="store_true",
        help="Use a temporary work dir and delete it after packaging (no persistent files)",
    )
    parser.add_argument(
        "-X", "--no-cache",
        action="store_true",
        help="Skip cache lookup and delete downloaded media after packaging",
    )
    parser.add_argument(
        "-l", "--log-file",
        default=None,
        help="Log file path (default: next to <media-dir> as avianki.log)",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="Show debug output")
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="Only show warnings and errors"
    )
    args = parser.parse_args()

    location = args.location
    if args.ephemeral:
        work_dir = Path(tempfile.mkdtemp(prefix="avianki_"))
    else:
        work_dir = Path(args.work_dir)
    media_dir = Path(args.media_dir) if args.media_dir else work_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    log_file = Path(args.log_file) if args.log_file else work_dir / "avianki.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = _setup_logging(str(log_file), args.verbose, args.quiet)

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
        deck_name = args.deck_name or f"Birds – {region}"
        deck_seed = region
    else:
        slugs = allaboutbirds.fetch_browse_species(location, limit=args.limit)
        names = {}  # resolved lazily from each overview page
        deck_name = args.deck_name or "Birds – Local"
        place_id_match = re.search(r"/loc/([^/]+)", location)
        deck_seed = place_id_match.group(1) if place_id_match else location

    if not slugs:
        log.error("No species found for: %s", location)
        sys.exit(1)

    deck_id = int(hashlib.md5(deck_seed.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, deck_name)
    all_media: list[Path] = []
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
            time.sleep(args.delay)
            continue

        if not sci:
            sci = overview.get("sciName", "")

        if not args.no_images:
            img_fields, img_paths = _get_images(
                overview["images"], safe, media_dir, no_cache=args.no_cache
            )
            all_media.extend(img_paths)
        else:
            img_fields = ["", ""]

        time.sleep(args.delay)

        if not args.no_audio:
            sounds = allaboutbirds.fetch_sounds(slug)
            call_field, call_paths = _get_audio(
                sounds, "call", safe, media_dir, no_cache=args.no_cache
            )
            all_media.extend(call_paths)
            time.sleep(args.delay)
            song_field, song_paths = _get_audio(
                sounds, "song", safe, media_dir, no_cache=args.no_cache
            )
            all_media.extend(song_paths)
            time.sleep(args.delay)
        else:
            call_field, song_field = "", ""

        desc = overview["desc"]
        note = genanki.Note(
            model=anki_model.MODEL,
            fields=[
                name,
                sci,
                img_fields[0],
                img_fields[1],
                call_field,
                song_field,
                desc,
                _redact_name(desc, name),
            ],
            guid=genanki.guid_for(deck_seed, name, "v1"),
        )
        deck.add_note(note)

    pkg = genanki.Package(deck)
    pkg.media_files = [str(p) for p in all_media]
    output = args.output or f"Birds_{re.sub(r'[^A-Za-z0-9_-]', '_', deck_seed)}.apkg"
    pkg.write_to_file(output)

    if args.ephemeral:
        shutil.rmtree(work_dir, ignore_errors=True)
    elif args.no_cache:
        for p in all_media:
            p.unlink(missing_ok=True)

    log.info("✅  Saved → %s", output)
    log.info(
        "    %d species, %d skipped, %d notes, %d media files",
        len(slugs),
        skipped,
        len(deck.notes),
        len(all_media),
    )
    log.info("    File > Import > %s", output)

    fh.close()
    log.removeHandler(fh)


if __name__ == "__main__":
    main()
