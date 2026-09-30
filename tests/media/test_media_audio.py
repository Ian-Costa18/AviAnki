"""Tests for avianki.media.audio: inputs are synthesised with ffmpeg, no network.

These need ffmpeg and ffprobe on PATH and fail loudly (they never skip) when it is absent.
"""

import json
import re
import shutil
import subprocess
import tempfile
from array import array
from pathlib import Path

import pytest

from avianki.media import MediaError
from avianki.media.audio import excerpt, probe_duration, process_audio

LOW_HZ, HIGH_HZ = 1000, 3000
CHANGE_AT_S = 8  # the tone steps from LOW_HZ to HIGH_HZ here


def _ffmpeg(*args: str, out: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args, str(out)],
        check=True,
        capture_output=True,
    )
    return out.read_bytes()


def _stepped_tone(tmp_path: Path, total_s: float, name: str = "tone.wav", *codec: str) -> bytes:
    """LOW_HZ for CHANGE_AT_S seconds, then HIGH_HZ, quiet (about -35 dBFS) and mono."""
    rest = total_s - CHANGE_AT_S
    fc = (
        f"sine=f={LOW_HZ}:r=44100:d={CHANGE_AT_S}[a];sine=f={HIGH_HZ}:r=44100:d={rest}[b];"
        "[a][b]concat=n=2:v=0:a=1,volume=0.02"
    )
    return _ffmpeg("-f", "lavfi", "-i", fc, *codec, out=tmp_path / name)


def _short_tone(tmp_path: Path, seconds: float) -> bytes:
    return _ffmpeg(
        "-f", "lavfi", "-i", f"sine=f={HIGH_HZ}:r=44100:d={seconds},volume=0.02",
        out=tmp_path / "short.wav",
    )  # fmt: skip


def _ffprobe_stream(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,channels,sample_rate,bit_rate,duration",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    return json.loads(proc.stdout)["streams"][0]


def _pcm(mp3: bytes, tmp_path: Path) -> array:
    """Decode to mono 44.1 kHz signed 16-bit samples."""
    src = tmp_path / "decode.mp3"
    src.write_bytes(mp3)
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-f", "s16le", "-ac", "1",
         "-ar", "44100", "-"],
        check=True, capture_output=True,
    )  # fmt: skip
    samples = array("h")
    samples.frombytes(proc.stdout)
    return samples


def _freq(samples: array, start_s: float, end_s: float) -> float:
    """Dominant frequency of a pure tone by zero crossings (ignores the loud/quiet level)."""
    seg = samples[int(start_s * 44100) : int(end_s * 44100)]
    crossings = sum(1 for a, b in zip(seg, seg[1:]) if (a < 0) != (b < 0))
    return crossings / 2 / (end_s - start_s)


