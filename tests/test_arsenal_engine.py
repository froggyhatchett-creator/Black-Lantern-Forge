"""Step 5A tests 39-49 and 58 (+ golden-package checks): engine packages for every blade family.

39-42  glb:1 exports per family, validated against Contract v1 by the unchanged generic validator
43-45  socket_grip, socket_tip, and socket_tip at the blade's real terminal point (not "max +Y")
46-47  the collision hull exists and validates
48-49  manifest asset type and generator identity
58     engine packages are deterministic and reproduce the seed-1337 goldens byte for byte
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from arsenal_support import (
    ARSENAL_GOLDEN,
    BLADE_PRESENTATION,
    COMPONENTS,
    EXAMPLES,
    FAMILIES,
    GENERATOR_IDS,
    LINEUP_SEEDS,
    asset,
    build_package,
    edge_problems,
    package,
    presented,
    sha256,
)
from engine_support import accessor_rows, f32, node, split
from forge.blades.model import BladeAsset
from forge.blades.shapes import BladeShape, build_blade, curved_centerline, single_edge
from forge.catalog import ENGINE_ADAPTERS, REGISTRY
from forge.engine.contract import CONTRACT_ID, SUPPORTED_CONTRACT_VERSIONS, contract_spec
from forge.engine.validate import validate_package, validate_package_bytes
from forge.errors import EngineContractError, ExportError
from forge.mesh import Mesh
from forge.registry import export_asset
from forge_test_support import REPO_ROOT

IDENTITY = [0.0, 0.0, 0.0, 1.0]


def sockets(manifest):
    return {s["name"]: s for s in manifest["sockets"]}


class TestExport(unittest.TestCase):
    """39-42."""

    def check(self, family):
        with tempfile.TemporaryDirectory() as tmp:
            for seed in (1, 1337):
                p = presented(family, seed)
                out = Path(tmp) / f"{family}_{seed}.forgepkg"
                written = export_asset(REGISTRY, p.asset, p, "glb", 1, out)
                self.assertEqual([w.name for w in written], ["asset.glb", "manifest.json"])
                report = validate_package(out)                  # Forge's own, generic Contract v1 validator
                self.assertEqual(report.asset_type, family)
                glb = (out / "asset.glb").read_bytes()
                self.assertEqual(glb[:4], b"glTF")
                self.assertEqual(struct.unpack_from("<II", glb, 4), (2, len(glb)))
                gltf, _, bin_chunk = split(glb)
                self.assertEqual(gltf["asset"]["version"], "2.0")
                names = [n["name"] for n in gltf["nodes"]]
                for name in (family,) + COMPONENTS + ("socket_grip", "socket_tip", "collision_hull"):
                    self.assertIn(name, names)
                # the render meshes carry exactly the source geometry, rounded to binary32
                for mesh in p.asset.components:
                    prim = gltf["meshes"][node(gltf, mesh.name)[1]["mesh"]]["primitives"][0]
                    pos = accessor_rows(gltf, bin_chunk, prim["attributes"]["POSITION"])
                    self.assertEqual(set(pos), {tuple(f32(c) for c in q) for q in mesh.positions})
                if seed == 1337:
                    self.assertEqual(sha256(glb), ARSENAL_GOLDEN[family]["files"]["asset.glb"]["sha256"])

    def test_39_dagger_glb_exports(self):
        self.check("dagger")

    def test_40_long_sword_glb_exports(self):
        self.check("long_sword")

    def test_41_curved_sword_glb_exports(self):
        self.check("curved_sword")

    def test_42_great_sword_glb_exports(self):
        self.check("great_sword")

    def test_contract_v1_is_the_only_contract(self):
        self.assertEqual(SUPPORTED_CONTRACT_VERSIONS, (1,))
        with self.assertRaises(EngineContractError):
            contract_spec(2)
        self.assertEqual(REGISTRY.exporter("glb", 1).contract, (CONTRACT_ID, 1))
        self.assertIn((BLADE_PRESENTATION, 1), REGISTRY.exporter("glb", 1).presentations)


class TestSockets(unittest.TestCase):
    """43-45."""

    def test_43_socket_grip_exists_per_family(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    m = package(family, seed).manifest_data
                    s = sockets(m)["socket_grip"]
                    self.assertEqual((s["translation"], s["rotation"], s["parent"]), ([0.0, 0.0, 0.0], IDENTITY, family))
                    gltf = split(package(family, seed).glb)[0]
                    i, n = node(gltf, "socket_grip")
                    self.assertIn(i, node(gltf, family)[1]["children"])

    def test_44_socket_tip_exists_per_family(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    m = package(family, seed).manifest_data
                    s = sockets(m)["socket_tip"]
                    tip = asset(family, seed).landmark("blade_tip")
                    self.assertEqual(s["translation"], [f32(c) for c in tip])
                    self.assertEqual(s["rotation"], IDENTITY)
                    gltf = split(package(family, seed).glb)[0]
                    self.assertEqual(node(gltf, "socket_tip")[1]["translation"], [f32(c) for c in tip])
                    self.assertEqual([x["name"] for x in m["sockets"]], ["socket_grip", "socket_tip"])

    def test_45_socket_tip_is_the_terminal_point(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS + tuple(range(200, 240)):
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    blade = a.component("blade")
                    tip, (tx, ty, _) = a.landmark("blade_tip"), a.landmark("blade_tip_tangent")
                    # the apex is the vertex where the blade sweep ends (the last one written) ...
                    self.assertEqual(blade.positions[-1], tip)
                    # ... it is the extreme blade point along the blade's own end direction ...
                    reach = tip[0] * tx + tip[1] * ty
                    self.assertTrue(all(q[0] * tx + q[1] * ty <= reach for q in blade.positions))
                    # ... and the socket is put there
                    got = {s.name: s for s in ENGINE_ADAPTERS[family].sockets(a)}["socket_tip"]
                    self.assertEqual(got.translation, tip)
                    if family == "curved_sword":
                        self.assertLess(tip[0], -0.01, "a curved blade ends off the grip axis")
                        self.assertLess(tx, 0.0)

    def test_45b_terminal_point_differs_from_highest_vertex(self):
        """A blade that curls far enough has a vertex higher than its terminal point. The adapter must
        still put socket_tip at the terminal point. Built directly from the shared shape primitives,
        past the generator's turn limit, so this can only pass if the adapter uses the recorded apex."""
        hilt = asset("dagger", 1337)
        base_y = hilt.landmark("blade_base_center")[1]
        cl = curved_centerline(base_y, 0.8, 64, 0.12, 1.0)
        half, s_sh = 0.03, 0.92
        widths, offsets = [], []
        for k in range(64):
            s = k / 64
            w = half if s <= s_sh else half * (1.0 - (s - s_sh) / (1.0 - s_sh))
            widths.append(w)
            offsets.append(w - half)                       # clipped point: the spine runs straight on
        shape = BladeShape(centerline=cl, profile=single_edge(0.5), half_widths=tuple(widths),
                           half_thicknesses=tuple(0.004 for _ in range(64)), offsets=tuple(offsets),
                           apex_offset=0.0 - half)
        blade, apex, tangent = build_blade(shape)
        highest = max(blade.positions, key=lambda q: q[1])
        self.assertNotEqual(highest, apex)
        self.assertGreater(highest[1], apex[1] + 0.005)
        curled = BladeAsset(asset_type="dagger", generator=hilt.generator, generator_version=1, seed=hilt.seed,
                            params=hilt.params, components=(blade,) + hilt.components[1:],
                            landmarks=tuple(sorted({**dict(hilt.landmarks), "blade_tip": apex,
                                                    "blade_tip_tangent": (tangent[0], tangent[1], 0.0)}.items())))
        tip = {s.name: s for s in ENGINE_ADAPTERS["dagger"].sockets(curled)}["socket_tip"]
        self.assertEqual(tip.translation, apex)
        self.assertNotEqual(tip.translation, highest)

    def test_socket_adapter_fails_closed(self):
        a = asset("long_sword", 3)
        t = a.landmark("blade_tip")
        moved = BladeAsset(asset_type=a.asset_type, generator=a.generator, generator_version=1, seed=a.seed,
                           params=a.params, components=a.components,
                           landmarks=tuple(sorted({**dict(a.landmarks), "blade_tip": (t[0], t[1] + 1e-6, t[2])}.items())))
        with self.assertRaisesRegex(ExportError, "not a blade vertex"):
            ENGINE_ADAPTERS["long_sword"].sockets(moved)
        grip = a.component("grip")
        shifted = Mesh(name="grip", positions=tuple((x + 0.001, y, z) for x, y, z in grip.positions),
                       triangles=grip.triangles)
        off = BladeAsset(asset_type=a.asset_type, generator=a.generator, generator_version=1, seed=a.seed,
                         params=a.params, components=(a.components[0], a.components[1], shifted, a.components[3]),
                         landmarks=a.landmarks)
        with self.assertRaisesRegex(ExportError, "not at the origin"):
            ENGINE_ADAPTERS["long_sword"].sockets(off)


