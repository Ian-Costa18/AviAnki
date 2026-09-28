"""iNaturalist asset source: research-grade photos (fallback) and audio (ADR 0005, 0011)."""

from avianki.sources.inaturalist.source import (
    AVES_TAXON_ID,
    LIMITS,
    NORTH_AMERICA_PLACES,
    PLAUSIBILITY_MIN_RATIO,
    INaturalistSource,
    PlausibilityFlag,
)

__all__ = ["AVES_TAXON_ID", "LIMITS", "NORTH_AMERICA_PLACES", "PLAUSIBILITY_MIN_RATIO", "INaturalistSource",
           "PlausibilityFlag"]
