"""Step 5A tests 55-56: Forge Desktop lists and drives the blade families through the registry.

55  the asset-type list is the registry's list; nothing is hard-coded or preselected
56  generate, preview, save, reload and export work for every family through the unchanged shell
Plus an optional real-window check (skipped without tkinter and a display).
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arsenal_support import ARSENAL_GOLDEN, EXAMPLES, FAMILIES, GENERATOR_IDS
from desktop_support import SMALL_PREVIEW, FakeDialogs
from forge.catalog import ASSETS, EXPORTERS, GENERATORS, PREVIEWS, PRESENTATIONS, REGISTRY
from forge.engine.validate import validate_package
from forge.record import load_record
from forge.registry import build_registry
from forge_desktop.controller import ForgeController
from forge_desktop.session import DesktopSession, SyncRunner

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:  # ImportError (no tkinter) or TclError (no display)
    HAVE_DISPLAY = False


def session(registry=REGISTRY, dialogs=None, seed=1337):
    dialogs = dialogs or FakeDialogs()
    s = DesktopSession(ForgeController(registry, preview_size=SMALL_PREVIEW), dialogs, SyncRunner(), lambda: seed)
    return s, dialogs


class TestListing(unittest.TestCase):
    def test_55_desktop_lists_families_through_the_registry(self):
        s, _ = session()
        vm = s.view_model()
        self.assertEqual(vm.asset_types, REGISTRY.asset_types())
        self.assertEqual(vm.asset_types, ("curved_sword", "dagger", "great_sword", "long_sword", "mace", "one_hand_axe",
                                          "short_sword", "two_hand_axe", "war_hammer"))   # Step 5B: + hafted
        self.assertIsNone(vm.asset_type, "with several types registered, none is preselected")
        self.assertFalse(vm.can_export)
        # the shell lists exactly what the registry it is given contains
        subset = build_registry(assets=(ASSETS[0], ASSETS[2]), generators=(GENERATORS[0], GENERATORS[2]),
                                presentations=PRESENTATIONS, exporters=EXPORTERS, previews=PREVIEWS)
        s2, _ = session(subset)
        self.assertEqual(s2.view_model().asset_types, ("long_sword", "short_sword"))
        only_short = build_registry(assets=ASSETS[:1], generators=GENERATORS[:1], presentations=PRESENTATIONS[:1],
                                    exporters=EXPORTERS, previews=PREVIEWS)
        s3, _ = session(only_short)
        self.assertEqual(s3.view_model().asset_type, "short_sword", "a single type is still preselected (Step 2.75)")

    def test_family_options_come_from_the_registry(self):
        s, _ = session()
        for family in FAMILIES:
            s.select_asset_type(family)
            vm = s.view_model()
            self.assertEqual(vm.asset_type, family)
            self.assertEqual(vm.generator_versions, (1,))
            self.assertEqual(vm.generator_version, 1)            # the only one, so selected; never "latest"
            self.assertEqual(vm.presentation_versions, (1,))
            self.assertEqual(vm.preview_versions, (1,))
            self.assertEqual([c.key for c in vm.exporters], ["glb:1", "obj:2"])
            self.assertIsNone(vm.export_key, "two exporters: the user chooses")
            self.assertEqual(vm.export_action, "Export…")


class TestGenerate(unittest.TestCase):
    def test_56_gui_generation_works_per_family(self):
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
                    self.assertIsNotNone(vm.preview)
                    rows = dict(vm.details)
                    self.assertEqual(rows["Generator"], f"{GENERATOR_IDS[family]} v1")
                    self.assertEqual(rows["geometry_sha256"], ARSENAL_GOLDEN[family]["integrity"]["geometry_sha256"])
                    self.assertIn("forge.preview.fit v1", rows["Preview"])
                    for view in ("front", "side"):
                        s.select_view(view)
                        self.assertIsNotNone(s.view_model().preview)
                    s.save_record()
                    self.assertTrue(s.view_model().status.startswith("Record saved"))
                    self.assertEqual(load_record(tmp / f"{family}.json").asset.asset_type, family)
                    s.select_export("glb:1")
                    self.assertEqual(s.view_model().export_action, "Export Engine Package…")
                    s.export()
                    self.assertTrue(s.view_model().status.endswith("forge.engine-contract v1 validated"),
                                    s.view_model().status)
                    self.assertEqual(validate_package(tmp / f"{family}.forgepkg").asset_type, family)
                    self.assertEqual((tmp / f"{family}.forgepkg" / "asset.glb").read_bytes(),
                                     (EXAMPLES / f"{family}_seed1337_v1.forgepkg" / "asset.glb").read_bytes())
                    s.select_export("obj:2")
                    dialogs.export_path = tmp / f"{family}.obj"
                    s.export()
                    self.assertTrue((tmp / f"{family}.mtl").exists())
                    s.save_preview()
                    self.assertTrue((tmp / f"{family}.png").exists())
                    s.load_record()
                    self.assertEqual(s.view_model().status, f"Loaded {family}.json: 6 checks passed")
                    self.assertEqual(dialogs.errors, [])

    def test_golden_records_load_in_the_shell(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                dialogs = FakeDialogs(open_path=EXAMPLES / f"{family}_record_seed1337.json")
                s, _ = session(dialogs=dialogs)
                s.load_record()
                self.assertEqual(dialogs.errors, [])
                self.assertEqual(s.state.preview_note, "matches record")
                self.assertEqual(s.view_model().asset_type, family)


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class TestRealWindow(unittest.TestCase):
    def test_real_window_generates_every_family(self):
        # patch.dict restores sys.modules afterwards, so importing the window here cannot leak into
        # the frozen Step 2.75 guard that checks "importing forge.gui does not load the window"
        with mock.patch.dict(sys.modules):
            from forge_desktop.window import build_window
            self.drive(build_window)

    def drive(self, build_window):
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
                w.random_button.invoke()
                w.generate_button.invoke()
                root.update()
                self.assertEqual(w.session.state.current.asset_type, family)
                self.assertIn(family, root.title())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
