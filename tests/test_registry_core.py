"""Step 2.5: registry resolution, explicit versions, errors, immutability, ordering."""

import dataclasses
import tempfile
import unittest
from pathlib import Path

from forge import catalog, generate_sword, obj_bytes
from forge import registry as registry_module
from forge.catalog import REGISTRY
from forge.errors import (
    ExportError,
    RecordFormatError,
    RegistryConfigurationError,
    RegistryError,
    UnknownAssetTypeError,
    UnknownExportFormatError,
    UnknownGeneratorError,
    UnknownPresentationError,
    UnknownPreviewError,
    UnsupportedExportVersionError,
    UnsupportedGeneratorVersionError,
    UnsupportedVersionError,
)
from forge.presentation import derive_presentation
from forge.registry import (
    AssetDescriptor,
    build_registry,
    export_asset,
    generate_asset,
    present_asset,
)
from forge_test_support import sha256
from registry_fixtures import production_tables, registry_with_sword_v2, reversed_registry
from step2_support import GOLDEN_1337, presented

FROZEN_OBJ_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"
GOLDEN_1337_OBJ2 = "69a545afc45357397d68093fb1e7e6f292e97fba2cbaacc522b943e2e40d1010"  # mtllib sword.mtl


class TestResolution(unittest.TestCase):
    def test_01_short_sword_resolves_through_asset_registry(self):
        d = REGISTRY.asset("short_sword").descriptor
        self.assertEqual(d, AssetDescriptor(
            asset_type="short_sword", display_name="procedural short sword", generator_id="forge.sword",
            presentation_id="forge.presentation", export_formats=(("glb", 1), ("obj", 1), ("obj", 2)),
            preview_id="forge.preview", record_versions=(1,),
            convention_id="forge.rh-y-up-meters.grip-origin.v1",
            components=("blade", "guard", "grip", "pommel")))
        self.assertEqual(REGISTRY.asset_types(), ("curved_sword", "dagger", "great_sword", "long_sword", "mace",
                                                  "one_hand_axe", "short_sword", "two_hand_axe", "war_hammer"))

    def test_descriptor_is_pure_routing_data(self):
        d = REGISTRY.asset("short_sword").descriptor
        hash(d)  # hashable: immutable values only
        for f in dataclasses.fields(d):
            value = getattr(d, f.name)
            self.assertFalse(callable(value), f.name)
            self.assertIsInstance(value, (str, tuple, type(None)), f.name)

    def test_02_generator_version_1_resolves_exactly(self):
        g = REGISTRY.generator("forge.sword", 1)
        self.assertEqual((g.generator_id, g.generator_version, g.asset_type), ("forge.sword", 1, "short_sword"))
        a = g.generate(1337)
        self.assertEqual(a.generator_version, 1)
        self.assertEqual(sha256(obj_bytes(a)), FROZEN_OBJ_1337)
        self.assertEqual(REGISTRY.generator_versions("forge.sword"), (1,))

    def test_03_unknown_generator_version_refuses(self):
        for bad in (0, 2, -1, 999, True, 1.0, "1", None):
            with self.subTest(version=bad):
                with self.assertRaises(UnsupportedGeneratorVersionError) as ctx:
                    REGISTRY.generator("forge.sword", bad)
                self.assertIn("supported", str(ctx.exception))
                with self.assertRaises(UnsupportedGeneratorVersionError):
                    generate_asset(REGISTRY, "short_sword", 1, bad)
        with self.assertRaises(UnknownGeneratorError):
            REGISTRY.generator("forge.axe", 1)

    def test_04_unknown_asset_type_refuses(self):
        for bad in ("armor", "", "Short_Sword", "short_sword ", None, 5, ["short_sword"]):
            with self.subTest(asset_type=bad):
                with self.assertRaises(UnknownAssetTypeError) as ctx:
                    REGISTRY.asset(bad)
                self.assertIsInstance(ctx.exception, RegistryError)
                self.assertIsInstance(ctx.exception, RecordFormatError)  # Step 2 compatibility
                self.assertIn("asset_type", str(ctx.exception))

    def test_05_known_presentation_version_resolves(self):
        p = REGISTRY.presentation("forge.presentation", 1)
        self.assertEqual((p.normals_version, p.uv_version, p.material_version, p.preview_versions), (1, 1, 1, (1,)))
        self.assertIs(p.derive, derive_presentation)
        self.assertEqual(p.versions.to_dict(), {"presentation_version": 1, "normals_version": 1,
                                                "uv_version": 1, "material_version": 1})

    def test_06_unknown_presentation_version_refuses(self):
        for bad in (0, 2, True, 1.0, "1", None):
            with self.subTest(version=bad):
                with self.assertRaises(UnsupportedVersionError) as ctx:
                    REGISTRY.presentation("forge.presentation", bad)
                self.assertIn("presentation_version", str(ctx.exception))
        with self.assertRaises(UnknownPresentationError):
            REGISTRY.presentation("forge.shader", 1)
        a = generate_sword(1, 1)
        wrong = dataclasses.replace(REGISTRY.presentation("forge.presentation", 1).versions, uv_version=2)
        with self.assertRaises(UnsupportedVersionError) as ctx:
            present_asset(REGISTRY, a, wrong)  # family v1 pins uv v1
        self.assertIn("uv_version", str(ctx.exception))

    def test_07_obj_format_1_resolves_through_export_registry(self):
        e = REGISTRY.exporter("obj", 1)
        self.assertEqual((e.extension, e.needs_presentation, e.extra_file_labels), (".obj", False, ()))
        with tempfile.TemporaryDirectory() as tmp:
            (path,) = export_asset(REGISTRY, generate_sword(1337, 1), None, "obj", 1, Path(tmp) / "s.obj")
            self.assertEqual(sha256(path.read_bytes()), FROZEN_OBJ_1337)

    def test_08_obj_format_2_resolves_through_export_registry(self):
        e = REGISTRY.exporter("obj", 2)
        self.assertTrue(e.needs_presentation)
        self.assertEqual(e.presentations, (("forge.presentation", 1), ("forge.blade-presentation", 1),
                                           ("forge.hafted-presentation", 1)))
        p = presented(1337)
        with tempfile.TemporaryDirectory() as tmp:
            obj, mtl = export_asset(REGISTRY, p.asset, p, "obj", 2, Path(tmp) / "sword.obj")
            self.assertEqual(sha256(obj.read_bytes()), GOLDEN_1337_OBJ2)
            self.assertEqual(mtl.name, "sword.mtl")
            with self.assertRaises(UnsupportedVersionError):
                export_asset(REGISTRY, p.asset, None, "obj", 2, Path(tmp) / "x.obj")  # needs presentation
            with self.assertRaises(ExportError):
                export_asset(REGISTRY, p.asset, p, "obj", 2, Path(tmp) / "x.fbx")

    def test_09_unknown_export_format_refuses(self):
        for bad in ("fbx", "gltf", "usd", "OBJ", "", None, 1):
            with self.subTest(fmt=bad):
                with self.assertRaises(UnknownExportFormatError) as ctx:
                    REGISTRY.exporter(bad, 1)
                self.assertIsInstance(ctx.exception, RegistryError)

    def test_10_unsupported_export_version_refuses(self):
        for bad in (0, 3, -1, True, 1.0, "2", None):
            with self.subTest(version=bad):
                with self.assertRaises(UnsupportedExportVersionError) as ctx:
                    REGISTRY.exporter("obj", bad)
                self.assertIsInstance(ctx.exception, UnsupportedVersionError)

    def test_preview_resolution(self):
        self.assertEqual(REGISTRY.preview("forge.preview", 1).preview_version, 1)
        with self.assertRaises(UnsupportedVersionError):
            REGISTRY.preview("forge.preview", 2)
        with self.assertRaises(UnknownPreviewError):
            REGISTRY.preview("forge.raytrace", 1)


