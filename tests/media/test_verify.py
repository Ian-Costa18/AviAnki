"""Tests for avianki.media.verify: the scoring maths, label mapping, the missing-extra path, and
`analyse` with a fake analyser. The real-model test is an integration test (needs the extra)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from avianki.media import verify
from avianki.media.verify import (
    BirdNetAnalyzer,
    ClipAnalysis,
    UnreadableAudio,
    VerifyUnavailable,
    WindowScore,
    analyse,
    birdnet_label,
)

ROBIN = "Turdus migratorius_American Robin"
LABELS = [
    "Cardinalis cardinalis_Northern Cardinal",
    ROBIN,
    "Turdus merula_Common Blackbird",
    "Setophaga coronata_Yellow-rumped Warbler",
]
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def scores(*confidences: float, step: float = 3.0) -> list[WindowScore]:
    return [WindowScore(i * step, i * step + 3.0, c) for i, c in enumerate(confidences)]


def clip(*confidences: float, duration: float | None = None, **kw) -> ClipAnalysis:
    return ClipAnalysis(scores(*confidences), duration_s=duration, **kw)


# -- passes / best_confidence ------------------------------------------------------------------


def test_passes_at_exactly_the_threshold():
    assert clip(0.1, 0.5, 0.1).passes


def test_fails_just_below_the_threshold():
    assert not clip(0.1, 0.4999, 0.2).passes


def test_threshold_is_configurable():
    assert clip(0.3, min_confidence=0.25).passes
    assert not clip(0.3, min_confidence=0.35).passes


def test_no_windows_never_passes():
    empty = ClipAnalysis([])
    assert not empty.passes
    assert empty.best_confidence == 0.0
    assert empty.best_window() == (0.0, 0.0)


def test_best_confidence_is_the_maximum():
    assert clip(0.2, 0.9, 0.4).best_confidence == 0.9


# -- best_window -------------------------------------------------------------------------------


def test_best_window_takes_the_densest_ten_seconds():
    # 30 s of audio; the strong call sits at 12-21 s.
    a = clip(0.0, 0.0, 0.0, 0.0, 0.9, 0.8, 0.7, 0.0, 0.0, 0.0, duration=30.0)
    assert a.best_window() == (12.0, 22.0)
    assert a.best_window_score() == pytest.approx(2.4)


def test_best_window_ties_go_to_the_earliest():
    a = clip(0.5, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, duration=30.0)
    assert a.best_window() == (0.0, 10.0)


def test_best_window_covers_a_call_flush_with_the_end():
    # 12 s of audio: windows at 0, 3, 6, 9. The best ten seconds is [2, 12), which holds the
    # last three windows; window-aligned starts alone would only offer [0, 10).
    a = clip(0.0, 0.6, 0.6, 0.6, duration=12.0)
    assert a.best_window() == (2.0, 12.0)
    assert a.best_window_score() == pytest.approx(1.8)


def test_best_window_ignores_the_padded_final_window():
    # BirdNET pads the last 3 s window past the end of a 22.77 s recording; it must not be
    # counted inside a stretch, and no stretch may run past the audio.
    a = clip(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.9, duration=22.77)
    start, end = a.best_window()
    assert end <= 22.77 + 1e-9
    assert a.best_window_score() < 0.9


def test_short_clip_is_returned_whole():
    a = clip(0.7, 0.2, duration=6.0)
    assert a.best_window() == (0.0, 6.0)
    assert a.best_window_score() == pytest.approx(0.9)


def test_clip_of_exactly_ten_seconds_is_returned_whole():
    assert clip(0.1, 0.2, 0.3, 0.4, duration=10.0).best_window() == (0.0, 10.0)


def test_unknown_duration_falls_back_to_the_last_window_end():
    a = clip(0.9, 0.0, 0.0, 0.0)  # windows end at 12 s
    assert a.total_duration_s == 12.0
    assert a.best_window() == (0.0, 10.0)


def test_best_window_honours_a_different_length():
    a = clip(0.0, 0.9, 0.0, 0.0, 0.0, 0.0, duration=18.0)
    assert a.best_window(seconds=3.0) == (3.0, 6.0)


def test_overlapping_windows_are_handled():
    # 1.5 s hop: window k spans [1.5k, 1.5k + 3).
    windows = [WindowScore(1.5 * k, 1.5 * k + 3.0, c) for k, c in enumerate([0, 0, 0, 0.8, 0.9, 0, 0, 0, 0])]
    a = ClipAnalysis(windows, duration_s=13.5)
    start, end = a.best_window()
    assert start <= 4.5 and end >= 7.5  # both strong windows sit inside the stretch


# -- birdnet_label -----------------------------------------------------------------------------


def test_label_exact_match():
    assert birdnet_label("Turdus migratorius", LABELS) == ROBIN


def test_label_no_match_is_none():
    assert birdnet_label("Passer domesticus", LABELS) is None


def test_label_wrong_genus_is_none():
    # Same epithet, other genus: never a match. No fuzzy matching.
    assert birdnet_label("Turdus coronata", LABELS) is None
    assert birdnet_label("Setophaga migratorius", LABELS) is None


def test_label_partial_names_do_not_match():
    assert birdnet_label("Turdus", LABELS) is None
    assert birdnet_label("Turdus migratorius_American Robin", LABELS) is None


def test_label_needs_a_single_hit():
    assert birdnet_label("Turdus migratorius", [ROBIN, ROBIN.replace("American", "Other")]) is None


def test_label_synonym_table_is_explicit_and_still_exact():
    labels = ["Setophaga coronata_Yellow-rumped Warbler"]
    assert birdnet_label("Dendroica coronata", labels) is None
    assert birdnet_label("Dendroica coronata", labels, {"Dendroica coronata": "Setophaga coronata"}) == labels[0]
    assert birdnet_label("Setophaga coronata", labels, {"Dendroica coronata": "Setophaga coronata"}) == labels[0]


# -- missing extra -----------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["birdnet", "ai_edge_litert.interpreter"])
def test_missing_extra_raises_with_install_hint(monkeypatch, missing):
    def fake_import(name, *a, **kw):
        if name == missing:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return object()

    monkeypatch.setattr(verify.importlib, "import_module", fake_import)
    with pytest.raises(VerifyUnavailable, match=r"avianki\[verify\]"):
        BirdNetAnalyzer().labels  # noqa: B018


def test_unavailable_is_a_verify_error():
    assert issubclass(VerifyUnavailable, verify.VerifyError)
    assert issubclass(UnreadableAudio, verify.VerifyError)


# -- analyse with a fake analyser --------------------------------------------------------------


class FakeAnalyzer:
    def __init__(self, confidences: list[float]) -> None:
        self.confidences = confidences
        self.calls: list[tuple[str, str, float]] = []

    def predict(self, path: Path, label: str) -> list[WindowScore]:
        import wave

        with wave.open(str(path), "rb") as w:  # the analyser must receive 48 kHz mono wav
            self.calls.append((label, f"{w.getframerate()}/{w.getnchannels()}", w.getnframes() / w.getframerate()))
        return scores(*self.confidences)


def tone_bytes(tmp_path: Path, seconds: float, *, suffix: str = "mp3") -> bytes:
    out = tmp_path / f"tone.{suffix}"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=880:duration={seconds}"]
    subprocess.run([*cmd, "-ac", "2", "-ar", "44100", str(out)], check=True)
    return out.read_bytes()


def test_analyse_decodes_to_48k_mono_and_scores_with_the_fake(tmp_path):
    fake = FakeAnalyzer([0.2, 0.7])
    result = analyse(tone_bytes(tmp_path, 6.0), ROBIN, analyzer=fake)
    (label, fmt, seconds), = fake.calls
    assert (label, fmt) == (ROBIN, "48000/1")
    assert seconds == pytest.approx(6.0, abs=0.1)
    assert result.passes and result.best_confidence == 0.7
    assert result.duration_s == pytest.approx(6.0, abs=0.1)
    assert result.best_window() == (0.0, pytest.approx(result.duration_s))


def test_analyse_applies_min_confidence(tmp_path):
    data = tone_bytes(tmp_path, 3.0, suffix="ogg")
    assert not analyse(data, ROBIN, analyzer=FakeAnalyzer([0.4])).passes
    assert analyse(data, ROBIN, min_confidence=0.4, analyzer=FakeAnalyzer([0.4])).passes


def test_analyse_rejects_bytes_that_are_not_audio():
    with pytest.raises(UnreadableAudio):
        analyse(b"definitely not audio", ROBIN, analyzer=FakeAnalyzer([1.0]))


def test_analyse_without_ffmpeg_is_unavailable(monkeypatch):
    monkeypatch.setattr(verify.shutil, "which", lambda name: None)
    with pytest.raises(VerifyUnavailable, match="ffmpeg"):
        analyse(b"x", ROBIN, analyzer=FakeAnalyzer([1.0]))


# -- the real model (integration; needs the verify extra and the network for the first run) ----


@pytest.mark.integration
@needs_ffmpeg
def test_real_model_scores_noise_below_the_gate(tmp_path):
    pytest.importorskip("birdnet")
    pytest.importorskip("ai_edge_litert.interpreter")
    noise = tmp_path / "noise.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:r=48000:a=0.3", str(noise)],
        check=True,
    )
    with BirdNetAnalyzer() as analyzer:
        assert ROBIN in analyzer.labels
        result = analyse(noise.read_bytes(), ROBIN, analyzer=analyzer)
    assert [(w.start_s, w.end_s) for w in result.windows] == [(0.0, 3.0), (3.0, 6.0)]
    assert not result.passes
    assert result.best_confidence < 0.5
