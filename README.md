# AutoVideo

Turn a voice file and a folder of images into a video. Each image appears when its first words
are spoken: no manual editing in CapCut.

1. **Listens** to the voice with Whisper (runs on your PC, free, works offline after the first
   model download) and notes when every word is spoken.
2. **Matches** those words to the text of each image (skipped or misheard words are fine).
3. **Renders** `final_video.mp4` with FFmpeg: 1920×1080, 30 fps, your voice as the sound, the
   last image held 0.5 s after the voice ends. Images that are not 16:9 get black bars.

It also writes, next to the video:

- `final_video.timeline.txt` — when each image appears, to check the timing;
- `final_video.srt` — subtitles (one per image), for YouTube or CapCut.

## Setup (once)

```bash
winget install --id Gyan.FFmpeg -e
```

Then, in this folder:

```bash
uv sync
```

## Run

```bash
uv run autovideo
```

1. **Images folder**: the images in order. Names like `0001.png, 0002.png` or `1.png, 2.png,
   10.png` both work (natural order).
2. **Voice file**: mp3, wav, m4a… — voice only works best (no music mixed in).
3. **Texts file**: the words of each image, in the same order — one line per image:

   ```
   You yawn.
   Your friend yawns too.
   But why?
   ```

   or paste "IMAGE 1 / Voiceover: … / Prompt: …" blocks as they are (only the `Voiceover:`
   lines are used). The number of texts must equal the number of images.
4. **Check**, then **Make video**. **Cancel** stops at any time; **Open folder** shows the result.

The fields are remembered between runs.

## Choosing the listening model

The first run of a model downloads it (once). On a laptop with 8 GB of memory:

| Model | Download | Time for a 10-min voice (approx.) |
|---|---|---|
| base | ~150 MB | 2–4 min |
| **small (default)** | ~500 MB | 5–10 min |
| medium | ~1.5 GB | 15–30 min — close other apps first |

Close Chrome and other heavy apps before a long video. "Faster encoding" makes the video step
quicker (the file is bigger, the quality nearly the same).

## Development

```bash
uv run pytest
uv run ruff check
```

`autovideo/core.py` holds the timing logic (pure functions, fully tested), `hearing.py` the
Whisper step, `pipeline.py` one video from start to end, `app.py` the window (presentation only:
the work runs on a background thread, so the window never freezes).
