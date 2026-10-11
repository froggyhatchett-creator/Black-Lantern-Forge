"""Step 3 tests 1-24: registry identity, determinism, GLB structure, geometry, materials, sockets, collision."""

import math
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine_support import (
    FROZEN_GEOMETRY_1337,
    FROZEN_OBJ_1337,
    GOLDEN,
    GOLDEN_GLB_SHA256,
    GOLDEN_MANIFEST_SHA256,
    accessor_rows,
    build,
    cached,
    f32,
    node,
    presented,
    sha256,
    split,
)
from forge.catalog import REGISTRY
from forge.engine.contract import CONTRACT_ID
from forge.engine.hull import convex_hull
from forge.errors import ExportError, GeometryError, UnsupportedExportVersionError
from forge.export.obj import obj_bytes
from forge.hashing import geometry_sha256
from forge.registry import export_asset, exporter_for
from forge_test_support import REPO_ROOT

RENDER = ("blade", "guard", "grip", "pommel")


def render_primitives(gltf):
    for name in RENDER:
        _, n = node(gltf, name)
        yield name, gltf["meshes"][n["mesh"]]["primitives"][0]


class TestRegistryIdentity(unittest.TestCase):
    def test_01_glb_registered_as_version_1(self):
        exp = REGISTRY.exporter("glb", 1)
        self.assertEqual((exp.format_id, exp.format_version, exp.extension), ("glb", 1, ".forgepkg"))
        self.assertEqual(REGISTRY.export_versions("glb"), (1,))
        self.assertEqual(exp.presentations, (("forge.presentation", 1), ("forge.blade-presentation", 1),
                                             ("forge.hafted-presentation", 1)))
        self.assertEqual(exp.extra_file_labels, ("manifest",))
        self.assertEqual(exp.contract, (CONTRACT_ID, 1))
        self.assertIn(("glb", 1), REGISTRY.asset("short_sword").descriptor.export_formats)
        self.assertIs(exporter_for(REGISTRY, "short_sword", "glb", 1), exp)
        self.assertIsNone(REGISTRY.exporter("obj", 1).contract)     # OBJ exporters declare no contract

    def test_02_unsupported_glb_version_refuses(self):
        p = presented()
        with tempfile.TemporaryDirectory() as tmp:
            for bad in (2, 0, -1, True, 1.0, "1", None):
                with self.subTest(version=bad):
                    with self.assertRaises(UnsupportedExportVersionError):
                        REGISTRY.exporter("glb", bad)
                    with self.assertRaises(UnsupportedExportVersionError):
                        export_asset(REGISTRY, p.asset, p, "glb", bad, Path(tmp) / "x.forgepkg")
            with self.assertRaises(ExportError):                       # wrong suffix: refused, nothing written
                export_asset(REGISTRY, p.asset, p, "glb", 1, Path(tmp) / "x.glb")
            self.assertEqual(list(Path(tmp).iterdir()), [])


class TestDeterminism(unittest.TestCase):
    def test_03_identical_bytes_for_the_same_seed(self):
        a, b = build(1337), build(1337)
        self.assertEqual(a.glb, b.glb)
        self.assertEqual(a.manifest, b.manifest)
        self.assertEqual((a.glb_sha256, a.manifest_sha256), (GOLDEN_GLB_SHA256, GOLDEN_MANIFEST_SHA256))
        p, q = presented(), presented()                       # two independent generations
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            w1 = export_asset(REGISTRY, p.asset, p, "glb", 1, Path(t1) / "one.forgepkg")
            w2 = export_asset(REGISTRY, q.asset, q, "glb", 1, Path(t2) / "deep" / "two.forgepkg")
            self.assertEqual([x.read_bytes() for x in w1], [x.read_bytes() for x in w2])
            self.assertEqual([x.name for x in w1], ["asset.glb", "manifest.json"])

    def test_03b_identical_across_processes_and_hash_seeds(self):
        script = ("import hashlib, sys; sys.path[:0] = ['tests']; import engine_support as e; p = e.build(1337); "
                  "print(hashlib.sha256(p.glb + p.manifest).hexdigest(), __import__('os').getpid())")
        expected = sha256(cached(1337).glb + cached(1337).manifest)
        pids = set()
        for hash_seed in ("0", "4242", "random"):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(REPO_ROOT))
            out = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=env, capture_output=True,
                                 text=True, check=True).stdout.split()
            self.assertEqual(out[0], expected)
            pids.add(out[1])
        self.assertEqual(len(pids), 3)        # three different processes, one byte stream

    def test_04_different_seeds_differ(self):
        seeds = (0, 1, 1337, 1338, 2 ** 64 - 1)
        pkgs = [cached(s) for s in seeds]
        self.assertEqual(len({p.glb for p in pkgs}), len(seeds))
        self.assertEqual(len({p.manifest for p in pkgs}), len(seeds))
        semantic = {p.manifest_data["hashes"]["semantic_sha256"]["sha256"] for p in pkgs}
        self.assertEqual(len(semantic), len(seeds))

    def test_05_obj1_hash_unchanged(self):
        p = presented()
        before = (sha256(obj_bytes(p.asset)), geometry_sha256(p.asset))
        cached(1337)
        with tempfile.TemporaryDirectory() as tmp:
            export_asset(REGISTRY, p.asset, p, "glb", 1, Path(tmp) / "x.forgepkg")
        self.assertEqual(before, (FROZEN_OBJ_1337, FROZEN_GEOMETRY_1337))
        self.assertEqual((sha256(obj_bytes(p.asset)), geometry_sha256(p.asset)), before)
        self.assertEqual(cached().manifest_data["hashes"]["source_obj_format1_sha256"]["sha256"], FROZEN_OBJ_1337)
        self.assertEqual(cached().manifest_data["hashes"]["source_geometry_sha256"]["sha256"], FROZEN_GEOMETRY_1337)


