"""Audio processing: window, high-pass, loudness-normalise, MP3 (ADR 0011).

Pure functions over bytes, driving the ``ffmpeg`` and ``ffprobe`` found on PATH. Inputs
are written to a private temporary directory that is always removed, so a failure never
leaves partial output behind.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from avianki.media.errors import MediaError

__all__ = ["MediaError", "ProcessedAudio", "excerpt", "probe_duration", "process_audio"]

log = logging.getLogger("bird_deck")

# The chain the audio research measured: 46 dB of loudness spread down to 6 dB.
FILTER_CHAIN = "highpass=f=250,loudnorm=I=-18:TP=-1.5:LRA=11"
SAMPLE_RATE = 44_100
BITRATE = "96k"
_TIMEOUT_S = 180

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ProcessedAudio:
    data: bytes
    duration_s: float
    modifications: tuple[str, ...]


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None and name == "ffprobe":
        # ffprobe ships beside ffmpeg; find it there if only ffmpeg is on PATH.
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
            if sibling.exists():
                path = str(sibling)
    if path is None:
        raise MediaError(f"{name} not found on PATH; install ffmpeg")
    return path


def _run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(cmd[0]).stem} timed out after {_TIMEOUT_S} s") from exc
    except OSError as exc:
        raise MediaError(f"could not run {cmd[0]}: {exc}") from exc


def _stderr_tail(proc: subprocess.CompletedProcess[bytes]) -> str:
    return proc.stderr.decode(errors="replace").strip()[-300:]


def _probe_file(path: Path) -> float:
    """Duration in seconds of the audio in ``path``; ``MediaError`` if it isn't audio."""
    proc = _run(
        [
            _tool("ffprobe"), "-v", "error",
            "-show_entries", "format=duration:stream=codec_type",
            "-of", "json", str(path),
        ]
    )  # fmt: skip
    if proc.returncode != 0:
        raise MediaError(f"unreadable audio: {_stderr_tail(proc)}")
    try:
        info = json.loads(proc.stdout)
    except ValueError as exc:
        raise MediaError("unreadable audio: ffprobe gave no JSON") from exc
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise MediaError("unreadable audio: no audio stream")
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = _decode_duration(path)  # e.g. webm streams carry no container duration
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError(f"unreadable audio: duration {duration}")
    return duration


def _decode_duration(path: Path) -> float:
    """Slow path: decode to null and read the final ``time=`` from ffmpeg's progress."""
    proc = _run([_tool("ffmpeg"), "-nostdin", "-i", str(path), "-vn", "-f", "null", "-"])
    if proc.returncode != 0:
        raise MediaError(f"unreadable audio: {_stderr_tail(proc)}")
    times = _TIME_RE.findall(proc.stderr.decode(errors="replace"))
    if not times:
        raise MediaError("unreadable audio: could not measure duration")
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def probe_duration(data: bytes) -> float:
    """Duration in seconds of ``data`` (ogg, wav, mp3, flac, m4a, webm, ...)."""
    with tempfile.TemporaryDirectory(prefix="avianki-audio-") as tmp:
        src = Path(tmp) / "in.bin"
        src.write_bytes(data)
        return _probe_file(src)


def excerpt(data: bytes, seconds: float = 60.0) -> bytes:
    """The first ``seconds`` of ``data`` as 48 kHz mono 16-bit WAV, for BirdNET (ADR 0023).

    Analysing only the opening minute keeps a cold build's compute bounded. Timing is
    untouched (the cut starts at 0 and nothing is trimmed from the front), so a window
    BirdNET picks in the excerpt starts at the same offset in the original recording. A clip
    shorter than ``seconds`` comes back whole, in the same format. Raises `MediaError` if
    ``data`` isn't audio.
    """
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"seconds must be a finite number > 0, got {seconds}")
    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="avianki-audio-") as tmp:
        src, dst = Path(tmp) / "in.bin", Path(tmp) / "out.wav"
        src.write_bytes(data)
        _probe_file(src)  # a clear "unreadable audio" before ffmpeg's own noise
        proc = _run(
            [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(src), "-t", f"{seconds:g}",
                "-vn", "-map_metadata", "-1", "-ac", "1", "-ar", "48000",
                "-c:a", "pcm_s16le", "-f", "wav", str(dst),
            ]
        )  # fmt: skip
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            raise MediaError(f"ffmpeg failed to cut the excerpt: {_stderr_tail(proc)}")
        return dst.read_bytes()


def process_audio(data: bytes, start_s: float = 0.0, *, seconds: float = 10.0) -> ProcessedAudio:
    """Cut a ``seconds``-long window at ``start_s``, filter it and encode mono 44.1 kHz MP3.

    A clip no longer than ``seconds`` is kept whole. A window that would overrun the end is
    shifted back so it still lasts ``seconds``. The output is bit-exact (no version tags or
    timestamps), so the same input and window give the same bytes with the same ffmpeg.
    """
    if not math.isfinite(start_s) or start_s < 0:
        raise ValueError(f"start_s must be a finite number >= 0, got {start_s}")
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"seconds must be a finite number > 0, got {seconds}")

    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="avianki-audio-") as tmp:
        src, dst = Path(tmp) / "in.bin", Path(tmp) / "out.mp3"
        src.write_bytes(data)
        total = _probe_file(src)

        trimmed = total > seconds
        start = min(start_s, total - seconds) if trimmed else 0.0
        window = ["-ss", f"{start:.3f}", "-t", f"{seconds:g}"] if trimmed else []

        proc = _run(
            [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                *window, "-i", str(src),
                "-vn", "-map_metadata", "-1", "-af", FILTER_CHAIN,
                "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-c:a", "libmp3lame", "-b:a", BITRATE,
                "-fflags", "+bitexact", "-flags:a", "+bitexact",
                "-f", "mp3", str(dst),
            ]
        )  # fmt: skip
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            raise MediaError(f"ffmpeg failed to encode audio: {_stderr_tail(proc)}")
        out = dst.read_bytes()
        duration = _probe_file(dst)

    modifications = ([f"trimmed to {seconds:g} s"] if trimmed else []) + [
        "high-pass filtered",
        "loudness normalised",
        "transcoded to MP3",
    ]
    return ProcessedAudio(data=out, duration_s=duration, modifications=tuple(modifications))
