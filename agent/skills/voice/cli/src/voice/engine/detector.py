"""The wake word detector: a livekit-wakeword ONNX classifier, on the CPU.

A loaded model keeps no audio state, so the sessions share one model for each file. Each call
scores one window, in one thread: the default thread pool of ONNX Runtime uses every core and
costs about fifty times the CPU for the same score.
"""

import dataclasses as dc
import pathlib as pl
import typing as tp

if tp.TYPE_CHECKING:
    import numpy as np

INSTALL = "uv tool install --editable ~/agent/skills/voice/cli && voice daemon restart"

# A model file and its mtime (0 when there is no file), so a new file at the same path is a new key.
ModelKey = tuple[str, int]


class DetectorError(Exception):
    """The model cannot load: the file is missing or bad, or the package is not installed."""


def model_key(path: pl.Path) -> ModelKey:
    try:
        return str(path), path.stat().st_mtime_ns
    except OSError:
        return str(path), 0


class Detector(tp.Protocol):
    def score(self, window: bytes) -> float:
        """The score, 0 to 1, that the window (pcm_s16le, 16 kHz, mono) ends with the phrase.
        It blocks for about 20 ms, so the session calls it in a thread."""
        ...


class _Model(tp.Protocol):
    def predict(self, audio_chunk: "np.ndarray") -> dict[str, float]: ...


@dc.dataclass(frozen=True)
class OnnxDetector:
    model: _Model
    name: str

    def score(self, window: bytes) -> float:
        import numpy as np

        scores = self.model.predict(np.frombuffer(window, dtype=np.int16))
        return scores[self.name] if self.name in scores else 0.0


def load(path: pl.Path) -> Detector:
    """Load the classifier at `path`. Raises DetectorError."""
    if not path.is_file():
        raise DetectorError(f"no wake word model at {path}; ~/agent/skills/voice/SETUP.md says how to train one")
    try:
        import onnxruntime
        from livekit.wakeword import WakeWordModel
    except ImportError as e:
        raise DetectorError(f"the wake word needs the livekit-wakeword package ({e}); run `{INSTALL}`") from None
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    try:
        model = WakeWordModel(models=[path], sess_options=options)
    except Exception as e:
        raise DetectorError(f"the wake word model at {path} did not load: {e}") from e
    return OnnxDetector(model=model, name=path.stem)
