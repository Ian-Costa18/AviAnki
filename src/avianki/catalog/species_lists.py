"""Species half of the catalog build (spec §4 step 2): region lists and minting.

For each region, ask the species source for its ranked list, map every record to a
minted species id (minting new ones into ``species.csv``), keep the top N by rank and
produce the region file content of spec §5.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from avianki.core.http import SourceError
from avianki.sources.contract import Region, SpeciesRecord, SpeciesSource
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

log = logging.getLogger("bird_deck")

TOP_N = 400


@runtime_checkable
class VersionedSource(Protocol):
    def dataset_version(self) -> str: ...


@runtime_checkable
class ReportsNameFallbacks(Protocol):
    def name_fallbacks(self) -> list[Any]: ...


@dataclass
class SpeciesListsResult:
    region_files: dict[str, dict[str, Any]] = field(default_factory=dict)  # slug -> spec §5 region file
    species_counts: dict[str, int] = field(default_factory=dict)  # slug -> species the source listed
    minted: list[SpeciesRow] = field(default_factory=list)  # new species.csv rows: the diff to commit
    no_ioc_match: list[Any] = field(default_factory=list)  # the source's name fallbacks
    unmintable: list[SpeciesRecord] = field(default_factory=list)  # names mint_id refuses (e.g. hybrids)
    failed: dict[str, str] = field(default_factory=dict)  # slug -> error; never written as an empty list
    dataset_version: str = "unknown"

    @property
    def ok(self) -> bool:
        return not self.failed


def build_species_lists(
    source: SpeciesSource,
    regions: Iterable[Region],
    species_table: SpeciesTable,
    *,
    top_n: int = TOP_N,
    dataset_version: str | None = None,
) -> SpeciesListsResult:
    """Build every region's list. Mints into ``species_table`` in place.

    A region whose source call raises `SourceError` is logged and recorded in
    ``failed``; the others carry on. Any other exception is a bug and propagates.
    """
    result = SpeciesListsResult()
    if dataset_version is not None:
        result.dataset_version = dataset_version
    elif isinstance(source, VersionedSource):
        result.dataset_version = source.dataset_version()

    unmintable_keys: set[str] = set()
    for region in regions:
        try:
            records = source.species_for(region.slug)
        except SourceError as e:
            log.error("species list for %s failed: %s", region.slug, e)
            result.failed[region.slug] = str(e)
            continue
        if not records:
            msg = "the source returned no species; every US and Canadian region has records, so this is a failure"
            log.error("species list for %s failed: %s", region.slug, msg)
            result.failed[region.slug] = msg
            continue
        result.species_counts[region.slug] = len(records)
        held = _held_keys(source)

        listed: list[list[Any]] = []
        seen: set[str] = set()
        for record in sorted(records, key=lambda r: r.rank):
            if len(listed) >= top_n:
                break
            if record.source_key in held:
                continue  # not in the IOC list: reported, never minted (ADR 0008)
            species_id = _species_id(record, species_table, result)
            if species_id is None:
                if record.source_key not in unmintable_keys:
                    unmintable_keys.add(record.source_key)
                    result.unmintable.append(record)
                continue
            if species_id in seen:
                log.warning("%s: %s maps to %s twice; keeping the higher rank", region.slug, record.sci_name, species_id)
                continue
            seen.add(species_id)
            listed.append([species_id, list(record.monthly)])
        result.region_files[region.slug] = {"slug": region.slug, "species": listed}
        log.info("%s: %d species listed by %s, kept %d", region.slug, len(records), source.name, len(listed))

    if isinstance(source, ReportsNameFallbacks):
        result.no_ioc_match = list(source.name_fallbacks())
    return result


def render_report(result: SpeciesListsResult, regions: Iterable[Region], top_n: int) -> str:
    """``species-lists-report.md``: what changed and what needs a human look."""
    def cell(text: object) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Species lists",
        "",
        f"- EOD dataset version: `{result.dataset_version}`",
        f"- Regions: {len(result.region_files)} written, {len(result.failed)} failed",
        f"- Newly minted species: {len(result.minted)}",
        f"- Species without an IOC match: {len(result.no_ioc_match)}",
        "",
    ]
    if result.failed:
        lines += ["## Failed regions", "", "No list was written for these; the previous one stands.", "",
                  "| Region | Error |", "|---|---|"]
        lines += [f"| {slug} | {cell(err)} |" for slug, err in result.failed.items()]
        lines.append("")
    lines += ["## Regions", "", f"| Region | Name | Species listed | Kept (top {top_n}) |", "|---|---|---|---|"]
    for region in regions:
        if region.slug in result.region_files:
            kept = len(result.region_files[region.slug]["species"])
            lines.append(f"| {region.slug} | {cell(region.name)} | {result.species_counts[region.slug]} | {kept} |")
        elif region.slug in result.failed:
            lines.append(f"| {region.slug} | {cell(region.name)} | FAILED | - |")
    lines.append("")
    if result.minted:
        lines += ["## Minted species (the diff to commit to data/species.csv)", "",
                  "| Id | Scientific name | Common name | GBIF key |", "|---|---|---|---|"]
        lines += [f"| {r.id} | {cell(r.sci_name)} | {cell(r.common_name)} | {r.gbif_key or ''} |" for r in result.minted]
        lines.append("")
    if result.no_ioc_match:
        lines += ["## No IOC match: held back", "",
                  "Not in the IOC list, so not minted and left out of every region list (ADR 0008). "
                  "Add each one to species.csv by hand, with an alias row if IOC uses another name, or leave it out.", "",
                  "| GBIF key | Scientific name | Common name | Common name from |", "|---|---|---|---|"]
        lines += [
            f"| {f.source_key} | {cell(f.sci_name)} | {cell(f.common_name)} | {f.common_name_from} |"
            for f in result.no_ioc_match
        ]
        lines.append("")
    if result.unmintable:
        lines += ["## Skipped: no id can be minted", "", "| Source key | Scientific name | Common name |", "|---|---|---|"]
        lines += [f"| {r.source_key} | {cell(r.sci_name)} | {cell(r.common_name)} |" for r in result.unmintable]
        lines.append("")
    return "\n".join(lines)


def _held_keys(source: SpeciesSource) -> set[str]:
    if isinstance(source, ReportsNameFallbacks):
        return {str(f.source_key) for f in source.name_fallbacks()}
    return set()


def _species_id(record: SpeciesRecord, table: SpeciesTable, result: SpeciesListsResult) -> str | None:
    if record.species_id is not None and record.species_id in table:
        return table.get(record.species_id).id
    gbif_key = int(record.source_key) if record.source_key.isdigit() else None
    try:
        minted = table.mint(record.sci_name, record.common_name, gbif_key)
    except ValueError as e:
        log.warning("can't mint an id for %s (%s): %s", record.sci_name, record.source_key, e)
        return None
    if minted.created:
        log.info("minted %s (%s, gbif %s)", minted.row.id, minted.row.common_name, gbif_key)
        result.minted.append(minted.row)
    return minted.row.id