class TestGlbContainer(unittest.TestCase):
    def setUp(self):
        self.glb = cached().glb
        self.gltf, self.json_chunk, self.bin_chunk = split(self.glb)

    def test_06_header(self):
        import struct
        magic, version, length = struct.unpack_from("<III", self.glb, 0)
        self.assertEqual(self.glb[:4], b"glTF")
        self.assertEqual(magic, 0x46546C67)
        self.assertEqual(length, len(self.glb))
        self.assertEqual(length % 4, 0)

    def test_07_version_2(self):
        import struct
        self.assertEqual(struct.unpack_from("<I", self.glb, 4)[0], 2)
        self.assertEqual(self.gltf["asset"]["version"], "2.0")
        self.assertNotIn("minVersion", self.gltf["asset"])
        self.assertNotIn("extensionsUsed", self.gltf)
        self.assertNotIn("extensionsRequired", self.gltf)

    def test_08_json_chunk_parses(self):
        import struct
        length, kind = struct.unpack_from("<II", self.glb, 12)
        self.assertEqual(kind, 0x4E4F534A)
        self.assertEqual(length % 4, 0)
        body = self.json_chunk.rstrip(b" ")
        self.assertLess(len(self.json_chunk) - len(body), 4)                 # space padding only
        self.assertTrue(body.isascii())
        import json
        self.assertEqual(json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode(), body)

    def test_09_bin_chunk_bounds(self):
        import struct
        json_len = struct.unpack_from("<I", self.glb, 12)[0]
        bin_len, kind = struct.unpack_from("<II", self.glb, 20 + json_len)
        self.assertEqual(kind, 0x004E4942)
        self.assertEqual(bin_len % 4, 0)
        self.assertEqual(28 + json_len + bin_len, len(self.glb))             # nothing after the BIN chunk
        self.assertEqual(len(self.gltf["buffers"]), 1)
        self.assertNotIn("uri", self.gltf["buffers"][0])
        n = self.gltf["buffers"][0]["byteLength"]
        self.assertTrue(0 < n <= bin_len and bin_len - n < 4)

    def test_10_accessor_bounds(self):
        sizes = {5126: 4, 5123: 2, 5125: 4}
        widths = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}
        for i, a in enumerate(self.gltf["accessors"]):
            with self.subTest(accessor=i):
                v = self.gltf["bufferViews"][a["bufferView"]]
                need = a.get("byteOffset", 0) + a["count"] * widths[a["type"]] * sizes[a["componentType"]]
                self.assertLessEqual(need, v["byteLength"])
                self.assertEqual((v["byteOffset"] + a.get("byteOffset", 0)) % sizes[a["componentType"]], 0)
                self.assertGreater(a["count"], 0)

    def test_11_buffer_view_bounds(self):
        n = self.gltf["buffers"][0]["byteLength"]
        end = 0
        for i, v in enumerate(self.gltf["bufferViews"]):
            with self.subTest(view=i):
                self.assertEqual(v["buffer"], 0)
                self.assertEqual(v["byteOffset"] % 4, 0)
                self.assertGreaterEqual(v["byteOffset"], end)                # in order, no overlap
                self.assertLessEqual(v["byteOffset"] + v["byteLength"], n)
                self.assertIn(v["target"], (34962, 34963))
                self.assertNotIn("byteStride", v)
                end = v["byteOffset"] + v["byteLength"]


