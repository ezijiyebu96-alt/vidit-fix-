"""Small shared helpers."""
from __future__ import annotations

import logging
import logging.handlers
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional


def find_sandbox_python() -> Optional[List[str]]:
    """Command prefix for running user/skill code in a subprocess.

    From source this is simply ``sys.executable -I``. Inside a PyInstaller
    bundle (Vidit.exe) ``sys.executable`` is Vidit itself, so we look for a
    real system Python instead — never the packaged app. Returns None when
    no usable interpreter exists (packaged app without Python on PATH).
    """
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-I"]
    exe_self = Path(sys.executable).resolve()
    candidates = [("py", ["py", "-3", "-I"]), ("python", ["python", "-I"])]
    if not sys.platform.startswith("win"):
        candidates.append(("python3", ["python3", "-I"]))
    for which_name, prefix in candidates:
        exe = shutil.which(which_name)
        if exe and Path(exe).resolve() != exe_self:
            return prefix
    return None


def probe_run(args: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Run a short command, capturing output (never raises on timeout)."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:  # noqa: PERF203
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def mark_clean_exit() -> None:
    """Tell the frozen launcher this session ended normally, so the next
    boot doesn't go into safe mode (best effort; no-op from source)."""
    import json
    import os
    import time

    if not getattr(sys, "frozen", False):
        return
    try:
        home = os.environ.get("VIDIT_HOME") or os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Vidit"
        )
        marker = os.path.join(home, "boot_state.json")
        os.makedirs(home, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as fh:
            json.dump({"started": time.time(), "clean": True, "crashes": 0}, fh)
    except OSError:
        pass


def apply_autostart(mode: str, exe: str | None = None) -> bool:
    """Register/unregister Vidit to start with Windows (HKCU Run key).

    Only acts inside the frozen Windows app; from source this is a no-op.
    'with_system' registers the exe; any other mode removes the entry.
    Returns True when the registry was actually touched.
    """
    if not (getattr(sys, "frozen", False) and sys.platform.startswith("win")):
        return False
    import winreg

    exe = exe or sys.executable
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
        if mode == "with_system":
            winreg.SetValueEx(key, "Vidit", 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, "Vidit")
            except FileNotFoundError:
                pass
    return True



def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(getattr(h, "_vidit", False) for h in root.handlers):
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "vidit.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler._vidit = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(fmt)
    console._vidit = True  # type: ignore[attr-defined]
    root.addHandler(console)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_ts() -> float:
    return time.time()


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


_WORD_RE = re.compile(r"[A-Za-z0-9\u0900-\u097F']+")

STOPWORDS = frozenset(
    """a an the and or but if then so of to in on at for from by with about as into
    like through after over between out against during without before under around
    among is are was were be been being am do does did doing have has had having i me
    my myself we our ours you your yours he him his she her hers it its they them their
    what which who whom this that these those will would can could should shall may
    might must not no nor only own same too very just also than there here when where
    why how all any both each few more most other some such""".split()
)


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def keywords(text: str, limit: int | None = None) -> list[str]:
    seen: dict[str, None] = {}
    for word in tokenize(text):
        if len(word) > 2 and word not in STOPWORDS:
            seen.setdefault(word, None)
    words = list(seen)
    return words[:limit] if limit else words


def truncate(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "file"


def is_within(path: Path, roots: Iterable[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError):
            continue
    return False
