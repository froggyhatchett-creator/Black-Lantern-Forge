"""Step 5B tests 56-57: Forge Desktop lists and drives the hafted families through the registry.

56  the asset-type list is the registry's list; the shell names no family
57  generate, every view, save, reload, OBJ and engine-package export work for every family
Plus an optional real-window check (skipped without tkinter and a display).
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from desktop_support import SMALL_PREVIEW, FakeDialogs
from forge.catalog import ASSETS, EXPORTERS, GENERATORS, PREVIEWS, PRESENTATIONS, REGISTRY
from forge.engine.validate import validate_package
from forge.registry import build_registry
from forge_desktop.controller import ForgeController
from forge_desktop.session import DesktopSession, SyncRunner
from forge_test_support import REPO_ROOT
from hafted_support import EXAMPLES, FAMILIES, GENERATOR_IDS, HAFTED_GOLDEN, NEW_IDENTIFIERS

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:  # ImportError (no tkinter) or TclError (no display)
    HAVE_DISPLAY = False


def session(registry=REGISTRY, dialogs=None, seed=1337):
    dialogs = dialogs or FakeDialogs()
    return DesktopSession(ForgeController(registry, preview_size=SMALL_PREVIEW), dialogs, SyncRunner(), lambda: seed), dialogs


class TestListing(unittest.TestCase):
    def test_56_desktop_lists_new_families_from_registry(self):
        s, _ = session()
        vm = s.view_model()
        self.assertEqual(vm.asset_types, REGISTRY.asset_types())
        for family in ("short_sword", "dagger", "long_sword", "curved_sword", "great_sword") + FAMILIES:
            self.assertIn(family, vm.asset_types)
        self.assertEqual(len(vm.asset_types), 9)
        self.assertIsNone(vm.asset_type, "with several types registered, none is preselected")
        without = build_registry(assets=ASSETS[:5], generators=GENERATORS[:5], presentations=PRESENTATIONS[:2],
                                 exporters=EXPORTERS, previews=PREVIEWS)
        self.assertFalse(set(FAMILIES) & set(session(without)[0].view_model().asset_types),
                         "the shell lists only what the registry it is given contains")
        for family in FAMILIES:
            s.select_asset_type(family)
            vm = s.view_model()
            self.assertEqual((vm.generator_versions, vm.presentation_versions, vm.preview_versions), ((1,), (1,), (1,)))
            self.assertEqual([c.key for c in vm.exporters], ["glb:1", "obj:2"])
            self.assertIsNone(vm.export_key)
        # the shell's own code names no hafted family
        for path in sorted((REPO_ROOT / "forge_desktop").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            for ident in NEW_IDENTIFIERS:
                self.assertFalse(any(ident in x for x in strings), f"{path.name} names {ident}")


class TestGenerate(unittest.TestCase):
    def test_57_gui_generation_works_for_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for family in FAMILIES:
                with self.subTest(family=family):
                    dialogs = FakeDialogs(save_path=tmp / f"{family}.json", export_path=tmp / f"{family}.forgepkg",
                                          preview_path=tmp / f"{family}.png", open_path=tmp / f"{family}.json")
                    s, _ = session(dialogs=dialogs)
                    s.select_asset_type(family)
                    s.set_seed_text("1337")
                    s.generate()
                    vm = s.view_model()
                    self.assertEqual(dialogs.errors, [])
                    self.assertEqual(vm.status, f"Generated {family} seed 1337 · preview rendered (three_quarter)")
                    rows = dict(vm.details)
                    self.assertEqual(rows["Generator"], f"{GENERATOR_IDS[family]} v1")
                    self.assertEqual(rows["geometry_sha256"], HAFTED_GOLDEN[family]["integrity"]["geometry_sha256"])
                    self.assertIn("forge.preview.fit v1", rows["Preview"])
                    for view in ("front", "side"):
                        s.select_view(view)
                        self.assertIsNotNone(s.view_model().preview)
                    s.save_record()
                    s.select_export("glb:1")
                    self.assertEqual(s.view_model().export_action, "Export Engine Package…")
                    s.export()
                    self.assertTrue(s.view_model().status.endswith("forge.engine-contract v1 validated"))
                    self.assertEqual(validate_package(tmp / f"{family}.forgepkg").asset_type, family)
                    self.assertEqual((tmp / f"{family}.forgepkg" / "asset.glb").read_bytes(),
                                     (EXAMPLES / f"{family}_seed1337_v1.forgepkg" / "asset.glb").read_bytes())
                    s.select_export("obj:2")
                    dialogs.export_path = tmp / f"{family}.obj"
                    s.export()
                    self.assertTrue((tmp / f"{family}.mtl").exists())
                    s.save_preview()
                    s.load_record()
                    self.assertEqual(s.view_model().status, f"Loaded {family}.json: 6 checks passed")
                    self.assertEqual(dialogs.errors, [])

    def test_golden_records_load_in_the_shell(self):
        for family in FAMILIES:
            dialogs = FakeDialogs(open_path=EXAMPLES / f"{family}_record_seed1337.json")
            s, _ = session(dialogs=dialogs)
            s.load_record()
            self.assertEqual(dialogs.errors, [])
            self.assertEqual(s.state.preview_note, "matches record")


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class TestRealWindow(unittest.TestCase):
    def test_real_window_generates_every_hafted_family(self):
        with mock.patch.dict(sys.modules):           # keeps the frozen "importing forge.gui loads no window" guard true
            from forge_desktop.window import build_window
            root = tk.Tk()
            root.withdraw()
            try:
                w = build_window(root, controller=ForgeController(REGISTRY, preview_size=SMALL_PREVIEW),
                                 seed_source=lambda: 1337, dialogs=FakeDialogs(), runner=SyncRunner())
                root.update()
                self.assertEqual(tuple(w.asset_combo.cget("values")), REGISTRY.asset_types())
                for family in FAMILIES:
                    w.asset_var.set(family)
                    w.asset_combo.event_generate("<<ComboboxSelected>>")
                    root.update()
                    w.random_button.invoke()                 # the scripted seed source gives 1337
                    w.generate_button.invoke()
                    root.update()
                    self.assertEqual(w.session.state.current.asset_type, family)
                    self.assertIn(family, root.title())
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
