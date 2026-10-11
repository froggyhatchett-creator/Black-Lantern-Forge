"""Step 5A tests 1-6 and 29 (+ CLI, lineage and bayonet-groundwork checks): the registered blade families.

1-4   each family is registered with an explicit identity: generator forge.<family> v1,
      presentation forge.blade-presentation v1, preview forge.preview.fit v1, exports glb:1 and obj:2
5     the short_sword registration is unchanged
6     every version is explicit; nothing resolves to "latest"
29    every asset has the four required components, in order
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from arsenal_support import (
    BLADE_PRESENTATION,
    COMPONENTS,
    FAMILIES,
    FIT_PREVIEW,
    FROZEN_OBJ1_1337,
    GENERATOR_IDS,
    LINEUP_SEEDS,
    asset,
    sha256,
)
from forge.assets import blades, short_sword
from forge.blades import lineage
from forge.blades.lineage import BAYONET_LINEAGE, BLADE_CLASSES, RESERVED_SOCKETS, MountSpec, grip_hands
from forge.catalog import ASSET_ENTRIES, ENGINE_ADAPTERS, REGISTRY
from forge.errors import (
    ForgeError,
    GenerationError,
    UnknownAssetTypeError,
    UnsupportedGeneratorVersionError,
    UnsupportedVersionError,
)
from forge.registry import generate_asset, present_asset
from forge_test_support import REPO_ROOT

CONVENTION = "forge.rh-y-up-meters.grip-origin.v1"


class _Stub:
    def __init__(self, a):
        self.components = ()


def presented_stub(a):
    """engine_tags reads presented.components only for material tags; none are needed here."""
    return _Stub(a)


def run_cli(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run([sys.executable, "-m", "forge", *args], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=300)


class TestRegistered(unittest.TestCase):
    def check_family(self, family):
        self.assertIn(family, REGISTRY.asset_types())
        d = REGISTRY.asset(family).descriptor
        self.assertEqual(d.asset_type, family)
        self.assertEqual(d.generator_id, GENERATOR_IDS[family])
        self.assertEqual(REGISTRY.generator_versions(d.generator_id), (1,))
        gen = REGISTRY.generator(d.generator_id, 1)
        self.assertEqual((gen.asset_type, gen.generator_version), (family, 1))
        self.assertEqual(d.presentation_id, BLADE_PRESENTATION)
        self.assertEqual(REGISTRY.presentation_versions(BLADE_PRESENTATION), (1,))
        self.assertEqual(d.preview_id, FIT_PREVIEW)
        self.assertEqual(REGISTRY.preview_versions(FIT_PREVIEW), (1,))
        self.assertEqual(d.export_formats, (("glb", 1), ("obj", 2)))
        self.assertEqual(d.record_versions, (1,))
        self.assertEqual(d.convention_id, CONVENTION)
        self.assertEqual(d.components, COMPONENTS)
        self.assertIn(family, ENGINE_ADAPTERS)
        self.assertEqual([k for k, _ in ASSET_ENTRIES[family].integrity],
                         ["geometry_sha256", "normals_sha256", "uvs_sha256", "materials_sha256"])
        a = asset(family)
        self.assertEqual((a.asset_type, a.generator, a.generator_version, a.seed),
                         (family, GENERATOR_IDS[family], 1, 1337))

    def test_01_dagger_registered(self):
        self.check_family("dagger")

    def test_02_long_sword_registered(self):
        self.check_family("long_sword")

    def test_03_curved_sword_registered(self):
        self.check_family("curved_sword")

    def test_04_great_sword_registered(self):
        self.check_family("great_sword")

    def test_registry_listing_is_explicit_and_sorted(self):
        self.assertEqual(REGISTRY.asset_types(),                         # Step 5B: + the four hafted families
                         ("curved_sword", "dagger", "great_sword", "long_sword", "mace", "one_hand_axe", "short_sword",
                          "two_hand_axe", "war_hammer"))
        self.assertEqual(REGISTRY.generator_ids(), ("forge.curved_sword", "forge.dagger", "forge.great_sword",
                                                    "forge.long_sword", "forge.mace", "forge.one_hand_axe",
                                                    "forge.sword", "forge.two_hand_axe", "forge.war_hammer"))
        self.assertEqual(REGISTRY.presentation_ids(), (BLADE_PRESENTATION, "forge.hafted-presentation",
                                                       "forge.presentation"))
        self.assertEqual(REGISTRY.preview_ids(), ("forge.preview", FIT_PREVIEW))
        self.assertEqual(tuple(e.descriptor.asset_type for e in blades.ASSETS), FAMILIES)
        # importing the family modules registers nothing; forge.catalog lists them explicitly
        self.assertEqual(blades.FAMILIES[0].ASSET_TYPE, "dagger")

    def test_05_short_sword_registration_unchanged(self):
        e = REGISTRY.asset("short_sword")
        self.assertIs(e, short_sword.ASSET)
        self.assertIs(ENGINE_ADAPTERS["short_sword"], short_sword.ENGINE_ADAPTER)
        d = e.descriptor
        self.assertEqual(
            (d.asset_type, d.display_name, d.generator_id, d.presentation_id, d.export_formats, d.preview_id,
             d.record_versions, d.convention_id, d.components),
            ("short_sword", "procedural short sword", "forge.sword", "forge.presentation",
             (("glb", 1), ("obj", 1), ("obj", 2)), "forge.preview", (1,), CONVENTION,
             ("blade", "guard", "grip", "pommel")))
        self.assertEqual([k for k, _ in e.integrity],
                         ["geometry_sha256", "obj_format1_sha256", "normals_sha256", "uvs_sha256", "materials_sha256"])
        self.assertEqual(REGISTRY.generator_versions("forge.sword"), (1,))
        self.assertEqual(REGISTRY.presentation_versions("forge.presentation"), (1,))
        self.assertEqual(REGISTRY.presentation("forge.presentation", 1).preview_versions, (1,))
        self.assertEqual(REGISTRY.preview_versions("forge.preview"), (1,))
        self.assertEqual(REGISTRY.exporter("obj", 1).presentations, ())
        self.assertEqual(REGISTRY.export_versions("obj"), (1, 2))
        self.assertEqual(REGISTRY.export_versions("glb"), (1,))
        # the blade families never offer the frozen short-sword exporter, OBJ format 1
        for family in FAMILIES:
            self.assertNotIn(("obj", 1), REGISTRY.asset(family).descriptor.export_formats)

    def test_06_explicit_versions_required(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                for bad in (None, 0, 2, "1", 1.0, True, "latest"):
                    with self.assertRaises(ForgeError):
                        generate_asset(REGISTRY, family, 1337, bad)
                with self.assertRaises(UnsupportedGeneratorVersionError):
                    generate_asset(REGISTRY, family, 1337, 2)
                a = asset(family)
                for bad in (None, 1, "1"):
                    with self.assertRaises(UnsupportedVersionError):
                        present_asset(REGISTRY, a, bad)
                with self.assertRaises(ForgeError):
                    REGISTRY.presentation(BLADE_PRESENTATION, 2)
                with self.assertRaises(ForgeError):
                    REGISTRY.preview(FIT_PREVIEW, None)
        with self.assertRaises(UnknownAssetTypeError):
            generate_asset(REGISTRY, "axe", 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "dagger", "--seed", "1337", cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertIn("--generator-version", r.stderr)
            r = run_cli("generate", "dagger", "--seed", "1337", "--generator-version", "1", "--save", "x.json",
                        cwd=tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("presentation", (r.stderr + r.stdout).lower())
            self.assertFalse((Path(tmp) / "x.json").exists())

    def test_29_required_components_exist(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    self.assertEqual(a.component_names, COMPONENTS)
                    for name in COMPONENTS:
                        m = a.component(name)
                        self.assertEqual(m.name, name)
                        self.assertGreater(len(m.positions), 0)
                        self.assertGreater(len(m.triangles), 0)
                    self.assertEqual([n for n, _ in a.landmarks],
                                     sorted(["blade_base_center", "blade_tip", "blade_tip_tangent",
                                             "grip_bottom_center", "grip_center", "grip_top_center"]))


class TestCli(unittest.TestCase):
    def test_generate_command_from_the_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "dagger", "--seed", "1337", "--generator-version", "1",
                        "--presentation-version", "1", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("procedural dagger", r.stdout)
            self.assertIn("blade tip", r.stdout)

    def test_every_family_round_trips_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    r = run_cli("generate", family, "--seed", "7", "--generator-version", "1",
                                "--presentation-version", "1", "--export", "glb:1", "--out", f"{family}.forgepkg",
                                "--save", f"{family}.json", "--preview", f"{family}.png", "--width", "64",
                                "--height", "128", "--ssaa", "1", cwd=tmp)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    r = run_cli("load", f"{family}.json", cwd=tmp)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    r = run_cli("validate-package", f"{family}.forgepkg", cwd=tmp)
                    self.assertEqual(r.returncode, 0, r.stderr)

    def test_sword_alias_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("sword", "--seed", "1337", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sha256((Path(tmp) / "output" / "short_sword_seed1337_v1.obj").read_bytes()),
                             FROZEN_OBJ1_1337)
            self.assertNotIn("dagger", r.stdout)

    def test_unknown_family_lists_registered_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "axe", "--seed", "1", "--generator-version", "1", cwd=tmp)
            self.assertNotEqual(r.returncode, 0)
            for family in FAMILIES + ("short_sword",):
                self.assertIn(family, r.stderr)

    def test_json_output_names_the_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "curved_sword", "--seed", "42", "--generator-version", "1",
                        "--presentation-version", "1", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual((data["asset_type"], data["generator"], data["generator_version"], data["seed"]),
                             ("curved_sword", "forge.curved_sword", 1, 42))


class TestLineage(unittest.TestCase):
    """Bayonet groundwork: architecture only. Nothing is registered, generated, exported or mounted."""

    def test_every_family_has_a_blade_class(self):
        self.assertEqual(sorted(BLADE_CLASSES), sorted(FAMILIES))
        for family, cls in BLADE_CLASSES.items():
            self.assertEqual(cls.attachment_roles, ("handheld",), family)
        self.assertEqual(BLADE_CLASSES["dagger"].lineage, "short_blade")
        self.assertEqual(BLADE_CLASSES["curved_sword"].edge, "single")
        self.assertEqual(BLADE_CLASSES["great_sword"].hands, ("two",))
        self.assertEqual(BLADE_CLASSES["long_sword"].hands, ("hand_and_half",))
        self.assertEqual(BLADE_CLASSES["dagger"].hands, ("one",))
        self.assertEqual(BLADE_CLASSES["curved_sword"].hands, ("one", "hand_and_half"))
        for module in blades.FAMILIES:
            self.assertEqual(module.RULES.hands, BLADE_CLASSES[module.ASSET_TYPE].hands)
        self.assertEqual([f for f, c in BLADE_CLASSES.items() if c.bayonet_lineage_parent], ["dagger"])

    def test_bayonet_lineage_is_experimental_and_unregistered(self):
        self.assertEqual((BAYONET_LINEAGE.lineage_id, BAYONET_LINEAGE.parent_family, BAYONET_LINEAGE.status),
                         ("bayonet", "dagger", "experimental"))
        self.assertEqual(BAYONET_LINEAGE.blade_class.lineage, "short_blade")
        self.assertNotIn("bayonet", REGISTRY.asset_types())
        self.assertFalse(any("bayonet" in g for g in REGISTRY.generator_ids()))
        self.assertFalse(any(c.asset_type == "bayonet" for c in ENGINE_ADAPTERS.values()))

    def test_reserved_sockets_are_not_emitted(self):
        self.assertEqual(sorted(RESERVED_SOCKETS), ["socket_mount", "socket_muzzle"])
        for family in FAMILIES:
            sockets = [s.name for s in ENGINE_ADAPTERS[family].sockets(asset(family))]
            self.assertEqual(sockets, ["socket_grip", "socket_tip"])

    def test_mount_spec_schema_validates_and_fails_closed(self):
        ok = (MountSpec("socket", 0.018, 0.021, 0.012), MountSpec("plug", 0.015, 0.0, 0.0),
              MountSpec("lug", 0.016, 0.020, 0.025))
        for spec in ok:
            self.assertIs(spec.validate(), spec)
        bad = (MountSpec("clip", 0.018, 0.021, 0.0), MountSpec("socket", 0.03, 0.035, 0.0),
               MountSpec("socket", 0.018, 0.017, 0.0), MountSpec("plug", 0.015, 0.02, 0.0),
               MountSpec("lug", 0.016, 0.020, 0.2), MountSpec("socket", float("nan"), 0.02, 0.0),
               MountSpec("socket", 18, 0.02, 0.0), MountSpec("socket", 0.018, 0.035, 0.0))
        for spec in bad:
            with self.subTest(spec=spec):
                with self.assertRaises(GenerationError):
                    spec.validate()

    def test_blade_class_rejects_unknown_values(self):
        with self.assertRaises(GenerationError):
            lineage.BladeClass("polearm", "double", ("two",), ("handheld",), False)
        with self.assertRaises(GenerationError):
            lineage.BladeClass("sword", "double", ("two",), ("thrown",), False)
        with self.assertRaises(GenerationError):
            lineage.BladeClass("sword", "double", ("two",), (), False)
        with self.assertRaises(GenerationError):
            lineage.BladeClass("sword", "double", (), ("handheld",), False)
        with self.assertRaises(GenerationError):
            lineage.BladeClass("sword", "double", ("three",), ("handheld",), False)

    def test_grip_hands(self):
        self.assertEqual([grip_hands(x) for x in (0.10, 0.149, 0.15, 0.259, 0.26, 0.40)],
                         ["one", "one", "hand_and_half", "hand_and_half", "two", "two"])
        for family in FAMILIES:
            for seed in range(1, 121):
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    hands = grip_hands(a.params.grip.length)
                    self.assertIn(hands, BLADE_CLASSES[family].hands)
                    self.assertIn(f"hands:{hands}", ENGINE_ADAPTERS[family].tags(a, presented_stub(a)))

    def test_grip_outside_the_family_hands_is_refused(self):
        from dataclasses import replace
        from forge.blades import long_sword
        from forge.blades.model import validate
        p = long_sword.draw_params(1337)
        validate(p, long_sword.RULES)
        rules = replace(long_sword.RULES, grip={**long_sword.RULES.grip, "length": (0.19, 0.30)})
        with self.assertRaisesRegex(GenerationError, "two-handed"):
            validate(replace(p, grip=replace(p.grip, length=0.27)), rules)


if __name__ == "__main__":
    unittest.main()
