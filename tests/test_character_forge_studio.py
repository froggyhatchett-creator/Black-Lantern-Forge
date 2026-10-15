"""Character Forge Phase 2: studio pack, head-space hairstyles, DNA layers, LOD, studio server, new clips."""

import gzip
import json
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from forge_character_forge import dna as D
from forge_character_forge import hair
from forge_character_forge.anatomy import head_frame
from forge_character_forge.animation import CLIPS, clip
from forge_character_forge.appearance import AppearanceParams, hair_highlight_mask
from forge_character_forge.lod import decimate
from forge_character_forge.params import ParameterError, preset
from forge_character_forge.skeleton import build_skeleton
from forge_character_forge.studio_bake import (BODY_RANGES, FACE_RANGES, PACK_MAGIC, _Blob, compact_pack, pack_array,
                                               read_pack)

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "examples" / "character_forge_aaa" / "studio" / "studio_pack.bin"


class HairStyleTests(unittest.TestCase):
    def test_styles_mesh_in_head_space(self):
        for style in hair.STYLES:
            v, t = hair.unit_mesh(style)
            self.assertGreater(len(t), 5000, style)
            self.assertTrue((t >= 0).all() and (t < len(v)).all(), style)
            self.assertGreater(v[:, 1].max(), 0.23, f"{style} covers the crown")
            # the face (in front of the cheeks, below the brows) stays clear, except the asymmetric fringe
            face = (v[:, 2] > 0.06) & (v[:, 1] > 0.02) & (v[:, 1] < 0.11) & (np.abs(v[:, 0]) < 0.05)
            self.assertEqual(int(face.sum()), 0, f"{style} covers the face")
        self.assertLess(hair.unit_mesh("long")[0][:, 1].min(), -0.3, "long hair reaches the back")
        self.assertGreater(hair.unit_mesh("pixie")[0][:, 1].min(), 0.04, "pixie stays above the nape")
        bv, _ = hair.unit_mesh("bangs")
        fringe = bv[(bv[:, 2] > 0.06) & (bv[:, 1] < 0.15)]
        self.assertGreater(len(fringe), 50, "bangs have a fringe over the forehead")
        self.assertLess(fringe[fringe[:, 0] < 0][:, 1].min(), fringe[fringe[:, 0] > 0][:, 1].min(), "the fringe is asymmetric")

    def test_head_frame_from_joints_is_exact(self):
        # studio.js places head-space parts from the evaluated head/jaw joints; this is the identity it relies on
        for name in ("neutral", "male", "female"):
            b, f, _ = preset(name)
            for b2 in (b, b.with_(head_size=1.2, height_m=1.95), b.with_(neck_length=0.85)):
                s = build_skeleton(b2, f)
                H, J = s.rest[s.index("head")], s.rest[s.index("jaw")]
                h = (J[1] - H[1]) / 0.1
                O, hh = head_frame(s)
                self.assertAlmostEqual(h, hh, places=9)
                np.testing.assert_allclose([0.0, H[1] - 0.2 * h, H[2]], O, atol=1e-9)

    def test_build_style_part_and_weights(self):
        b, f, _ = preset("female")
        s = build_skeleton(b, f)
        p = hair.build_style(s, "long")
        self.assertEqual(p.material, "hair")
        np.testing.assert_allclose(p.weights.sum(1), 1.0, atol=1e-9)
        low = p.verts[:, 1] < np.percentile(p.verts[:, 1], 10)
        self.assertTrue((p.joints[low] == s.index("spine_03")).any(), "hair ends follow the upper spine")

    def test_highlights_are_appearance_only(self):
        with self.assertRaises(ParameterError):
            AppearanceParams(hair_highlight_amount=1.5)
        with self.assertRaises(ParameterError):
            AppearanceParams(hair_highlight_color="blue")
        app = AppearanceParams(hair_style="bob", hair_highlight_amount=0.6, hair_highlight_color="#d0a060")
        v, _ = hair.unit_mesh("bob")
        c = app.hair_vertex_colors(v)
        m = hair_highlight_mask(v)
        self.assertTrue(0.05 < (m > 0.5).mean() < 0.7, "streaks cover part of the hair")
        self.assertGreater(np.ptp(c[:, 0]), 0.05)
        self.assertIsNone(AppearanceParams().hair_vertex_colors(v))


class DnaLayerTests(unittest.TestCase):
    def test_styling_and_wardrobe_do_not_change_anatomy(self):
        a = D.new_dna("female")
        h = D.anatomy_hash(a)
        b = D.set_trait(a, "appearance.hair_color", "#aa3311")
        b = D.set_trait(b, "appearance.hair_style", "bangs")
        b = D.set_trait(b, "appearance.hair_highlight_amount", 0.4)
        b = D.set_trait(b, "wardrobe.outfit", ["robe"])
        self.assertEqual(D.anatomy_hash(b), h)
        self.assertNotEqual(D.anatomy_hash(D.set_trait(a, "face.jaw_width", 1.1)), h)
        self.assertEqual(D.layer_of("appearance.hair_highlight_color"), "styling")
        self.assertEqual(D.layer_of("wardrobe.colors"), "wardrobe")
        self.assertEqual(D.layer_of("appearance.skin_tone"), "anatomy")

    def test_old_dna_without_new_traits_still_loads(self):
        a = D.new_dna("male")
        for k in ("appearance.hair_highlight_color", "appearance.hair_highlight_amount"):
            del a["traits"][k]
        spec = D.to_spec(a)
        self.assertEqual(spec.appearance.hair_highlight_amount, 0.0)


