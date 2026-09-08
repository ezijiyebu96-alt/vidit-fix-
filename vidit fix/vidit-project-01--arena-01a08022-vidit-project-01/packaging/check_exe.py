"""Run the packaged Vidit.exe with a hard timeout (CI-safe).

A windowed Windows app shares no stdout with the console, and an unhandled
bootloader error pops a modal dialog that hangs a headless CI runner forever.
This helper enforces a timeout, reports the exit code, and prints the tail of
``<VIDIT_HOME>/logs/vidit_crash.log`` when the app failed.

Usage:  python packaging/check_exe.py path/to/Vidit.exe --version
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

TIMEOUT = 240


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("usage: check_exe.py Vidit.exe [args...]")
        return 3
    exe, args = argv[0], argv[1:]
    if not os.path.isfile(exe):
        print(f"FAIL: {exe} not found")
        return 3
    try:
        proc = subprocess.run([exe, *args], timeout=TIMEOUT)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        print(f"FAIL: {' '.join([exe, *args])} did not exit within {TIMEOUT}s "
              "(possible modal dialog / hang)")
        return 2
    print(f"{os.path.basename(exe)} {' '.join(args)} -> exit {code}")
    if code != 0:
        home = os.environ.get("VIDIT_HOME") or os.path.join(
            os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "Vidit"
        )
        crash = pathlib.Path(home) / "logs" / "vidit_crash.log"
        if crash.exists():
            print(f"--- crash log tail ({crash}) ---")
            tail = crash.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            print("\n".join(tail))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
