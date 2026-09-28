"""Tests for avianki.sources.contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import avianki.sources as sources_pkg
from avianki.core import http
from avianki.core.licences import AssetRecord
from avianki.sources.contract import (
    AssetKind,
    AssetSource,
    BudgetExhausted,
    Candidate,
    FetchedAsset,
    Limits,
    Region,
    SourceError,
    SpeciesRecord,
    SpeciesSource,
)

RECORD = AssetRecord(
    source="commons",
    source_asset_id="File:X.jpg",
    source_url="https://commons.wikimedia.org/wiki/File:X.jpg",
    file_url="https://upload.wikimedia.org/x.jpg",
    licence_id="CC-BY-4.0",
    licence_url="https://creativecommons.org/licenses/by/4.0/",
    creator="Someone",
    retrieved_at="2026-09-28",
)


def test_reexports_are_the_core_http_objects():
    assert Limits is http.Limits
    assert SourceError is http.SourceError
    assert BudgetExhausted is http.BudgetExhausted
    assert sources_pkg.Limits is http.Limits
    assert sources_pkg.SourceError is http.SourceError


def test_asset_kinds():
    assert {k.name for k in AssetKind} == {"PHOTO", "AUDIO", "DESCRIPTION"}


def test_abcs_cannot_be_instantiated():
    with pytest.raises(TypeError):
        SpeciesSource()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        AssetSource()  # type: ignore[abstract]


def test_species_record_validates_monthly_and_rank():
    ok = SpeciesRecord(None, "Turdus migratorius", "American Robin", "2490719", 1, tuple(range(12)), 10)
    assert ok.species_id is None
    with pytest.raises(ValueError):
        SpeciesRecord(None, "x", "x", "1", 1, (0,) * 11, 1)
    with pytest.raises(ValueError):
        SpeciesRecord(None, "x", "x", "1", 1, (0,) * 11 + (256,), 1)
    with pytest.raises(ValueError):
        SpeciesRecord(None, "x", "x", "1", 0, (0,) * 12, 1)


def test_region_is_frozen():
    r = Region("us-ma", "Massachusetts", "US", "USA.22_1")
    with pytest.raises(FrozenInstanceError):
        r.slug = "x"  # type: ignore[misc]


def test_candidate_and_fetched_asset():
    c = Candidate("turdus-migratorius", AssetKind.PHOTO, "File:X.jpg", RECORD, width=960, height=640)
    assert c.agreements is None
    f = FetchedAsset(c, b"bytes", "image/jpeg", RECORD.with_modification("resized"))
    assert f.record.modifications == ("resized",)
    assert f.candidate.record.modifications == ()


class _EmptySource(SpeciesSource):
    name = "empty"
    republishable = True

    def regions(self):
        return []

    def species_for(self, region):
        return []


def test_concrete_species_source_can_return_empty():
    assert _EmptySource().species_for("us-ma") == []