class TestRenderGeometry(unittest.TestCase):
    def setUp(self):
        self.p = presented()
        self.gltf, _, self.bin = split(cached().glb)

    def test_12_position_exists(self):
        for name, prim in render_primitives(self.gltf):
            with self.subTest(component=name):
                a = self.gltf["accessors"][prim["attributes"]["POSITION"]]
                self.assertEqual((a["type"], a["componentType"]), ("VEC3", 5126))
                rows = accessor_rows(self.gltf, self.bin, prim["attributes"]["POSITION"])
                self.assertEqual(a["min"], [min(r[i] for r in rows) for i in range(3)])
                self.assertEqual(a["max"], [max(r[i] for r in rows) for i in range(3)])

    def test_13_normal_exists(self):
        for name, prim in render_primitives(self.gltf):
            with self.subTest(component=name):
                a = self.gltf["accessors"][prim["attributes"]["NORMAL"]]
                self.assertEqual((a["type"], a["componentType"]), ("VEC3", 5126))
                for n in accessor_rows(self.gltf, self.bin, prim["attributes"]["NORMAL"]):
                    self.assertAlmostEqual(math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2), 1.0, delta=1e-6)

    def test_14_uv_exists_and_flips_v(self):
        for (name, prim), comp, mesh in zip(render_primitives(self.gltf), self.p.components, self.p.asset.components):
            with self.subTest(component=name):
                a = self.gltf["accessors"][prim["attributes"]["TEXCOORD_0"]]
                self.assertEqual((a["type"], a["componentType"]), ("VEC2", 5126))
                uvs = accessor_rows(self.gltf, self.bin, prim["attributes"]["TEXCOORD_0"])
                idx = [r[0] for r in accessor_rows(self.gltf, self.bin, prim["indices"])]
                for t, tri in enumerate(comp.uv_indices):          # corner by corner, in frozen order
                    for k in range(3):
                        u, v = comp.uvs[tri[k]]
                        self.assertEqual(uvs[idx[3 * t + k]], (f32(u), f32(1.0 - v)))
                self.assertEqual(set(prim["attributes"]), {"POSITION", "NORMAL", "TEXCOORD_0"})

    def test_15_indices_in_bounds(self):
        for name, prim in render_primitives(self.gltf):
            with self.subTest(component=name):
                a = self.gltf["accessors"][prim["indices"]]
                count = self.gltf["accessors"][prim["attributes"]["POSITION"]]["count"]
                self.assertEqual((a["type"], a["componentType"]), ("SCALAR", 5123))   # all fit in u16
                idx = [r[0] for r in accessor_rows(self.gltf, self.bin, prim["indices"])]
                self.assertEqual(len(idx) % 3, 0)
                self.assertTrue(all(0 <= i < count for i in idx))
                self.assertEqual(set(idx), set(range(count)))                         # no unused vertices

    def test_16_triangle_mode_and_frozen_triangles(self):
        for (name, prim), mesh in zip(render_primitives(self.gltf), self.p.asset.components):
            with self.subTest(component=name):
                self.assertEqual(prim["mode"], 4)
                pos = accessor_rows(self.gltf, self.bin, prim["attributes"]["POSITION"])
                idx = [r[0] for r in accessor_rows(self.gltf, self.bin, prim["indices"])]
                self.assertEqual(len(idx) // 3, mesh.triangle_count)
                for t, tri in enumerate(mesh.triangles):                # same triangles, same order, same winding
                    for k in range(3):
                        self.assertEqual(pos[idx[3 * t + k]], tuple(f32(c) for c in mesh.positions[tri[k]]))
        collision = self.gltf["meshes"][node(self.gltf, "collision_hull")[1]["mesh"]]["primitives"][0]
        self.assertEqual(collision["mode"], 4)

    def test_17_materials_resolve(self):
        names = [m["name"] for m in self.gltf["materials"]]
        self.assertEqual(names, [f"forge_{c}" for c in RENDER])
        for i, (name, prim) in enumerate(render_primitives(self.gltf)):
            self.assertEqual(self.gltf["materials"][prim["material"]]["name"], f"forge_{name}")
        collision = self.gltf["meshes"][node(self.gltf, "collision_hull")[1]["mesh"]]["primitives"][0]
        self.assertNotIn("material", collision)
        for m in self.gltf["materials"]:
            self.assertEqual((m["alphaMode"], m["doubleSided"]), ("OPAQUE", False))
            self.assertNotIn("baseColorTexture", m["pbrMetallicRoughness"])           # factor-only in glb:1
            self.assertFalse(m["extras"]["forge_pattern_baked"])

    def test_18_factors_match_frozen_materials(self):
        for m, comp in zip(self.gltf["materials"], self.p.components):
            with self.subTest(component=comp.name):
                pbr = m["pbrMetallicRoughness"]
                self.assertEqual(pbr["baseColorFactor"], [*comp.material.base_color, 1.0])   # exact, not rounded
                self.assertEqual(pbr["metallicFactor"], comp.material.metallic)
                self.assertEqual(pbr["roughnessFactor"], comp.material.roughness)
                self.assertEqual(m["extras"]["forge_preset"], comp.material.preset)
                self.assertEqual(m["extras"]["forge_procedural_pattern"], comp.material.pattern.to_dict())


class TestSockets(unittest.TestCase):
    def test_19_sockets_exist(self):
        gltf, _, _ = split(cached().glb)
        root, root_node = node(gltf, "short_sword")
        for name in ("socket_grip", "socket_tip"):
            with self.subTest(socket=name):
                i, n = node(gltf, name)
                self.assertIn(i, root_node["children"])
                self.assertNotIn("mesh", n)
                self.assertNotIn("children", n)
                self.assertEqual(n["rotation"], [0.0, 0.0, 0.0, 1.0])
                self.assertEqual(n["extras"], {"forge_role": "socket"})
        self.assertEqual(node(gltf, "socket_grip")[1]["translation"], [0.0, 0.0, 0.0])
        self.assertEqual(node(gltf, "socket_tip")[1]["translation"], GOLDEN["sockets"]["socket_tip"]["translation"])

    def test_20_sockets_are_deterministic_derivations(self):
        for seed in (0, 1, 7, 42, 1337, 99999, 2 ** 64 - 1):
            with self.subTest(seed=seed):
                p, pkg = presented(seed), cached(seed)
                gltf, _, _ = split(pkg.glb)
                blade = p.asset.component("blade").positions
                apex = max(blade, key=lambda q: q[1])
                self.assertEqual(sum(1 for q in blade if q[1] == apex[1]), 1)
                self.assertEqual(node(gltf, "socket_tip")[1]["translation"], [f32(c) for c in apex])
                self.assertEqual(apex[0], 0.0)
                self.assertEqual(apex[2], 0.0)
                self.assertEqual(node(gltf, "socket_grip")[1]["translation"], [0.0, 0.0, 0.0])
                lo, hi = p.asset.component("grip").bounds()
                self.assertTrue(all(abs(lo[i] + hi[i]) <= 2e-9 for i in range(3)))
                self.assertEqual(split(build(seed).glb)[0]["nodes"], gltf["nodes"])

    def test_21_socket_transforms_match_golden_and_tip_is_on_render_geometry(self):
        gltf, _, bin_chunk = split(cached().glb)
        for name, want in GOLDEN["sockets"].items():
            _, n = node(gltf, name)
            self.assertEqual({"translation": n["translation"], "rotation": n["rotation"]}, want)
        _, blade = node(gltf, "blade")
        prim = gltf["meshes"][blade["mesh"]]["primitives"][0]
        top = max(accessor_rows(gltf, bin_chunk, prim["attributes"]["POSITION"]), key=lambda q: q[1])
        self.assertEqual(list(top), node(gltf, "socket_tip")[1]["translation"])        # exactly the render apex
        frames = {s["name"]: s["frame"] for s in cached().manifest_data["sockets"]}
        self.assertIn("+Y along the blade toward the tip", frames["socket_tip"])


class TestCollision(unittest.TestCase):
    def test_22_collision_hull_exists_and_is_not_render_geometry(self):
        gltf, _, bin_chunk = split(cached().glb)
        i, n = node(gltf, "collision_hull")
        self.assertEqual(n["extras"], {"forge_collision": "convex_hull", "forge_role": "collision"})
        self.assertEqual(gltf["scene"], 0)
        self.assertEqual([s["name"] for s in gltf["scenes"]], ["forge_render", "forge_collision"])
        self.assertEqual(gltf["scenes"][1]["nodes"], [i])
        root = node(gltf, "short_sword")[0]
        self.assertEqual(gltf["scenes"][0]["nodes"], [root])
        self.assertNotIn(i, gltf["nodes"][root]["children"])
        prim = gltf["meshes"][n["mesh"]]["primitives"][0]
        self.assertEqual(set(prim["attributes"]), {"POSITION"})
        pos = accessor_rows(gltf, bin_chunk, prim["attributes"]["POSITION"])
        idx = [r[0] for r in accessor_rows(gltf, bin_chunk, prim["indices"])]
        self.assertEqual((len(pos), len(idx) // 3), (GOLDEN["collision"]["vertices"], GOLDEN["collision"]["triangles"]))
        self.assertEqual(len(pos) - len(idx) // 2 + len(idx) // 3, 2)    # closed genus-0 triangle mesh: V - E + F

    def test_23_collision_is_deterministic_and_order_independent(self):
        h = cached().manifest_data["hashes"]["collision_sha256"]["sha256"]
        self.assertEqual(h, GOLDEN["collision"]["collision_sha256"])
        self.assertEqual(build().manifest_data["hashes"]["collision_sha256"]["sha256"], h)
        gltf, _, bin_chunk = split(cached().glb)
        render = [q for name in RENDER for q in accessor_rows(
            gltf, bin_chunk, gltf["meshes"][node(gltf, name)[1]["mesh"]]["primitives"][0]["attributes"]["POSITION"])]
        reference = convex_hull(render)
        shuffled = list(render)
        random.Random(5).shuffle(shuffled)
        self.assertEqual(convex_hull(shuffled), reference)
        self.assertEqual(list(reference.positions), sorted(reference.positions))
        self.assertEqual(list(reference.triangles), sorted(reference.triangles))
        self.assertTrue(all(t[0] < t[1] and t[0] < t[2] for t in reference.triangles))

    def test_24_render_geometry_unchanged_by_collision_and_sockets(self):
        p = presented()
        before = geometry_sha256(p.asset)
        pkg = build()
        self.assertEqual(geometry_sha256(p.asset), before)
        self.assertEqual(pkg.manifest_data["hashes"]["render_geometry_sha256"]["sha256"],
                         GOLDEN["hashes"]["render_geometry_sha256"])
        gltf, _, bin_chunk = split(pkg.glb)
        frozen = {tuple(f32(c) for c in q) for m in p.asset.components for q in m.positions}
        rendered = {q for name in RENDER for q in accessor_rows(
            gltf, bin_chunk, gltf["meshes"][node(gltf, name)[1]["mesh"]]["primitives"][0]["attributes"]["POSITION"])}
        self.assertEqual(rendered, frozen)                            # every frozen vertex, nothing invented
        hull = gltf["meshes"][node(gltf, "collision_hull")[1]["mesh"]]["primitives"][0]
        self.assertTrue(set(accessor_rows(gltf, bin_chunk, hull["attributes"]["POSITION"])) <= frozen)


class TestHullUnit(unittest.TestCase):
    def test_cube_with_interior_and_face_points(self):
        corners = [(x, y, z) for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)]
        extra = [(0.5, 0.5, 0.5), (0.5, 0.5, 0.0), (0.25, 0.0, 0.75), (1.0, 0.5, 0.5)]
        h = convex_hull(corners + extra)
        self.assertEqual(sorted(h.positions), sorted(corners))
        self.assertEqual(len(h.triangles), 12)

    def test_degenerate_inputs_refuse(self):
        for pts in ([(0.0, 0.0, 0.0)] * 5, [(float(i), 0.0, 0.0) for i in range(6)],
                    [(float(i), float(j), 0.0) for i in range(3) for j in range(3)], []):
            with self.subTest(n=len(pts)):
                with self.assertRaises(GeometryError):
                    convex_hull(pts)

    def test_random_clouds_are_exact(self):
        r = random.Random(11)
        for trial in range(20):
            pts = [tuple(f32(r.uniform(-1, 1)) for _ in range(3)) for _ in range(60)]
            h = convex_hull(pts)
            self.assertEqual(convex_hull(list(reversed(pts))), h)
            self.assertEqual(len(h.positions) - 3 * len(h.triangles) // 2 + len(h.triangles), 2)

    def test_negative_zero_is_normalized(self):
        pts = [(0.0, 0.0, 0.0), (-0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-0.0, -0.0, -0.0)]
        h = convex_hull(pts)
        self.assertTrue(all(math.copysign(1.0, c) > 0 for p in h.positions for c in p))


if __name__ == "__main__":
    unittest.main()
