"""BirdNET verification of audio candidates (ADR 0011, optional extra ``avianki[verify]``).

An audio candidate is accepted only if BirdNET, run on the *whole* recording, scores the
expected species at ``>= 0.5`` in at least one 3-second window. The clip that finally ships is
the 10-second stretch with the highest summed confidence for that species.

The scoring maths (`WindowScore`, `ClipAnalysis`) is pure and needs no model. The model itself
lives behind the `Analyzer` protocol so the catalog pipeline and the tests can fake it:
`BirdNetAnalyzer` is the real one and imports ``birdnet`` lazily, so a base install never needs
the extra (`VerifyUnavailable` says how to get it).

Decisions the ADR left open:

* Model: BirdNET v2.4 (6,522 labels, ``Genus species_Common Name``), the FP32 TFLite build, run
  through ``ai-edge-litert`` (no TensorFlow). ``birdnet`` downloads it on first use from a
  versioned Zenodo record into ``%APPDATA%/birdnet`` (Windows) or ``~/.local/share/birdnet``
  (Linux); set ``BIRDNET_APP_DATA`` to move it (that directory is what CI should cache).
* Segments: back-to-back 3-second windows (overlap 0), so "some 3-second window" is BirdNET's own
  segmentation, the 10-second sum never double-counts audio, and CPU cost is one inference per
  3 s of audio. ``BirdNetAnalyzer(overlap_s=...)`` can raise it.
* No location or week filter is applied. A Rhode Island recording may be a vagrant from
  elsewhere; this gate asks whether the sound is the species, not whether the bird is likely
  there.
"""

from __future__ import annotations

import atexit
import importlib
import logging
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from avianki.media.errors import MediaError

log = logging.getLogger("bird_deck")

SEGMENT_S = 3.0  # BirdNET's analysis window; fixed by the model.
MIN_CONFIDENCE = 0.5  # ADR 0011: the one place to tune the gate.
CLIP_S = 10.0  # length of the clip that ships.
MODEL_SAMPLE_RATE = 48_000
_EPS = 1e-6
_FFMPEG_TIMEOUT_S = 300

INSTALL_HINT = (
    "BirdNET verification needs the optional extra: install it with "
    "`pip install 'avianki[verify]'` (or `uv sync --extra verify`). The extra supports "
    "Python 3.11-3.13 only, because its inference runtime (ai-edge-litert) ships no wheels "
    "for 3.14 yet."
)


class VerifyError(MediaError):
    """BirdNET verification could not produce an answer for this clip."""


class VerifyUnavailable(VerifyError):
    """The ``verify`` extra (or ffmpeg) is missing. An infrastructure failure, never a reject."""


class UnreadableAudio(VerifyError):
    """ffmpeg could not decode the candidate. The caller rejects that candidate."""


@dataclass(frozen=True)
class WindowScore:
    """BirdNET's confidence for the expected species in ``[start_s, end_s)``."""

    start_s: float
    end_s: float
    confidence: float