class TestExplicitVersions(unittest.TestCase):
    def test_16_no_implicit_latest(self):
        for obj in (REGISTRY, registry_module, catalog):
            for name in dir(obj):
                self.assertFalse(any(w in name.lower() for w in ("latest", "newest", "default", "current")),
                                 f"{obj!r} exposes {name}")
        with self.assertRaises(TypeError):
            REGISTRY.generator("forge.sword")
        with self.assertRaises(TypeError):
            REGISTRY.presentation("forge.presentation")
        with self.assertRaises(TypeError):
            REGISTRY.exporter("obj")
        with self.assertRaises(TypeError):
            generate_asset(REGISTRY, "short_sword", 1337)

    def test_17_lookup_is_exact_even_when_a_newer_version_exists(self):
        reg = registry_with_sword_v2()
        self.assertEqual(reg.generator_versions("forge.sword"), (1, 2))
        v1 = generate_asset(reg, "short_sword", 1337, 1)
        v2 = generate_asset(reg, "short_sword", 1337, 2)
        self.assertEqual((v1.generator_version, v2.generator_version), (1, 2))
        self.assertEqual(sha256(obj_bytes(v1)), FROZEN_OBJ_1337)
        with self.assertRaises(UnsupportedGeneratorVersionError):
            generate_asset(reg, "short_sword", 1337, 3)


