"""Sources registered for catalog builds, and the fill order per asset kind.

Adding a source = one folder under ``sources/`` plus its name in `ORDER` (ADR 0007).
The order is freest first (ADR 0005). Only republishable sources may register:
eBird (``republishable=False``) is used directly by the CLI, never registered here.
"""

from __future__ import annotations

from collections.abc import Mapping

from avianki.sources.contract import AssetKind, AssetSource, SpeciesSource

ORDER: Mapping[AssetKind, tuple[str, ...]] = {
    AssetKind.PHOTO: ("commons", "inaturalist"),
    AssetKind.AUDIO: ("commons", "inaturalist"),
    AssetKind.DESCRIPTION: (),
}


class Registry:
    def __init__(self, order: Mapping[AssetKind, tuple[str, ...]] = ORDER) -> None:
        self._order = order
        self._species: dict[str, SpeciesSource] = {}
        self._assets: dict[str, AssetSource] = {}

    def register(self, source: SpeciesSource | AssetSource) -> None:
        """Register a source for catalog builds. Raises ValueError if it isn't
        republishable or its name is already taken."""
        if not source.republishable:
            raise ValueError(f"source {source.name!r} is not republishable and can't feed the catalog")
        if source.name in self._species or source.name in self._assets:
            raise ValueError(f"source {source.name!r} is already registered")
        if isinstance(source, SpeciesSource):
            self._species[source.name] = source
        elif isinstance(source, AssetSource):
            self._assets[source.name] = source
        else:
            raise TypeError(f"not a source: {source!r}")

    def species_sources(self) -> list[SpeciesSource]:
        """Registered species sources, in registration order."""
        return list(self._species.values())

    def asset_sources(self, kind: AssetKind) -> list[AssetSource]:
        """Registered sources supplying ``kind``, in `ORDER`. Names in the order list
        that aren't registered are skipped; registered sources not in it are unused."""
        found = (self._assets.get(name) for name in self._order.get(kind, ()))
        return [s for s in found if s is not None and kind in s.supplies]


_default = Registry()


def register(source: SpeciesSource | AssetSource) -> None:
    _default.register(source)


def species_sources() -> list[SpeciesSource]:
    return _default.species_sources()


def asset_sources(kind: AssetKind) -> list[AssetSource]:
    return _default.asset_sources(kind)
