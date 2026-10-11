"""Step 2.5: generic record / export / preview dispatch reproduces frozen outputs."""

import contextlib
import copy
import dataclasses
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge import obj_bytes
from forge.catalog import REGISTRY
from forge.cli import main
from forge.errors import UnknownAssetTypeError, UnknownExportFormatError, UnsupportedVersionError
from forge.record import (
    build_record,
    dumps_record,
    load_record,
    loads_record,
    record_content_sha256,
    validate_record,
)
from forge.registry import (
    exporter_for,
    generate_asset,
    present_asset,
    render_asset_preview,
)
from forge_test_support import REPO_ROOT, sha256
from registry_fixtures import registry_with_sword_v2, registry_with_tetra, reversed_registry, spying_registry
from step2_support import (
    GOLDEN_1337,
    GOLDEN_1337_PIXELS_DEFAULT,
    GOLDEN_1337_PIXELS_SMALL,
    GOLDEN_1337_RECORD_CONTENT_NO_PREVIEW,
    SMALL,
    presented,
)

EXAMPLE = REPO_ROOT / "examples" / "asset_record_seed1337.json"
FROZEN_OBJ_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"
EXAMPLE_CONTENT_SHA256 = "447fcfe4e6dad11650043c47c31b184e1fb3d493473a8bde74f744c15e4cf4f0"


