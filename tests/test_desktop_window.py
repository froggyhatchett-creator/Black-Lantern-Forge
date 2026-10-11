"""Step 2.75 real-window smoke test. Skipped automatically when tkinter or a display is unavailable,
so the rest of the suite never depends on a graphical session."""

import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:  # ImportError (no tkinter) or TclError (no display)
    HAVE_DISPLAY = False

from forge_test_support import sha256
from desktop_support import SMALL_PREVIEW, FakeDialogs
from registry_fixtures import spying_registry
from step2_support import GOLDEN_1337_PIXELS_SMALL

FROZEN_OBJ_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class TestRealWindow(unittest.TestCase):
    def setUp(self):
        from forge_desktop.controller import ForgeController
        from forge_desktop.session import SyncRunner
        from forge_desktop.window import build_window
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.registry, self.spies = spying_registry()
        self.dialogs = FakeDialogs(save_path=self.tmp / "w.json", export_path=self.tmp / "w.obj",
                                   preview_path=self.tmp / "w.png")
        self.root = tk.Tk()
        self.root.withdraw()
        self.win = build_window(self.root, controller=ForgeController(self.registry, preview_size=SMALL_PREVIEW),
                                seed_source=lambda: 1337, dialogs=self.dialogs, runner=SyncRunner())
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self._tmp.cleanup()

    def test_window_builds_from_registry_without_generating(self):
        w = self.win
        self.assertEqual(self.spies["generate"].calls, 0)
        self.assertEqual(tuple(w.asset_combo.cget("values")), ("short_sword",))
        self.assertEqual(tuple(w.gen_combo.cget("values")), ("1",))
        self.assertEqual(w.gen_var.get(), "1")
        self.assertEqual([b.cget("text") for b in w.view_buttons.values()], ["Three-quarter", "Front", "Side"])
        self.assertEqual(len(w.export_combo.cget("values")), 3)
        self.assertIn("disabled", w.save_button.state())
        self.assertNotIn("disabled", w.generate_button.state())
        self.assertEqual(w.status_var.get(), "Ready")

    def test_generate_switch_view_save_export_in_the_real_window(self):
        w = self.win
        w.random_button.invoke()
        self.assertEqual(w.seed_var.get(), "1337")
        w.generate_button.invoke()
        self.root.update()
        self.assertIsNotNone(w._photo)
        self.assertEqual(w.session.view_model().preview.pixels_sha256, GOLDEN_1337_PIXELS_SMALL["three_quarter"])
        self.assertGreater(len(w.details_frame.winfo_children()), 20)
        w.view_buttons["side"].invoke()
        self.root.update()
        self.assertEqual(w.session.view_model().preview.pixels_sha256, GOLDEN_1337_PIXELS_SMALL["side"])
        w.save_button.invoke()
        self.assertTrue((self.tmp / "w.json").is_file())
        w.export_combo.current(1)
        w._on_export_selected()
        w.export_button.invoke()
        self.assertEqual(sha256((self.tmp / "w.obj").read_bytes()), FROZEN_OBJ_1337)
        w.save_preview_button.invoke()
        self.assertTrue((self.tmp / "w.png").is_file())
        self.assertEqual(self.dialogs.errors, [])

    def test_keyboard_reaches_every_control(self):
        w = self.win
        self.root.deiconify()
        self.root.update()
        seen, widget = [], w.seed_entry
        for _ in range(60):
            widget = widget.tk_focusNext()
            if widget is None or widget in seen:
                break
            seen.append(widget)
        for target in (w.random_button, w.gen_combo, w.generate_button, w.load_button):
            self.assertIn(target, seen, f"{target} not reachable with Tab")


if __name__ == "__main__":
    unittest.main()
