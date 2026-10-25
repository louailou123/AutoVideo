import time
import tkinter as tk

import pytest

from autovideo.app import App
from autovideo.core import Cancelled

TEXTS = "You yawn.\nYour friend yawns too.\nBut why?\n"


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def files(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for n in (1, 2, 3):
        (images / f"{n:04d}.png").write_bytes(b"png")
    (tmp_path / "voice.mp3").write_bytes(b"mp3")
    (tmp_path / "texts.txt").write_text(TEXTS, "utf-8")
    return tmp_path


def make_app(root, tmp_path, make=None):
    return App(root, make=make or (lambda *a, **k: None), settings_path=tmp_path / "s.json")


def fill(app, files):
    app.set_images(files / "images")
    app.voice_var.set(str(files / "voice.mp3"))
    app.texts_var.set(str(files / "texts.txt"))


def wait(root, app, timeout=5.0):
    end = time.monotonic() + timeout
    while app.is_running() and time.monotonic() < end:
        root.update()
        time.sleep(0.02)
    root.update()
    assert not app.is_running()


def test_choosing_images_suggests_an_output_file(root, files):
    app = make_app(root, files)
    app.set_images(files / "images")
    assert app.out_var.get() == str(files / "final_video.mp4")


def test_check_shows_counts_or_problems(root, files):
    app = make_app(root, files)
    fill(app, files)
    app.check()
    assert app.status_text() == "3 images · 3 texts — ready"
    (files / "images" / "0004.png").write_bytes(b"png")
    app.check()
    assert "4 images but 3 texts" in app.status_text()


def test_make_runs_in_the_background_and_shows_progress(root, files):
    seen = {}

    def fake_make(job, report, should_stop):
        seen["job"] = job
        report("log", "Listening…")
        report("progress", ("Listening", 0.5))
        report("timeline", "Image    1:     0.00s -     1.20s  You yawn.\n")
        report("progress", ("Making the video", 1.0))
        time.sleep(0.1)  # the window keeps responding meanwhile
        return job.out

    app = make_app(root, files, fake_make)
    fill(app, files)
    app.language_var.set("French")
    app.fast_var.set(True)
    app.make()
    assert app.is_running()
    wait(root, app)
    job = seen["job"]
    assert (job.language, job.model, job.preset) == ("fr", "small", "veryfast")
    log = app.log_text()
    assert "Listening…" in log and "You yawn." in log and "Video ready" in log
    assert app.progress_value() == 100
    assert app.can_open_folder()


def test_cancel_stops_the_run(root, files):
    def slow_make(job, report, should_stop):
        while not should_stop():
            time.sleep(0.01)
        raise Cancelled

    app = make_app(root, files, slow_make)
    fill(app, files)
    app.make()
    app.cancel()
    wait(root, app)
    assert "Cancelled." in app.log_text()


def test_errors_are_shown_in_the_window(root, files):
    def failing(job, report, should_stop):
        raise ValueError("4 images but 3 texts: they must match one to one.")

    app = make_app(root, files, failing)
    fill(app, files)
    app.make()
    wait(root, app)
    assert "4 images but 3 texts" in app.log_text()
    assert "4 images but 3 texts" in app.status_text()


def test_choices_are_remembered(root, files):
    app = make_app(root, files)
    fill(app, files)
    app.language_var.set("Arabic")
    app.save_settings()
    again = make_app(root, files)
    assert again.voice_var.get() == str(files / "voice.mp3")
    assert again.language_var.get() == "Arabic"
