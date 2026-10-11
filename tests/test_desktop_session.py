"""Step 2.75: window state and user intents (headless; fake dialogs and runners)."""

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge_test_support import REPO_ROOT, sha256
from desktop_support import DeferredRunner, FakeDialogs, make_session
from registry_fixtures import registry_with_sword_v2, spying_registry
from step2_support import GOLDEN_1337_PIXELS_DEFAULT, GOLDEN_1337_PIXELS_SMALL

FROZEN_OBJ_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"
EXAMPLE = REPO_ROOT / "examples" / "asset_record_seed1337.json"


class TestLaunch(unittest.TestCase):
    def test_27_launch_does_not_generate(self):
        reg, spies = spying_registry()
        session, dialogs = make_session(reg)
        vm = session.view_model()
        self.assertEqual((spies["generate"].calls, spies["derive"].calls, spies["preview"].calls), (0, 0, 0))
        self.assertIsNone(vm.preview)
        self.assertEqual(vm.details, ())
        self.assertEqual(vm.status, "Ready")
        self.assertFalse(vm.can_save_record or vm.can_export or vm.can_save_preview)
        session.randomize_seed()                     # convenience only: still nothing generated
        self.assertEqual(spies["generate"].calls, 0)

    def test_selectors_come_from_registry_with_explicit_versions(self):
        vm = make_session()[0].view_model()
        self.assertEqual(vm.asset_types, ("curved_sword", "dagger", "great_sword", "long_sword", "mace", "one_hand_axe",
                                          "short_sword", "two_hand_axe", "war_hammer"))
        self.assertEqual(vm.asset_type, "short_sword")              # selected by make_session (several types)
        self.assertEqual((vm.generator_versions, vm.generator_version), ((1,), 1))
        self.assertEqual((vm.presentation_versions, vm.presentation_version), ((1,), 1))
        self.assertEqual((vm.preview_versions, vm.preview_version), ((1,), 1))
        self.assertEqual(vm.views, ("three_quarter", "front", "side"))
        self.assertEqual([e.key for e in vm.exporters], ["glb:1", "obj:1", "obj:2"])
        self.assertIsNone(vm.export_key)                            # two formats: the user must choose

    def test_no_implicit_latest_when_several_versions_exist(self):
        session, dialogs = make_session(registry_with_sword_v2())
        vm = session.view_model()
        self.assertEqual(vm.generator_versions, (1, 2))
        self.assertIsNone(vm.generator_version)                     # not preselected
        session.set_seed_text("1337")
        session.generate()
        self.assertEqual(dialogs.errors[-1][0], "Choose a generator version")
        self.assertIsNone(session.state.current)
        session.select_generator_version("2")
        session.generate()
        self.assertEqual(session.state.current.generator_version, 2)


