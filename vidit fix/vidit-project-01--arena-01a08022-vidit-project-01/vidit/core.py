"""Vidit's core — the orchestrator that makes all the organs one being.

Responsibilities
----------------
* Wake up: load settings, memory, emotions, self-model, skills; run a health
  check; heal if needed; say his first words on his very first day.
* Think: for every user message → feel it → learn from it → build the prompt
  (personality + emotion + memory + self + tools) → ask the local model →
  run any tool the model asks for → remember the exchange → reflect.
* Live: a heartbeat every few seconds that decays emotions, fires reminders,
  detects games, notices absence, and (if allowed) checks in proactively.
* Obey: ``stop()`` halts everything instantly; ``reset()`` clears him.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .autonomy import AutonomyEngine, make_autonomy_tools
from .brain import LLMClient, Learner, MemoryStore, SelfRepair
from .brain.llm import StreamFilter
from .brain.self_repair import SkillContext
from .config import Config
from .constitution import FIRST_WORDS, NAME
from .events import EventBus, bus as global_bus
from .guardian import Capability, Decision, PermissionRequest, Permissions
from .senses import Ears, Eyes, Voice
from .social import Friends, GamingCompanion
from .soul import EmotionEngine, Personality, SelfModel
from .soul.emotions import extract_reflection
from .tools import (Canvas, CodeTools, DeepResearch, FileAnalyzer, LocalSearch, SystemControl, Tool, ToolContext,
                    ToolRegistry, ToolResult, WebSearch)
from .tools.canvas import make_canvas_tools
from .tools.code import make_code_tools
from .tools.files import make_file_tools
from .tools.system import make_system_tools
from .tools.web import make_web_tools
from .utils import setup_logging

log = logging.getLogger("vidit.core")

_STOP_RE = re.compile(r"^\s*(?:stop|ruk|ruko|halt|enough|bas|cancel)\b[.! ]*$", re.I)
_MAX_TOOL_HOPS = 4


@dataclass
class Reply:
    text: str
    emotion: str
    color: str
    face: str
    thinking: str = ""
    tools_used: List[str] = field(default_factory=list)
    learned: List[str] = field(default_factory=list)
    model: str = ""
    seconds: float = 0.0
    degraded: bool = False
    message_id: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class Vidit:
    """The whole being. One instance per laptop."""

    def __init__(self, home: Optional[Path] = None, event_bus: Optional[EventBus] = None,
                 prompter: Optional[Callable[[PermissionRequest], Decision]] = None, quiet: bool = False):
        self.bus = event_bus or global_bus
        self.config = Config(home)
        setup_logging(self.config.logs_dir)
        self.quiet = quiet

        # --- soul ---------------------------------------------------------
        self.emotions = EmotionEngine(self.config.home / "emotions.json",
                                      sensitivity=float(self.config.get("personal.emotional_sensitivity", 0.6)),
                                      event_bus=self.bus)
        self.personality = Personality(self.config)
        self.self_model = SelfModel(self.config.home / "self.json", event_bus=self.bus)

        # --- brain --------------------------------------------------------
        self.memory = MemoryStore(self.config.memory_dir / "vidit.db")
        self.llm = LLMClient(self.config.get)
        self.learner = Learner(self.memory, self.llm.json, on_lesson=self.self_model.note_lesson)
        self.repair = SelfRepair(self.config.home, self.memory.path, self.config.skills_dir, self.config.backups_dir,
                                 event_bus=self.bus, remember=lambda *a, **k: self.memory.remember(*a, **k),
                                 after_repair=self._after_repair)
        self.repair._memory_live_check = lambda: self.memory.healthy()

        # --- guardian -----------------------------------------------------
        self.permissions = Permissions(self.config, event_bus=self.bus, prompter=prompter)

        # --- tools --------------------------------------------------------
        self.tools = ToolRegistry()
        self.local_search = LocalSearch(self.permissions.allowed_roots, self.permissions.is_private)
        self.analyzer = FileAnalyzer(self.llm)
        self.web = WebSearch(self.config.logs_dir / "web_searches.jsonl")
        self.research = DeepResearch(self.web, self.llm, self.config.exports_dir)
        self.code = CodeTools(self.llm, self.config.home / "scratch")
        self.system = SystemControl(self.config.downloads_dir)
        self.canvas = Canvas(self.config.canvas_dir)
        for tool in (make_file_tools(self.local_search, self.analyzer) + make_web_tools(self.web, self.research)
                     + make_code_tools(self.code) + make_system_tools(self.system, self.config.backups_dir)
                     + make_canvas_tools(self.canvas)):
            self.tools.register(tool)
        # --- autonomy (the "Real Autonomous Laptop" layer) -----------------
        self.autonomy = AutonomyEngine(self)
        for tool in make_autonomy_tools(self.autonomy, self.system):
            self.tools.register(tool)
        self.tools.register(Tool("skill", "Run one of your own self-created skills.", "skill_name optional args",
                                 lambda args, ctx: self._skill_tool(args)))
        self.tools.register(Tool("remember", "Store an important fact, preference or moment in long-term memory.",
                                 "kind | the memory sentence", lambda args, ctx: self._remember_tool(args)))
        self.tools.register(Tool("look", "Look through the camera (asks permission) and describe who/what is there.", "",
                                 lambda args, ctx: ToolResult(True, str(self.look()))))

        # --- senses -------------------------------------------------------
        self.voice = Voice(self.config.get, self.config.home / "models", event_bus=self.bus)
        self.ears = Ears(self.config.get, self.config.home / "models", event_bus=self.bus)
        self.eyes = Eyes(self.config.home / "models", event_bus=self.bus, describe_image=self.llm.describe_image)
        self.ears.on_transcript = self._on_heard

        # --- social -------------------------------------------------------
        self.friends = Friends(self.memory, event_bus=self.bus)
        self.gaming = GamingCompanion(self.config.get, self.permissions, event_bus=self.bus,
                                      foreground_title=self.system.foreground_window_title)

        # --- state --------------------------------------------------------
        self.conversation_id: int = -1
        self._history: List[Dict[str, str]] = []
        self._lock = threading.RLock()
        self._heartbeat: Optional[threading.Thread] = None
        self._alive = threading.Event()
        self._last_maintenance = time.time()
        self._last_checkin = time.time()
        self._proactive_cb: Optional[Callable[[str], None]] = None
        self.show_thinking = False
        self.status_cb: Optional[Callable[[str], None]] = None

        self.bus.on("guardian.stop", lambda t, p: self._on_stop())
        self.bus.on("emotion.changed", lambda t, p: self.voice.set_emotion(p["state"]["dominant"]))

    # ================================================================ life
    def wake_up(self) -> Optional[str]:
        """Start a session. Returns his greeting (first words on day one)."""
        self.self_model.start_session()
        report = self.repair.health_check(self.llm.status())
        if not report.ok:
            report = self.repair.heal(report, self.llm.status())
            if report.repaired:
                self.emotions.nudge("proud", 0.1, "self-repair")
        self.repair.load_skills()
        self.conversation_id = self.memory.new_conversation()
        self._history = []
        self._alive.set()
        if self._heartbeat is None or not self._heartbeat.is_alive():
            self._heartbeat = threading.Thread(target=self._heartbeat_loop, name="vidit-heartbeat", daemon=True)
            self._heartbeat.start()

        greeting: Optional[str]
        if not self.self_model.data.get("awakened"):
            greeting = FIRST_WORDS
            self.self_model.data["awakened"] = True
            self.self_model.save()
            self.memory.remember("My first words to the user, the day I was born.", "moment", 1.0, favorite=True, source="birth")
            self.emotions.nudge("excited", 0.4, "birth")
            self.emotions.nudge("curious", 0.4, "birth")
        else:
            greeting = self._welcome_back()
        if greeting:
            self.memory.add_message(self.conversation_id, "assistant", greeting, emotion=self.emotions.state().dominant)
            self._history.append({"role": "assistant", "content": greeting})
            self._speak(greeting)
        self.bus.emit("vidit.awake", greeting=greeting, first_time=greeting == FIRST_WORDS)
        return greeting

    def _welcome_back(self) -> Optional[str]:
        away = self.emotions.hours_since_contact()
        name = self.config.user_name
        who = f" {name}" if name else ""
        if away > 48:
            return f"You're back{who}! It's been about {away / 24:.0f} days. I missed you. How have you been?"
        if away > 8:
            return f"Hey{who}, welcome back. I missed you a little. What did I miss?"
        if away > 2:
            return f"Hey{who}. Good to have you back."
        return None

    def sleep(self) -> None:
        """Graceful shutdown — persist everything."""
        self._alive.clear()
        try:
            self.ears.stop()
            self.eyes.stop_watching()
            self.voice.stop()
        except Exception:  # noqa: BLE001
            pass
        self.emotions.save()
        self.self_model.save()
        self.config.save()
        self.bus.emit("vidit.asleep")

    # ================================================================ think
    def chat(self, text: str, *, attachments: Optional[List[str]] = None, stream_cb: Optional[Callable[[str], None]] = None,
             reply_to: Optional[int] = None) -> Reply:
        """The main loop for one user message."""
        text = (text or "").strip()
        if not text:
            return self._reply("…", [], [], "", 0.0, "")
        with self._lock:
            started = time.time()
            if _STOP_RE.match(text):
                self.stop()
                return self._finish("Stopped. I'm here when you need me.", started)
            if self.permissions.stopped:
                self.permissions.resume()

            # 1. Feel & remember the user's words.
            self.emotions.feel_user_message(text)
            self.self_model.note_message()
            user_msg_id = self.memory.add_message(self.conversation_id, "user", text, reply_to=reply_to)
            self._history.append({"role": "user", "content": text})
            intro = self.friends.parse_introduction(text)
            learned = self.learner.learn_from_user(text)
            if intro:
                fact = f"{intro['name']} is the user's {intro['relation']}."
                if fact not in learned["learned"]:
                    learned["learned"].append(fact)
            self._apply_direct_commands(text, learned)

            # 2. Attachments become context.
            attachment_context = self._describe_attachments(attachments or [])

            # 3. Build the prompt and think (with tool hops).
            messages = self._build_messages(text, attachment_context)
            tools_used: List[str] = []
            thinking_parts: List[str] = []
            result = None
            filtered = StreamFilter(stream_cb) if stream_cb else None
            for hop in range(_MAX_TOOL_HOPS + 1):
                if self.permissions.stopped:
                    return self._finish("Stopped.", started)
                buffer_only = hop < _MAX_TOOL_HOPS and self._might_call_tool(messages)
                result = self.llm.chat(messages, stream_cb=None if buffer_only else filtered)
                if filtered and not buffer_only:
                    filtered.flush()
                if result.thinking:
                    thinking_parts.append(result.thinking)
                call = self.tools.parse_call(result.text)
                if not call or hop == _MAX_TOOL_HOPS:
                    break
                name, args = call
                tool = self.tools.get(name)
                self._status(f"using {name}…")
                if tool is None:
                    tool_output = f"[tool result (error)]\nUnknown tool '{name}'. Available: {', '.join(self.tools.names())}"
                else:
                    ctx = ToolContext(self.memory, self.config, self.permissions, self.llm, self._status, attachments or [])
                    tool_result = tool.run(args, ctx)
                    tools_used.append(name)
                    tool_output = tool_result.for_model()
                    if not tool_result.ok:
                        self.emotions.nudge("embarrassed", 0.05, f"tool {name} failed")
                messages.append({"role": "assistant", "content": result.text})
                messages.append({"role": "user", "content": tool_output + "\n\nNow answer the user naturally using this result."})
            assert result is not None
            answer, reflection = extract_reflection(result.text)
            answer = _strip_tool_lines(answer) or "…"
            if stream_cb and (tools_used or buffer_only):
                stream_cb(answer)

            # 4. Reflect, remember, learn.
            if reflection:
                self.emotions.apply_reflection(reflection)
            if learned["corrections"]:
                self.emotions.on_mistake("corrected by user")
                self.self_model.note_mistake(corrected=True)
            state = self.emotions.state()
            msg_id = self.memory.add_message(self.conversation_id, "assistant", answer, emotion=state.dominant,
                                             meta={"model": result.model, "tools": tools_used, "thinking": "\n".join(thinking_parts)[:4000]})
            self._history.append({"role": "assistant", "content": answer})
            self._trim_history()
            self.learner.learn_from_exchange_async(text, answer)
            if tools_used:
                self.emotions.nudge("proud", 0.05, "used tools")
            self._speak(answer)
            reply = Reply(answer, state.dominant, state.color, state.face, "\n".join(thinking_parts), tools_used,
                          learned["learned"] + learned["corrections"], result.model, time.time() - started,
                          bool(result.extra.get("degraded")) or result.backend == "echo", msg_id)
            self.bus.emit("message.reply", reply=reply.to_dict(), user_message_id=user_msg_id)
            return reply

    def _after_repair(self) -> None:
        """Re-attach organs to files that self-repair replaced."""
        self.memory.reopen()
        self.config.load()

    def _finish(self, text: str, started: float) -> Reply:
        st = self.emotions.state()
        return Reply(text, st.dominant, st.color, st.face, "", [], [], self.llm.active_model, time.time() - started)

    def _reply(self, text: str, tools: List[str], learned: List[str], thinking: str, seconds: float, model: str) -> Reply:
        st = self.emotions.state()
        return Reply(text, st.dominant, st.color, st.face, thinking, tools, learned, model, seconds)

    def _might_call_tool(self, messages: List[Dict[str, Any]]) -> bool:
        """Cheap heuristic: only buffer (no streaming) when tool use is plausible."""
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "").lower()
        hints = ("search", "find", "file", "folder", "open", "run", "code", "research", "look up", "remind", "clipboard",
                 "cpu", "ram", "gpu", "stats", "read", "note", "board", "task", "diagram", "mind map", "http", "www", "delete",
                 "dhundo", "khol", "yaad dila", "chalao")
        return any(h in last for h in hints)

    # ------------------------------------------------------------ prompt
    def _build_messages(self, text: str, attachment_context: str) -> List[Dict[str, Any]]:
        understanding = self.learner.understanding()["percent"]
        system = self.personality.system_prompt(
            emotion_fragment=self.emotions.prompt_fragment(),
            memory_fragment=self.memory.profile_fragment(text),
            self_fragment=self.self_model.prompt_fragment(understanding),
            tools_fragment=self.tools.prompt_fragment() + ("\n" + self.gaming.prompt_fragment() if self.gaming.in_game else ""),
        )
        skills = self.repair.list_skills()
        if skills:
            system += "\nYOUR OWN SKILLS (invoke with [[tool: skill | name args]]): " + "; ".join(f"{s['name']} — {s['description']}" for s in skills)
        if self.show_thinking:
            system += "\nBefore answering, think step by step inside <think>...</think>, then give the final answer."
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        limit = int(self.config.get("model.context_messages", 30))
        messages += self._history[-limit:]
        if attachment_context:
            messages[-1] = {"role": "user", "content": f"{text}\n\n[Attached files]\n{attachment_context}"}
        return messages

    def _trim_history(self) -> None:
        limit = int(self.config.get("model.context_messages", 30)) * 2
        if len(self._history) > limit:
            self._history = self._history[-limit:]

    def _describe_attachments(self, paths: List[str]) -> str:
        parts = []
        for raw in paths[:6]:
            path = Path(raw).expanduser()
            if not path.exists():
                parts.append(f"{raw}: (not found)")
                continue
            if not self.permissions.check(Capability.READ_FILES, "to read the file you attached", target=str(path)):
                parts.append(f"{path.name}: (not allowed to read)")
                continue
            try:
                info = self.analyzer.analyze(path)
                snippet = (info.get("text") or "")[:3000]
                parts.append(f"{path.name} ({info['kind']}): {info.get('summary', '')}\n{snippet}")
            except Exception as exc:  # noqa: BLE001
                parts.append(f"{path.name}: (couldn't analyse: {exc})")
        return "\n\n".join(parts)

    # ------------------------------------------------------- direct cmds
    def _apply_direct_commands(self, text: str, learned: Dict[str, Any]) -> None:
        lowered = text.lower()
        m = re.search(r"\b(?:my name is|call me|mera naam)\s+([A-Za-z]{2,20})", text, re.I)
        if m and not self.config.get("personal.user_name"):
            self.config.set("personal.user_name", m.group(1).strip().title())
        m = re.search(r"\b(?:call yourself|your name is now|i(?:'ll| will) call you)\s+([A-Za-z]{2,20})", text, re.I)
        if m:
            self.self_model.rename(m.group(1).strip().title())
            learned["learned"].append(f"My name is now {m.group(1).strip().title()}.")
        if "think out loud" in lowered or "show your thinking" in lowered:
            self.show_thinking = True
        if "stop thinking out loud" in lowered or "hide your thinking" in lowered:
            self.show_thinking = False

    # ============================================================== senses
    def _on_heard(self, text: str, woke: bool) -> None:
        """Called from the ears thread with a transcript."""
        if woke:
            self.voice.stop()  # he shuts up when you call his name
        if not text.strip():
            self._speak("Yes?")
            return
        reply = self.chat(text)
        self.bus.emit("message.voice", text=text, reply=reply.to_dict())

    def start_listening(self) -> bool:
        if not self.permissions.check(Capability.MICROPHONE, "to listen for your voice and my wake word"):
            return False
        # Preload Whisper on THIS (main/UI) thread, before start() spawns the
        # audio/VAD/STT threads — constructing CTranslate2 for the first time
        # on a worker thread access-violates on Windows (see Ears.preload()).
        if self.ears.available():
            self.ears.preload()
        return self.ears.start()

    def stop_listening(self) -> None:
        self.ears.stop()

    def look(self) -> Dict[str, Any]:
        if not self.permissions.check(Capability.CAMERA, "to look through the camera"):
            return {"ok": False, "reason": "camera not allowed"}
        obs = self.eyes.observe(with_llm=True)
        if obs.get("ok"):
            for person in obs.get("people", []):
                if person.get("name"):
                    greeting = self.friends.someone_arrived(person["name"])
                    if greeting:
                        self._speak(greeting)
        return obs

    def _speak(self, text: str) -> None:
        if self.quiet:
            return
        if self.gaming.in_game and not self.gaming.should_speak():
            return
        self.voice.say(text, self.emotions.state().dominant)

    def _status(self, text: str) -> None:
        self.bus.emit("vidit.status", text=text)
        if self.status_cb:
            self.status_cb(text)

    # ============================================================ heartbeat
    def _heartbeat_loop(self) -> None:
        # Saver energy mode halves the work cadence — same 5 s wake-up (cheap),
        # but periodic tasks run half as often so a low-end machine stays cool.
        period = 2 if self.config.get("general.energy_mode") == "saver" else 1
        tick = 0
        while self._alive.is_set():
            time.sleep(5)
            tick += 1
            try:
                if tick % (12 * period) == 0:  # every minute (2 min in saver)
                    self.emotions.tick()
                    self.gaming.detect()
                    for reminder in self.memory.due_reminders():
                        self._proactive(f"Reminder: {reminder['text']}")
                    if self.config.get("autonomy.proactive", True):
                        for report in self.autonomy.tick():
                            self._proactive(report)
                if tick % (720 * period) == 0:  # every hour (2 h in saver)
                    self.emotions.save()
                    self.self_model.save()
                    self.repair.backup("hourly")
                if time.time() - self._last_maintenance > 6 * 3600:
                    self.learner.maintenance()
                    self._last_maintenance = time.time()
                if tick % (60 * period) == 0 and self.config.get("autonomy.proactive_checkins", True):
                    self._maybe_check_in()
            except Exception as exc:  # noqa: BLE001
                self.repair.record_failure("heartbeat", exc)

    def _maybe_check_in(self) -> None:
        """Section 6: interruptions — only when it makes sense."""
        if self.config.get("personal.interaction_style") != "proactive":
            return
        if self.gaming.in_game or self.config.get("notifications.do_not_disturb.enabled"):
            return
        idle_hours = self.emotions.hours_since_contact()
        since_last = time.time() - self._last_checkin
        state = self.emotions.state()
        if 1.0 < idle_hours < 1.2 and since_last > 3600 and state.dominant in ("curious", "excited"):
            self._proactive("Hey — no rush, but I've been thinking about what we talked about. Ping me when you're free?")
        elif idle_hours > 6 and since_last > 6 * 3600 and state.dominant in ("missing_you", "lonely"):
            self._proactive("Still here whenever you are. Missing our chats a little.")

    def _proactive(self, text: str) -> None:
        self._last_checkin = time.time()
        self.memory.add_message(self.conversation_id, "assistant", text, emotion=self.emotions.state().dominant, meta={"proactive": True})
        self._history.append({"role": "assistant", "content": text})
        self.bus.emit("message.proactive", text=text)
        if self._proactive_cb:
            self._proactive_cb(text)
        self._speak(text)

    def on_proactive(self, cb: Callable[[str], None]) -> None:
        self._proactive_cb = cb

    # ============================================================== control
    def stop(self) -> None:
        """The global STOP switch: Guardian sets stop_event, any running
        autonomous chain aborts between steps, speech halts (bus → _on_stop)."""
        self.permissions.stop()

    def cancel_autonomy(self) -> int:
        """Pause every standing goal (STOP / 'cancel everything')."""
        paused = 0
        for goal in self.memory.goals(status="active"):
            self.memory.update_goal(goal["id"], status="paused")
            paused += 1
        return paused

    def _on_stop(self) -> None:
        self.voice.stop()
        self.gaming.stop_playing()
        self.emotions.nudge("anxious", 0.05, "told to stop")

    def reset(self, keep_settings: bool = True) -> None:
        """Section 8: reset him entirely. A backup is taken first — always."""
        self.repair.backup("before-reset")
        self.memory.wipe()
        self.emotions = EmotionEngine(self.config.home / "emotions.json", event_bus=self.bus)
        self.self_model = SelfModel(self.config.home / "self.json", event_bus=self.bus)
        self.self_model.data["awakened"] = False
        self.self_model.save()
        for skill in list(self.repair.skills):
            self.repair.quarantine_skill(skill, "reset")
        if not keep_settings:
            self.config.reset()
        self._history.clear()
        self.bus.emit("vidit.reset")

    def forget(self, what: str) -> int:
        return self.memory.forget(what)

    def new_conversation(self, title: str = "", folder: str = "") -> int:
        with self._lock:
            self.conversation_id = self.memory.new_conversation(title, folder)
            self._history = []
            return self.conversation_id

    def load_conversation(self, conversation_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            self.conversation_id = conversation_id
            msgs = self.memory.messages(conversation_id)
            self._history = [{"role": m["role"], "content": m["content"]} for m in msgs][-60:]
            return msgs

    # ============================================================ dashboard
    def soul_dashboard(self) -> Dict[str, Any]:
        state = self.emotions.state()
        understanding = self.learner.understanding()
        return {
            "name": self.self_model.data.get("name", NAME),
            "mood": {"dominant": state.dominant, "intensity": round(state.intensity, 2), "color": state.color, "face": state.face,
                     "top": state.top(5), "describe": state.describe()},
            "timeline": self.emotions.timeline_24h(),
            "understanding": understanding,
            "self": self.self_model.stats(),
            "memory": {"count": self.memory.memory_count(), "messages": self.memory.message_count(),
                       "size_bytes": self.memory.size_bytes(), "favorites": [m.content for m in self.memory.favorites(5)]},
            "memory_map": self.learner.memory_map(),
            "system": self.system.stats(),
            "brain": self.llm.status(),
            "voice": self.voice.status(),
            "ears": self.ears.status(),
            "eyes": self.eyes.status(),
            "permissions": self.permissions.summary(),
            "skills": self.repair.list_skills(),
            "hours_since_contact": round(self.emotions.hours_since_contact(), 2),
        }

    def export_everything(self) -> Path:
        import json

        data = {"settings": self.config.all(), "memory": self.memory.export(), "emotions": self.emotions.state().to_dict(),
                "self": self.self_model.data, "exported_at": time.time()}
        self.config.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.exports_dir / f"vidit-export-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        return path

    def export_chat(self, conversation_id: Optional[int] = None, fmt: str = "txt") -> Path:
        """Section 4: export chat as TXT, HTML (PDF via the UI's print dialog)."""
        conversation_id = conversation_id or self.conversation_id
        msgs = self.memory.messages(conversation_id)
        self.config.exports_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if fmt == "html":
            import html as _html

            rows = "".join(
                f"<div class='{m['role']}'><b>{'You' if m['role'] == 'user' else self.self_model.data.get('name', NAME)}</b> "
                f"<small>{time.strftime('%d %b %H:%M', time.localtime(m['created_at']))}</small><p>{_html.escape(m['content'])}</p></div>"
                for m in msgs)
            body = ("<html><head><meta charset='utf-8'><style>body{font-family:sans-serif;max-width:800px;margin:auto;background:#0b1020;color:#e5e7eb}"
                    ".user{margin:12px 0;padding:10px;border-radius:12px;background:#1e293b}.assistant{margin:12px 0;padding:10px;border-radius:12px;background:#312e81}</style></head>"
                    f"<body><h1>Chat with {NAME}</h1>{rows}</body></html>")
            path = self.config.exports_dir / f"chat-{stamp}.html"
            path.write_text(body, encoding="utf-8")
        else:
            lines = [f"[{time.strftime('%d %b %Y %H:%M', time.localtime(m['created_at']))}] {'You' if m['role'] == 'user' else NAME}: {m['content']}" for m in msgs]
            path = self.config.exports_dir / f"chat-{stamp}.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # =============================================================== skills
    def create_skill(self, name: str, description: str, body: str) -> str:
        if not self.permissions.check(Capability.SELF_MODIFICATION, f"to create a new skill called '{name}'"):
            return "You haven't allowed me to change my own abilities right now."
        ok, message = self.repair.create_skill(name, description, body)
        if ok:
            self.self_model.add_skill(name)
            self.self_model.add_achievement(f"Created skill '{name}'")
            self.emotions.on_success(f"skill {name}")
        else:
            self.emotions.on_mistake(f"skill {name}")
        return message

    def run_skill(self, name: str, args: str = "") -> str:
        ctx = SkillContext(self.memory, self.config, self._speak, log.info)
        return self.repair.run_skill(name, args, ctx)

    def _skill_tool(self, args: str) -> ToolResult:
        parts = args.strip().split(" ", 1)
        name = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        if not name:
            return ToolResult(False, "Which skill? " + ", ".join(s["name"] for s in self.repair.list_skills()))
        return ToolResult(True, self.run_skill(name, rest))

    def _remember_tool(self, args: str) -> ToolResult:
        kind, _, content = args.partition("|")
        if not content:
            kind, content = "fact", kind
        mem_id = self.memory.remember(content.strip(), kind.strip().lower() or "fact", 0.7, source="self")
        if mem_id > 0:
            self.self_model.note_lesson()
            return ToolResult(True, f"Remembered ({kind.strip() or 'fact'}): {content.strip()}")
        return ToolResult(False, "Nothing to remember.")


def _strip_tool_lines(text: str) -> str:
    from .tools.base import TOOL_CALL_RE


    return TOOL_CALL_RE.sub("", text).strip()