def _integrated_lufs(mp3: bytes, tmp_path: Path) -> float:
    src = tmp_path / "measure.mp3"
    src.write_bytes(mp3)
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af", "ebur128=framelog=quiet",
         "-f", "null", "-"],
        check=True, capture_output=True,
    )  # fmt: skip
    summary = proc.stderr.decode(errors="replace").rsplit("Summary:", 1)[1]
    return float(re.search(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", summary).group(1))  # type: ignore[union-attr]


@pytest.fixture(scope="module")
def long_wav(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    return _stepped_tone(tmp_path_factory.mktemp("src"), 25)


def test_ffmpeg_and_ffprobe_are_installed():
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "install ffmpeg to run media tests"


def test_default_window_is_10s_mono_44k_96kbps_mp3(long_wav, tmp_path):
    result = process_audio(long_wav)
    out = tmp_path / "out.mp3"
    out.write_bytes(result.data)
    stream = _ffprobe_stream(out)
    assert stream["codec_name"] == "mp3"
    assert stream["channels"] == 1
    assert stream["sample_rate"] == "44100"
    assert abs(int(stream["bit_rate"]) - 96_000) < 3_000
    assert 9.9 < result.duration_s < 10.2
    assert abs(float(stream["duration"]) - result.duration_s) < 0.05
    assert result.modifications == (
        "trimmed to 10 s",
        "high-pass filtered",
        "loudness normalised",
        "transcoded to MP3",
    )


def test_default_window_starts_at_zero(long_wav, tmp_path):
    samples = _pcm(process_audio(long_wav).data, tmp_path)
    assert _freq(samples, 1, 6) == pytest.approx(LOW_HZ, rel=0.03)
    assert _freq(samples, 9, 9.8) == pytest.approx(HIGH_HZ, rel=0.03)


def test_start_s_selects_that_region(long_wav, tmp_path):
    # Window [5, 15): 3 s of LOW_HZ, then HIGH_HZ. Default window would be LOW_HZ for 8 s.
    samples = _pcm(process_audio(long_wav, 5).data, tmp_path)
    assert _freq(samples, 0.5, 2.5) == pytest.approx(LOW_HZ, rel=0.03)
    assert _freq(samples, 4, 9.5) == pytest.approx(HIGH_HZ, rel=0.03)


def test_window_after_the_change_is_all_high_tone(long_wav, tmp_path):
    result = process_audio(long_wav, CHANGE_AT_S + 1)
    samples = _pcm(result.data, tmp_path)
    assert _freq(samples, 0.3, 9.7) == pytest.approx(HIGH_HZ, rel=0.03)


def test_window_overrun_is_shifted_back_to_keep_10s(long_wav, tmp_path):
    result = process_audio(long_wav, 20)  # 20 + 10 > 25: window becomes [15, 25)
    assert 9.9 < result.duration_s < 10.2
    assert "trimmed to 10 s" in result.modifications
    assert _freq(_pcm(result.data, tmp_path), 0.3, 9.7) == pytest.approx(HIGH_HZ, rel=0.03)


def test_clip_shorter_than_window_is_kept_whole_without_trim_entry(tmp_path):
    result = process_audio(_short_tone(tmp_path, 6), start_s=3)
    assert 5.9 < result.duration_s < 6.3
    assert result.modifications == (
        "high-pass filtered",
        "loudness normalised",
        "transcoded to MP3",
    )


def test_custom_window_length(long_wav):
    result = process_audio(long_wav, seconds=4)
    assert 3.9 < result.duration_s < 4.2
    assert result.modifications[0] == "trimmed to 4 s"


def test_loudness_is_normalised_towards_minus_18_lufs(long_wav, tmp_path):
    # The source sits near -40 LUFS; single-pass loudnorm on a 10 s window lands close to
    # the target, so allow a few LU rather than an exact figure.
    assert _integrated_lufs(long_wav, tmp_path) < -30
    lufs = _integrated_lufs(process_audio(long_wav).data, tmp_path)
    assert lufs == pytest.approx(-18, abs=3.5)


def test_high_pass_removes_rumble(tmp_path):
    fc = (
        "sine=f=60:r=44100:d=12,volume=0.1[a];sine=f=2000:r=44100:d=12,volume=0.05[b];"
        "[a][b]amix=inputs=2:normalize=0"
    )
    rumble = _ffmpeg("-f", "lavfi", "-i", fc, out=tmp_path / "rumble.wav")
    # Premise: the raw mix is dominated by the 60 Hz rumble, so its crossing rate is low.
    src = tmp_path / "rumble.wav"
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-f", "s16le", "-ac", "1", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    raw_samples = array("h")
    raw_samples.frombytes(raw)
    assert _freq(raw_samples, 1, 9) < 1000
    samples = _pcm(process_audio(rumble).data, tmp_path)
    assert _freq(samples, 1, 9) == pytest.approx(2000, rel=0.1)


def test_same_input_and_window_give_identical_bytes(long_wav):
    first = process_audio(long_wav, 4).data
    assert process_audio(long_wav, 4).data == first
    # bitexact keeps a bare "Lavf" tag but drops the ffmpeg version that would change per upgrade
    assert not re.search(rb"Lav[cf]\d", first)


@pytest.mark.parametrize(
    ("name", "codec"),
    [
        ("in.ogg", ("-c:a", "libvorbis")),
        ("in.mp3", ("-c:a", "libmp3lame")),
        ("in.flac", ("-c:a", "flac")),
        ("in.m4a", ("-c:a", "aac")),
        ("in.webm", ("-c:a", "libopus")),
    ],
)
def test_accepts_common_input_formats(tmp_path, name, codec):
    data = _stepped_tone(tmp_path, 14, name, *codec)
    assert probe_duration(data) == pytest.approx(14, abs=0.3)
    result = process_audio(data, 2)
    assert 9.8 < result.duration_s < 10.3


def test_probe_duration_of_wav(long_wav):
    assert probe_duration(long_wav) == pytest.approx(25, abs=0.05)


@pytest.mark.parametrize("data", [b"", b"this is not audio" * 100, b"\x89PNG\r\n\x1a\n" + b"\0" * 64])
def test_unreadable_input_is_a_media_error(data):
    with pytest.raises(MediaError):
        probe_duration(data)
    with pytest.raises(MediaError):
        process_audio(data)


def test_video_only_input_is_a_media_error(tmp_path):
    video = _ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-c:v", "mpeg4",
                    out=tmp_path / "v.mp4")  # fmt: skip
    with pytest.raises(MediaError, match="no audio stream"):
        process_audio(video)


def test_missing_ffmpeg_is_a_media_error(long_wav, monkeypatch):
    monkeypatch.setattr("avianki.media.audio.shutil.which", lambda _name: None)
    with pytest.raises(MediaError, match="ffmpeg"):
        process_audio(long_wav)
    with pytest.raises(MediaError, match="ffprobe"):
        probe_duration(long_wav)


def test_temp_files_are_cleaned_up_on_success_and_failure(long_wav, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    process_audio(long_wav)
    with pytest.raises(MediaError):
        process_audio(b"garbage")
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("kwargs", [{"start_s": -1.0}, {"seconds": 0}, {"start_s": float("nan")}])
def test_bad_arguments_are_rejected(long_wav, kwargs):
    with pytest.raises(ValueError, match="must be a finite number"):
        process_audio(long_wav, **kwargs)


# --- excerpt: the first N seconds, for BirdNET (ADR 0023) -----------------------------------


def test_excerpt_keeps_only_the_first_seconds(tmp_path):
    long = _stepped_tone(tmp_path, 20.0)
    short = excerpt(long, seconds=6.0)
    assert probe_duration(short) == pytest.approx(6.0, abs=0.1)
    assert len(short) < len(long)


def test_excerpt_of_a_short_clip_is_the_whole_clip(tmp_path):
    clip = _short_tone(tmp_path, 4.0)
    assert probe_duration(excerpt(clip, seconds=60.0)) == pytest.approx(4.0, abs=0.1)


def test_excerpt_default_is_sixty_seconds(tmp_path):
    long = _ffmpeg("-f", "lavfi", "-i", "sine=f=1000:r=8000:d=75", out=tmp_path / "long.wav")
    assert probe_duration(excerpt(long)) == pytest.approx(60.0, abs=0.2)


def test_excerpt_keeps_timing_so_window_offsets_still_line_up(tmp_path):
    # the tone changes at CHANGE_AT_S; an excerpt must not shift it
    out = tmp_path / "ex.wav"
    out.write_bytes(excerpt(_stepped_tone(tmp_path, 20.0), seconds=12.0))
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(out), "-f", "s16le", "-ac", "1", "-ar", "44100", "-"],
        check=True, capture_output=True,
    )  # fmt: skip
    samples = array("h")
    samples.frombytes(proc.stdout)
    assert _freq(samples, 1, 6) == pytest.approx(LOW_HZ, rel=0.03)
    assert _freq(samples, 9, 11) == pytest.approx(HIGH_HZ, rel=0.03)


def test_excerpt_rejects_garbage_and_bad_arguments(long_wav):
    with pytest.raises(MediaError):
        excerpt(b"not audio")
    with pytest.raises(ValueError, match="seconds must be a finite number"):
        excerpt(long_wav, seconds=0)
