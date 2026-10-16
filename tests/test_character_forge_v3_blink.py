"""Phase 4A: blink model 2 (per-column lid closure, anchored fornix, chord clearance) and the studio's blink path."""
import json
import unittest

import numpy as np

from forge_character_forge.params import preset
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, identity, identity_dna as I, model


def body_preset(name):
    b, f, _ = preset(name)
    return {k: float(getattr(b if k.startswith("body.") else f, k.split(".")[1])) for k in E.control_defaults()}


class BlinkModel2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fem = body_preset("female")
        cls.P = I.presets()

    def check(self, m, folds_closed, folds_visible_any, in_eye_mm, label):
        s = Q.summary(m)
        self.assertLessEqual(s["exposure_closed_max"], 0.003, (label, s))
        self.assertLessEqual(s["folds_total_closed"], folds_closed, (label, s))
        self.assertLessEqual(s["folds_visible_max"], folds_visible_any, (label, s))
        self.assertLessEqual(s["lid_in_eye_max_mm"], in_eye_mm, (label, s))
        self.assertLessEqual(s["symmetry_exposure_diff_max"], 0.003, (label, s))
        for side in "lr":  # opens steadily: exposure falls with the weight
            ex = [m["weights"][w][side]["exposure"] for w in ("0.0", "0.25", "0.5", "0.75", "1.0")]
            self.assertTrue(all(a > b for a, b in zip(ex, ex[1:-1])), (label, side, ex))

    def test_neutral_exact(self):
        v = model.neutral()
        self.check(Q.measure(v, model.blink(v)[0]), folds_closed=4, folds_visible_any=2, in_eye_mm=0.2, label="neutral")

    def test_worst_case_id_a_on_the_female_body_through_the_studio_path(self):
        """Phase 3D: 75 folded lid triangles at full blink (37 + 38), lid edge ~1 mm inside the eye mid-blink."""
        iv = self.P["ID-A"]["values"]
        v = E.shape(self.fem, iv)
        self.check(Q.measure(v, E.blink(self.fem, iv)), folds_closed=24, folds_visible_any=6, in_eye_mm=1.0, label="ID-A female")

    def test_mercy_on_the_female_body_through_the_studio_path(self):
        iv = self.P["MERCY-INSPIRED"]["values"]
        v = E.shape(self.fem, iv)
        self.check(Q.measure(v, E.blink(self.fem, iv)), folds_closed=12, folds_visible_any=6, in_eye_mm=0.5, label="Mercy female")

    def test_blink_is_continuous_in_the_shape(self):
        """No grid choice: a small shape change gives a small blink change (bounded per unit of shape), where the
        Phase 1-3 grid fit jumped between closing factors (so its correctives summed badly)."""
        v = model.neutral()
        b = model.blink(v)[0]
        for key in ("eye_size", "eye_tilt", "eye_aperture", "cheekbone_height"):
            for eps in (0.05, 0.1, 0.2):
                change = np.abs(model.blink(v + eps * identity.basis(key))[0] - b).max()
                self.assertLess(change, 0.012 * eps, (key, eps, change))  # under 1.2 mm per unit of the parameter

    def test_blink_stays_on_the_lids(self):
        v = model.neutral()
        d = model.blink(v)[0]
        moved = np.nonzero(np.linalg.norm(d, axis=1) > 1e-7)[0]
        lids = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
        self.assertTrue(np.isin(moved, lids).all())


class LashTest(unittest.TestCase):
    def test_contact_bends_lashes_within_its_limits_and_only_helps(self):
        from forge_character_forge.v3 import lash_contact as LC
        v = model.neutral()
        d = model.blink(v)[0]
        src, *_ = model.body_surface()
        c0, c1 = Q.lash_points(v), Q.lash_points(v, d)
        off = LC.apply(c0, v[src], c1, (v + d)[src])
        self.assertEqual(np.abs(off[:, 0]).max(), 0.0)  # roots stay on their triangle
        push = np.linalg.norm(off, axis=2)
        reach = LC.BEND_RATIO * np.linalg.norm(c1 - c1[:, :1], axis=2)
        self.assertTrue((push <= np.minimum(LC.MAX_BEND + LC.MAX_BEND_OWN, reach * 2) + 1e-9).all())
        self.assertLessEqual(push.max(), LC.MAX_BEND + LC.MAX_BEND_OWN)
        for side in "lr":  # strands through the skin at full blink: fewer with contact, and at most 5 per eye
            m = LC.strand_sides(c0) == side
            sd0 = LC.signed_to_skin(c0[m, 2:].reshape(-1, 3), v[src], LC.eye_tris()[side])[0].reshape(m.sum(), -1)
            clear = ~(sd0 < -Q.LASH_TOL_M).any(1)  # as blink_quality counts: strands clear of the skin when open

            def strands(c):
                sd = LC.signed_to_skin(c[m, 2:].reshape(-1, 3), (v + d)[src], LC.eye_tris()[side])[0].reshape(m.sum(), -1)
                return int(((sd < -Q.LASH_TOL_M).any(1) & clear).sum())
            rigid, bent = strands(c1), strands(c1 + off)
            self.assertLessEqual(bent, rigid, side)
            self.assertLessEqual(bent, 5, side)

    def test_lashes_stay_out_of_the_lid_mid_blink(self):
        """The reported ID-A defect: lashes through the lid at intermediate weights."""
        fem = body_preset("female")
        iv = I.presets()["ID-A"]["values"]
        v = E.shape(fem, iv)
        m = Q.measure(v, E.blink(fem, iv), weights=(0.0, 0.25, 0.5))
        for w in ("0.25", "0.5"):
            for s in "lr":
                self.assertLessEqual(m["weights"][w][s]["lash_strands_penetrating"], 1, (w, s))


if __name__ == "__main__":
    unittest.main()


class PackTest(unittest.TestCase):
    def test_pack_carries_blink_model_2_and_lash_contact(self):
        from pathlib import Path
        from forge_character_forge.studio_bake import pack_array, read_pack
        from forge_character_forge.v3 import lash_contact as LC
        man, blob = read_pack(Path(__file__).resolve().parents[1] / "examples/character_forge_aaa/studio/studio_pack_v3.bin")
        self.assertEqual(man["blink_model"], 2)
        c = man["parts"]["lashes"]["contact"]
        for (side, up), t in LC.lid_tris().items():
            np.testing.assert_array_equal(pack_array(c[f"tris_{side}_{'up' if up else 'lo'}"], blob).reshape(-1, 3), t)
        self.assertEqual((c["clear"], c["max_depth"], tuple(c["path_ts"]), c["max_bend"], c["max_bend_own"], c["bend_ratio"]),
                         (LC.CLEAR, LC.MAX_DEPTH, LC.PATH_TS, LC.MAX_BEND, LC.MAX_BEND_OWN, LC.BEND_RATIO))
        # the pack's neutral blink is blink model 2 of the neutral (the encoder drops deltas under 0.05 mm)
        src, *_ = model.body_surface()
        b0, _ = E.blink0()
        for e in man["expressions"]:
            enc = e["body"]
            d = np.zeros((len(src), 3))
            d[pack_array(enc["idx"], blob)] = pack_array(enc["val"], blob).reshape(-1, 3) * enc["scale"]
            self.assertLess(np.abs(d - b0[e["name"][-1]][src]).max(), 5.1e-5)
