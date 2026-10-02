"""Tests for the full ``avianki-catalog build``: argument handling, exit codes and the wiring, with the
real GBIF source over a routing session and fake asset sources plus a scripted BirdNET behind the
`catalog_cli` seams. Nothing here touches the network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from gbif_fakes import API, EOD, FIXTURES, REGIONS, TINY, RoutingSession, request_key, tiny_routes
from pipeline_fakes import AUDIO, PHOTO, FakeSource, FakeSourceNoSpecies, ScriptedAnalyzer, make_fake_registry

from avianki import catalog_cli
from avianki.catalog.format import load_catalog
from avianki.core.http import HttpClient
from avianki.media.verify import VerifyUnavailable
from avianki.sources.registry import Registry
from avianki.taxonomy.species import SpeciesRow, SpeciesTable, load_species, save_species

EOD_META = json.loads((FIXTURES / "eod_dataset.json").read_text(encoding="utf-8"))
IDS = ["alpha-alpha", "gamma-gamma", "beta-beta", "delta-delta"]  # the tiny region, in rank order
BIRDNET = [
    "Alpha alpha_Alpha Bird",
    "Gamma gamma_Gamma Bird",
    "Beta beta_Beta Bird",
    "Delta delta_Delta Bird",
]


@dataclass
class Env:
    args: list[str]
    out: Path
    csv: Path
    session: RoutingSession
    commons: FakeSource
    inat: FakeSource
    analyzer: ScriptedAnalyzer
    expected: list


def sources() -> tuple[FakeSource, FakeSource]:
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    for sid in IDS:
        commons.add(sid, PHOTO, f"{sid}-p")
        commons.add(sid, AUDIO, f"{sid}-a")
    return commons, inat


@pytest.fixture()
def env(tmp_path, monkeypatch) -> Env:
    routes = tiny_routes()
    routes[request_key(f"{API}/dataset/{EOD}", None)] = EOD_META
    session = RoutingSession(routes)
    commons, inat = sources()
    analyzer = ScriptedAnalyzer([0.9], labels=BIRDNET)
    expected: list = []

    def registry(client, species, counts) -> Registry:
        expected.append(counts)
        return make_fake_registry(commons, inat)

    monkeypatch.setattr(catalog_cli, "new_session", lambda: session)
    monkeypatch.setattr(
        catalog_cli, "new_client", lambda cache_dir, sess: HttpClient(cache_dir, session=sess, sleep=lambda _s: None)
    )
    monkeypatch.setattr(catalog_cli, "load_regions", lambda: REGIONS)
    monkeypatch.setattr(catalog_cli, "new_registry", registry)
    monkeypatch.setattr(catalog_cli, "new_analyzer", lambda: analyzer)
    csv = tmp_path / "species.csv"
    row = SpeciesRow("alpha-alpha", "Alpha alpha", "Alpha Bird", gbif_key=10, birdnet_label=BIRDNET[0], ioc_name="Alpha Fowl")
    save_species(SpeciesTable([row]), csv)
    pins = tmp_path / "pins.toml"
    pins.write_text("", encoding="utf-8")
    out = tmp_path / "build"
    args = ["build", "--regions", TINY.slug, "--out", str(out), "--cache-dir", str(tmp_path / "cache"),
            "--species-csv", str(csv), "--pins", str(pins), "-q"]  # fmt: skip
    return Env(args, out, csv, session, commons, inat, analyzer, expected)


def test_a_full_build_writes_everything_and_exits_zero(env: Env, capsys):
    assert catalog_cli.main(env.args) == 0
    site = env.out / "site"
    for name in ("manifest.json", "credits.html"):
        assert (site / name).is_file()
    for name in ("build-report.md", "contact-sheet.html", "catalog.log"):
        assert (env.out / name).is_file(), name
    cat = load_catalog(site)
    assert set(cat.species) == set(IDS) and set(cat.regions) == {"xx-tiny"}
    assert all(len(cat.species[s].photo) == 1 and len(cat.species[s].audio) == 1 for s in IDS)
    assert cat.manifest.eod_version and cat.manifest.gadm_version == "4.1"
    printed = capsys.readouterr().out
    assert "4 species" in printed and "validation PASSED" in printed
    assert env.expected[0] and env.expected[0]["alpha-alpha"] > 0  # ADR 0022 expected counts reached the registry


def test_the_catalog_names_new_species_by_ebird_and_never_renames_an_existing_one(env: Env):
    assert catalog_cli.main([*env.args, "--update-species-csv"]) == 0
    cat = load_catalog(env.out / "site")
    # species.csv's name wins for alpha-alpha even though EOD's record says "Alpha Birdie" (ADR 0026)
    assert cat.species["alpha-alpha"].name == "Alpha Bird"
    assert cat.species["gamma-gamma"].name == "Gamma Birdie"
    assert {r.id: r.common_name for r in load_species(env.csv)}["alpha-alpha"] == "Alpha Bird"


def test_the_ioc_name_reaches_the_catalog_and_survives_update_species_csv(env: Env):
    """ADR 0027: species.csv's ioc_name is published (key omitted when empty) and never lost on a rewrite."""
    assert catalog_cli.main([*env.args, "--update-species-csv"]) == 0
    cat = load_catalog(env.out / "site")
    assert cat.species["alpha-alpha"].ioc_name == "Alpha Fowl"
    assert all(cat.species[s].ioc_name == "" for s in IDS if s != "alpha-alpha")
    published = json.loads(next((env.out / "site").glob("species.*.json")).read_text(encoding="utf-8"))
    assert published["alpha-alpha"]["ioc_name"] == "Alpha Fowl"
    assert all("ioc_name" not in v for k, v in published.items() if k != "alpha-alpha")
    assert {r.id: r.ioc_name for r in load_species(env.csv)}["alpha-alpha"] == "Alpha Fowl"