class TestCollision(unittest.TestCase):
    """46-47."""

    def hull(self, family, seed):
        pkg = package(family, seed)
        gltf, _, bin_chunk = split(pkg.glb)
        prim = gltf["meshes"][node(gltf, "collision_hull")[1]["mesh"]]["primitives"][0]
        pos = accessor_rows(gltf, bin_chunk, prim["attributes"]["POSITION"])
        idx = [r[0] for r in accessor_rows(gltf, bin_chunk, prim["indices"])]
        return gltf, prim, pos, [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]

    def test_46_collision_hull_exists_per_family(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                m = package(family).manifest_data
                c = m["collision"]
                self.assertEqual((c["node"], c["representation"], c["scene"]),
                                 ("collision_hull", "convex_hull", "forge_collision"))
                gltf, prim, pos, tris = self.hull(family, 1337)
                self.assertEqual((len(pos), len(tris)), (c["vertices"], c["triangles"]))
                self.assertNotIn("material", prim)
                self.assertEqual(sorted(prim["attributes"]), ["POSITION"])
                scene = gltf["scenes"][c["scene_index"]]
                self.assertEqual([gltf["nodes"][i]["name"] for i in scene["nodes"]], ["collision_hull"])
                g = ARSENAL_GOLDEN[family]["collision"]
                self.assertEqual((c["vertices"], c["triangles"]), (g["vertices"], g["triangles"]))

    def test_47_collision_hull_validates_per_family(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    gltf, prim, pos, tris = self.hull(family, seed)
                    validate_package_bytes(package(family, seed).glb, package(family, seed).manifest)
                    hull_mesh = Mesh(name="hull", positions=tuple(pos), triangles=tuple(tris))
                    self.assertEqual(edge_problems(hull_mesh), [])
                    self.assertEqual(len(tris), 2 * len(pos) - 4, "a closed triangulated convex polyhedron")
                    # every render vertex (binary32) lies inside or on every hull face plane
                    render = {tuple(f32(c) for c in q) for mesh in asset(family, seed).components for q in mesh.positions}
                    for a, b, c in tris:
                        pa, pb, pc = pos[a], pos[b], pos[c]
                        u = [pb[k] - pa[k] for k in range(3)]
                        v = [pc[k] - pa[k] for k in range(3)]
                        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                        d = n[0] * pa[0] + n[1] * pa[1] + n[2] * pa[2]
                        worst = max(n[0] * q[0] + n[1] * q[1] + n[2] * q[2] - d for q in render)
                        self.assertLessEqual(worst, 1e-12)
                    self.assertTrue(set(pos) <= render, "hull vertices are render vertices")


class TestManifest(unittest.TestCase):
    """48-49."""

    def test_48_manifest_asset_type(self):
        for family in FAMILIES:
            m = package(family).manifest_data
            self.assertEqual(m["asset"]["asset_type"], family)
            self.assertEqual(m["package"]["root_node"], family)
            self.assertIn(f"asset_type:{family}", m["tags"])
            self.assertEqual(m["lods"]["levels"][0]["nodes"], list(COMPONENTS))
            self.assertEqual(m["asset"]["display_name"], REGISTRY.asset(family).descriptor.display_name)

    def test_49_manifest_generator_identity(self):
        for family in FAMILIES:
            m = package(family).manifest_data
            self.assertEqual(m["asset"]["generator_id"], GENERATOR_IDS[family])
            self.assertEqual(m["asset"]["generator_version"], 1)
            self.assertEqual(m["asset"]["seed"], "1337")
            self.assertEqual((m["presentation"]["presentation_id"], m["presentation"]["presentation_version"]),
                             (BLADE_PRESENTATION, 1))
            self.assertEqual(m["package"]["exporter"], {"format_id": "glb", "format_version": 1})
            self.assertEqual((m["contract"]["id"], m["contract"]["version"]), (CONTRACT_ID, 1))
            self.assertEqual(m["coordinates"]["convention_id"], "forge.rh-y-up-meters.grip-origin.v1")
            g = ARSENAL_GOLDEN[family]
            self.assertEqual(m["hashes"]["source_geometry_sha256"]["sha256"], g["integrity"]["geometry_sha256"])
            self.assertEqual({k: v["sha256"] for k, v in m["hashes"].items()}, g["package_hashes"])
            self.assertEqual(m["tags"], g["tags"])


class TestPackageDeterminism(unittest.TestCase):
    def test_58_engine_package_deterministic(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])\n"
                "from arsenal_support import build_package, FAMILIES\n"
                "print(' '.join(build_package(f, 1337, fresh=True).glb_sha256 + ':' + "
                "build_package(f, 1337, fresh=True).manifest_sha256 for f in FAMILIES))\n")
        env = dict(os.environ, PYTHONHASHSEED="777")
        r = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT), str(REPO_ROOT / "tests")], env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        other_process = r.stdout.split()
        for family, theirs in zip(FAMILIES, other_process):
            with self.subTest(family=family):
                a, b = build_package(family, 1337, fresh=True), build_package(family, 1337, fresh=True)
                self.assertEqual((a.glb, a.manifest), (b.glb, b.manifest))
                self.assertEqual(f"{a.glb_sha256}:{a.manifest_sha256}", theirs)
                pkg = EXAMPLES / f"{family}_seed1337_v1.forgepkg"
                self.assertEqual(a.glb, (pkg / "asset.glb").read_bytes())
                self.assertEqual(a.manifest, (pkg / "manifest.json").read_bytes())
                files = ARSENAL_GOLDEN[family]["files"]
                self.assertEqual(a.glb_sha256, files["asset.glb"]["sha256"])
                self.assertEqual(a.manifest_sha256, files["manifest.json"]["sha256"])
                self.assertEqual((len(a.glb), len(a.manifest)), (files["asset.glb"]["bytes"],
                                                                 files["manifest.json"]["bytes"]))

    def test_golden_packages_validate_on_disk(self):
        for family in FAMILIES:
            report = validate_package(EXAMPLES / f"{family}_seed1337_v1.forgepkg")
            self.assertEqual(report.asset_type, family)
            g = ARSENAL_GOLDEN[family]
            m = json.loads((EXAMPLES / f"{family}_seed1337_v1.forgepkg" / "manifest.json").read_bytes())
            self.assertEqual({s["name"]: {"translation": s["translation"], "rotation": s["rotation"]}
                              for s in m["sockets"]}, g["sockets"])


if __name__ == "__main__":
    unittest.main()
