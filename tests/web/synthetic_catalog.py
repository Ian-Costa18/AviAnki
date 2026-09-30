"""A realistic-size catalog for the mobile heap test, made at test time and never committed.

One region (``us-ma``, "Massachusetts") with 400 species. Each species has one photo of about
60 KB and one recording of about 100 KB, both random bytes: real photos and recordings do not
compress further, so random bytes make the .apkg the size the real one would be (Standard, 100
species, about 16 MB; Everything, 400 species, about 64 MB). The files go through the real writers
in ``avianki.catalog.format`` so the names are content hashes and the JSON validates.
"""

from __future__ import annotations

import random
from pathlib import Path

from avianki.catalog.credit import render_credit
from avianki.catalog.format import (
    DatasetCredit,
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

SPECIES_COUNT = 400
PHOTO_BYTES = 60_000
AUDIO_BYTES = 100_000
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def species_id(i: int) -> str:
    """``aa-ab``-style slugs (letters only, so they are valid ids and unique)."""
    return f"{LETTERS[i // 26 % 26]}{LETTERS[i % 26]}-{LETTERS[i // 676]}bird"


def _record(kind: str, sid: str) -> AssetRecord:
    licence = "CC-BY-4.0"
    return AssetRecord(
        source="synthetic",
        source_asset_id=f"{sid}-{kind}",
        source_url=f"https://example.org/synthetic/{sid}/{kind}",
        file_url=f"https://example.org/synthetic/{sid}/{kind}/file",
        licence_id=licence,
        licence_url=licence_url(licence),
        creator="Synthetic Creator",
        title=f"{sid} {kind}",
        modifications=("resized",) if kind == "photo" else ("trimmed",),
        retrieved_at="2026-01-01",
    )


def build_synthetic_catalog(out_dir: Path, *, species: int = SPECIES_COUNT, seed: int = 20260101) -> Manifest:
    """Write the catalog into ``out_dir`` and return its manifest (``total_bytes`` is the download size)."""
    rng = random.Random(seed)
    entries: dict[str, SpeciesEntry] = {}
    provenance: dict[str, ProvenanceEntry] = {}
    rows: list[tuple[str, tuple[int, ...]]] = []
    for i in range(species):
        sid = species_id(i)
        tag = sid.split("-")[0]
        refs: dict[str, list[MediaRef]] = {}
        for kind, ext, size in (("photo", "webp", PHOTO_BYTES), ("audio", "mp3", AUDIO_BYTES)):
            data = rng.randbytes(size + rng.randrange(-size // 10, size // 10))
            file = write_media(out_dir, data, ext)
            record = _record(kind, sid)
            refs[kind] = [MediaRef(file, len(data), render_credit(kind, record))]
            provenance[file] = ProvenanceEntry(
                record=record, species_id=sid, kind=kind,  # type: ignore[arg-type]
                token=f"synthetic:{sid}-{kind}",
            )  # fmt: skip
        entries[sid] = SpeciesEntry(f"Quillfinch {tag}", f"Vexia {tag}", refs["photo"], refs["audio"])  # no word a card front shows
        level = max(1, 255 - i * 254 // species)
        rows.append((sid, (level,) * 12))

    manifest = Manifest(
        catalog_version="2026-01-01",
        base_url="https://synthetic.invalid/catalog/",
        gadm_version="4.1",
        species_file="species.00000000.json",  # recomputed by write_catalog
        regions=[RegionRef("us-ma", "Massachusetts", "US", "regions/x.00000000.json", 0)],
        dataset_credits=[
            DatasetCredit(
                text="Synthetic dataset for a memory test",
                licence_id="CC-BY-4.0",
                url="https://example.org/synthetic/dataset",
                modifications="none",
            )
        ],
        total_bytes=0,
        eod_version="synthetic",
    )
    written = write_catalog(
        out_dir, manifest, [RegionFile("us-ma", rows)], SpeciesFile(entries), ProvenanceFile(provenance)
    )
    load_catalog(out_dir)
    return written
