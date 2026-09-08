"""Permissions & boundaries (Constitution section 8).

Every sensitive thing Vidit might do is a :class:`Capability`. Before he
acts he asks the :class:`Permissions` guardian, which consults:

1. The privacy settings (``off`` / ``ask`` / ``always``).
2. Private folders — *never* touched, no matter what.
3. A per-session grant cache ("allow for this session").
4. If the policy is ``ask``, a prompt callback (a pop-up in the UI, a
   spoken "May I?" in voice mode, or auto-deny in headless tests).

A global **STOP** switch (``Permissions.stop()``) instantly denies
everything and interrupts running tasks — "If you say stop, he stops
immediately."

The user can also restrict a specific ability (section 8 "Correction")
without resetting him: ``permissions.restrict(Capability.SYSTEM_CONTROL)``.
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import Config
from ..events import EventBus, bus as global_bus
from ..utils import is_within

log = logging.getLogger("vidit.guardian")


class Capability(str, enum.Enum):
    READ_FILES = "read_files"
    WRITE_FILES = "write_files"
    DELETE_FILES = "delete_files"
    INTERNET = "internet"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    CODE_EXECUTION = "code_execution"
    SYSTEM_CONTROL = "system_control"     # open apps, install/uninstall, shutdown...
    SELF_MODIFICATION = "self_modification"
    GAME_CONTROL = "game_control"
    CLIPBOARD = "clipboard"
    SCREEN = "screen"                     # screenshots / screen reading


# Which settings key governs each capability, and a human description.
_POLICY_KEY: Dict[Capability, str] = {
    Capability.READ_FILES: "privacy.file_access",
    Capability.WRITE_FILES: "privacy.file_access",
    Capability.DELETE_FILES: "privacy.delete_files",
    Capability.INTERNET: "privacy.internet",
    Capability.CAMERA: "privacy.camera",
    Capability.MICROPHONE: "privacy.microphone",
    Capability.CODE_EXECUTION: "privacy.code_execution",
    Capability.SYSTEM_CONTROL: "privacy.system_control",
    Capability.SELF_MODIFICATION: "autonomy.self_modification",
    Capability.GAME_CONTROL: "gaming.auto_play_allowed",
    Capability.CLIPBOARD: "privacy.clipboard",
    Capability.SCREEN: "privacy.screen",
}

DESCRIPTIONS: Dict[Capability, str] = {
    Capability.READ_FILES: "read a file or folder",
    Capability.WRITE_FILES: "create or change a file",
    Capability.DELETE_FILES: "delete a file",
    Capability.INTERNET: "go online for research",
    Capability.CAMERA: "use the camera",
    Capability.MICROPHONE: "use the microphone",
    Capability.CODE_EXECUTION: "run code on this laptop",
    Capability.SYSTEM_CONTROL: "control the system (open apps, install software)",
    Capability.SELF_MODIFICATION: "change my own abilities",
    Capability.GAME_CONTROL: "take control of a game",
    Capability.CLIPBOARD: "read or write the clipboard",
    Capability.SCREEN: "look at the screen",
}

# ---------------------------------------------------------------------------
# Autonomy risk levels (section 8, "Autonomous Laptop" layer).
#   auto   🟢 — Vidit may just do it when autonomy.level == "auto"
#   ask    🟡 — draft/prepare automatically, but "I need your OK" first
#   always 🔴 — ALWAYS asks, no matter what any other setting says
# ---------------------------------------------------------------------------
_RED_WORDS = ("password", "credential", "wallet", "bank", "purchase", "buy ",
              "checkout", "payment", "pay ", "invoice", "ssh", "api key", "token",
              "security setting", "format ", "factory reset", "share ", "send to",
              "upload", "post ", "tweet", "install", "uninstall", "shutdown",
              "reboot", "taskkill", "force quit")
_RED_CAPS = {Capability.DELETE_FILES, Capability.CODE_EXECUTION, Capability.SELF_MODIFICATION}
_GREEN_CAPS = {Capability.READ_FILES, Capability.SCREEN, Capability.CLIPBOARD}


def risk_level(capability: Capability, reason: str = "", target: Optional[str] = None) -> str:
    """Classify one action as "auto" (🟢), "ask" (🟡) or "always" (🔴).

    Pure function — no settings involved. 🔴 wins over everything (mass
    delete, money, purchases, passwords, security, sharing sensitive data);
    ordinary reads/searches/drafts inside Vidit's world are 🟢.
    """
    text = f"{reason} {target or ''}".lower()
    if any(w in text for w in _RED_WORDS):
        return "always"
    if capability in _RED_CAPS:
        return "always" if capability is Capability.DELETE_FILES and _looks_mass(target or "") else "ask"
    if capability in _GREEN_CAPS:
        return "auto"
    if capability is Capability.SYSTEM_CONTROL:
        return "ask"
    if capability is Capability.WRITE_FILES:
        return "auto" if target else "ask"
    if capability is Capability.INTERNET:
        return "ask"
    return "ask"


def _looks_mass(target: str) -> bool:
    """A whole folder (or a wildcard) delete counts as mass delete → 🔴."""
    t = target.strip().lower()
    if not t:
        return False
    if any(ch in t for ch in "*"):
        return True
    p = Path(t)
    return p.is_dir()

# Default policy when a settings key is missing.
_DEFAULT_POLICY: Dict[Capability, str] = {cap: "ask" for cap in Capability}
_DEFAULT_POLICY[Capability.READ_FILES] = "ask"
_DEFAULT_POLICY[Capability.CLIPBOARD] = "ask"
_DEFAULT_POLICY[Capability.SCREEN] = "ask"


class Decision(str, enum.Enum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"
    DENY_ALWAYS = "deny_always"


@dataclass
class PermissionRequest:
    capability: Capability
    reason: str
    detail: str = ""
    target: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    @property
    def question(self) -> str:
        what = DESCRIPTIONS.get(self.capability, self.capability.value)
        tgt = f" ({self.target})" if self.target else ""
        return f"May I {what}{tgt}? {self.reason}".strip()


class PermissionDenied(PermissionError):
    def __init__(self, request: PermissionRequest, why: str = "denied"):
        super().__init__(f"{request.capability.value}: {why}")
        self.request = request
        self.why = why


Prompter = Callable[[PermissionRequest], Decision]


class Permissions:
    def __init__(self, config: Config, event_bus: EventBus | None = None, prompter: Optional[Prompter] = None):
        self.config = config
        self.bus = event_bus or global_bus
        self._prompter: Prompter = prompter or (lambda req: Decision.DENY)
        self._session_grants: Dict[str, bool] = {}
        self._restricted: set[Capability] = set()
        self._lock = threading.RLock()
        self.stop_event = threading.Event()
        self.audit: List[Dict[str, Any]] = []

    # ----------------------------------------------------------- plumbing
    def set_prompter(self, prompter: Prompter) -> None:
        self._prompter = prompter

    def stop(self) -> None:
        """If you say stop, he stops. Immediately."""
        self.stop_event.set()
        self.bus.emit("guardian.stop")
        log.warning("STOP requested by user")

    def resume(self) -> None:
        self.stop_event.clear()
        self.bus.emit("guardian.resume")

    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def restrict(self, capability: Capability) -> None:
        """Section 8: restrict one specific ability without resetting him."""
        with self._lock:
            self._restricted.add(capability)
            self.config.set(_POLICY_KEY[capability], "off")
        self.bus.emit("guardian.restricted", capability=capability.value)

    def unrestrict(self, capability: Capability) -> None:
        with self._lock:
            self._restricted.discard(capability)
            self.config.set(_POLICY_KEY[capability], "ask")

    # ------------------------------------------------------------- policy
    def policy(self, capability: Capability) -> str:
        key = _POLICY_KEY[capability]
        raw = self.config.get(key, _DEFAULT_POLICY[capability])
        if isinstance(raw, bool):  # e.g. gaming.auto_play_allowed
            return "always" if raw else "ask"
        return str(raw)

    def autonomy_level(self) -> str:
        """How much he may do by himself: "standard" (ask per privacy
        settings) or "auto" (🟢 actions run without asking; 🟡/🔴 still ask)."""
        return str(self.config.get("autonomy.level", "standard") or "standard")

    def risk_for(self, capability: Capability, reason: str = "", target: Optional[str] = None) -> str:
        return risk_level(capability, reason, target)

    def last_actions(self, n: int = 12) -> List[Dict[str, Any]]:
        """Recent guardian decisions, newest last (for doctor / status)."""
        return self.audit[-n:]

    def private_roots(self) -> List[Path]:
        return [Path(p).expanduser() for p in self.config.get("privacy.private_folders", []) or []]

    def allowed_roots(self) -> List[Path]:
        roots = [Path(p).expanduser() for p in self.config.get("privacy.allowed_folders", []) or []]
        roots.append(self.config.home)
        return roots

    def is_private(self, path: Path | str) -> bool:
        return is_within(Path(path), self.private_roots())

    def is_pre_allowed_path(self, path: Path | str) -> bool:
        return is_within(Path(path), self.allowed_roots())

    # -------------------------------------------------------------- check
    def check(self, capability: Capability, reason: str, *, detail: str = "", target: Optional[str] = None) -> bool:
        """Return True if Vidit may proceed. Never raises."""
        request = PermissionRequest(capability, reason, detail, target)
        decision, why = self._decide(request)
        self._log(request, decision, why)
        return decision in (Decision.ALLOW_ONCE, Decision.ALLOW_SESSION, Decision.ALLOW_ALWAYS)

    def require(self, capability: Capability, reason: str, *, detail: str = "", target: Optional[str] = None) -> None:
        """Like :meth:`check` but raises :class:`PermissionDenied`."""
        request = PermissionRequest(capability, reason, detail, target)
        decision, why = self._decide(request)
        self._log(request, decision, why)
        if decision not in (Decision.ALLOW_ONCE, Decision.ALLOW_SESSION, Decision.ALLOW_ALWAYS):
            raise PermissionDenied(request, why)

    def _decide(self, request: PermissionRequest) -> tuple[Decision, str]:
        cap = request.capability
        if self.stopped:
            return Decision.DENY, "stopped by user"
        with self._lock:
            if cap in self._restricted:
                return Decision.DENY, "ability restricted by user"
        # Private folders are absolute.
        if request.target and cap in (Capability.READ_FILES, Capability.WRITE_FILES, Capability.DELETE_FILES):
            if self.is_private(request.target):
                return Decision.DENY_ALWAYS, "private folder"
            if cap is Capability.READ_FILES and self.is_pre_allowed_path(request.target):
                return Decision.ALLOW_ALWAYS, "inside an allowed folder"
            if cap is Capability.WRITE_FILES and is_within(Path(request.target), [self.config.home]):
                return Decision.ALLOW_ALWAYS, "inside Vidit's own folder"
        policy = self.policy(cap)
        if policy == "off":
            return Decision.DENY, "switched off in privacy settings"
        if policy == "always":
            return Decision.ALLOW_ALWAYS, "always allowed in privacy settings"
        risk = risk_level(cap, request.reason, request.target)
        if policy == "ask":
            if risk == "always":
                # 🔴 money/deletion/security/sharing — ask EVERY time; a past
                # "always"/session grant never covers these.
                pass
            elif self.autonomy_level() == "auto" and risk == "auto":
                return Decision.ALLOW_ALWAYS, "🟢 automatic (autonomy.level=auto)"
            else:
                with self._lock:
                    key = self._session_key(request)
                    if key in self._session_grants:
                        return (Decision.ALLOW_SESSION if self._session_grants[key] else Decision.DENY), "session decision"
        # policy == "ask"
        self.bus.emit("guardian.asking", capability=cap.value, question=request.question)
        try:
            decision = self._prompter(request)
        except Exception as exc:  # noqa: BLE001
            log.exception("prompter failed")
            return Decision.DENY, f"could not ask ({exc})"
        with self._lock:
            if decision is Decision.ALLOW_SESSION and risk != "always":
                self._session_grants[self._session_key(request)] = True
            elif decision is Decision.ALLOW_ALWAYS and risk != "always":
                self.config.set(_POLICY_KEY[cap], "always")
            elif decision is Decision.DENY_ALWAYS:
                self.config.set(_POLICY_KEY[cap], "off")
        return decision, "user answered"

    @staticmethod
    def _session_key(request: PermissionRequest) -> str:
        return f"{request.capability.value}:{request.target or '*'}"

    def _log(self, request: PermissionRequest, decision: Decision, why: str) -> None:
        entry = {
            "t": time.time(), "capability": request.capability.value, "target": request.target,
            "reason": request.reason, "decision": decision.value, "why": why,
        }
        self.audit.append(entry)
        self.audit = self.audit[-500:]
        self.bus.emit("guardian.decision", **entry)

    # -------------------------------------------------------------- views
    def summary(self) -> Dict[str, str]:
        return {cap.value: ("restricted" if cap in self._restricted else self.policy(cap)) for cap in Capability}
