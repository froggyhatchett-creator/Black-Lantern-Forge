"""Step 5B tests 1-5 and 22 (+ CLI checks): the registered hafted families.

1-4  each family is registered with an explicit identity: generator forge.<family> v1,
     presentation forge.hafted-presentation v1, preview forge.preview.fit v1, exports glb:1 and obj:2
5    every version is explicit; nothing resolves to "latest"
22   every asset has its family's required, semantically named components
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge.assets import blades, hafted, short_sword
from forge.catalog import ASSET_ENTRIES, ASSETS, ENGINE_ADAPTERS, REGISTRY
from forge.errors import ForgeError, UnknownAssetTypeError, UnsupportedGeneratorVersionError, UnsupportedVersionError
from forge.hafted.model import HaftedAsset
from forge.registry import generate_asset, present_asset
from forge_test_support import REPO_ROOT
from hafted_support import (
    COMPONENTS,
    FAMILIES,
    FIT_PREVIEW,
    GENERATOR_IDS,
    HAFTED_PRESENTATION,
    LINEUP_SEEDS,
    asset,
)

CONVENTION = "forge.rh-y-up-meters.grip-origin.v1"


def run_cli(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run([sys.executable, "-m", "forge", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=300)


class TestRegistered(unittest.TestCase):
    def check_family(self, family):
        self.assertIn(family, REGISTRY.asset_types())
        d = REGISTRY.asset(family).descriptor
        self.assertEqual(d.asset_type, family)
        self.assertEqual(d.generator_id, GENERATOR_IDS[family])
        self.assertEqual(REGISTRY.generator_versions(d.generator_id), (1,))
        gen = REGISTRY.generator(d.generator_id, 1)
        self.assertEqual((gen.asset_type, gen.generator_version), (family, 1))
        self.assertEqual(d.presentation_id, HAFTED_PRESENTATION)
        self.assertEqual(REGISTRY.presentation_versions(HAFTED_PRESENTATION), (1,))
        self.assertEqual(REGISTRY.presentation(HAFTED_PRESENTATION, 1).preview_versions, (1,))
        self.assertEqual(d.preview_id, FIT_PREVIEW)
        self.assertEqual(d.export_formats, (("glb", 1), ("obj", 2)))
        self.assertEqual(d.record_versions, (1,))
        self.assertEqual(d.convention_id, CONVENTION)
        self.assertEqual(d.components, COMPONENTS[family])
        self.assertIn(family, ENGINE_ADAPTERS)
        self.assertEqual([k for k, _ in ASSET_ENTRIES[family].integrity],
                         ["geometry_sha256", "normals_sha256", "uvs_sha256", "materials_sha256"])
        a = asset(family)
        self.assertIsInstance(a, HaftedAsset)
        self.assertEqual((a.asset_type, a.generator, a.generator_version, a.seed), (family, GENERATOR_IDS[family], 1, 1337))

    def test_01_one_hand_axe_registered(self):
        self.check_family("one_hand_axe")

    def test_02_two_hand_axe_registered(self):
        self.check_family("two_hand_axe")

    def test_03_mace_registered(self):
        self.check_family("mace")

    def test_04_war_hammer_registered(self):
        self.check_family("war_hammer")

    def test_registry_lists_every_family_in_order(self):
        self.assertEqual(REGISTRY.asset_types(), ("curved_sword", "dagger", "great_sword", "long_sword", "mace",
                                                  "one_hand_axe", "short_sword", "two_hand_axe", "war_hammer"))
        self.assertEqual(tuple(e.descriptor.asset_type for e in ASSETS),
                         ("short_sword", "dagger", "long_sword", "curved_sword", "great_sword") + FAMILIES)
        self.assertIs(ASSETS[0], short_sword.ASSET)
        self.assertEqual(ASSETS[1:5], blades.ASSETS)
        self.assertEqual(ASSETS[5:], hafted.ASSETS)
        self.assertEqual(REGISTRY.preview_ids(), ("forge.preview", FIT_PREVIEW))
        for fmt in (("obj", 2), ("glb", 1)):
            self.assertIn((HAFTED_PRESENTATION, 1), REGISTRY.exporter(*fmt).presentations)
        self.assertEqual(REGISTRY.exporter("obj", 1).presentations, ())

    def test_05_explicit_versions_required(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                for bad in (None, 0, 2, "1", 1.0, True, "latest"):
                    with self.assertRaises(ForgeError):
                        generate_asset(REGISTRY, family, 1337, bad)
                with self.assertRaises(UnsupportedGeneratorVersionError):
                    generate_asset(REGISTRY, family, 1337, 2)
                for bad in (None, 1, "1"):
                    with self.assertRaises(UnsupportedVersionError):
                        present_asset(REGISTRY, asset(family), bad)
                with self.assertRaises(ForgeError):
                    REGISTRY.presentation(HAFTED_PRESENTATION, 2)
        with self.assertRaises(UnknownAssetTypeError):
            generate_asset(REGISTRY, "halberd", 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "mace", "--seed", "1337", cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertIn("--generator-version", r.stderr)
            r = run_cli("generate", "mace", "--seed", "1337", "--generator-version", "1", "--save", "x.json", cwd=tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((Path(tmp) / "x.json").exists())

    def test_22_required_components_exist(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    self.assertEqual(a.component_names, COMPONENTS[family])
                    for name in COMPONENTS[family]:
                        m = a.component(name)
                        self.assertGreater(len(m.positions), 0)
                        self.assertGreater(len(m.triangles), 0)
                    keys = [k for k, _ in a.landmarks]
                    for must in ("grip_center", "head_center", "strike_point", "tip"):
                        self.assertIn(must, keys)
                    self.assertEqual("secondary_strike_point" in keys, family == "war_hammer")
                    self.assertEqual("upper_grip_top" in keys, family == "two_hand_axe")
                    self.assertGreaterEqual(len(a.joints), 3)


class TestCli(unittest.TestCase):
    def test_generate_commands_from_the_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    r = run_cli("generate", family, "--seed", "1337", "--generator-version", "1",
                                "--presentation-version", "1", cwd=tmp)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn(REGISTRY.asset(family).descriptor.display_name, r.stdout)
                    self.assertIn("strike point", r.stdout)

    def test_every_family_round_trips_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    r = run_cli("generate", family, "--seed", "7", "--generator-version", "1",
                                "--presentation-version", "1", "--export", "glb:1", "--out", f"{family}.forgepkg",
                                "--save", f"{family}.json", "--preview", f"{family}.png", "--width", "64",
                                "--height", "128", "--ssaa", "1", cwd=tmp)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(run_cli("load", f"{family}.json", cwd=tmp).returncode, 0)
                    self.assertEqual(run_cli("validate-package", f"{family}.forgepkg", "--reproduce", cwd=tmp).returncode, 0)
                    self.assertEqual(run_cli("export", f"{family}.json", "--format", "obj:2", "--out", f"{family}.obj",
                                             cwd=tmp).returncode, 0)

    def test_json_output_names_the_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "war_hammer", "--seed", "42", "--generator-version", "1", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual((data["asset_type"], data["generator"], data["generator_version"], data["seed"]),
                             ("war_hammer", "forge.war_hammer", 1, 42))
            self.assertIn("overall_length", data["derived"])
            self.assertEqual(len(data["joints"]), len(asset("war_hammer", 42).joints))

    def test_unknown_family_lists_every_registered_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("generate", "halberd", "--seed", "1", "--generator-version", "1", cwd=tmp)
            self.assertEqual(r.returncode, 2)
            for family in FAMILIES + ("short_sword", "dagger"):
                self.assertIn(family, r.stderr)


if __name__ == "__main__":
    unittest.main()