@dataclass
class ClipAnalysis:
    """Per-window confidences for one expected species in one recording."""

    windows: list[WindowScore]
    min_confidence: float = MIN_CONFIDENCE
    # Length of the audio. BirdNET pads the last window past the end, so the last window's
    # end can exceed it; when unknown, the last window's end stands in.
    duration_s: float | None = field(default=None)

    @property
    def passes(self) -> bool:
        """True when some window reaches ``min_confidence`` (inclusive)."""
        return any(w.confidence >= self.min_confidence for w in self.windows)

    @property
    def best_confidence(self) -> float:
        return max((w.confidence for w in self.windows), default=0.0)

    @property
    def total_duration_s(self) -> float:
        if self.duration_s is not None:
            return self.duration_s
        return max((w.end_s for w in self.windows), default=0.0)

    def best_window(self, seconds: float = CLIP_S) -> tuple[float, float]:
        """The ``[start, end)`` stretch of ``seconds`` with the highest summed confidence.

        Only windows lying entirely inside a stretch count towards it (so the padded final
        window never does). Ties go to the earliest start. A recording no longer than
        ``seconds`` yields the whole recording.
        """
        start, end, _ = self._best(seconds)
        return start, end

    def best_window_score(self, seconds: float = CLIP_S) -> float:
        """The summed confidence inside `best_window`; what candidates are ranked by."""
        return self._best(seconds)[2]

    def _best(self, seconds: float) -> tuple[float, float, float]:
        total = self.total_duration_s
        if total <= seconds + _EPS:
            return 0.0, total, sum(w.confidence for w in self.windows)

        # The covered set only changes when the stretch starts on a window boundary, and the
        # last possible stretch is the one flush with the end of the recording.
        last_start = total - seconds
        starts = sorted({w.start_s for w in self.windows if w.start_s <= last_start + _EPS})
        if not starts or starts[-1] < last_start - _EPS:
            starts.append(last_start)

        best: tuple[float, float, float] | None = None
        for s in starts:
            e = s + seconds
            covered = sum(
                w.confidence
                for w in self.windows
                if w.start_s >= s - _EPS and w.end_s <= e + _EPS
            )
            if best is None or covered > best[2] + _EPS:  # strict: earliest wins ties
                best = (s, e, covered)
        assert best is not None
        return best


class Analyzer(Protocol):
    """Anything that scores a 48 kHz mono wav for one label; the real one is `BirdNetAnalyzer`."""

    def predict(self, path: Path, label: str) -> Sequence[WindowScore]: ...


# -- label mapping -----------------------------------------------------------------------------


def birdnet_label(
    sci_name: str,
    labels: Iterable[str],
    synonyms: Mapping[str, str] | None = None,
) -> str | None:
    """The BirdNET label for an IOC scientific name, or None when there is no exact match.

    Labels look like ``Turdus migratorius_American Robin``; only the part before the first
    underscore is compared, and it must equal ``sci_name`` exactly. There is no fuzzy or
    genus-level matching: a wrong bird is worse than a missing one, so unmapped species get no
    audio and are listed in the build report. ``synonyms`` (IOC name -> BirdNET's name) is the
    hook for curated one-off renames; it is empty by default.
    """
    wanted = (synonyms or {}).get(sci_name, sci_name).strip()
    hits = [label for label in labels if label.partition("_")[0] == wanted]
    return hits[0] if len(hits) == 1 else None


# -- the real analyser -------------------------------------------------------------------------


def _import_birdnet() -> Any:
    """Import ``birdnet`` (and its runtime) lazily; a missing extra is `VerifyUnavailable`."""
    try:
        birdnet = importlib.import_module("birdnet")
        importlib.import_module("ai_edge_litert.interpreter")
    except ImportError as exc:
        raise VerifyUnavailable(f"{INSTALL_HINT} (import failed: {exc})") from exc
    return birdnet


