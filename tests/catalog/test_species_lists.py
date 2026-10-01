"""Tests for avianki.catalog.species_lists — a fake species source, no network."""

from __future__ import annotations

import pytest

from avianki.core.http import SourceError
from avianki.sources.contract import Region, SpeciesRecord, SpeciesSource
from avianki.sources.gbif import DroppedMinority, NameFallback, ReResolved
from avianki.catalog.species_lists import build_species_lists, group_re_resolved, render_report
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


def test_species_totals_sum_record_counts_across_regions_for_kept_species_only():
    source = FakeSource({
        "us-ri": [
            rec("Turdus migratorius", "American Robin", 9510564, 1, count=700),
            rec("Cardinalis cardinalis", "Northern Cardinal", 2490384, 2, count=200),
            rec("Zonotrichia albicollis", "White-throated Sparrow", 9515886, 3, count=5),
        ],
        "us-ma": [rec("Turdus migratorius", "American Robin", 9510564, 1, count=1300)],
    })
    result = build_species_lists(source, [RI, MA], SpeciesTable([ROBIN]), top_n=2)
    assert result.species_totals == {"turdus-migratorius": 2000, "cardinalis-cardinalis": 200}


def test_a_failed_region_adds_nothing_to_species_totals():
    source = FakeSource({
        "us-ri": SourceError("gbif is down"),
        "us-ma": [rec("Turdus migratorius", "American Robin", 9510564, 1, count=40)],
    })
    result = build_species_lists(source, [RI, MA], SpeciesTable([ROBIN]))
    assert result.species_totals == {"turdus-migratorius": 40}


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


class NamingSource(FakeSource):
    """A source that names new species by eBird and records who it was asked about."""

    def __init__(self, lists, names):
        super().__init__(lists)
        self.names = names
        self.named: list[str] = []

    def mint_name(self, record):
        self.named.append(record.sci_name)
        return self.names.get(record.sci_name, (record.common_name, "ioc"))


def test_a_new_species_takes_the_name_the_source_gives_and_a_known_one_is_never_asked_about():
    source = NamingSource(
        {"us-ri": [rec("Turdus migratorius", "American Robin", 9510564, 1),
                   rec("Pluvialis squatarola", "Grey Plover", 2480283, 2)]},
        {"Pluvialis squatarola": ("Black-bellied Plover", "eod-record")},
    )
    robin = SpeciesRow("turdus-migratorius", "Turdus migratorius", "Robin from the csv", gbif_key=9510564)
    table = SpeciesTable([robin])
    result = build_species_lists(source, [RI], table)
    assert source.named == ["Pluvialis squatarola"]
    assert table.get("turdus-migratorius").common_name == "Robin from the csv"
    assert [r.common_name for r in result.minted] == ["Black-bellied Plover"]
    assert result.minted_name_from == {"pluvialis-squatarola": "eod-record"}
    assert "| pluvialis-squatarola | Pluvialis squatarola | Black-bellied Plover | eod-record |" in render_report(
        result, [RI], 400)


def test_a_species_minted_in_one_region_is_not_named_again_in_the_next():
    record = rec("Pluvialis squatarola", "Grey Plover", 2480283, 1)
    source = NamingSource({"us-ri": [record], "us-dc": [record]}, {})
    build_species_lists(source, [RI, DC], SpeciesTable())
    assert source.named == ["Pluvialis squatarola"]


def test_a_source_without_mint_name_mints_with_the_name_it_reported():
    result = build_species_lists(FakeSource({"us-ri": [rec("Pluvialis squatarola", "Grey Plover", 1, 1)]}), [RI],
                                 SpeciesTable())
    assert [r.common_name for r in result.minted] == ["Grey Plover"]


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


def test_an_empty_region_is_a_failure_not_an_empty_list():
    result = build_species_lists(FakeSource({"us-ri": []}), [RI], SpeciesTable())
    assert result.region_files == {}
    assert "us-ri" in result.failed
    assert not result.ok


def test_unexpected_errors_are_not_swallowed():
    with pytest.raises(ZeroDivisionError):
        build_species_lists(FakeSource({"us-ri": ZeroDivisionError()}), [RI], SpeciesTable())


def test_species_without_an_ioc_match_are_reported():
    fb = NameFallback("10542232", "Falco atricapillus", "American Goshawk", "eod-record")
    source = FakeSource({"us-ri": [rec("Falco atricapillus", "American Goshawk", 10542232, 1)]}, fallbacks=[fb])
    result = build_species_lists(source, [RI], SpeciesTable())
    assert result.no_ioc_match == [fb]


def test_species_without_an_ioc_match_are_held_back_not_minted():
    fb = NameFallback("10542232", "Falco atricapillus", "American Goshawk", "eod-record")
    source = FakeSource({"us-ri": [
        rec("Falco atricapillus", "American Goshawk", 10542232, 1),
        rec("Anas rubripes", "American Black Duck", 2, 2),
    ]}, fallbacks=[fb])
    table = SpeciesTable()
    result = build_species_lists(source, [RI], table)
    assert [s[0] for s in result.region_files["us-ri"]["species"]] == ["anas-rubripes"]
    assert [r.id for r in result.minted] == ["anas-rubripes"]
    assert "falco-atricapillus" not in table


