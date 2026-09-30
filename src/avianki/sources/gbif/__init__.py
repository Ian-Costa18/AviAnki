"""GBIF species source: region lists from the eBird Observation Dataset (ADR 0004, 0024)."""

from avianki.sources.gbif.source import (
    EOD_DATASET_KEY,
    IOC_DATASET_KEY,
    LIMITS,
    DroppedMinority,
    GbifSpeciesSource,
    NameFallback,
    ReResolved,
)

__all__ = [
    "EOD_DATASET_KEY",
    "IOC_DATASET_KEY",
    "LIMITS",
    "DroppedMinority",
    "GbifSpeciesSource",
    "NameFallback",
    "ReResolved",
]
