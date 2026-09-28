"""Tests for avianki.catalog_cli — the real GBIF source over a routing fake session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from gbif_fakes import API, EOD, FIXTURES, REGIONS, TINY, RoutingSession, request_key, tiny_routes

from avianki import catalog_cli
from avianki.core.http import HttpClient
from avianki.taxonomy.species import SpeciesRow, SpeciesTable, load_species, save_species

EOD_META = json.loads((FIXTURES / "eod_dataset.json").read_text(encoding="utf-8"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    routes = tiny_routes()
    routes[request_key(f"{API}/dataset/{EOD}", None)] = EOD_META
    session = RoutingSession(routes)
    monkeypatch.setattr(catalog_cli, "new_session", lambda: session)
    monkeypatch.setattr(catalog_cli, "new_client",
                        lambda cache_dir, sess: HttpClient(cache_dir, session=sess, sleep=lambda _s: None))
    monkeypatch.setattr(catalog_cli, "load_regions", lambda: REGIONS)
    csv = tmp_path / "species.csv"
    save_species(SpeciesTable([SpeciesRow("alpha-alpha", "Alpha alpha", "Alpha Bird", gbif_key=10)]), csv)
    out = tmp_path / "build"
    args = ["build", "--species-only", "--regions", TINY.slug, "--out", str(out),
            "--cache-dir", str(tmp_path / "cache"), "--species-csv", str(csv), "-q"]
    return args, out, csv, session, routes


def test_writes_region_files_report_and_minted_rows(env):
    args, out, csv, _, _ = env
    assert catalog_cli.main(args) == 0
    region = json.loads((out / "regions" / "xx-tiny.json").read_text(encoding="utf-8"))
    assert region == {
        "slug": "xx-tiny",
        "species": [
            ["alpha-alpha", [51, 255, 0, 0, 0, 0, 102, 0, 0, 0, 0, 0]],
            ["gamma-gamma", [255] + [0] * 11],
            ["beta-beta", [0, 0, 0, 0, 1, 3, 0, 0, 0, 0, 0, 255]],
            ["delta-delta", [0, 128, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0]],
        ],
    }
    ids = [r.id for r in load_species(csv)]
    assert ids == ["alpha-alpha", "beta-beta", "delta-delta", "gamma-gamma"]
    report = (out / "species-lists-report.md").read_text(encoding="utf-8")
    assert "2025-08-08 2024-eBird-dwca-1.0.zip" in report
    assert "| xx-tiny | Tiny | 4 | 4 |" in report
    assert "gamma-gamma" in report  # minted list


def test_top_n_limits_the_region_file(env):
    args, out, _, _, _ = env
    assert catalog_cli.main([*args, "--top-n", "2"]) == 0
    region = json.loads((out / "regions" / "xx-tiny.json").read_text(encoding="utf-8"))
    assert [s[0] for s in region["species"]] == ["alpha-alpha", "gamma-gamma"]


def test_a_failed_region_exits_non_zero_and_writes_no_list(env):
    args, out, csv, session, _ = env
    for k in session.routes:
        if "month=3" in k:
            session.routes[k] = (500, b"down")
    before = csv.read_text(encoding="utf-8")
    assert catalog_cli.main(args) == 1
    assert not (out / "regions" / "xx-tiny.json").exists()
    assert "xx-tiny" in (out / "species-lists-report.md").read_text(encoding="utf-8")
    assert csv.read_text(encoding="utf-8") == before


def test_responses_are_cached_per_dataset_version(env, tmp_path):
    args, _, _, session, _ = env
    catalog_cli.main(args)
    first = len(session.calls)
    catalog_cli.main(args)
    # the rerun only re-checks the dataset version
    assert session.calls[first:] == [f"{API}/dataset/{EOD}"]
    assert len([p for p in (tmp_path / "cache").iterdir() if p.name.startswith("eod-")]) == 1


def test_build_without_species_only_is_not_implemented_yet(env, capsys):
    assert catalog_cli.main(["build"]) == 2
    assert "M3" in capsys.readouterr().err


def test_unknown_region_is_a_usage_error(env):
    args, *_ = env
    with pytest.raises(SystemExit) as e:
        catalog_cli.main([*args, "--regions", "us-zz"])
    assert e.value.code == 2


def test_console_script_is_declared():
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'avianki-catalog = "avianki.catalog_cli:main"' in text
