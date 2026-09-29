"""Builders for small, real published catalogs on disk (for validate/report tests).

Media bytes are synthetic (they only need to hash, not decode). Every catalog goes through
`write_media` / `write_catalog`, so it is exactly what the pipeline would publish.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avianki.catalog.credit import render_credit
from avianki.catalog.format import (
    DatasetCredit,
    LoadedCatalog,
    Manifest,
    MediaRef,
    ProvenanceEntry,
    ProvenanceFile,
    RegionFile,
    RegionRef,
    SpeciesEntry,
    SpeciesFile,
    load_catalog,
    write_catalog,
    write_media,
)
from avianki.core.licences import AssetRecord, licence_url

MONTHLY = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120)

DATASET_CREDITS = [
    DatasetCredit(
        text="eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF",
        licence_id="CC-BY-4.0",
        url="https://doi.org/10.15468/aomfnb",
        modifications="filtered and ranked by region",
    )
]


def make_record(**overrides: Any) -> AssetRecord:
    base: dict[str, Any] = {
        "source": "commons",
        "source_asset_id": "File:Robin.jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Robin.jpg",
        "file_url": "https://upload.wikimedia.org/robin.jpg",
        "licence_id": "CC-BY-SA-3.0",
        "licence_url": licence_url("CC-BY-SA-3.0"),
        "creator": "Mdf",
        "title": "Robin",
        "modifications": ("resized",),
        "retrieved_at": "2026-09-28",
    }
    base.update(overrides)
    return AssetRecord(**base)


@dataclass
class Sp:
    """A species to put in a test catalog."""

    name: str
    sci: str = "Turdus testus"
    photos: int = 1
    audios: int = 1
    verified: str | None = "birdnet"
    confidence: float | None = 0.9


def build_catalog(
    out_dir: Path,
    species: dict[str, Sp],
    regions: dict[str, list[str]] | None = None,
) -> LoadedCatalog:
    """Write a catalog for ``species`` (id -> Sp); by default one region, ``us-ma``, of all."""
    if regions is None:
        regions = {"us-ma": list(species)}
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: dict[str, SpeciesEntry] = {}
    prov: dict[str, ProvenanceEntry] = {}
    for sid, sp in species.items():
        photo_refs: list[MediaRef] = []
        audio_refs: list[MediaRef] = []
        for kind, count, ext, refs in (
            ("photo", sp.photos, "webp", photo_refs),
            ("audio", sp.audios, "mp3", audio_refs),
        ):
            for i in range(count):
                data = f"{sid}/{kind}/{i}".encode() * 4
                name = write_media(out_dir, data, ext)
                record = make_record(
                    source="commons" if kind == "photo" else "inaturalist",
                    source_asset_id=f"{sid}-{kind}-{i}",
                    creator=f"Creator {sid}",
                    title=f"{sp.name} {kind} {i}",
                )
                refs.append(MediaRef(name, len(data), render_credit(kind, record)))
                prov[name] = ProvenanceEntry(
                    record=record,
                    species_id=sid,
                    kind=kind,  # type: ignore[arg-type]
                    token=f"{sid}-{kind}-{i}",
                    verified=sp.verified if kind == "audio" else "pinned",  # type: ignore[arg-type]
                    birdnet_confidence=sp.confidence if kind == "audio" else None,
                )
        entries[sid] = SpeciesEntry(sp.name, sp.sci, photo_refs, audio_refs)
    return write_parts(
        out_dir, SpeciesFile(entries), ProvenanceFile(prov), regions, media_from=None
    )


def write_parts(
    out_dir: Path,
    species: SpeciesFile,
    provenance: ProvenanceFile,
    regions: dict[str, list[str]],
    *,
    media_from: Path | None,
    dataset_credits: list[DatasetCredit] | None = None,
) -> LoadedCatalog:
    """Write JSON for the given parts into ``out_dir`` and load it back.

    ``media_from`` is another catalog root whose ``media/`` is copied in first (used to
    make a mutated copy of a catalog).
    """
    if media_from is not None:
        shutil.copytree(media_from / "media", out_dir / "media", dirs_exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    region_files = [RegionFile(slug, [(sid, MONTHLY) for sid in ids]) for slug, ids in regions.items()]
    manifest = Manifest(
        catalog_version="2026-10-01",
        base_url="https://example.test/catalog/",
        gadm_version="4.1",
        species_file="species.00000000.json",
        regions=[RegionRef(slug, slug.upper(), "US", "regions/x.00000000.json", 0) for slug in regions],
        dataset_credits=DATASET_CREDITS if dataset_credits is None else dataset_credits,
        total_bytes=0,
    )
    write_catalog(out_dir, manifest, region_files, species, provenance)
    return load_catalog(out_dir)


def mutated_copy(
    cat: LoadedCatalog,
    dest: Path,
    *,
    species: SpeciesFile | None = None,
    provenance: ProvenanceFile | None = None,
    regions: dict[str, list[str]] | None = None,
) -> LoadedCatalog:
    """A new catalog at ``dest`` from ``cat`` with some parts replaced (media copied)."""
    assert cat.provenance is not None
    return write_parts(
        dest,
        species or cat.species,
        provenance or cat.provenance,
        regions if regions is not None else {s: [i for i, _ in r.species] for s, r in cat.regions.items()},
        media_from=cat.root,
    )
