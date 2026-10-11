"""Step 3 tests 25-42: manifest content, canonical bytes, and environment hygiene."""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine_support import GOLDEN, GOLDEN_DIR, cached, manifest_bytes, node, presented, sha256, split, write_package
from forge.catalog import REGISTRY
from forge.engine.contract import CONTRACT_ID, CONTRACT_NAME, CONTRACT_V1
from forge.engine.validate import validate_package, validate_package_bytes
from forge.errors import EngineContractError
from forge.registry import export_asset
from forge_test_support import REPO_ROOT

UUID = re.compile(rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TIMESTAMP = re.compile(rb"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|\b(19|20)\d{2}-\d{2}-\d{2}\b")


def strings_and_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from strings_and_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings_and_keys(v)
    elif isinstance(obj, str):
        yield obj


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.pkg = cached()
        self.m = json.loads(self.pkg.manifest)
        self.gltf, _, self.bin = split(self.pkg.glb)

    def test_25_manifest_exists_beside_the_glb(self):
        p = presented()
        with tempfile.TemporaryDirectory() as tmp:
            written = export_asset(REGISTRY, p.asset, p, "glb", 1, Path(tmp) / "pkg.forgepkg")
            self.assertEqual([w.name for w in written], ["asset.glb", "manifest.json"])
            self.assertEqual(sorted(x.name for x in (Path(tmp) / "pkg.forgepkg").iterdir()),
                             ["asset.glb", "manifest.json"])
            self.assertEqual(written[1].read_bytes(), self.pkg.manifest)

    def test_26_manifest_parses(self):
        self.assertTrue(self.pkg.manifest.isascii())
        self.assertTrue(self.pkg.manifest.endswith(b"}\n"))
        self.assertNotIn(b"\r", self.pkg.manifest)
        self.assertIsInstance(self.m, dict)
        self.assertEqual(sorted(self.m), sorted(CONTRACT_V1.manifest_sections))
        self.assertEqual(sorted(self.m), ["asset", "collision", "contract", "coordinates", "hashes", "lods",
                                          "materials", "package", "presentation", "sockets", "tags"])

    def test_27_contract_version_is_explicit(self):
        self.assertEqual(self.m["contract"], {"id": CONTRACT_ID, "name": CONTRACT_NAME, "version": 1})
        self.assertEqual(self.gltf["asset"]["extras"]["forge_contract"], {"id": CONTRACT_ID, "version": 1})
        no_version = dict(self.m, contract={"id": CONTRACT_ID, "name": CONTRACT_NAME})
        with self.assertRaisesRegex(EngineContractError, "no explicit contract version"):
            validate_package_bytes(self.pkg.glb, manifest_bytes(no_version))

    def test_28_asset_identity(self):
        self.assertEqual(self.m["asset"], {"asset_type": "short_sword", "display_name": "procedural short sword",
                                           "generator_id": "forge.sword", "generator_version": 1, "seed": "1337"})
        self.assertEqual(self.m["package"]["root_node"], "short_sword")
        self.assertEqual(self.gltf["nodes"][self.gltf["scenes"][0]["nodes"][0]]["name"], "short_sword")
        self.assertEqual(self.m["package"]["exporter"], {"format_id": "glb", "format_version": 1})

    def test_29_seed(self):
        self.assertEqual(self.m["asset"]["seed"], "1337")
        self.assertEqual(self.gltf["asset"]["extras"]["forge_seed"], "1337")
        big = cached(2 ** 64 - 1).manifest_data["asset"]["seed"]
        self.assertEqual(big, "18446744073709551615")              # a string: exact beyond 2**53

    def test_30_generator_and_presentation_versions(self):
        self.assertEqual(self.m["asset"]["generator_version"], 1)
        self.assertEqual({k: v for k, v in self.m["presentation"].items() if k != "texcoord_0"},
                         {"presentation_id": "forge.presentation", "presentation_version": 1, "normals_version": 1,
                          "uv_version": 1, "material_version": 1})
        self.assertEqual(self.gltf["asset"]["extras"]["forge_generator"], {"id": "forge.sword", "version": 1})
        self.assertEqual(self.gltf["asset"]["extras"]["forge_presentation"], {"id": "forge.presentation", "version": 1})

    def test_31_coordinates(self):
        c = self.m["coordinates"]
        self.assertEqual((c["handedness"], c["up_axis"], c["front_face_winding"]), ("right", "+Y", "counter_clockwise"))
        self.assertEqual(c["convention_id"], "forge.rh-y-up-meters.grip-origin.v1")
        self.assertTrue(c["conversion"].startswith("none"))

    def test_32_meters(self):
        c = self.m["coordinates"]
        self.assertEqual((c["units"], c["meters_per_unit"]), ("meters", 1))
        p = presented()
        lo, hi = p.asset.bounds()
        _, blade = node(self.gltf, "blade")
        acc = self.gltf["accessors"][self.gltf["meshes"][blade["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
        self.assertAlmostEqual(acc["max"][1], hi[1], places=6)            # tip height in meters, unscaled
        self.assertAlmostEqual(hi[1] - lo[1], p.asset.params.total_length, places=9)
        self.assertTrue(0.3 < hi[1] - lo[1] < 1.2)                       # a short sword, in meters

    def test_33_grip_origin(self):
        self.assertEqual(self.m["coordinates"]["origin"], "grip_center")
        grip = {s["name"]: s for s in self.m["sockets"]}["socket_grip"]
        self.assertEqual(grip["translation"], [0.0, 0.0, 0.0])
        _, g = node(self.gltf, "grip")
        acc = self.gltf["accessors"][self.gltf["meshes"][g["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
        for lo, hi in zip(acc["min"], acc["max"]):
            self.assertAlmostEqual(lo + hi, 0.0, places=7)                 # the grip box is centered on the origin
        root = self.gltf["nodes"][self.gltf["scenes"][0]["nodes"][0]]
        self.assertFalse({"translation", "rotation", "scale", "matrix"} & set(root))

    def test_34_sockets_match_glb(self):
        self.assertEqual([s["name"] for s in self.m["sockets"]], ["socket_grip", "socket_tip"])
        for s in self.m["sockets"]:
            i, n = node(self.gltf, s["name"])
            self.assertEqual((s["node_index"], s["parent"], s["translation"], s["rotation"]),
                             (i, "short_sword", n["translation"], n["rotation"]))
            self.assertTrue(s["frame"] and s["derivation"])
            self.assertEqual({"translation": s["translation"], "rotation": s["rotation"]}, GOLDEN["sockets"][s["name"]])

    def test_35_collision_hull_declared(self):
        c = self.m["collision"]
        i, _ = node(self.gltf, "collision_hull")
        self.assertEqual((c["node"], c["node_index"], c["representation"], c["scene"], c["scene_index"]),
                         ("collision_hull", i, "convex_hull", "forge_collision", 1))
        self.assertEqual((c["vertices"], c["triangles"]), (GOLDEN["collision"]["vertices"], GOLDEN["collision"]["triangles"]))
        self.assertIn("POSITION and indices only", c["gltf_representation"])

    def test_36_lod0_only(self):
        lods = self.m["lods"]
        self.assertEqual(lods["count"], 1)
        self.assertEqual([lv["level"] for lv in lods["levels"]], [0])
        self.assertEqual(lods["levels"][0], {"level": 0, **GOLDEN["lod0"]})
        self.assertEqual(lods["levels"][0]["triangles"], presented().asset.triangle_count)
        for name in lods["levels"][0]["nodes"]:
            self.assertEqual(node(self.gltf, name)[1]["extras"]["forge_lod"], 0)
        self.assertNotIn("MSFT_lod", self.pkg.glb.decode("latin-1"))

    def test_37_glb_hash_matches(self):
        h = self.m["hashes"]
        self.assertEqual(h["glb_sha256"]["sha256"], sha256(self.pkg.glb))
        _, json_chunk, bin_chunk = split(self.pkg.glb)
        self.assertEqual(h["gltf_json_sha256"]["sha256"], sha256(json_chunk))
        self.assertEqual(h["gltf_bin_sha256"]["sha256"], sha256(bin_chunk))
        for name, entry in h.items():
            with self.subTest(hash=name):
                self.assertTrue(entry["covers"])                                     # every hash says what it covers
                self.assertEqual(entry["verifiable_from_package"], not name.startswith("source_"))
        self.assertEqual({k: v["sha256"] for k, v in h.items()}, GOLDEN["hashes"])
        report = validate_package(GOLDEN_DIR)
        self.assertEqual(len(report.hashes_verified), 9)

    def test_38_canonical_bytes_reproduce(self):
        self.assertEqual(manifest_bytes(self.m), self.pkg.manifest)
        self.assertEqual(json.dumps(self.m, indent=2, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ": ")).encode() + b"\n", self.pkg.manifest)
        self.assertEqual((GOLDEN_DIR / "manifest.json").read_bytes(), self.pkg.manifest)
        self.assertEqual((GOLDEN_DIR / "asset.glb").read_bytes(), self.pkg.glb)
        without = dict(self.m, hashes={k: v for k, v in self.m["hashes"].items() if k != "manifest_content_sha256"})
        canonical = json.dumps(without, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        self.assertEqual(self.m["hashes"]["manifest_content_sha256"]["sha256"], sha256(canonical))


class TestHygiene(unittest.TestCase):
    def files(self):
        return [cached().glb, cached().manifest, (GOLDEN_DIR / "asset.glb").read_bytes()]

    def test_39_no_timestamps(self):
        for data in self.files():
            self.assertIsNone(TIMESTAMP.search(data))
        keys = {k.lower() for k in strings_and_keys(json.loads(cached().manifest)) if isinstance(k, str)}
        self.assertFalse(keys & {"timestamp", "created", "modified", "date", "time", "datetime"})
        self.assertNotIn("forge_version", cached().manifest.decode())                  # not even the package version

    def test_40_no_absolute_paths(self):
        p = presented()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            wa = export_asset(REGISTRY, p.asset, p, "glb", 1, Path(a) / "x.forgepkg")
            wb = export_asset(REGISTRY, p.asset, p, "glb", 1, Path(b) / "other" / "y.forgepkg")
            self.assertEqual([w.read_bytes() for w in wa], [w.read_bytes() for w in wb])
            for data in (w.read_bytes() for w in wa):
                for needle in (a.encode(), b.encode(), str(REPO_ROOT).encode(), os.path.expanduser("~").encode(),
                               b"/tmp/", b"/home/", b"C:\\", b"x.forgepkg"):
                    self.assertNotIn(needle, data)

    def test_41_no_process_ids(self):
        script = ("import sys, hashlib; sys.path[:0] = ['tests']; import engine_support as e; p = e.build(7); "
                  "print(hashlib.sha256(p.glb + p.manifest).hexdigest())")
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        outs = {subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=env, capture_output=True,
                               text=True, check=True).stdout.strip() for _ in range(2)}
        self.assertEqual(outs, {sha256(cached(7).glb + cached(7).manifest)})       # different PIDs, same bytes
        for k in strings_and_keys(json.loads(cached().manifest)):
            self.assertNotIn(k.lower(), {"pid", "process", "hostname", "host", "user", "username", "machine"})
        for k in strings_and_keys(split(cached().glb)[0]):
            self.assertNotIn(k.lower(), {"pid", "process", "hostname", "host", "user", "username", "machine"})

    def test_42_no_uuids(self):
        for data in self.files():
            self.assertIsNone(UUID.search(data))
        gltf = split(cached().glb)[0]
        self.assertFalse(any(re.search(r"(?i)\b(uuid|guid)\b", s) for s in strings_and_keys(gltf)))
        self.assertEqual(gltf["asset"]["generator"], "Black Lantern Forge glb exporter format 1")


if __name__ == "__main__":
    unittest.main()
