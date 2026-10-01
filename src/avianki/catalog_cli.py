"""``avianki-catalog``: the maintainer-side catalog build (spec §4).

``build --species-only`` builds the region species lists (GBIF) and mints new species into
``src/avianki/data/species.csv``. ``build`` alone is the full build: species lists, a photo and a
BirdNET-verified recording per species, the validation gate, and ``site/``, ``build-report.md``
and ``contact-sheet.html`` under ``--out``. This module only parses arguments, wires the real
collaborators and prints; the work is in `avianki.catalog.build`.

Exit codes: 0 built (source failures that left previous entries in place still exit 0, and are
in the report); 1 the catalog failed validation, a pin could not be honoured, or a region has
no list; 2 usage errors, unreadable inputs, or audio that cannot be verified.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import requests

# The build needs the `catalog` extra (Pillow, jsonschema, tomli). Without it these imports fail
# deep inside the pipeline, so this is the one place that turns that into a plain message; the
# console script imports this module first, which makes even `--help` safe.
_EXTRA_MODULES = frozenset({"PIL", "jsonschema", "tomli"})
try:
    from avianki.catalog.build import DEFAULT_BASE_URL, BuildOptions, make_registry, run_build
    from avianki.catalog.format import FormatError, LoadedCatalog, load_catalog
    from avianki.catalog.pins import Pins, PinsError, load_pins
    from avianki.catalog.species_lists import TOP_N, build_species_lists, render_report
    from avianki.catalog.validate import format_result
    from avianki.core.http import HttpClient, SourceError
    from avianki.core.log import setup_logging, teardown_logging
    from avianki.core.text import use_utf8_output
    from avianki.media.verify import VerifyUnavailable, default_analyzer
    from avianki.sources.contract import Region
    from avianki.sources.gbif import GbifSpeciesSource
    from avianki.sources.registry import Registry
    from avianki.taxonomy import DATA_DIR
    from avianki.taxonomy.regions import RegionTable, load_regions
    from avianki.taxonomy.species import SPECIES_CSV, SpeciesTable, load_species, save_species
except ModuleNotFoundError as _missing:
    if (_missing.name or "").partition(".")[0] not in _EXTRA_MODULES:
        raise
    print('avianki-catalog needs the catalog extra: pip install "avianki[catalog]"', file=sys.stderr)
    raise SystemExit(2) from None

log = logging.getLogger("bird_deck")

PINS_TOML = DATA_DIR / "pins.toml"


# -- seams the tests replace ----------------------------------------------------------------


def new_client(cache_dir: Path | None, session: requests.Session) -> HttpClient:
    return HttpClient(cache_dir=cache_dir, session=session)


def new_session() -> requests.Session:
    return requests.Session()


def new_registry(client: HttpClient, species: SpeciesTable, expected_counts: Any) -> Registry:
    """The real asset sources (Commons, iNaturalist), sharing ``client``."""
    return make_registry(client, species, expected_counts)


def new_analyzer() -> Any:
    """The BirdNET analyser (needs the ``birdnet`` extra)."""
    return default_analyzer()


# -- arguments ------------------------------------------------------------------------------


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
                       help="species table to read and extend (default: the packaged src/avianki/data/species.csv)")
    build.add_argument("--top-n", type=int, default=TOP_N, help=f"species kept per region (default: {TOP_N})")
    build.add_argument("--max-species", type=int, metavar="N",
                       help="build only the N most widespread species (a dev run)")
    build.add_argument("--previous", type=Path, metavar="DIR",
                       help="the last published catalog: its assets are kept (sticky, ADR 0014) and "
                            "its region lists are reused while the EOD version is unchanged")
    build.add_argument("--pins", type=Path, default=PINS_TOML,
                       help="pins, exclusions and credit-removal requests (default: src/avianki/data/pins.toml)")
    build.add_argument("--refresh-species", action="store_true",
                       help="rebuild the region lists even when the EOD version is unchanged (after a change "
                            "to how lists are built)")
    build.add_argument("--allow-shrink", action="store_true",
                       help="downgrade the shrink checks to warnings (a deliberate drop)")
    build.add_argument("--no-verify", action="store_true",
                       help="skip BirdNET: audio comes only from pins. For development; never publish the result")
    build.add_argument("--time-budget-minutes", type=float, metavar="M",
                       help="stop starting new work after M minutes; publish what exists and list the rest")
    build.add_argument("--update-species-csv", action="store_true",
                       help="write minted species and newly found ids into --species-csv (otherwise the "
                            "build report lists them)")
    build.add_argument("--base-url", default=DEFAULT_BASE_URL,
                       help=f"where the catalog will be served (default: {DEFAULT_BASE_URL})")
    noise = build.add_mutually_exclusive_group()
    noise.add_argument("-v", "--verbose", action="store_true", help="debug output")
    noise.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    return parser


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.top_n < 1:
        parser.error("--top-n must be at least 1")
    if args.max_species is not None and args.max_species < 1:
        parser.error("--max-species must be at least 1")
    if args.time_budget_minutes is not None and args.time_budget_minutes <= 0:
        parser.error("--time-budget-minutes must be greater than 0")

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
        if args.species_only:
            return _build_species(args, regions, table, out)
        return _build_catalog(args, regions, table, out)
    finally:
        teardown_logging()


# -- shared: the EOD version and the per-version cache ---------------------------------------


def _eod_version_and_cache(
    cache_root: Path, session: requests.Session, regions: RegionTable
) -> tuple[str, Path] | None:
    """The current EOD dataset version and its response cache directory, or None if GBIF is unreachable.

    Responses are cached per EOD version, so a new release never reads the old one's facets;
    directories cached for other versions are removed.
    """
    try:
        version = GbifSpeciesSource(new_client(None, session), regions).dataset_version()
    except SourceError as e:
        log.error("couldn't check the EOD dataset version: %s", e)
        return None
    log.info("EOD dataset version: %s", version)
    cache = cache_root / f"eod-{hashlib.sha256(version.encode('utf-8')).hexdigest()[:12]}"
    if cache_root.is_dir():
        for stale in cache_root.glob("eod-*"):
            if stale != cache and stale.is_dir():
                log.info("removing responses cached for an older EOD version: %s", stale)
                shutil.rmtree(stale)
    return version, cache


# -- --species-only ---------------------------------------------------------------------------


def _build_species(args: argparse.Namespace, regions: list[Region], table: RegionTable, out: Path) -> int:
    session = new_session()
    prepared = _eod_version_and_cache(args.cache_dir, session, table)
    if prepared is None:
        return 1
    version, cache = prepared
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


# -- the full build ---------------------------------------------------------------------------


def _load_previous(path: Path) -> LoadedCatalog | None:
    try:
        return load_catalog(path)
    except FormatError as e:
        log.error("--previous %s is not a readable catalog: %s", path, e)
        return None


def _build_catalog(args: argparse.Namespace, regions: list[Region], table: RegionTable, out: Path) -> int:
    species = load_species(args.species_csv)
    try:
        pins: Pins = load_pins(args.pins, species)
    except PinsError as e:
        log.error("%s", e)
        print(f"avianki-catalog: {e}", file=sys.stderr)
        return 2
    previous: LoadedCatalog | None = None
    if args.previous is not None:
        previous = _load_previous(args.previous)
        if previous is None:
            return 2

    verify = not args.no_verify
    analyzer = None
    if verify:
        try:
            analyzer = new_analyzer()
            _ = analyzer.labels  # loads the model now, so a missing extra fails before any request
        except VerifyUnavailable as e:
            log.error("audio cannot be verified: %s", e)
            print(f"avianki-catalog: audio cannot be verified: {e}\n"
                  "Install the extra (uv sync --extra verify) or pass --no-verify for a dev run.",
                  file=sys.stderr)
            return 2
    else:
        print("WARNING: --no-verify: no audio will be checked by BirdNET, so audio comes only from pins. "
              "Do not publish this catalog.", file=sys.stderr)
        log.warning("--no-verify: audio comes only from pins")

    session = new_session()
    prepared = _eod_version_and_cache(args.cache_dir, session, table)
    if prepared is None:
        return 1
    eod_version, cache = prepared
    client = new_client(cache, session)
    species_source = GbifSpeciesSource(client, table)

    rows = [table.by_slug(r.slug) for r in regions]
    options = BuildOptions(
        out=out,
        regions=regions,
        gadm_version=", ".join(sorted({r.gadm_version for r in rows})),
        eod_version=eod_version,
        catalog_version=client.today(),
        top_n=args.top_n,
        max_species=args.max_species,
        previous=previous,
        pins=pins,
        allow_shrink=args.allow_shrink,
        refresh_species=args.refresh_species,
        verify=verify,
        time_budget_minutes=args.time_budget_minutes,
        base_url=args.base_url,
    )
    try:
        result = run_build(
            options,
            species_source=species_source,
            species_table=species,
            registry_factory=lambda expected: new_registry(client, species, expected),
            analyzer=analyzer,
        )
    except VerifyUnavailable as e:
        log.error("audio cannot be verified: %s", e)
        print(f"avianki-catalog: audio cannot be verified: {e}", file=sys.stderr)
        return 2

    if args.update_species_csv:
        _update_species_csv(args.species_csv, species, result.report.new_ids_discovered)
    _print_summary(result, out, args)
    return 0 if result.ok else 1


def _update_species_csv(path: Path, table: SpeciesTable, discovered: dict[str, dict[str, str]]) -> None:
    """Write minted species and newly found ids (iNaturalist taxon id, BirdNET label) to ``path``."""
    rows = []
    for row in table.all_rows():
        found = discovered.get(row.id, {})
        changes: dict[str, Any] = {}
        if "inat_taxon_id" in found and row.inat_taxon_id is None:
            changes["inat_taxon_id"] = int(found["inat_taxon_id"])
        if "birdnet_label" in found and not row.birdnet_label:
            changes["birdnet_label"] = found["birdnet_label"]
        rows.append(dataclasses.replace(row, **changes) if changes else row)
    save_species(SpeciesTable(rows), path)
    log.info("updated %s", path)


def _print_summary(result: Any, out: Path, args: argparse.Namespace) -> None:
    rep = result.report
    lines = [
        f"catalog {rep.catalog_version}: {rep.species_total} species "
        f"({rep.built} built, {rep.reused} reused, {rep.sticky_invalidated} previous assets not kept), "
        f"{rep.photos} photos, {rep.audio} recordings",
    ]
    if result.site_dir is not None:
        lines.append(f"site: {result.site_dir}")
    lines.append(f"report: {out / 'build-report.md'}")
    lines.append(f"contact sheet: {out / 'contact-sheet.html'}")
    if result.validation is not None:
        lines.append(format_result(result.validation))
    for err in result.errors:
        lines.append(f"ERROR: {err}")
    for err in rep.pin_errors:
        lines.append(f"PIN ERROR: {err}")
    if rep.unfinished_species:
        lines.append(f"{len(rep.unfinished_species)} species unfinished (see the report): they keep what they had")
    if rep.source_failures:
        lines.append(f"{len(rep.source_failures)} source failure(s) (see the report); failures are never treated as absence")
    if args.no_verify:
        lines.append("WARNING: built with --no-verify. Audio was not checked. Do not publish.")
    if rep.new_ids_discovered and not args.update_species_csv:
        lines.append(f"{len(rep.new_ids_discovered)} species have new ids to commit; rerun with --update-species-csv")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
