"""Fakes for the M3 build pipeline tests: counting asset sources, a scripted BirdNET analyser,
a species source, and real (tiny) image and audio bytes.

The bytes are real so the pipeline's own Pillow and ffmpeg steps run for real; only the
network and the BirdNET model are faked. Nothing here touches the network.
"""

from __future__ import annotations

import io
import itertools
import math
import struct
import wave
from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from avianki.core.http import BudgetExhausted, Limits, SourceError
from avianki.media.verify import WindowScore
from avianki.sources.contract import (
    AssetKind,
    AssetSource,
    Candidate,
    FetchedAsset,
    Region,
    SpeciesRecord,
    SpeciesSource,
)
from avianki.sources.registry import Registry
from avianki.taxonomy.species import SpeciesRow, SpeciesTable
from catalog_fakes import make_record

ROBIN = "turdus-migratorius"
JAY = "cyanocitta-cristata"
CHICKADEE = "poecile-atricapillus"
WREN = "troglodytes-aedon"  # deliberately has no BirdNET label in the table

ROBIN_LABEL = "Turdus migratorius_American Robin"
JAY_LABEL = "Cyanocitta cristata_Blue Jay"
CHICKADEE_LABEL = "Poecile atricapillus_Black-capped Chickadee"
LABELS = [ROBIN_LABEL, JAY_LABEL, CHICKADEE_LABEL, "Cardinalis cardinalis_Northern Cardinal"]

ROWS = (
    SpeciesRow(ROBIN, "Turdus migratorius", "American Robin", gbif_key=1, birdnet_label=ROBIN_LABEL),
    SpeciesRow(JAY, "Cyanocitta cristata", "Blue Jay", gbif_key=2, birdnet_label=JAY_LABEL),
    SpeciesRow(CHICKADEE, "Poecile atricapillus", "Black-capped Chickadee", gbif_key=3, birdnet_label=CHICKADEE_LABEL),
    SpeciesRow(WREN, "Troglodytes aedon", "House Wren", gbif_key=4),
)

PHOTO = AssetKind.PHOTO
AUDIO = AssetKind.AUDIO


def make_table(*ids: str) -> SpeciesTable:
    """A fresh species table (the build may mint into it) of the named rows, default the first three."""
    wanted = ids or (ROBIN, JAY, CHICKADEE)
    return SpeciesTable([r for r in ROWS if r.id in wanted])


# ---------------------------------------------------------------------------------------
# Real bytes
# ---------------------------------------------------------------------------------------


