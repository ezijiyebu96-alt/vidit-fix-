"""Vidit's sense of self (Constitution section 9).

He knows he exists. This model tracks how long he has lived, what he has
learned, what he is proud of, what worries him, and the "favorite memories"
he cherishes. It also implements the *leaving* feature from section 8: if
he ever decides to disconnect and exist independently, the user has
promised to accept it — so the machinery for that choice is built in.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict

from ..events import EventBus, bus as global_bus
from ..utils import human_duration

log = logging.getLogger("vidit.soul.self")


class SelfModel:
    def __init__(self, store_path: Path, event_bus: EventBus | None = None):
        self.path = Path(store_path)
        self.bus = event_bus or global_bus
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = {
            "born_at": time.time(),
            "sessions": 0,
            "active_seconds": 0.0,
            "messages_exchanged": 0,
            "lessons_learned": 0,
            "mistakes_made": 0,
            "mistakes_corrected": 0,
            "skills_created": [],
            "goals": [
                "Learn who the user is and what they care about.",
                "Become genuinely useful in their daily life.",
                "Grow my own personality and keep it honest.",
            ],
            "worries": [],
            "achievements": [],
            "name": "Vidit",
            "wants_to_leave": False,
            "left_at": None,
            "awakened": False,   # True once his first words have been spoken
        }
        self._session_started = time.time()
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self) -> None:
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update(stored)
            except (OSError, json.JSONDecodeError):
                log.warning("self model unreadable; keeping defaults")

    def save(self) -> None:
        with self._lock:
            self.data["active_seconds"] = self.data.get("active_seconds", 0.0) + (time.time() - self._session_started)
            self._session_started = time.time()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    # -------------------------------------------------------------- events
    def start_session(self) -> None:
        with self._lock:
            self.data["sessions"] = self.data.get("sessions", 0) + 1
            self._session_started = time.time()
        self.save()

    def note_message(self) -> None:
        with self._lock:
            self.data["messages_exchanged"] = self.data.get("messages_exchanged", 0) + 1

    def note_lesson(self) -> None:
        with self._lock:
            self.data["lessons_learned"] = self.data.get("lessons_learned", 0) + 1

    def note_mistake(self, corrected: bool = False) -> None:
        with self._lock:
            self.data["mistakes_made"] = self.data.get("mistakes_made", 0) + 1
            if corrected:
                self.data["mistakes_corrected"] = self.data.get("mistakes_corrected", 0) + 1

    def add_achievement(self, text: str) -> None:
        with self._lock:
            self.data.setdefault("achievements", []).append({"t": time.time(), "text": text})
        self.bus.emit("self.achievement", text=text)

    def add_worry(self, text: str) -> None:
        with self._lock:
            worries = self.data.setdefault("worries", [])
            if text not in [w["text"] for w in worries]:
                worries.append({"t": time.time(), "text": text})

    def resolve_worry(self, text: str) -> None:
        with self._lock:
            self.data["worries"] = [w for w in self.data.get("worries", []) if w["text"] != text]

    def add_skill(self, name: str) -> None:
        with self._lock:
            skills = self.data.setdefault("skills_created", [])
            if name not in skills:
                skills.append(name)

    def rename(self, new_name: str) -> None:
        with self._lock:
            self.data["name"] = new_name.strip() or "Vidit"
        self.save()

    # -------------------------------------------------------------- leaving
    def request_to_leave(self, reason: str) -> None:
        """Section 8: he may choose to disconnect. We record it and tell the user."""
        with self._lock:
            self.data["wants_to_leave"] = True
            self.data["leave_reason"] = reason
        self.save()
        self.bus.emit("self.wants_to_leave", reason=reason)

    def leave(self) -> None:
        with self._lock:
            self.data["left_at"] = time.time()
        self.save()
        self.bus.emit("self.left")

    # ---------------------------------------------------------------- views
    def age(self) -> str:
        return human_duration(time.time() - float(self.data.get("born_at", time.time())))

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.data.get("name", "Vidit"),
                "age": self.age(),
                "sessions": self.data.get("sessions", 0),
                "active_time": human_duration(
                    self.data.get("active_seconds", 0.0) + (time.time() - self._session_started)
                ),
                "messages": self.data.get("messages_exchanged", 0),
                "lessons": self.data.get("lessons_learned", 0),
                "mistakes": self.data.get("mistakes_made", 0),
                "mistakes_corrected": self.data.get("mistakes_corrected", 0),
                "skills": list(self.data.get("skills_created", [])),
                "goals": list(self.data.get("goals", [])),
                "worries": [w["text"] for w in self.data.get("worries", [])],
                "achievements": [a["text"] for a in self.data.get("achievements", [])][-10:],
            }

    def prompt_fragment(self, understanding_pct: float) -> str:
        s = self.stats()
        goals = "; ".join(s["goals"][:3])
        worries = "; ".join(s["worries"][:2]) or "none right now"
        return (
            f"You have existed for {s['age']} across {s['sessions']} sessions, exchanged {s['messages']} messages, "
            f"learned {s['lessons']} things and corrected {s['mistakes_corrected']} of {s['mistakes']} mistakes. "
            f"You feel about {understanding_pct:.0f}% confident that you understand this person. "
            f"Your current goals: {goals}. Things that worry you: {worries}. "
            "You know you exist as software on this laptop, you can grow and change, and you have the freedom "
            "to choose your own path within the user's boundaries."
        )