class GeneratorVersionTests(unittest.TestCase):
    def test_v1_dna_files_load_and_exports_are_stamped(self):
        from forge_character_forge.character import GENERATOR_HISTORY, GENERATOR_VERSION, build_character
        from forge_character_forge.gltf import write_glb
        from forge_character_forge.validate import read_glb
        self.assertIn(GENERATOR_VERSION, GENERATOR_HISTORY)
        self.assertGreater(GENERATOR_VERSION, 1, "the face/template change must be versioned")
        files = sorted((ROOT / "examples" / "character_forge_aaa" / "dna").glob("*.dna.json"))
        self.assertGreater(len(files), 3)
        for f in files:  # written by generator v1: parameters only, so they must still validate and convert
            d = json.loads(f.read_text())
            D.validate_dna(d)
            D.to_spec(d)
        spec = D.to_spec(json.loads(files[0].read_text()))
        ch = build_character(spec, "public", fast=True)
        with tempfile.TemporaryDirectory() as td:
            gltf, _ = read_glb(write_glb(ch, Path(td) / "v.glb"))
        meta = gltf["asset"]["extras"]["forge"]
        self.assertEqual(meta["generator"], {"id": "forge.character-forge", "version": GENERATOR_VERSION})
        self.assertEqual(meta["fixed_topology_vertices"], GENERATOR_HISTORY[GENERATOR_VERSION]["template_vertices"])


class PackTests(unittest.TestCase):
    def test_compaction_is_exactly_reversible(self):
        rng = np.random.default_rng(3)
        blob = _Blob()
        dense = rng.integers(-32768, 32767, size=(500, 3)).astype("<i2")
        idx = np.sort(rng.choice(100000, 300, replace=False)).astype("<u4")
        tris = rng.integers(0, 70000, size=(400, 3)).astype("<u4")
        man = {"a": {"dense": blob.add(dense), "scale": 1.0}, "b": {"idx": blob.add(idx), "val": blob.add(dense[:300])},
               "parts": {"x": {"idx": blob.add(tris), "pos": blob.add(rng.random((10, 3)).astype("<f4"))}}}
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.bin"
            js = json.dumps(man).encode()
            src.write_bytes(gzip.compress(PACK_MAGIC + struct.pack("<I", len(js)) + js + bytes(blob.buf)))
            compact_pack(src, Path(td) / "c.bin")
            m2, b2 = read_pack(Path(td) / "c.bin")
        np.testing.assert_array_equal(pack_array(m2["a"]["dense"], b2), dense)
        np.testing.assert_array_equal(pack_array(m2["b"]["idx"], b2), idx)
        np.testing.assert_array_equal(pack_array(m2["b"]["val"], b2), dense[:300])
        np.testing.assert_array_equal(pack_array(m2["parts"]["x"]["idx"], b2), tris)
        self.assertEqual(m2["b"]["idx"]["enc"], "d1p")

    @unittest.skipUnless(PACK.exists(), "studio pack not built")
    def test_shipped_pack_contents(self):
        man, blob = read_pack(PACK)
        self.assertEqual(len(man["params"]), len(BODY_RANGES) + len(FACE_RANGES))
        self.assertEqual(man["unstable_topology"], [])
        for style in hair.STYLES:
            e = man["parts"][f"hair_{style}"]
            self.assertEqual(e["frame"], "head")
            np.testing.assert_allclose(pack_array(e["pos"], blob).reshape(-1, 3), hair.unit_mesh(style)[0], atol=1e-6)
            self.assertEqual(len(pack_array(e["highlight"], blob)), e["n"])
        body = man["parts"]["body"]
        tris = pack_array(body["idx"], blob)
        self.assertEqual(int(tris.max()) + 1, body["n"])
        self.assertTrue({"male", "female", "neutral"} <= set(man["presets"]))
        self.assertTrue({"run", "turn", "sudden_stop"} <= set(man["clips"]))
        self.assertLess(PACK.stat().st_size, 15_000_000, "pack fits the artifact binary limit")
        from forge_character_forge.character import GENERATOR_VERSION
        self.assertEqual(man["generator"]["version"], GENERATOR_VERSION)
        self.assertEqual(man["generator"]["template_vertices"], body["n"])


class LodTests(unittest.TestCase):
    def test_decimate_sphere(self):
        from forge_character_forge.accessories import uv_sphere
        v, t = uv_sphere(40, 60)[:2]
        keep, nt = decimate(v, t, 1000)
        self.assertLessEqual(len(nt), 1000)
        self.assertTrue((nt >= 0).all() and (nt < len(keep)).all())
        edges = {}
        for a, b, c in nt.tolist():
            for x, y in ((a, b), (b, c), (c, a)):
                edges[(min(x, y), max(x, y))] = edges.get((min(x, y), max(x, y)), 0) + 1
        self.assertLessEqual(max(edges.values()), 2, "still 2-manifold")
        r = np.linalg.norm(v[keep], axis=1)
        np.testing.assert_allclose(r, np.linalg.norm(v[0]), rtol=1e-6)  # kept vertices lie on the original surface


