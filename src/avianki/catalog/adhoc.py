"""The upstream half of ``avianki --ebird CODE`` (ADR 0017), behind one function.

The CLI is downstream: it may not import sources, media or the pipeline (ADR 0018). ``--ebird``
needs all three, so they sit here and the CLI's one allowed crossing is `build_ebird_species`.

What it does, in order:

1. Ask eBird for the region's species, in eBird's order (`EbirdSpeciesSource`; needs a key).
2. Give each species an id: by the ``ebird_code`` column of ``species.csv`` when it is filled,
   else by scientific name, else a *transient* id minted from the scientific name and never
   written anywhere. Species that get no id (hybrids, odd names) are skipped with a note.
3. Species the catalog already has keep the catalog's media: nothing is built for them here.
4. Everything else is built live with `build_species`: the same registry, licence gate,
   processing and BirdNET check as a catalog build. That needs the ``catalog`` extra (Pillow),
   and ffmpeg plus the ``verify`` extra for audio. Missing extras are `AdhocUnavailable`
   (the message says what to install); missing audio tooling only drops the recordings.
5. Built media is written into the cache directory under its catalog name
   (``media/<hash>.webp``), the same layout `CatalogClient` uses, so the deck writer reads
   both kinds of file the same way.

A species that ends up with no photo and no recording is an absence and produces no notes.
A species a source *failed* on is reported in ``unfinished``; failure is never absence
(ADR 0007), and the caller says so.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avianki.catalog.format import SpeciesEntry, SpeciesFile, write_media
from avianki.core.http import HttpClient
from avianki.sources.ebird import EbirdSpeciesSource, is_region_code
from avianki.sources.registry import Registry
from avianki.taxonomy.species import SpeciesRow, SpeciesTable, load_species, mint_id

log = logging.getLogger("bird_deck")

__all__ = ["AdhocSpecies", "AdhocUnavailable", "InvalidRegionCode", "build_ebird_species"]

BATCH = 25  # species built per `build_species` call, so a progress bar can move


class AdhocUnavailable(Exception):
    """A tool this path needs is not installed. The message says exactly what to install."""


class InvalidRegionCode(ValueError):
    """The text is not an eBird region code (``US``, ``US-MA``, ``US-MA-017``)."""


@dataclass
class AdhocSpecies:
    """What `build_ebird_species` produced.

    ``species_ids`` are in eBird's order and include species the catalog already has.
    ``entries`` holds only the species built live (their names, media and credits), and
    ``media`` maps each live-built file's catalog-relative name to its local path.
    """

    species_ids: list[str] = field(default_factory=list)
    entries: dict[str, SpeciesEntry] = field(default_factory=dict)
    media: dict[str, Path] = field(default_factory=dict)
    from_catalog: int = 0  # species served from catalog media
    skipped: list[str] = field(default_factory=list)  # eBird species that could not be used, and why
    unfinished: list[str] = field(default_factory=list)  # ids a source failed on (not absence)
    notes: list[str] = field(default_factory=list)  # things the user should know about this build


# Hooks the tests replace (the same pattern as catalog_cli): the real client, registry and
# analyser talk to the network and load a model.


def new_client(cache_dir: Path) -> HttpClient:
    return HttpClient(cache_dir=cache_dir)


def new_registry(client: HttpClient, table: SpeciesTable) -> Registry:
    from avianki.catalog.build import make_registry

    return make_registry(client, table)


def new_analyzer() -> Any:
    """The BirdNET analyser (needs the ``verify`` extra)."""
    from avianki.media.verify import default_analyzer

    return default_analyzer()


def _identify(records: Iterable[Any], table: SpeciesTable) -> tuple[list[tuple[str, SpeciesRow]], list[str]]:
    """``(id, row)`` for each eBird species in order, and the species that could not be used, and why.

    ``row`` is transient when the species is not in the table.
    """
    by_code = {r.ebird_code: r for r in table if r.ebird_code}
    out: list[tuple[str, SpeciesRow]] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for rec in records:
        row = by_code.get(rec.source_key)
        if row is None:
            try:
                row = table.by_sci_name(rec.sci_name)
            except KeyError:
                row = None
        if row is None:
            try:
                row = SpeciesRow(id=mint_id(rec.sci_name), sci_name=rec.sci_name, common_name=rec.common_name)
            except ValueError as exc:
                skipped.append(f"{rec.common_name} ({rec.sci_name}): {exc}")
                continue
        if row.id in seen:  # two eBird taxa on one species id would only make duplicate notes
            continue
        seen.add(row.id)
        out.append((row.id, row))
    return out, skipped


def build_ebird_species(
    code: str,
    *,
    api_key: str,
    catalog_species: SpeciesFile,
    cache_dir: Path,
    limit: int | None = None,
    verify: bool | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> AdhocSpecies:
    """The species for an eBird region, with media for each (see the module docstring).

    ``limit`` keeps only the first N species of eBird's list before anything is built (the
    Standard tier). ``verify`` is True to require BirdNET audio checks (raises
    `AdhocUnavailable` without them), False to skip live audio, and None (default) to use
    them when installed and otherwise build photos only, saying so in ``notes``.
    ``progress(done, total)`` counts species built live. Errors from eBird are
    `SourceError`s; the caller reports them.
    """
    code = code.strip().upper()
    if not is_region_code(code):
        raise InvalidRegionCode(f"{code!r} is not an eBird region code (for example US, US-MA or US-MA-017)")
    client = new_client(cache_dir / "http")
    source = EbirdSpeciesSource(client, api_key)
    records = source.species_for(code)

    table = load_species()
    identified, skipped = _identify(records, table)
    result = AdhocSpecies(skipped=skipped)
    if limit is not None:
        identified = identified[:limit]
    result.species_ids = [sid for sid, _ in identified]

    live = [(sid, row) for sid, row in identified if sid not in catalog_species]
    result.from_catalog = len(identified) - len(live)
    log.info(
        "%s: %d species from eBird, %d with catalog media, %d to build live",
        code, len(identified), result.from_catalog, len(live),
    )
    if not live:
        return result

    try:
        from avianki.catalog.build import build_species
    except ImportError as exc:
        raise AdhocUnavailable(
            f"{len(live)} of the species in {code} are not in the catalog and building them needs "
            "the catalog extra. Install it with: pip install 'avianki[catalog]'"
        ) from exc

    analyzer, verify_audio = _audio_tools(verify, result)

    build_table = SpeciesTable(table.all_rows())
    for _sid, row in live:
        if row.id not in build_table:  # a transient row: in memory for this build only
            build_table.add(row)
    registry = new_registry(client, build_table)

    total = len(live)
    if progress is not None:
        progress(0, total)
    for start in range(0, total, BATCH):
        batch = [sid for sid, _ in live[start : start + BATCH]]
        built = build_species(
            batch, table=build_table, registry=registry, analyzer=analyzer, verify=verify_audio
        )
        result.entries.update(built.species.entries)
        for name, data in built.media.items():
            written = write_media(cache_dir, data, Path(name).suffix.lstrip("."))
            result.media[written] = cache_dir / written
        result.unfinished.extend(built.report.unfinished_species)
        for failure in built.report.source_failures:
            log.warning("%s failed%s: %s", failure.source, f" for {failure.species_id}" if failure.species_id else "", failure.error)
        if progress is not None:
            progress(min(start + BATCH, total), total)
    return result


def _audio_tools(verify: bool | None, result: AdhocSpecies) -> tuple[Any, bool]:
    """The BirdNET analyser and whether to build live audio, per the ``verify`` policy."""
    if verify is False:
        result.notes.append("Recordings for species outside the catalog were skipped (audio checks are off).")
        return None, False
    problem: str | None = None
    analyzer: Any = None
    if shutil.which("ffmpeg") is None:
        problem = "ffmpeg is not installed (install it from ffmpeg.org, or your package manager)"
    else:
        from avianki.media.verify import VerifyUnavailable

        try:
            analyzer = new_analyzer()
            _ = analyzer.labels  # loads the model now, so a missing extra fails before any request
        except VerifyUnavailable as exc:
            problem = f"BirdNET is not available ({exc}); install it with: pip install 'avianki[verify]'"
    if problem is None:
        return analyzer, True
    if verify is True:
        raise AdhocUnavailable(f"audio checks were required but {problem}")
    result.notes.append(
        f"Recordings for species outside the catalog were skipped: {problem}. "
        "Their photos are included."
    )
    return None, False
