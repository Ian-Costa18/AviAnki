"""Tests for scripts/fetch_latest_catalog.sh against a fake `gh` on PATH.

The fake stands in for the GitHub CLI: `gh release list` prints the lines the real
`--jq` filter would produce ("<createdAt> <tag>") from a fixture, and `gh release
download` copies a prepared tarball. This tests the script's selection and failure
handling, not gh's own `--jq` evaluation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fetch_latest_catalog.sh"

FAKE_GH = """#!/usr/bin/env bash
echo "gh $*" >>"$FAKE_GH_LOG"
case "$1 $2" in
  "release list")
    [ -z "${FAKE_GH_LIST_FAILS:-}" ] || { echo "gh: HTTP 502" >&2; exit 1; }
    cat "$FAKE_GH_RELEASES"
    ;;
  "release download")
    [ -z "${FAKE_GH_DOWNLOAD_FAILS:-}" ] || { echo "gh: asset not found" >&2; exit 1; }
    dir=""
    while [ $# -gt 0 ]; do
      [ "$1" = "--dir" ] && dir=$2
      shift
    done
    cp "$FAKE_GH_TARBALL" "$dir/catalog.tar.gz"
    ;;
  *) echo "fake gh: unexpected call: $*" >&2; exit 3 ;;
esac
"""


def _bash_candidates() -> list[str]:
    found = [shutil.which("bash")]
    git = shutil.which("git")
    if git is not None:  # Git for Windows: PATH often has WSL's bash.exe ahead of it
        found.append(str(Path(git).resolve().parents[1] / "bin" / "bash.exe"))
    return [c for c in found if c is not None and Path(c).exists()]


def _bash() -> str:
    """A bash that can run the script by its path (WSL's bash.exe cannot see Windows paths)."""
    for bash in _bash_candidates():
        try:
            probe = subprocess.run(
                [bash, "-c", f'test -f "{SCRIPT.as_posix()}" && echo ok'], capture_output=True, text=True, timeout=30
            )
        except OSError:
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return bash
    pytest.skip("no bash that can run scripts/fetch_latest_catalog.sh")


def make_tarball(path: Path, files: dict[str, str]) -> None:
    src = path.parent / "tar_src"
    src.mkdir()
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    with tarfile.open(path, "w:gz") as tar:
        for name in files:
            tar.add(src / name, arcname=name)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.bash = _bash()
        self.tmp = tmp_path
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8", newline="\n")
        gh.chmod(0o755)
        self.log = tmp_path / "gh.log"
        self.log.write_text("", encoding="utf-8")
        self.releases = tmp_path / "releases.txt"
        self.tarball = tmp_path / "catalog.tar.gz"
        make_tarball(self.tarball, {"manifest.json": "{}"})
        self.output = tmp_path / "github_output.txt"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_LOG": self.log.as_posix(),
            "FAKE_GH_RELEASES": self.releases.as_posix(),
            "FAKE_GH_TARBALL": self.tarball.as_posix(),
            "GITHUB_OUTPUT": self.output.as_posix(),
        }
        self.env.pop("FAKE_GH_LIST_FAILS", None)
        self.env.pop("FAKE_GH_DOWNLOAD_FAILS", None)

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.bash, SCRIPT.as_posix(), *args],
            capture_output=True,
            text=True,
            env={**self.env, **env},
            timeout=120,
        )

    def outputs(self) -> dict[str, str]:
        text = self.output.read_text(encoding="utf-8") if self.output.exists() else ""
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_picks_the_newest_catalog_release(env: Env) -> None:
    env.releases.write_text(
        "2026-08-01T05:10:00Z catalog-2026-08-01\n"
        "2026-10-01T05:12:00Z catalog-2026-10-01\n"
        "2026-09-01T05:11:00Z catalog-2026-09-01\n",
        encoding="utf-8",
    )
    dest = env.tmp / "previous"

    result = env.run(str(dest.as_posix()))

    assert result.returncode == 0, result.stderr
    assert (dest / "manifest.json").is_file()
    assert env.outputs() == {"found": "true", "tag": "catalog-2026-10-01"}
    assert "release download catalog-2026-10-01" in env.log.read_text(encoding="utf-8")


def test_only_the_catalog_prefix_is_listed_for_the_jq_filter(env: Env) -> None:
    env.releases.write_text("2026-08-01T05:10:00Z catalog-2026-08-01\n", encoding="utf-8")
    env.run(str((env.tmp / "previous").as_posix()))
    listing = next(
        line for line in env.log.read_text(encoding="utf-8").splitlines() if line.startswith("gh release list")
    )
    assert 'startswith("catalog-")' in listing
    assert "--exclude-drafts" in listing


def test_no_release_with_allow_none_is_a_clean_skip(env: Env) -> None:
    env.releases.write_text("", encoding="utf-8")
    dest = env.tmp / "previous"

    result = env.run(str(dest.as_posix()), "--allow-none")

    assert result.returncode == 0, result.stderr
    assert "no previous" in result.stdout.lower()
    assert env.outputs() == {"found": "false", "tag": ""}
    assert "release download" not in env.log.read_text(encoding="utf-8")
    assert not (dest / "manifest.json").exists()


def test_no_release_without_allow_none_fails_loudly(env: Env) -> None:
    env.releases.write_text("", encoding="utf-8")

    result = env.run(str((env.tmp / "catalog").as_posix()))

    assert result.returncode == 1
    assert "no catalog-* release" in result.stderr


def test_failed_download_of_an_existing_release_is_an_error_even_with_allow_none(env: Env) -> None:
    env.releases.write_text("2026-09-01T05:11:00Z catalog-2026-09-01\n", encoding="utf-8")

    result = env.run(str((env.tmp / "previous").as_posix()), "--allow-none", FAKE_GH_DOWNLOAD_FAILS="1")

    assert result.returncode != 0
    assert env.outputs().get("found") != "false"


def test_failed_listing_is_an_error_even_with_allow_none(env: Env) -> None:
    env.releases.write_text("", encoding="utf-8")

    result = env.run(str((env.tmp / "previous").as_posix()), "--allow-none", FAKE_GH_LIST_FAILS="1")

    assert result.returncode != 0
    assert env.outputs().get("found") != "false"


def test_tarball_without_a_manifest_is_an_error(env: Env) -> None:
    env.releases.write_text("2026-09-01T05:11:00Z catalog-2026-09-01\n", encoding="utf-8")
    bad = env.tmp / "bad"
    bad.mkdir()
    make_tarball(bad / "catalog.tar.gz", {"species.json": "{}"})
    env.env["FAKE_GH_TARBALL"] = (bad / "catalog.tar.gz").as_posix()

    result = env.run(str((env.tmp / "previous").as_posix()))

    assert result.returncode == 1
    assert "manifest.json" in result.stderr


def test_usage_error(env: Env) -> None:
    assert env.run().returncode == 2
    assert env.run("dest", "--bogus").returncode == 2
