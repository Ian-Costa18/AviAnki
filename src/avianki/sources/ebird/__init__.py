"""eBird species source: a region's species list from the eBird API, for ``--ebird`` only (ADR 0017)."""

from avianki.sources.ebird.source import LIMITS, EbirdSpeciesSource, is_region_code

__all__ = ["LIMITS", "EbirdSpeciesSource", "is_region_code"]
