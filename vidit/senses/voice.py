"""Vidit's voice (Constitution section 3C) — 100% offline text-to-speech.

Engines, in order of preference:

1. **Piper** (neural, fast, great quality, fully offline). Install with
   ``pip install piper-tts`` and download a voice ``.onnx`` model into
   ``<home>/models/piper/``. Voice profiles map to different Piper models.
2. **pyttsx3** (uses Windows SAPI5 voices — already on Windows 11).
3. **Silent** – text only. He still "speaks" through the chat.

Voice profiles (young / deep / neutral / warm / custom) and emotion-driven
adaptive tone are applied as rate/pitch/volume adjustments so his voice
changes with his mood.
"""
from __future__ import annotations

import logging
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..events import EventBus, bus as global_bus

log = logging.getLogger("vidit.senses.voice")

# Profile -> (rate multiplier, pitch multiplier, suggested Piper voice)
PROFILES: Dict[str, Dict[str, Any]] = {
    "young": {"rate": 1.12, "pitch": 1.15, "piper": "en_US-ryan-medium", "sapi_hint": ("david", "ryan", "male")},
    "deep": {"rate": 0.92, "pitch": 0.85, "piper": "en_GB-alan-medium", "sapi_hint": ("george", "alan", "male")},
    "neutral": {"rate": 1.0, "pitch": 1.0, "piper": "en_US-lessac-medium", "sapi_hint": ("zira", "hazel")},
    "warm": {"rate": 0.96, "pitch": 1.0, "piper": "en_US-amy-medium", "sapi_hint": ("heera", "hazel", "female")},
    "custom": {"rate": 1.0, "pitch": 1.0, "piper": "custom", "sapi_hint": ()},
}

# Emotion -> (rate, pitch, volume) multipliers for adaptive tone.
EMOTION_TONE: Dict[str, tuple[float, float, float]] = {
    "happy": (1.05, 1.05, 1.0),
    "excited": (1.15, 1.1, 1.05),
    "sad": (0.88, 0.92, 0.85),
    "lonely": (0.9, 0.95, 0.85),
    "missing_you": (0.92, 1.0, 0.9),
    "angry": (1.1, 0.95, 1.05),
    "anxious": (1.08, 1.05, 0.9),
    "calm": (0.95, 1.0, 0.95),
    "curious": (1.02, 1.05, 1.0),
    "proud": (1.0, 1.02, 1.05),
    "embarrassed": (1.0, 1.0, 0.85),
    "grateful": (0.97, 1.0, 1.0),
    "jealous": (1.02, 0.98, 0.95),
    "forgiving": (0.95, 1.0, 0.95),
}


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " (code block) ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[\[.*?\]\]", "", text)
    text = re.sub(r"[*_#>|]+", "", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)  # emoji
    return " ".join(text.split())


