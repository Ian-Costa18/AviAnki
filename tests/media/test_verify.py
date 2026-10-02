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
    ClipChoice,
    UnreadableAudio,
    VerifyUnavailable,
    WindowScore,
    analyse,
    birdnet_label,
    competitor_labels,
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


# -- choosing the clip and measuring it (ADR 0031) ----------------------------------------------

SHRIKE = "Lanius ludovicianus_Loggerhead Shrike"
JAY = "Cyanocitta cristata_Blue Jay"
STELLERS = "Cyanocitta stelleri_Steller's Jay"
DOG = "Dog_Dog"
CRICKET = "Insecta_Insecta"


def grid(confidences: list[float], others: dict[int, dict[str, float]] | None = None, *, tail: int = 2, **kw):
    """A 1 s step grid: one 3 s window per second, then ``tail`` windows padded past the end."""
    others = others or {}
    n = len(confidences)
    wins = [WindowScore(float(i), i + 3.0, c, others.get(i, {})) for i, c in enumerate(confidences)]
    # BirdNET pads the final windows past the end; they must never count.
    wins += [WindowScore(float(n + j), n + j + 3.0, 0.0, {"Pad_Pad": 0.99}) for j in range(tail)]
    return ClipAnalysis(wins, duration_s=n + 2.0, **kw)


def test_the_clip_opens_on_the_first_step_where_the_target_reaches_the_gate():
    # 20 s of audio (18 steps): quiet, then the bird from step 4 to 13.
    conf = [0.0, 0.1, 0.1, 0.1] + [0.8] * 10 + [0.1] * 4
    got = grid(conf).choose()
    assert got.start_s == 4.0 and got.end_s == 14.0
    assert got.presence == 1.0 and got.usable


def test_the_start_is_pulled_back_so_the_clip_keeps_its_length():
    # The only hit is the last step: the clip is 10 s ending flush with the audio.
    conf = [0.1] * 17 + [0.9]
    got = grid(conf).choose()
    assert got.end_s - got.start_s == 10.0
    assert got.end_s == 20.0 and got.start_s == 10.0
    assert got.best_confidence == 0.9 and got.usable


def test_a_recording_no_longer_than_the_clip_is_used_whole():
    got = grid([0.2, 0.7, 0.7, 0.2]).choose()  # 6 s
    assert (got.start_s, got.end_s) == (0.0, 6.0)
    assert got.presence == 0.5


def test_metrics_are_taken_on_the_exact_final_clip_not_the_whole_recording():
    # A loud shrike sits before the bird; it is outside the clip, so it must not count.
    conf = [0.0] * 4 + [0.9] * 14
    early = grid(conf, {1: {SHRIKE: 0.95}}, label=JAY).choose(counted={SHRIKE})
    assert early.start_s == 4.0 and early.competitor == 0.0
    inside = grid(conf, {6: {SHRIKE: 0.7}}, label=JAY).choose(counted={SHRIKE})
    assert (inside.competitor, inside.competitor_label) == (0.7, SHRIKE)


def test_padded_final_windows_never_count_as_steps_or_competitors():
    got = grid([0.9] * 8, tail=2).choose()  # 10 s: 8 whole steps, 2 padded ones
    assert got.presence == 1.0 and got.competitor == 0.0


def test_presence_is_the_share_of_steps_at_the_gate():
    conf = [0.9] * 6 + [0.1] * 4 + [0.0] * 4  # 14 steps; the 10 s clip holds the first 8
    got = grid(conf).choose()
    assert got.start_s == 0.0
    assert got.presence == pytest.approx(6 / 8)
    assert got.mean_target == pytest.approx((0.9 * 6 + 0.1 * 2) / 8)


def test_only_counted_labels_compete():
    others = {i: {SHRIKE: 0.4, "Strix aluco_Tawny Owl": 0.9, CRICKET: 0.8} for i in range(8)}
    a = grid([0.9] * 8, others, label=JAY)
    assert a.choose(counted={SHRIKE, DOG}).competitor == 0.4
    assert a.choose(counted=set()).competitor == 0.0
    assert a.choose().competitor == 0.9  # None counts every label


def test_noise_labels_count_and_the_own_genus_does_not():
    got = grid([0.9] * 8, {2: {DOG: 0.6, STELLERS: 0.95}}, label=JAY).choose(counted={DOG, STELLERS})
    assert (got.competitor, got.competitor_label) == (0.6, DOG)  # Steller's Jay shares the genus
    assert grid([0.9] * 8, {2: {STELLERS: 0.95}}, label=JAY).choose(counted={STELLERS}).competitor == 0.0


def test_the_competitor_label_set_is_our_species_plus_noise():
    labels = [JAY, SHRIKE, "Strix aluco_Tawny Owl", DOG, CRICKET, "Noise_Noise", "Siren_Siren"]
    got = competitor_labels(["Cyanocitta cristata", "Lanius ludovicianus"], labels)
    assert got == {JAY, SHRIKE, DOG, "Siren_Siren"}


def test_a_faint_background_bird_is_tolerated_but_a_strong_one_is_not():
    faint = grid([0.9] * 8, {3: {SHRIKE: 0.3}}).choose(counted={SHRIKE})
    assert faint.good and faint.quality == pytest.approx(0.9)  # up to 0.3 costs nothing
    loud = grid([0.9] * 8, {3: {SHRIKE: 0.5}}).choose(counted={SHRIKE})
    assert not loud.good and loud.quality == pytest.approx(0.9 - 0.2)
    assert loud.usable  # it still passes the gate; it only ranks lower


@pytest.mark.parametrize(
    ("presence", "competitor", "best", "good", "usable"),
    [
        (0.6, 0.49, 0.9, True, True),
        (0.59, 0.0, 0.9, False, True),
        (0.9, 0.5, 0.9, False, True),
        (0.9, 0.0, 0.49, False, False),
    ],
)
def test_good_and_usable_thresholds(presence, competitor, best, good, usable):
    c = ClipChoice(0.0, 10.0, presence, competitor, "", 0.5, best)
    assert (c.good, c.usable) == (good, usable)


def test_a_clip_that_never_reaches_the_gate_is_unusable_but_still_measured():
    got = grid([0.3] * 14).choose()
    assert not got.usable and got.presence == 0.0 and got.mean_target == pytest.approx(0.3)


def test_the_chosen_clip_still_passes_when_a_denser_stretch_has_no_step_at_the_gate():
    # Steps 0-7 are all 0.45 (sum 3.6, the densest stretch) but below the gate; the one real hit is later.
    conf = [0.45] * 8 + [0.0] * 4 + [0.9] + [0.0] * 5
    got = grid(conf).choose()
    assert got.usable and got.best_confidence == 0.9


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
