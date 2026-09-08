#!/usr/bin/env python3
"""PyInstaller entry point for the Windows 11 build (Vidit.exe).

Crash-proofing for the windowed (no-console) app:

* ``faulthandler`` is enabled first — even NATIVE crashes (access violations
  in bundled DLLs) leave the Python stack in ``%LOCALAPPDATA%\\Vidit\\logs\\
  vidit_crash.log`` instead of dying silently.
* ``sys.excepthook`` / ``threading.excepthook`` log every Python exception,
  including ones from worker threads.
* Startup stage markers are appended to the same log, so a crash at a
  specific stage (qt → core → gui → voice → event loop) is visible at a
  glance.
* A clean-exit marker is written on normal quit. If the previous run died
  within 90 s of starting, the next launch runs in SAFE MODE (voice and
  auto-listening off) so a bad TTS/GPU state can never loop crashes —
  the user just sees a note and chat still works.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
import time


def _home() -> str:
    return (
        os.environ.get("VIDIT_HOME")
        or os.path.join(os.environ.get("LOCALAPPDATA", tempfile_dir()), "Vidit")
    )


def tempfile_dir() -> str:
    import tempfile

    return tempfile.gettempdir()


def _log_path() -> str:
    log_dir = os.path.join(_home(), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, "vidit_crash.log")
    except OSError:
        return os.path.join(tempfile_dir(), "vidit_crash.log")


_log_file = None


def _stage(msg: str) -> None:
    """Append a progress marker (best effort — must never raise)."""
    global _log_file
    try:
        if _log_file is None:
            _log_file = open(_log_path(), "a", encoding="utf-8", buffering=1)
        _log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stage: {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _install_crash_logging() -> None:
    global _log_file
    import faulthandler
    import traceback

    try:
        _log_file = open(_log_path(), "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_log_file)  # catches native crashes too
    except Exception:  # noqa: BLE001
        _log_file = None

    def _py_hook(kind: str, args: tuple) -> None:  # noqa: ANN401
        try:
            exc_type, value, tb = args
            if _log_file is not None:
                _log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {kind}\n")
                traceback.print_exception(exc_type, value, tb, file=_log_file)
                _log_file.write("---- end of traceback ----\n")
        except Exception:  # noqa: BLE001
            pass

    def _excepthook(exc_type, value, tb):  # noqa: ANN001
        _py_hook("unhandled exception", (exc_type, value, tb))
        try:  # keep the windowed app from vanishing silently
            from PyQt5.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                box = QMessageBox(QMessageBox.Critical, "Vidit hit a problem",
                                  "Vidit ran into an error and has to close.\n\n"
                                  f"Details were saved to:\n{_log_path()}")
                box.exec_()
        except Exception:  # noqa: BLE001
            pass
        os._exit(1)

    def _thread_hook(args):  # noqa: ANN001
        _py_hook("unhandled exception in a thread", (args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _excepthook
    threading_excepthook = getattr(__import__("threading"), "excepthook", None)
    if threading_excepthook is not None:
        __import__("threading").excepthook = _thread_hook


def _attach_parent_console() -> None:
    """Windowed apps have no console; borrow the parent's for CLI flags."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        if k32.GetConsoleWindow():
            return
        if not k32.AttachConsole(-1):
            return
        fd = os.open("CONOUT$", os.O_WRONLY | os.O_TEXT)
        sys.stdout = open(fd, "w", encoding="utf-8", closefd=False)
        sys.stderr = open(fd, "w", encoding="utf-8", closefd=False)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    try:
        multiprocessing.freeze_support()
        args = sys.argv[1:]
        cli_mode = any(a in ("--doctor", "--version", "--cli") for a in args)
        if cli_mode:
            _attach_parent_console()
        if getattr(sys, "frozen", False) and not cli_mode:
            # SAFE MODE: previous run crashed right after boot? Start quiet.
            marker = os.path.join(_home(), "boot_state.json")
            safe = False
            try:
                import json

                if os.path.isfile(marker):
                    state = json.load(open(marker, encoding="utf-8"))
                    started = float(state.get("started", 0))
                    clean = bool(state.get("clean"))
                    if not clean and (time.time() - started) < 1.0e9:
                        # marker exists and was not cleared by a clean exit:
                        # the last session ended abnormally.
                        crashed_fast = (time.time() - started) < 90
                        safe = crashed_fast or state.get("crashes", 0) >= 2
            except Exception:  # noqa: BLE001
                safe = False
            try:
                import json

                os.makedirs(_home(), exist_ok=True)
                crashes = 0
                try:
                    crashes = json.load(open(marker, encoding="utf-8")).get("crashes", 0)
                except Exception:  # noqa: BLE001
                    pass
                json.dump({"started": time.time(), "clean": False, "crashes": crashes + 1},
                          open(marker, "w", encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
            if safe:
                os.environ["VIDIT_SAFE_MODE"] = "1"
            _install_crash_logging()
            _stage(f"boot (pid {os.getpid()}, safe_mode={safe})")
        from vidit.__main__ import main as vidit_main

        return vidit_main()
    except SystemExit as exc:
        # normal exit paths (including CLI) — mark clean unless it failed
        try:
            import json

            json.dump({"started": time.time(), "clean": int(exc.code or 0) == 0, "crashes": 0},
                      open(os.path.join(_home(), "boot_state.json"), "w", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
        raise
    except BaseException as exc:  # noqa: BLE001 — log, don't hang
        _stage(f"fatal: {type(exc).__name__}: {exc}")
        try:
            import traceback

            if _log_file is not None:
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=_log_file)
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
