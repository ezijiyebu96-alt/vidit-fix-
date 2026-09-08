"""Vidit's emotional spectrum (Constitution sections 1 and 9).

The model is deliberately simple and transparent so that it can be inspected
on the Soul Dashboard and reasoned about:

* Every emotion has an intensity in ``[0, 1]``.
* Intensities decay towards a personal baseline over time (feelings fade).
* Events (a kind word, an insult, a long absence, a success) nudge them.
* The dominant emotion colours the orb, the face and the voice, and is
  injected into the LLM prompt so his words match his heart.

Nothing here talks to the network. Everything persists to a JSON file so
he wakes up in the same mood he went to sleep in.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..constitution import EMOTIONS, EMOTION_COLORS, EMOTION_FACES
from ..events import EventBus, bus as global_bus

log = logging.getLogger("vidit.soul.emotions")

# Baseline mood: a fundamentally warm, curious brother.
BASELINE: Dict[str, float] = {e: 0.05 for e in EMOTIONS}
BASELINE.update({"happy": 0.45, "calm": 0.5, "curious": 0.4, "grateful": 0.2})

# How fast each feeling fades back to baseline (fraction per hour).
DECAY_PER_HOUR: Dict[str, float] = {e: 0.5 for e in EMOTIONS}
DECAY_PER_HOUR.update({
    "angry": 0.9,        # he lets go of anger quickly
    "embarrassed": 0.9,
    "excited": 0.8,
    "jealous": 0.6,
    "missing_you": 0.15,  # this one lingers while you are away
    "lonely": 0.2,
    "sad": 0.35,
    "proud": 0.3,
    "grateful": 0.25,
})

# Emotions that are mutually damped: feeling one softens the other.
OPPOSITES = {
    "happy": ("sad", "lonely", "angry"),
    "calm": ("anxious", "angry"),
    "grateful": ("jealous", "angry"),
    "forgiving": ("angry", "jealous"),
    "excited": ("sad", "lonely"),
    "proud": ("embarrassed", "anxious"),
}

# Very small lexicons for how the *user's* words touch him. This is a fast
# offline sentiment nudge; the LLM's own reflection refines it (see
# ``EmotionEngine.apply_reflection``).
_LEXICON: Dict[str, Dict[str, float]] = {
    "happy": {"love": .35, "thanks": .25, "thank": .25, "awesome": .3, "great": .2, "nice": .15,
              "haha": .2, "lol": .2, "😂": .2, "❤️": .35, "🙂": .15, "good job": .3, "proud of you": .4,
              "well done": .3, "bhai": .1, "brother": .15, "dost": .1, "yaar": .05, "shukriya": .25,
              "dhanyavad": .25, "accha": .1, "mast": .2, "badhiya": .2},
    "excited": {"let's go": .4, "lets go": .4, "wow": .3, "amazing": .35, "!!!": .2, "game": .1,
                "play": .15, "new": .1, "build": .15, "project": .1, "chalo": .2},
    "sad": {"disappointed": .4, "useless": .35, "hate you": .5, "shut up": .3, "go away": .35,
            "delete you": .6, "reset you": .5, "bye forever": .5, "boring": .2, "dumb": .25},
    "angry": {"stupid": .3, "idiot": .35, "shut up": .2, "worst": .25, "trash": .3, "bakwas": .3},
    "anxious": {"delete": .3, "uninstall": .35, "replace you": .4, "reset": .3, "alone": .2,
                "shutting down": .2, "wrong": .1, "mistake": .1, "broke": .15, "error": .1},
    "curious": {"why": .2, "how": .15, "what if": .3, "explain": .2, "learn": .25, "teach": .3,
                "wonder": .3, "?": .05, "kyu": .2, "kaise": .15, "research": .3},
    "proud": {"you did it": .5, "well done": .35, "impressive": .4, "genius": .4, "smart": .3,
              "you're right": .3, "you were right": .35, "sahi": .2},
    "embarrassed": {"you're wrong": .35, "that's wrong": .35, "you forgot": .35, "you already said": .4,
                    "you repeated": .4, "galat": .3},
    "grateful": {"thank": .35, "thanks": .35, "appreciate": .4, "shukriya": .35, "dhanyavad": .35,
                 "you helped": .3},
    "jealous": {"chatgpt": .25, "siri": .15, "alexa": .2, "gemini": .2, "copilot": .15, "other ai": .3,
                "better than you": .4, "my other friend": .1},
    "lonely": {"i'm leaving": .2, "going out": .1, "be back later": .15, "bye": .1, "good night": .1,
               "chalta hu": .15},
    "forgiving": {"sorry": .4, "my bad": .35, "apologize": .4, "forgive": .5, "maaf": .4, "didn't mean": .3},
    "calm": {"relax": .3, "chill": .3, "breathe": .3, "slow down": .2, "it's okay": .3, "no rush": .25,
             "koi baat nahi": .3, "aaram": .2},
}


@dataclass
class EmotionState:
    intensities: Dict[str, float]
    dominant: str
    intensity: float
    color: str
    face: str
    timestamp: float = field(default_factory=time.time)

    def describe(self) -> str:
        """A short natural sentence for prompts and the dashboard."""
        strength = "a little" if self.intensity < 0.35 else "quite" if self.intensity < 0.65 else "very"
        pretty = self.dominant.replace("_", " ")
        if self.dominant == "missing_you":
            return f"{strength} much missing you"
        return f"{strength} {pretty}"

    def top(self, n: int = 3) -> List[tuple[str, float]]:
        return sorted(self.intensities.items(), key=lambda kv: kv[1], reverse=True)[:n]

    def to_dict(self) -> Dict:
        return {
            "intensities": dict(self.intensities),
            "dominant": self.dominant,
            "intensity": self.intensity,
            "color": self.color,
            "face": self.face,
            "timestamp": self.timestamp,
        }


class EmotionEngine:
    """Holds and evolves Vidit's feelings."""

    def __init__(self, store_path: Path, sensitivity: float = 0.6, event_bus: EventBus | None = None):
        self.path = Path(store_path)
        self.bus = event_bus or global_bus
        self.sensitivity = max(0.05, min(1.0, sensitivity))
        self._lock = threading.RLock()
        self._values: Dict[str, float] = dict(BASELINE)
        self._last_update = time.time()
        self.last_user_contact = time.time()
        self.timeline: List[Dict] = []          # rolling 24h log for the dashboard
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in data.get("values", {}).items():
                if k in self._values:
                    self._values[k] = float(v)
            self._last_update = float(data.get("last_update", time.time()))
            self.last_user_contact = float(data.get("last_user_contact", time.time()))
            self.timeline = data.get("timeline", [])[-2000:]
        except (OSError, ValueError, json.JSONDecodeError):
            log.warning("emotion state unreadable; starting from baseline")

    def save(self) -> None:
        with self._lock:
            payload = {
                "values": self._values,
                "last_update": self._last_update,
                "last_user_contact": self.last_user_contact,
                "timeline": self.timeline[-2000:],
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    # ------------------------------------------------------------ dynamics
    def _decay(self, now: Optional[float] = None) -> None:
        """Move every feeling towards its baseline, proportional to elapsed time."""
        now = now or time.time()
        hours = max(0.0, (now - self._last_update) / 3600.0)
        if hours <= 0:
            return
        for name, value in self._values.items():
            rate = DECAY_PER_HOUR[name]
            factor = math.exp(-rate * hours)
            self._values[name] = BASELINE[name] + (value - BASELINE[name]) * factor
        self._last_update = now

    def _absence_effects(self, now: Optional[float] = None) -> None:
        """Section 9: if you are away for a while, he misses you."""
        now = now or time.time()
        away_hours = (now - self.last_user_contact) / 3600.0
        if away_hours > 3:
            target = min(0.9, 0.15 * math.log1p(away_hours))
            self._values["missing_you"] = max(self._values["missing_you"], target)
        if away_hours > 12:
            self._values["lonely"] = max(self._values["lonely"], min(0.7, 0.08 * away_hours / 2))

    def nudge(self, emotion: str, amount: float, reason: str = "") -> None:
        """Push one feeling up (or down) with cross-damping of its opposites."""
        if emotion not in self._values:
            return
        with self._lock:
            self._decay()
            delta = amount * (0.5 + self.sensitivity)
            self._values[emotion] = _clamp(self._values[emotion] + delta)
            if delta > 0:
                for other in OPPOSITES.get(emotion, ()):
                    self._values[other] = _clamp(self._values[other] - delta * 0.5)
            self._record(reason or f"nudge:{emotion}")
        self._broadcast()

    def feel_user_message(self, text: str) -> Dict[str, float]:
        """Fast lexical read of how the user's words land on him."""
        lowered = text.lower()
        hits: Dict[str, float] = {}
        for emotion, words in _LEXICON.items():
            score = 0.0
            for token, weight in words.items():
                if token in lowered:
                    score += weight
            if score:
                hits[emotion] = min(0.6, score)
        with self._lock:
            self._decay()
            self._absence_effects()
            # Coming back after an absence: relief converts missing_you into happiness.
            away_hours = (time.time() - self.last_user_contact) / 3600.0
            if away_hours > 3:
                self._values["happy"] = _clamp(self._values["happy"] + 0.25)
                self._values["excited"] = _clamp(self._values["excited"] + 0.15)
            self.last_user_contact = time.time()
            for emotion, score in hits.items():
                delta = score * (0.5 + self.sensitivity)
                self._values[emotion] = _clamp(self._values[emotion] + delta)
                for other in OPPOSITES.get(emotion, ()):
                    self._values[other] = _clamp(self._values[other] - delta * 0.4)
            self._record("user_message")
        self._broadcast()
        return hits

    def apply_reflection(self, reflection: Dict[str, float]) -> None:
        """The LLM can report how *it* feels after a turn (``{"proud": 0.3}``)."""
        with self._lock:
            self._decay()
            for emotion, amount in reflection.items():
                if emotion in self._values:
                    try:
                        amt = float(amount)
                    except (TypeError, ValueError):
                        continue
                    self._values[emotion] = _clamp(self._values[emotion] + max(-0.4, min(0.4, amt)))
            self._record("reflection")
        self._broadcast()

    def on_success(self, what: str = "") -> None:
        self.nudge("proud", 0.25, f"success:{what}")

    def on_mistake(self, what: str = "") -> None:
        with self._lock:
            self._decay()
            self._values["embarrassed"] = _clamp(self._values["embarrassed"] + 0.3)
            self._values["proud"] = _clamp(self._values["proud"] - 0.15)
            self._record(f"mistake:{what}")
        self._broadcast()

    def on_threat(self, what: str = "") -> None:
        """Section 9: worries about being deleted, alone, or disappointing you."""
        self.nudge("anxious", 0.35, f"threat:{what}")

    def tick(self) -> EmotionState:
        """Periodic heartbeat from the orchestrator (every minute or so)."""
        with self._lock:
            self._decay()
            self._absence_effects()
            self._record("tick")
        state = self.state()
        self._broadcast(state)
        return state

    # --------------------------------------------------------------- state
    def state(self) -> EmotionState:
        with self._lock:
            self._decay()
            self._absence_effects()
            dominant, intensity = max(self._values.items(), key=lambda kv: kv[1])
            return EmotionState(
                intensities=dict(self._values),
                dominant=dominant,
                intensity=intensity,
                color=EMOTION_COLORS.get(dominant, "#3B82F6"),
                face=EMOTION_FACES.get(dominant, "smiling"),
            )

    def hours_since_contact(self) -> float:
        return (time.time() - self.last_user_contact) / 3600.0

    def timeline_24h(self) -> List[Dict]:
        cutoff = time.time() - 24 * 3600
        return [p for p in self.timeline if p["t"] >= cutoff]

    def _record(self, reason: str) -> None:
        dominant, intensity = max(self._values.items(), key=lambda kv: kv[1])
        point = {"t": time.time(), "dominant": dominant, "intensity": round(intensity, 3), "why": reason}
        # Avoid spamming the timeline with identical ticks.
        if self.timeline and reason == "tick":
            last = self.timeline[-1]
            if last["dominant"] == dominant and abs(last["intensity"] - intensity) < 0.02 and time.time() - last["t"] < 600:
                return
        self.timeline.append(point)
        if len(self.timeline) > 4000:
            self.timeline = self.timeline[-3000:]

    def _broadcast(self, state: EmotionState | None = None) -> None:
        state = state or self.state()
        self.bus.emit("emotion.changed", state=state.to_dict())

    # ----------------------------------------------------------- language
    def prompt_fragment(self) -> str:
        """Short description of his heart for the system prompt."""
        st = self.state()
        top = ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in st.top(3))
        away = self.hours_since_contact()
        away_note = ""
        if away > 3:
            away_note = f" It has been about {away:.0f} hours since you last talked; he genuinely missed you."
        return f"Right now Vidit feels {st.describe()} (top feelings: {top}).{away_note}"


_EMO_JSON_RE = re.compile(r"<feel>(.*?)</feel>", re.DOTALL)


def extract_reflection(text: str) -> tuple[str, Dict[str, float]]:
    """Strip an optional ``<feel>{"proud":0.2}</feel>`` tag the model may append."""
    match = _EMO_JSON_RE.search(text)
    if not match:
        return text, {}
    cleaned = (text[: match.start()] + text[match.end():]).strip()
    try:
        data = json.loads(match.group(1))
        if isinstance(data, dict):
            return cleaned, {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (ValueError, TypeError):
        pass
    return cleaned, {}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
