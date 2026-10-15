"""Character Forge experiment: GLB export, profiles, validation and the independent Node.js loader."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from forge_character_forge import dna as D
from forge_character_forge.animation import clip
from forge_character_forge.character import CharacterSpec, ProfileError, build_character, resolve_outfit
from forge_character_forge.gltf import pose_check_data, write_glb
from forge_character_forge.params import preset
from forge_character_forge.validate import read_glb, validate_glb

ROOT = Path(__file__).resolve().parent.parent


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        b, f, g = preset("male")
        cls.spec = CharacterSpec(b, f, g, outfit=("shorts",), name="t_male")
        cls.pub = build_character(cls.spec, "public", fast=True)
        cls.dev = build_character(CharacterSpec(b, f, g, outfit=(), name="t_male"), "developer", fast=True)
        cls.clips = [clip("walk"), clip("jump")]
        cls.pub_path = write_glb(cls.pub, cls.tmp / "m.glb", clips=cls.clips)
        cls.dev_path = write_glb(cls.dev, cls.tmp / "m.dev.glb", clips=cls.clips)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_public_glb_valid(self):
        r = validate_glb(self.pub_path, "public")
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(r["stats"]["animations"], 2)
        self.assertGreater(r["stats"]["morph_targets"], 5)
        gltf, _ = read_glb(self.pub_path)
        names = [n["name"] for n in gltf["nodes"]]
        self.assertNotIn("penis_01", names)
        self.assertNotIn("dev_genitals", names)
        forge = gltf["asset"]["extras"]["forge"]
        self.assertEqual(forge["profile"], "public")
        self.assertEqual(forge["units"], "meters")
        self.assertEqual(forge["up_axis"], "+Y")

    def test_developer_glb_valid_and_flagged(self):
        r = validate_glb(self.dev_path, "developer")
        self.assertTrue(r["ok"], r["errors"])
        gltf, _ = read_glb(self.dev_path)
        dev_nodes = [n["name"] for n in gltf["nodes"] if n.get("extras", {}).get("dev_only")]
        self.assertIn("dev_genitals", dev_nodes)
        self.assertIn("penis_01", dev_nodes)
        self.assertEqual(gltf["asset"]["extras"]["forge"]["dev_only_parts"], ["dev_genitals"])

    def test_public_validator_rejects_dev_content(self):
        r = validate_glb(self.dev_path, "public")
        self.assertFalse(r["ok"])

    def test_naming_gates(self):
        with self.assertRaises(ValueError):
            write_glb(self.dev, self.tmp / "leak.glb")
        with self.assertRaises(ValueError):
            write_glb(self.pub, self.tmp / "wrong.dev.glb")

    def test_public_build_is_clothed_by_default(self):
        b, f, g = preset("female")
        outfit = resolve_outfit(CharacterSpec(b, f, g, outfit=()), "public")
        self.assertIn("shorts", outfit)
        self.assertIn("tshirt", outfit)
        self.assertEqual(resolve_outfit(CharacterSpec(b, f, g, outfit=()), "developer"), ())

    def test_bad_profile(self):
        with self.assertRaises(ProfileError):
            build_character(self.spec, "steam_workshop")

    def test_deterministic_bytes(self):
        p2 = write_glb(self.pub, self.tmp / "m2.glb", clips=self.clips)
        self.assertEqual(Path(p2).read_bytes(), Path(self.pub_path).read_bytes())

    def test_validator_catches_corruption(self):
        data = bytearray(Path(self.pub_path).read_bytes())
        bad = self.tmp / "bad.glb"
        bad.write_bytes(bytes(data[:100]))
        with self.assertRaises(ValueError):
            validate_glb(bad)
        data2 = bytearray(data)
        data2[0:4] = b"XXXX"
        bad.write_bytes(bytes(data2))
        with self.assertRaises(ValueError):
            validate_glb(bad)
        # out-of-range index: rewrite one index in the first mesh's index buffer
        gltf, bin_ = read_glb(self.pub_path)
        acc = gltf["accessors"][gltf["meshes"][1]["primitives"][0]["indices"]]
        view = gltf["bufferViews"][acc["bufferView"]]
        jlen = int.from_bytes(data[12:16], "little")
        off = 20 + jlen + 8 + view.get("byteOffset", 0)
        width = 2 if acc["componentType"] == 5123 else 4
        data3 = bytearray(data)
        data3[off:off + width] = (0xFFFE if width == 2 else 0xFFFFFFF0).to_bytes(width, "little")
        bad.write_bytes(bytes(data3))
        r = validate_glb(bad)
        self.assertFalse(r["ok"])
        self.assertTrue(any("index out of range" in e for e in r["errors"]), r["errors"])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_independent_node_loader_matches_python_skinning(self):
        exp = self.tmp / "expect.json"
        exp.write_text(json.dumps(pose_check_data(self.pub, self.clips[0], 8, count=400)))
        out = subprocess.run(["node", str(ROOT / "tools/glb_independent_check.mjs"), str(self.pub_path), "--anim", "walk",
                              "--frame", "8", "--expect", str(exp)], capture_output=True, text=True)
        rep = json.loads(out.stdout)
        self.assertTrue(rep["ok"], rep)
        self.assertLess(rep["maxPositionErrorVsPython_m"], 1e-5)
        self.assertGreater(rep["meshes"]["body"]["verticesMovedBySkinning"], 0.9 * rep["meshes"]["body"]["vertices"])


class DevProfileGateTests(unittest.TestCase):
    def test_adult_gate_in_dna(self):
        d = D.new_dna("male")
        d["identity"]["age_years"] = 16
        with self.assertRaises(Exception):
            D.validate_dna(d)

    def test_no_genitals_when_disabled(self):
        b, f, g = preset("female")
        ch = build_character(CharacterSpec(b, f, g, outfit=()), "developer", fast=True)
        self.assertFalse(any(p.name == "dev_genitals" for p in ch.parts))


if __name__ == "__main__":
    unittest.main()
