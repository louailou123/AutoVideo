from pathlib import Path

import pytest

from autovideo.core import (
    NoMatchError,
    concat_listing,
    ffmpeg_command,
    list_images,
    norm,
    parse_progress,
    plan_timeline,
    read_texts,
    srt,
    timeline_text,
    word_times,
)


def test_norm_ignores_case_punctuation_and_arabic_variants():
    assert norm("Why?") == norm("why") == "why"
    assert norm("C'est") == "cest"
    assert norm("«l'eau»") == "leau"
    assert norm("أَحْمَد") == norm("احمد")  # diacritics and hamza forms
    assert norm("مدرسة") == norm("مدرسه")
    assert norm("—") == ""


def test_read_texts_one_line_per_image():
    assert read_texts("You yawn.\n\n  Your friend yawns too.  \nBut why?\n") == [
        "You yawn.", "Your friend yawns too.", "But why?"
    ]  # fmt: skip


def test_read_texts_takes_only_voiceover_lines_from_image_blocks():
    blocks = (
        "IMAGE 1\nVoiceover: You yawn.\nDuration: 2 seconds\nPrompt: A stick figure…\n\n"
        "IMAGE 2\nvoiceover:  Your friend yawns too.\nPrompt: Two stick figures…\n"
    )
    assert read_texts(blocks) == ["You yawn.", "Your friend yawns too."]


def test_list_images_natural_order_and_types(tmp_path):
    for name in ("10.png", "2.jpg", "1.PNG", "notes.txt", "3.webp"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in list_images(tmp_path)] == ["1.PNG", "2.jpg", "3.webp", "10.png"]


HEARD = [(" You", 0.0), (" yawn.", 0.3), (" Your", 1.2), (" friend", 1.45),
         (" yawns", 1.8), (" too.", 2.1), (" But", 3.4), (" why?", 3.7)]  # fmt: skip


def test_word_times_exact():
    words = ["You", "yawn.", "Your", "friend", "yawns", "too.", "But", "why?"]
    assert word_times(words, HEARD) == [0.0, 0.3, 1.2, 1.45, 1.8, 2.1, 3.4, 3.7]


def test_word_times_fills_words_the_voice_did_not_say():
    # "best" was never heard
    words = ["You", "yawn.", "Your", "best", "friend", "yawns", "too.", "But", "why?"]
    times = word_times(words, HEARD)
    assert times[2] == 1.2 and times[4] == 1.45
    assert 1.2 < times[3] < 1.45


def test_word_times_refuses_an_unrelated_voice():
    with pytest.raises(NoMatchError):
        word_times(["completely", "different", "words"], HEARD)


def test_plan_timeline_starts_at_first_spoken_word():
    texts = ["You yawn.", "Your friend yawns too.", "But why?"]
    plan = plan_timeline(texts, HEARD, duration=4.1, fps=30, tail=0.5)
    assert plan.starts == [0.0, 1.2, 3.4]
    assert plan.frames == [36, 66, 36]  # 1.2 s, 2.2 s, 1.2 s (voice ends 4.1 + 0.5 tail)
    assert sum(plan.frames) == round(4.6 * 30)
    assert plan.total_seconds == pytest.approx(4.6)


def test_plan_timeline_keeps_order_and_a_minimum_length():
    texts = ["You yawn.", "Your friend", "yawns too.", "But why?"]
    heard = HEARD[:3] + [(" friend", 1.2), (" yawns", 1.2)] + HEARD[5:]  # same instant
    plan = plan_timeline(texts, heard, duration=4.1, fps=30, tail=0.5, min_seconds=0.1)
    assert all(b > a for a, b in zip(plan.starts, plan.starts[1:], strict=False))
    assert all(n >= 3 for n in plan.frames)  # 0.1 s at 30 fps


def test_plan_timeline_rejects_an_empty_text():
    with pytest.raises(ValueError, match="image 2"):
        plan_timeline(["You yawn.", "   ", "But why?"], HEARD, duration=4.1)


def test_concat_listing_durations_and_last_image_twice(tmp_path):
    images = [tmp_path / "0001.png", tmp_path / "it's.png"]
    listing = concat_listing(images, [36, 66], fps=30).splitlines()
    assert listing[0] == f"file '{images[0].resolve().as_posix()}'"
    assert listing[1] == "duration 1.200000"
    assert listing[2].endswith("it'\\''s.png'")  # quotes escaped for FFmpeg
    assert listing[3] == "duration 2.200000"
    assert listing[4] == listing[2]  # FFmpeg ignores the last duration without this


def test_srt_and_timeline():
    texts = ["You yawn.", "But why?"]
    assert srt(texts, [36, 81], fps=30) == (
        "1\n00:00:00,000 --> 00:00:01,200\nYou yawn.\n\n"
        "2\n00:00:01,200 --> 00:00:03,900\nBut why?\n"
    )
    lines = timeline_text(texts, [36, 81], fps=30).splitlines()
    assert lines[1].startswith("Image    2:     1.20s -     3.90s") and "But why?" in lines[1]


def test_ffmpeg_command_shape(tmp_path):
    cmd = ffmpeg_command("ffmpeg", tmp_path / "list.txt", tmp_path / "v.mp3", tmp_path / "o.mp4")
    assert cmd[:6] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0"]
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in vf and "fps=30" in vf
    assert cmd[cmd.index("-af") + 1] == "apad" and "-shortest" in cmd
    assert cmd[cmd.index("-preset") + 1] == "medium"
    assert cmd[-1] == str(tmp_path / "o.mp4")
    fast = ffmpeg_command("ffmpeg", Path("l"), Path("v"), Path("o"), preset="veryfast")
    assert fast[fast.index("-preset") + 1] == "veryfast"
    # Exactly the planned frames: FFmpeg 8 shows the repeated last list entry again.
    capped = ffmpeg_command("ffmpeg", Path("l"), Path("v"), Path("o"), total_frames=138)
    assert capped[capped.index("-frames:v") + 1] == "138"


@pytest.mark.parametrize(("line", "seconds"), [
    ("out_time_us=1500000", 1.5), ("out_time_ms=2500000", 2.5),
    ("out_time=00:01:02.500000", 62.5), ("frame=10", None), ("out_time_us=N/A", None),
])  # fmt: skip
def test_parse_progress(line, seconds):
    assert parse_progress(line) == seconds