class TestRecordDispatch(unittest.TestCase):
    def test_11_step2_record_loads_through_generic_dispatch(self):
        reg, spies = spying_registry()
        loaded = load_record(EXAMPLE, registry=reg)
        self.assertEqual(spies["generate"].calls, 1)   # geometry came through the registry...
        self.assertEqual(spies["derive"].calls, 1)     # ...and so did presentation
        self.assertEqual(loaded.spec.asset_type, "short_sword")
        self.assertEqual(loaded.asset.seed, 1337)

    def test_12_seed_1337_record_reproduces_all_frozen_hashes(self):
        loaded = load_record(EXAMPLE)
        self.assertEqual(loaded.verified, ("record_content_sha256", "materials", "geometry_sha256",
                                           "obj_format1_sha256", "normals_sha256", "uvs_sha256", "materials_sha256"))
        self.assertEqual(loaded.record_content_sha256, EXAMPLE_CONTENT_SHA256)
        for key, value in GOLDEN_1337.items():
            self.assertEqual(loaded.spec.integrity[key], value, key)

    def test_13_step1_obj_format_1_hash_is_exact(self):
        a = generate_asset(REGISTRY, "short_sword", 1337, 1)
        self.assertEqual(sha256(obj_bytes(a)), FROZEN_OBJ_1337)
        self.assertEqual(sha256(obj_bytes(load_record(EXAMPLE).asset)), FROZEN_OBJ_1337)

    def test_14_step2_preview_record_reproduces_pixel_hash(self):
        loaded = load_record(EXAMPLE)
        image = render_asset_preview(REGISTRY, loaded.presented, loaded.spec.preview)
        self.assertEqual(image.pixels_sha256, loaded.spec.expected_pixels_sha256)
        self.assertEqual(image.pixels_sha256, GOLDEN_1337_PIXELS_DEFAULT)

    def test_19_unknown_record_asset_type_refuses_before_generation(self):
        reg, spies = spying_registry()
        rec = json.loads(EXAMPLE.read_text())
        rec["asset_type"] = "armor"
        with mock.patch("forge.sword.v1.generate", side_effect=AssertionError("generated anyway")):
            with self.assertRaises(UnknownAssetTypeError):
                loads_record(json.dumps(rec), registry=reg)
            with self.assertRaises(UnknownAssetTypeError):
                validate_record(rec, registry=reg)
        self.assertEqual(spies["generate"].calls, 0)

    def test_20a_presentation_version_mismatch_refuses_before_generation(self):
        reg, spies = spying_registry()
        rec = json.loads(EXAMPLE.read_text())
        rec["presentation"]["presentation_version"] = 2
        with self.assertRaises(UnsupportedVersionError):
            loads_record(json.dumps(rec), registry=reg)
        self.assertEqual((spies["generate"].calls, spies["derive"].calls), (0, 0))

    def test_20b_presentation_version_mismatch_refuses_before_preview_and_export(self):
        reg, spies = spying_registry()
        p = presented(1337)
        forged = dataclasses.replace(p, versions=dataclasses.replace(p.versions, presentation_version=2))
        with self.assertRaises(UnsupportedVersionError):
            render_asset_preview(reg, forged, SMALL["front"])
        self.assertEqual(spies["preview"].calls, 0)
        with tempfile.TemporaryDirectory() as tmp:
            from forge.registry import export_asset
            with self.assertRaises(UnsupportedVersionError):
                export_asset(reg, forged.asset, forged, "obj", 2, Path(tmp) / "x.obj")
            self.assertEqual(spies["export"][1].calls, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_21_registry_state_does_not_alter_hashes(self):
        base = build_record(presented(1337), forge_version="x")
        for reg in (reversed_registry(), registry_with_tetra(), registry_with_sword_v2()):
            a = generate_asset(reg, "short_sword", 1337, 1)
            p = present_asset(reg, a, reg.presentation("forge.presentation", 1).versions)
            rec = build_record(p, forge_version="x", registry=reg)
            self.assertEqual(rec, base)
            self.assertEqual(record_content_sha256(rec), GOLDEN_1337_RECORD_CONTENT_NO_PREVIEW)
            self.assertEqual(loads_record(dumps_record(rec), registry=reg).verified, load_record(EXAMPLE).verified)
        text = dumps_record(base)
        for leak in ("object at", "0x", "<", "AssetEntry", "Registry", "function", "lambda", "forge.assets"):
            self.assertNotIn(leak, text)

    def test_asset_without_an_export_format_refuses(self):
        reg = registry_with_tetra()
        with self.assertRaises(UnknownExportFormatError):
            exporter_for(reg, "test_tetra", "obj", 1)


class TestPreviewDispatch(unittest.TestCase):
    def test_preview_resolves_through_registry(self):
        reg, spies = spying_registry()
        for view, settings in SMALL.items():
            img = render_asset_preview(reg, presented(1337), settings)
            self.assertEqual(img.pixels_sha256, GOLDEN_1337_PIXELS_SMALL[view])
        self.assertEqual(spies["preview"].calls, 3)

    def test_preview_requires_presentation_compatibility_and_capability(self):
        from forge.errors import UnknownPreviewError
        from forge.registry import build_registry
        from registry_fixtures import production_tables
        t = production_tables()
        reg, spies = spying_registry()
        no_preview_family = build_registry(**{**t, "presentations": tuple(
            dataclasses.replace(p, preview_versions=()) for p in t["presentations"])})
        with self.assertRaises(UnsupportedVersionError):
            render_asset_preview(no_preview_family, presented(1337), SMALL["front"])
        with self.assertRaises(UnsupportedVersionError):   # record carries a v1 preview the family can't render
            validate_record(json.loads(EXAMPLE.read_text()), registry=no_preview_family)
        sword = t["assets"][0]
        no_capability = build_registry(**{**t, "assets": (dataclasses.replace(
            sword, descriptor=dataclasses.replace(sword.descriptor, preview_id=None)),)})
        with self.assertRaises(UnknownPreviewError):
            render_asset_preview(no_capability, presented(1337), SMALL["front"])
        self.assertEqual(spies["preview"].calls, 0)


class TestCliRouting(unittest.TestCase):
    def run_main(self, argv, registry=REGISTRY):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv, registry=registry)
        return code, out.getvalue(), err.getvalue()

    def test_generic_generate_matches_legacy_sword(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_main(["sword", "--seed", "1337", "--out", f"{tmp}/s.obj"])
            b = self.run_main(["generate", "short_sword", "--seed", "1337", "--generator-version", "1",
                               "--export", "obj:1", "--out", f"{tmp}/s.obj"])
            self.assertEqual(a, b)
            self.assertEqual(sha256(Path(tmp, "s.obj").read_bytes()), FROZEN_OBJ_1337)

    def test_sword_alias_stays_pinned_when_newer_generator_is_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_main(["sword", "--seed", "1337", "--out", f"{tmp}/s.obj"],
                                         registry=registry_with_sword_v2())
            self.assertEqual(code, 0)
            self.assertIn("generator_version  1", out)
            self.assertEqual(sha256(Path(tmp, "s.obj").read_bytes()), FROZEN_OBJ_1337)

    def test_generate_requires_explicit_versions(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main(["generate", "short_sword", "--seed", "1"])
        self.assertEqual(ctx.exception.code, 2)
        code, _, err = self.run_main(["generate", "short_sword", "--seed", "1", "--generator-version", "1",
                                      "--save", "r.json"])
        self.assertEqual(code, 2)
        self.assertIn("--presentation-version is required", err)

    def test_generate_errors(self):
        cases = {
            ("armor",): "unknown asset_type",
            ("short_sword", "--export", "fbx:1"): "unknown export format",
            ("short_sword", "--export", "obj:3"): "unsupported export version",
            ("short_sword", "--export", "obj"): "FORMAT:VERSION",
            ("short_sword", "--out", "x.obj"): "--out requires --export",
        }
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                for extra, needle in cases.items():
                    with self.subTest(args=extra):
                        argv = ["generate", extra[0], "--seed", "1", "--generator-version", "1", *extra[1:]]
                        code, _, err = self.run_main(argv)
                        self.assertEqual(code, 2)
                        self.assertIn(needle, err)
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally:
                os.chdir(cwd)


class TestStep2RecordCompatibility(unittest.TestCase):
    def test_example_record_is_untouched_and_still_valid(self):
        raw = json.loads(EXAMPLE.read_text())
        self.assertEqual(raw["record_version"], 1)       # no schema change was needed
        spec = validate_record(copy.deepcopy(raw))
        self.assertEqual((spec.asset_type, spec.seed, spec.generator_version), ("short_sword", 1337, 1))


if __name__ == "__main__":
    unittest.main()
