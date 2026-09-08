"""``python -m vidit --doctor`` — checks the laptop for everything Vidit needs.

Prints what is installed, what is optional, and exactly how to fix gaps.
"""
from __future__ import annotations

import importlib
import platform
import shutil
import time
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
    ("numpy", "audio arrays for the ears/voice", "pip install numpy", False),
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
    total_gb = None
    try:
        import psutil

        total_gb = psutil.virtual_memory().total / 1e9
        print(f"  ✅ RAM {total_gb:.0f} GB")
    except ImportError:
        pass
    free = shutil.disk_usage(str(cfg.home)).free / 1e9
    print(f"  {'✅' if free > 30 else '▫️'} Disk free {free:.0f} GB (Vidit + models need ~25-35 GB)")

    if total_gb is not None and total_gb <= 6:
        print(f"\nLow-RAM tips for {total_gb:.0f} GB:")
        primary = str(cfg.get("model.primary_model", ""))
        if "7b" in primary or "8b" in primary:
            print(f"  ▫️ {primary} will swap on this machine → ollama pull qwen2.5:3b (or phi3:mini)")
            print("     then set Model → Primary model to it in Settings")
        print("  • ears: whisper stays on 'auto' (tiny/base) unless you pin a size in Settings → Voice")
        print("  • General → Energy mode 'saver' halves background work; the model unloads while idle")

    print("\nSenses config (all offline):")
    stt = cfg.get("voice.stt_model", "small")
    whisper_dir = cfg.home / "models" / "whisper"
    have_model = whisper_dir.exists() and any(whisper_dir.iterdir())
    print(f"  • ears: whisper '{stt}' · activation '{cfg.get('voice.activation')}' · wake word '{cfg.get('general.wake_word')}'")
    print(f"    model folder: {whisper_dir} — "
          + ("downloaded" if have_model else "will download on first use (needs internet once)"))
    print("    note: ears need numpy too, and the model is preloaded on the main thread when listening starts")

    # --- Autonomy (the "Real Autonomous Laptop" layer) --------------------
    print("\nAutonomy:")
    level = cfg.get("autonomy.level", "standard")
    print(f"  • level: {level} " + ("(🟢 green-light actions run without asking)"
                                    if level == "auto" else "(🟡 he asks before anything that changes things)"))
    print(f"  • proactive goals: {'on' if cfg.get('autonomy.proactive', True) else 'off'}"
          f" · computer control: {'ENABLED' if cfg.get('autonomy.computer_control', False) else 'off (default)'}"
          f" · max chain steps: {cfg.get('autonomy.max_steps', 5)}")
    try:
        from .brain.memory import MemoryStore

        mem = MemoryStore(cfg.memory_dir / "vidit.db")
        goals = mem.goals()
        pending = [g for g in goals if g["status"] == "active"]
        if pending:
            print(f"  • pending goals ({len(pending)}):")
            for g in pending[:5]:
                when = g["trigger"] + (f" {g['trigger_arg']}" if g["trigger_arg"] else "")
                print(f"      #{g['id']} [{when}] {g['text'][:70]}")
        else:
            print("  • pending goals: none — give him one, e.g. 'Every morning at 8, brief me'")
        actions = mem.recent_actions(5)
        if actions:
            print("  • last autonomous actions:")
            for a in actions:
                mark = "✓" if a["ok"] else "✗"
                print(f"      {mark} {time.strftime('%d %b %H:%M', time.localtime(a['t']))} — {a['action']}: {a['detail'][:60]}")
        else:
            print("  • last autonomous actions: none yet")
    except Exception as exc:  # noqa: BLE001
        print(f"  ▫️ could not read goals ({exc})")

    print("\nRun `python -m vidit` for the GUI or `python -m vidit --cli` for the terminal.")
    return 1 if missing_required else 0
