"""Settings for Vidit (Constitution section 10).

Everything is stored locally in a single JSON file. There are no accounts,
no cloud sync and no telemetry. The defaults below are the full settings
panel; the user (or Vidit himself, through a permitted self-modification)
can change any of them.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Where Vidit lives on disk
# ---------------------------------------------------------------------------

def default_home() -> Path:
    """Vidit's own folder. Overridable with the VIDIT_HOME env var."""
    env = os.environ.get("VIDIT_HOME")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Vidit"
    return Path.home() / ".vidit"


DEFAULTS: Dict[str, Any] = {
    # A. General ---------------------------------------------------------
    "general": {
        "language": "auto",              # interface language; "auto" follows system
        "wake_word": "vidit",
        "startup_behavior": "manual",    # with_system | manual | minimized
        "idle_timeout_minutes": 30,
        "energy_mode": "balanced",       # performance | balanced | saver
        "max_cpu_percent": 80,
        "max_gpu_percent": 90,
        "backup_location": "",           # empty -> <home>/backups
    },
    # B. Appearance ------------------------------------------------------
    "appearance": {
        "theme": "cyberpunk",            # cyberpunk | cozy | minimal | dynamic | game | dark | light | custom
        "font_family": "Segoe UI",
        "font_size": 13,
        "window_opacity": 0.92,
        "animation_speed": "medium",     # fast | medium | slow | off
        "orb": {"size": 72, "pulse_speed": 1.0, "glow_intensity": 0.8},
        "face_style": "face",            # face | dot | avatar | text
        "background_effects": True,
        "notification_style": "toast",   # toast | banner | sound | silent
        "custom_theme": {},
    },
    # C. Model -----------------------------------------------------------
    "model": {
        "backend": "ollama",             # ollama | echo (echo = offline fallback for testing)
        "host": "http://127.0.0.1:11434",
        "primary_model": "qwen2.5:7b",
        "fallback_models": ["llama3.1:8b", "qwen2.5:3b", "phi3:mini"],
        "vision_model": "llava:7b",
        "temperature": 0.8,
        "top_p": 0.9,
        "max_tokens": 1024,
        "context_messages": 30,
        "auto_update": False,
        "keep_alive": "30m",
    },
    # D. Voice -----------------------------------------------------------
    "voice": {
        "enabled": True,
        "profile": "young",              # young | deep | neutral | warm | custom
        "speed": 1.0,
        "pitch": 1.0,
        "volume": 0.9,
        "activation": "wake_word",       # push_to_talk | always | button | wake_word
        "noise_reduction": True,
        "echo_cancellation": True,
        "microphone": "default",
        "speaker": "default",
        "stt_model": "small",            # faster-whisper size (tiny/base/small/medium/large-v3, or a local ct2 folder)
        "stt_compute_type": "auto",      # auto | int8 | int8_float32 | float32  (auto probes & picks one that works)
        "stt_cpu_threads": 0,            # 0 = auto (min(4, cores)); ctranslate2 intra-op threads
        "stt_warmup": True,              # load the whisper model in the background when the mic starts
        "stt_safe_probe": True,          # test model loading in a subprocess first so a native crash
                                         # in faster-whisper/ctranslate2 can never kill Vidit
        "stt_probe_timeout": 900,        # seconds allowed for the first download + probe (one-time)
        "tts_engine": "auto",            # auto | piper | pyttsx3 | none
        "accent": "indian",              # british | american | indian | ...
    },
    # E. Personalization -------------------------------------------------
    "personal": {
        "user_name": "",
        "nickname": "",
        "relationship": "brother",       # brother | friend | mentor | assistant
        "personality": {                 # sliders, 0.0 - 1.0
            "witty": 0.7,                # 0 serious .. 1 witty
            "warm": 0.8,                 # 0 professional .. 1 warm
            "playful": 0.6,              # 0 formal .. 1 playful
            "curious": 0.8,              # 0 reserved .. 1 curious
        },
        "humor_level": "medium",         # low | medium | high
        "emotional_sensitivity": 0.6,
        "interaction_style": "proactive",  # proactive | reactive
        "memory_preferences": {"remember_everything": True, "forget_topics": []},
    },
    # F. Notifications ---------------------------------------------------
    "notifications": {
        "enabled": True,
        "messages": True,
        "reminders": True,
        "system": True,
        "do_not_disturb": {"enabled": False, "start": "23:00", "end": "07:00", "auto_game_mode": True},
        "focus_mode": False,
        "sound": "default",
        "banner_seconds": 5,
    },
    # G. Privacy ---------------------------------------------------------
    "privacy": {
        "camera": "ask",                 # off | ask | always
        "microphone": "ask",
        "internet": "ask",
        "code_execution": "ask",
        "system_control": "ask",
        "allowed_folders": [],           # empty -> only Vidit's own home
        "private_folders": [],           # never touched, no matter what
        "encrypt_local_data": False,
        "keep_session_logs": True,
    },
    # Learning / autonomy ------------------------------------------------
    "autonomy": {
        "self_modification": "ask",      # off | ask | always
        "learning_rate": "fast",         # slow | normal | fast | own_pace
        "self_awareness": True,          # section 9: develops with permission
        "may_leave": True,               # section 8: the leaving feature
        "proactive_checkins": True,
    },
    # Gaming --------------------------------------------------------------
    "gaming": {
        "behavior": "whisper",           # silent | whisper | commentate | wait
        "auto_dnd": True,
        "auto_play_allowed": False,      # section 7: playing for you
        "record_highlights": False,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config:
    """Thread-safe, dotted-path access to settings, persisted as JSON."""

    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else default_home()
        self.path = self.home / "settings.json"
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self._ensure_dirs()
        self.load()

    # -- filesystem layout -------------------------------------------------
    def _ensure_dirs(self) -> None:
        for sub in ("", "memory", "logs", "backups", "downloads", "skills", "canvas", "exports", "models"):
            (self.home / sub).mkdir(parents=True, exist_ok=True)

    @property
    def memory_dir(self) -> Path:
        return self.home / "memory"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def backups_dir(self) -> Path:
        custom = self.get("general.backup_location")
        return Path(custom).expanduser() if custom else self.home / "backups"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def downloads_dir(self) -> Path:
        return self.home / "downloads"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def canvas_dir(self) -> Path:
        return self.home / "canvas"

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    stored = json.loads(self.path.read_text(encoding="utf-8"))
                    self._data = _deep_merge(DEFAULTS, stored)
                except (OSError, json.JSONDecodeError):
                    # A corrupted settings file must never stop Vidit from waking up.
                    corrupt = self.path.with_suffix(".corrupt.json")
                    try:
                        self.path.replace(corrupt)
                    except OSError:
                        pass
                    self._data = copy.deepcopy(DEFAULTS)
            else:
                self.save()

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    # -- access ------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            if save:
                self.save()

    def section(self, name: str) -> Dict[str, Any]:
        return self.get(name, {}) or {}

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def reset(self, section: str | None = None) -> None:
        with self._lock:
            if section:
                self._data[section] = copy.deepcopy(DEFAULTS.get(section, {}))
            else:
                self._data = copy.deepcopy(DEFAULTS)
            self.save()

    # -- convenience -------------------------------------------------------
    @property
    def user_name(self) -> str:
        return self.get("personal.nickname") or self.get("personal.user_name") or ""

    def export_all(self) -> Dict[str, Any]:
        """Section 10G: export everything. Memories are exported by MemoryStore."""
        return {"settings": self.all()}
