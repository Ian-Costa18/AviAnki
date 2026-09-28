"""The two source contracts (ADR 0007).

A `SpeciesSource` answers "which species occur in this region, how often, when".
An `AssetSource` offers `Candidate` photos/recordings for species, fetches the one
the pipeline picks, and turns a pin token back into a candidate.

**Absence is not failure.** Every method returns an empty list (or omits a key)
when the source has nothing, and raises `SourceError` when it couldn't find out:
timeouts, 429/5xx after retries, `BudgetExhausted`, malformed responses. A source
never turns an error into an empty result.

Sources are pure: no disk, clocks or sleeps. They make requests through an
injected `avianki.core.http.HttpClient`, which enforces their declared `Limits`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from avianki.core.http import BudgetExhausted, Limits, SourceError
from avianki.core.licences import AssetRecord

__all__ = [
    "AssetKind",
    "AssetSource",
    "BudgetExhausted",
    "Candidate",
    "FetchedAsset",
    "Limits",
    "Region",
    "RegionId",
    "SourceError",
    "SpeciesId",
    "SpeciesRecord",
    "SpeciesSource",
]

SpeciesId: TypeAlias = str
"""Minted species id, e.g. ``cardinalis-cardinalis`` (ADR 0008)."""

RegionId: TypeAlias = str
"""Region slug, e.g. ``us-ma`` (ADR 0008)."""


class AssetKind(Enum):
    PHOTO = "photo"
    AUDIO = "audio"
    DESCRIPTION = "description"


@dataclass(frozen=True)
class Region:
    """A GADM level-1 region (ADR 0008)."""

    slug: RegionId
    name: str
    country: str
    gadm_gid: str


@dataclass(frozen=True)
class SpeciesRecord:
    """One species in one region's list, as a species source reports it.

    ``species_id`` is None when the source doesn't know our minted id; the pipeline
    maps ``source_key`` (e.g. a GBIF speciesKey) through ``species.csv``.
    ``monthly`` holds 12 relative frequencies 0–255, January first.
    """

    species_id: SpeciesId | None
    sci_name: str
    common_name: str
    source_key: str
    rank: int  # 1 = most frequent in the region
    monthly: tuple[int, ...]
    count: int

    def __post_init__(self) -> None:
        if len(self.monthly) != 12 or any(not 0 <= v <= 255 for v in self.monthly):
            raise ValueError(f"monthly must be 12 values in 0..255, got {self.monthly!r}")
        if self.rank < 1:
            raise ValueError(f"rank starts at 1, got {self.rank}")


@dataclass(frozen=True)
class Candidate:
    """An asset a source offers, before download: metadata and licence record only.

    ``token`` is the opaque, source-native pin token (`AssetSource.resolve_pin`).
    The last three fields are optional ranking/filter hints the pipeline reads
    without knowing which source produced them; None means the source doesn't say.
    """

    species_id: SpeciesId
    kind: AssetKind
    token: str
    record: AssetRecord
    width: int | None = None  # pixels, photos: the 800 px long-side filter (ADR 0011)
    height: int | None = None
    agreements: int | None = None  # community ID agreements: iNat ranking (ADR 0011)


@dataclass(frozen=True)
class FetchedAsset:
    """A downloaded asset: bytes plus its final licence record."""

    candidate: Candidate
    data: bytes
    content_type: str
    record: AssetRecord


class SpeciesSource(ABC):
    """Supplies region lists. ``republishable=False`` keeps it out of the catalog."""

    name: str
    republishable: bool

    @abstractmethod
    def regions(self) -> list[Region]:
        """Every region this source can list. Raises `SourceError` on failure."""

    @abstractmethod
    def species_for(self, region: RegionId) -> list[SpeciesRecord]:
        """The region's species in rank order.

        Returns ``[]`` when the source has no records for the region; raises
        `SourceError` when it couldn't find out. Never an empty list for an error.
        """


class AssetSource(ABC):
    """Supplies photos/audio/descriptions. Throttling and caching are the client's job."""

    name: str
    supplies: frozenset[AssetKind]
    republishable: bool
    limits: Limits  # declared here, enforced by core.http

    @abstractmethod
    def candidates(
        self, species: list[SpeciesId], kind: AssetKind, limit: int
    ) -> dict[SpeciesId, list[Candidate]]:
        """Up to ``limit`` candidates of ``kind`` per species, best first, metadata only.

        A species with nothing gets ``[]`` or is omitted. Raises `SourceError` on any
        failure (the whole batch fails; the pipeline keeps previous entries).
        """

    @abstractmethod
    def fetch(self, candidate: Candidate) -> FetchedAsset:
        """Download the candidate's bytes. Raises `SourceError` on failure."""

    @abstractmethod
    def resolve_pin(self, token: str) -> Candidate:
        """Turn a pin token back into a candidate.

        Raises `SourceError` if the token no longer resolves (deleted, relicensed) or
        the lookup fails; there is no "empty" answer to a pin.
        """
