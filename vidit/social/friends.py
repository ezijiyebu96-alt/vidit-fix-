"""Friend profiles and greetings (Constitution section 7).

Vidit remembers your friends — names, relation, interests, history — in the
``people`` table. When the eyes or ears recognise someone he can greet them
("Hello Rahul!") or stay quiet until you introduce them, depending on the
``greeting`` preference. Introductions in chat ("this is my friend Rahul, he
loves Valorant") are parsed here.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..brain.memory import MemoryStore
from ..events import EventBus, bus as global_bus

log = logging.getLogger("vidit.social.friends")

_INTRO_RE = re.compile(
    r"\b(?i:this is|meet|say hi to|introducing)\s+(?:(?i:my)\s+(?P<rel>[a-z]+)\s+)?(?P<name>[A-Z][a-zA-Z]{1,20})\b(?:[,.]?\s*(?P<notes>[^.!?\n]{3,120}))?",
)


class Friends:
    def __init__(self, memory: MemoryStore, event_bus: EventBus | None = None):
        self.memory = memory
        self.bus = event_bus or global_bus
        self.present: Dict[str, float] = {}  # name -> last seen timestamp this session

    # -------------------------------------------------------- introductions
    def parse_introduction(self, text: str) -> Optional[Dict[str, str]]:
        m = _INTRO_RE.search(text)
        if not m:
            return None
        name = m.group("name")
        if name.lower() in {"vidit", "the", "a", "an"}:
            return None
        relation = m.group("rel") or "friend"
        notes = (m.group("notes") or "").strip()
        self.memory.remember_person(name, relation, notes)
        self.bus.emit("friends.introduced", name=name, relation=relation)
        return {"name": name, "relation": relation, "notes": notes}

    # -------------------------------------------------------------- greetings
    def someone_arrived(self, name: Optional[str], greeting_mode: str = "auto") -> Optional[str]:
        """Called by the eyes/ears. Returns what Vidit should say, if anything."""
        now = time.time()
        if name:
            recently = self.present.get(name, 0) > now - 1800
            self.present[name] = now
            profile = self.memory.person(name)
            if profile:
                self.memory.remember_person(name)  # bump interactions/last_seen
            if greeting_mode == "quiet" or recently:
                return None
            note = ""
            if profile and profile.get("notes"):
                note = f" {profile['notes'].splitlines()[0][:80]}"
            return f"Hello {name}! Good to see you again.{'' if not note else ''}"
        if greeting_mode == "auto":
            return None  # unknown person: stay quiet until introduced
        return None

    def profile_fragment(self, names: List[str]) -> str:
        lines = []
        for name in names:
            p = self.memory.person(name)
            if p:
                lines.append(f"- {p['name']} ({p['relation'] or 'friend'}): {p['notes'][:160] or 'no notes yet'}; seen {p['interactions']} times")
        return "\n".join(lines)

    def everyone(self) -> List[Dict[str, Any]]:
        return self.memory.people()
