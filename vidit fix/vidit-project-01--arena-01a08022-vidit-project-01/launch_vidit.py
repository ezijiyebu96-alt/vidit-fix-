#!/usr/bin/env python3
"""PyInstaller entry point for the Windows 11 build (Vidit.exe).

Same behaviour as ``python run.py`` — the GUI by default, ``--cli`` /
``--doctor`` / ``--version`` on the command line.

Frozen-build safety:

* ``freeze_support()`` first (multiprocessing-safe on Windows).
* Every failure is written to ``<VIDIT_HOME>/logs/vidit_crash.log`` and the
  process exits 1 — a windowed app must NEVER die with PyInstaller's modal
  error dialog (it would hang headless CI and confuse users).
* ``--doctor`` / ``--version`` / ``--cli`` attach to the parent console so
  the report is actually visible when run from a terminal.
"""
from __future__ import annotations

import multiprocessing
import sys


def _attach_parent_console() -> None:
    """Windowed apps have no console; borrow the parent's for CLI flags."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        import os

        k32 = ctypes.windll.kernel32
        if k32.GetConsoleWindow():
            return
        if not k32.AttachConsole(-1):  # double-clicked: no parent console
            return
        fd = os.open("CONOUT$", os.O_WRONLY | os.O_TEXT)
        sys.stdout = open(fd, "w", encoding="utf-8", closefd=False)
        sys.stderr = open(fd, "w", encoding="utf-8", closefd=False)
    except Exception:  # noqa: BLE001 — console output is best-effort
        pass


def _crash_log(exc: BaseException) -> None:
    try:
        import os
        import tempfile
        import time
        import traceback

        home = os.environ.get("VIDIT_HOME") or os.path.join(
            os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "Vidit"
        )
        log_dir = os.path.join(home, "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, "vidit_crash.log")
        except OSError:
            path = os.path.join(tempfile.gettempdir(), "vidit_crash.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    except Exception:  # noqa: BLE001 — never let logging crash the exit
        pass


def main() -> int:
    try:
        multiprocessing.freeze_support()
        if getattr(sys, "frozen", False) and any(
            a in ("--doctor", "--version", "--cli") for a in sys.argv[1:]
        ):
            _attach_parent_console()
        from vidit.__main__ import main as vidit_main

        return vidit_main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — log, don't hang
        _crash_log(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