def test_a_build_leaves_species_csv_alone_without_the_flag(env: Env):
    before = env.csv.read_text(encoding="utf-8")
    assert catalog_cli.main(env.args) == 0
    assert env.csv.read_text(encoding="utf-8") == before


def test_update_species_csv_writes_minted_species_and_found_labels(env: Env):
    assert catalog_cli.main([*env.args, "--update-species-csv"]) == 0
    rows = {r.id: r for r in load_species(env.csv)}
    assert set(rows) == set(IDS)
    assert rows["gamma-gamma"].birdnet_label == "Gamma gamma_Gamma Bird"
    assert rows["alpha-alpha"].birdnet_label == BIRDNET[0]


def test_max_species_builds_only_the_most_widespread(env: Env):
    assert catalog_cli.main([*env.args, "--max-species", "2"]) == 0
    cat = load_catalog(env.out / "site")
    assert list(cat.species) == IDS[:2]
    assert [s for s, _ in cat.regions["xx-tiny"].species] == IDS[:2]


def test_base_url_is_written_to_the_manifest(env: Env):
    assert catalog_cli.main([*env.args, "--base-url", "https://example.test/c/"]) == 0
    assert load_catalog(env.out / "site").manifest.base_url == "https://example.test/c/"


def test_previous_keeps_assets_and_makes_no_source_calls(env: Env, tmp_path: Path):
    assert catalog_cli.main(env.args) == 0
    first = load_catalog(env.out / "site")
    env.commons.calls.clear()
    env.analyzer.calls.clear()
    second_out = tmp_path / "second"
    args = [*env.args, "--previous", str(env.out / "site")]
    args[args.index("--out") + 1] = str(second_out)
    assert catalog_cli.main(args) == 0
    assert env.commons.calls == [] and env.inat.calls == [] and env.analyzer.calls == []
    assert load_catalog(second_out / "site").referenced_media() == first.referenced_media()
    assert env.expected[-1] is None  # the species half was reused, so no plausibility counts


def test_a_failed_validation_exits_one_and_allow_shrink_downgrades_it(env: Env, tmp_path: Path):
    assert catalog_cli.main(env.args) == 0
    args = [*env.args, "--previous", str(env.out / "site"), "--max-species", "1"]
    args[args.index("--out") + 1] = str(tmp_path / "shrunk")
    assert catalog_cli.main(args) == 1
    assert (tmp_path / "shrunk" / "site" / "manifest.json").is_file()  # written anyway, for inspection
    assert catalog_cli.main([*args, "--allow-shrink"]) == 0


def test_a_pin_that_cannot_be_honoured_exits_one_but_writes_the_files(env: Env, tmp_path: Path, capsys):
    pins = tmp_path / "pins.toml"
    pins.write_text('[alpha-alpha]\nphoto = "commons:GHOST"\nnote = "a test"\n', encoding="utf-8")
    assert catalog_cli.main(env.args) == 1
    assert (env.out / "site" / "manifest.json").is_file()
    assert "PIN ERROR" in capsys.readouterr().out
    assert "PIN ERRORS" in (env.out / "build-report.md").read_text(encoding="utf-8")


