"""Entry point: ``python -m vidit`` (GUI) or ``python -m vidit --cli``."""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vidit", description="Vidit — your offline digital brother.")
    parser.add_argument("--cli", action="store_true", help="talk in the terminal instead of the GUI")
    parser.add_argument("--home", default=None, help="folder where Vidit keeps his memory (default: ~/.vidit or %%LOCALAPPDATA%%/Vidit)")
    parser.add_argument("--quiet", action="store_true", help="no voice output")
    parser.add_argument("--doctor", action="store_true", help="check the environment and exit")
    args = parser.parse_args(argv)

    if args.doctor:
        from .doctor import run_doctor

        return run_doctor(args.home)
    if args.cli:
        from .cli import run_cli

        return run_cli(args.home, quiet=args.quiet)
    try:
        from .ui.app import main as gui_main
    except ImportError as exc:
        print(f"GUI unavailable ({exc}). Install PyQt5 (`pip install PyQt5`) or use `python -m vidit --cli`.")
        return 1
    return gui_main(args.home)


if __name__ == "__main__":
    sys.exit(main())