def test_an_unmintable_name_is_skipped_and_reported():
    source = FakeSource({"us-ri": [
        rec("Anas platyrhynchos × rubripes", "hybrid", 1, 1),
        rec("Anas rubripes", "American Black Duck", 2, 2),
    ]})
    result = build_species_lists(source, [RI], SpeciesTable())
    assert [s[0] for s in result.region_files["us-ri"]["species"]] == ["anas-rubripes"]
    assert [(r.source_key, r.sci_name) for r in result.unmintable] == [("1", "Anas platyrhynchos × rubripes")]


# ── ADR 0024: keys named by eBird's own names ────────────────────────────────────


class ReResolvingSource(FakeSource):
    """A source that reports the keys it re-resolved and the records it dropped (ADR 0024)."""

    def __init__(self, lists, re_resolved=(), dropped=(), **kwargs):
        super().__init__(lists, **kwargs)
        self._re_resolved = list(re_resolved)
        self._dropped = list(dropped)

    def re_resolved(self):
        return self._re_resolved

    def dropped_minorities(self):
        return self._dropped


CIRCUS_MOVED = ReResolved("2480487", "us-ma", "Circus cyaneus", "Hen Harrier", "Circus hudsonius",
                          "Northern Harrier", 0.96)
CIRCUS_MOVED_RI = ReResolved("2480487", "us-ri", "Circus cyaneus", "Hen Harrier", "Circus hudsonius",
                             "Northern Harrier", 0.6)
SWAMPHEN_DROPPED = DroppedMinority("2474416", "us-az", "Porphyrio porphyrio", "Western Swamphen", 0.7,
                                   ("Porphyrio poliocephalus",))


def test_a_re_resolved_record_mints_its_own_species_beside_the_one_that_owns_the_backbone_key():
    hen = SpeciesRow("circus-cyaneus", "Circus cyaneus", "Hen Harrier", gbif_key=2480487)
    # the source hands the chosen species' own backbone key, not the lumped 2480487
    source = FakeSource({"us-ma": [rec("Circus hudsonius", "Northern Harrier", 6101217, 1)]})
    table = SpeciesTable([hen])
    result = build_species_lists(source, [MA], table)
    assert [s[0] for s in result.region_files["us-ma"]["species"]] == ["circus-hudsonius"]
    assert result.minted == [SpeciesRow("circus-hudsonius", "Circus hudsonius", "Northern Harrier",
                                        gbif_key=6101217)]
    assert table.by_gbif_key(2480487).id == "circus-cyaneus"


def test_re_resolved_and_dropped_items_are_carried_into_the_result():
    source = ReResolvingSource({"us-ma": [rec("Circus hudsonius", "Northern Harrier", 6101217, 1)]},
                               re_resolved=[CIRCUS_MOVED], dropped=[SWAMPHEN_DROPPED])
    result = build_species_lists(source, [MA], SpeciesTable())
    assert result.re_resolved == [CIRCUS_MOVED]
    assert result.dropped_minorities == [SWAMPHEN_DROPPED]


def test_a_source_that_does_not_report_re_resolution_has_none():
    result = build_species_lists(FakeSource({"us-ri": [rec("Turdus migratorius", "American Robin", 9510564, 1)]}),
                                 [RI], SpeciesTable([ROBIN]))
    assert result.re_resolved == []
    assert result.dropped_minorities == []


def test_group_re_resolved_folds_the_regions_of_one_key_into_a_share_range():
    (group,) = group_re_resolved([CIRCUS_MOVED_RI, CIRCUS_MOVED])
    assert (group.source_key, group.sci_name, group.regions) == ("2480487", "Circus hudsonius", ("us-ma", "us-ri"))
    assert group.share == "60-96%"
    assert group_re_resolved([CIRCUS_MOVED])[0].share == "96%"


def test_the_report_shows_re_resolved_keys_and_dropped_records():
    source = ReResolvingSource({"us-ma": [rec("Circus hudsonius", "Northern Harrier", 6101217, 1)]},
                               re_resolved=[CIRCUS_MOVED_RI, CIRCUS_MOVED], dropped=[SWAMPHEN_DROPPED])
    result = build_species_lists(source, [MA], SpeciesTable())
    md = render_report(result, [MA], 100)
    assert "- Backbone keys named by eBird's own names, not the IOC entry for the key: 1" in md
    assert "## Re-resolved keys (ADR 0024)" in md
    assert "| 2480487 | Hen Harrier (Circus cyaneus) | Northern Harrier (Circus hudsonius) | 60-96% | us-ma, us-ri |" in md
    assert "## Records dropped from split keys (over 10%)" in md
    assert "| 2474416 | us-az | Western Swamphen (Porphyrio porphyrio) | 70% | Porphyrio poliocephalus |" in md


def test_the_report_has_no_re_resolved_sections_when_nothing_moved():
    result = build_species_lists(FakeSource({"us-ri": [rec("Turdus migratorius", "American Robin", 9510564, 1)]}),
                                 [RI], SpeciesTable([ROBIN]))
    md = render_report(result, [RI], 100)
    assert "Re-resolved keys" not in md
    assert "Records dropped" not in md
    assert "named by eBird's own names, not the IOC entry for the key: 0" in md
