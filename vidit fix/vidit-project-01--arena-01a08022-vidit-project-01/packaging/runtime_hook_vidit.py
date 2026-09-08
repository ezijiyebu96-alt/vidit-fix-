"""PyInstaller runtime hook — runs before vidit imports, inside Vidit.exe.

Keeps the packaged app honest and Windows-friendly:

* marks the frozen build (VIDIT_FROZEN=1) so Vidit can say so and pick
  frozen-safe code paths (code sandbox, piper, paths);
* makes sure user data NEVER lands in the (read-only) install folder —
  vidit.config.default_home() already uses %LOCALAPPDATA%\\Vidit on Windows,
  this hook only pins it explicitly so every subsystem agrees;
* leaves Python's stdout/stderr attached to whatever the bootloader provides
  (windowed build: no console) — logging always goes to <home>/logs/vidit.log.
"""
import os
import sys

os.environ.setdefault("VIDIT_FROZEN", "1")

if sys.platform.startswith("win"):
    local = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    os.environ.setdefault("VIDIT_HOME", os.path.join(local, "Vidit"))

# pyscreeze (used by pyautogui screenshots) must find Pillow — it does, but
# be explicit that pyautogui's failsafe corner is the emergency brake.
os.environ.setdefault("PYAUTOGUI_FAILSAFE", "1")

# Vidit's senses are CPU-only by design (whisper int8 on CPU, piper/pyttsx3).
# Keep CUDA DLLs out of the process unless the user explicitly opts in - on
# some NVIDIA driver setups a GPU probe inside a bundled app access-violates
# seconds after boot (the classic "crashes ~10 s in" report).
if not os.environ.get("VIDIT_ALLOW_GPU"):
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

