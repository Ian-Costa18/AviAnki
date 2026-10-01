"""The 1.0.1 command-line fixes: inputs checked early, errors with advice, honest summaries.

Everything runs offline against the fixture catalog (see ``cli_fakes``).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest
from cli_fakes import FIXTURE_CATALOG, note_fields, run_cli

from avianki import cli
from avianki.deck.build import PlannedNote

REPO_ROOT = Path(__file__).resolve().parents[2]


def call(
    argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """``cli.main`` with no added flags (``run_cli`` appends --cache-dir and --catalog-url)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake home directory, for ``~`` (Path.expanduser reads HOME or USERPROFILE)."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    return fake


# ---------------------------------------------------------------------------------------
# 2. .env in the working directory
# ---------------------------------------------------------------------------------------


def test_a_dotenv_in_the_working_directory_is_loaded(tmp_path, monkeypatch):
    # find_dotenv() searches from the calling module's folder, which for an installed package
    # is site-packages; the working directory has to be asked for explicitly.
    monkeypatch.setenv(cli.EBIRD_KEY_VAR, "placeholder")
    monkeypatch.delenv(cli.EBIRD_KEY_VAR)  # leaves monkeypatch to restore "unset" afterwards
    (tmp_path / ".env").write_text(f"{cli.EBIRD_KEY_VAR}=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    seen: list[str | None] = []

    def fake_ebird_deck(args, client):
        seen.append(os.environ.get(cli.EBIRD_KEY_VAR))
        return 0

    monkeypatch.setattr(cli, "_ebird_deck", fake_ebird_deck)
    assert cli.main(["--ebird", "US-MA", "--cache-dir", str(tmp_path / "cache")]) == 0
    assert seen == ["from-dotenv"]


# ---------------------------------------------------------------------------------------
# 3. ~ is expanded
# ---------------------------------------------------------------------------------------


def test_a_tilde_in_output_is_expanded(tmp_path, monkeypatch, capsys, home):
    r = run_cli(["us-az", "-o", "~/decks/az.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert (home / "decks" / "az.apkg").is_file()
    assert not (tmp_path / "~").exists()


def test_a_tilde_in_cache_dir_is_expanded(tmp_path, monkeypatch, capsys, home):
    code, _, err = call(
        ["us-az", "--catalog-url", str(FIXTURE_CATALOG), "--cache-dir", "~/avianki-cache"],
        tmp_path,
        monkeypatch,
        capsys,
    )
    assert code == 0, err
    assert any((home / "avianki-cache").rglob("*.webp"))
    assert not (tmp_path / "~").exists()


# ---------------------------------------------------------------------------------------
# 4. Output paths are checked before any download
# ---------------------------------------------------------------------------------------


def test_an_output_that_is_a_directory_exits_2_before_downloading(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "decks"
    folder.mkdir()
    r = run_cli(["us-ma", "-o", str(folder)], tmp_path, monkeypatch, capsys)
    assert r.code == 2
    assert "is a folder" in r.err and str(folder) in r.err
    assert not (tmp_path / "cache").exists()  # nothing was fetched


def test_a_directory_named_by_a_trailing_slash_is_refused(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "-o", "out/"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "folder" in capsys.readouterr().err


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_output_is_a_usage_error(empty, tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "-o", empty], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "empty" in capsys.readouterr().err
    assert not (tmp_path / "cache").exists()


def test_a_parent_that_cannot_be_created_exits_2(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "afile"
    blocker.write_text("not a folder")
    r = run_cli(["us-ma", "-o", str(blocker / "sub" / "x.apkg")], tmp_path, monkeypatch, capsys)
    assert r.code == 2
    assert "cannot create the folder" in r.err
    assert "Traceback" not in r.err
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize(
    "name",
    ["my:deck.apkg", "deck?.apkg", 'say"hi".apkg', "x|y.apkg", "star*.apkg", "CON.apkg", "nul", "deck.apkg.", "deck.apkg "],
)
def test_windows_reserved_names_are_refused_on_windows(name, tmp_path):
    problem = cli.output_problem(tmp_path / name, platform="win32")
    assert problem is not None and "Windows" in problem


def test_the_same_names_are_fine_elsewhere(tmp_path):
    assert cli.output_problem(tmp_path / "my:deck.apkg", platform="linux") is None


def test_dotted_parents_are_not_mistaken_for_bad_names(tmp_path):
    assert cli.output_problem(tmp_path / ".." / tmp_path.name / "ok.apkg", platform="win32") is None


@pytest.mark.skipif(sys.platform != "win32", reason="the colon rule is Windows-only")
def test_a_colon_in_the_output_name_exits_2_on_windows(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-ma", "-o", "my:deck.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 2 and "Windows does not allow" in r.err
    assert not (tmp_path / "cache").exists()


def test_a_missing_parent_folder_is_still_created(tmp_path, monkeypatch, capsys):
    target = tmp_path / "new" / "deeper" / "deck.apkg"
    r = run_cli(["us-az", "-o", str(target)], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert target.is_file()


def test_an_existing_file_is_replaced_and_the_summary_says_so(tmp_path, monkeypatch, capsys):
    target = tmp_path / "deck.apkg"
    target.write_bytes(b"old")
    r = run_cli(["us-az", "-o", str(target)], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert target.stat().st_size > 3
    assert "replaced" in r.out and str(target) in r.out


def test_a_new_file_is_not_called_replaced(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az"], tmp_path, monkeypatch, capsys)
    assert "replaced" not in r.out


# ---------------------------------------------------------------------------------------
# 5. avianki-catalog without the catalog extra
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--help"], ["build", "--help"], []])
def test_avianki_catalog_without_the_extra_says_what_to_install(argv):
    # sys.modules[name] = None makes `import name` fail like an uninstalled package.
    code = (
        "import sys; sys.modules['PIL'] = None; "
        "from avianki.catalog_cli import main; main(sys.argv[1:])"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    done = subprocess.run(
        [sys.executable, "-c", code, *argv], capture_output=True, text=True, env=env, timeout=120
    )
    assert done.returncode == 2
    assert 'avianki-catalog needs the catalog extra: pip install "avianki[catalog]"' in done.stderr
    assert "Traceback" not in done.stderr


# ---------------------------------------------------------------------------------------
# 6. Redirected output on Windows, Ctrl-C
# ---------------------------------------------------------------------------------------


def test_non_cp1252_text_survives_a_cp1252_stdout_and_stderr(tmp_path, monkeypatch):
    out_buf, err_buf = io.BytesIO(), io.BytesIO()
    out = io.TextIOWrapper(out_buf, encoding="cp1252", write_through=True)
    err = io.TextIOWrapper(err_buf, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)
    argv = ["us-az", "-o", "鳥.apkg", "--catalog-url", str(FIXTURE_CATALOG), "--cache-dir", str(tmp_path / "c")]
    assert cli.main(argv) == 0
    assert "鳥.apkg" in out_buf.getvalue().decode("utf-8")
    # An error message too: the unknown region goes to stderr.
    assert cli.main(["鳥", "--catalog-url", str(FIXTURE_CATALOG), "--cache-dir", str(tmp_path / "c")]) == 2
    assert "鳥" in err_buf.getvalue().decode("utf-8")


def test_ctrl_c_prints_cancelled_and_exits_130_without_a_traceback(tmp_path, monkeypatch, capsys):
    def interrupted(args, client):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_catalog_deck", interrupted)
    code, out, err = call(["us-ma", "--cache-dir", str(tmp_path / "c")], tmp_path, monkeypatch, capsys)
    assert code == 130
    assert err.strip() == "Cancelled."
    assert "Traceback" not in err + out


# ---------------------------------------------------------------------------------------
# 7. Progress bars
# ---------------------------------------------------------------------------------------


def test_nothing_but_the_summary_is_written_when_stderr_is_not_a_terminal(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-ma"], tmp_path, monkeypatch, capsys)
    assert r.code == 0
    assert r.err == ""  # no "Downloading media: 0%|" debris


class _TtyStderr(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_the_bar_is_drawn_when_stderr_is_a_terminal(monkeypatch):
    fake = _TtyStderr()
    monkeypatch.setattr(sys, "stderr", fake)
    bar = cli._Bar("Downloading media", disable=False)
    bar(1, 2)
    bar.close()
    assert "Downloading media" in fake.getvalue()


def test_the_bar_stays_silent_on_a_plain_stream_or_with_quiet(monkeypatch):
    plain = io.StringIO()
    monkeypatch.setattr(sys, "stderr", plain)
    cli._Bar("x", disable=False)(1, 2)
    monkeypatch.setattr(sys, "stderr", _TtyStderr())
    quiet = sys.stderr
    cli._Bar("x", disable=True)(1, 2)
    assert plain.getvalue() == "" and quiet.getvalue() == ""  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------
# 8. The summary names the birds missing a card type
# ---------------------------------------------------------------------------------------


def test_the_summary_says_which_birds_lack_a_recording_or_a_photo(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-ma"], tmp_path, monkeypatch, capsys)
    # Snowy Owl has no audio, Common Loon no photo (12 birds in the fixture region).
    assert "1 of the 12 birds has no recording, so it has photo cards only." in r.out
    assert "1 of the 12 birds has no photo, so it has audio cards only." in r.out


def test_no_line_for_a_kind_no_chosen_card_needs(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-ma", "--cards", "photo"], tmp_path, monkeypatch, capsys)
    assert "no recording" not in r.out
    r = run_cli(["us-ma", "--cards", "audio"], tmp_path, monkeypatch, capsys)
    assert "no photo," not in r.out


def _note(species: str, with_photo: bool, with_audio: bool, card_type: str) -> PlannedNote:
    # The summary only asks whether a media reference is there, so a stand-in will do.
    photo = object() if with_photo else None
    audio = object() if with_audio else None
    return PlannedNote(species, card_type, photo=photo, audio=audio)  # type: ignore[arg-type]


def test_the_missing_kind_lines_are_pluralised():
    notes = [_note(f"s{i}", True, i >= 3, "photo") for i in range(10)]
    notes += [_note(f"s{i}", True, True, "audio") for i in range(3, 10)]
    cards = ["photo", "audio"]
    (line,) = cli._missing_kind_lines(notes, 10, cards)
    assert line == "3 of the 10 birds have no recording, so they have photo cards only."
    (line,) = cli._missing_kind_lines(notes[:1] + notes[3:], 8, cards)
    assert line == "1 of the 8 birds has no recording, so it has photo cards only."
    assert cli._missing_kind_lines(notes[3:], 7, cards) == []


def test_several_birds_without_media_say_have_and_they():
    assert cli._plural(2, "has", "have") == "have" and cli._plural(1, "it has", "they have") == "it has"


# ---------------------------------------------------------------------------------------
# 9. Flags
# ---------------------------------------------------------------------------------------


def test_version_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"avianki {metadata.version('avianki')}"


@pytest.mark.parametrize("spelling", ["EVERYTHING", "Everything", "everything"])
def test_tier_is_case_insensitive(spelling, tmp_path, monkeypatch, capsys):
    r = run_cli(["us-ma", "--tier", spelling], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err


def test_a_wrong_tier_is_still_rejected(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "--tier", "all"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2


def test_everything_is_described_as_the_top_400_not_all(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "all of them" not in text
    assert "400 most common" in text


@pytest.mark.parametrize("name", ["", "   "])
def test_an_empty_deck_name_is_a_usage_error(name, tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-ma", "--deck-name", name], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "deck name" in capsys.readouterr().err


def test_a_double_colon_in_the_deck_name_warns_that_anki_will_nest_it(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az", "--deck-name", "Birds::Az"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert "warning" in r.err and "nest" in r.err and "Birds::Az" in r.err


def test_a_plain_deck_name_does_not_warn(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az", "--deck-name", "Birds"], tmp_path, monkeypatch, capsys)
    assert r.err == ""


# ---------------------------------------------------------------------------------------
# 10. Region lookup through the CLI
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["ma", "MA", "Ma"])
def test_a_bare_state_code_finds_the_region(query, tmp_path, monkeypatch, capsys):
    r = run_cli([query], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    assert (tmp_path / "AviAnki-us-ma.apkg").is_file()


def test_an_ambiguous_region_does_not_suggest_ebird(tmp_path, monkeypatch, capsys):
    copy = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG, copy, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    manifest["regions"][2]["name"] = "Massachusetts"
    (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    r = run_cli(["Massachusetts"], tmp_path, monkeypatch, capsys, catalog=copy)
    assert r.code == 2
    assert "matches several regions" in r.err
    assert "--ebird" not in r.err and "eBird" not in r.err


def test_an_unknown_region_still_suggests_ebird(tmp_path, monkeypatch, capsys):
    r = run_cli(["Atlantis"], tmp_path, monkeypatch, capsys)
    assert r.code == 2 and "--ebird" in r.err


# ---------------------------------------------------------------------------------------
# 11. Errors that say what to do
# ---------------------------------------------------------------------------------------


def test_a_catalog_that_cannot_be_read_says_to_check_the_connection_or_url(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run_cli(["us-ma"], tmp_path, monkeypatch, capsys, catalog=empty)
    assert r.code == 1
    assert "--catalog-url" in r.err and "try again later" in r.err


def test_a_media_file_missing_from_the_catalog_says_try_again(tmp_path, monkeypatch, capsys):
    copy = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG, copy, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    for media in (copy / "media").iterdir():
        media.unlink()
    r = run_cli(["us-az"], tmp_path, monkeypatch, capsys, catalog=copy)
    assert r.code == 1
    assert "probably updated" in r.err and "try again" in r.err
    assert "Check your internet" not in r.err  # the 404 advice replaces the generic line


def test_an_unwritable_cache_dir_names_the_flag(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "afile"
    blocker.write_text("not a folder")
    code, _, err = call(
        ["us-az", "--catalog-url", str(FIXTURE_CATALOG), "--cache-dir", str(blocker / "cache")],
        tmp_path,
        monkeypatch,
        capsys,
    )
    assert code == 1
    assert "--cache-dir" in err and "cannot write" in err


# ---------------------------------------------------------------------------------------
# 12. No duplicate output
# ---------------------------------------------------------------------------------------


def test_the_deck_is_reported_once_at_default_verbosity(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az"], tmp_path, monkeypatch, capsys)
    assert "INFO" not in r.out
    assert r.out.lower().count("wrote ") == 1


def test_verbose_still_logs_the_write(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az", "-v"], tmp_path, monkeypatch, capsys)
    assert "DEBUG" in r.out and "media files" in r.out


# ---------------------------------------------------------------------------------------
# 13. --subdeck is honest
# ---------------------------------------------------------------------------------------


def test_the_subdeck_help_says_only_new_birds_move(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "not yet in your collection" in text
    assert "browser" in text


def test_a_subdeck_names_the_notes_deck_and_keeps_note_identity(tmp_path, monkeypatch, capsys):
    plain = run_cli(["us-az", "-o", "plain.apkg"], tmp_path, monkeypatch, capsys)
    sub = run_cli(["us-az", "--subdeck", "-o", "sub.apkg"], tmp_path, monkeypatch, capsys)
    assert plain.code == sub.code == 0
    # Same notes (so same GUIDs: ADR 0009), only the deck they belong to differs.
    assert note_fields(tmp_path / "plain.apkg") == note_fields(tmp_path / "sub.apkg")
