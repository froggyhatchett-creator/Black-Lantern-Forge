"""Step 4 tests 1-31 and 39-55 (+ extra fail-closed cases): independent ingestion of a Contract v1 package.

The golden package is read from disk exactly as Step 3 froze it. Nothing here regenerates it.
"""

import json
import math
import random
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from forge_engine_viewer.errors import IngestionError
from forge_engine_viewer.glb import AccessorReader, read_glb
from forge_engine_viewer.ingest import ingest
from viewer_support import (
    FROZEN_GLB_SHA256,
    FROZEN_MANIFEST_SHA256,
    FROZEN_SOCKET_TIP,
    GOLDEN_DIR,
    copy_golden,
    golden_bytes,
    node,
    prim,
    raw_rows,
    sha256,
    split,
    variant,
)

GOLDEN = ingest(GOLDEN_DIR)
GLTF, JSON_CHUNK, BIN_CHUNK = split(golden_bytes()[0])
MANIFEST = json.loads(golden_bytes()[1])


class Refusals(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def pkg(self, **kwargs) -> Path:
        self.n += 1
        return variant(self.tmp / f"v{self.n}.forgepkg", **kwargs)

    def refuses(self, path, code, pattern=""):
        with self.assertRaises(IngestionError) as ctx:
            ingest(path)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        if pattern:
            self.assertRegex(ctx.exception.message, pattern)
        return ctx.exception


class TestOpenAndDiscover(Refusals):
    def test_01_opens_a_valid_package(self):
        p = ingest(GOLDEN_DIR)
        self.assertEqual(p.checks[0], "package.discovered")
        self.assertEqual(p.checks[-1], "hashes.semantic")
        self.assertEqual(len(p.checks), 16)
        self.assertEqual((p.contract_id, p.contract_version), ("forge.engine-contract", 1))

    def test_02_rejects_missing_manifest(self):
        d = copy_golden(self.tmp / "a.forgepkg")
        (d / "manifest.json").unlink()
        self.refuses(d, "missing_manifest")

    def test_03_rejects_missing_glb(self):
        d = copy_golden(self.tmp / "a.forgepkg")
        (d / "asset.glb").unlink()
        self.refuses(d, "missing_glb")

    def test_04_rejects_wrong_contract_id(self):
        self.refuses(self.pkg(manifest_fn=lambda m: m["contract"].__setitem__("id", "acme.contract")),
                     "unsupported_contract", "acme.contract")

    def test_05_rejects_unsupported_contract_version(self):
        for bad in (2, 0, "1", True, 1.0, None):
            with self.subTest(version=bad):
                self.refuses(self.pkg(manifest_fn=lambda m: m["contract"].__setitem__("version", bad)),
                             "unsupported_contract", "not supported")
        self.refuses(self.pkg(manifest_fn=lambda m: m["contract"].pop("version")), "unsupported_contract",
                     "no implicit latest")

    def test_06_rejects_glb_hash_mismatch(self):
        def flip(b):
            b[100] ^= 0x01
            return b
        e = self.refuses(self.pkg(bin_fn=flip, fix_hashes=False), "hash_mismatch", "asset.glb hashes to")
        self.assertIn(FROZEN_GLB_SHA256, e.message)                      # the declared (golden) value

    def test_non_canonical_manifest_refuses(self):
        # Same JSON content (so every hash still matches), different bytes: the contract fixes the byte form.
        for label, rewrite in (("compact", lambda b: json.dumps(json.loads(b), sort_keys=True).encode()),
                               ("crlf", lambda b: b.replace(b"\n", b"\r\n")),
                               ("no final newline", lambda b: b.rstrip(b"\n"))):
            with self.subTest(form=label):
                d = copy_golden(self.tmp / f"{label.replace(' ', '_')}.forgepkg")
                (d / "manifest.json").write_bytes(rewrite((d / "manifest.json").read_bytes()))
                self.refuses(d, "bad_manifest", "canonical")

    def test_other_discovery_refusals(self):
        self.refuses(self.tmp / "nowhere.forgepkg", "not_a_package")
        f = self.tmp / "file.forgepkg"
        f.write_text("x")
        self.refuses(f, "not_a_package")
        d = copy_golden(self.tmp / "extra.forgepkg")
        (d / "notes.txt").write_text("x")
        self.refuses(d, "unexpected_entry")
        d = copy_golden(self.tmp / "manifest_dir.forgepkg")
        (d / "manifest.json").unlink()
        (d / "manifest.json").mkdir()
        self.refuses(d, "missing_manifest", "not a file")


class TestIndependentGlbParser(Refusals):
    def test_07_parses_glb_header_independently(self):
        glb = golden_bytes()[0]
        parsed = read_glb(glb)
        self.assertEqual((parsed.version, parsed.length), (2, len(glb)))
        self.assertEqual(struct.unpack_from("<III", glb, 0), (0x46546C67, 2, len(glb)))
        for data, pattern in ((glb[:8], "shorter"), (b"gltf" + glb[4:], "magic"),
                              (glb[:4] + struct.pack("<I", 1) + glb[8:], "version is 1"),
                              (glb[:8] + struct.pack("<I", len(glb) + 4) + glb[12:], "header says")):
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(IngestionError, pattern):
                    read_glb(data)

    def test_08_parses_json_chunk_independently(self):
        parsed = read_glb(golden_bytes()[0])
        self.assertEqual(parsed.json_chunk, JSON_CHUNK)
        self.assertEqual(parsed.document, GLTF)
        bad = b'{"scene":0,"scene":0}   '
        glb = (struct.pack("<III", 0x46546C67, 2, 20 + len(bad) + 8 + len(BIN_CHUNK)) + struct.pack("<II", len(bad), 0x4E4F534A)
               + bad + struct.pack("<II", len(BIN_CHUNK), 0x004E4942) + BIN_CHUNK)
        with self.assertRaisesRegex(IngestionError, "repeats the key"):
            read_glb(glb)

    def test_09_parses_bin_chunk_independently(self):
        parsed = read_glb(golden_bytes()[0])
        self.assertEqual(parsed.bin_chunk, BIN_CHUNK)
        self.assertEqual(len(parsed.bin_chunk), GLTF["buffers"][0]["byteLength"])
        glb = golden_bytes()[0]
        json_len = struct.unpack_from("<I", glb, 12)[0]
        wrong_type = glb[:24 + json_len] + b"BIX\0" + glb[28 + json_len:]
        with self.assertRaisesRegex(IngestionError, "exactly a JSON chunk then a BIN chunk"):
            read_glb(wrong_type)

    def _decoded(self, name):
        return next(m for m in GOLDEN.meshes if m.node == name)

    def test_10_decodes_position(self):
        for name in ("blade", "guard", "grip", "pommel"):
            mesh = self._decoded(name)
            self.assertEqual(list(mesh.positions), raw_rows(GLTF, BIN_CHUNK, prim(GLTF, name)["attributes"]["POSITION"]))
        top = max(p[1] for p in self._decoded("blade").positions)
        self.assertEqual(top, FROZEN_SOCKET_TIP[1])

    def test_11_decodes_normal(self):
        for mesh in GOLDEN.meshes:
            self.assertEqual(list(mesh.normals), raw_rows(GLTF, BIN_CHUNK, prim(GLTF, mesh.node)["attributes"]["NORMAL"]))
            for n in mesh.normals:
                self.assertAlmostEqual(math.sqrt(sum(c * c for c in n)), 1.0, delta=1e-6)

    def test_12_decodes_texcoord_0(self):
        for mesh in GOLDEN.meshes:
            self.assertEqual(list(mesh.texcoords),
                             raw_rows(GLTF, BIN_CHUNK, prim(GLTF, mesh.node)["attributes"]["TEXCOORD_0"]))
            self.assertTrue(all(0.0 <= c <= 1.0 for uv in mesh.texcoords for c in uv))

    def test_13_decodes_indices(self):
        for mesh in GOLDEN.meshes:
            self.assertEqual(list(mesh.indices), [r[0] for r in raw_rows(GLTF, BIN_CHUNK, prim(GLTF, mesh.node)["indices"])])
            self.assertEqual(len(mesh.indices) % 3, 0)
        self.assertEqual(sum(m.triangle_count for m in GOLDEN.meshes), 280)

    def test_14_index_bounds_are_checked(self):
        accessor = GLTF["accessors"][prim(GLTF, "blade")["indices"]]
        offset = GLTF["bufferViews"][accessor["bufferView"]]["byteOffset"]

        def poke(b):
            struct.pack_into("<H", b, offset, 4000)        # the blade has 113 vertices
            return b
        self.refuses(self.pkg(bin_fn=poke), "bad_accessor", "out of range")

    def test_15_buffer_view_bounds_are_checked(self):
        def huge(g):
            g["bufferViews"][3]["byteLength"] = 10 ** 6
        self.refuses(self.pkg(gltf_fn=huge), "bad_accessor", "covers bytes")

    def test_16_accessor_bounds_are_checked(self):
        def overrun(g):
            g["accessors"][0]["count"] += 1
        self.refuses(self.pkg(gltf_fn=overrun), "bad_accessor", "needs .* bytes")

    def test_decoder_refuses_unsupported_representations(self):
        reader = AccessorReader(read_glb(golden_bytes()[0]))
        with self.assertRaises(IngestionError) as ctx:
            reader.decode(0, "test", types=("VEC2",), components=(5126,))     # accessor 0 is a VEC3
        self.assertEqual(ctx.exception.code, "unsupported_accessor")


class TestScenesSocketsCollision(Refusals):
    def test_17_default_render_scene_excludes_collision_hull(self):
        self.assertEqual(GOLDEN.render_scene, (0, "forge_render"))
        self.assertEqual([m.node for m in GOLDEN.meshes], ["blade", "guard", "grip", "pommel"])
        self.assertNotIn("collision_hull", [m.node for m in GOLDEN.meshes])

    def test_18_collision_scene_contains_collision_hull(self):
        c = GOLDEN.collision
        self.assertEqual((c.node, c.scene_index, c.scene_name), ("collision_hull", 1, "forge_collision"))
        self.assertEqual(GLTF["scenes"][1]["nodes"], [c.node_index])

    def _moved(self, name, translation, rotation=None):
        def g(gltf):
            n = node(gltf, name)[1]
            n["translation"] = translation
            if rotation:
                n["rotation"] = rotation

        def m(man):
            s = next(s for s in man["sockets"] if s["name"] == name)
            s["translation"] = translation
            if rotation:
                s["rotation"] = rotation
        from engine_support import rehash            # full rehash: a consistent package, not a corrupted one
        d = self.pkg(gltf_fn=g, manifest_fn=m)
        glb = (d / "asset.glb").read_bytes()
        (d / "manifest.json").write_bytes(rehash(glb, json.loads((d / "manifest.json").read_bytes())))
        return ingest(d)

    def test_19_socket_grip_is_loaded_from_the_node_hierarchy(self):
        s = GOLDEN.socket("socket_grip")
        i, n = node(GLTF, "socket_grip")
        self.assertEqual((s.node_index, s.parent), (i, "short_sword"))
        self.assertEqual(list(s.local.translation), n["translation"])
        self.assertEqual(list(s.world.translation), [0.0, 0.0, 0.0])

    def test_20_socket_tip_is_loaded_from_the_node_hierarchy_not_derived(self):
        s = GOLDEN.socket("socket_tip")
        self.assertEqual((s.node_index, list(s.local.translation)), (node(GLTF, "socket_tip")[0], FROZEN_SOCKET_TIP))
        moved = self._moved("socket_tip", [0.0, 0.5, 0.0])     # no longer at the blade apex: still reported as shipped
        self.assertEqual(list(moved.socket("socket_tip").world.translation), [0.0, 0.5, 0.0])

    def test_21_socket_transforms_match_manifest_and_respect_rotation(self):
        for s in GOLDEN.sockets:
            declared = next(d for d in MANIFEST["sockets"] if d["name"] == s.name)
            self.assertEqual(list(s.local.translation), declared["translation"])
            self.assertEqual(list(s.local.rotation), declared["rotation"])
        h = math.sqrt(0.5)
        turned = self._moved("socket_tip", FROZEN_SOCKET_TIP, [0.0, 0.0, h, h])   # 90 degrees about +Z
        tip = turned.socket("socket_tip")
        self.assertEqual(list(tip.world.rotation), [0.0, 0.0, h, h])
        from forge_engine_viewer.ingest import rotate
        x_axis = rotate(tip.world.rotation, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(x_axis[1], 1.0, places=12)                         # +X now points along +Y

        def disagree(m):
            m["sockets"][1]["translation"] = [0.0, 0.6, 0.0]
        self.refuses(self.pkg(manifest_fn=disagree), "identity_mismatch", "manifest transform differs")

    def test_22_collision_hull_is_loaded_from_the_package(self):
        c = GOLDEN.collision
        p = prim(GLTF, "collision_hull")
        self.assertEqual(list(c.positions), raw_rows(GLTF, BIN_CHUNK, p["attributes"]["POSITION"]))
        self.assertEqual(list(c.indices), [r[0] for r in raw_rows(GLTF, BIN_CHUNK, p["indices"])])
        self.assertEqual(c.representation, "convex_hull")
        self.assertTrue(c.closed)

    def test_23_collision_is_not_recomputed(self):
        # Ship a different, still valid hull (the render geometry's bounding box): the viewer must report
        # exactly that box (8 vertices, 12 triangles). A hull it built itself would have 49/94.
        pts = [p for m in GOLDEN.meshes for p in m.positions]
        lo = [min(p[k] for p in pts) for k in range(3)]
        hi = [max(p[k] for p in pts) for k in range(3)]
        box = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        tris = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
                (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]

        def g(gltf):
            hull = prim(gltf, "collision_hull")
            pa, ia = gltf["accessors"][hull["attributes"]["POSITION"]], gltf["accessors"][hull["indices"]]
            pa.update(count=8, min=list(lo), max=list(hi))
            ia["count"] = 36
            gltf["bufferViews"][pa["bufferView"]]["byteLength"] = 96
            gltf["bufferViews"][ia["bufferView"]]["byteLength"] = 72

        def b(data):
            pa = GLTF["bufferViews"][GLTF["accessors"][prim(GLTF, "collision_hull")["attributes"]["POSITION"]]["bufferView"]]
            ia = GLTF["bufferViews"][GLTF["accessors"][prim(GLTF, "collision_hull")["indices"]]["bufferView"]]
            struct.pack_into("<24f", data, pa["byteOffset"], *[c for p in box for c in p])
            struct.pack_into("<36H", data, ia["byteOffset"], *[i for t in tris for i in t])
            return data

        def m(man):
            man["collision"]["vertices"], man["collision"]["triangles"] = 8, 12
        from engine_support import rehash
        d = self.pkg(gltf_fn=g, bin_fn=b, manifest_fn=m)
        (d / "manifest.json").write_bytes(rehash((d / "asset.glb").read_bytes(), json.loads((d / "manifest.json").read_bytes())))
        c = ingest(d).collision
        self.assertEqual((len(c.positions), c.triangle_count), (8, 12))
        self.assertEqual(sorted(c.positions), sorted(box))


class TestMaterialsAndManifest(unittest.TestCase):
    def components(self):
        return MANIFEST["materials"]["components"]

    def test_24_materials_load_base_color_factor(self):
        for mat, gl, comp in zip(GOLDEN.materials, GLTF["materials"], self.components()):
            self.assertEqual(list(mat.base_color_factor), gl["pbrMetallicRoughness"]["baseColorFactor"])
            self.assertEqual(list(mat.base_color_factor), comp["base_color_factor"])

    def test_25_materials_load_metallic_factor(self):
        self.assertEqual([m.metallic_factor for m in GOLDEN.materials], [c["metallic_factor"] for c in self.components()])
        self.assertEqual([m.metallic_factor for m in GOLDEN.materials], [1.0, 1.0, 0.0, 1.0])

    def test_26_materials_load_roughness_factor(self):
        self.assertEqual([m.roughness_factor for m in GOLDEN.materials],
                         [c["roughness_factor"] for c in self.components()])
        self.assertEqual([m.name for m in GOLDEN.materials], ["forge_blade", "forge_guard", "forge_grip", "forge_pommel"])
        self.assertEqual([m.preset for m in GOLDEN.materials], ["bronze", "steel", "black_leather", "steel"])

    def test_27_manifest_seed(self):
        self.assertEqual(GOLDEN.asset["seed"], "1337")

    def test_28_manifest_generator_version(self):
        self.assertEqual((GOLDEN.asset["generator_id"], GOLDEN.asset["generator_version"]), ("forge.sword", 1))
        self.assertEqual(GOLDEN.presentation["presentation_version"], 1)

    def test_29_coordinate_convention(self):
        c = GOLDEN.coordinates
        self.assertEqual(c["convention_id"], "forge.rh-y-up-meters.grip-origin.v1")
        self.assertEqual((c["handedness"], c["up_axis"], c["origin"], c["front_face_winding"]),
                         ("right", "+Y", "grip_center", "counter_clockwise"))

    def test_30_units_are_meters(self):
        self.assertEqual((GOLDEN.coordinates["units"], GOLDEN.coordinates["meters_per_unit"]), ("meters", 1))

    def test_31_lod0_metadata(self):
        self.assertEqual(len(GOLDEN.lods), 1)
        lv = GOLDEN.lods[0]
        self.assertEqual((lv.level, lv.nodes, lv.vertices, lv.triangles), (0, ("blade", "guard", "grip", "pommel"), 379, 280))
        self.assertIn("LOD0 only", GOLDEN.lod_note)


class TestGolden(unittest.TestCase):
    def test_39_golden_seed_1337_package_loads(self):
        self.assertEqual((GOLDEN.asset["asset_type"], GOLDEN.asset["seed"]), ("short_sword", "1337"))
        self.assertEqual(GOLDEN.path, str(GOLDEN_DIR))

    def test_40_golden_glb_hash_equals_frozen_step3_value(self):
        self.assertEqual(GOLDEN.glb_sha256, FROZEN_GLB_SHA256)
        self.assertEqual(sha256((GOLDEN_DIR / "asset.glb").read_bytes()), FROZEN_GLB_SHA256)

    def test_41_golden_manifest_hash_equals_frozen_step3_value(self):
        self.assertEqual(GOLDEN.manifest_sha256, FROZEN_MANIFEST_SHA256)

    def test_42_socket_grip_at_origin(self):
        self.assertEqual(list(GOLDEN.socket("socket_grip").world.translation), [0, 0, 0])

    def test_43_socket_tip_frozen(self):
        self.assertEqual(list(GOLDEN.socket("socket_tip").world.translation), FROZEN_SOCKET_TIP)
        self.assertEqual(list(GOLDEN.socket("socket_tip").world.rotation), [0.0, 0.0, 0.0, 1.0])

    def test_44_collision_counts(self):
        self.assertEqual((len(GOLDEN.collision.positions), GOLDEN.collision.triangle_count), (49, 94))

    def test_all_package_verifiable_hashes_are_recomputed(self):
        self.assertEqual(set(GOLDEN.hashes_verified),
                         {k for k in MANIFEST["hashes"] if not k.startswith("source_")})
        self.assertEqual(len(GOLDEN.provenance_hashes), 5)


class TestStructuralRefusals(Refusals):
    def test_45_malformed_accessor_refuses(self):
        def byte_indices(g):
            g["accessors"][prim(g, "blade")["indices"]]["componentType"] = 5121
        self.refuses(self.pkg(gltf_fn=byte_indices), "unsupported_accessor", "componentType 5121")

        def matrix_type(g):
            g["accessors"][prim(g, "blade")["attributes"]["POSITION"]]["type"] = "MAT4"
        self.refuses(self.pkg(gltf_fn=matrix_type), "unsupported_accessor")

        def sparse(g):
            g["accessors"][0]["sparse"] = {"count": 1}
        self.refuses(self.pkg(gltf_fn=sparse), "unsupported_feature", "sparse")

        def stride(g):
            g["bufferViews"][0]["byteStride"] = 12
        self.refuses(self.pkg(gltf_fn=stride), "unsupported_feature", "byteStride")

        def misaligned(g):
            g["accessors"][prim(g, "blade")["attributes"]["POSITION"]]["byteOffset"] = 2
        self.refuses(self.pkg(gltf_fn=misaligned), "bad_accessor", "aligned")

    def _drop(self, attribute):
        def g(gltf):
            del prim(gltf, "guard")["attributes"][attribute]
        return self.pkg(gltf_fn=g)

    def test_46_missing_position_refuses(self):
        self.refuses(self._drop("POSITION"), "missing_attribute", "no POSITION")

    def test_47_missing_normal_refuses(self):
        self.refuses(self._drop("NORMAL"), "missing_attribute", "no NORMAL")

    def test_48_missing_texcoord_0_refuses(self):
        self.refuses(self._drop("TEXCOORD_0"), "missing_attribute", "no TEXCOORD_0")

    def _rename(self, old, new):
        def g(gltf):
            node(gltf, old)[1]["name"] = new
        return self.pkg(gltf_fn=g)

    def test_49_missing_socket_grip_refuses(self):
        self.refuses(self._rename("socket_grip", "grip_point"), "missing_socket", "socket_grip")

    def test_50_missing_socket_tip_refuses(self):
        self.refuses(self._rename("socket_tip", "tip_point"), "missing_socket", "socket_tip")
        self.refuses(self.pkg(manifest_fn=lambda m: m["sockets"].pop()), "missing_socket", "not declared")

    def test_51_missing_collision_hull_refuses(self):
        self.refuses(self._rename("collision_hull", "hull"), "missing_collision", "collision_hull")

        def drop(g):
            i, n = node(g, "collision_hull")
            del g["nodes"][i]
            del g["scenes"][1]
        self.refuses(self.pkg(gltf_fn=drop), "bad_scene", "exactly two scenes")

    def test_52_wrong_units_refuse(self):
        for key, value in (("units", "centimeters"), ("meters_per_unit", 100), ("meters_per_unit", 1.0)):
            with self.subTest(key=key, value=value):
                self.refuses(self.pkg(manifest_fn=lambda m: m["coordinates"].__setitem__(key, value)),
                             "bad_coordinates", key)

    def test_53_wrong_up_axis_refuses(self):
        for key, value in (("up_axis", "+Z"), ("handedness", "left"), ("origin", "pommel_base"),
                           ("front_face_winding", "clockwise")):
            with self.subTest(key=key):
                self.refuses(self.pkg(manifest_fn=lambda m: m["coordinates"].__setitem__(key, value)),
                             "bad_coordinates", key)

    def test_54_invalid_scene_index_refuses(self):
        self.refuses(self.pkg(gltf_fn=lambda g: g.__setitem__("scene", 3)), "bad_scene", "scene 0")
        self.refuses(self.pkg(gltf_fn=lambda g: g["scenes"][1].__setitem__("nodes", [99])), "bad_scene", "does not exist")
        self.refuses(self.pkg(gltf_fn=lambda g: g["scenes"][0].__setitem__("nodes", [1])), "bad_scene", "non-root")

    def test_55_invalid_material_index_refuses(self):
        self.refuses(self.pkg(gltf_fn=lambda g: prim(g, "grip").__setitem__("material", 9)), "bad_material",
                     "material 9")

    def test_transforms_outside_contract_v1_refuse(self):
        self.refuses(self.pkg(gltf_fn=lambda g: node(g, "socket_tip")[1].__setitem__("scale", [2, 2, 2])),
                     "bad_transform", "scale")
        self.refuses(self.pkg(gltf_fn=lambda g: node(g, "socket_tip")[1].__setitem__("rotation", [0, 0, 0, 2])),
                     "bad_transform", "unit quaternion")
        self.refuses(self.pkg(gltf_fn=lambda g: node(g, "short_sword")[1].__setitem__("translation", [0, 1, 0])),
                     "bad_transform", "asset root")

    def test_unsupported_features_refuse_clearly(self):
        self.refuses(self.pkg(gltf_fn=lambda g: g.__setitem__("animations", [{}])), "unsupported_feature", "animations")
        self.refuses(self.pkg(gltf_fn=lambda g: g.__setitem__("extensionsRequired", ["KHR_draco_mesh_compression"])),
                     "unsupported_feature")
        self.refuses(self.pkg(gltf_fn=lambda g: g.__setitem__("textures", [{"source": 0}])), "unsupported_feature",
                     "does not support them")
        self.refuses(self.pkg(gltf_fn=lambda g: prim(g, "blade").__setitem__("mode", 1)), "bad_mesh", "mode 4")

    def test_semantic_hashes_catch_a_structurally_valid_edit(self):
        def nudge(b):                                    # one UV mantissa bit: structure stays valid
            view = GLTF["bufferViews"][GLTF["accessors"][prim(GLTF, "blade")["attributes"]["TEXCOORD_0"]]["bufferView"]]
            b[view["byteOffset"]] ^= 0x01
            return b
        self.refuses(self.pkg(bin_fn=nudge), "hash_mismatch", "render_geometry_sha256")

    def test_collision_must_still_be_a_convex_hull_of_the_render_geometry(self):
        def shrink(b):
            acc = GLTF["accessors"][prim(GLTF, "collision_hull")["attributes"]["POSITION"]]
            off = GLTF["bufferViews"][acc["bufferView"]]["byteOffset"]
            rows = raw_rows(GLTF, BIN_CHUNK, prim(GLTF, "collision_hull")["attributes"]["POSITION"])
            struct.pack_into(f"<{3 * len(rows)}f", b, off, *[c * 0.5 for r in rows for c in r])
            return b

        def minmax(g):
            acc = g["accessors"][prim(g, "collision_hull")["attributes"]["POSITION"]]
            acc["min"] = [c * 0.5 for c in acc["min"]]
            acc["max"] = [c * 0.5 for c in acc["max"]]
        self.refuses(self.pkg(gltf_fn=minmax, bin_fn=shrink), "bad_collision", "not a convex hull")

    def test_random_damage_is_always_refused_cleanly(self):
        """Ordinary bad input must raise IngestionError, never crash with another exception."""
        rng = random.Random(4)
        glb, man = golden_bytes()
        _, json_chunk, _ = split(glb)
        outcomes = {"refused": 0, "accepted": 0}
        for trial in range(160):
            target = rng.choice(("glb", "manifest", "json"))
            data = bytearray({"glb": glb, "manifest": man, "json": glb}[target])
            lo = 20 if target == "json" else 0
            hi = 20 + len(json_chunk) if target == "json" else len(data)
            for _ in range(rng.randint(1, 3)):
                data[rng.randrange(lo, hi)] = rng.randrange(256)
            d = self.tmp / f"fuzz{trial}.forgepkg"
            d.mkdir()
            (d / "asset.glb").write_bytes(bytes(data) if target != "manifest" else glb)
            (d / "manifest.json").write_bytes(bytes(data) if target == "manifest" else man)
            try:
                ingest(d)
                outcomes["accepted"] += 1
            except IngestionError:
                outcomes["refused"] += 1
            shutil.rmtree(d)
        self.assertEqual(outcomes["accepted"], 0)       # every byte is hash-covered: nothing damaged gets in
        self.assertEqual(outcomes["refused"], 160)


if __name__ == "__main__":
    unittest.main()
