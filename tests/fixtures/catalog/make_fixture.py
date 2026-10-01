"""Regenerate this directory: a tiny published catalog in the exact spec section 5 format.

    uv run --extra catalog python tests/fixtures/catalog/make_fixture.py

Needs the ``catalog`` extra (Pillow, jsonschema) and ``ffmpeg`` on PATH. It goes through the
real writers in ``avianki.catalog.format`` and the real credit renderer, so the files are
exactly what the pipeline would publish; re-run it whenever the format changes.

What it contains (all made up: the photos are solid-colour WebPs, the recordings are one
second sine tones, the creators and URLs are invented and live under example.org):

* 12 species, real ids and names from data/species.csv.
* ``us-ma`` "Massachusetts": all 12 species. Migrants and winter visitors have monthly
  zeros, so a month filter changes the list (Snowy Owl and Dark-eyed Junco are absent in
  summer, Ruby-throated Hummingbird and Common Loon absent in winter).
* ``ca-qc`` "Québec": 7 species; the accent is there to test name matching.
* ``us-az`` "Arizona": 6 species.
* Snowy Owl has no audio; Common Loon has no photo.
* Mallard carries an invented ``ioc_name`` so the IOC tag has a species to show on (ADR 0027);
  every other species omits the key, as the real catalog does.
* ``base_url`` is a placeholder that tests override (clients resolve paths against
  where they read the manifest from, not against this).
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

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

OUT_DIR = Path(__file__).resolve().parent
PLACEHOLDER_BASE_URL = "https://fixture.invalid/catalog/"
RETRIEVED = "2026-01-01"

# (id, common name, scientific name, photos, audio recordings, tone Hz of the first recording)
# The species with 0 photos or 0 recordings are the "absence" cases.
SPECIES: list[tuple[str, str, str, int, int, int]] = [
    ("turdus-migratorius", "American Robin", "Turdus migratorius", 2, 2, 440),
    ("poecile-atricapillus", "Black-capped Chickadee", "Poecile atricapillus", 2, 2, 523),
    ("cardinalis-cardinalis", "Northern Cardinal", "Cardinalis cardinalis", 2, 1, 587),
    ("cyanocitta-cristata", "Blue Jay", "Cyanocitta cristata", 2, 1, 659),
    ("spinus-tristis", "American Goldfinch", "Spinus tristis", 2, 1, 698),
    ("bubo-scandiacus", "Snowy Owl", "Bubo scandiacus", 2, 0, 0),
    ("archilochus-colubris", "Ruby-throated Hummingbird", "Archilochus colubris", 1, 1, 784),
    ("gavia-immer", "Common Loon", "Gavia immer", 0, 1, 880),
    ("anas-platyrhynchos", "Mallard", "Anas platyrhynchos", 2, 1, 988),
    ("buteo-jamaicensis", "Red-tailed Hawk", "Buteo jamaicensis", 2, 1, 1047),
    ("dryobates-pubescens", "Downy Woodpecker", "Dryobates pubescens", 2, 1, 1175),
    ("junco-hyemalis", "Dark-eyed Junco", "Junco hyemalis", 2, 1, 1319),
]

_YEAR_ROUND = (120, 110, 130, 180, 220, 240, 230, 220, 200, 170, 140, 120)
_WINTER_ONLY = (200, 190, 120, 20, 0, 0, 0, 0, 0, 30, 130, 210)
_SUMMER_ONLY = (0, 0, 0, 40, 160, 230, 250, 240, 120, 10, 0, 0)


def _scaled(base: tuple[int, ...], factor: float) -> tuple[int, ...]:
    return tuple(min(255, round(v * factor)) for v in base)


# region slug -> (name, country, [(species id, monthly vector)]) in rank order.
REGIONS: dict[str, tuple[str, str, list[tuple[str, tuple[int, ...]]]]] = {
    "us-ma": (
        "Massachusetts",
        "US",
        [
            ("turdus-migratorius", _YEAR_ROUND),
            ("poecile-atricapillus", _scaled(_YEAR_ROUND, 0.95)),
            ("cardinalis-cardinalis", _scaled(_YEAR_ROUND, 0.9)),
            ("cyanocitta-cristata", _scaled(_YEAR_ROUND, 0.85)),
            ("spinus-tristis", _scaled(_YEAR_ROUND, 0.8)),
            ("anas-platyrhynchos", _scaled(_YEAR_ROUND, 0.7)),
            ("dryobates-pubescens", _scaled(_YEAR_ROUND, 0.6)),
            ("buteo-jamaicensis", _scaled(_YEAR_ROUND, 0.5)),
            ("archilochus-colubris", _SUMMER_ONLY),
            ("junco-hyemalis", _WINTER_ONLY),
            ("gavia-immer", _scaled(_SUMMER_ONLY, 0.6)),
            ("bubo-scandiacus", _scaled(_WINTER_ONLY, 0.2)),
        ],
    ),
    "ca-qc": (
        "Québec",
        "CA",
        [
            ("poecile-atricapillus", _YEAR_ROUND),
            ("cyanocitta-cristata", _scaled(_YEAR_ROUND, 0.9)),
            ("junco-hyemalis", _scaled(_WINTER_ONLY, 0.8)),
            ("turdus-migratorius", _scaled(_SUMMER_ONLY, 0.7)),
            ("anas-platyrhynchos", _scaled(_YEAR_ROUND, 0.5)),
            ("gavia-immer", _scaled(_SUMMER_ONLY, 0.5)),
            ("bubo-scandiacus", _scaled(_WINTER_ONLY, 0.4)),
        ],
    ),
    "us-az": (
        "Arizona",
        "US",
        [
            ("turdus-migratorius", _scaled(_YEAR_ROUND, 0.9)),
            ("buteo-jamaicensis", _scaled(_YEAR_ROUND, 0.8)),
            ("spinus-tristis", _scaled(_WINTER_ONLY, 0.7)),
            ("anas-platyrhynchos", _scaled(_YEAR_ROUND, 0.6)),
            ("archilochus-colubris", _scaled(_SUMMER_ONLY, 0.5)),
            ("junco-hyemalis", _scaled(_WINTER_ONLY, 0.4)),
        ],
    ),
}

# species id -> invented IOC English name, for the optional ``ioc_name`` key (ADR 0027).
IOC_NAMES: dict[str, str] = {"anas-platyrhynchos": "Wild Duck"}

_LICENCES = ("CC-BY-SA-3.0", "CC-BY-4.0", "CC0-1.0", "CC-BY-2.0")


def _photo_bytes(seed: int) -> bytes:
    # A distinct solid colour per photo gives each a distinct content hash.
    colour = ((seed * 67) % 256, (seed * 131 + 40) % 256, (seed * 29 + 90) % 256)
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(buf, "WEBP", quality=50, method=6)
    return buf.getvalue()


def _mp3_bytes(freq: int) -> bytes:
    # Small and bit-exact: mono 16 kHz, 24 kbit/s, no metadata, so a re-run is byte-identical.
    cmd = [
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=1",
        "-ac", "1", "-ar", "16000", "-b:a", "24k", "-map_metadata", "-1",
        "-fflags", "+bitexact", "-flags:a", "+bitexact", "-f", "mp3", "-",
    ]  # fmt: skip
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def _record(kind: str, sid: str, n: int, seed: int) -> AssetRecord:
    licence = _LICENCES[seed % len(_LICENCES)]
    what = "photo" if kind == "photo" else "recording"
    return AssetRecord(
        source="fixture",
        source_asset_id=f"{sid}-{kind}-{n}",
        source_url=f"https://example.org/fixture/{sid}/{kind}/{n}",
        file_url=f"https://example.org/fixture/{sid}/{kind}/{n}/file",
        licence_id=licence,
        licence_url=licence_url(licence),
        creator=f"Fixture {'Photographer' if kind == 'photo' else 'Recordist'} {seed % 7 + 1}",
        title=f"{sid.replace('-', ' ').title()} {what} {n}",
        modifications=("resized",) if kind == "photo" else ("trimmed", "normalized"),
        retrieved_at=RETRIEVED,
    )


def build(out_dir: Path) -> None:
    for stale in (*out_dir.glob("*.json"), out_dir / "media", out_dir / "regions"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()

    entries: dict[str, SpeciesEntry] = {}
    provenance: dict[str, ProvenanceEntry] = {}
    seed = 0
    for sid, name, sci, n_photos, n_audio, tone in SPECIES:
        refs: dict[str, list[MediaRef]] = {"photo": [], "audio": []}
        for kind, count in (("photo", n_photos), ("audio", n_audio)):
            for n in range(1, count + 1):
                seed += 1
                if kind == "photo":
                    data, ext = _photo_bytes(seed), "webp"
                else:
                    data, ext = _mp3_bytes(tone + 40 * (n - 1)), "mp3"
                file = write_media(out_dir, data, ext)
                record = _record(kind, sid, n, seed)
                refs[kind].append(MediaRef(file, len(data), render_credit(kind, record)))
                provenance[file] = ProvenanceEntry(
                    record=record, species_id=sid, kind=kind,  # type: ignore[arg-type]
                    token=f"fixture:{sid}-{kind}-{n}",
                )  # fmt: skip
        entries[sid] = SpeciesEntry(name, sci, refs["photo"], refs["audio"], IOC_NAMES.get(sid, ""))

    region_files = [RegionFile(slug, list(rows)) for slug, (_, _, rows) in REGIONS.items()]
    manifest = Manifest(
        catalog_version=RETRIEVED,
        base_url=PLACEHOLDER_BASE_URL,
        gadm_version="4.1",
        species_file="species.00000000.json",  # recomputed by write_catalog
        regions=[
            RegionRef(slug, name, country, "regions/x.00000000.json", 0)
            for slug, (name, country, _) in REGIONS.items()
        ],
        dataset_credits=[
            DatasetCredit(
                text="eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF (fixture)",
                licence_id="CC-BY-4.0",
                url="https://example.org/fixture/dataset",
                modifications="filtered and ranked by region",
            )
        ],
        total_bytes=0,
        eod_version="fixture",
    )
    write_catalog(
        out_dir, manifest, region_files, SpeciesFile(entries), ProvenanceFile(provenance)
    )
    load_catalog(out_dir)  # the writer validated the parts; this checks the directory as a whole


if __name__ == "__main__":
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg must be on PATH")
    build(OUT_DIR)
    size = sum(p.stat().st_size for p in OUT_DIR.rglob("*") if p.is_file())
    print(f"wrote {OUT_DIR} ({size} bytes including this script)")
