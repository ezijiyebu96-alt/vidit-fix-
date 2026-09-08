#!/usr/bin/env python3
"""Convenience launcher: ``python run.py`` (GUI) or ``python run.py --cli``."""
import sys

from vidit.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
