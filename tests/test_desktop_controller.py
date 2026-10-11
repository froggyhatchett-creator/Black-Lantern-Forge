"""Step 2.75: the desktop controller drives the frozen registry pipeline (headless)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge.catalog import REGISTRY
from forge.record import dumps_record, validate_record
from forge_desktop import controller as controller_module
from forge_desktop.controller import ForgeActionError, ForgeController
from forge_test_support import REPO_ROOT, sha256
from desktop_support import SMALL_PREVIEW
from registry_fixtures import registry_with_sword_v2, registry_with_tetra, spying_registry
from step2_support import GOLDEN_1337, GOLDEN_1337_PIXELS_DEFAULT, GOLDEN_1337_PIXELS_SMALL

FROZEN_OBJ_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"
GOLDEN_1337_OBJ2 = "69a545afc45357397d68093fb1e7e6f292e97fba2cbaacc522b943e2e40d1010"  # named sword.obj/.mtl
EXAMPLE = REPO_ROOT / "examples" / "asset_record_seed1337.json"


def small():
    return ForgeController(preview_size=SMALL_PREVIEW)


class TestGenerate(unittest.TestCase):
    def test_01_generates_short_sword_through_registry(self):
        reg, spies = spying_registry()
        c = ForgeController(reg, preview_size=SMALL_PREVIEW)
        r = c.generate("short_sword", "1337", 1, 1)
        self.assertEqual((spies["generate"].calls, spies["derive"].calls), (1, 1))
        self.assertEqual((r.asset_type, r.seed, r.generator_version), ("short_sword", 1337, 1))

    def test_02_controller_never_names_the_frozen_generator(self):
        for name in ("generate_sword", "derive_presentation", "render_preview", "obj_bytes", "write_obj",
                     "write_enriched_obj", "SwordAsset", "generate_short_sword_v1"):
            self.assertFalse(hasattr(controller_module, name), name)

    def test_03_uses_explicit_generator_version(self):
        with mock.patch.object(controller_module, "generate_asset", wraps=controller_module.generate_asset) as spy:
            small().generate("short_sword", "1337", 1, 1)
        self.assertEqual(spy.call_args.args[1:], ("short_sword", 1337, 1))
        self.assertIs(type(spy.call_args.args[3]), int)
        with self.assertRaises(ForgeActionError) as ctx:
            small().generate("short_sword", "1337", None, 1)
        self.assertEqual(ctx.exception.title, "Choose a generator version")
        with self.assertRaises(ForgeActionError) as ctx:
            small().generate("short_sword", "1337", 2, 1)
        self.assertIn("generator_version", ctx.exception.message)
        c = ForgeController(registry_with_sword_v2(), preview_size=SMALL_PREVIEW)
        self.assertEqual(c.options("short_sword").generator_versions, (1, 2))
        self.assertEqual(c.generate("short_sword", "1337", 1, 1).generator_version, 1)  # exact, not newest
        self.assertEqual(c.generate("short_sword", "1337", 2, 1).generator_version, 2)

    def test_04_uses_explicit_presentation_version(self):
        with mock.patch.object(controller_module, "present_asset", wraps=controller_module.present_asset) as spy:
            small().generate("short_sword", "1337", 1, 1)
        self.assertEqual(spy.call_args.args[2].to_dict(), {"presentation_version": 1, "normals_version": 1,
                                                           "uv_version": 1, "material_version": 1})
        with self.assertRaises(ForgeActionError) as ctx:
            small().generate("short_sword", "1337", 1, None)
        self.assertEqual(ctx.exception.title, "Choose a presentation version")
        with self.assertRaises(ForgeActionError):
            small().generate("short_sword", "1337", 1, 2)

    def test_07_valid_seeds_generate(self):
        c = small()
        for text, seed in (("0", 0), ("18446744073709551615", (1 << 64) - 1), ("  42 ", 42)):
            self.assertEqual(c.generate("short_sword", text, 1, 1).seed, seed)

    def test_08_invalid_seed_is_a_controlled_error(self):
        for bad in ("abc", "-1", "1.5", "", "18446744073709551616", "0x10", "4 2"):
            with self.subTest(seed=bad):
                with self.assertRaises(ForgeActionError) as ctx:
                    small().generate("short_sword", bad, 1, 1)
                self.assertEqual(ctx.exception.title, "Invalid seed")
                self.assertNotIn("Traceback", ctx.exception.message)

    def test_18_unknown_asset_type_is_a_controlled_error(self):
        for bad in ("armor", "", None):
            with self.assertRaises(ForgeActionError) as ctx:
                small().generate(bad, "1", 1, 1)
            self.assertEqual(ctx.exception.title, "Unknown asset type")


class TestChoicesComeFromRegistry(unittest.TestCase):
    def test_05_exporters_populate_from_registry(self):
        opts = small().options("short_sword")
        d = REGISTRY.asset("short_sword").descriptor
        self.assertEqual(tuple((e.format_id, e.format_version) for e in opts.exporters), d.export_formats)
        self.assertEqual([e.key for e in opts.exporters], ["glb:1", "obj:1", "obj:2"])
        self.assertEqual(opts.exporters[1].label, "OBJ format 1 · geometry only")
        self.assertEqual(opts.exporters[2].label, "OBJ format 2 · with presentation data · + materials file")
        self.assertEqual(opts.views, ("three_quarter", "front", "side"))
        self.assertEqual(small().preview_versions("short_sword", 1), (1,))
        tetra = ForgeController(registry_with_tetra()).options("test_tetra")
        self.assertEqual(tetra.exporters, ())       # offers none, so none are shown

    def test_06_unsupported_export_is_not_selectable(self):
        c = small()
        r = c.generate("short_sword", "1337", 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            for key in ("obj:3", "fbx:1", "glb:2", "obj"):
                with self.subTest(key=key):
                    with self.assertRaises(ForgeActionError) as ctx:
                        c.export(r, key, Path(tmp) / "x.obj")
                    self.assertEqual(ctx.exception.title, "Export not available")
            self.assertEqual(list(Path(tmp).iterdir()), [])


class TestPreviewAndDetails(unittest.TestCase):
    def test_09_10_metadata_and_preview(self):
        c = small()
        r = c.generate("short_sword", "1337", 1, 1)
        image = c.render(r, c.preview_settings(1, "three_quarter"))
        rows = dict(c.details(r, export_key="obj:1", image=image))
        for key in ("geometry_sha256", "obj_format1_sha256", "normals_sha256", "uvs_sha256", "materials_sha256"):
            self.assertEqual(rows[key], GOLDEN_1337[key], key)
        self.assertEqual(rows["Generator"], "forge.sword v1")
        self.assertEqual(rows["Presentation"], "forge.presentation v1 (normals v1, uv v1, material v1)")
        self.assertEqual(rows["Coordinate convention"], "forge.rh-y-up-meters.grip-origin.v1")
        self.assertEqual(rows["Export format"], "OBJ format 1 · geometry only")
        self.assertEqual(rows["record_content_sha256"], "not saved yet")
        self.assertEqual(rows["pixels_sha256"], GOLDEN_1337_PIXELS_SMALL["three_quarter"])
        self.assertEqual(len(image.pixels), 96 * 192 * 3)

    def test_11_12_13_every_view_matches_the_frozen_renderer(self):
        c = small()
        r = c.generate("short_sword", "1337", 1, 1)
        for view in ("front", "side", "three_quarter"):
            with self.subTest(view=view):
                self.assertEqual(c.render(r, c.preview_settings(1, view)).pixels_sha256,
                                 GOLDEN_1337_PIXELS_SMALL[view])

    def test_22_default_preview_pixel_hash_is_unchanged(self):
        c = ForgeController()   # default size: the frozen 480x960, ssaa 2 settings
        r = c.generate("short_sword", "1337", 1, 1)
        self.assertEqual(c.render(r, c.preview_settings(1, "three_quarter")).pixels_sha256, GOLDEN_1337_PIXELS_DEFAULT)


class TestPersistenceAndExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.c = small()
        self.r = self.c.generate("short_sword", "1337", 1, 1)
        self.image = self.c.render(self.r, self.c.preview_settings(1, "three_quarter"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_14_save_uses_the_existing_record_format(self):
        path, content = self.c.save_record(self.r, self.tmp / "gui.json", self.image)
        record = json.loads(path.read_text())
        spec = validate_record(record)
        self.assertEqual(record["record_format"], "black-lantern-forge/asset-record")
        self.assertEqual(record["record_version"], 1)
        self.assertEqual((spec.asset_type, spec.seed, spec.generator_version), ("short_sword", 1337, 1))
        self.assertEqual(record["integrity"]["record_content_sha256"], content)
        self.assertEqual(record["preview"]["pixels_sha256"], self.image.pixels_sha256)
        self.assertEqual(path.read_text(), dumps_record(record))   # byte-identical to the Step 2 writer

    def test_15_cli_loads_a_gui_saved_record(self):
        path, content = self.c.save_record(self.r, self.tmp / "gui.json", self.image)
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        res = subprocess.run([sys.executable, "-m", "forge", "load", str(path)], env=env, capture_output=True,
                             text=True, cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(content, res.stdout)
        res = subprocess.run([sys.executable, "-m", "forge", "preview", str(path)], env=env, capture_output=True,
                             text=True, cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("verified against record", res.stdout)

    def test_16_loads_the_existing_step2_record(self):
        loaded = self.c.load_record(EXAMPLE)
        self.assertEqual(loaded.result.seed, 1337)
        self.assertEqual(loaded.record_content_sha256,
                         "447fcfe4e6dad11650043c47c31b184e1fb3d493473a8bde74f744c15e4cf4f0")
        self.assertEqual(len(loaded.checks), 7)
        self.assertEqual(loaded.preview.to_dict(), {"preview_version": 1, "view": "three_quarter",
                                                    "width": 480, "height": 960, "ssaa": 2})
        self.assertEqual(loaded.expected_pixels_sha256, GOLDEN_1337_PIXELS_DEFAULT)

    def test_17_malformed_and_tampered_records_are_controlled_errors(self):
        (self.tmp / "garbage.json").write_text("{not json")
        rec = json.loads(EXAMPLE.read_text())
        (self.tmp / "armor.json").write_text(json.dumps({**rec, "asset_type": "armor"}))
        tampered = json.loads(EXAMPLE.read_text())
        tampered["presentation"]["materials"]["blade"]["roughness"] = 0.9
        (self.tmp / "tampered.json").write_text(json.dumps(tampered))
        cases = {"garbage.json": ("Could not load record", "not valid JSON"),
                 "armor.json": ("Could not load record", "unknown asset_type"),
                 "tampered.json": ("Record failed verification", "record_content_sha256"),
                 "missing.json": ("Could not load record", "not found")}
        for name, (title, needle) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ForgeActionError) as ctx:
                    self.c.load_record(self.tmp / name)
                self.assertEqual(ctx.exception.title, title)
                self.assertIn(needle, ctx.exception.message)

    def test_19_21_export_format_1_is_frozen(self):
        (path,) = self.c.export(self.r, "obj:1", self.tmp / "s.obj")
        self.assertEqual(sha256(path.read_bytes()), FROZEN_OBJ_1337)

    def test_20_export_format_2_is_valid(self):
        obj, mtl = self.c.export(self.r, "obj:2", self.tmp / "sword.obj")
        self.assertEqual(sha256(obj.read_bytes()), GOLDEN_1337_OBJ2)
        self.assertTrue(mtl.is_file())
        text = obj.read_text()
        self.assertIn("mtllib sword.mtl", text)
        self.assertIn("# obj_format: 2", text)

    def test_28_saving_twice_is_deterministic(self):
        a, ca = self.c.save_record(self.r, self.tmp / "a.json", self.image)
        b, cb = self.c.save_record(self.r, self.tmp / "b.json", self.image)
        self.assertEqual(ca, cb)
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_save_and_export_failures_are_controlled(self):
        with self.assertRaises(ForgeActionError) as ctx:
            self.c.save_record(self.r, self.tmp / "record.txt", self.image)
        self.assertEqual(ctx.exception.title, "Save failed")
        with self.assertRaises(ForgeActionError) as ctx:
            self.c.export(self.r, "obj:1", self.tmp / "s.fbx")
        self.assertEqual(ctx.exception.title, "Export failed")
        with self.assertRaises(ForgeActionError) as ctx:
            self.c.save_preview(self.r, self.image, self.tmp / "p.jpg")
        self.assertEqual(ctx.exception.title, "Save preview failed")


class TestRegistryUntouched(unittest.TestCase):
    def test_26_controller_does_not_mutate_registry_state(self):
        tables = ("assets", "generators", "presentations", "exporters", "previews")
        before = {t: (getattr(REGISTRY, t), dict(getattr(REGISTRY, t))) for t in tables}
        c = small()
        r = c.generate("short_sword", "7", 1, 1)
        image = c.render(r, c.preview_settings(1, "side"))
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = c.save_record(r, Path(tmp) / "r.json", image)
            c.load_record(path)
            c.export(r, "obj:2", Path(tmp) / "s.obj")
        for t in tables:
            self.assertIs(getattr(REGISTRY, t), before[t][0], t)
            self.assertEqual(dict(getattr(REGISTRY, t)), before[t][1], t)
        self.assertIs(c.registry, REGISTRY)


if __name__ == "__main__":
    unittest.main()
