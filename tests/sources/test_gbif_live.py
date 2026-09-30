"""The GBIF eBird Observation Dataset against the live API (ADR 0020 check 2; run with --integration).

Uncached, `species_for("us-ma")` makes about 400 extra requests for ADR 0024's verbatim-name
lookups, so this takes several minutes. A network failure is a failure.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from avianki import catalog_cli
from avianki.sources.gbif import GbifSpeciesSource
from avianki.taxonomy.regions import load_regions

MANIFEST_URL = "https://ian-costa18.github.io/AviAnki/catalog/manifest.json"
MIN_SPECIES = 300


def published_eod_version() -> str | None:
    with urllib.request.urlopen(MANIFEST_URL, timeout=60) as response:  # noqa: S310 - https only
        return json.load(response).get("eod_version")


@pytest.mark.integration
def test_the_eod_lists_at_least_300_species_for_massachusetts(record_property) -> None:
    client = catalog_cli.new_client(None, catalog_cli.new_session())  # uncached, as the weekly check intends
    source = GbifSpeciesSource(client, load_regions())

    records = source.species_for("us-ma")
    assert len(records) >= MIN_SPECIES
    assert [r.rank for r in records] == list(range(1, len(records) + 1))
    assert all(r.source_key and r.sci_name and r.common_name for r in records)

    # A new EOD release is news, not a failure: the next catalog build picks it up (ADR 0014).
    live = source.dataset_version()
    published = published_eod_version()
    record_property("eod_version", live)
    record_property("published_eod_version", published or "")
    print(f"\nus-ma: {len(records)} species; EOD dataset version: {live}")
    if live == published:
        print("EOD version matches the published catalog's manifest.")
    else:
        print(f"NOTICE: the EOD version differs from the published catalog's ({published!r}): a new release.")
