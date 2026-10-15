"""Character Forge experiment: parameters, skeleton, template topology, skinning, body generation, morphs."""

import math
import unittest

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.body import build_body
from forge_character_forge.character import CharacterSpec, build_character
from forge_character_forge.expressions import EXPRESSIONS
from forge_character_forge.params import BodyParams, FaceParams, GenitalParams, ParameterError, preset
from forge_character_forge.rig import forward_kinematics, lbs, quat_from_euler, skinning_matrices
from forge_character_forge.skeleton import HUMANOID_MAP, build_skeleton
from forge_character_forge.template import get_template


class ParamsTests(unittest.TestCase):
    def test_ranges_and_types(self):
        BodyParams(height_m=2.4, breast_size=3.0, belly=1.0)
        for bad in ({"height_m": 3.5}, {"height_m": float("nan")}, {"breast_size": -0.1}, {"waist_width": True}):
            with self.assertRaises(ParameterError):
                BodyParams(**bad)
        with self.assertRaises(ParameterError):
            FaceParams.from_dict({"face_width": 1.0, "not_a_field": 1.0})
        with self.assertRaises(ParameterError):
            GenitalParams(penis_length=9.0)

    def test_presets_round_trip(self):
        for name in ("male", "female", "neutral"):
            b, f, g = preset(name)
            self.assertEqual(BodyParams.from_dict(b.to_dict()), b)
            self.assertEqual(FaceParams.from_dict(f.to_dict()), f)
        with self.assertRaises(ParameterError):
            preset("child")

    def test_adult_only(self):
        with self.assertRaises(ParameterError):
            CharacterSpec(age_years=17)


class SkeletonTests(unittest.TestCase):
    def test_hierarchy(self):
        sk = build_skeleton(*preset("female"))
        self.assertEqual(len(sk.names), len(set(sk.names)))
        for j, p in enumerate(sk.parents):
            self.assertLess(p, j, "parents precede children (acyclic, topological order)")
        self.assertEqual(sk.parents[0], -1)
        for name in HUMANOID_MAP:
            self.assertIn(name, sk.names)

    def test_proportions_follow_parameters(self):
        b, f, _ = preset("neutral")
        tall = build_skeleton(b.with_(height_m=2.0), f)
        short = build_skeleton(b.with_(height_m=1.5), f)
        self.assertAlmostEqual(tall.marks["y_crown"], 2.0, places=6)
        self.assertAlmostEqual(short.marks["y_crown"], 1.5, places=6)
        legs = build_skeleton(b.with_(leg_length=1.2), f)
        base = build_skeleton(b, f)
        self.assertGreater(legs["thigh_l"][1], base["thigh_l"][1])


class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tpl = get_template()

    def test_closed_oriented_manifold(self):
        chk = mesher.check_closed_manifold(self.tpl.tris)
        self.assertTrue(chk["closed_oriented"], chk)
        self.assertGreater(len(self.tpl.verts), 40000)
        self.assertEqual(int(self.tpl.tris.max()) + 1, len(self.tpl.verts))

    def test_skin_weights(self):
        w = self.tpl.weights
        self.assertEqual(w.shape[1], 4)
        self.assertTrue(np.all(w >= 0))
        self.assertLess(np.abs(w.sum(1) - 1).max(), 1e-6)
        self.assertTrue(np.all(np.isfinite(w)))
        names = self.tpl.skeleton.names
        dom = np.array(names)[self.tpl.joints[:, 0]]
        head = self.tpl.verts[:, 1] > self.tpl.skeleton.marks["y_chin"] + 0.05
        self.assertGreater(np.isin(dom[head], ["head", "jaw"]).mean(), 0.95)
        left_hand_tip = self.tpl.skeleton.marks.get("tip_middle_l")
        if left_hand_tip is not None:
            near = np.linalg.norm(self.tpl.verts - left_hand_tip, axis=1) < 0.01
            self.assertTrue(all(n.startswith("middle_") for n in dom[near]))


class BodyGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b, f, _ = preset("female")
        cls.female = build_body(b, f)
        bm, fm, _ = preset("male")
        cls.male = build_body(bm, fm)

    def test_fixed_topology_real_geometry_change(self):
        self.assertTrue(np.array_equal(self.female.tris, self.male.tris))
        self.assertEqual(self.female.verts.shape, self.male.verts.shape)
        d = np.linalg.norm(self.female.verts - self.male.verts, axis=1)
        self.assertGreater(d.mean(), 0.01)
        self.assertAlmostEqual(np.ptp(self.female.verts[:, 1]), 1.66, delta=0.02)
        self.assertAlmostEqual(np.ptp(self.male.verts[:, 1]), 1.78, delta=0.02)

    def test_surface_quality(self):
        for bm in (self.female, self.male):
            self.assertLess(bm.quality["surface_residual_p99_mm"], 0.5)
            self.assertLess(bm.quality["flipped_triangles_vs_template"], 0.002 * len(bm.tris))
            self.assertEqual(bm.quality["degenerate_triangles"], 0)

    def test_face_edits_keep_surface_clean(self):
        b, f, _ = preset("female")
        edited = build_body(b.with_(head_size=1.15, height_m=1.8),
                            f.with_(jaw_width=1.15, nose_length=1.2, nose_width=1.15, chin_projection=1.2, eye_size=0.9))
        self.assertLess(edited.quality["flipped_triangles_vs_template"], 0.001 * len(edited.tris))

    def test_deterministic(self):
        b, f, _ = preset("female")
        again = build_body(b, f)
        self.assertTrue(np.array_equal(again.verts, self.female.verts))

    def test_lbs_rest_is_identity_and_pose_deforms(self):
        sk = self.female.skeleton
        S = skinning_matrices(sk, forward_kinematics(sk))
        rest = lbs(self.female.verts, self.female.joints, self.female.weights, S)
        self.assertLess(np.abs(rest - self.female.verts).max(), 1e-9)
        S2 = skinning_matrices(sk, forward_kinematics(sk, {"thigh_l": quat_from_euler(-0.8, 0, 0)}))
        posed = lbs(self.female.verts, self.female.joints, self.female.weights, S2)
        moved = np.linalg.norm(posed - self.female.verts, axis=1)
        knee = sk["calf_l"]
        near_knee = np.linalg.norm(self.female.verts - knee, axis=1) < 0.06
        head = self.female.verts[:, 1] > sk.marks["y_chin"]
        self.assertGreater(moved[near_knee].min(), 0.1, "the left knee must follow the left thigh bone")
        self.assertLess(moved[head].max(), 1e-9, "the head must not move when only the thigh rotates")


class CharacterAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b, f, g = preset("female")
        cls.ch = build_character(CharacterSpec(b, f, g, outfit=("tshirt", "shorts")), "public")

    def test_parts_present(self):
        names = {p.name for p in self.ch.parts}
        for n in ("body", "eye_l", "eye_r", "teeth_upper", "teeth_lower", "eyebrows", "eyelashes", "hair_cap",
                  "tshirt", "shorts"):
            self.assertIn(n, names)
        self.assertFalse(any(p.dev_only for p in self.ch.parts))
        for p in self.ch.parts:
            self.assertEqual(p.joints.shape, (len(p.verts), 4))
            self.assertLess(np.abs(p.weights.sum(1) - 1).max(), 1e-6, p.name)
            self.assertLess(int(p.joints.max()), len(self.ch.skeleton.names))

    def test_expression_morphs_are_real_and_local(self):
        body = self.ch.body
        for name in ("blink_l", "blink_r", "smile", "brow_raise", "frown", "pucker", "lips_part"):
            d = np.linalg.norm(body.morphs[name], axis=1)
            self.assertGreater(d.max(), 5e-4, name)
        bl = np.linalg.norm(body.morphs["blink_l"], axis=1) > 1e-6
        self.assertTrue(np.all(body.verts[bl, 0] > 0), "blink_l moves only the character's left side (+X)")
        chin = self.ch.skeleton.marks["y_chin"]
        for name in EXPRESSIONS:
            if name in body.morphs:
                moved = np.linalg.norm(body.morphs[name], axis=1) > 1e-6
                self.assertTrue(np.all(body.verts[moved, 1] > chin - 0.02), name)

    def test_garments_are_outside_body(self):
        F = self.ch.body_field
        for g in ("tshirt", "shorts"):
            d = F.evaluate(self.ch.part(g).verts)
            self.assertGreater(np.percentile(d, 1), 0.0, f"{g} must sit outside the skin")


if __name__ == "__main__":
    unittest.main()
