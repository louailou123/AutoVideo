"""Listening to the voice: every spoken word with the time it starts (Whisper, on this PC).

faster-whisper runs on the CPU with 8-bit weights. The model is downloaded once, on first
use, into the Hugging Face cache (~/.cache/huggingface). It is imported only when needed:
it is slow to load, and the window must appear first.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from autovideo.core import Cancelled, HeardWord

MODELS = {  # name: what to tell the user
    "tiny": "tiny (~75 MB, least accurate)",
    "base": "base (~150 MB)",
    "small": "small (~500 MB, recommended)",
    "medium": "medium (~1.5 GB, slower; close other apps)",
    "large-v3": "large-v3 (~3 GB, too heavy for most laptops)",
}


def _whisper_model(name: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8")


def hear(
    voice: Path,
    language: str | None,
    model_name: str,
    on_progress: Callable[[float], None],
    should_stop: Callable[[], bool],
    model_factory: Callable[[str], Any] = _whisper_model,
) -> tuple[list[HeardWord], float]:
    """(word, start seconds) for every spoken word, and the length of the voice."""
    model = model_factory(model_name)
    segments, info = model.transcribe(str(voice), language=language, word_timestamps=True)
    duration = float(info.duration) or 1.0
    words: list[HeardWord] = []
    for segment in segments:  # transcribed lazily, segment by segment
        if should_stop():
            raise Cancelled
        words += [(w.word, float(w.start)) for w in segment.words or []]
        on_progress(min(1.0, float(segment.end) / duration))
    on_progress(1.0)
    return words, float(info.duration)