class TestGenerateFlow(unittest.TestCase):
    def test_generate_populates_preview_details_and_actions(self):
        session, dialogs = make_session()
        session.set_seed_text("1337")
        session.generate()
        vm = session.view_model()
        self.assertEqual(dialogs.errors, [])
        self.assertEqual(vm.status, "Generated short_sword seed 1337 · preview rendered (three_quarter)")
        self.assertEqual(vm.preview.pixels_sha256, GOLDEN_1337_PIXELS_SMALL["three_quarter"])
        self.assertIn(("Seed", "1337"), vm.details)
        self.assertTrue(vm.can_save_record and vm.can_save_preview)
        self.assertFalse(vm.can_export)                             # no export format chosen yet
        self.assertEqual(vm.title, "Black Lantern Forge — short_sword · seed 1337")

    def test_view_switching_renders_each_view_once_and_never_changes_geometry(self):
        reg, spies = spying_registry()
        session, _ = make_session(reg)
        session.set_seed_text("1337")
        session.generate()
        asset = session.state.current.asset
        for view in ("front", "side", "three_quarter", "front"):
            session.select_view(view)
            self.assertEqual(session.view_model().preview.pixels_sha256, GOLDEN_1337_PIXELS_SMALL[view])
        self.assertEqual(spies["preview"].calls, 3)                 # cached after first render
        self.assertEqual(spies["generate"].calls, 1)
        self.assertIs(session.state.current.asset, asset)

    def test_invalid_seed_keeps_the_current_asset(self):
        session, dialogs = make_session()
        session.set_seed_text("1337")
        session.generate()
        current = session.state.current
        session.set_seed_text("not a seed")
        session.generate()
        self.assertEqual(dialogs.errors[-1][0], "Invalid seed")
        self.assertIs(session.state.current, current)
        vm = session.view_model()
        self.assertTrue(vm.status.startswith("Error:"))           # visible without relying on color
        self.assertEqual(vm.status_kind, "error")
        self.assertFalse(vm.busy)

    def test_random_seed_is_explicit_and_visible(self):
        session, _ = make_session(seed_source=lambda: 987654321)
        session.randomize_seed()
        self.assertEqual(session.view_model().seed_text, "987654321")
        session.generate()
        self.assertEqual(session.state.current.seed, 987654321)

    def test_busy_state_blocks_overlapping_work(self):
        runner = DeferredRunner()
        reg, spies = spying_registry()
        session, _ = make_session(reg, runner=runner)
        session.set_seed_text("1")
        session.generate()
        vm = session.view_model()
        self.assertTrue(vm.busy)
        self.assertFalse(vm.can_generate or vm.can_load or vm.can_save_record)
        session.generate()                                          # ignored while busy
        self.assertEqual(len(runner.queue), 1)
        runner.flush()
        self.assertFalse(session.view_model().busy)
        self.assertEqual(spies["generate"].calls, 1)

    def test_unexpected_errors_are_reported_not_raised(self):
        session, dialogs = make_session()
        session.set_seed_text("1")
        with mock.patch.object(session.controller, "generate", side_effect=RuntimeError("boom")):
            with self.assertLogs("forge_desktop", level=logging.ERROR) as logs:
                session.generate()
        title, message = dialogs.errors[-1]
        self.assertIn("unexpected error", title)
        self.assertIn("RuntimeError: boom", message)
        self.assertIn("written to the log", message)
        self.assertNotIn("Traceback", message)                     # traceback goes to the log, not the dialog
        self.assertTrue(any("Traceback" in line for line in logs.output))
        self.assertFalse(session.view_model().busy)

    def test_unknown_selections_are_refused(self):
        session, dialogs = make_session()
        session.select_asset_type("armor")
        self.assertEqual(dialogs.errors[-1][0], "Unknown asset type")
        self.assertEqual(session.state.asset_type, "short_sword")
        session.select_export("fbx:1")
        self.assertEqual(dialogs.errors[-1][0], "Export not available")
        self.assertIsNone(session.state.export_key)
        session.select_generator_version("7")
        self.assertEqual(dialogs.errors[-1][0], "Unsupported generator version")
        session.select_view("top")
        self.assertEqual(dialogs.errors[-1][0], "Unknown view")


