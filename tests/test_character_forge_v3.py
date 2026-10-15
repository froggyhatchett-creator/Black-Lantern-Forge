"""Generator v3 Phase 1: CC0 assets, rig mapping, controls, corrected blink, garments and the v3 studio pack."""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np

from forge_character_forge.studio_bake import BODY_RANGES, FACE_RANGES, pack_array, read_pack
from forge_character_forge.v3 import GENERATOR, TEMPLATE_VERTICES, controls, garments, metrics, mh, model, rig

ROOT = Path(__file__).resolve().parent.parent
PACK_V3 = ROOT / "examples" / "character_forge_aaa" / "studio" / "studio_pack_v3.bin"
PACK_V2 = ROOT / "examples" / "character_forge_aaa" / "studio" / "studio_pack.bin"
ASSETS = ROOT / "forge_character_forge" / "v3" / "assets"


class AssetTests(unittest.TestCase):
    def test_provenance_matches_files_and_targets_are_cc0(self):
        prov = json.loads((ASSETS / "PROVENANCE.json").read_text())
        files = {p["file"]: p for p in prov["files"]}
        for rel, p in files.items():
            data = (ASSETS / rel).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), p["sha256"], rel)
            self.assertTrue(p["source_url"].startswith("https://raw.githubusercontent.com/makehumancommunity/makehuman/"))
            if rel.startswith("targets/"):
                self.assertIn(b"CC0", data[:600], rel)
        on_disk = {str(f.relative_to(ASSETS)) for f in ASSETS.rglob("*") if f.is_file()}
        self.assertEqual(on_disk - set(files), {"PROVENANCE.json", "makehuman_LICENSE.md", "makehuman_LICENSE.ASSETS.md"})


class RigTests(unittest.TestCase):
    def test_every_makehuman_bone_maps_to_one_joint(self):
        bones, _ = mh.skeleton()
        self.assertEqual(len(bones), 163)
        bm = rig.bone_map()
        self.assertEqual(set(bm), set(bones))
        self.assertTrue(set(bm.values()) <= set(rig.NAMES))
        for b in bones:  # explicit (pattern) rules never overlap; the ancestry fallbacks apply only when none matches
            explicit = [p for p, _ in rig.RULES if not p.startswith("@") and re.fullmatch(p, b)]
            self.assertLessEqual(len(explicit), 1, b)

    def test_joint_budget_and_hierarchy(self):
        self.assertEqual(len(rig.NAMES), 62)
        self.assertLessEqual(len(rig.NAMES), 64)  # export contract; the renderer allows 80
        self.assertEqual(len(set(rig.NAMES)), len(rig.NAMES))
        for k, p in enumerate(rig.PARENTS):
            self.assertLess(p, k)  # parents precede children (FK order)
        self.assertFalse([n for n in rig.NAMES if n.startswith("cloth_")])

    def test_skin_weights_are_complete_and_normalised(self):
        v = model.neutral()
        j, w, rep = rig.skin(len(v))
        body = model.body_vertex_ids()
        self.assertEqual(rep["unweighted_vertices"], 0)
        np.testing.assert_allclose(w[body].sum(1), 1, atol=1e-9)
        self.assertTrue((j < len(rig.NAMES)).all())
        self.assertLess(rep["mean_dropped_weight"], 0.005)

    def test_joints_are_anatomically_placed(self):
        J = {n: p for n, p in zip(rig.NAMES, rig.joint_rest(model.neutral()))}
        self.assertTrue(J["foot_l"][1] < J["calf_l"][1] < J["thigh_l"][1] < J["pelvis"][1] < J["spine_03"][1] < J["head"][1])
        self.assertGreater(J["upperarm_l"][0], 0.1)  # _l is +X, as in v1/v2
        self.assertLess(J["upperarm_r"][0], -0.1)
        self.assertGreater(J["breast_l"][2], J["spine_03"][2])


class ControlTests(unittest.TestCase):
    def test_all_53_controls_are_mapped_and_labelled(self):
        studio = {f"body.{k}" for k in BODY_RANGES} | {f"face.{k}" for k in FACE_RANGES}
        self.assertEqual(set(controls.CONTROLS), studio)
        self.assertEqual(len(studio), 53)
        self.assertEqual(controls.summary()["by_quality"], {"direct": 36, "approximate": 16, "derived": 1})
        for key, (quality, _, _, note) in controls.CONTROLS.items():
            if quality != "direct":
                self.assertTrue(note, key)  # every approximation says what it does instead
        for rel in controls.required_targets():
            self.assertTrue((ASSETS / "targets" / rel).is_file(), rel)

    def test_neutral_is_the_default_height_with_soles_on_the_floor(self):
        b = model.neutral()[model.body_vertex_ids()]
        self.assertAlmostEqual(b[:, 1].min(), 0, places=9)
        self.assertAlmostEqual(np.ptp(b[:, 1]), model.HEIGHT_M, places=9)
        self.assertEqual(len(model.body_vertex_ids()), TEMPLATE_VERTICES)

    def test_control_deltas_keep_feet_on_the_floor(self):
        v = model.neutral()
        for key in ("body.leg_length", "body.femininity", "body.foot_size"):
            for side in ("hi", "lo"):
                d, _ = model.control_delta(key, side)
                self.assertAlmostEqual((v + d)[model.body_vertex_ids(), 1].min(), 0, places=9)


class BlinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = model.neutral()
        cls.d = model.blink_delta(cls.v, "l") + model.blink_delta(cls.v, "r")
        cls.lbs = model.blink_delta(cls.v, "l", corrected=False) + model.blink_delta(cls.v, "r", corrected=False)
        cls.region = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
        cls.open_px = metrics.eye_exposure_pixels(cls.v)

    def test_blink_closes(self):
        self.assertGreater(self.open_px, 500)
        self.assertLess(metrics.eye_exposure_pixels(self.v + self.d) / self.open_px, 0.02)
        half = metrics.eye_exposure_pixels(self.v + 0.5 * self.d) / self.open_px
        self.assertTrue(0.3 < half < 0.8, half)

    def test_corrective_reduces_lid_folding(self):
        q = metrics.tri_quality(self.v, self.v + self.d, self.region)
        q_lbs = metrics.tri_quality(self.v, self.v + self.lbs, self.region)
        self.assertLessEqual(q["flipped"], 4)
        self.assertLess(q["flipped"], q_lbs["flipped"])

    def test_blink_touches_only_the_lids(self):
        body = model.body_vertex_ids()  # helper vertices (not rendered) follow the lid bones too
        moved = body[np.linalg.norm(self.d[body], axis=1) > 1e-7]
        grown = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
        self.assertTrue(set(moved) <= set(grown))


class GarmentTests(unittest.TestCase):
    def test_garments_cover_chest_and_pelvis(self):
        v = model.neutral()
        J = {n: p for n, p in zip(rig.NAMES, rig.joint_rest(v))}
        covered = {}
        for name, (ci, cw, faces, _) in garments.shells().items():
            covered[name] = set(ci[cw > 0.5].ravel())
            self.assertTrue(len(faces))
        joints, _, _ = rig.skin(len(v))
        body = model.body_vertex_ids()
        breast = body[np.isin(joints[body, 0], [rig.NAMES.index("breast_l"), rig.NAMES.index("breast_r")])]
        self.assertTrue(set(breast) <= covered["basic_top"])
        crotch = body[(np.abs(v[body, 1] - J["thigh_l"][1]) < 0.05) & (np.abs(v[body, 0]) < 0.06)]
        self.assertTrue(len(crotch) and set(crotch) <= covered["basic_shorts"])


class PackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man, cls.blob = read_pack(PACK_V3)

    def test_generator_stamp_and_v2_untouched(self):
        self.assertEqual(self.man["generator"], GENERATOR)
        self.assertEqual(self.man["generator"]["version"], 3)
        man2, _ = read_pack(PACK_V2)
        self.assertEqual(man2["generator"]["version"], 2)
        from forge_character_forge.character import GENERATOR_VERSION
        self.assertEqual(GENERATOR_VERSION, 2)

    def test_every_control_moves_geometry(self):
        self.assertEqual(len(self.man["params"]), 53)
        for key, pe in self.man["params"].items():
            self.assertIn(pe["quality"], ("direct", "approximate", "derived"))
            self.assertTrue(pe["sides"], key)
            for side, se in pe["sides"].items():
                self.assertIn("body", se["parts"], f"{key}:{side}")
        self.assertEqual(self.man["params"]["body.height_m"]["mode"], "uniform_scale")

    def test_parts_skeleton_and_clips(self):
        P = self.man["parts"]
        self.assertEqual(set(P), {"body", "eye_l", "eye_r", "cornea_l", "cornea_r", "basic_top", "basic_shorts"})
        src, uv, tris, weld = model.body_surface()
        self.assertEqual(P["body"]["n"], len(src))
        np.testing.assert_array_equal(pack_array(P["body"]["weld"], self.blob), weld)
        np.testing.assert_allclose(pack_array(P["body"]["uv"], self.blob), uv, atol=1e-6)
        self.assertEqual(len(np.unique(src)), TEMPLATE_VERTICES)
        for name, p in P.items():
            j = pack_array(p["joints"], self.blob)
            w = pack_array(p["weights"], self.blob).astype(int)
            self.assertTrue((j < len(rig.NAMES)).all(), name)
            self.assertTrue((w.sum(1) == 255).all(), name)
        self.assertEqual(self.man["skeleton"]["names"], rig.NAMES)
        for c in self.man["clips"].values():
            self.assertTrue(set(c["rot"]) <= set(rig.NAMES))
        self.assertEqual([e["name"] for e in self.man["expressions"]], ["blink_l", "blink_r"])

    def test_blink_correctives_close_every_reshaping_control_end(self):
        fits = self.man["blink_fits"]
        self.assertIn("face.eye_size:hi", fits)
        for where, f in fits.items():
            self.assertLessEqual(f["exposure"], 0.005, where)
        se = self.man["params"]["face.eye_size"]["sides"]["hi"]
        self.assertEqual(set(se["expr"]), {"blink_l", "blink_r"})

    def test_bake_is_reproducible(self):
        from forge_character_forge.v3.bake import bake
        with tempfile.TemporaryDirectory() as d:
            man = bake(Path(d) / "p.bin", log=lambda *_: None)
            a, ba = read_pack(Path(d) / "p.bin")
        b, bb = read_pack(PACK_V3)
        a.pop("bake_seconds")
        b.pop("bake_seconds")
        self.assertEqual(a, b)
        self.assertEqual(ba, bb)
        self.assertEqual(len(man["params"]), 53)


if __name__ == "__main__":
    unittest.main()