class BirdNetAnalyzer:
    """BirdNET v2.4 on CPU, loaded once and reused.

    ``birdnet`` runs inference in worker processes, and starting them costs about 2 s, so one
    prediction session stays open across clips. Call `close` (or use it as a context manager)
    to stop the workers; an ``atexit`` hook does it otherwise. On Windows a script that uses
    this must sit behind ``if __name__ == "__main__":`` because the workers are spawned.
    """

    def __init__(self, *, overlap_s: float = 0.0, n_workers: int = 1) -> None:
        if not 0.0 <= overlap_s < SEGMENT_S:
            raise ValueError(f"overlap_s must be in [0, {SEGMENT_S}): {overlap_s}")
        self.overlap_s = overlap_s
        self.n_workers = n_workers
        self._model: Any = None
        self._labels: list[str] | None = None
        self._label_index: dict[str, int] | None = None
        self._session: Any = None

    def __enter__(self) -> BirdNetAnalyzer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _load_model(self) -> Any:
        if self._model is None:
            birdnet = _import_birdnet()
            log.info("Loading BirdNET v2.4 (downloads the model on first use)")
            # "litert" avoids TensorFlow; the default "tflite" library would need it.
            self._model = birdnet.load("acoustic", "2.4", "tf", precision="fp32", library="litert")
            self._labels = [str(s) for s in self._model.species_list]
            self._label_index = {s: i for i, s in enumerate(self._labels)}
        return self._model

    @property
    def labels(self) -> list[str]:
        self._load_model()
        assert self._labels is not None
        return self._labels

    def _open_session(self) -> Any:
        if self._session is None:
            session = self._load_model().predict_session(
                top_k=None,  # every label per window, so one session serves any species
                n_workers=self.n_workers,
                n_producers=1,
                overlap_duration_s=self.overlap_s,
                default_confidence_threshold=None,  # report every window, however low
                max_n_files=1,
            )
            self._session = session.__enter__()
            atexit.register(self.close)
        return self._session

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            session.__exit__(None, None, None)

    def predict(self, path: Path, label: str) -> list[WindowScore]:
        self._load_model()
        assert self._label_index is not None
        wanted = self._label_index.get(label)
        if wanted is None:
            raise VerifyError(f"not a BirdNET v2.4 label: {label!r}")
        result = self._open_session().run(str(path))

        ids, probs = result.species_ids[0], result.species_probs[0]  # (windows, labels)
        step = SEGMENT_S - self.overlap_s
        windows: list[WindowScore] = []
        for i in range(ids.shape[0]):
            hit = (ids[i] == wanted).nonzero()[0]
            confidence = float(probs[i][hit[0]]) if len(hit) else 0.0
            windows.append(WindowScore(i * step, i * step + SEGMENT_S, confidence))
        return windows


_default: BirdNetAnalyzer | None = None


def default_analyzer() -> BirdNetAnalyzer:
    """The process-wide analyser, created on first use so the model loads once."""
    global _default
    if _default is None:
        _default = BirdNetAnalyzer()
    return _default


def load_labels() -> list[str]:
    """BirdNET v2.4's label list (``Genus species_Common Name``); downloads the model once."""
    return list(default_analyzer().labels)


# -- entry point -------------------------------------------------------------------------------


def _to_wav(src: Path, dst: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VerifyUnavailable("ffmpeg is not on PATH; it is needed to decode candidate audio")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1"]
    cmd += ["-ar", str(MODEL_SAMPLE_RATE), "-c:a", "pcm_s16le", str(dst)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise UnreadableAudio("ffmpeg timed out decoding the clip") from exc
    if proc.returncode != 0 or not dst.exists():
        raise UnreadableAudio(f"ffmpeg could not decode the clip: {proc.stderr.strip()[:200]}")


def _wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def analyse(
    data: bytes,
    label: str,
    *,
    min_confidence: float = MIN_CONFIDENCE,
    analyzer: Analyzer | None = None,
) -> ClipAnalysis:
    """Score every 3-second window of a recording for ``label``.

    ``data`` is any audio ffmpeg can read. It is decoded to 48 kHz mono wav in a temp dir, so
    the analyser sees one format. Raises `UnreadableAudio` when the bytes are not audio (reject
    the candidate) and `VerifyUnavailable` when the extra or ffmpeg is missing (stop the build).
    """
    with tempfile.TemporaryDirectory(prefix="avianki-verify-") as tmp:
        src, wav_path = Path(tmp, "clip.bin"), Path(tmp, "clip.wav")
        src.write_bytes(data)
        _to_wav(src, wav_path)
        duration = _wav_duration_s(wav_path)
        windows = list((analyzer or default_analyzer()).predict(wav_path, label))
    return ClipAnalysis(windows, min_confidence=min_confidence, duration_s=duration)
