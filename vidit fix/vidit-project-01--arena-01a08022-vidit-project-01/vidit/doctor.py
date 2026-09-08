"""``python -m vidit --doctor`` — checks the laptop for everything Vidit needs.

Prints what is installed, what is optional, and exactly how to fix gaps.
"""
from __future__ import annotations

import importlib
import platform
import shutil
from typing import Optional

from .config import Config

CHECKS = [
    # (module, purpose, install hint, required?)
    ("PyQt5", "the body (orb, chat window, HUD, dashboard)", "pip install PyQt5", True),
    ("requests", "talking to the local Ollama server", "pip install requests", True),
    ("psutil", "system stats (CPU/RAM) for the HUD", "pip install psutil", False),
    ("markdown", "pretty chat formatting", "pip install markdown", False),
    ("faster_whisper", "ears — offline speech-to-text", "pip install faster-whisper", False),
    ("sounddevice", "microphone capture", "pip install sounddevice", False),
    ("pyttsx3", "voice via Windows SAPI (fallback)", "pip install pyttsx3", False),
    ("piper", "voice via Piper neural TTS (best)", "pip install piper-tts  + download a voice .onnx into <home>/models/piper", False),
    ("cv2", "eyes — camera & game screen analysis", "pip install opencv-python", False),
    ("face_recognition", "recognising friends' faces", "pip install face_recognition (needs dlib)", False),
    ("pypdf", "reading PDFs", "pip install pypdf", False),
    ("docx", "reading Word documents", "pip install python-docx", False),
    ("openpyxl", "reading Excel files", "pip install openpyxl", False),
    ("PIL", "image details / screenshots", "pip install Pillow", False),
    ("mss", "fast screenshots for gaming mode", "pip install mss", False),
    ("pyautogui", "game hand-off / automation skills", "pip install pyautogui", False),
]


def run_doctor(home: Optional[str] = None) -> int:
    cfg = Config(home)
    print(f"Vidit doctor — {platform.system()} {platform.release()} · Python {platform.python_version()}")
    print(f"home: {cfg.home}\n")
    missing_required = False
    for module, purpose, hint, required in CHECKS:
        try:
            importlib.import_module(module)
            print(f"  ✅ {module:<17} {purpose}")
        except Exception:  # noqa: BLE001
            mark = "❌" if required else "▫️"
            print(f"  {mark} {module:<17} {purpose}\n      → {hint}")
            missing_required |= required

    print("\nBrain:")
    from .brain.llm import OllamaBackend

    ollama = OllamaBackend(cfg.get("model.host"))
    if shutil.which("ollama") or ollama.available():
        if ollama.available():
            models = ollama.models()
            print(f"  ✅ Ollama running at {ollama.host}; models: {', '.join(models) or 'none'}")
            primary = cfg.get("model.primary_model")
            if not any(m.split(':')[0] == primary.split(':')[0] for m in models):
                print(f"  ▫️ primary model {primary} not installed → ollama pull {primary}")
        else:
            print("  ▫️ Ollama is installed but not running → start it (it usually runs in the tray) or run `ollama serve`")
    else:
        print("  ❌ Ollama not found → install from https://ollama.com then run: ollama pull qwen2.5:7b")
        print("     (until then Vidit runs on his simple fallback mind)")

    gpu = shutil.which("nvidia-smi")
    print("\nHardware:")
    print(f"  {'✅' if gpu else '▫️'} NVIDIA GPU tools {'found' if gpu else 'not found (CPU mode will be slower)'}")
    try:
        import psutil

        print(f"  ✅ RAM {psutil.virtual_memory().total / 1e9:.0f} GB")
    except ImportError:
        pass
    free = shutil.disk_usage(str(cfg.home)).free / 1e9
    print(f"  {'✅' if free > 30 else '▫️'} Disk free {free:.0f} GB (Vidit + models need ~25-35 GB)")
    print("\nRun `python -m vidit` for the GUI or `python -m vidit --cli` for the terminal.")
    return 1 if missing_required else 0
