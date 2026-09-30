"""A smoke test of the real eBird API (run with --integration; needs EBIRD_API_KEY)."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from avianki.core.http import HttpClient
from avianki.sources.ebird import EbirdSpeciesSource


@pytest.mark.integration
def test_the_live_ebird_list_for_a_small_region() -> None:
    load_dotenv()
    key = os.environ.get("EBIRD_API_KEY", "").strip()
    if not key:
        pytest.skip("EBIRD_API_KEY is not set")
    records = EbirdSpeciesSource(HttpClient(cache_dir=None), key).species_for("US-MA-017")
    assert len(records) > 100
    assert [r.rank for r in records] == list(range(1, len(records) + 1))
    assert all(r.source_key and r.sci_name and r.common_name for r in records)