class TestImmutabilityAndOrder(unittest.TestCase):
    def test_registry_is_read_only(self):
        with self.assertRaises(TypeError):
            REGISTRY.assets["armor"] = None
        with self.assertRaises(TypeError):
            REGISTRY.generators[("forge.sword", 2)] = None
        with self.assertRaises(dataclasses.FrozenInstanceError):
            REGISTRY.assets = {}
        with self.assertRaises(dataclasses.FrozenInstanceError):
            REGISTRY.asset("short_sword").descriptor.generator_id = "forge.axe"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            REGISTRY.exporter("obj", 1).extension = ".txt"

    def test_15_insertion_order_does_not_change_behavior(self):
        rev = reversed_registry()
        for field in ("assets", "generators", "presentations", "exporters", "previews"):
            self.assertEqual(dict(getattr(rev, field)), dict(getattr(REGISTRY, field)), field)
        self.assertEqual(rev.export_versions("obj"), REGISTRY.export_versions("obj"))
        self.assertEqual(rev.asset_types(), REGISTRY.asset_types())
        for reg in (REGISTRY, rev):
            a = generate_asset(reg, "short_sword", 1337, 1)
            p = present_asset(reg, a, reg.presentation("forge.presentation", 1).versions)
            self.assertEqual(sha256(obj_bytes(a)), FROZEN_OBJ_1337)
            self.assertEqual(registry_module.integrity_hashes(reg, p),
                             {k: GOLDEN_1337[k] for k in ("geometry_sha256", "obj_format1_sha256",
                                                          "normals_sha256", "uvs_sha256", "materials_sha256")})
            self.assertEqual(list(registry_module.integrity_hashes(reg, p)),
                             ["geometry_sha256", "obj_format1_sha256", "normals_sha256", "uvs_sha256",
                              "materials_sha256"])

    def test_build_registry_rejects_inconsistent_tables(self):
        t = production_tables()
        sword = t["assets"][0]
        d = sword.descriptor
        cases = {
            "duplicate asset": {"assets": t["assets"] * 2},
            "duplicate exporter": {"exporters": t["exporters"] + t["exporters"][:1]},
            "missing generator": {"generators": ()},
            "missing presentation": {"presentations": ()},
            "missing exporter": {"exporters": t["exporters"][:1]},
            "missing preview": {"previews": ()},
            "unknown convention": {"assets": (dataclasses.replace(
                sword, descriptor=dataclasses.replace(d, convention_id="z-up")),)},
            "duplicate integrity key": {"assets": (dataclasses.replace(
                sword, integrity=sword.integrity + sword.integrity[:1]),)},
            "reserved integrity key": {"assets": (dataclasses.replace(
                sword, integrity=sword.integrity + (("record_content_sha256", sword.integrity[0][1]),)),)},
        }
        for label, override in cases.items():
            with self.subTest(label):
                with self.assertRaises(RegistryConfigurationError):
                    build_registry(**{**t, **override})


if __name__ == "__main__":
    unittest.main()