class TestFileActions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def generated(self, **dialog_paths):
        session, dialogs = make_session(dialogs=FakeDialogs(**dialog_paths))
        session.set_seed_text("1337")
        session.generate()
        return session, dialogs

    def test_save_record_then_details_show_record_hash(self):
        session, dialogs = self.generated(save_path=self.tmp / "s.json")
        session.save_record()
        self.assertEqual(dialogs.asked[-1], ("save", "short_sword_seed1337.json"))
        rows = dict(session.view_model().details)
        record = json.loads((self.tmp / "s.json").read_text())
        self.assertEqual(rows["record_content_sha256"], record["integrity"]["record_content_sha256"])
        self.assertEqual(session.view_model().status, "Record saved: s.json")

    def test_cancelled_dialogs_do_nothing(self):
        session, dialogs = self.generated()
        for action, status in ((session.save_record, "Save cancelled"), (session.export, None),
                               (session.save_preview, "Save preview cancelled"), (session.load_record, "Load cancelled")):
            session.select_export("obj:1")
            action()
            if status:
                self.assertEqual(session.view_model().status, status)
        self.assertEqual(session.view_model().status, "Load cancelled")
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertEqual(dialogs.errors, [])

    def test_export_obj1_and_obj2_through_session(self):
        session, dialogs = self.generated(export_path=self.tmp / "s.obj")
        session.select_export("obj:1")
        session.export()
        self.assertEqual(sha256((self.tmp / "s.obj").read_bytes()), FROZEN_OBJ_1337)
        self.assertEqual(dialogs.asked[-1][1:3], ("short_sword_seed1337_v1_obj1.obj", ".obj"))
        self.assertEqual(session.view_model().status, "Export complete: obj:1 → s.obj")
        dialogs.export_path = self.tmp / "rich.obj"
        session.select_export("obj:2")
        session.export()
        self.assertTrue((self.tmp / "rich.mtl").is_file())
        self.assertEqual(session.view_model().status, "Export complete: obj:2 → rich.obj (+ rich.mtl)")

    def test_save_preview_png(self):
        from forge.render import decode_png
        session, _ = self.generated(preview_path=self.tmp / "p.png")
        session.save_preview()
        w, h, pixels, text = decode_png((self.tmp / "p.png").read_bytes())
        self.assertEqual((w, h), (96, 192))
        self.assertIn("forge.preview", text)

    def test_16_load_step2_record_restores_explicit_state(self):
        session, dialogs = make_session(dialogs=FakeDialogs(open_path=EXAMPLE))
        session.load_record()
        s, vm = session.state, session.view_model()
        self.assertEqual(dialogs.errors, [])
        self.assertEqual((s.asset_type, s.seed_text, s.generator_version, s.presentation_version,
                          s.preview_version, s.view), ("short_sword", "1337", 1, 1, 1, "three_quarter"))
        rows = dict(vm.details)
        self.assertEqual(rows["record_content_sha256"],
                         "447fcfe4e6dad11650043c47c31b184e1fb3d493473a8bde74f744c15e4cf4f0")
        self.assertEqual(rows["pixels_sha256"], GOLDEN_1337_PIXELS_DEFAULT + " (matches record)")
        self.assertEqual(vm.status, "Loaded asset_record_seed1337.json: 7 checks passed")

    def test_17_malformed_record_load_is_controlled_and_keeps_current_asset(self):
        (self.tmp / "bad.json").write_text("{nope")
        session, dialogs = self.generated(open_path=self.tmp / "bad.json")
        current = session.state.current
        session.load_record()
        self.assertEqual(dialogs.errors[-1][0], "Could not load record")
        self.assertIs(session.state.current, current)
        self.assertTrue(session.view_model().status.startswith("Error:"))

    def test_18_record_with_unknown_asset_type_is_controlled(self):
        rec = json.loads(EXAMPLE.read_text())
        rec["asset_type"] = "armor"
        (self.tmp / "armor.json").write_text(json.dumps(rec))
        session, dialogs = make_session(dialogs=FakeDialogs(open_path=self.tmp / "armor.json"))
        session.load_record()
        title, message = dialogs.errors[-1]
        self.assertEqual(title, "Could not load record")
        self.assertIn("unknown asset_type 'armor'", message)
        self.assertIsNone(session.state.current)

    def test_28_save_twice_without_changes_is_identical(self):
        session, dialogs = self.generated(save_path=self.tmp / "a.json")
        session.save_record()
        first = session.state.record_content
        dialogs.save_path = self.tmp / "b.json"
        session.save_record()
        self.assertEqual(session.state.record_content, first)
        self.assertEqual((self.tmp / "a.json").read_bytes(), (self.tmp / "b.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
