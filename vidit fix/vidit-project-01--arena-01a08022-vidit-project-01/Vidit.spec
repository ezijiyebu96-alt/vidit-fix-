# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Vidit — Windows 11 x64 (also verifiable on Linux).

Build:  pyinstaller --noconfirm --clean Vidit.spec
Output: dist/Vidit/Vidit.exe  (onedir — fast start, clean upgrades)

The spec is platform-aware so the same file can be smoke-built on Linux to
validate hidden imports and data files; the Windows build is the target.
"""
from __future__ import annotations

import importlib.util
import platform
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
ROOT = Path(SPECPATH).resolve()  # project root (folder that holds Vidit.spec)


def have(module: str) -> bool:
    """Hidden-import only what is actually installed (optional senses deps)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


hidden = ["vidit.autonomy"]  # dynamic import chain is static enough, but be explicit
for mod in (
    # senses (all optional at runtime, bundled when present)
    "faster_whisper", "faster_whisper.utils", "huggingface_hub", "tokenizers", "ctranslate2", "av", "sounddevice",
    "piper", "pyttsx3.drivers", "cv2", "mss", "pyautogui", "pyscreeze",
    "pygetwindow", "mouseinfo",
    # files / docs stack
    "pypdf", "docx", "openpyxl", "PIL",
    # core
    "psutil", "markdown",
):
    if have(mod):
        hidden.append(mod)

if IS_WINDOWS:
    hidden += ["pyttsx3.drivers.sapi5", "pyttsx3.drivers", "winreg", "winsound"]
    if have("piper"):
        hidden += ["piper"]

datas = [
    (str(ROOT / "vidit" / "ui" / "assets"), "vidit/ui/assets"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "CONSTITUTION.md"), "."),
    (str(ROOT / "AUTONOMY.md"), "."),
    (str(ROOT / "WINDOWS11_BUILD.md"), "."),
]
# Data files that ship inside optional wheels (e.g. sounddevice's portaudio DLL metadata).
for mod, pkg in (("sounddevice", "_sounddevice_data"), ("cv2", None)):
    if have(mod):
        try:
            top = __import__(mod)
            base = Path(top.__file__).parent
            if pkg:
                # the sounddevice wheel may put _sounddevice_data inside the
                # package or at site-packages root - collect whichever exists
                for cand in (base / pkg, base.parent / pkg):
                    if cand.exists():
                        datas.append((str(cand), f"{mod}/{pkg}"))
                        break
        except Exception:  # noqa: BLE001
            pass

a = Analysis(
    [str(ROOT / "launch_vidit.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "runtime_hook_vidit.py")],
    excludes=[
        "face_recognition", "dlib",           # optional, needs CMake/dlib — documented
        "torch", "tensorflow",                # never used by Vidit (faster-whisper is ONNX/ctranslate2)
        "tkinter",
        "matplotlib",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Vidit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX triggers false-positive AV on Windows; keep off
    console=False,  # windowed app; --doctor/--cli still work via CLI piping
    icon=str(ROOT / "packaging" / "vidit.ico"),
    version=str(ROOT / "packaging" / "version_info.txt") if IS_WINDOWS else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Vidit",
)
