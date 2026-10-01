"""`--theme`, `--theme-file` and `--name-on-photo` (ADR 0028): the card look chosen on the command line."""

from __future__ import annotations

import json

import pytest
from cli_fakes import read_apkg, run_cli
from ebird_fakes import install

from avianki import cli
from avianki.deck import themes
from avianki.deck.notetypes import MODELS

ALL = "photo,audio,photo-audio"
MY_THEME = """
font = "mono"
name_style = "caps"
rule = "side"

[light]
background = "#fff7e0"
name = "#c2410c"
"""


def models_in(path):
    """The note types of an .apkg as {name: model json}."""
    conn, _ = read_apkg(path)
    try:
        (raw,) = conn.execute("SELECT models FROM col").fetchone()
    finally:
        conn.close()
    return {m["name"]: m for m in json.loads(raw).values()}


def test_a_deck_with_no_look_options_carries_the_default_css_and_back(tmp_path, monkeypatch, capsys):
    r = run_cli(["us-az", "--cards", ALL, "-o", "d.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    models = models_in(tmp_path / "d.apkg")
    assert len(models) == 3
    for card_type, model in MODELS.items():
        assert models[model.name]["css"] == themes.BASE_CSS
        assert models[model.name]["tmpls"][0]["afmt"] == model.templates[0]["afmt"]


@pytest.mark.parametrize("theme", themes.THEME_NAMES)
@pytest.mark.parametrize("overlay", [False, True])
def test_theme_and_name_on_photo_set_the_css_and_nothing_of_the_identity(theme, overlay, tmp_path, monkeypatch, capsys):
    argv = ["us-az", "--cards", ALL, "--theme", theme, "-o", "d.apkg"] + (["--name-on-photo"] if overlay else [])
    r = run_cli(argv, tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    models = models_in(tmp_path / "d.apkg")
    assert {int(m["id"]) for m in models.values()} == {m.model_id for m in MODELS.values()}
    for model in themes_models(theme, overlay).values():
        got = models[model.name]
        assert got["css"] == themes.compose_css(theme, overlay)
        assert got["tmpls"][0]["afmt"] == model.templates[0]["afmt"]
        assert [f["name"] for f in got["flds"]] == [f["name"] for f in model.fields]


def themes_models(theme, overlay):
    from avianki.deck.notetypes import models_for

    return models_for(theme, overlay)


def test_a_theme_file_sets_the_look(tmp_path, monkeypatch, capsys):
    (tmp_path / "mine.toml").write_text(MY_THEME, encoding="utf-8")
    r = run_cli(["us-az", "--cards", ALL, "--theme-file", "mine.toml", "--name-on-photo", "-o", "d.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    tokens = themes.tokens_from_toml(MY_THEME)
    models = models_in(tmp_path / "d.apkg")
    assert {m["css"] for m in models.values()} == {themes.compose_css(tokens, True)}
    assert themes.FONTS["mono"] in next(iter(models.values()))["css"]


def test_a_copied_theme_is_a_valid_theme_file(tmp_path, monkeypatch, capsys):
    # What the website's "Copy theme" gives is read back by --theme-file.
    (tmp_path / "nord.toml").write_text(themes.tokens_to_toml(themes.THEMES["nord"].tokens), encoding="utf-8")
    r = run_cli(["us-az", "--cards", ALL, "--theme-file", "nord.toml", "-o", "d.apkg"], tmp_path, monkeypatch, capsys)
    assert r.code == 0, r.err
    # Tokens only: a built-in theme's extra rules (nord's credit box) are not expressible in a theme file.
    expected = themes.compose_css(themes.THEMES["nord"].tokens, False)
    assert {m["css"] for m in models_in(tmp_path / "d.apkg").values()} == {expected}


def test_theme_and_theme_file_cannot_be_combined(tmp_path, monkeypatch, capsys):
    (tmp_path / "mine.toml").write_text(MY_THEME, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-az", "--theme", "nord", "--theme-file", "mine.toml"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_an_unknown_theme_is_a_usage_error_that_lists_the_choices(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-az", "--theme", "neon"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err and "nord" in err
    assert not list(tmp_path.glob("*.apkg"))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[light]\nbackground = "red"\n', "colour"),
        ('[light]\nbackground = "#12345"\n', "colour"),
        ('font = "Comic Sans"\n', "font"),
        ('corners = "50%"\n', "corners"),
        ('colour = "#ffffff"\n', "unknown key"),
        ("[light\n", "TOML"),
    ],
)
def test_a_bad_theme_file_is_a_usage_error(text, message, tmp_path, monkeypatch, capsys):
    (tmp_path / "bad.toml").write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-az", "--theme-file", "bad.toml"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err
    assert not list(tmp_path.glob("*.apkg"))


def test_a_missing_theme_file_is_a_usage_error(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(["us-az", "--theme-file", "nope.toml"], tmp_path, monkeypatch, capsys)
    assert exc.value.code == 2
    assert "nope.toml" in capsys.readouterr().err


def test_help_explains_the_look_options_and_that_a_collection_has_one_look(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = " ".join(capsys.readouterr().out.split()).replace("- ", "-")  # argparse wraps at hyphens
    for flag in ("--theme", "--theme-file", "--name-on-photo"):
        assert flag in text
    assert "one collection has one look" in text
    for name in themes.THEME_NAMES:
        assert name in text


def test_ebird_decks_honour_the_look(tmp_path, monkeypatch, capsys):
    install(monkeypatch)
    r = run_cli(
        ["--ebird", "US-MA-017", "--theme", "nord", "--name-on-photo", "-o", "e.apkg"],
        tmp_path,
        monkeypatch,
        capsys,
        env={"EBIRD_API_KEY": "k3y"},
    )
    assert r.code == 0, r.err
    assert {m["css"] for m in models_in(tmp_path / "e.apkg").values()} == {themes.compose_css("nord", True)}
