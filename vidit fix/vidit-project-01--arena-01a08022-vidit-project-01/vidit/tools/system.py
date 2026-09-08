"""System control (Constitution sections 6 & 8): stats, apps, clipboard, reminders.

Everything that touches the machine goes through the Guardian. Destructive
actions make a backup first where that makes sense ("he makes a backup
first and then asks later").
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..guardian import Capability
from ..utils import human_duration, human_size
from .base import Tool, ToolContext, ToolResult

log = logging.getLogger("vidit.tools.system")


class SystemControl:
    def __init__(self, downloads_dir: Path):
        self.downloads_dir = Path(downloads_dir)

    # --------------------------------------------------------------- stats
    @staticmethod
    def stats() -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "time": datetime.now().strftime("%A %d %B %Y, %H:%M"),
        }
        try:
            import psutil

            info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            vm = psutil.virtual_memory()
            info["ram_percent"] = vm.percent
            info["ram_used"] = human_size(vm.used)
            info["ram_total"] = human_size(vm.total)
            info["uptime"] = human_duration(time.time() - psutil.boot_time())
            try:
                battery = psutil.sensors_battery()
                if battery:
                    info["battery_percent"] = battery.percent
                    info["plugged_in"] = battery.power_plugged
            except Exception:  # noqa: BLE001
                pass
        except ImportError:
            info["note"] = "install psutil for live CPU/RAM stats"
        try:
            usage = shutil.disk_usage(str(Path.home()))
            info["disk_free"] = human_size(usage.free)
            info["disk_total"] = human_size(usage.total)
        except OSError:
            pass
        info["gpu"] = SystemControl.gpu_stats()
        return info

    @staticmethod
    def gpu_stats() -> Optional[Dict[str, Any]]:
        """NVIDIA stats via nvidia-smi (present on the RTX 4050 laptop); None elsewhere."""
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip().splitlines()
            if not out:
                return None
            name, util, used, total, temp = [p.strip() for p in out[0].split(",")]
            return {"name": name, "util_percent": float(util), "vram_used_mb": float(used), "vram_total_mb": float(total), "temp_c": float(temp)}
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------------- apps
    @staticmethod
    def open_path(target: str) -> str:
        """Open a file/folder/URL with the default application."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            return f"Opened {target}"
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't open {target}: {exc}"

    @staticmethod
    def launch_app(name: str) -> str:
        exe = shutil.which(name)
        if exe:
            subprocess.Popen([exe])
            return f"Launched {name}"
        if sys.platform.startswith("win"):
            try:
                os.startfile(name)  # type: ignore[attr-defined]
                return f"Launched {name}"
            except OSError as exc:
                return f"Couldn't find an app called {name}: {exc}"
        return f"Couldn't find an app called {name}."

    @staticmethod
    def running_processes(limit: int = 15) -> List[Dict[str, Any]]:
        try:
            import psutil
        except ImportError:
            return []
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            try:
                procs.append({"name": p.info["name"], "cpu": p.info["cpu_percent"] or 0.0,
                              "mem": human_size(p.info["memory_info"].rss if p.info["memory_info"] else 0)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        return procs[:limit]

    @staticmethod
    def foreground_window_title() -> str:
        """Used by gaming mode to detect a game in front. Windows only; empty elsewhere."""
        if not sys.platform.startswith("win"):
            return ""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def list_windows(limit: int = 20) -> List[Dict[str, Any]]:
        """Visible top-level windows (title + owning app). Windows 11 via the
        Win32 API; other platforms get an honest empty list."""
        if not sys.platform.startswith("win"):
            return []
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            windows: List[Dict[str, Any]] = []

            def _cb(hwnd: int, _lparam: int) -> bool:
                if len(windows) >= limit:
                    return False
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if not title:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                app = ""
                try:
                    k32 = ctypes.windll.kernel32
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
                    if h:
                        name = ctypes.create_unicode_buffer(260)
                        size = wintypes.DWORD(260)
                        if k32.QueryFullProcessImageNameW(h, 0, name, ctypes.byref(size)):
                            app = Path(name.value).name
                        k32.CloseHandle(h)
                except Exception:  # noqa: BLE001
                    pass
                windows.append({"title": title[:120], "app": app, "hwnd": hwnd})
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(_cb), 0)
            return windows
        except Exception:  # noqa: BLE001
            return []


    # ----------------------------------------------------------- clipboard
    @staticmethod
    def clipboard_read() -> str:
        try:
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance()
            if app:
                return app.clipboard().text()
        except Exception:  # noqa: BLE001
            pass
        try:
            if sys.platform.startswith("win"):
                return subprocess.run(["powershell", "-NoProfile", "-command", "Get-Clipboard"], capture_output=True, text=True, timeout=5).stdout
            if shutil.which("xclip"):
                return subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=5).stdout
        except Exception:  # noqa: BLE001
            pass
        return ""

    @staticmethod
    def clipboard_write(text: str) -> bool:
        try:
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance()
            if app:
                app.clipboard().setText(text)
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["clip"], input=text, text=True, timeout=5)
                return True
            if shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=5)
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    # -------------------------------------------------------------- delete
    def safe_delete(self, path: Path, backups_dir: Path) -> str:
        """Backup first, then delete (section 8)."""
        path = Path(path)
        if not path.exists():
            return f"{path} doesn't exist."
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = backups_dir / "deleted" / f"{stamp}-{path.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.is_dir():
                shutil.copytree(path, dest)
                shutil.rmtree(path)
            else:
                shutil.copy2(path, dest)
                path.unlink()
            return f"Deleted {path} (backup kept at {dest})."
        except OSError as exc:
            return f"Couldn't delete {path}: {exc}"


