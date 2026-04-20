"""Tests for CLI argument parsing and AVIANKI_* env var fallbacks."""
import tempfile
from pathlib import Path

import pytest

from avianki.cli import _parse_args


URL = "https://www.allaboutbirds.org/guide/browse/filter/loc/abc123"


# ── location ─────────────────────────────────────────────────────────────────


def test_location_from_cli():
    args = _parse_args([URL])
    assert args.location == URL


def test_location_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_LOCATION", URL)
    args = _parse_args([])
    assert args.location == URL


def test_location_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_LOCATION", "https://other.example.com")
    args = _parse_args([URL])
    assert args.location == URL


def test_location_missing_raises(monkeypatch):
    monkeypatch.delenv("AVIANKI_LOCATION", raising=False)
    with pytest.raises(SystemExit):
        _parse_args([])


# ── --limit / AVIANKI_LIMIT ───────────────────────────────────────────────────


def test_limit_from_cli():
    args = _parse_args([URL, "--limit", "30"])
    assert args.limit == 30


def test_limit_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_LIMIT", "25")
    args = _parse_args([URL])
    assert args.limit == 25


def test_limit_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_LIMIT", "25")
    args = _parse_args([URL, "--limit", "10"])
    assert args.limit == 10


def test_limit_default_is_none(monkeypatch):
    monkeypatch.delenv("AVIANKI_LIMIT", raising=False)
    args = _parse_args([URL])
    assert args.limit is None


# ── --output / AVIANKI_OUTPUT ─────────────────────────────────────────────────


def test_output_from_cli():
    args = _parse_args([URL, "--output", "out.apkg"])
    assert args.output == "out.apkg"


def test_output_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_OUTPUT", "env_out.apkg")
    args = _parse_args([URL])
    assert args.output == "env_out.apkg"


def test_output_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_OUTPUT", "env_out.apkg")
    args = _parse_args([URL, "--output", "cli_out.apkg"])
    assert args.output == "cli_out.apkg"


# ── --deck-name / AVIANKI_DECK_NAME ──────────────────────────────────────────


def test_deck_name_from_cli():
    args = _parse_args([URL, "--deck-name", "My Birds"])
    assert args.deck_name == "My Birds"


def test_deck_name_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_DECK_NAME", "Env Birds")
    args = _parse_args([URL])
    assert args.deck_name == "Env Birds"


def test_deck_name_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_DECK_NAME", "Env Birds")
    args = _parse_args([URL, "--deck-name", "CLI Birds"])
    assert args.deck_name == "CLI Birds"


# ── --delay / AVIANKI_DELAY ───────────────────────────────────────────────────


def test_delay_default():
    args = _parse_args([URL])
    assert args.delay == 0


def test_delay_from_cli():
    args = _parse_args([URL, "--delay", "1.5"])
    assert args.delay == 1.5


def test_delay_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_DELAY", "2.0")
    args = _parse_args([URL])
    assert args.delay == 2.0


def test_delay_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_DELAY", "2.0")
    args = _parse_args([URL, "--delay", "0.1"])
    assert args.delay == 0.1


# ── --work-dir / AVIANKI_WORK_DIR ─────────────────────────────────────────────


def test_work_dir_default():
    args = _parse_args([URL])
    assert args.work_dir == str(Path(tempfile.gettempdir()) / "avianki")


def test_work_dir_from_cli(tmp_path):
    args = _parse_args([URL, "--work-dir", str(tmp_path)])
    assert args.work_dir == str(tmp_path)


def test_work_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AVIANKI_WORK_DIR", str(tmp_path))
    args = _parse_args([URL])
    assert args.work_dir == str(tmp_path)


def test_work_dir_cli_overrides_env(monkeypatch, tmp_path):
    cli_dir = tmp_path / "cli"
    env_dir = tmp_path / "env"
    monkeypatch.setenv("AVIANKI_WORK_DIR", str(env_dir))
    args = _parse_args([URL, "--work-dir", str(cli_dir)])
    assert args.work_dir == str(cli_dir)


# ── --media-dir / AVIANKI_MEDIA_DIR ──────────────────────────────────────────


def test_media_dir_from_cli(tmp_path):
    args = _parse_args([URL, "--media-dir", str(tmp_path)])
    assert args.media_dir == str(tmp_path)


def test_media_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AVIANKI_MEDIA_DIR", str(tmp_path))
    args = _parse_args([URL])
    assert args.media_dir == str(tmp_path)


