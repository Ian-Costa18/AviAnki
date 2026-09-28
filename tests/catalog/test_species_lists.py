"""Tests for avianki.catalog.species_lists — a fake species source, no network."""

from __future__ import annotations

import pytest

from avianki.core.http import SourceError
from avianki.sources.contract import Region, SpeciesRecord, SpeciesSource
from avianki.sources.gbif import NameFallback
from avianki.catalog.species_lists import build_species_lists
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

MA = Region("us-ma", "Massachusetts", "US", "USA.22_1")
RI = Region("us-ri", "Rhode Island", "US", "USA.40_1")
DC = Region("us-dc", "District of Columbia", "US", "USA.9_1")

ROBIN = SpeciesRow("turdus-migratorius", "Turdus migratorius", "American Robin", gbif_key=9510564)


def rec(sci: str, common: str, key: int, rank: int, count: int = 100, peak: int = 0) -> SpeciesRecord:
    monthly = tuple(255 if m == peak else 10 for m in range(12))
    return SpeciesRecord(None, sci, common, str(key), rank, monthly, count)


class FakeSource(SpeciesSource):
    name = "fake"
    republishable = True

    def __init__(self, lists, version="2025-08-08 test", fallbacks=()):
        self.lists = lists
        self.version = version
        self.fallbacks = list(fallbacks)
        self.asked: list[str] = []

    def regions(self):
        return [MA, RI, DC]

    def species_for(self, region):
        self.asked.append(region)
        answer = self.lists[region]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def dataset_version(self):
        return self.version

    def name_fallbacks(self):
        return self.fallbacks


def test_region_file_is_species_ids_and_monthly_in_rank_order():
    source = FakeSource({
        "us-ri": [
            rec("Turdus migratorius", "American Robin", 9510564, 1, peak=3),
            rec("Cardinalis cardinalis", "Northern Cardinal", 2490384, 2),
        ],
    })
    result = build_species_lists(source, [RI], SpeciesTable([ROBIN]))
    assert result.region_files == {
        "us-ri": {
            "slug": "us-ri",
            "species": [
                ["turdus-migratorius", [10, 10, 10, 255, 10, 10, 10, 10, 10, 10, 10, 10]],
                ["cardinalis-cardinalis", [255] + [10] * 11],
            ],
        }
    }
    assert result.species_counts == {"us-ri": 2}
    assert result.dataset_version == "2025-08-08 test"


def test_new_species_are_minted_and_reported_once():
    source = FakeSource({
        "us-ri": [rec("Cardinalis cardinalis", "Northern Cardinal", 2490384, 1)],
        "us-dc": [rec("Cardinalis cardinalis", "Northern Cardinal", 2490384, 1)],
    })
    table = SpeciesTable([ROBIN])
    result = build_species_lists(source, [RI, DC], table)
    assert result.minted == [SpeciesRow("cardinalis-cardinalis", "Cardinalis cardinalis", "Northern Cardinal",
                                        gbif_key=2490384)]
    assert table.by_gbif_key(2490384).id == "cardinalis-cardinalis"


def test_a_known_gbif_key_keeps_its_id_even_after_an_ioc_rename():
    renamed = rec("Turdus newname", "Robin Renamed", 9510564, 1)
    result = build_species_lists(FakeSource({"us-ri": [renamed]}), [RI], SpeciesTable([ROBIN]))
    assert result.region_files["us-ri"]["species"][0][0] == "turdus-migratorius"
    assert result.minted == []


def test_an_ioc_name_live_under_another_key_reuses_that_id():
    other_key = rec("Turdus migratorius", "American Robin", 111, 1)
    result = build_species_lists(FakeSource({"us-ri": [other_key]}), [RI], SpeciesTable([ROBIN]))
    assert result.region_files["us-ri"]["species"][0][0] == "turdus-migratorius"
    assert result.minted == []


def test_keeps_the_top_n_by_rank():
    records = [rec(f"Genus s{chr(97 + i)}", f"Bird {i}", 1000 + i, i + 1, count=100 - i) for i in range(5)]
    shuffled = records[3:] + records[:3]
    result = build_species_lists(FakeSource({"us-ri": shuffled}), [RI], SpeciesTable(), top_n=3)
    assert [s[0] for s in result.region_files["us-ri"]["species"]] == ["genus-sa", "genus-sb", "genus-sc"]
    assert result.species_counts == {"us-ri": 5}
    assert len(result.minted) == 3  # only listed species are minted


def test_a_failed_region_is_recorded_and_the_rest_carry_on():
    source = FakeSource({
        "us-ma": SourceError("HTTP 503 for https://api.gbif.org/..."),
        "us-ri": [rec("Turdus migratorius", "American Robin", 9510564, 1)],
    })
    result = build_species_lists(source, [MA, RI], SpeciesTable([ROBIN]))
    assert "us-ma" not in result.region_files  # failure is never an empty list
    assert result.failed == {"us-ma": "HTTP 503 for https://api.gbif.org/..."}
    assert list(result.region_files) == ["us-ri"]
    assert not result.ok


def test_an_empty_region_is_absence_not_failure():
    result = build_species_lists(FakeSource({"us-ri": []}), [RI], SpeciesTable())
    assert result.region_files == {"us-ri": {"slug": "us-ri", "species": []}}
    assert result.ok


def test_unexpected_errors_are_not_swallowed():
    with pytest.raises(ZeroDivisionError):
        build_species_lists(FakeSource({"us-ri": ZeroDivisionError()}), [RI], SpeciesTable())


def test_species_without_an_ioc_match_are_reported():
    fb = NameFallback("10542232", "Falco atricapillus", "American Goshawk", "eod-record")
    source = FakeSource({"us-ri": [rec("Falco atricapillus", "American Goshawk", 10542232, 1)]}, fallbacks=[fb])
    result = build_species_lists(source, [RI], SpeciesTable())
    assert result.no_ioc_match == [fb]


def test_an_unmintable_name_is_skipped_and_reported():
    source = FakeSource({"us-ri": [
        rec("Anas platyrhynchos × rubripes", "hybrid", 1, 1),
        rec("Anas rubripes", "American Black Duck", 2, 2),
    ]})
    result = build_species_lists(source, [RI], SpeciesTable())
    assert [s[0] for s in result.region_files["us-ri"]["species"]] == ["anas-rubripes"]
    assert [(r.source_key, r.sci_name) for r in result.unmintable] == [("1", "Anas platyrhynchos × rubripes")]
