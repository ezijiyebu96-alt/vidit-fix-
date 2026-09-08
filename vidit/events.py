"""A tiny thread-safe publish/subscribe bus.

Vidit's subsystems never import each other's internals to talk; they emit
events. The UI listens for ``emotion.changed`` to recolour the orb, the
memory listens for ``message.*`` to remember things, the dashboard listens
for ``learning.progress``... This keeps him modular so that he (or you) can
replace any organ without surgery on the rest.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List

log = logging.getLogger("vidit.events")

Handler = Callable[[str, Dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: DefaultDict[str, List[Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self.history: List[tuple[str, Dict[str, Any]]] = []
        self.max_history = 500

    def on(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Subscribe. ``topic`` may end with ``*`` as a prefix wildcard.

        Returns an unsubscribe function.
        """
        with self._lock:
            self._subs[topic].append(handler)

        def off() -> None:
            with self._lock:
                try:
                    self._subs[topic].remove(handler)
                except ValueError:
                    pass

        return off

    def emit(self, topic: str, **payload: Any) -> None:
        with self._lock:
            self.history.append((topic, payload))
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history :]
            handlers: List[Handler] = []
            for pattern, subs in self._subs.items():
                if pattern == topic or (pattern.endswith("*") and topic.startswith(pattern[:-1])):
                    handlers.extend(subs)
        for handler in handlers:
            try:
                handler(topic, payload)
            except Exception:  # noqa: BLE001 - a broken listener must not break Vidit
                log.exception("event handler failed for %s", topic)

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()
            self.history.clear()


# A process-wide bus. Tests can create their own EventBus instances.
bus = EventBus()