def test_media_dir_cli_overrides_env(monkeypatch, tmp_path):
    cli_dir = tmp_path / "cli"
    env_dir = tmp_path / "env"
    monkeypatch.setenv("AVIANKI_MEDIA_DIR", str(env_dir))
    args = _parse_args([URL, "--media-dir", str(cli_dir)])
    assert args.media_dir == str(cli_dir)


# ── --json-file / AVIANKI_JSON_FILE ──────────────────────────────────────────


def test_json_file_from_cli():
    args = _parse_args([URL, "--json-file", "/tmp/birds.json"])
    assert args.json_file == "/tmp/birds.json"


def test_json_file_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_JSON_FILE", "/tmp/env_birds.json")
    args = _parse_args([URL])
    assert args.json_file == "/tmp/env_birds.json"


def test_json_file_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_JSON_FILE", "/tmp/env_birds.json")
    args = _parse_args([URL, "--json-file", "/tmp/cli_birds.json"])
    assert args.json_file == "/tmp/cli_birds.json"


# ── --log-file / AVIANKI_LOG_FILE ─────────────────────────────────────────────


def test_log_file_from_cli():
    args = _parse_args([URL, "--log-file", "/tmp/test.log"])
    assert args.log_file == "/tmp/test.log"


def test_log_file_from_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_LOG_FILE", "/tmp/env.log")
    args = _parse_args([URL])
    assert args.log_file == "/tmp/env.log"


def test_log_file_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("AVIANKI_LOG_FILE", "/tmp/env.log")
    args = _parse_args([URL, "--log-file", "/tmp/cli.log"])
    assert args.log_file == "/tmp/cli.log"


# ── boolean flags ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flag,attr", [
    ("--no-audio", "no_audio"),
    ("--no-images", "no_images"),
    ("--ephemeral", "ephemeral"),
    ("--no-cache", "no_cache"),
    ("--verbose", "verbose"),
    ("--quiet", "quiet"),
])
def test_boolean_flag_from_cli(flag, attr):
    args = _parse_args([URL, flag])
    assert getattr(args, attr) is True


@pytest.mark.parametrize("env_key,attr", [
    ("AVIANKI_NO_AUDIO", "no_audio"),
    ("AVIANKI_NO_IMAGES", "no_images"),
    ("AVIANKI_EPHEMERAL", "ephemeral"),
    ("AVIANKI_NO_CACHE", "no_cache"),
    ("AVIANKI_VERBOSE", "verbose"),
    ("AVIANKI_QUIET", "quiet"),
])
@pytest.mark.parametrize("value", ["1", "true", "yes", "True", "YES"])
def test_boolean_env_truthy_values(env_key, attr, value, monkeypatch):
    monkeypatch.setenv(env_key, value)
    args = _parse_args([URL])
    assert getattr(args, attr) is True


@pytest.mark.parametrize("env_key,attr", [
    ("AVIANKI_NO_AUDIO", "no_audio"),
    ("AVIANKI_NO_IMAGES", "no_images"),
    ("AVIANKI_EPHEMERAL", "ephemeral"),
    ("AVIANKI_NO_CACHE", "no_cache"),
])
@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_boolean_env_falsy_values(env_key, attr, value, monkeypatch):
    monkeypatch.setenv(env_key, value)
    args = _parse_args([URL])
    assert getattr(args, attr) is False


@pytest.mark.parametrize("env_key,attr", [
    ("AVIANKI_NO_AUDIO", "no_audio"),
    ("AVIANKI_NO_IMAGES", "no_images"),
    ("AVIANKI_EPHEMERAL", "ephemeral"),
    ("AVIANKI_NO_CACHE", "no_cache"),
])
def test_boolean_cli_flag_overrides_env_falsy(env_key, attr, monkeypatch):
    monkeypatch.setenv(env_key, "0")
    flag = "--" + attr.replace("_", "-")
    args = _parse_args([URL, flag])
    assert getattr(args, attr) is True


def test_verbose_env_does_not_apply_when_quiet_flag_set(monkeypatch):
    monkeypatch.setenv("AVIANKI_VERBOSE", "1")
    args = _parse_args([URL, "--quiet"])
    assert args.quiet is True
    assert args.verbose is False


def test_quiet_env_does_not_apply_when_verbose_flag_set(monkeypatch):
    monkeypatch.setenv("AVIANKI_QUIET", "1")
    args = _parse_args([URL, "--verbose"])
    assert args.verbose is True
    assert args.quiet is False
