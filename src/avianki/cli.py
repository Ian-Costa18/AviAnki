"""The ``avianki`` command: read the published catalog and write an Anki .apkg (ADR 0017).

    avianki us-ma                       # a catalog slug ...
    avianki "Massachusetts" --tier everything --cards photo,audio,photo-audio
    avianki --ebird US-MA-017           # any eBird region, for personal use

The default path needs no ffmpeg, API key or scraping: manifest -> region -> species ->
only the media the deck uses, then genanki. ``--ebird`` is the one escape hatch; its
upstream work (eBird, live media building) sits behind `avianki.catalog.adhoc`, the only
part of the pipeline this module may import (dependency rule, ADR 0018).

Exit codes: 0 done, 1 the network or the catalog failed (or nothing to write), 2 a usage
problem (unknown region, missing key, bad flag combination, an output path that can't be
written, missing tool), 130 cancelled with Ctrl-C.
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
from importlib import metadata
from pathlib import Path

import tqdm
from dotenv import find_dotenv, load_dotenv

from avianki.catalog.client import (
    AmbiguousRegion,
    CacheWriteError,
    CatalogClient,
    CatalogError,
    CatalogFetchError,
    MediaNotFound,
    RegionNotFound,
    default_cache_dir,
)
from avianki.catalog.format import DEFAULT_BASE_URL, Manifest, RegionFile, SpeciesFile
from avianki.core.http import SourceError
from avianki.core.log import setup_logging, teardown_logging
from avianki.core.text import fold, use_utf8_output
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
# The catalog keeps each region's top 400 species and "everything" is all of them (ADR 0015).
# This is documentation for --help; the selection itself reads the region file.
EVERYTHING_LIMIT = 400


def _card_label(card_type: str) -> str:
    """The CLI spells the combined card type with a hyphen; note types use an underscore."""
    return card_type.replace("_", "-")


_CARD_SPELLINGS = {_card_label(ct): ct for ct in CARD_TYPES}

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
EXIT_INTERRUPTED = 130  # the shell convention for Ctrl-C

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


def _path(text: str) -> Path:
    """A path argument, with ``~`` expanded (PowerShell and cmd pass it through literally)."""
    return Path(text).expanduser()


def _output_path(text: str) -> Path:
    if not text.strip():
        raise argparse.ArgumentTypeError("the output path is empty; give a file name such as deck.apkg")
    if text.endswith(("/", "\\")):
        # "out/" names a folder, and Path would silently drop the slash and make a file "out".
        raise argparse.ArgumentTypeError(f"{text!r} is a folder; give a file name such as {text}deck.apkg")
    return _path(text)


# Characters Windows refuses in a file name (a drive letter's colon is not part of a name)
# and the device names it reserves whatever the extension.
_WINDOWS_BAD_CHARS = frozenset('<>:"|?*')
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


def output_problem(path: Path, *, platform: str = sys.platform) -> str | None:
    """Why ``path`` can't be written as the deck, or None. Creates a missing parent folder.

    Checked before anything is downloaded, so a typo costs nothing. An existing file is fine
    (it is replaced).
    """
    if path.is_dir():
        return f"{path} is a folder; give a file name, for example {path / 'deck.apkg'}"
    if platform == "win32":
        parts = path.parts[1:] if path.anchor else path.parts
        for part in parts:
            if part in (".", ".."):
                continue
            bad =sorted(_WINDOWS_BAD_CHARS & set(part))
            if bad:
                return f"{path}: Windows does not allow {' '.join(bad)} in a file name"
            if part.split(".")[0].rstrip().lower() in _WINDOWS_DEVICES or part != part.rstrip(" ."):
                return f"{path}: {part!r} is not a usable file name on Windows"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"cannot create the folder for {path}: {exc.strerror or exc}"
    return None


def _deck_name(text: str) -> str:
    name = text.strip()
    if not name:
        raise argparse.ArgumentTypeError("the deck name must not be empty")
    return name


def _version() -> str:
    try:
        return metadata.version("avianki")
    except metadata.PackageNotFoundError:
        return "unknown"


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
    parser.add_argument("--version", action="version", version=f"avianki {_version()}")
    parser.add_argument(
        "--tier",
        type=str.lower,
        choices=[TIER_STANDARD, TIER_EVERYTHING],
        default=TIER_STANDARD,
        help=f"standard: the {STANDARD_LIMIT} most common species; everything: the region's "
        f"{EVERYTHING_LIMIT} most common (default: standard)",
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
        help="put new notes in a subdeck named after the region (AviAnki::<Region>). Anki "
        "leaves a bird you already have in the deck it is in, so only birds not yet in your "
        "collection go to the subdeck; to reorganise the rest, move their cards in Anki's browser",
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
        type=_output_path,
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
        type=_path,
        metavar="DIR",
        help="where downloaded catalog files are kept (default: your per-user cache directory)",
    )
    advanced = parser.add_argument_group("advanced")
    advanced.add_argument(
        "--deck-name",
        type=_deck_name,
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
    """A tqdm bar driven by ``progress(done, total)`` callbacks; silent when ``disable`` or when
    stderr isn't a terminal (a redirected bar is a pile of carriage returns)."""

    def __init__(self, label: str, disable: bool) -> None:
        isatty = getattr(sys.stderr, "isatty", None)
        interactive = bool(isatty is not None and isatty())
        self._bar = tqdm.tqdm(
            total=0, desc=label, unit="file", disable=disable or not interactive, leave=False
        )

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
    if isinstance(exc, AmbiguousRegion):
        return  # the catalog has the region; --ebird would be the wrong advice
    known = _known_ebird_region(query)
    if known is not None:
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

    replaced = out.is_file()
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
        f"Wrote {out} ({_human_size(out.stat().st_size)}): "
        f"{summary.note_count} {_plural(summary.note_count, 'note', 'notes')} ({by_type}) "
        f"for {species_count} {_plural(species_count, 'species', 'species')}."
    )
    if replaced:
        print(f"The file already existed, so it was replaced: {out}")
    if species_count < selected:
        missing = selected - species_count
        print(
            f"{missing} of the {selected} selected species "
            f"{_plural(missing, 'has', 'have')} no media for the chosen card types, "
            f"so {_plural(missing, 'it has', 'they have')} no cards."
        )
    for line in _missing_kind_lines(notes, species_count, args.cards):
        print(line)
    print(f"Next: open {out.name} in Anki (double-click it, or File > Import).")
    return EXIT_OK


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _missing_kind_lines(notes: Sequence[PlannedNote], birds: int, cards: Sequence[str]) -> list[str]:
    """One line per kind of media some bird in the deck lacks, so a bird with a photo but no
    recording (or the reverse) is not a surprise. A bird's notes all carry the same media, and
    a bird missing a kind only has the card types that don't need it."""
    by_species: dict[str, PlannedNote] = {}
    for note in notes:
        by_species.setdefault(note.species_id, note)
    chosen = set(cards)
    lines: list[str] = []
    for kind, other, needs_it in (
        ("recording", "photo", ("audio", "photo_audio")),
        ("photo", "audio", ("photo", "photo_audio")),
    ):
        if not chosen & set(needs_it):
            continue  # no card of the deck asks for this kind
        lacking = sum(
            1 for n in by_species.values() if (n.audio if kind == "recording" else n.photo) is None
        )
        if lacking:
            lines.append(
                f"{lacking} of the {birds} {_plural(birds, 'bird', 'birds')} {_plural(lacking, 'has', 'have')} no {kind}, "
                f"so {_plural(lacking, 'it has', 'they have')} {other} cards only."
            )
    return lines


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


