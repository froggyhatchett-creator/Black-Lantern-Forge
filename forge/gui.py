"""`python -m forge.gui` launches Forge Desktop.

The desktop shell lives in the separate `forge_desktop` package, so the
deterministic core stays free of GUI and entropy code. Importing this module
does nothing; only running it as a script starts the window.
"""

if __name__ == "__main__":
    import sys

    from forge_desktop.app import main

    sys.exit(main())