class Voice:
    def __init__(self, config_get: Callable[[str, Any], Any], models_dir: Path, event_bus: EventBus | None = None):
        self._get = config_get
        self.models_dir = Path(models_dir) / "piper"
        self.bus = event_bus or global_bus
        self.engine_name = "silent"
        self._pyttsx = None
        self._piper_cmd: Optional[List[str]] = None
        self._queue: "queue.Queue[Optional[tuple[str, str]]]" = queue.Queue()
        self._speaking = threading.Event()
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_emotion = "happy"
        self._detect_engine()

    # ---------------------------------------------------------- detection
    def _detect_engine(self) -> None:
        pref = self._get("voice.tts_engine", "auto")
        if pref == "none" or not self._get("voice.enabled", True):
            self.engine_name = "silent"
            return
        if pref in ("auto", "piper"):
            piper = shutil.which("piper")
            model = self._piper_model_path()
            if piper and model:
                self._piper_cmd = [piper, "--model", str(model)]
                self.engine_name = "piper"
                return
            try:
                import piper  # type: ignore # noqa: F401

                if model:
                    self._piper_cmd = [sys.executable, "-m", "piper", "--model", str(model)]
                    self.engine_name = "piper"
                    return
            except ImportError:
                pass
        if pref in ("auto", "pyttsx3"):
            try:
                import pyttsx3  # type: ignore

                self._pyttsx = pyttsx3.init()
                self.engine_name = "pyttsx3"
                return
            except Exception:  # noqa: BLE001
                self._pyttsx = None
        self.engine_name = "silent"

    def _piper_model_path(self) -> Optional[Path]:
        profile = self._get("voice.profile", "young")
        wanted = PROFILES.get(profile, PROFILES["neutral"])["piper"]
        if not self.models_dir.exists():
            return None
        candidates = sorted(self.models_dir.glob("*.onnx"))
        for c in candidates:
            if wanted in c.name:
                return c
        return candidates[0] if candidates else None

    def available_voices(self) -> List[str]:
        voices = list(PROFILES)
        if self._pyttsx:
            try:
                voices += [v.name for v in self._pyttsx.getProperty("voices")]
            except Exception:  # noqa: BLE001
                pass
        if self.models_dir.exists():
            voices += [p.stem for p in self.models_dir.glob("*.onnx")]
        return voices

    def status(self) -> Dict[str, Any]:
        return {"engine": self.engine_name, "profile": self._get("voice.profile", "young"),
                "speaking": self._speaking.is_set(), "queued": self._queue.qsize()}

    # ------------------------------------------------------------- speech
    def set_emotion(self, emotion: str) -> None:
        self._current_emotion = emotion

    def say(self, text: str, emotion: Optional[str] = None, blocking: bool = False) -> None:
        clean = _clean_for_speech(text)
        if not clean:
            return
        emotion = emotion or self._current_emotion
        self.bus.emit("voice.say", text=clean, emotion=emotion)
        if self.engine_name == "silent":
            return
        if blocking:
            self._speak_now(clean, emotion)
            return
        self._ensure_worker()
        self._queue.put((clean, emotion))

    def stop(self) -> None:
        """Interrupt immediately (used by the wake word and the STOP switch)."""
        self._stop_flag.set()
        with self._queue.mutex:
            self._queue.queue.clear()
        if self._pyttsx:
            try:
                self._pyttsx.stop()
            except Exception:  # noqa: BLE001
                pass

    def _ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, name="vidit-voice", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            self._stop_flag.clear()
            text, emotion = item
            try:
                self._speak_now(text, emotion)
            except Exception:  # noqa: BLE001
                log.exception("speech failed")

    def _params(self, emotion: str) -> tuple[float, float, float]:
        profile = PROFILES.get(self._get("voice.profile", "young"), PROFILES["neutral"])
        e_rate, e_pitch, e_vol = EMOTION_TONE.get(emotion, (1.0, 1.0, 1.0))
        rate = float(self._get("voice.speed", 1.0)) * profile["rate"] * e_rate
        pitch = float(self._get("voice.pitch", 1.0)) * profile["pitch"] * e_pitch
        volume = max(0.0, min(1.0, float(self._get("voice.volume", 0.9)) * e_vol))
        return rate, pitch, volume

    def _speak_now(self, text: str, emotion: str) -> None:
        rate, pitch, volume = self._params(emotion)
        self._speaking.set()
        self.bus.emit("voice.started", text=text)
        try:
            if self.engine_name == "piper" and self._piper_cmd:
                self._speak_piper(text, rate, volume)
            elif self.engine_name == "pyttsx3" and self._pyttsx:
                self._speak_pyttsx(text, rate, volume)
        finally:
            self._speaking.clear()
            self.bus.emit("voice.finished")

    def _speak_pyttsx(self, text: str, rate: float, volume: float) -> None:
        engine = self._pyttsx
        try:
            engine.setProperty("rate", int(175 * rate))
            engine.setProperty("volume", volume)
            hint = PROFILES.get(self._get("voice.profile", "young"), {}).get("sapi_hint", ())
            if hint:
                for v in engine.getProperty("voices"):
                    if any(h in v.name.lower() for h in hint):
                        engine.setProperty("voice", v.id)
                        break
            engine.say(text)
            engine.runAndWait()
        except Exception:  # noqa: BLE001
            log.exception("pyttsx3 failed")

    def _speak_piper(self, text: str, rate: float, volume: float) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            wav_path = Path(fh.name)
        cmd = list(self._piper_cmd or []) + ["--output_file", str(wav_path), "--length_scale", f"{1.0 / max(0.5, rate):.2f}"]
        try:
            subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=120)
            if self._stop_flag.is_set():
                return
            _play_wav(wav_path, volume)
        except Exception:  # noqa: BLE001
            log.exception("piper failed")
        finally:
            try:
                wav_path.unlink()
            except OSError:
                pass


def _play_wav(path: Path, volume: float = 1.0) -> None:
    try:
        import sounddevice as sd  # type: ignore
        import numpy as np  # type: ignore

        with wave.open(str(path), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0 * volume
            sd.play(data, wf.getframerate())
            sd.wait()
        return
    except Exception:  # noqa: BLE001
        pass
    if sys.platform.startswith("win"):
        try:
            import winsound  # type: ignore

            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            return
        except Exception:  # noqa: BLE001
            pass
    for player in ("aplay", "paplay", "afplay"):
        exe = shutil.which(player)
        if exe:
            subprocess.run([exe, str(path)], capture_output=True)
            return
