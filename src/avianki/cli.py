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
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import genanki
import tqdm as tqdm_module
from dotenv import load_dotenv
from avianki.redact import redact_name

from . import allaboutbirds, anki_model, ebird, media

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("bird_deck")
log.handlers.clear()  # avoid duplicate handlers if rerun in same Python session
log.setLevel(logging.DEBUG)
log.propagate = False


class _TqdmHandler(logging.StreamHandler):
    """Routes log output through tqdm.write() so progress bars aren't clobbered."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm_module.tqdm.write(self.format(record))
        except Exception:
            self.handleError(record)


_sh = _TqdmHandler(sys.stdout)
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
    img_urls: list[str], safe: str, media_dir: Path, no_cache: bool = False, delay: float = 0
) -> tuple[list[str], list[Path], bool]:
    """
    Download and cache up to 2 images.
    Returns (img_fields, media_paths, fetched) where fetched is True if any network request was made.
    """
    img_fields = []
    media_paths = []
    fetched = False

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
            fetched = True
            if delay:
                time.sleep(delay)

    while len(img_fields) < 2:
        img_fields.append("")

    return img_fields, media_paths, fetched


# ─── Main ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI args and apply AVIANKI_* env var fallbacks. CLI always wins."""
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
        "location", nargs="?", default=None,
        help="allaboutbirds.org URL, Google Place ID, or eBird region code (or set AVIANKI_LOCATION)",
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
        "-j", "--json-file",
        default=None,
        help="Path for birds.json output (default: <work-dir>/birds.json, use /dev/null to skip)",
    )
    parser.add_argument(
        "-D", "--delay",
        type=float,
        default=None,
        help="Seconds to wait between requests (default: 0)",
    )
    parser.add_argument(
        "-w", "--work-dir",
        default=None,
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
    args = parser.parse_args(argv)

    # ── Env-var fallbacks (CLI flags always take precedence) ──────────────────
    def _bool_env(key: str) -> bool:
        return os.environ.get(key, "").lower() in ("1", "true", "yes")

    if not args.location:
        args.location = os.environ.get("AVIANKI_LOCATION") or ""
    if not args.location:
        parser.error("LOCATION is required — pass as argument or set AVIANKI_LOCATION in .env")
    if args.limit is None and os.environ.get("AVIANKI_LIMIT"):
        args.limit = int(os.environ["AVIANKI_LIMIT"])
    if args.output is None:
        args.output = os.environ.get("AVIANKI_OUTPUT")
    if args.deck_name is None:
        args.deck_name = os.environ.get("AVIANKI_DECK_NAME")
    if args.delay is None:
        args.delay = float(os.environ.get("AVIANKI_DELAY") or "0")
    if args.work_dir is None:
        args.work_dir = os.environ.get("AVIANKI_WORK_DIR") or str(Path(tempfile.gettempdir()) / "avianki")
    if args.media_dir is None:
        args.media_dir = os.environ.get("AVIANKI_MEDIA_DIR")
    if args.json_file is None:
        args.json_file = os.environ.get("AVIANKI_JSON_FILE")
    if args.log_file is None:
        args.log_file = os.environ.get("AVIANKI_LOG_FILE")
    args.no_audio = args.no_audio or _bool_env("AVIANKI_NO_AUDIO")
    args.no_images = args.no_images or _bool_env("AVIANKI_NO_IMAGES")
    args.ephemeral = args.ephemeral or _bool_env("AVIANKI_EPHEMERAL")
    args.no_cache = args.no_cache or _bool_env("AVIANKI_NO_CACHE")
    if not args.verbose and not args.quiet:
        if _bool_env("AVIANKI_VERBOSE"):
            args.verbose = True
        elif _bool_env("AVIANKI_QUIET"):
            args.quiet = True

    return args


def main() -> None:
    args = _parse_args()
    location = args.location
    work_dir = Path(args.work_dir)
    if args.ephemeral:
        ephemeral_dir = work_dir / ".ephemeral"
        ephemeral_dir.mkdir(parents=True, exist_ok=True)
        media_dir = Path(args.media_dir) if args.media_dir else ephemeral_dir / "media"
    else:
        ephemeral_dir = None
        media_dir = Path(args.media_dir) if args.media_dir else work_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    default_dir = work_dir / ".ephemeral" if args.ephemeral else work_dir
    log_file = Path(args.log_file) if args.log_file else default_dir / "avianki.log"
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
        deck_name = args.deck_name or f"AviAnki – {region}"
        deck_seed = region
    else:
        slugs = allaboutbirds.fetch_browse_species(location, limit=args.limit)
        names = {}  # resolved lazily from each overview page
        deck_name = args.deck_name or "AviAnki – Local Birds"
        place_id_match = re.search(r"/loc/([^/]+)", location)
        deck_seed = place_id_match.group(1) if place_id_match else location

    if not slugs:
        log.error("No species found for: %s", location)
        sys.exit(1)

    deck_id = int(hashlib.md5(deck_seed.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, deck_name)
    all_media: list[Path] = []
    birds_data: list[dict] = []
    skipped = 0

    pbar = tqdm_module.tqdm(slugs, unit="bird", desc="Downloading", leave=True, disable=args.quiet)
    for slug in pbar:
        # Resolve common + scientific name
        if slug in names:
            name = names[slug]["comName"]
            sci = names[slug]["sciName"]
        else:
            resolved = allaboutbirds.slug_to_names(slug)
            name = resolved["comName"]
            sci = resolved["sciName"]

        safe = _safe_name(name)
        pbar.set_postfix_str(name)
        log.info("── %s ──", name)

        overview = allaboutbirds.fetch_overview(slug)
        if not overview["desc"] and not overview["images"]:
            log.warning("  no allaboutbirds page found — skipping")
            skipped += 1
            time.sleep(args.delay)
            continue

        if not sci:
            sci = overview.get("sciName", "")

        img_paths: list[Path] = []
        call_paths: list[Path] = []
        song_paths: list[Path] = []

        if not args.no_images:
            img_fields, img_paths, imgs_fetched = _get_images(
                overview["images"], safe, media_dir, no_cache=args.no_cache, delay=args.delay
            )
            all_media.extend(img_paths)
        else:
            imgs_fetched = False
            img_fields = ["", ""]

        # overview was always fetched (needed for desc); sleep once after it
        if args.delay and imgs_fetched:
            time.sleep(args.delay)

        if not args.no_audio:
            call_cached = not args.no_cache and bool(media.find_cached_audio(media_dir, f"bird_{safe}_call"))
            song_cached = not args.no_cache and bool(media.find_cached_audio(media_dir, f"bird_{safe}_song"))
            if not (call_cached and song_cached):
                sounds = allaboutbirds.fetch_sounds(slug)
                if args.delay:
                    time.sleep(args.delay)
            else:
                sounds = {"calls": [], "songs": []}
            call_field, call_paths = _get_audio(
                sounds, "call", safe, media_dir, no_cache=args.no_cache
            )
            all_media.extend(call_paths)
            song_field, song_paths = _get_audio(
                sounds, "song", safe, media_dir, no_cache=args.no_cache
            )
            all_media.extend(song_paths)
        else:
            call_field, song_field = "", ""

        desc = overview["desc"]
        note_fields = [
            name,
            sci,
            img_fields[0],
            img_fields[1],
            call_field,
            song_field,
            desc,
            redact_name(desc, name),
        ]
        deck.add_note(genanki.Note(
            model=anki_model.PHOTO_MODEL,
            fields=note_fields,
            guid=genanki.guid_for(deck_seed, name, "v1_photo"),
        ))
        deck.add_note(genanki.Note(
            model=anki_model.DESC_MODEL,
            fields=note_fields,
            guid=genanki.guid_for(deck_seed, name, "v1_desc"),
        ))
        birds_data.append({
            "name": name,
            "sci_name": sci,
            "description": desc,
            "images": [str(p.relative_to(media_dir)) for p in img_paths] if not args.no_images else [],
            "call": str(call_paths[0].relative_to(media_dir)) if call_paths else None,
            "song": str(song_paths[0].relative_to(media_dir)) if song_paths else None,
        })

    json_path = Path(args.json_file) if args.json_file else default_dir / "birds.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(birds_data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("    Birds data → %s", json_path)

    pkg = genanki.Package(deck)
    pkg.media_files = [str(p) for p in all_media]
    output = args.output or f"Birds_{re.sub(r'[^A-Za-z0-9_-]', '_', deck_seed)}.apkg"
    pkg.write_to_file(output)

    if args.ephemeral:
        if ephemeral_dir is None:
            raise RuntimeError("ephemeral_dir was not set despite --ephemeral flag")
        shutil.rmtree(ephemeral_dir, ignore_errors=True)
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
