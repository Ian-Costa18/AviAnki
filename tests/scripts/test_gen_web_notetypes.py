"""scripts/gen_web_notetypes.py keeps web/js/notetypes.json equal to what avianki.deck defines.

Python is the single source of truth (ADR 0006, 0009); the browser reads the JSON. These tests
fail the build when the checked-in file drifts, and prove the description strings the browser
assembles are the ones ``deck_description`` produces.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType

from deck_fakes import manifest

from avianki.deck.credits import EBIRD_NOTICE, LICENCE_NOTICE, STUDY_GUIDANCE, deck_description
from avianki.deck.notetypes import CARD_TYPES, FIELDS, MODEL_SEEDS, MODELS

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "gen_web_notetypes.py"
CHECKED_IN = REPO / "web" / "js" / "notetypes.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_web_notetypes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_json_equals_a_fresh_dump() -> None:
    fresh = _load().render()
    on_disk = CHECKED_IN.read_bytes().decode("utf-8")
    assert on_disk.replace("\r\n", "\n") == fresh, "run: uv run python scripts/gen_web_notetypes.py"


def test_check_mode_agrees(capsys) -> None:
    assert _load().main(["--check"]) == 0
    assert capsys.readouterr().err == ""


def test_check_mode_fails_on_a_stale_file(tmp_path, monkeypatch, capsys) -> None:
    module = _load()
    stale = tmp_path / "notetypes.json"
    stale.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "OUT", stale)
    assert module.main(["--check"]) == 1
    assert "out of date" in capsys.readouterr().err
    assert stale.read_text(encoding="utf-8") == "{}\n"  # --check never writes


def test_write_mode_rewrites_the_file(tmp_path, monkeypatch) -> None:
    module = _load()
    out = tmp_path / "notetypes.json"
    monkeypatch.setattr(module, "OUT", out)
    assert module.main([]) == 0
    assert out.read_bytes().decode("utf-8") == module.render()
    assert b"\r\n" not in out.read_bytes()


def test_the_json_carries_every_note_type_as_genanki_writes_it() -> None:
    doc = json.loads(CHECKED_IN.read_text(encoding="utf-8"))
    assert doc["card_types"] == list(CARD_TYPES)
    assert doc["fields"] == list(FIELDS)
    assert list(doc["models"]) == list(CARD_TYPES)
    for card_type in CARD_TYPES:
        model = doc["models"][card_type]
        assert model["seed"] == MODEL_SEEDS[card_type]
        assert model["id"] == MODELS[card_type].model_id
        assert model["json"] == json.loads(json.dumps(MODELS[card_type].to_json(0, 0)))
        assert model["json"]["req"], "req is what decides which templates make a card"


def test_description_strings_equal_deck_description() -> None:
    """The browser joins these fixed strings around the manifest's credits; so must Python."""
    doc = json.loads(CHECKED_IN.read_text(encoding="utf-8"))["description"]
    assert doc["study_guidance"] == list(STUDY_GUIDANCE)
    assert doc["licence_notice"] == LICENCE_NOTICE
    assert doc["ebird_notice"] == EBIRD_NOTICE

    bare = replace(manifest(), dataset_credits=[])
    plain = deck_description(bare, ebird=False)
    assert plain == "<p>" + "<br>".join(doc["study_guidance"]) + "</p>\n<p>" + doc["licence_notice"] + "</p>"
    assert deck_description(bare, ebird=True) == plain + "\n<p>" + doc["ebird_notice"] + "</p>"
