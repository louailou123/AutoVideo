"""The timing core: which image is on screen when, from the words heard in the voice.

Each image comes with the words spoken over it. The voice is listened to (hearing.py) and
every heard word gets a time. Script words and heard words are lined up like a "compare
documents" tool; an image starts when its first word is spoken and ends when the next image
starts. Durations become frame counts on a running total, so the picture never drifts from
the voice, however long the video.
"""

import bisect
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
HeardWord = tuple[str, float]  # (word as heard, start time in seconds)

_ARABIC_MARKS = re.compile(r"[ً-ْـ]")  # diacritics and tatweel
_ARABIC_FORMS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
_VOICEOVER = re.compile(r"(?im)^\s*voiceover\s*:\s*(.+?)\s*$")


class Cancelled(Exception):
    """The user pressed Cancel."""


class NoMatchError(ValueError):
    """The heard words do not match the texts (wrong voice file, texts or language)."""


def norm(word: str) -> str:
    """A word reduced for comparison: lower case, no punctuation, no Arabic diacritics."""
    w = unicodedata.normalize("NFKC", word).lower()
    w = _ARABIC_MARKS.sub("", w).translate(_ARABIC_FORMS)
    return re.sub(r"[^\w]", "", w)


def read_texts(content: str) -> list[str]:
    """The words of each image: the 'Voiceover:' lines of IMAGE blocks if there are any,
    otherwise one non-empty line per image."""
    voiceovers = _VOICEOVER.findall(content)
    return voiceovers or [line.strip() for line in content.splitlines() if line.strip()]


def _natural_key(path: Path) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def list_images(folder: Path) -> list[Path]:
    """Images of a folder in natural order (1, 2, 10 — not 1, 10, 2)."""
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT]
    return sorted(files, key=_natural_key)


def word_times(script_words: Sequence[str], heard: Sequence[HeardWord]) -> list[float]:
    """A time for every script word. Words matched to a heard word get its time; the others
    (skipped, added or misheard) get a time between their matched neighbours."""
    a, b = [norm(w) for w in script_words], [norm(w) for w, _ in heard]
    times: list[float | None] = [None] * len(a)
    for i, j, size in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(size):
            if a[i + k]:  # punctuation-only tokens carry no timing
                times[i + k] = heard[j + k][1]
    known = [i for i, t in enumerate(times) if t is not None]
    if len(known) < 2:
        raise NoMatchError(
            "The voice does not match the texts. Check the voice file, the texts file and the "
            "language."
        )
    filled: list[float] = []
    for i, t in enumerate(times):
        if t is not None:
            filled.append(t)
            continue
        k = bisect.bisect(known, i)
        if k == 0:
            filled.append(times[known[0]])  # type: ignore[arg-type]
        elif k == len(known):
            filled.append(times[known[-1]])  # type: ignore[arg-type]
        else:
            lo, hi = known[k - 1], known[k]
            t_lo, t_hi = times[lo], times[hi]
            filled.append(t_lo + (t_hi - t_lo) * (i - lo) / (hi - lo))  # type: ignore[operator]
    return filled


@dataclass
class Plan:
    starts: list[float]  # when each image appears (seconds)
    frames: list[int]  # how many frames each image stays
    fps: int

    @property
    def total_seconds(self) -> float:
        return sum(self.frames) / self.fps


def plan_timeline(
    texts: Sequence[str],
    heard: Sequence[HeardWord],
    duration: float,
    fps: int = 30,
    tail: float = 0.5,
    min_seconds: float = 0.1,
) -> Plan:
    """Image n starts when its first word is spoken (image 1 at 0) and stays until the next
    one; the last stays `tail` seconds after the voice ends."""
    words: list[str] = []
    first: list[int] = []
    for n, text in enumerate(texts, start=1):
        if not text.split():
            raise ValueError(f"The text for image {n} is empty.")
        first.append(len(words))
        words += text.split()
    times = word_times(words, heard)

    starts = [0.0] + [times[i] for i in first[1:]]
    for j in range(1, len(starts)):  # keep the order; every image shows at least min_seconds
        starts[j] = max(starts[j], starts[j - 1] + min_seconds)
    end = max(duration, starts[-1] + min_seconds) + tail

    min_frames = max(1, round(min_seconds * fps))
    cuts = [round(t * fps) for t in starts[1:]] + [round(end * fps)]
    frames, done = [], 0
    for cut in cuts:
        frames.append(max(min_frames, cut - done))
        done += frames[-1]
    return Plan(starts=starts, frames=frames, fps=fps)


def _seconds_range(frames: Sequence[int], fps: int) -> list[tuple[float, float]]:
    out, done = [], 0
    for n in frames:
        out.append((done / fps, (done + n) / fps))
        done += n
    return out


def concat_listing(images: Sequence[Path], frames: Sequence[int], fps: int) -> str:
    """FFmpeg concat-demuxer list: each image with its duration."""

    def entry(path: Path) -> str:
        return "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'"

    lines = []
    for image, n in zip(images, frames, strict=True):
        lines += [entry(image), f"duration {n / fps:.6f}"]
    lines.append(entry(images[-1]))  # FFmpeg ignores the last duration without this
    return "\n".join(lines) + "\n"


def _stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def srt(texts: Sequence[str], frames: Sequence[int], fps: int) -> str:
    """Subtitles: one cue per image, with its text."""
    cues = [
        f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{text}\n"
        for n, (text, (a, b)) in enumerate(
            zip(texts, _seconds_range(frames, fps), strict=True), start=1
        )
    ]
    return "\n".join(cues)


def timeline_text(texts: Sequence[str], frames: Sequence[int], fps: int) -> str:
    """One line per image: when it is on screen, and its words."""
    rows = [
        f"Image {n:4d}: {a:8.2f}s - {b:8.2f}s  {text}"
        for n, (text, (a, b)) in enumerate(
            zip(texts, _seconds_range(frames, fps), strict=True), start=1
        )
    ]
    return "\n".join(rows) + "\n"


def ffmpeg_command(
    ffmpeg: str,
    list_file: Path,
    voice: Path,
    out: Path,
    size: tuple[int, int] = (1920, 1080),
    fps: int = 30,
    preset: str = "medium",
    total_frames: int | None = None,
) -> list[str]:
    """Images (letterboxed to `size`, never stretched) + the voice, padded with silence to the
    end of the last image. Progress is written to stdout (parse_progress). `total_frames` caps
    the video at exactly the planned length (FFmpeg 8 shows the repeated last entry again)."""
    w, h = size
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p"
    )
    return [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-i", str(voice),
        "-vf", vf, "-af", "apad", "-shortest",
        "-c:v", "libx264", "-preset", preset, "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        *(["-frames:v", str(total_frames)] if total_frames else []),
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        str(out),
    ]  # fmt: skip


def parse_progress(line: str) -> float | None:
    """Seconds of video written so far, from one line of FFmpeg's `-progress` output."""
    key, _, value = line.strip().partition("=")
    try:
        if key in ("out_time_us", "out_time_ms"):  # both are microseconds
            return int(value) / 1_000_000
        if key == "out_time":
            h, m, s = value.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return None
    return None
