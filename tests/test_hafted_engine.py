"""Step 5B tests 41-49 and 58: Contract v1 engine packages for the hafted families.

41     glb:1 exports all, validated by the unchanged generic validator
42-45  socket_grip, socket_head, socket_strike (on a real render vertex) and the other sockets
46-47  the collision hull exists and validates
48-49  manifest asset type and generator identity
58     packages are deterministic and reproduce the seed-1337 goldens byte for byte
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine_support import accessor_rows, f32, node, split
from forge.catalog import ENGINE_ADAPTERS, REGISTRY
from forge.engine.contract import CONTRACT_ID, SUPPORTED_CONTRACT_VERSIONS
from forge.engine.validate import validate_package, validate_package_bytes
from forge.errors import ExportError
from forge.hafted.model import HaftedAsset
from forge.mesh import Mesh
from forge.registry import export_asset
from forge_test_support import REPO_ROOT
from hafted_support import (
    COMPONENTS,
    EXAMPLES,
    FAMILIES,
    GENERATOR_IDS,
    HAFTED_GOLDEN,
    HAFTED_PRESENTATION,
    LINEUP_SEEDS,
    STRIKE_PART,
    asset,
    build_package,
    edge_problems,
    package,
    presented,
    sha256,
)

IDENTITY = [0.0, 0.0, 0.0, 1.0]
SOCKETS = {f: ["socket_grip", "socket_head", "socket_strike", "socket_tip"] for f in FAMILIES}
SOCKETS["war_hammer"] = ["socket_grip", "socket_head", "socket_secondary_strike", "socket_strike", "socket_tip"]


def sockets(manifest):
    return {s["name"]: s for s in manifest["sockets"]}


def render_vertices(family, seed):
    return {tuple(f32(c) for c in q) for m in asset(family, seed).components for q in m.positions}


class TestExport(unittest.TestCase):
    def test_41_glb_exports_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                for seed in (1, 1337):
                    with self.subTest(family=family, seed=seed):
                        p = presented(family, seed)
                        out = Path(tmp) / f"{family}_{seed}.forgepkg"
                        written = export_asset(REGISTRY, p.asset, p, "glb", 1, out)
                        self.assertEqual([w.name for w in written], ["asset.glb", "manifest.json"])
                        self.assertEqual(validate_package(out).asset_type, family)
                        gltf, _, bin_chunk = split((out / "asset.glb").read_bytes())
                        names = [n["name"] for n in gltf["nodes"]]
                        self.assertEqual(names, [family, *COMPONENTS[family], *SOCKETS[family], "collision_hull"])
                        for mesh in p.asset.components:
                            prim = gltf["meshes"][node(gltf, mesh.name)[1]["mesh"]]["primitives"][0]
                            pos = accessor_rows(gltf, bin_chunk, prim["attributes"]["POSITION"])
                            self.assertEqual(set(pos), {tuple(f32(c) for c in q) for q in mesh.positions})
                        if seed == 1337:
                            self.assertEqual(sha256((out / "asset.glb").read_bytes()),
                                             HAFTED_GOLDEN[family]["files"]["asset.glb"]["sha256"])
        self.assertEqual(SUPPORTED_CONTRACT_VERSIONS, (1,), "no Contract v2 was made")
        self.assertIn((HAFTED_PRESENTATION, 1), REGISTRY.exporter("glb", 1).presentations)


class TestSockets(unittest.TestCase):
    def test_42_socket_grip_exists_for_all(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                s = sockets(package(family, seed).manifest_data)["socket_grip"]
                self.assertEqual((s["translation"], s["rotation"], s["parent"]), ([0.0, 0.0, 0.0], IDENTITY, family))

    def test_43_socket_head_exists_for_all(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    s = sockets(package(family, seed).manifest_data)["socket_head"]
                    head = a.landmark("head_center")
                    self.assertEqual(s["translation"], [f32(c) for c in head])
                    self.assertEqual((head[0], head[2]), (0.0, 0.0), "on the haft axis")
                    lo, hi = a.component("head").bounds()
                    self.assertTrue(lo[1] < head[1] < hi[1], "inside the head's height")

    def test_44_socket_strike_exists_for_all(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                m = package(family, seed).manifest_data
                self.assertEqual([x["name"] for x in m["sockets"]], SOCKETS[family])
                self.assertTrue(all(x["rotation"] == IDENTITY for x in m["sockets"]))
                self.assertIn("socket_tip", sockets(m), "Contract v1 requires it")

    def test_45_socket_strike_on_its_render_landmark(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS + tuple(range(400, 420)):
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    strike = a.landmark("strike_point")
                    part = a.component(STRIKE_PART[family])
                    self.assertIn(strike, part.positions, "the strike point is a real vertex of the striking part")
                    got = {s.name: s for s in ENGINE_ADAPTERS[family].sockets(a)}
                    self.assertEqual(got["socket_strike"].translation, strike)
                    self.assertIn(tuple(f32(c) for c in strike), render_vertices(family, seed))
                    head = a.landmark("head_center")
                    if family in ("one_hand_axe", "two_hand_axe"):
                        # the furthest-forward point of the edge, at the middle of its height
                        self.assertEqual(strike[0], max(q[0] for q in part.positions))
                        self.assertEqual(strike[2], 0.0)
                    elif family == "mace":
                        self.assertEqual(strike[2], 0.0)
                        self.assertEqual(strike[0], max(q[0] for q in part.positions if abs(q[2]) < 1e-12))
                    else:
                        self.assertEqual((strike[1], strike[2]), (head[1], 0.0), "the face's center")
                        self.assertEqual(strike[0], max(q[0] for q in part.positions))
                    tip = got["socket_tip"].translation
                    self.assertEqual((tip[0], tip[2]), (0.0, 0.0))
                    self.assertGreater(tip[1], head[1])
                    if family == "war_hammer":
                        rear = got["socket_secondary_strike"].translation
                        self.assertIn(rear, a.component("rear").positions)
                        self.assertEqual(rear[0], min(q[0] for q in a.component("rear").positions))

    def test_socket_adapter_fails_closed(self):
        a = asset("one_hand_axe", 3)
        s = a.landmark("strike_point")
        moved = HaftedAsset(asset_type=a.asset_type, generator=a.generator, generator_version=1, seed=a.seed,
                            params=a.params, components=a.components,
                            landmarks=tuple(sorted({**dict(a.landmarks), "strike_point": (s[0] + 1e-6, s[1], s[2])}.items())),
                            joints=a.joints, head_components=a.head_components, head_bore_volume=a.head_bore_volume)
        with self.assertRaisesRegex(ExportError, "not a bit vertex"):
            ENGINE_ADAPTERS["one_hand_axe"].sockets(moved)
        grip = a.component("grip")
        shifted = Mesh(name="grip", positions=tuple((x, y + 0.001, z) for x, y, z in grip.positions),
                       triangles=grip.triangles)
        off = HaftedAsset(asset_type=a.asset_type, generator=a.generator, generator_version=1, seed=a.seed,
                          params=a.params, components=tuple(shifted if m.name == "grip" else m for m in a.components),
                          landmarks=a.landmarks, joints=a.joints, head_components=a.head_components,
                          head_bore_volume=a.head_bore_volume)
        with self.assertRaisesRegex(ExportError, "not at the origin"):
            ENGINE_ADAPTERS["one_hand_axe"].sockets(off)


class TestCollision(unittest.TestCase):
    def hull(self, family, seed):
        gltf, _, bin_chunk = split(package(family, seed).glb)
        prim = gltf["meshes"][node(gltf, "collision_hull")[1]["mesh"]]["primitives"][0]
        pos = accessor_rows(gltf, bin_chunk, prim["attributes"]["POSITION"])
        idx = [r[0] for r in accessor_rows(gltf, bin_chunk, prim["indices"])]
        return gltf, prim, pos, [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]

    def test_46_collision_hull_exists_for_all(self):
        for family in FAMILIES:
            c = package(family).manifest_data["collision"]
            self.assertEqual((c["node"], c["representation"], c["scene"]), ("collision_hull", "convex_hull",
                                                                             "forge_collision"))
            gltf, prim, pos, tris = self.hull(family, 1337)
            self.assertEqual((len(pos), len(tris)), (c["vertices"], c["triangles"]))
            self.assertEqual(sorted(prim["attributes"]), ["POSITION"])
            g = HAFTED_GOLDEN[family]["collision"]
            self.assertEqual((c["vertices"], c["triangles"]), (g["vertices"], g["triangles"]))

    def test_47_collision_hull_validates_for_all(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    gltf, prim, pos, tris = self.hull(family, seed)
                    validate_package_bytes(package(family, seed).glb, package(family, seed).manifest)
                    self.assertEqual(edge_problems(Mesh(name="hull", positions=tuple(pos), triangles=tuple(tris))), [])
                    self.assertEqual(len(tris), 2 * len(pos) - 4)
                    render = render_vertices(family, seed)
                    for a, b, c in tris:
                        pa, pb, pc = pos[a], pos[b], pos[c]
                        u = [pb[k] - pa[k] for k in range(3)]
                        v = [pc[k] - pa[k] for k in range(3)]
                        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                        d = n[0] * pa[0] + n[1] * pa[1] + n[2] * pa[2]
                        self.assertLessEqual(max(n[0] * q[0] + n[1] * q[1] + n[2] * q[2] - d for q in render), 1e-12)
                    self.assertTrue(set(pos) <= render)


class TestManifest(unittest.TestCase):
    def test_48_manifests_identify_asset_type(self):
        for family in FAMILIES:
            m = package(family).manifest_data
            self.assertEqual((m["asset"]["asset_type"], m["package"]["root_node"]), (family, family))
            self.assertEqual(m["lods"]["levels"][0]["nodes"], list(COMPONENTS[family]))
            self.assertIn(f"asset_type:{family}", m["tags"])
            self.assertIn("lineage:hafted", m["tags"])

    def test_49_manifests_identify_generator(self):
        for family in FAMILIES:
            m = package(family).manifest_data
            g = HAFTED_GOLDEN[family]
            self.assertEqual((m["asset"]["generator_id"], m["asset"]["generator_version"], m["asset"]["seed"]),
                             (GENERATOR_IDS[family], 1, "1337"))
            self.assertEqual((m["presentation"]["presentation_id"], m["presentation"]["presentation_version"]),
                             (HAFTED_PRESENTATION, 1))
            self.assertEqual(m["package"]["exporter"], {"format_id": "glb", "format_version": 1})
            self.assertEqual((m["contract"]["id"], m["contract"]["version"]), (CONTRACT_ID, 1))
            self.assertEqual({k: v["sha256"] for k, v in m["hashes"].items()}, g["package_hashes"])
            self.assertEqual(m["tags"], g["tags"])


class TestPackageDeterminism(unittest.TestCase):
    def test_58_package_export_deterministic(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])\n"
                "from hafted_support import build_package, FAMILIES\n"
                "print(' '.join(build_package(f, 1337, fresh=True).glb_sha256 + ':' + "
                "build_package(f, 1337, fresh=True).manifest_sha256 for f in FAMILIES))\n")
        r = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT), str(REPO_ROOT / "tests")],
                           env=dict(os.environ, PYTHONHASHSEED="99"), capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        for family, theirs in zip(FAMILIES, r.stdout.split()):
            with self.subTest(family=family):
                a, b = build_package(family, 1337, fresh=True), build_package(family, 1337, fresh=True)
                self.assertEqual((a.glb, a.manifest), (b.glb, b.manifest))
                self.assertEqual(f"{a.glb_sha256}:{a.manifest_sha256}", theirs)
                pkg = EXAMPLES / f"{family}_seed1337_v1.forgepkg"
                self.assertEqual(a.glb, (pkg / "asset.glb").read_bytes())
                self.assertEqual(a.manifest, (pkg / "manifest.json").read_bytes())

    def test_golden_packages_validate_on_disk(self):
        for family in FAMILIES:
            self.assertEqual(validate_package(EXAMPLES / f"{family}_seed1337_v1.forgepkg").asset_type, family)
            m = json.loads((EXAMPLES / f"{family}_seed1337_v1.forgepkg" / "manifest.json").read_bytes())
            self.assertEqual({s["name"]: {"translation": s["translation"], "rotation": s["rotation"]}
                              for s in m["sockets"]}, HAFTED_GOLDEN[family]["sockets"])


if __name__ == "__main__":
    unittest.main()