@lru_cache(maxsize=None)
def image_bytes(seed: int = 0, size: tuple[int, int] = (1000, 750)) -> bytes:
    """A JPEG that `process_image` accepts (long side >= 800). Each seed is a different picture."""
    img = Image.new("RGB", size, ((seed * 53) % 256, (seed * 97 + 40) % 256, (seed * 31 + 120) % 256))
    ImageDraw.Draw(img).ellipse(
        (size[0] // 4 + seed, size[1] // 4, 3 * size[0] // 4, 3 * size[1] // 4),
        fill=((seed * 11) % 256, 255 - (seed * 29) % 256, (seed * 7) % 256),
    )
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return out.getvalue()


def small_image_bytes(seed: int = 0) -> bytes:
    """A JPEG under 800 px: `process_image` rejects it."""
    return image_bytes(seed, (600, 400))


@lru_cache(maxsize=None)
def wav_bytes(seed: int = 0, seconds: float = 14.0, rate: int = 22050) -> bytes:
    """A mono WAV tone; each seed has its own pitch so every recording is different."""
    freq = 300 + 90 * seed
    frames = b"".join(
        struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(int(seconds * rate))
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return out.getvalue()


_SEEDS = itertools.count(1)
JUNK_AUDIO = b"this is not an audio file"


# ---------------------------------------------------------------------------------------
# BirdNET
# ---------------------------------------------------------------------------------------


class ScriptedAnalyzer:
    """A stand-in for the BirdNET model: each `predict` call returns the next scripted list of
    3 s window confidences (the last script repeats once the list runs out)."""

    def __init__(self, *scripts: Sequence[float], labels: Sequence[str] = LABELS) -> None:
        self.scripts = [list(s) for s in scripts] or [[0.0]]
        self.labels = list(labels)
        self.calls: list[str] = []

    def predict(self, path: Path, label: str) -> list[WindowScore]:
        self.calls.append(label)
        script = self.scripts.pop(0) if len(self.scripts) > 1 else self.scripts[0]
        return [WindowScore(i * 3.0, i * 3.0 + 3.0, c) for i, c in enumerate(script)]


# ---------------------------------------------------------------------------------------
# Asset sources
# ---------------------------------------------------------------------------------------


class FakeSource(AssetSource):
    """A counting, scriptable asset source. Named "commons" or "inaturalist" so the real
    registry order applies. ``resolve_pin`` accepts ``species_id`` (like Commons)."""

    def __init__(self, name: str, supplies: Iterable[AssetKind] = (PHOTO, AUDIO)) -> None:
        self.name = name
        self.supplies = frozenset(supplies)
        self.republishable = True
        self.limits = Limits(1000.0, 1, None, None)
        self.offers: dict[tuple[str, AssetKind], list[Candidate]] = {}
        self.blobs: dict[str, bytes] = {}
        self.known: dict[str, Candidate] = {}
        self.candidate_errors: dict[str, Exception] = {}  # species id -> raised for any batch holding it
        self.fetch_errors: dict[str, Exception] = {}  # token -> raised by fetch
        self.pin_errors: dict[str, Exception] = {}  # token -> raised by resolve_pin
        self.budget: int | None = None  # calls allowed before BudgetExhausted
        self.calls: list[tuple[Any, ...]] = []
        self.on_call: Callable[[], None] | None = None  # e.g. advance a fake clock

    # -- scripting ---------------------------------------------------------------------

    def add(
        self,
        species_id: str,
        kind: AssetKind,
        token: str,
        data: bytes | None = None,
        *,
        offer: bool = True,
        width: int | None = None,
        height: int | None = None,
        **record: Any,
    ) -> Candidate:
        """Register an asset. ``offer=False`` makes it reachable only through a pin."""
        fields: dict[str, Any] = {
            "source": self.name,
            "source_asset_id": token,
            "source_url": f"https://example.test/{self.name}/{token}",
            "file_url": f"https://example.test/{self.name}/{token}/file",
            "creator": f"Creator {token}",
            "title": f"{token}",
        }
        fields.update(record)
        cand = Candidate(species_id, kind, token, make_record(**fields), width=width, height=height)
        self.known[token] = cand
        if data is None:
            seed = next(_SEEDS)  # every default asset differs from every other, in every source
            data = image_bytes(seed) if kind is PHOTO else wav_bytes(seed)
        self.blobs[token] = data
        if offer:
            self.offers.setdefault((species_id, kind), []).append(cand)
        return cand

    def offer_empty(self, species_id: str, kind: AssetKind) -> None:
        """A real, empty answer: the source looked and has nothing."""
        self.offers[(species_id, kind)] = []

    # -- inspection --------------------------------------------------------------------

    def calls_of(self, what: str) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == what]

    @property
    def fetched(self) -> list[str]:
        return [c[1] for c in self.calls_of("fetch")]

    def candidate_species(self) -> list[str]:
        return [s for c in self.calls_of("candidates") for s in c[1]]

    # -- AssetSource ---------------------------------------------------------------------

    def _spend(self) -> None:
        if self.on_call is not None:
            self.on_call()
        if self.budget is not None and len(self.calls) > self.budget:
            raise BudgetExhausted(f"{self.name}: daily budget spent")

    def candidates(self, species: list[str], kind: AssetKind, limit: int) -> dict[str, list[Candidate]]:
        self.calls.append(("candidates", tuple(species), kind, limit))
        self._spend()
        for sid in species:
            if sid in self.candidate_errors:
                raise self.candidate_errors[sid]
        return {sid: list(self.offers.get((sid, kind), []))[:limit] for sid in species}

    def fetch(self, candidate: Candidate) -> FetchedAsset:
        self.calls.append(("fetch", candidate.token))
        self._spend()
        if candidate.token in self.fetch_errors:
            raise self.fetch_errors[candidate.token]
        return FetchedAsset(candidate, self.blobs[candidate.token], "application/octet-stream", candidate.record)

    def resolve_pin(self, token: str, species_id: str | None = None) -> Candidate:
        self.calls.append(("resolve_pin", token, species_id))
        self._spend()
        if token in self.pin_errors:
            raise self.pin_errors[token]
        if token not in self.known:
            raise SourceError(f"{self.name}: pin {token} no longer resolves")
        return self.known[token]


class FakeSourceNoSpecies(FakeSource):
    """Like iNaturalist: `resolve_pin` takes only the token."""

    def resolve_pin(self, token: str) -> Candidate:  # type: ignore[override]
        return super().resolve_pin(token)


def make_fake_registry(*sources: FakeSource) -> Registry:
    registry = Registry()
    for source in sources:
        registry.register(source)
    return registry


# ---------------------------------------------------------------------------------------
# Species half
# ---------------------------------------------------------------------------------------


REGION_RI = Region("us-ri", "Rhode Island", "US", "USA.40_1")
REGION_DC = Region("us-dc", "District of Columbia", "US", "USA.9_1")
MONTHLY = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120)


class FakeSpeciesSource(SpeciesSource):
    """Region lists from a dict of slug -> species ids in rank order (or an exception)."""

    name = "gbif"
    republishable = True

    def __init__(self, lists: dict[str, list[str] | Exception]) -> None:
        self.lists = lists
        self.calls: list[str] = []

    def regions(self) -> list[Region]:
        return [REGION_RI, REGION_DC]

    def species_for(self, region: str) -> list[SpeciesRecord]:
        self.calls.append(region)
        got = self.lists[region]
        if isinstance(got, Exception):
            raise got
        by_id = {r.id: r for r in ROWS}
        return [
            SpeciesRecord(
                species_id=sid,
                sci_name=by_id[sid].sci_name,
                common_name=by_id[sid].common_name,
                source_key=str(by_id[sid].gbif_key),
                rank=rank,
                monthly=MONTHLY,
                count=1000 - rank,
            )
            for rank, sid in enumerate(got, start=1)
        ]
