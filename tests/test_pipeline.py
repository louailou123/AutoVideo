import json
import shutil
import subprocess
from dataclasses import dataclass, field

import pytest

from autovideo.core import Cancelled
from autovideo.hearing import hear
from autovideo.pipeline import Job, check, make_video, run_ffmpeg

TEXTS = "You yawn.\nYour friend yawns too.\nBut why?\n"
HEARD = [(" You", 0.0), (" yawn.", 0.3), (" Your", 1.2), (" friend", 1.45),
         (" yawns", 1.8), (" too.", 2.1), (" But", 3.4), (" why?", 3.7)]  # fmt: skip


@pytest.fixture
def job(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for n in (1, 2, 3):
        (images / f"{n:04d}.png").write_bytes(b"png")
    (tmp_path / "voice.wav").write_bytes(b"wav")
    (tmp_path / "texts.txt").write_text(TEXTS, "utf-8")
    return Job(images=images, voice=tmp_path / "voice.wav", texts=tmp_path / "texts.txt",
               out=tmp_path / "out" / "final_video.mp4", language="en")  # fmt: skip


@dataclass
class Recorder:
    events: list[tuple[str, object]] = field(default_factory=list)

    def __call__(self, kind, value):
        self.events.append((kind, value))

    def of(self, kind):
        return [v for k, v in self.events if k == kind]


def fake_hear(voice, language, model, on_progress, should_stop):
    on_progress(0.5)
    on_progress(1.0)
    return HEARD, 4.1


def test_check_counts_and_problems(job):
    ok = check(job)
    assert (len(ok.images), len(ok.texts), ok.problems) == (3, 3, [])
    (job.images / "0004.png").write_bytes(b"png")
    assert check(job).problems == ["4 images but 3 texts: they must match one to one."]
    job.voice.unlink()
    assert any("voice file" in p for p in check(job).problems)


def test_make_video_writes_timeline_subtitles_and_renders(job):
    report, commands = Recorder(), []

    def fake_run(cmd, total, on_progress, should_stop):
        commands.append((cmd, total))
        on_progress(1.0)
        job.out.write_bytes(b"mp4")

    out = make_video(job, report, lambda: False, hear=fake_hear, run=fake_run, ffmpeg="ffmpeg")
    assert out == job.out and out.is_file()
    timeline = job.out.with_suffix(".timeline.txt").read_text("utf-8")
    assert "Image    3:     3.40s -     4.60s  But why?" in timeline
    assert job.out.with_suffix(".srt").read_text("utf-8").startswith("1\n00:00:00,000 -->")
    ((cmd, total),) = commands
    assert total == pytest.approx(4.6) and cmd[-1] == str(job.out)
    assert ("Listening", 1.0) in report.of("progress")
    assert ("Making the video", 1.0) in report.of("progress")
    assert report.of("timeline") == [timeline]


def test_make_video_refuses_bad_inputs_before_listening(job):
    (job.images / "0004.png").write_bytes(b"png")
    with pytest.raises(ValueError, match="4 images but 3 texts"):
        make_video(job, Recorder(), lambda: False, hear=pytest.fail, run=pytest.fail,
                   ffmpeg="ffmpeg")  # fmt: skip


def test_make_video_stops_when_asked(job):
    with pytest.raises(Cancelled):
        make_video(job, Recorder(), lambda: True, hear=fake_hear, run=pytest.fail,
                   ffmpeg="ffmpeg")  # fmt: skip


def test_make_video_without_ffmpeg_says_how_to_install(job, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="winget install"):
        make_video(job, Recorder(), lambda: False, hear=fake_hear, run=pytest.fail)


# ------------------------------------------------------------------ hearing (fake model)


@dataclass
class W:
    word: str
    start: float


@dataclass
class Seg:
    end: float
    words: list


class FakeModel:
    def __init__(self, *args, **kwargs):
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        FakeModel.seen = kwargs
        segments = iter([Seg(2.0, [W(" You", 0.0), W(" yawn.", 0.3)]),
                         Seg(4.0, [W(" But", 3.4), W(" why?", 3.7)])])  # fmt: skip
        return segments, type("Info", (), {"duration": 4.1})()


def test_hear_returns_words_duration_and_progress(tmp_path):
    progress = []
    words, duration = hear(tmp_path / "v.wav", "fr", "small", progress.append, lambda: False,
                           model_factory=FakeModel)  # fmt: skip
    assert words == [(" You", 0.0), (" yawn.", 0.3), (" But", 3.4), (" why?", 3.7)]
    assert duration == 4.1
    assert progress == [pytest.approx(2.0 / 4.1), pytest.approx(4.0 / 4.1), 1.0]
    assert FakeModel.seen["word_timestamps"] is True and FakeModel.seen["language"] == "fr"


def test_hear_can_be_cancelled(tmp_path):
    with pytest.raises(Cancelled):
        hear(tmp_path / "v.wav", None, "small", lambda f: None, lambda: True,
             model_factory=FakeModel)  # fmt: skip


# ------------------------------------------------------------------ real FFmpeg


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.mark.ffmpeg
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_real_render_matches_the_plan(job):
    for n, color in ((1, "red"), (2, "green"), (3, "blue")):
        _ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=320x240", "-frames:v", "1",
                str(job.images / f"{n:04d}.png"))  # fmt: skip
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=4.1", str(job.voice))
    report = Recorder()
    out = make_video(job, report, lambda: False, hear=fake_hear, run=run_ffmpeg)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,nb_frames",
         "-show_entries", "format=duration", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    info = json.loads(probe.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)  # 4:3 image letterboxed
    assert abs(int(video["nb_frames"]) - 138) <= 1  # 4.6 s at 30 fps
    assert float(info["format"]["duration"]) == pytest.approx(4.6, abs=0.1)
    assert any(kind == "Making the video" for kind, _ in report.of("progress"))


@pytest.mark.ffmpeg
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_run_ffmpeg_reports_failure(tmp_path):
    with pytest.raises(RuntimeError, match="FFmpeg"):
        run_ffmpeg(["ffmpeg", "-loglevel", "error", "-i", str(tmp_path / "missing.wav"),
                    str(tmp_path / "x.mp4")], 1.0, lambda f: None, lambda: False)  # fmt: skip
