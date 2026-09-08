"""How Vidit learns (Constitution section 2).

Sources of learning:

1. **You, directly** – every message is mined for facts, preferences,
   people, goals and corrections. A fast offline pattern pass runs on
   every turn; when the local model is available it performs a richer
   extraction in the background.
2. **Corrections** – "no, my name is Aarav" or "you're wrong" creates a
   ``correction`` memory with high importance so the mistake is never
   repeated.
3. **Self-exploration** – file/web research results are stored as
   ``note`` memories with their source.
4. **Behaviour** – activity patterns (when you talk, how long, what
   about) feed the understanding score.

The *understanding score* shown on the Soul Dashboard ("I am X% confident
in understanding you") is computed from how much he knows across the
dimensions that matter to a brother: identity, people, preferences, goals,
routines and shared moments.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .memory import MemoryStore

log = logging.getLogger("vidit.brain.learning")

# Fast offline patterns. Kept intentionally readable; the LLM pass catches the rest.
_PATTERNS: List[tuple[re.Pattern[str], str, str, float]] = [
    # (regex, memory kind, template, importance)
    (re.compile(r"\b(?:my name is|i am called|call me|i'm|im|i am)\s+([A-Z][a-zA-Z]{1,20})\b(?!\s+(?:going|feeling|so|very|not|a|an|the|just|really|tired|happy|sad|bored|here|back|fine|ok|okay|good|done)\b)", re.I), "fact", "The user's name is {0}.", 1.0),
    (re.compile(r"\bmera naam\s+([A-Za-z]{2,20})\s+hai\b", re.I), "fact", "The user's name is {0}.", 1.0),
    (re.compile(r"\bi (?:really )?(?:love|like|enjoy|adore)\s+((?:(?!\bwith\b|\band\b|\bbecause\b)[^.!?\n,]){2,60})", re.I), "preference", "The user likes {0}.", 0.6),
    (re.compile(r"\bi (?:really )?(?:hate|dislike|can't stand|cannot stand)\s+((?:(?!\bbecause\b)[^.!?\n,]){2,60})", re.I), "preference", "The user dislikes {0}.", 0.6),
    (re.compile(r"\bmy favou?rite\s+([a-z ]{2,25})\s+is\s+([^.!?\n]{1,50})", re.I), "preference", "The user's favorite {0} is {1}.", 0.7),
    (re.compile(r"\bmy (?:best |close |good |school |college |online )?friend(?:'s name)?(?: is| is called|,)?\s+([A-Z][a-zA-Z]{1,20})\b", re.I), "person", "{0} is the user's friend.", 0.8),
    (re.compile(r"\bmy (brother|sister|mom|mother|dad|father|wife|husband|girlfriend|boyfriend|cousin|uncle|aunt|grandma|grandpa|teacher|boss)(?:'s name)?(?: is| is called|,)?\s+([A-Z][a-zA-Z]{1,20})\b", re.I), "person", "{1} is the user's {0}.", 0.85),
    (re.compile(r"\bi (?:live|stay) in\s+([A-Z][a-zA-Z ]{2,30})", re.I), "fact", "The user lives in {0}.", 0.8),
    (re.compile(r"\bi(?:'m| am) from\s+([A-Z][a-zA-Z ]{2,30})", re.I), "fact", "The user is from {0}.", 0.7),
    (re.compile(r"\bi (?:work|am working) (?:as|at|in)\s+([^.!?\n]{2,50})", re.I), "fact", "The user works as/at {0}.", 0.7),
    (re.compile(r"\bi(?:'m| am) (?:studying|a student (?:of|at|in))\s+([^.!?\n]{2,50})", re.I), "fact", "The user studies {0}.", 0.7),
    (re.compile(r"\bi(?:'m| am)\s+(\d{1,2})\s*(?:years old|yrs old|y/o)\b", re.I), "fact", "The user is {0} years old.", 0.8),
    (re.compile(r"\bmy birthday is\s+([^.!?\n]{3,30})", re.I), "fact", "The user's birthday is {0}.", 0.9),
    (re.compile(r"\bi (?:want to|wanna|plan to|am planning to|aim to)\s+([^.!?\n]{3,70})", re.I), "goal", "The user wants to {0}.", 0.6),
    (re.compile(r"\bi (?:usually|always|normally|often)\s+([^.!?\n]{3,60})", re.I), "fact", "The user usually {0}.", 0.5),
    (re.compile(r"\bi play\s+([A-Za-z0-9: ]{2,30})", re.I), "preference", "The user plays {0}.", 0.6),
    (re.compile(r"\bremember (?:that )?([^.!?\n]{4,120})", re.I), "note", "{0}", 0.8),
    (re.compile(r"\byaad rakhna (?:ki )?([^.!?\n]{4,120})", re.I), "note", "{0}", 0.8),
]

_NOT_NAMES = frozenset("""sure sorry fine good here done back not so very really just going feeling tired happy sad
    bored ok okay a an the still also always never now today tonight ready glad busy free home late early hungry
    sick sleepy bad great excited curious lost angry lonely alone proud grateful confused kidding serious""".split())

_CORRECTION_RE = re.compile(
    r"^(?:no|nope|nahi|nahin|wrong|that's wrong|you're wrong|galat|incorrect|actually|not quite)[,.! ]+(.{3,160})", re.I
)
_FORGET_RE = re.compile(r"\b(?:forget|bhool jao|bhul jao|delete the memory|don't remember)\s+(?:that |about |ki )?([^.!?\n]{2,100})", re.I)

_EXTRACT_SYSTEM = (
    "You extract long-term memories about a person from a short chat excerpt. "
    "Return ONLY a JSON list. Each item: {\"kind\": one of fact|preference|person|event|lesson|moment|goal, "
    "\"content\": a self-contained sentence written in third person about 'the user' (or about Vidit if it's about Vidit), "
    "\"importance\": 0.0-1.0}. Skip small talk. Include emotional moments worth cherishing as kind 'moment'. "
    "If nothing is worth remembering, return []."
)

UNDERSTANDING_DIMENSIONS: Dict[str, tuple[tuple[str, ...], int]] = {
    # dimension: (memory kinds that count, how many memories = 100% for this dimension)
    "identity": (("fact",), 8),
    "people": (("person",), 5),
    "preferences": (("preference",), 10),
    "goals": (("goal",), 4),
    "shared_moments": (("moment", "event"), 8),
    "lessons": (("lesson", "correction"), 6),
}


class Learner:
    def __init__(self, memory: MemoryStore, llm_quick_json: Optional[Callable[..., Any]] = None,
                 on_lesson: Optional[Callable[[], None]] = None):
        self.memory = memory
        self._llm_json = llm_quick_json
        self._on_lesson = on_lesson or (lambda: None)
        self._lock = threading.Lock()
        self._background: Optional[threading.Thread] = None

    # ------------------------------------------------------------ per turn
    def learn_from_user(self, text: str) -> Dict[str, Any]:
        """Synchronous, instant pattern learning. Returns what was learned."""
        learned: List[str] = []
        corrections: List[str] = []
        forgotten = 0
        stripped = text.strip()

        forget = _FORGET_RE.search(stripped)
        if forget:
            forgotten = self.memory.forget(forget.group(1))
            # A request to forget must never be mined for new facts.
            return {"learned": [], "corrections": [], "forgotten": forgotten}

        correction = _CORRECTION_RE.match(stripped)
        if correction:
            content = correction.group(1).strip()
            self.memory.remember(f"Correction from the user: {content}", "correction", 0.95, source="correction")
            corrections.append(content)
            # If the correction restates a fact we hold, drop the stale version first.
            name_fix = re.search(r"\bmy name is\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)", content)
            if name_fix:
                for old in self.memory.all_memories("fact"):
                    if old.content.startswith("The user's name is"):
                        self.memory.forget_id(old.id)
                self.memory.remember(f"The user's name is {name_fix.group(1)}.", "fact", 1.0, source="correction")
                learned.append(f"The user's name is {name_fix.group(1)}.")
            self._on_lesson()

        for pattern, kind, template, importance in _PATTERNS:
            for match in pattern.finditer(stripped):
                groups = [g.strip().rstrip(",;") for g in match.groups() if g]
                if not groups:
                    continue
                content = template.format(*groups)
                if kind == "fact" and content.startswith("The user's name is"):
                    name = groups[0]
                    # Names are capitalised in the user's own text; "i'm hungry" is not a name.
                    if not name[0].isupper() or name.lower() in _NOT_NAMES:
                        continue
                    if corrections and any(c.startswith("The user's name is") for c in learned):
                        continue  # the correction branch already stored the full corrected name
                if kind == "person" and len(groups) >= 1:
                    name = groups[-1] if "{1}" in template else groups[0]
                    relation = groups[0].lower() if "{1}" in template else "friend"
                    if not name[0].isupper() or name.lower() in _NOT_NAMES:
                        continue
                    self.memory.remember_person(name, relation)
                mem_id = self.memory.remember(content, kind, importance, source="pattern")
                if mem_id > 0:
                    learned.append(content)
        if learned:
            self._on_lesson()
        return {"learned": learned, "corrections": corrections, "forgotten": forgotten}

    def learn_from_exchange_async(self, user_text: str, assistant_text: str) -> None:
        """Deeper extraction with the local model, off the UI thread."""
        if not self._llm_json:
            return
        if len(user_text) < 15:
            return

        def _run() -> None:
            try:
                excerpt = f"User: {user_text}\nVidit: {assistant_text[:600]}"
                items = self._llm_json(f"Chat excerpt:\n{excerpt}\n\nJSON list of memories:", _EXTRACT_SYSTEM, default=[])
                if not isinstance(items, list):
                    return
                count = 0
                for item in items[:6]:
                    if not isinstance(item, dict):
                        continue
                    content = str(item.get("content", "")).strip()
                    if len(content) < 6:
                        continue
                    kind = str(item.get("kind", "fact"))
                    try:
                        importance = float(item.get("importance", 0.5))
                    except (TypeError, ValueError):
                        importance = 0.5
                    if self.memory.remember(content, kind, importance, source="llm") > 0:
                        count += 1
                if count:
                    self._on_lesson()
            except Exception:  # noqa: BLE001
                log.exception("background learning failed")

        with self._lock:
            if self._background and self._background.is_alive():
                # Don't pile up threads; skip this one, the next turn will catch up.
                return
            self._background = threading.Thread(target=_run, name="vidit-learn", daemon=True)
            self._background.start()

    # ---------------------------------------------------------- reflection
    def understanding(self) -> Dict[str, Any]:
        """"I am X% confident in understanding you" — with a per-dimension breakdown."""
        breakdown: Dict[str, float] = {}
        all_memories = self.memory.all_memories()
        for dim, (kinds, target) in UNDERSTANDING_DIMENSIONS.items():
            count = sum(1 for m in all_memories if m.kind in kinds)
            breakdown[dim] = min(1.0, count / target)
        weights = {"identity": 0.25, "people": 0.15, "preferences": 0.2, "goals": 0.1, "shared_moments": 0.2, "lessons": 0.1}
        score = sum(breakdown[d] * w for d, w in weights.items())
        return {"percent": round(score * 100, 1), "breakdown": {k: round(v * 100) for k, v in breakdown.items()},
                "memories": len(all_memories)}

    def maintenance(self) -> Dict[str, int]:
        """Nightly-ish housekeeping: decay, promote favourites."""
        self.memory.decay()
        promoted = self.memory.promote_favorites()
        return {"promoted_favorites": promoted}

    def memory_map(self) -> Dict[str, Any]:
        """Graph data for the Soul Dashboard's Memory Map."""
        nodes: List[Dict[str, Any]] = [{"id": "you", "label": "You", "kind": "root", "size": 30}]
        edges: List[Dict[str, Any]] = []
        for kind in ("fact", "preference", "person", "goal", "moment", "lesson", "correction", "event", "note", "skill"):
            mems = self.memory.all_memories(kind)
            if not mems:
                continue
            hub = f"kind:{kind}"
            nodes.append({"id": hub, "label": kind.title(), "kind": "hub", "size": 12 + min(18, len(mems))})
            edges.append({"source": "you", "target": hub})
            for m in mems[:25]:
                nodes.append({"id": f"m:{m.id}", "label": m.content[:60], "kind": kind, "size": 4 + int(m.importance * 8),
                              "favorite": m.favorite})
                edges.append({"source": hub, "target": f"m:{m.id}"})
        return {"nodes": nodes, "edges": edges, "generated_at": time.time()}