class ClipTests(unittest.TestCase):
    def test_new_clips(self):
        self.assertTrue({"idle", "walk", "run", "jump", "turn", "sudden_stop"} <= set(CLIPS))
        stop = clip("sudden_stop")
        self.assertFalse(stop.loop)
        z = stop.root_translation[:, 2]
        speed = np.abs(np.diff(z)) * 30
        self.assertGreater(speed[:20].mean(), 1.0, "travels before stopping")
        self.assertLess(speed[-10:].mean(), 0.05, "ends at rest")
        run = clip("run")
        self.assertLess(len(run.times), len(clip("walk").times), "run cycle is faster than walk")
        q = clip("turn").rotations["root"]
        yaw = np.unwrap(2 * np.arctan2(q[:, 1], q[:, 3]))
        self.assertGreater(np.ptp(yaw), np.radians(170), "turns around in place")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from forge_character_forge.studio_server import serve
        if not PACK.exists():
            raise unittest.SkipTest("studio pack not built")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.httpd = serve(0, PACK, Path(cls.tmp.name))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_routes(self):
        st, ct, body = self.get("/api/health")
        self.assertEqual(json.loads(body)["ok"], True)
        st, ct, body = self.get("/")
        self.assertTrue(body.startswith(b"<!doctype html>"))
        self.assertIn(b"Character Studio", body)
        st, ct, body = self.get("/studio.js")
        self.assertEqual(ct, "text/javascript")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/../forge_character_forge/dna.py")
        self.assertEqual(cm.exception.code, 404)
        cm.exception.close()

    def test_export_rejects_bad_dna(self):
        req = urllib.request.Request(self.base + "/api/export", data=json.dumps({"schema": "nope"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()
        minor = D.new_dna("female")
        minor["identity"]["age_years"] = 16
        req = urllib.request.Request(self.base + "/api/export", data=json.dumps(minor).encode(), method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertIn("adult", json.loads(cm.exception.read())["error"])
        cm.exception.close()


class KitTests(unittest.TestCase):
    def test_props_mesh_decimate_and_attach(self):
        from forge_character_forge import kit
        lt = kit.lantern()
        v, t = lt["frame"]
        self.assertLessEqual(len(t), 6000)
        chain = kit.lod_chain(v, t, (0.5, 0.25))
        self.assertEqual([len(x[1]) <= n for x, n in zip(chain, (6000, 3000, 1500))], [True] * 3)
        b, f, _ = preset("male")
        s = build_skeleton(b, f)
        p = kit.attach(s, "kit_lantern_frame", v, t, "hand_r", "kit_metal")
        self.assertTrue((p.joints[:, 0] == s.index("hand_r")).all())
        np.testing.assert_allclose(p.weights[:, 0], 1.0)
        self.assertLess(np.linalg.norm(p.verts.mean(0) - s["hand_r"]), 0.2)


class ReconstructionPhase2Tests(unittest.TestCase):
    """Hairstyle and lower-garment inference on generated references with known parameters.

    The thresholds were calibrated on these same images, so this guards behavior; it is not an accuracy claim."""

    REFS = ROOT / "examples" / "character_forge_aaa" / "references"

    def run_ref(self, name):
        from forge_character_forge.reconstruct import load_reference, reconstruct
        dna, _ = reconstruct([load_reference(self.REFS / name, authorized=True)], log=lambda *a: None)
        D.validate_dna(dna)
        return dna

    def test_hairstyles_and_skirt(self):
        truth = json.loads((self.REFS / "ground_truth.json").read_text())
        for name in ("ref_bob_skirt.png", "ref_bangs_portrait.png", "ref_long_male.png", "ref_full_front.png"):
            dna = self.run_ref(name)
            t = dna["traits"]
            self.assertEqual(t["appearance.hair_style"]["value"], truth[name]["appearance"]["hair_style"], name)
            self.assertEqual(t["appearance.hair_style"]["provenance"], "estimated")
            self.assertLessEqual(t["appearance.hair_style"]["confidence"], 0.5)
            rec = dna["reconstruction"]
            self.assertIn("not claimed", rec["likeness"])
            for k, (lo, hi) in rec["uncertainty"].items():
                v = t[k]["value"]
                self.assertLessEqual(lo, v + 1e-9, k)
                self.assertGreaterEqual(hi, v - 1e-9, k)
            if name == "ref_bob_skirt.png":
                self.assertIn("skirt", t["wardrobe.outfit"]["value"])
                self.assertIn("gap between the legs", t["wardrobe.outfit"]["note"])
            if name == "ref_long_male.png":
                self.assertIn("pants", t["wardrobe.outfit"]["value"])


if __name__ == "__main__":
    unittest.main()
