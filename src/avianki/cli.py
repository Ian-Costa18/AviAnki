"""The ``avianki`` command: read the published catalog and write an Anki .apkg (ADR 0017).

    avianki us-ma                       # a catalog slug ...
    avianki "Massachusetts" --tier everything --cards photo,audio,photo-audio
    avianki --ebird US-MA-017           # any eBird region, for personal use

The default path needs no ffmpeg, API key or scraping: manifest -> region -> species ->
only the media the deck uses, then genanki. ``--ebird`` is the one escape hatch; its
upstream work (eBird, live media building) sits behind `avianki.catalog.adhoc`, the only
part of the pipeline this module may import (dependency rule, ADR 0018).

Exit codes: 0 done, 1 the network or the catalog failed (or nothing to write), 2 a usage
problem (unknown region, missing key, bad flag combination, missing tool).
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import tqdm
from dotenv import load_dotenv

from avianki.catalog.client import (
    AmbiguousRegion,
    CatalogClient,
    CatalogError,
    RegionNotFound,
    default_cache_dir,
)
from avianki.catalog.format import DEFAULT_BASE_URL, Manifest, RegionFile, SpeciesFile
from avianki.core.http import SourceError
from avianki.core.log import setup_logging, teardown_logging
from avianki.core.text import fold
from avianki.deck.build import (
    DECK_NAME,
    STANDARD_LIMIT,
    TIER_EVERYTHING,
    TIER_STANDARD,
    PlannedNote,
    plan_notes,
    select_species,
    write_deck,
)
from avianki.deck.credits import EBIRD_NOTICE
from avianki.deck.notetypes import CARD_TYPES

log = logging.getLogger("bird_deck")

EBIRD_KEY_VAR = "EBIRD_API_KEY"
EBIRD_KEY_URL = "https://ebird.org/api/keygen"
DEFAULT_CARDS = "photo,audio"


def _card_label(card_type: str) -> str:
    """The CLI spells the combined card type with a hyphen; note types use an underscore."""
    return card_type.replace("_", "-")


_CARD_SPELLINGS = {_card_label(ct): ct for ct in CARD_TYPES}

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

# regions.csv is read directly (not through avianki.taxonomy, which cli may not import) only
# to recognise an eBird code or a place name that the catalog does not have. It ships inside
# the package (issue #51); tests/cli pins that this is the same file as taxonomy.DATA_DIR.
REGIONS_CSV = Path(__file__).resolve().parent / "data" / "regions.csv"


# ---------------------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------------------


def _cards(text: str) -> list[str]:
    """``photo,audio,photo-audio`` -> card types, in the order given, without repeats."""
    chosen: list[str] = []
    for part in text.split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in _CARD_SPELLINGS:
            raise argparse.ArgumentTypeError(
                f"unknown card type {part.strip()!r}; choose from {', '.join(_CARD_SPELLINGS)}"
            )
        card_type = _CARD_SPELLINGS[key]
        if card_type not in chosen:
            chosen.append(card_type)
    if not chosen:
        raise argparse.ArgumentTypeError("give at least one card type")
    return chosen


def _month(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a month number (1-12)") from None
    if not 1 <= value <= 12:
        raise argparse.ArgumentTypeError(f"month must be 1-12, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="avianki",
        description="Build an Anki deck for learning the birds of a region by photo and by sound.",
        epilog=(
            "Examples:\n"
            "  avianki us-ma\n"
            '  avianki "Massachusetts" --tier everything --cards photo,audio,photo-audio\n'
            "  avianki us-az --month 5 --subdeck\n"
            "  avianki --ebird US-MA-017    (needs EBIRD_API_KEY; for personal use only)\n"
            "\n"
            "Then open the .apkg in Anki (double-click it, or File > Import)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "region",
        nargs="?",
        metavar="REGION",
        help="a catalog region: its slug (us-ma) or display name (Massachusetts). "
        "Required unless --ebird is given",
    )
    parser.add_argument(
        "--tier",
        choices=[TIER_STANDARD, TIER_EVERYTHING],
        default=TIER_STANDARD,
        help=f"standard: the {STANDARD_LIMIT} most common species; everything: all of them "
        "(default: standard)",
    )
    parser.add_argument(
        "--cards",
        type=_cards,
        default=_cards(DEFAULT_CARDS),
        metavar="TYPES",
        help=f"comma-separated card types: photo, audio, photo-audio (default: {DEFAULT_CARDS})",
    )
    parser.add_argument(
        "--month",
        type=_month,
        metavar="1-12",
        help="only species likely to be seen in this month (default: all year)",
    )
    parser.add_argument(
        "--subdeck",
        action="store_true",
        help="put the notes in a subdeck named after the region (AviAnki::<Region>)",
    )
    parser.add_argument(
        "--ebird",
        metavar="CODE",
        help="build from any eBird region code (US-MA, CA-QC, MX-ROO...) instead of the catalog. "
        f"Needs {EBIRD_KEY_VAR}. Species outside the catalog are built live (needs the "
        "avianki[catalog] extra, plus ffmpeg and avianki[verify] for audio). "
        "The deck is for personal use only",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="where to write the deck (default: AviAnki-<region>.apkg, or AviAnki-<CODE>.apkg "
        "with --ebird)",
    )
    parser.add_argument(
        "--catalog-url",
        default=DEFAULT_BASE_URL,
        metavar="URL_OR_DIR",
        help="where to read the catalog: a URL or a local directory (default: the published catalog)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        metavar="DIR",
        help="where downloaded catalog files are kept (default: your per-user cache directory)",
    )
    advanced = parser.add_argument_group("advanced")
    advanced.add_argument(
        "--deck-name",
        default=DECK_NAME,
        metavar="NAME",
        help=f"the deck's name (default: {DECK_NAME}). Changing it puts the notes into a "
        "different deck in Anki, so a later import will not update the notes you already have",
    )
    noise = parser.add_mutually_exclusive_group()
    noise.add_argument("-v", "--verbose", action="store_true", help="show debug output and tracebacks")
    noise.add_argument("-q", "--quiet", action="store_true", help="show only warnings and errors")
    return parser


# ---------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------


def _region_rows() -> list[dict[str, str]]:
    """Rows of the packaged regions.csv, or [] when unreadable (the hint is only a courtesy)."""
    try:
        with REGIONS_CSV.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _known_ebird_region(query: str) -> tuple[str, str] | None:
    """``(eBird code, display name)`` when ``query`` is the code, slug or name of a regions.csv row."""
    key = fold(query)
    for row in _region_rows():
        if key in (fold(row["ebird_code"]), fold(row["slug"]), fold(row["name"])):
            return row["ebird_code"], row["name"]
    return None


def _region_name_for_code(code: str) -> str:
    """The display name of an eBird code from regions.csv, else the code itself."""
    for row in _region_rows():
        if row["ebird_code"].upper() == code.upper():
            return row["name"]
    return code.upper()


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} bytes"


class _Bar:
    """A tqdm bar driven by ``progress(done, total)`` callbacks; silent when ``disable``."""

    def __init__(self, label: str, disable: bool) -> None:
        self._bar = tqdm.tqdm(total=0, desc=label, unit="file", disable=disable, leave=False)

    def __call__(self, done: int, total: int) -> None:
        self._bar.total = total
        self._bar.n = done
        self._bar.refresh()

    def close(self) -> None:
        self._bar.close()


def _fetch_media(client: CatalogClient, files: list[str], quiet: bool) -> dict[str, Path]:
    """Download the catalog files a deck needs (cached ones are free), with a progress bar."""
    bar = _Bar("Downloading media", disable=quiet or not files)
    try:
        return client.media_many(files, bar)
    finally:
        bar.close()


def _needed_files(notes: Sequence[PlannedNote]) -> list[str]:
    files: list[str] = []
    for note in notes:
        files.extend(ref.file for ref in (note.photo, note.audio) if ref is not None)
    return list(dict.fromkeys(files))


def _error(message: str) -> None:
    print(f"avianki: error: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------------------
# The two paths
# ---------------------------------------------------------------------------------------


def _report_missing_region(exc: RegionNotFound | AmbiguousRegion, query: str) -> None:
    _error(str(exc))
    known = _known_ebird_region(query)
    if isinstance(exc, RegionNotFound) and known is not None:
        code, name = known
        print(
            f"{name} ({code}) is an eBird region that this catalog does not cover. "
            f"You can still build it for personal use: avianki --ebird {code}",
            file=sys.stderr,
        )
    else:
        print(
            "For a place outside the catalog, use --ebird CODE with an eBird region code "
            "(for example US-MA-017).",
            file=sys.stderr,
        )


@dataclass(frozen=True)
class _Deck:
    """What either path hands to `_finish`: the planned notes and what writing them needs."""

    notes: list[PlannedNote]
    species: SpeciesFile
    manifest: Manifest
    out: Path
    subdeck: str | None
    selected: int  # species selected, including any left without cards
    extra_media: dict[str, Path] = field(default_factory=dict)  # files built live by --ebird


def _finish(deck: _Deck, client: CatalogClient, args: argparse.Namespace) -> int:
    """Fetch the catalog media, write the deck, print the summary."""
    notes, out, extra_media = deck.notes, deck.out, deck.extra_media
    catalog_files = [f for f in _needed_files(notes) if f not in extra_media]
    downloaded = _fetch_media(client, catalog_files, args.quiet)

    def media(name: str) -> Path:
        return extra_media[name] if name in extra_media else downloaded[name]

    summary = write_deck(
        notes,
        deck.species,
        deck.manifest,
        media=media,
        out=out,
        deck_name=args.deck_name,
        subdeck=deck.subdeck,
        ebird=args.ebird is not None,
    )
    if args.quiet:
        return EXIT_OK
    selected = deck.selected
    species_count = len({n.species_id for n in notes})
    by_type = ", ".join(
        f"{count} {_card_label(card_type)}"
        for card_type, count in summary.notes_by_type.items()
        if count
    )
    print(
        f"Wrote {out} ({_human_size(out.stat().st_size)}): {summary.note_count} notes ({by_type}) "
        f"for {species_count} species."
    )
    if species_count < selected:
        print(
            f"{selected - species_count} of the {selected} selected species have no media for the "
            "chosen card types, so they have no cards."
        )
    print(f"Next: open {out.name} in Anki (double-click it, or File > Import).")
    return EXIT_OK


def _catalog_deck(args: argparse.Namespace, client: CatalogClient) -> int:
    manifest = client.manifest()
    try:
        ref = client.find_region(args.region)
    except (RegionNotFound, AmbiguousRegion) as exc:
        _report_missing_region(exc, args.region)
        return EXIT_USAGE
    region = client.region(ref)
    species = client.species()
    ids = select_species(region, tier=args.tier, month=args.month)
    notes = plan_notes(ids, species, args.cards)
    if not notes:
        _error(
            f"nothing to write: none of the {len(ids)} selected species in {ref.name} has media "
            "for the chosen cards"
            + (f" in month {args.month}" if args.month else "")
            + "."
        )
        return EXIT_FAILED
    out = args.output or Path(f"AviAnki-{ref.slug}.apkg")
    subdeck = ref.name if args.subdeck else None
    return _finish(_Deck(notes, species, manifest, out, subdeck, selected=len(ids)), client, args)


def _ebird_deck(args: argparse.Namespace, client: CatalogClient) -> int:
    # Imported here: it pulls in the sources and, lazily, the pipeline. The default path
    # never needs them.
    from avianki.catalog.adhoc import AdhocUnavailable, InvalidRegionCode, build_ebird_species

    code = args.ebird.strip().upper()
    api_key = os.environ.get(EBIRD_KEY_VAR, "").strip()
    if not api_key:
        _error(
            f"--ebird needs an eBird API key in the {EBIRD_KEY_VAR} environment variable "
            f"(or a .env file). Get one free at {EBIRD_KEY_URL}."
        )
        return EXIT_USAGE

    manifest = client.manifest()  # the catalog still supplies names, media and credits it has
    species = client.species()
    bar = _Bar("Building species", disable=args.quiet)
    try:
        adhoc = build_ebird_species(
            code,
            api_key=api_key,
            catalog_species=species,
            cache_dir=client.cache_dir,
            limit=STANDARD_LIMIT if args.tier == TIER_STANDARD else None,
            progress=bar,
        )
    except (InvalidRegionCode, AdhocUnavailable) as exc:
        _error(str(exc))
        return EXIT_USAGE
    finally:
        bar.close()

    for line in adhoc.notes:
        print(f"avianki: warning: {line}", file=sys.stderr)
    for line in adhoc.skipped:
        log.info("skipped %s", line)
    if adhoc.unfinished:
        print(
            f"avianki: warning: a source failed for {len(adhoc.unfinished)} species "
            f"({', '.join(adhoc.unfinished[:5])}{'...' if len(adhoc.unfinished) > 5 else ''}); "
            "they may be missing media. Run again to retry.",
            file=sys.stderr,
        )

    merged = SpeciesFile({**species.entries, **adhoc.entries})
    region = RegionFile(code.lower(), [(sid, (0,) * 12) for sid in adhoc.species_ids])
    ids = select_species(region, tier=args.tier, month=None)
    notes = plan_notes(ids, merged, args.cards)
    if not notes:
        _error(f"nothing to write: none of the species eBird lists for {code} has media for the chosen cards.")
        return EXIT_FAILED
    out = args.output or Path(f"AviAnki-{code}.apkg")
    subdeck = _region_name_for_code(code) if args.subdeck else None
    deck = _Deck(notes, merged, manifest, out, subdeck, selected=len(ids), extra_media=adhoc.media)
    status = _finish(deck, client, args)
    print(EBIRD_NOTICE)  # always shown, even with -q: it is a licence condition
    return status


# ---------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()  # lets a .env file supply EBIRD_API_KEY
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.ebird is None and not args.region:
        parser.error("a REGION is required (a catalog slug such as us-ma), or use --ebird CODE")
    if args.ebird is not None and args.region:
        parser.error("give either REGION or --ebird CODE, not both")
    if args.ebird is not None and args.month is not None:
        parser.error("--month needs the catalog's monthly data and cannot be used with --ebird")

    setup_logging(None, args.verbose, args.quiet)
    try:
        cache_dir = args.cache_dir if args.cache_dir is not None else default_cache_dir()
        client = CatalogClient(args.catalog_url, cache_dir=cache_dir)
        return _ebird_deck(args, client) if args.ebird is not None else _catalog_deck(args, client)
    except (CatalogError, SourceError, OSError) as exc:
        _error(str(exc))
        if args.verbose:
            traceback.print_exc()
        else:
            print("(run again with -v for details)", file=sys.stderr)
        return EXIT_FAILED
    finally:
        teardown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
