"""Source smoke tests against the live APIs (ADR 0020 check 1; run with --integration).

For three fixed species (Northern Cardinal: common; Brown Pelican: a known audio gap; Whimbrel: a
known taxonomy split) every registered asset source must return photo candidates, and whatever it
returns, for photos and audio, must carry a complete licence record. Audio may legitimately be
absent: a source then returns an empty result. It must never raise. A network failure is a
failure, never a skip.

The sources are built the way the catalog build builds them (`catalog_cli.new_session`,
`new_client`, `new_registry`), with no HTTP cache, so this really hits the network.
"""

from __future__ import annotations

import pytest

from avianki import catalog_cli
from avianki.core.licences import is_allowed
from avianki.sources.contract import AssetKind, Candidate
from avianki.sources.registry import ORDER, Registry
from avianki.taxonomy.species import load_species

CARDINAL = "cardinalis-cardinalis"
PELICAN = "pelecanus-occidentalis"
WHIMBREL = "numenius-phaeopus"
SPECIES = [CARDINAL, PELICAN, WHIMBREL]

# The registered sources, read from the fill order so a source added there is tested with no edit here.
SOURCE_NAMES = sorted({name for names in ORDER.values() for name in names})
LIMIT = 5  # candidates per species; the build asks for about this many

Offers = dict[tuple[str, AssetKind], dict[str, list[Candidate]]]


@pytest.fixture(scope="module")
def registry() -> Registry:
    client = catalog_cli.new_client(None, catalog_cli.new_session())  # no cache: this must hit the network
    return catalog_cli.new_registry(client, load_species(), None)


@pytest.fixture(scope="module")
def offers(registry: Registry) -> Offers:
    """Each source's answer per kind it supplies, for all three species. A raise fails the tests using it."""
    answers: Offers = {}
    for kind in (AssetKind.PHOTO, AssetKind.AUDIO):
        for source in registry.asset_sources(kind):
            answers[(source.name, kind)] = source.candidates(SPECIES, kind, LIMIT)
    return answers


def assert_complete(candidate: Candidate, species_id: str, kind: AssetKind) -> None:
    record = candidate.record
    where = f"{record.source} {record.source_asset_id}"
    assert candidate.species_id == species_id, where
    assert candidate.kind is kind, where
    assert candidate.token, where
    assert record.missing_required_fields() == [], f"{where}: incomplete record {record.missing_required_fields()}"
    assert is_allowed(record.licence_id), f"{where}: licence {record.licence_id!r} is not allowed"
    assert record.file_url.startswith("https://"), where


def test_the_registry_holds_the_sources_the_check_expects(registry: Registry) -> None:
    """Offline. If a source is added to `ORDER` without this check knowing, say so."""
    assert SOURCE_NAMES == ["commons", "inaturalist"]
    for kind in (AssetKind.PHOTO, AssetKind.AUDIO):
        assert [s.name for s in registry.asset_sources(kind)] == list(ORDER[kind])


@pytest.mark.integration
@pytest.mark.parametrize("species_id", SPECIES)
@pytest.mark.parametrize("source_name", SOURCE_NAMES)
def test_every_source_offers_complete_photo_candidates(offers: Offers, source_name: str, species_id: str) -> None:
    found = offers[(source_name, AssetKind.PHOTO)].get(species_id, [])
    print(f"\n{source_name} photos for {species_id}: {len(found)}")
    assert found, f"{source_name} returned no photo candidates for {species_id}"
    assert len(found) <= LIMIT
    for candidate in found:
        assert_complete(candidate, species_id, AssetKind.PHOTO)


@pytest.mark.integration
@pytest.mark.parametrize("source_name", SOURCE_NAMES)
def test_audio_candidates_are_complete_and_absence_is_an_empty_result(offers: Offers, source_name: str) -> None:
    """The fixture already proved the call returned instead of raising. What came back must be complete."""
    answer = offers[(source_name, AssetKind.AUDIO)]
    assert set(answer) <= set(SPECIES)
    for species_id in SPECIES:
        found = answer.get(species_id, [])  # an omitted key is absence too
        print(f"\n{source_name} audio for {species_id}: {len(found)}")
        assert isinstance(found, list)
        assert len(found) <= LIMIT
        for candidate in found:
            assert_complete(candidate, species_id, AssetKind.AUDIO)


@pytest.mark.integration
@pytest.mark.parametrize("species_id", [CARDINAL, WHIMBREL])
def test_some_source_has_audio_for_the_species_that_have_it(offers: Offers, species_id: str) -> None:
    per_source = {name: len(offers[(name, AssetKind.AUDIO)].get(species_id, [])) for name in SOURCE_NAMES}
    assert any(per_source.values()), f"no source has audio for {species_id}: {per_source}"


@pytest.mark.integration
def test_brown_pelican_audio_gap_is_reported_as_absence(registry: Registry) -> None:
    """Brown Pelican is a known audio gap: a source with nothing says so with an empty result.

    Asked about the pelican alone (the build's per-species case), no source may raise. What is
    there drifts with upstream, so emptiness isn't required; anything returned must be complete.
    """
    counts: dict[str, int] = {}
    for source in registry.asset_sources(AssetKind.AUDIO):
        found = source.candidates([PELICAN], AssetKind.AUDIO, LIMIT).get(PELICAN, [])
        counts[source.name] = len(found)
        for candidate in found:
            assert_complete(candidate, PELICAN, AssetKind.AUDIO)
    print(f"\nBrown Pelican audio candidates by source: {counts}")
