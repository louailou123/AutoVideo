"""The AutoVideo window. Presentation only: the work runs on a worker thread
(pipeline.make_video), which sends events through a queue that the window polls, so the
window never freezes."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from autovideo.core import Cancelled
from autovideo.hearing import MODELS
from autovideo.pipeline import Job, check, make_video

LANGUAGES = {"Detect automatically": None, "English": "en", "French": "fr", "Arabic": "ar"}
MODEL_NAMES = {label: name for name, label in MODELS.items()}
POLL_MS = 100


def create_root(attempts: int = 3, factory: Callable[[], Any] = tk.Tk) -> Any:
    """Start Tk, retrying briefly: on Windows, antivirus can lock Tk's own files for a moment
    ("couldn't read file .../tk8.6/ttk/cursors.tcl")."""
    for attempt in range(attempts):
        try:
            return factory()
        except tk.TclError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


def default_settings_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "AutoVideo" / "settings.json"


class App:
    def __init__(
        self,
        root: tk.Tk,
        make: Callable[..., Path] = make_video,
        settings_path: Path | None = None,
    ) -> None:
        self.root = root
        self._make = make
        self._settings_path = settings_path or default_settings_path()
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_out: Path | None = None

        self.images_var = tk.StringVar()
        self.voice_var = tk.StringVar()
        self.texts_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.language_var = tk.StringVar(value="Detect automatically")
        self.model_var = tk.StringVar(value=MODELS["small"])
        self.fast_var = tk.BooleanVar(value=False)
        self._build()
        self._load_settings()
        self.root.after(POLL_MS, self._poll)

    # ------------------------------------------------------------ layout

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        rows = [
            ("Images folder", self.images_var, self._browse_images),
            ("Voice file", self.voice_var, self._browse_voice),
            ("Texts file", self.texts_var, self._browse_texts),
            ("Save video as", self.out_var, self._browse_out),
        ]
        for row, (label, var, browse) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6)
            ttk.Button(frame, text="Browse…", command=browse).grid(row=row, column=2)

        options = ttk.Frame(frame)
        options.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 4))
        ttk.Label(options, text="Language").pack(side="left")
        ttk.Combobox(options, textvariable=self.language_var, values=list(LANGUAGES),
                     state="readonly", width=20).pack(side="left", padx=(6, 16))  # fmt: skip
        ttk.Label(options, text="Listening model").pack(side="left")
        ttk.Combobox(options, textvariable=self.model_var, values=list(MODEL_NAMES),
                     state="readonly", width=40).pack(side="left", padx=(6, 16))  # fmt: skip
        ttk.Checkbutton(frame, text="Faster encoding (bigger file, nearly the same quality)",
                        variable=self.fast_var).grid(row=5, column=0, columnspan=3,
                                                     sticky="w")  # fmt: skip

        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Button(actions, text="Check", command=self.check).pack(side="left")
        self._make_btn = ttk.Button(actions, text="Make video", command=self.make)
        self._make_btn.pack(side="left", padx=6)
        self._cancel_btn = ttk.Button(actions, text="Cancel", command=self.cancel,
                                      state="disabled")  # fmt: skip
        self._cancel_btn.pack(side="left")
        self._open_btn = ttk.Button(actions, text="Open folder", command=self.open_folder,
                                    state="disabled")  # fmt: skip
        self._open_btn.pack(side="left", padx=6)
        self._status = ttk.Label(actions, text="Choose the images, the voice and the texts.")
        self._status.pack(side="left", padx=12)

        progress_row = ttk.Frame(frame)
        progress_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=4)
        self._stage = ttk.Label(progress_row, text="", width=24)
        self._stage.pack(side="left")
        self._progress = ttk.Progressbar(progress_row, maximum=100)
        self._progress.pack(side="left", fill="x", expand=True)

        frame.rowconfigure(8, weight=1)
        log_frame = ttk.Frame(frame)
        log_frame.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        self._log = tk.Text(log_frame, height=16, wrap="word", state="disabled",
                            font=("Consolas", 10))  # fmt: skip
        scroll = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------ inputs

    def set_images(self, folder: Path) -> None:
        self.images_var.set(str(folder))
        if not self.out_var.get():
            self.out_var.set(str(folder.parent / "final_video.mp4"))

    def _browse_images(self) -> None:
        if folder := filedialog.askdirectory(parent=self.root, title="Images folder"):
            self.set_images(Path(folder))

    def _browse_voice(self) -> None:
        kinds = [("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")]
        if path := filedialog.askopenfilename(parent=self.root, filetypes=kinds):
            self.voice_var.set(path)

    def _browse_texts(self) -> None:
        kinds = [("Text", "*.txt"), ("All files", "*.*")]
        if path := filedialog.askopenfilename(parent=self.root, filetypes=kinds):
            self.texts_var.set(path)

    def _browse_out(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".mp4",
                                            filetypes=[("MP4 video", "*.mp4")])  # fmt: skip
        if path:
            self.out_var.set(path)

    def job(self) -> Job:
        return Job(
            images=Path(self.images_var.get().strip()),
            voice=Path(self.voice_var.get().strip()),
            texts=Path(self.texts_var.get().strip()),
            out=Path(self.out_var.get().strip() or "final_video.mp4"),
            language=LANGUAGES.get(self.language_var.get()),
            model=MODEL_NAMES.get(self.model_var.get(), "small"),
            preset="veryfast" if self.fast_var.get() else "medium",
        )

    # ------------------------------------------------------------ actions

    def check(self) -> bool:
        checked = check(self.job())
        if checked.problems:
            self._set_status(" ".join(checked.problems), error=True)
            return False
        self._set_status(f"{len(checked.images)} images · {len(checked.texts)} texts — ready")
        return True

    def make(self) -> None:
        if self._running or not self.check():
            return
        self.save_settings()
        job = self.job()
        self._stop.clear()
        self._running = True
        self._last_out = None
        self._progress["value"] = 0
        self._stage.configure(text="")
        self._make_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._open_btn.configure(state="disabled")
        self._append(f"--- {job.out.name} ---")
        self._thread = threading.Thread(target=self._work, args=(job,), daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        if self._running:
            self._stop.set()
            self._set_status("Stopping…")

    def open_folder(self) -> None:
        if self._last_out is None:
            return
        folder = str(self._last_out.parent)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 - the user's own output folder
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])

    def close(self) -> None:
        if self._running:
            if not messagebox.askyesno("AutoVideo", "A video is being made. Stop it and close?"):
                return
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=5)
        self.save_settings()
        self.root.destroy()

    # ------------------------------------------------------------ worker thread

    def _work(self, job: Job) -> None:
        def report(kind: str, value: Any) -> None:
            self._events.put((kind, value))

        try:
            out = self._make(job, report, self._stop.is_set)
            self._events.put(("finished", ("ok", out)))
        except Cancelled:
            self._events.put(("finished", ("cancelled", None)))
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            self._events.put(("finished", ("error", str(exc))))
        except Exception as exc:  # anything unexpected: show it, keep the window alive
            self._events.put(("log", traceback.format_exc()))
            self._events.put(("finished", ("error", f"{type(exc).__name__}: {exc}")))

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self._events.get_nowait()
                self._handle(kind, value)
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll)

    def _handle(self, kind: str, value: Any) -> None:
        if kind == "log":
            self._append(str(value))
        elif kind == "progress":
            stage, fraction = value
            percent = round(fraction * 100)
            self._stage.configure(text=f"{stage} {percent}%")
            self._progress["value"] = percent
        elif kind == "timeline":
            self._append("Timeline (also saved next to the video):\n" + str(value).rstrip())
        elif kind == "finished":
            self._finish(*value)

    def _finish(self, outcome: str, value: Any) -> None:
        self._running = False
        self._make_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        if outcome == "ok":
            self._last_out = Path(value)
            self._progress["value"] = 100
            self._open_btn.configure(state="normal")
            self._append(f"Video ready: {value}")
            self._set_status("Video ready.")
        elif outcome == "cancelled":
            self._append("Cancelled.")
            self._set_status("Cancelled.")
        else:
            self._append(f"Error: {value}")
            self._set_status(str(value), error=True)

    # ------------------------------------------------------------ helpers

    def _append(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status.configure(text=text, foreground="#b42318" if error else "")

    def save_settings(self) -> None:
        data = {
            "images": self.images_var.get(), "voice": self.voice_var.get(),
            "texts": self.texts_var.get(), "out": self.out_var.get(),
            "language": self.language_var.get(), "model": self.model_var.get(),
            "fast": self.fast_var.get(),
        }  # fmt: skip
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            self._settings_path.write_text(json.dumps(data, indent=2), "utf-8")
        except OSError:
            pass  # remembering the fields is a convenience, never a reason to fail

    def _load_settings(self) -> None:
        try:
            data = json.loads(self._settings_path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        for key, var in (("images", self.images_var), ("voice", self.voice_var),
                         ("texts", self.texts_var), ("out", self.out_var)):  # fmt: skip
            var.set(str(data.get(key, "")))
        if data.get("language") in LANGUAGES:
            self.language_var.set(data["language"])
        if data.get("model") in MODEL_NAMES:
            self.model_var.set(data["model"])
        self.fast_var.set(bool(data.get("fast", False)))

    # ------------------------------------------------------------ inspection (tests)

    def is_running(self) -> bool:
        return self._running

    def status_text(self) -> str:
        return str(self._status.cget("text"))

    def log_text(self) -> str:
        return self._log.get("1.0", "end-1c")

    def progress_value(self) -> int:
        return int(float(self._progress["value"]))

    def can_open_folder(self) -> bool:
        return str(self._open_btn.cget("state")) == "normal"


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = create_root()
    root.title("AutoVideo — images + voice → video")
    root.geometry("980x640")
    root.minsize(820, 520)
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