def test_a_source_failure_that_leaves_a_species_unfinished_still_exits_zero(env: Env, capsys):
    from avianki.core.http import SourceError

    env.commons.candidate_errors["beta-beta"] = SourceError("HTTP 503")
    assert catalog_cli.main(env.args) == 0
    assert "unfinished" in capsys.readouterr().out
    assert "beta-beta" in (env.out / "build-report.md").read_text(encoding="utf-8")


def test_an_invalid_pins_file_is_a_usage_error(env: Env, tmp_path: Path, capsys):
    (tmp_path / "pins.toml").write_text('[nope]\nnote = "x"\n', encoding="utf-8")
    assert catalog_cli.main(env.args) == 2
    assert "unknown species" in capsys.readouterr().err
    assert env.session.calls == []  # stopped before any request


def test_an_unreadable_previous_catalog_is_a_usage_error(env: Env, tmp_path: Path):
    assert catalog_cli.main([*env.args, "--previous", str(tmp_path / "nowhere")]) == 2


def test_audio_that_cannot_be_verified_stops_the_build_before_any_request(env: Env, monkeypatch, capsys):
    def unavailable():
        raise VerifyUnavailable("the birdnet extra is not installed")

    monkeypatch.setattr(catalog_cli, "new_analyzer", unavailable)
    assert catalog_cli.main(env.args) == 2
    assert "birdnet" in capsys.readouterr().err
    assert env.session.calls == [] and not (env.out / "site").exists()


def test_no_verify_builds_without_the_model_and_says_so_loudly(env: Env, monkeypatch, capsys):
    monkeypatch.setattr(catalog_cli, "new_analyzer", lambda: pytest.fail("the model must not be loaded"))
    assert catalog_cli.main([*env.args, "--no-verify"]) == 0
    captured = capsys.readouterr()
    assert "--no-verify" in captured.err and "Do not publish" in captured.out
    assert all(e.audio == [] for e in load_catalog(env.out / "site").species.entries.values())
    assert "AUDIO NOT VERIFIED" in (env.out / "build-report.md").read_text(encoding="utf-8")


def test_a_region_with_no_list_and_no_previous_exits_one(env: Env):
    for k in env.session.routes:
        if "month=3" in k:
            env.session.routes[k] = (500, b"down")
    assert catalog_cli.main(env.args) == 1
    assert not (env.out / "site" / "manifest.json").exists()
    assert "xx-tiny" in (env.out / "build-report.md").read_text(encoding="utf-8")


def test_species_only_is_unchanged_and_never_touches_assets(env: Env, monkeypatch):
    monkeypatch.setattr(catalog_cli, "new_registry", lambda *a: pytest.fail("no asset sources in --species-only"))
    monkeypatch.setattr(catalog_cli, "new_analyzer", lambda: pytest.fail("no BirdNET in --species-only"))
    assert catalog_cli.main([*env.args, "--species-only"]) == 0
    assert (env.out / "regions" / "xx-tiny.json").is_file()
    assert (env.out / "species-lists-report.md").is_file()
    assert not (env.out / "site").exists()


@pytest.mark.parametrize("flag", [["--max-species", "0"], ["--time-budget-minutes", "0"], ["--top-n", "0"]])
def test_bad_numbers_are_usage_errors(env: Env, flag):
    with pytest.raises(SystemExit) as e:
        catalog_cli.main([*env.args, *flag])
    assert e.value.code == 2


def test_the_default_registry_has_both_real_sources_and_the_default_pins_file_ships():
    client = HttpClient(cache_dir=None, session=RoutingSession({}), sleep=lambda _s: None)
    registry = catalog_cli.new_registry(client, SpeciesTable([]), None)
    assert [s.name for s in registry.asset_sources(PHOTO)] == ["commons", "inaturalist"]
    assert [s.name for s in registry.asset_sources(AUDIO)] == ["commons", "inaturalist"]
    assert catalog_cli.PINS_TOML.is_file()


@pytest.mark.parametrize("key", ["k-123", None])
def test_the_registry_gives_commons_the_xeno_canto_key_from_the_environment(monkeypatch, key):
    if key is None:
        monkeypatch.delenv("XC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("XC_API_KEY", key)
    client = HttpClient(cache_dir=None, session=RoutingSession({}), sleep=lambda _s: None)
    commons = catalog_cli.new_registry(client, SpeciesTable([]), None).asset_sources(AUDIO)[0]
    assert commons._xc is not None and commons._xc._key == key  # type: ignore[attr-defined]
