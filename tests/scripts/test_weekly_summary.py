"""Tests for scripts/weekly_summary.py: the weekly check's "no skips" gate and job summary.

The script isn't a package (and is stdlib-only), so it's imported from its path. Each test writes
a small JUnit report of the shape pytest produces (``-o junit_family=xunit1``, the family that supports record_property).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "weekly_summary.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("weekly_summary", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks the module up by name
    spec.loader.exec_module(module)
    return module


weekly_summary = _load()

EBIRD_SKIP = "EBIRD_API_KEY is not set"
# (classname, name) of one test per check, as pytest names them.
SOURCES = ("tests.sources.test_sources_live", "test_every_source_offers_complete_photo_candidates[commons-x]")
GBIF = ("tests.sources.test_gbif_live", "test_the_eod_lists_at_least_300_species_for_massachusetts")
SITE = ("tests.catalog.test_published_site_live", "test_the_manifest_loads_and_parses")
LIVE_DECK = ("tests.acceptance.test_acceptance_live", "test_the_live_us_ma_deck_imports_cleanly")
CLIENT = ("tests.catalog.test_catalog_client", "test_live_manifest_has_us_ma")
WEB = ("tests.web.test_web_live_catalog", "test_build_massachusetts_standard_from_the_published_catalog")
EBIRD = ("tests.sources.test_ebird_live", "test_the_live_ebird_list_for_a_small_region")
BIRDNET = ("tests.media.test_verify", "test_real_model_scores_noise_below_the_gate")


def case(where: tuple[str, str], outcome: str = "passed", message: str = "", properties: dict[str, str] | None = None) -> str:
    inner = ""
    if outcome == "skipped":
        inner = f'<skipped type="pytest.skip" message="{message}">skipped</skipped>'
    elif outcome in ("failure", "error"):
        inner = f'<{outcome} message="{message}">boom</{outcome}>'
    if properties:
        props = "".join(f'<property name="{k}" value="{v}"/>' for k, v in properties.items())
        inner = f"<properties>{props}</properties>" + inner
    return f'<testcase classname="{where[0]}" name="{where[1]}" time="1.5">{inner}</testcase>'


def report(tmp_path: Path, *cases: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{"".join(cases)}</testsuite></testsuites>', encoding="utf-8")
    return path


def everything(ebird: str = "passed") -> list[str]:
    ebird_case = case(EBIRD, ebird, EBIRD_SKIP if ebird == "skipped" else "")
    return [case(SOURCES), case(GBIF), case(SITE), case(LIVE_DECK), case(CLIENT), case(WEB), ebird_case, case(BIRDNET)]


def run(path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], summary: Path | None = None):
    if summary is None:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    else:
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = weekly_summary.main(["weekly_summary.py", str(path)])
    return code, capsys.readouterr().out


def test_a_clean_run_passes_and_lists_the_four_checks(tmp_path, monkeypatch, capsys) -> None:
    code, out = run(report(tmp_path, *everything()), monkeypatch, capsys)
    assert code == 0
    for heading in ("1. Source smoke tests", "2. GBIF EOD", "3. The published site", "4. eBird"):
        assert heading in out
    assert "FAILED" not in out and "SKIPPED" not in out and "NOT RUN" not in out
    assert "Other live tests" in out  # the BirdNET test is listed, not hidden


def test_the_summary_is_appended_to_the_github_step_summary_file(tmp_path, monkeypatch, capsys) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    run(report(tmp_path, *everything()), monkeypatch, capsys, summary)
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n") and "## Weekly integration check" in text


def test_the_ebird_skip_without_a_key_is_allowed_and_warned_about(tmp_path, monkeypatch, capsys) -> None:
    code, out = run(report(tmp_path, *everything(ebird="skipped")), monkeypatch, capsys)
    assert code == 0
    assert "SKIPPED (allowed)" in out
    assert "[!WARNING]" in out and "eBird smoke test SKIPPED" in out and "EBIRD_API_KEY" in out


def test_any_other_skip_fails_the_run(tmp_path, monkeypatch, capsys) -> None:
    cases = [c for c in everything() if "test_web_live_catalog" not in c]
    cases.append(case(WEB, "skipped", "chromium is not available"))
    code, out = run(report(tmp_path, *cases), monkeypatch, capsys)
    assert code == 1
    assert "Skips are not allowed" in out and "chromium is not available" in out


def test_an_ebird_skip_for_another_reason_is_not_the_allowed_one(tmp_path, monkeypatch, capsys) -> None:
    cases = [c for c in everything() if "test_ebird_live" not in c]
    cases.append(case(EBIRD, "skipped", "network down"))
    code, _ = run(report(tmp_path, *cases), monkeypatch, capsys)
    assert code == 1


@pytest.mark.parametrize("outcome", ["failure", "error"])
def test_a_failed_or_errored_test_fails_the_run_and_is_named(tmp_path, monkeypatch, capsys, outcome) -> None:
    cases = [c for c in everything() if "test_gbif_live" not in c]
    cases.append(case(GBIF, outcome, "AssertionError"))
    code, out = run(report(tmp_path, *cases), monkeypatch, capsys)
    assert code == 1
    assert "FAILED" in out and "test_the_eod_lists_at_least_300_species_for_massachusetts" in out


def test_a_check_with_no_tests_is_not_a_pass(tmp_path, monkeypatch, capsys) -> None:
    cases = [c for c in everything() if "test_published_site_live" not in c and "test_acceptance_live" not in c
             and "test_web_live_catalog" not in c and "test_catalog_client" not in c]
    code, out = run(report(tmp_path, *cases), monkeypatch, capsys)
    assert code == 1
    assert "NOT RUN" in out


def test_a_missing_report_fails_the_run(tmp_path, monkeypatch, capsys) -> None:
    code, out = run(tmp_path / "nope.xml", monkeypatch, capsys)
    assert code == 1
    assert "No test report" in out


def test_a_changed_eod_version_is_a_notice_not_a_failure(tmp_path, monkeypatch, capsys) -> None:
    cases = [c for c in everything() if "test_gbif_live" not in c]
    cases.append(case(GBIF, properties={"eod_version": "2026-01-01 new", "published_eod_version": "2025-08-08 old"}))
    code, out = run(report(tmp_path, *cases), monkeypatch, capsys)
    assert code == 0
    assert "2026-01-01 new" in out and "New EOD release" in out and "2025-08-08 old" in out


def test_an_unchanged_eod_version_is_reported_as_matching(tmp_path, monkeypatch, capsys) -> None:
    cases = [c for c in everything() if "test_gbif_live" not in c]
    cases.append(case(GBIF, properties={"eod_version": "v1", "published_eod_version": "v1"}))
    code, out = run(report(tmp_path, *cases), monkeypatch, capsys)
    assert code == 0 and "matches the published catalog" in out and "New EOD release" not in out
