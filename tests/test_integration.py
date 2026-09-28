"""
Integration tests: hit real network sources.

Run with:  uv run pytest --integration
Skipped by default to avoid network access in normal test runs.

Per ADR 0020 (interim, until the new sources land in M2–M3) this covers only
the eBird smoke test. allaboutbirds.org is dormant (ADR 0002) and not
monitored. A network failure is a test failure; the only allowed skip is
eBird when EBIRD_API_KEY is not set.
"""

import os

import pytest
from dotenv import load_dotenv

from avianki import ebird

load_dotenv()

EBIRD_REGION = "US-MA"
EBIRD_LIMIT = 3


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("EBIRD_API_KEY"), reason="EBIRD_API_KEY not set")
def test_ebird_fetch_species_smoke():
    """eBird returns a resolved species list for a known region."""
    species = ebird.fetch_species(EBIRD_REGION, limit=EBIRD_LIMIT)

    assert isinstance(species, list)
    assert 0 < len(species) <= EBIRD_LIMIT, f"Expected 1–{EBIRD_LIMIT} species, got {len(species)}"
    for sp in species:
        assert isinstance(sp, dict)
        for key in ("speciesCode", "comName", "sciName"):
            assert isinstance(sp.get(key), str) and sp[key], f"Missing/empty {key!r} in {sp}"
