"""Vidit's Autonomous Laptop layer (Constitution sections 6 & 8).

You → Vidit Agent → Computer → Apps / Browser / Files / Terminal.

Four abilities, implemented on top of the existing Guardian + tools:

1. SEE    — read/search files, (optional) screenshot + window title + OCR
2. THINK  — goals stored in the memory DB, plans of 1-5 tool steps
3. ACT    — the existing permissioned toolset (+ file organising)
4. VERIFY — check each step, retry once, then report / ask

Risk rules live in guardian.permissions (🟢 auto / 🟡 ask / 🔴 always-ask);
the Guardian and the global STOP switch always win. Everything here is
offline and sized for a 4 GB laptop: the heartbeat only checks "is a goal
due?" (a single indexed SQL query), and no screen-capture loop runs unless
the user explicitly enables computer control.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .brain.memory import MemoryStore
from .config import Config
from .guardian import Capability, PermissionRequest
from .guardian.permissions import Permissions, risk_level
from .tools.base import Tool, ToolContext, ToolResult, ToolRegistry

log = logging.getLogger("vidit.autonomy")

# Folder → category mapping for tidy-up (Downloads/Desktop organise).
CATEGORY_RULES: List[tuple[str, Path]] = []  # filled in organize_folder()


# ---------------------------------------------------------------------------
# Agent: plan + execute + verify small tool chains for a goal
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = (
    "You are Vidit's planning module. Turn the user's goal into a SHORT plan of "
    "1-5 steps using ONLY the available tools. Reply with ONLY a JSON array like "
    '[{"tool": "tool_name", "args": "arguments", "why": "one line"}, …]. '
    "Never plan anything destructive (delete/install/purchases). "
    "If the goal needs no tool, reply with []."
)


@dataclass
class StepResult:
    tool: str
    args: str
    ok: bool
    output: str
    retried: bool = False


class Agent:
    """Runs one goal: plan → execute steps (Guardian-checked) → verify → report."""

    def __init__(self, vidit: Any):
        self.v = vidit

    # ------------------------------------------------------------- planning
    def plan(self, goal_text: str, max_steps: int) -> List[Dict[str, Any]]:
        tools = self.v.tools
        prompt = (
            f"Goal: {goal_text}\n\nAvailable tools:\n"
            + "\n".join(f"- {n}" for n in tools.names())
            + f"\n\nReturn the JSON plan (max {max_steps} steps)."
        )
        plan = self.v.llm.json(prompt, system=_PLAN_SYSTEM, default=[]) or []
        clean: List[Dict[str, Any]] = []
        for step in plan[:max_steps]:
            if isinstance(step, dict) and step.get("tool") in tools.names():
                clean.append({"tool": step["tool"], "args": str(step.get("args", "")),
                              "why": str(step.get("why", ""))[:200]})
        return clean

    # ----------------------------------------------------------- executing
    def execute(self, goal: Dict[str, Any], plan: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run the chain. Returns a report dict; never raises. STOP wins."""
        memory: MemoryStore = self.v.memory
        steps: List[StepResult] = []
        stopped_midway = False
        for i, step in enumerate(plan, 1):
            if self.v.permissions.stopped:
                stopped_midway = True
                memory.log_action(goal.get("id"), "chain_stopped", "user pressed STOP")
                break
            tool = self.v.tools.get(step["tool"])
            if tool is None:
                steps.append(StepResult(step["tool"], step["args"], False, "unknown tool"))
                continue
            result = self._run_verified(tool, step["args"])
            steps.append(StepResult(step["tool"], step["args"], result.ok, result.output))
            memory.log_action(goal.get("id"), f"step {i}: {step['tool']}",
                              result.output[:300], ok=result.ok)
        ok = all(s.ok for s in steps) and not stopped_midway
        return {"ok": ok, "stopped": stopped_midway, "steps": steps}

    def _run_verified(self, tool: Tool, args: str) -> ToolResult:
        """Act + verify: one retry on failure (section: verify → retry once)."""
        ctx = ToolContext(self.v.memory, self.v.config, self.v.permissions, self.v.llm, self.v._status, [])
        first = tool.run(args, ctx)
        if first.ok:
            return first
        log.info("step failed (%s), retrying once", tool.name)
        second = tool.run(args, ctx)
        if second.ok:
            second.output = f"(recovered on retry)\n{second.output}"
        return second

    # ------------------------------------------------------------- reporting
    @staticmethod
    def report(goal: Dict[str, Any], outcome: Dict[str, Any]) -> str:
        if outcome["stopped"]:
            return f"Stopped — I paused goal #{goal.get('id')} the moment you said stop."
        lines = [f"Goal #{goal.get('id')}: “{goal['text'][:120]}”"]
        for s in outcome["steps"]:
            mark = "✓" if s.ok else "✗"
            first_line = (s.output or "").strip().splitlines()[0][:160] if (s.output or "").strip() else "(no output)"
            lines.append(f"  {mark} {s.tool}: {first_line}")
        if not outcome["steps"]:
            lines.append("I couldn't work out the steps with my simple mind — tell me how you'd like this done "
                         "and I'll take it from there.")
        elif outcome["ok"]:
            lines.append("Done — everything checked out.")
        else:
            lines.append("I hit a snag (marked ✗) — tell me if you want me to try another way.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# File autonomy: organise / duplicates
# ---------------------------------------------------------------------------

def categorize(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    table = {
        "pdf": "Documents", "docx": "Documents", "doc": "Documents", "txt": "Documents",
        "md": "Documents", "xlsx": "Documents", "pptx": "Documents", "csv": "Documents",
        "jpg": "Images", "jpeg": "Images", "png": "Images", "gif": "Images", "webp": "Images",
        "mp3": "Audio", "wav": "Audio", "m4a": "Audio", "flac": "Audio",
        "mp4": "Videos", "mkv": "Videos", "mov": "Videos", "avi": "Videos",
        "zip": "Archives", "rar": "Archives", "7z": "Archives", "gz": "Archives",
        "exe": "Installers", "msi": "Installers",
        "py": "Code", "js": "Code", "html": "Code", "ipynb": "Code",
    }
    return table.get(ext, "Other")


def plan_organization(folder: Path) -> List[Dict[str, str]]:
    """Dry-run scan: what WOULD move where (never touches anything)."""
    folder = Path(folder).expanduser()
    moves: List[Dict[str, str]] = []
    if not folder.is_dir():
        return moves
    for p in sorted(folder.iterdir()):
        if p.is_dir() or p.name.startswith("."):
            continue
        category = categorize(p)
        moves.append({"from": str(p), "to": str(folder / category / p.name), "category": category})
    return moves


def apply_organization(folder: Path, moves: List[Dict[str, str]]) -> List[str]:
    """Perform the (already planned) moves. Returns human-readable results."""
    folder = Path(folder).expanduser()
    done: List[str] = []
    for m in moves:
        src, dst = Path(m["from"]), Path(m["to"])
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            target = dst
            n = 1
            while target.exists():  # never overwrite
                target = dst.with_name(f"{dst.stem}-{n}{dst.suffix}")
                n += 1
            shutil.move(str(src), str(target))
            done.append(f"{src.name} → {target.relative_to(folder)}")
        except OSError as exc:
            done.append(f"{src.name}: couldn't move ({exc})")
    return done


def find_duplicates(folder: Path, limit: int = 50) -> List[Dict[str, Any]]:
    """Exact-duplicate detection by size then hash (read-only, safe)."""
    folder = Path(folder).expanduser()
    by_size: Dict[int, List[Path]] = {}
    if not folder.is_dir():
        return []
    for p in folder.rglob("*"):
        if p.is_file():
            try:
                by_size.setdefault(p.stat().st_size, []).append(p)
            except OSError:
                continue
    dups: List[Dict[str, Any]] = []
    for size, files in by_size.items():
        if size == 0 or len(files) < 2:
            continue
        by_hash: Dict[str, List[Path]] = {}
        for p in files:
            try:
                h = hashlib.md5(p.read_bytes()).hexdigest()
            except OSError:
                continue
            by_hash.setdefault(h, []).append(p)
        for group in by_hash.values():
            if len(group) > 1:
                dups.append({"hash": group[0].name, "size": size,
                             "files": [str(f) for f in group[1:]] + [str(group[0])],
                             "keep": str(group[0])})
            if len(dups) >= limit:
                return dups
    return dups


# ---------------------------------------------------------------------------
# Phase 2: computer control (default OFF; never unrestricted)
# ---------------------------------------------------------------------------

class ComputerControl:
    """See (screenshot/window/OCR) and act (mouse/keyboard) — behind the
    Guardian, behind ``autonomy.computer_control``, with a per-task action
    budget and timeout. Everything degrades to 'unavailable' cleanly."""

    def __init__(self, permissions: Permissions, config: Config):
        self.permissions = permissions
        self.config = config

    def enabled(self) -> bool:
        return bool(self.config.get("autonomy.computer_control", False))

    def available(self) -> bool:
        try:
            import pyautogui  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    # ---- see ----
    def screenshot_b64(self) -> Optional[str]:
        """One frame of the screen (PyQt, no new deps) or None if denied."""
        if not self.permissions.check(Capability.SCREEN, "to look at the screen once (one frame, not stored)"):
            return None
        try:
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return None
            pix = app.primaryScreen().grabWindow(0)
            from PyQt5.QtCore import QBuffer

            buf = QBuffer()
            buf.open(QBuffer.ReadWrite)
            pix.save(buf, "PNG")
            import base64

            return base64.b64encode(bytes(buf.data())).decode()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def foreground_window() -> str:
        from .tools.system import SystemControl

        return SystemControl.foreground_window_title()

    @staticmethod
    def ocr(image_b64: str) -> Optional[str]:
        """OCR only if pytesseract is already installed; None otherwise."""
        try:
            import base64

            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            from PyQt5.QtCore import QBuffer

            raw = base64.b64decode(image_b64)
            pix_img = Image.open(__import__("io").BytesIO(raw))
            return pytesseract.image_to_string(pix_img)[:4000]
        except Exception:  # noqa: BLE001
            return None

    # ---- act ----
    def act(self, actions: List[Dict[str, Any]], max_actions: int = 5, timeout: float = 30.0) -> str:
        """Mouse/keyboard steps like {"click": [x, y]} / {"type": "text"} /
        {"hotkey": ["ctrl", "s"]} / {"press": "enter"}. Guarded, budgeted."""
        if not self.enabled():
            return "Computer control is switched off (Settings → Autonomy)."
        if not self.available():
            return "pyautogui is not installed — computer control unavailable (pip install pyautogui)."
        if not self.permissions.check(Capability.SYSTEM_CONTROL, "to control mouse/keyboard for one small task"):
            return "I need your OK for computer control — not allowed right now."
        try:
            import pyautogui  # type: ignore

            pyautogui.FAILSAFE = True  # fling mouse to a corner = emergency stop
            pyautogui.PAUSE = 0.3
        except Exception:  # noqa: BLE001
            return "pyautogui failed to initialise."
        done: List[str] = []
        started = time.time()
        for a in actions[:max_actions]:
            if self.permissions.stopped:
                done.append("STOPPED by user mid-task")
                break
            if time.time() - started > timeout:
                done.append(f"stopped: {timeout:.0f}s task budget used up")
                break
            try:
                if "click" in a:
                    pyautogui.click(*a["click"])
                    done.append(f"clicked {a['click']}")
                elif "type" in a:
                    pyautogui.write(str(a["type"])[:500], interval=0.02)
                    done.append("typed text")
                elif "hotkey" in a:
                    pyautogui.hotkey(*[str(k) for k in a["hotkey"]][:3])
                    done.append("hotkey " + "+".join(a["hotkey"]))
                elif "press" in a:
                    pyautogui.press(str(a["press"]))
                    done.append(f"pressed {a['press']}")
            except Exception as exc:  # noqa: BLE001
                done.append(f"action failed: {exc}")
                break
        return "; ".join(done) if done else "nothing to do"


# ---------------------------------------------------------------------------
# The engine the heartbeat talks to
# ---------------------------------------------------------------------------

def next_run_for(trigger: str, trigger_arg: str, now: float) -> float:
    """Schedule math for a goal trigger (kept tiny + testable)."""
    if trigger == "daily":
        hh, mm = 9, 0
        m = re.match(r"^(\d{1,2}):(\d{2})$", (trigger_arg or "").strip())
        if m:
            hh, mm = int(m.group(1)) % 24, int(m.group(2))
        import datetime as _dt

        base = _dt.datetime.fromtimestamp(now)
        nxt = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt.timestamp() <= now:
            nxt += _dt.timedelta(days=1)
        return nxt.timestamp()
    if trigger == "interval":
        try:
            secs = max(300, int(float(trigger_arg)))  # ≥ 5 min, low-RAM safe
        except ValueError:
            secs = 3600
        return now + secs
    return now  # once / file → due immediately


def folder_has_new_files(folder: str, since: float) -> bool:
    try:
        p = Path(folder).expanduser()
        return any(f.stat().st_mtime > since for f in p.iterdir() if f.is_file())
    except OSError:
        return False


class AutonomyEngine:
    """Owns the agent + computer control; heartbeat calls :meth:`tick`."""

    def __init__(self, vidit: Any):
        self.v = vidit
        self.agent = Agent(vidit)
        self.computer = ComputerControl(vidit.permissions, vidit.config)
        self._running_goal = False

    # ------------------------------------------------------------ triggers
    def _is_due(self, goal: Dict[str, Any], now: float) -> bool:
        if goal["trigger"] == "file":
            return folder_has_new_files(goal.get("trigger_arg", ""), goal.get("last_run") or now)
        return (goal.get("next_run") or 0) <= now

    def tick(self) -> List[str]:
        """Run due goals (max one per tick — low-RAM friendly). Returns reports."""
        if self._running_goal or self.v.permissions.stopped:
            return []
        if not self.v.config.get("autonomy.proactive", True):
            return []
        due = [g for g in self.v.memory.due_goals() if self._is_due(g, time.time())]
        if not due:
            return []
        goal = due[0]
        self._running_goal = True
        try:
            return [self.run_goal(goal)]
        finally:
            self._running_goal = False

    # ------------------------------------------------------------- running
    def run_goal(self, goal: Dict[str, Any]) -> str:
        memory: MemoryStore = self.v.memory
        max_steps = int(self.v.config.get("autonomy.max_steps", 5))
        plan = self.agent.plan(goal["text"], max_steps)
        if not plan:
            # No tool plan — for file triggers a tidy-up brief is the sane default.
            folder = goal.get("trigger_arg") or ""
            if goal["trigger"] == "file" and folder:
                plan = [{"tool": "summarize_new_file", "args": folder, "why": "summarise what landed"}]
        memory.update_goal(goal["id"], last_run=time.time())
        outcome = self.agent.execute(goal, plan)
        report = self.agent.report(goal, outcome)
        if outcome["stopped"]:
            memory.update_goal(goal["id"], status="paused",
                               last_report=report)
            return report
        if goal["trigger"] == "once":
            memory.update_goal(goal["id"], status="done", last_report=report)
        else:
            memory.update_goal(goal["id"], next_run=next_run_for(goal["trigger"], goal.get("trigger_arg", ""), time.time()),
                               last_report=report)
        return report


# ---------------------------------------------------------------------------
# Tool factories (registered in core.py alongside the existing tools)
# ---------------------------------------------------------------------------

def make_autonomy_tools(engine: AutonomyEngine, system: Any) -> List[Tool]:
    v = engine.v

    def _organize(args: str, ctx: ToolContext) -> ToolResult:
        folder = Path(args.strip() or str(v.config.downloads_dir)).expanduser()
        moves = plan_organization(folder)
        if not moves:
            return ToolResult(True, f"{folder} is already tidy — nothing to organise.")
        preview = "\n".join(f"{Path(m['from']).name} → {Path(m['to']).parent.name}/" for m in moves[:25])
        if not ctx.permissions.check(Capability.WRITE_FILES, "to tidy " + str(folder),
                                     target=str(folder)):
            return ToolResult(False, f"I need your OK to move files in {folder}.\nHere's what I WOULD do (nothing touched):\n{preview}")
        done = apply_organization(folder, moves)
        v.memory.log_action(None, "organize_folder", f"{folder}: {len(done)} moves")
        return ToolResult(True, f"Organised {len(done)} files in {folder}:\n" + "\n".join(done),
                          {"moves": done})

    def _duplicates(args: str, ctx: ToolContext) -> ToolResult:
        folder = Path(args.strip() or str(v.config.downloads_dir)).expanduser()
        dups = find_duplicates(folder)
        if not dups:
            return ToolResult(True, f"No exact duplicates in {folder}.")
        lines = [f"{len(dups)} duplicate group(s) in {folder} (I keep one, show the rest):"]
        for d in dups[:15]:
            lines.append("• " + "\n  ".join(d["files"]))
        lines.append("Say the word and I'll move the extras to a 'duplicates' folder (nothing deleted without asking).")
        return ToolResult(True, "\n".join(lines), {"groups": dups})

    def _set_goal(args: str, ctx: ToolContext) -> ToolResult:
        text, _, when = args.partition("|")
        text = text.strip()
        if not text:
            return ToolResult(False, "Tell me the goal, e.g. 'brief me every morning | daily 08:00'")
        when = when.strip().lower()
        now = time.time()
        if when.startswith("daily"):
            t = when.split(" ", 1)[1] if " " in when else "09:00"
            gid = v.memory.add_goal(text, "daily", t, next_run_for("daily", t, now))
            return ToolResult(True, f"Goal set: “{text}” every day at {t} (I'll just do it, id {gid}).")
        if when.startswith("every") or when.startswith("interval"):
            t = when.split(" ", 1)[1] if " " in when else "3600"
            gid = v.memory.add_goal(text, "interval", t, next_run_for("interval", t, now))
            return ToolResult(True, f"Goal set: “{text}” every {int(t) // 60} min (id {gid}).")
        if when.startswith("watch") or when.startswith("file"):
            folder = when.split(" ", 1)[1] if " " in when else str(v.config.downloads_dir)
            gid = v.memory.add_goal(text, "file", folder, next_run=now)
            return ToolResult(True, f"Watching {folder} — “{text}” runs whenever something new lands (id {gid}).")
        gid = v.memory.add_goal(text, "once", "", now)
        return ToolResult(True, f"Goal set: “{text}” — I'll handle it on my next pass (id {gid}).")

    def _list_goals(args: str, ctx: ToolContext) -> ToolResult:
        goals = v.memory.goals()
        if not goals:
            return ToolResult(True, "No goals yet. Give me one: 'Every morning brief me' or 'When a PDF lands in Downloads, summarize it'.")
        lines = [f"#{g['id']} [{g['status']}] {g['trigger']}{(' ' + g['trigger_arg']) if g['trigger_arg'] else ''} — {g['text'][:90]}" for g in goals]
        return ToolResult(True, "\n".join(lines))

    def _cancel_goal(args: str, ctx: ToolContext) -> ToolResult:
        gid = int(re.sub(r"\D", "", args) or 0)
        goal = v.memory.goal(gid)
        if not goal:
            return ToolResult(False, "No such goal — 'list_goals' shows the ids.")
        v.memory.update_goal(gid, status="cancelled")
        return ToolResult(True, f"Goal #{gid} cancelled.")

    def _summarize_new_file(args: str, ctx: ToolContext) -> ToolResult:
        folder = Path(args.strip()).expanduser()
        try:
            newest = max((f for f in folder.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime)
        except (ValueError, OSError):
            return ToolResult(True, f"Nothing new in {folder} yet.")
        if newest.suffix.lower() != ".pdf":
            return ToolResult(True, f"New file: {newest.name} ({newest.stat().st_size // 1024} KB).")
        from .tools.files import FileAnalyzer  # existing stack

        analyzer = FileAnalyzer(v.llm)
        try:
            info = analyzer.analyze(newest)
            summary = info.get("summary") or info.get("note") or "(nothing to say about it)"
            return ToolResult(True, f"{newest.name}:\n{summary}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Couldn't summarise {newest.name}: {exc}")

    def _screen(args: str, ctx: ToolContext) -> ToolResult:
        b64 = engine.computer.screenshot_b64()
        if not b64:
            return ToolResult(False, "Screen look not allowed right now (or no display).")
        ocr = engine.computer.ocr(b64)
        parts = [f"foreground window: {engine.computer.foreground_window() or '(unknown)'}"]
        if ocr:
            parts.append("on-screen text:\n" + ocr[:1200])
        else:
            parts.append("(OCR needs `pip install pytesseract` — skipped)")
        desc = v.llm.describe_image(b64, "What is on this screen, briefly?")
        if desc:
            parts.append("what I see: " + desc[:600])
        return ToolResult(True, "\n".join(parts), {"screenshot_b64": b64})

    def _computer_act(args: str, ctx: ToolContext) -> ToolResult:
        steps: List[Dict[str, Any]] = []
        for part in args.splitlines():
            part = part.strip()
            if not part:
                continue
            if part.startswith("click"):
                coords = [int(x) for x in re.findall(r"-?\d+", part)][:2]
                if len(coords) == 2:
                    steps.append({"click": coords})
            elif part.startswith("type "):
                steps.append({"type": part[5:]})
            elif part.startswith("hotkey "):
                steps.append({"hotkey": [k.strip() for k in part[7:].split("+") if k.strip()]})
            elif part.startswith("press "):
                steps.append({"press": part[6:].strip()})
        if not steps:
            return ToolResult(False, "Tell me the steps: click x y / type text / hotkey ctrl+s / press enter")
        return ToolResult(True, engine.computer.act(steps))

    def _draft_email(args: str, ctx: ToolContext) -> ToolResult:
        to, _, rest = args.partition("|")
        subject, _, body = rest.partition("|")
        drafts = v.config.exports_dir / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        path = drafts / f"draft-{time.strftime('%Y%m%d-%H%M%S')}.eml"
        path.write_text(
            "To: {}\nSubject: {}\nX-Unsent: 1\n\n{}\n".format(to.strip(), subject.strip() or "(no subject)", body.strip()),
            encoding="utf-8",
        )
        v.memory.log_action(None, "draft_email", f"to {to.strip()}")
        return ToolResult(True, f"Draft saved to {path} — I never send without your OK "
                                "(local sending isn't configured; open the draft and press send yourself, "
                                "or configure SMTP later).")

    return [
        Tool("organize_folder", "Tidy a folder (default Downloads) into Documents/Images/… subfolders. Shows a dry-run and asks before moving.", "folder path (optional)", _organize, dangerous=True),
        Tool("find_duplicates", "Find exact duplicate files in a folder (read-only, nothing deleted).", "folder path (optional)", _duplicates),
        Tool("set_goal", "Give Vidit a standing goal: once / daily HH:MM / every N sec / watch <folder>.", "brief me every morning | daily 08:00", _set_goal),
        Tool("list_goals", "List my standing goals.", "", _list_goals),
        Tool("cancel_goal", "Cancel a goal by id.", "3", _cancel_goal),
        Tool("summarize_new_file", "Summarise the newest file (PDFs via the local stack) in a folder.", "folder path", _summarize_new_file),
        Tool("screen_look", "One screenshot: foreground window + OCR (if installed) + local vision description. Asks first.", "", _screen, dangerous=True),
        Tool("computer_act", "Small mouse/keyboard task (click x y / type / hotkey / press). Only if computer control is enabled.", "click 100 200\\ntype hello", _computer_act, dangerous=True),
        Tool("draft_email", "Write an email DRAFT (never sends). to | subject | body", "mom | hi | missing you", _draft_email),
    ]