def _advice(exc: Exception) -> str | None:
    """One line of what to try next, for the failures a user can do something about."""
    if isinstance(exc, CacheWriteError):
        return "Choose a folder you can write to with --cache-dir DIR."
    if isinstance(exc, MediaNotFound):
        return None  # its message already says what happened and to try again
    if isinstance(exc, CatalogFetchError):
        return "Check your internet connection and --catalog-url, or try again later."
    if isinstance(exc, SourceError):
        return "Check your internet connection, or try again later."
    return None


def main(argv: Sequence[str] | None = None) -> int:
    use_utf8_output()
    # usecwd: find_dotenv otherwise searches from this module's folder, which for an installed
    # package is site-packages, so a .env in the folder you run from would never be read.
    load_dotenv(find_dotenv(usecwd=True))  # lets a .env file supply EBIRD_API_KEY
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.ebird is None and not args.region:
        parser.error("a REGION is required (a catalog slug such as us-ma), or use --ebird CODE")
    if args.ebird is not None and args.region:
        parser.error("give either REGION or --ebird CODE, not both")
    if args.ebird is not None and args.month is not None:
        parser.error("--month needs the catalog's monthly data and cannot be used with --ebird")
    if args.output is not None:
        problem = output_problem(args.output)
        if problem is not None:
            _error(problem)
            return EXIT_USAGE
    if "::" in args.deck_name:
        print(
            f"avianki: warning: Anki treats '::' in a deck name as a subdeck separator, so "
            f"{args.deck_name!r} will be nested. --subdeck is the usual way to get one.",
            file=sys.stderr,
        )

    setup_logging(None, args.verbose, args.quiet)
    try:
        cache_dir = args.cache_dir if args.cache_dir is not None else default_cache_dir()
        client = CatalogClient(args.catalog_url, cache_dir=cache_dir)
        return _ebird_deck(args, client) if args.ebird is not None else _catalog_deck(args, client)
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (CatalogError, SourceError, OSError) as exc:
        _error(str(exc))
        advice = _advice(exc)
        if advice:
            print(advice, file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        else:
            print("(run again with -v for details)", file=sys.stderr)
        return EXIT_FAILED
    finally:
        teardown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
