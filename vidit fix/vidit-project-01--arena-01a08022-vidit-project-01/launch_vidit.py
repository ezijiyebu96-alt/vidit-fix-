#!/usr/bin/env python3
"""PyInstaller entry point for the Windows 11 build (Vidit.exe).

Same behaviour as ``python run.py`` — the GUI by default, ``--cli`` /
``--doctor`` / ``--version`` on the command line. ``freeze_support`` must run
before anything else so any bundled library that spawns workers is safe.
"""
from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from vidit.__main__ import main as vidit_main

    return vidit_main()


if __name__ == "__main__":
    sys.exit(main())
