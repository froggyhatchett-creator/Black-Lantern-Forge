"""Forge Desktop: the first human-facing shell for Black Lantern Forge (Step 2.75).

This package is the GUI *shell*. The deterministic Forge *core* lives in the
`forge` package and is not modified by anything here. The shell reaches the core
only through ForgeController, which uses the registry-driven pipeline.

    python -m forge_desktop        # or: python -m forge.gui

Layers:
  window.py      Tk widgets (the only module that imports tkinter)
  session.py     window state + user intents, headless and testable
  controller.py  registry pipeline: generate, preview, save, load, export
  entropy.py     the Random Seed button's randomness (UI convenience only)
"""

__all__ = ["controller", "session"]
