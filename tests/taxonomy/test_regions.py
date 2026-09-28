from pathlib import Path

import pytest

from avianki.taxonomy import DATA_DIR
from avianki.taxonomy.regions import RegionRow, RegionTable, load_regions

HEADER = "slug,name,country,gadm_gid,gadm_version,ebird_code\n"


@pytest.fixture(scope="module")
def regions() -> RegionTable:
    return load_regions()


def write(tmp_path: Path, body: str, header: str = HEADER) -> Path:
    p = tmp_path / "regions.csv"
    p.write_text(header + body, encoding="utf-8", newline="")
    return p


# --- the real data/regions.csv ---------------------------------------------------


def test_default_path_is_repo_data_dir():
    assert (DATA_DIR / "regions.csv").is_file()


def test_real_table_has_64_regions(regions):
    rows = list(regions)
    assert len(rows) == len(regions) == 64
    assert sum(r.country == "US" for r in rows) == 51
    assert sum(r.country == "CA" for r in rows) == 13


def test_real_table_keys_are_unique(regions):
    rows = list(regions)
    for field in ("slug", "name", "gadm_gid", "ebird_code"):
        values = [getattr(r, field) for r in rows]
        assert len(set(values)) == 64, field


def test_real_table_is_consistent(regions):
    for r in regions:
        assert r.slug == r.ebird_code.lower()
        assert r.ebird_code.startswith(r.country + "-")
        prefix = {"US": "USA.", "CA": "CAN."}[r.country]
        assert r.gadm_gid.startswith(prefix) and r.gadm_gid.endswith("_1")
    assert regions.gadm_version == "4.1"


def test_real_file_is_sorted_by_slug():
    lines = (DATA_DIR / "regions.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == HEADER.strip()
    slugs = [line.split(",")[0] for line in lines[1:]]
    assert slugs == sorted(slugs)


def test_known_gids(regions):
    # Checked against GBIF's /v1/geocode/gadm/{USA,CAN}/subdivisions and occurrence gadmGid filters.
    assert regions.by_slug("us-ma").gadm_gid == "USA.22_1"
    assert regions.by_slug("us-dc").gadm_gid == "USA.9_1"
    assert regions.by_slug("ca-yt").gadm_gid == "CAN.13_1"


# --- lookups ---------------------------------------------------------------------


def test_by_slug(regions):
    ma = regions.by_slug("us-ma")
    assert ma == RegionRow("us-ma", "Massachusetts", "US", "USA.22_1", "4.1", "US-MA")
    assert regions.by_slug("US-MA") is ma


def test_by_name_is_case_insensitive(regions):
    assert regions.by_name("Massachusetts").slug == "us-ma"
    assert regions.by_name("  massachusetts ").slug == "us-ma"
    assert regions.by_name("NEWFOUNDLAND AND LABRADOR").slug == "ca-nl"


def test_by_name_ignores_accents(regions):
    assert regions.by_name("Quebec").slug == "ca-qc"
    assert regions.by_name("québec").slug == "ca-qc"


def test_by_ebird_is_case_insensitive(regions):
    assert regions.by_ebird("CA-ON").slug == "ca-on"
    assert regions.by_ebird("ca-on").slug == "ca-on"


@pytest.mark.parametrize(
    ("method", "arg"),
    [("by_slug", "us-zz"), ("by_name", "Atlantis"), ("by_ebird", "MX-ROO")],
)
def test_unknown_lookup_raises_helpful_keyerror(regions, method, arg):
    with pytest.raises(KeyError, match=arg):
        getattr(regions, method)(arg)


def test_iteration_is_in_slug_order(tmp_path):
    p = write(tmp_path, "us-ma,Massachusetts,US,USA.22_1,4.1,US-MA\nca-on,Ontario,CA,CAN.9_1,4.1,CA-ON\n")
    assert [r.slug for r in load_regions(p)] == ["ca-on", "us-ma"]


# --- validation ------------------------------------------------------------------


def test_disagreeing_gadm_versions_raise(tmp_path):
    p = write(tmp_path, "us-ma,Massachusetts,US,USA.22_1,4.1,US-MA\nca-on,Ontario,CA,CAN.9_1,3.6,CA-ON\n")
    table = load_regions(p)
    with pytest.raises(ValueError, match="gadm_version"):
        _ = table.gadm_version


def test_empty_table_has_no_gadm_version():
    with pytest.raises(ValueError):
        _ = RegionTable([]).gadm_version


def test_wrong_header_raises(tmp_path):
    p = write(tmp_path, "us-ma,Massachusetts,US,USA.22_1,4.1,US-MA\n", header="slug,name,country,gid,version,ebird\n")
    with pytest.raises(ValueError, match="header"):
        load_regions(p)


def test_duplicate_slug_raises(tmp_path):
    p = write(tmp_path, "us-ma,Massachusetts,US,USA.22_1,4.1,US-MA\nus-ma,Mass,US,USA.23_1,4.1,US-MB\n")
    with pytest.raises(ValueError, match="us-ma"):
        load_regions(p)


def test_duplicate_gid_raises(tmp_path):
    p = write(tmp_path, "us-ma,Massachusetts,US,USA.22_1,4.1,US-MA\nus-mi,Michigan,US,USA.22_1,4.1,US-MI\n")
    with pytest.raises(ValueError, match="USA.22_1"):
        load_regions(p)
