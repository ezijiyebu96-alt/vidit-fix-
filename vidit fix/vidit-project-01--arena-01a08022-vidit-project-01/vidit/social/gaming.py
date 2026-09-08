"""Gaming companion (Constitution sections 6 & 7).

Behaviours while you game (``gaming.behavior``):

* ``silent``     – DND; he only reacts to his wake word.
* ``whisper``    – short text tips in the HUD, no voice.
* ``commentate`` – active voice comments ("Enemy left!").
* ``wait``       – nothing until you call him.

Game detection is heuristic (foreground window title + a list of known
game processes). Screen analysis uses OpenCV on screenshots when the SCREEN
permission is granted. **Auto-play / hand-off** ("Vidit, play with my
friends") is a prototype gated behind ``GAME_CONTROL``: a plug-in interface
where per-game controllers can be added under ``skills/`` — the core only
ships the safe scaffolding, a match log and the report mechanism.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..events import EventBus, bus as global_bus
from ..guardian import Capability

log = logging.getLogger("vidit.social.gaming")

KNOWN_GAME_HINTS = (
    "valorant", "counter-strike", "cs2", "csgo", "minecraft", "fortnite", "apex", "league of legends", "dota",
    "gta", "bgmi", "pubg", "call of duty", "warzone", "overwatch", "rocket league", "elden ring", "forza",
    "fifa", "ea sports fc", "roblox", "genshin", "free fire", "among us", "the finals",
)


@dataclass
class MatchReport:
    game: str
    started_at: float
    ended_at: float = 0.0
    events: List[str] = field(default_factory=list)
    outcome: str = "unknown"

    def summary(self) -> str:
        mins = (self.ended_at or time.time()) - self.started_at
        lines = [f"Match report — {self.game} ({mins / 60:.0f} min), outcome: {self.outcome}"]
        lines += [f"- {e}" for e in self.events[-12:]]
        return "\n".join(lines)


class GamingCompanion:
    def __init__(self, config_get: Callable[[str, Any], Any], permissions, event_bus: EventBus | None = None,
                 foreground_title: Optional[Callable[[], str]] = None):
        self._get = config_get
        self.permissions = permissions
        self.bus = event_bus or global_bus
        self._foreground = foreground_title or (lambda: "")
        self.in_game = False
        self.current_game = ""
        self.reports: List[MatchReport] = []
        self._active_report: Optional[MatchReport] = None
        self._autoplay_thread: Optional[threading.Thread] = None
        self._autoplay_stop = threading.Event()
        self.controllers: Dict[str, Callable[[threading.Event, Callable[[str], None]], str]] = {}

    # ---------------------------------------------------------- detection
    def detect(self) -> bool:
        title = (self._foreground() or "").lower()
        game = next((g for g in KNOWN_GAME_HINTS if g in title), "")
        was = self.in_game
        self.in_game = bool(game)
        self.current_game = game
        if self.in_game and not was:
            self.bus.emit("gaming.started", game=game)
            if self._get("gaming.auto_dnd", True):
                self.bus.emit("notifications.dnd", enabled=True, reason=f"gaming: {game}")
        elif was and not self.in_game:
            self.bus.emit("gaming.ended", game=self.current_game)
            self.bus.emit("notifications.dnd", enabled=False, reason="game closed")
        return self.in_game

    def behavior(self) -> str:
        return str(self._get("gaming.behavior", "whisper"))

    def should_speak(self) -> bool:
        return self.behavior() == "commentate"

    def should_show_text(self) -> bool:
        return self.behavior() in ("whisper", "commentate")

    def prompt_fragment(self) -> str:
        if not self.in_game:
            return ""
        b = self.behavior()
        return (f"The user is currently playing {self.current_game or 'a game'}. Gaming behaviour = {b}: "
                + {"silent": "stay silent unless directly addressed.",
                   "whisper": "keep replies to one short line, like a whispered tip.",
                   "commentate": "you may comment briefly and energetically like a teammate.",
                   "wait": "don't initiate anything; answer only when asked."}.get(b, ""))

    # ------------------------------------------------------ screen reading
    def screenshot(self):
        """Grab the screen (needs SCREEN permission + mss or Pillow)."""
        if not self.permissions.check(Capability.SCREEN, "to look at your game screen"):
            return None
        try:
            import mss  # type: ignore
            import numpy as np  # type: ignore

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
                return np.array(shot)[:, :, :3]
        except ImportError:
            try:
                from PIL import ImageGrab  # type: ignore
                import numpy as np  # type: ignore

                return np.array(ImageGrab.grab())[:, :, :3]
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None

    # ----------------------------------------------------------- autoplay
    def register_controller(self, game: str, controller: Callable[[threading.Event, Callable[[str], None]], str]) -> None:
        """A controller is ``fn(stop_event, log) -> outcome`` implemented by a skill (e.g. with pyautogui)."""
        self.controllers[game.lower()] = controller

    def play_for_me(self, game: Optional[str] = None) -> str:
        game = (game or self.current_game or "").lower()
        if not game:
            return "I can't tell which game you mean — open it first or tell me the name."
        if not self.permissions.check(Capability.GAME_CONTROL, f"to take over {game} while you're away"):
            return "You haven't allowed me to control games. Enable it in Settings → Gaming if you want me to."
        controller = self.controllers.get(game)
        if controller is None:
            return (f"I don't have a controller skill for {game} yet. Teach me (a skill named `game_{game}` with "
                    "`run(args, ctx)`) and I'll be able to hold the fort next time.")
        if self._autoplay_thread and self._autoplay_thread.is_alive():
            return "I'm already playing."
        self._autoplay_stop.clear()
        report = MatchReport(game=game, started_at=time.time())
        self._active_report = report

        def run() -> None:
            try:
                outcome = controller(self._autoplay_stop, report.events.append)
                report.outcome = outcome or "finished"
            except Exception as exc:  # noqa: BLE001
                report.outcome = f"crashed: {exc}"
                log.exception("autoplay controller crashed")
            finally:
                report.ended_at = time.time()
                self.reports.append(report)
                self._active_report = None
                self.bus.emit("gaming.report", summary=report.summary())

        self._autoplay_thread = threading.Thread(target=run, name="vidit-autoplay", daemon=True)
        self._autoplay_thread.start()
        return f"On it — I'll play {game} and report back when you return."

    def stop_playing(self) -> str:
        self._autoplay_stop.set()
        return "Stopping. Your controls are yours again."

    def last_report(self) -> Optional[str]:
        return self.reports[-1].summary() if self.reports else None
