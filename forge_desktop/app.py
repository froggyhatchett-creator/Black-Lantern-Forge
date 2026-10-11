"""Forge Desktop entry point.

    python -m forge_desktop            launch the window
    python -m forge_desktop --check    build the window, process events once, close (smoke test)
    python -m forge.gui                same as the first line
"""

from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger("forge_desktop")

TKINTER_MISSING = (
    "Forge Desktop needs Tkinter, which this Python does not include.\n"
    "  Windows / macOS: use the python.org installer (Tkinter is included).\n"
    "  Debian / Ubuntu: sudo apt install python3-tk\n"
    "  Fedora:          sudo dnf install python3-tkinter\n"
    "The command-line interface (python -m forge) works without it."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m forge_desktop", description="Black Lantern Forge desktop shell")
    parser.add_argument("--check", action="store_true", help="create the window, process events once, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        import tkinter as tk
    except ImportError:
        print(TKINTER_MISSING, file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Forge Desktop could not open a window: {exc}\n"
              "A graphical desktop session is required (no display was found).", file=sys.stderr)
        return 1

    from forge_desktop.window import build_window
    build_window(root)
    if args.check:
        root.update()
        root.destroy()
        print("Forge Desktop window created successfully.")
        return 0
    log.info("Forge Desktop started")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
