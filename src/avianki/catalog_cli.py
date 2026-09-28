"""``avianki-catalog``: the maintainer-side catalog build (spec §4).

At M2 only ``build --species-only`` exists: region species lists from GBIF, minting new
species into ``data/species.csv``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path

import requests

from avianki.catalog.species_lists import TOP_N, build_species_lists, render_report
from avianki.core.http import HttpClient, SourceError
from avianki.core.log import setup_logging, teardown_logging
from avianki.sources.contract import Region
from avianki.sources.gbif import GbifSpeciesSource
from avianki.taxonomy.regions import load_regions
from avianki.taxonomy.species import SPECIES_CSV, load_species, save_species

log = logging.getLogger("bird_deck")


def new_client(cache_dir: Path | None, session: requests.Session) -> HttpClient:
    return HttpClient(cache_dir=cache_dir, session=session)


def new_session() -> requests.Session:
    return requests.Session()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avianki-catalog", description="Build the AviAnki catalog.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build the catalog")
    build.add_argument("--species-only", action="store_true",
                       help="only build region species lists and mint new species (the M2 half)")
    build.add_argument("--regions", help="comma-separated region slugs, e.g. us-ri,us-dc (default: every region)")
    build.add_argument("--out", type=Path, default=Path("build"), help="output directory (default: build/)")
    build.add_argument("--cache-dir", type=Path, default=Path(".cache/http"),
                       help="HTTP response cache (default: .cache/http)")
    build.add_argument("--species-csv", type=Path, default=SPECIES_CSV,
                       help="species table to read and extend (default: the repo's data/species.csv)")
    build.add_argument("--top-n", type=int, default=TOP_N, help=f"species kept per region (default: {TOP_N})")
    noise = build.add_mutually_exclusive_group()
    noise.add_argument("-v", "--verbose", action="store_true", help="debug output")
    noise.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.species_only:
        print("avianki-catalog build: only --species-only is implemented; the full build arrives in M3.",
              file=sys.stderr)
        return 2
    if args.top_n < 1:
        parser.error("--top-n must be at least 1")

    table = load_regions()
    try:
        slugs = [s.strip() for s in args.regions.split(",") if s.strip()] if args.regions else [r.slug for r in table]
        rows = [table.by_slug(s) for s in dict.fromkeys(slugs)]
    except KeyError as e:
        parser.error(str(e.args[0]))
    regions = [Region(r.slug, r.name, r.country, r.gadm_gid) for r in rows]

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    setup_logging(out / "catalog.log", args.verbose, args.quiet)
    try:
        return _build_species(args, regions, table, out)
    finally:
        teardown_logging()


def _build_species(args: argparse.Namespace, regions: list[Region], table, out: Path) -> int:
    session = new_session()
    try:
        version = GbifSpeciesSource(new_client(None, session), table).dataset_version()
    except SourceError as e:
        log.error("couldn't check the EOD dataset version: %s", e)
        return 1
    log.info("EOD dataset version: %s", version)

    # Responses are cached per EOD version, so a new release never reads the old one's facets.
    cache_root: Path = args.cache_dir
    cache = cache_root / f"eod-{hashlib.sha256(version.encode('utf-8')).hexdigest()[:12]}"
    if cache_root.is_dir():
        for stale in cache_root.glob("eod-*"):
            if stale != cache and stale.is_dir():
                log.info("removing responses cached for an older EOD version: %s", stale)
                shutil.rmtree(stale)
    source = GbifSpeciesSource(new_client(cache, session), table)

    species = load_species(args.species_csv)
    result = build_species_lists(source, regions, species, top_n=args.top_n, dataset_version=version)

    regions_dir = out / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)
    for slug, content in result.region_files.items():
        (regions_dir / f"{slug}.json").write_text(
            json.dumps(content, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"
        )
    (out / "species-lists-report.md").write_text(render_report(result, regions, args.top_n), encoding="utf-8")
    if result.minted:
        save_species(species, args.species_csv)
        log.info("minted %d species into %s", len(result.minted), args.species_csv)

    log.info("wrote %d region lists to %s", len(result.region_files), regions_dir)
    if result.failed:
        log.error("%d region(s) failed: %s", len(result.failed), ", ".join(result.failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
