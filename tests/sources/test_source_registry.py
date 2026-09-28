"""Tests for avianki.sources.registry."""

from __future__ import annotations

import pytest

from avianki.sources import registry
from avianki.sources.contract import AssetKind, AssetSource, Limits, SpeciesSource
from avianki.sources.registry import ORDER, Registry

LIMITS = Limits(requests_per_second=1.0, max_concurrency=1, daily_request_budget=None, needs_secret=None)


class FakeAssets(AssetSource):
    def __init__(self, name, supplies=frozenset({AssetKind.PHOTO, AssetKind.AUDIO}), republishable=True):
        self.name = name
        self.supplies = supplies
        self.republishable = republishable
        self.limits = LIMITS

    def candidates(self, species, kind, limit):
        return {}

    def fetch(self, candidate):
        raise NotImplementedError

    def resolve_pin(self, token):
        raise NotImplementedError


class FakeSpecies(SpeciesSource):
    def __init__(self, name, republishable=True):
        self.name = name
        self.republishable = republishable

    def regions(self):
        return []

    def species_for(self, region):
        return []


def test_default_order_is_commons_then_inaturalist():
    assert ORDER[AssetKind.PHOTO] == ("commons", "inaturalist")
    assert ORDER[AssetKind.AUDIO] == ("commons", "inaturalist")
    assert ORDER[AssetKind.DESCRIPTION] == ()


def test_asset_sources_follow_configured_order_not_registration_order():
    reg = Registry()
    inat, commons = FakeAssets("inaturalist"), FakeAssets("commons")
    reg.register(inat)
    reg.register(commons)
    assert reg.asset_sources(AssetKind.PHOTO) == [commons, inat]
    assert reg.asset_sources(AssetKind.AUDIO) == [commons, inat]
    assert reg.asset_sources(AssetKind.DESCRIPTION) == []


def test_unregistered_names_are_skipped():
    reg = Registry()
    inat = FakeAssets("inaturalist")
    reg.register(inat)
    assert reg.asset_sources(AssetKind.PHOTO) == [inat]
    assert Registry().asset_sources(AssetKind.PHOTO) == []


def test_sources_not_supplying_the_kind_are_skipped():
    reg = Registry()
    commons = FakeAssets("commons", supplies=frozenset({AssetKind.PHOTO}))
    inat = FakeAssets("inaturalist")
    reg.register(commons)
    reg.register(inat)
    assert reg.asset_sources(AssetKind.AUDIO) == [inat]


def test_sources_outside_the_order_list_are_unused():
    reg = Registry()
    reg.register(FakeAssets("xenocanto"))
    assert reg.asset_sources(AssetKind.AUDIO) == []


def test_custom_order():
    reg = Registry(order={AssetKind.PHOTO: ("b", "a")})
    a, b = FakeAssets("a"), FakeAssets("b")
    reg.register(a)
    reg.register(b)
    assert reg.asset_sources(AssetKind.PHOTO) == [b, a]


def test_non_republishable_sources_are_refused():
    reg = Registry()
    with pytest.raises(ValueError, match="republishable"):
        reg.register(FakeSpecies("ebird", republishable=False))
    with pytest.raises(ValueError, match="republishable"):
        reg.register(FakeAssets("commons", republishable=False))
    assert reg.species_sources() == []
    assert reg.asset_sources(AssetKind.PHOTO) == []


def test_duplicate_names_are_refused():
    reg = Registry()
    reg.register(FakeAssets("commons"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(FakeAssets("commons"))


def test_species_sources_in_registration_order():
    reg = Registry()
    a, b = FakeSpecies("gbif"), FakeSpecies("other")
    reg.register(a)
    reg.register(b)
    assert reg.species_sources() == [a, b]


def test_module_level_functions_use_a_default_registry(monkeypatch):
    monkeypatch.setattr(registry, "_default", Registry())
    src = FakeAssets("commons")
    registry.register(src)
    assert registry.asset_sources(AssetKind.PHOTO) == [src]
    gbif = FakeSpecies("gbif")
    registry.register(gbif)
    assert registry.species_sources() == [gbif]
    with pytest.raises(ValueError):
        registry.register(FakeSpecies("ebird", republishable=False))
