# PyInstaller recipe: dist/AutoVideo/AutoVideo.exe, the window with everything it needs,
# FFmpeg included. Run through packaging/build.ps1, which finds FFmpeg (AUTOVIDEO_FFMPEG).
# SPECPATH, Analysis, PYZ, EXE and COLLECT are provided by PyInstaller.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.dirname(SPECPATH)
ICON = os.path.join(ROOT, "autovideo", "autovideo.ico")

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[ROOT],
    binaries=[
        (os.environ["AUTOVIDEO_FFMPEG"], "ffmpeg"),  # found by pipeline.find_ffmpeg
        *collect_dynamic_libs("ctranslate2"),  # Whisper's engine loads these from its folder
    ],
    datas=[(ICON, "autovideo"), *collect_data_files("faster_whisper")],
    excludes=["pytest", "_pytest", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoVideo",
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AutoVideo")
