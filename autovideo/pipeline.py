"""One video: check the inputs, listen to the voice, plan the timeline, render with FFmpeg.

Runs on a worker thread. It talks to the window only through `report(kind, value)`:
"log" (a line of text), "progress" ((stage, fraction 0..1)), "timeline" (the timeline text).
"""

import shutil
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autovideo.core import (
    Cancelled,
    concat_listing,
    ffmpeg_command,
    list_images,
    parse_progress,
    plan_timeline,
    read_texts,
    srt,
    timeline_text,
)
from autovideo.hearing import hear as whisper_hear

Report = Callable[[str, Any], None]
ShouldStop = Callable[[], bool]
INSTALL_FFMPEG = "FFmpeg is not installed. Install it with:  winget install --id Gyan.FFmpeg -e"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class Job:
    images: Path  # folder
    voice: Path
    texts: Path
    out: Path
    language: str | None = None  # "en", "fr", "ar"; None = detect
    model: str = "small"
    preset: str = "medium"  # FFmpeg x264 preset: "veryfast" encodes faster, bigger file


@dataclass
class Checked:
    images: list[Path]
    texts: list[str]
    problems: list[str]


def check(job: Job) -> Checked:
    """What is wrong with the inputs, in plain words (empty list = ready)."""
    problems: list[str] = []
    images: list[Path] = []
    texts: list[str] = []
    if job.images.is_dir():
        images = list_images(job.images)
        if not images:
            problems.append("The images folder has no images (png, jpg, webp).")
    else:
        problems.append("Choose the images folder.")
    if not job.voice.is_file():
        problems.append("Choose the voice file.")
    if job.texts.is_file():
        texts = read_texts(job.texts.read_text("utf-8-sig"))
        if not texts:
            problems.append("The texts file is empty.")
    else:
        problems.append("Choose the texts file.")
    if images and texts and len(images) != len(texts):
        problems.append(f"{len(images)} images but {len(texts)} texts: they must match one to one.")
    return Checked(images=images, texts=texts, problems=problems)


def run_ffmpeg(
    cmd: list[str],
    total_seconds: float,
    on_progress: Callable[[float], None],
    should_stop: ShouldStop,
) -> None:
    """Run FFmpeg, reporting progress from its `-progress pipe:1` output."""
    tail: deque[str] = deque(maxlen=12)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", creationflags=_NO_WINDOW,
    )  # fmt: skip
    assert proc.stdout is not None
    for line in proc.stdout:
        if should_stop():
            proc.kill()
            proc.wait()
            raise Cancelled
        seconds = parse_progress(line)
        if seconds is not None:
            on_progress(min(1.0, seconds / max(total_seconds, 0.001)))
        elif "=" not in line and line.strip():
            tail.append(line.strip())  # error text (-loglevel error)
    if proc.wait() != 0:
        raise RuntimeError("FFmpeg failed: " + (" | ".join(tail) or f"exit {proc.returncode}"))
    on_progress(1.0)


def make_video(
    job: Job,
    report: Report,
    should_stop: ShouldStop,
    hear: Callable[..., tuple[list, float]] = whisper_hear,
    run: Callable[..., None] = run_ffmpeg,
    ffmpeg: str | None = None,
) -> Path:
    checked = check(job)
    if checked.problems:
        raise ValueError("\n".join(checked.problems))
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError(INSTALL_FFMPEG)

    report("log", f"Listening to the voice ({job.model} model; the first use downloads it)…")
    heard, duration = hear(job.voice, job.language, job.model,
                           lambda f: report("progress", ("Listening", f)), should_stop)  # fmt: skip
    if should_stop():
        raise Cancelled
    report("log", f"Heard {len(heard)} words in {duration:.1f} s of voice.")

    plan = plan_timeline(checked.texts, heard, duration)
    job.out.parent.mkdir(parents=True, exist_ok=True)
    list_file = job.out.with_suffix(".images.txt")
    list_file.write_text(concat_listing(checked.images, plan.frames, plan.fps), "utf-8")
    job.out.with_suffix(".srt").write_text(srt(checked.texts, plan.frames, plan.fps), "utf-8")
    timeline = timeline_text(checked.texts, plan.frames, plan.fps)
    job.out.with_suffix(".timeline.txt").write_text(timeline, "utf-8")
    report("timeline", timeline)

    report("log", f"Making the video ({plan.total_seconds:.1f} s, {len(checked.images)} images)…")
    cmd = ffmpeg_command(
        ffmpeg,
        list_file,
        job.voice,
        job.out,
        fps=plan.fps,
        preset=job.preset,
        total_frames=sum(plan.frames),
    )
    run(cmd, plan.total_seconds, lambda f: report("progress", ("Making the video", f)),
        should_stop)  # fmt: skip
    report("log", f"Done: {job.out}")
    return job.out
