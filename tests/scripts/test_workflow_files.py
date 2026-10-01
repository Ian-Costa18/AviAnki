"""Checks on the workflow files that guard the release (issue #47, ADR 0020).

PyYAML isn't a direct dependency, but genanki requires it, so it is always installed with avianki.
YAML 1.1 reads the bare key ``on`` as the boolean True; `triggers` accepts either spelling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["on"] if "on" in workflow else workflow[True]


def step_text(step: dict[str, Any]) -> str:
    return yaml.safe_dump(step)


def publishing_jobs(workflow: dict[str, Any]) -> list[str]:
    return [
        name for name, job in workflow["jobs"].items()
        if any("uv publish" in step.get("run", "") for step in job["steps"])
    ]


# -- publish.yml ---------------------------------------------------------------------------


def test_pushing_a_v_tag_publishes_and_a_manual_run_names_the_tag() -> None:
    on = triggers(load("publish.yml"))
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"tags": ["v*"]}  # tags only: a branch push must never publish
    assert on["workflow_dispatch"]["inputs"]["tag"]["required"] is True


def test_the_github_release_is_created_after_the_upload() -> None:
    workflow = load("publish.yml")
    job = workflow["jobs"]["release"]
    assert set(job["needs"]) == {"sanity-test", "publish"}
    assert job["permissions"] == {"contents": "write"}
    assert publishing_jobs(workflow) == ["publish"]  # the release job never uploads to PyPI
    assert any("gh release create" in s.get("run", "") for s in job["steps"])


def test_only_the_environment_protected_job_publishes() -> None:
    workflow = load("publish.yml")
    publishers = publishing_jobs(workflow)
    assert publishers == ["publish"]
    job = workflow["jobs"]["publish"]
    assert job["environment"] == "pypi"
    assert job["permissions"] == {"id-token": "write"}
    assert "sanity-test" in job["needs"]
    assert any("--trusted-publishing always" in s.get("run", "") for s in job["steps"])


def test_the_tag_is_checked_against_the_project_version_before_anything_is_built() -> None:
    steps = load("publish.yml")["jobs"]["sanity-test"]["steps"]
    checks = [i for i, s in enumerate(steps) if "pyproject.toml" in s.get("run", "") and "TAG" in s.get("run", "")]
    assert len(checks) == 1
    assert '"v$version"' in steps[checks[0]]["run"]
    tests = [i for i, s in enumerate(steps) if s.get("run", "").startswith("uv run pytest")]
    assert tests and checks[0] < tests[0]
    assert steps[0]["with"]["ref"] == "${{ inputs.tag || github.ref_name }}"


def test_the_sanity_tests_install_what_ci_installs() -> None:
    steps = [s.get("run", "") for s in load("publish.yml")["jobs"]["sanity-test"]["steps"]]
    assert "uv sync --group dev --extra catalog" in steps
    assert any(s.startswith("uv run playwright install") and "chromium" in s for s in steps)


def test_nothing_generates_or_commits_examples_any_more() -> None:
    workflow = load("publish.yml")
    assert "update-examples" not in workflow["jobs"]
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "gen_examples" not in text, path.name
        assert "examples/" not in text, path.name
    assert not (ROOT / "scripts" / "gen_examples.py").exists()
    assert not (ROOT / "examples").exists()


# -- weekly-integration.yml ------------------------------------------------------------------


def weekly_steps() -> list[dict[str, Any]]:
    return load("weekly-integration.yml")["jobs"]["integration"]["steps"]


def test_the_weekly_check_runs_the_live_suite_on_python_313_with_every_extra_it_needs() -> None:
    steps = weekly_steps()
    python = next(s for s in steps if s.get("uses", "").startswith("actions/setup-python"))
    assert python["with"]["python-version"] == "3.13"  # birdnet has no 3.14 wheels
    installs = [s["run"] for s in steps if s.get("run", "").startswith("uv sync")]
    assert len(installs) == 1
    assert "--extra catalog" in installs[0] and "--extra verify" in installs[0]
    assert any("playwright install" in s.get("run", "") and "chromium" in s["run"] for s in steps)
    run = next(s["run"] for s in steps if "pytest" in s.get("run", ""))
    assert "--integration" in run and "-rs" in run and "--junitxml" in run


def test_the_weekly_check_enforces_no_skips_even_after_a_failed_run() -> None:
    workflow = load("weekly-integration.yml")
    job = workflow["jobs"]["integration"]
    assert job["timeout-minutes"] <= 60
    enforce = [s for s in job["steps"] if "weekly_summary.py" in s.get("run", "")]
    assert len(enforce) == 1
    assert "always()" in str(enforce[0]["if"])
    assert not any(s.get("continue-on-error") for s in job["steps"])
    assert (ROOT / "scripts" / "weekly_summary.py").is_file()


def test_a_failed_weekly_run_opens_an_issue_and_the_interim_text_is_gone() -> None:
    workflow = load("weekly-integration.yml")
    assert workflow["jobs"]["notify-on-failure"]["needs"] == "integration"
    assert "interim" not in (WORKFLOWS / "weekly-integration.yml").read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_every_workflow_parses(name: str) -> None:
    workflow = load(name)
    assert workflow["jobs"]
    assert triggers(workflow)