# ---------------------------------------------------------------------------
# natural-language time parsing for reminders (small but practical)
# ---------------------------------------------------------------------------
_REL_RE = re.compile(r"in\s+(\d+)\s*(second|sec|minute|min|hour|hr|day)s?", re.I)
_ABS_RE = re.compile(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def parse_when(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    now = now or datetime.now()
    m = _REL_RE.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        seconds = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400}[unit]
        return now + timedelta(seconds=n * seconds)
    m = _ABS_RE.search(text)
    if m:
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        if "tomorrow" in text.lower() and target.date() == now.date():
            target += timedelta(days=1)
        return target
    if "tomorrow" in text.lower():
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if "tonight" in text.lower():
        return now.replace(hour=21, minute=0, second=0, microsecond=0)
    return None


def make_system_tools(system: SystemControl, backups_dir: Path) -> List[Tool]:
    def _windows(args: str, ctx: ToolContext) -> ToolResult:
        if not ctx.permissions.check(Capability.SCREEN, "to list open windows (titles + apps only, no content)"):
            return ToolResult(False, "You haven't allowed me to look at the screen right now.")
        wins = SystemControl.list_windows(20)
        if not wins:
            return ToolResult(True, "I can't list windows on this platform (window listing is a Windows 11 feature).")
        lines = [f"• {w['title']}  ({w['app'] or 'unknown app'})" for w in wins]
        return ToolResult(True, "\n".join(lines), {"windows": wins})

    def _stats(args: str, ctx: ToolContext) -> ToolResult:
        s = system.stats()
        lines = [f"{k}: {v}" for k, v in s.items() if k != "gpu"]
        if s.get("gpu"):
            g = s["gpu"]
            lines.append(f"gpu: {g['name']} {g['util_percent']:.0f}% util, {g['vram_used_mb']:.0f}/{g['vram_total_mb']:.0f} MB VRAM, {g['temp_c']:.0f}°C")
        return ToolResult(True, "\n".join(lines), s)

    def _open(args: str, ctx: ToolContext) -> ToolResult:
        if not ctx.permissions.check(Capability.SYSTEM_CONTROL, f"to open {args}"):
            return ToolResult(False, "You haven't allowed me to control the system right now.")
        target = args.strip()
        if re.match(r"^https?://", target) or Path(target).expanduser().exists():
            return ToolResult(True, system.open_path(str(Path(target).expanduser()) if not target.startswith("http") else target))
        return ToolResult(True, system.launch_app(target))

    def _processes(args: str, ctx: ToolContext) -> ToolResult:
        procs = system.running_processes()
        return ToolResult(True, "\n".join(f"{p['name']}: cpu {p['cpu']:.0f}% mem {p['mem']}" for p in procs) or "(psutil not installed)")

    def _clipboard(args: str, ctx: ToolContext) -> ToolResult:
        if not ctx.permissions.check(Capability.CLIPBOARD, "to use the clipboard"):
            return ToolResult(False, "You haven't allowed me to touch the clipboard.")
        if args.strip().lower().startswith("write "):
            ok = system.clipboard_write(args.strip()[6:])
            return ToolResult(ok, "Copied." if ok else "Couldn't write the clipboard.")
        return ToolResult(True, system.clipboard_read()[:4000] or "(clipboard is empty)")

    def _remind(args: str, ctx: ToolContext) -> ToolResult:
        when = parse_when(args)
        if not when:
            return ToolResult(False, "Tell me when, e.g. 'in 20 minutes' or 'at 7pm'.")
        text = re.sub(r"\b(remind me|to)\b", "", args, flags=re.I)
        text = _REL_RE.sub("", text)
        text = _ABS_RE.sub("", text).strip(" ,.") or "the thing you asked about"
        ctx.memory.add_reminder(text, when.timestamp())
        return ToolResult(True, f"Reminder set for {when.strftime('%d %b %H:%M')}: {text}")

    def _delete(args: str, ctx: ToolContext) -> ToolResult:
        path = Path(args.strip()).expanduser()
        if not ctx.permissions.check(Capability.DELETE_FILES, "to delete this (I'll back it up first)", target=str(path)):
            return ToolResult(False, f"You haven't allowed me to delete {path}.")
        return ToolResult(True, system.safe_delete(path, backups_dir))

    return [
        Tool("system_stats", "CPU, RAM, GPU, disk, battery and time.", "", _stats),
        Tool("windows", "List the open windows (titles + app names) so I can see what's on screen.", "", _windows),
        Tool("open", "Open an app, file, folder or URL (asks permission).", "notepad | C:/path | https://…", _open, dangerous=True),
        Tool("processes", "Top running processes.", "", _processes),
        Tool("clipboard", "Read the clipboard, or write to it with 'write <text>'.", "write hello", _clipboard),
        Tool("remind", "Set a reminder.", "call mom in 30 minutes", _remind),
        Tool("delete_file", "Delete a file or folder after backing it up (asks permission).", "path", _delete, dangerous=True),
    ]
