"""Phase 4A.1: eyelid fit 2 (shape changes keep the lid skin on the eyeball), its DNA versioning, corner folds and
closed lash orientation."""
import copy
import json
import unittest
from pathlib import Path

import numpy as np

from forge_character_forge import dna as D
from forge_character_forge.params import preset
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, eyelid_fit as F, identity, identity_dna as I, model

ROOT = Path(__file__).resolve().parent.parent
LEGACY_DNA = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.dna.json"


def body_preset(name):
    b, f, _ = preset(name)
    return {k: float(getattr(b if k.startswith("body.") else f, k.split(".")[1])) for k in E.control_defaults()}


class CorrectionTest(unittest.TestCase):
    def test_the_eye_size_control_moves_the_lids_but_not_the_eyeball(self):
        """The defect's root cause, kept as a regression fact about the CC0 targets."""
        d, _ = model.control_delta("face.eye_size", "lo")
        ids = model.eye_parts()["eye_l"][0]
        v = model.neutral()
        _, r0 = model.sphere_fit(F.mh.fit_eyes(v)[ids])
        _, r1 = model.sphere_fit(F.mh.fit_eyes(v + d)[ids])
        self.assertAlmostEqual(r0, r1, places=9)
        self.assertGreater(np.abs(d[model.lid_region("l")]).max(), 0.002)

    def test_correction_is_linear_and_local(self):
        for key in ("eye_size", "brow_ridge", "cheekbone_height"):
            B = identity.basis(key)
            K = F.correction(B)
            np.testing.assert_allclose(F.correction(-B), -K, atol=1e-9)
            np.testing.assert_allclose(F.correction(0.5 * B), 0.5 * K, atol=1e-9)
            near = np.zeros(len(B), bool)
            for vid, *_ in F.geometry().values():
                near[vid] = True
            self.assertEqual(float(np.abs(K[~near]).max()), 0.0, key)
        self.assertEqual(float(np.abs(F.correction(np.zeros_like(model.neutral()))).max()), 0.0)

    def test_correction_keeps_the_lid_on_the_eyeball(self):
        """Fit 2 removes the first-order change of the skin-to-eyeball gap for the fully corrected lid skin."""
        d, _ = model.control_delta("face.eye_size", "lo")
        K = F.correction(d)
        for vid, u, f, c, R, ids in F.geometry().values():
            full = f > 0.999
            dg = (u[full] * (d + K)[vid[full]]).sum(1)  # the eyeball does not move under this control
            self.assertLess(float(np.abs(dg).max()), 1e-5)  # 10 um (least-squares eye fit residue) vs mm-scale motion


class ReproductionTest(unittest.TestCase):
    def test_fit_1_is_the_phase_4a_geometry(self):
        P = I.presets()
        for idn in P:
            ctl = {**body_preset("female"), "face.eye_size": 0.8}
            with E.fit(1):
                v = E.shape(ctl, P[idn]["values"])
            ref = model.neutral().copy()
            for k, side, w in E.control_weights(ctl):
                ref += w * model.control_delta(k, side)[0]
            ref += identity.identity_delta(P[idn]["values"])
            np.testing.assert_allclose(v, ref, atol=1e-12, err_msg=idn)

    def test_neutral_is_unchanged(self):
        with E.fit(2):
            np.testing.assert_array_equal(E.shape({}, {}), model.neutral())


class LargeAndSmallEyesTest(unittest.TestCase):
    """The worst open-pose cases (eye size at the slider minimum 0.8): skin no deeper in the eye than the neutral's
    own margins (10-13 vertices per eye, up to 1.15 mm, where the margin rests on the cornea)."""

    def test_worst_cases_at_eye_size_0_8(self):
        P = I.presets()
        base = Q.open_skin_in_eye(model.neutral())
        for idn in ("ID-A", "MERCY-INSPIRED"):
            ctl = {**body_preset("female"), "face.eye_size": 0.8}
            with E.fit(1):
                before = Q.open_skin_in_eye(E.shape(ctl, P[idn]["values"]))
            with E.fit(2):
                after = Q.open_skin_in_eye(E.shape(ctl, P[idn]["values"]))
            for s in "lr":
                self.assertGreater(before[s]["vertices"], 2 * base[s]["vertices"], (idn, before))
                self.assertLessEqual(after[s]["vertices"], base[s]["vertices"] + 12, (idn, after, base))
                self.assertLessEqual(after[s]["max_mm"], 1.4, (idn, after))


class DnaTest(unittest.TestCase):
    def setUp(self):
        self.dna = json.loads(LEGACY_DNA.read_text())  # a Phase 4A studio DNA (no face_deformation group)
        self.dna["traits"]["wardrobe.outfit"]["value"] = []  # the Python validator knows the v2 garments only

    def test_legacy_dna_is_fit_1_and_keeps_its_hash(self):
        self.assertNotIn(F.GROUP, self.dna)
        self.assertEqual(F.dna_fit(self.dna), 1)
        h = D.dna_hash(self.dna)
        D.validate_dna(self.dna)
        self.assertEqual(D.dna_hash(copy.deepcopy(self.dna)), h)

    def test_fit_group_validates_and_changes_the_hash(self):
        d2 = {**copy.deepcopy(self.dna), F.GROUP: F.dna_group(2)}
        D.validate_dna(d2)
        self.assertEqual(F.dna_fit(d2), 2)
        self.assertNotEqual(D.dna_hash(d2), D.dna_hash(self.dna))
        self.assertNotEqual(D.anatomy_hash(d2), D.anatomy_hash(self.dna))

    def test_unknown_fit_is_refused(self):
        for bad in ({**F.dna_group(2), "eyelid_fit": 3}, {**F.dna_group(2), "version": 2}, {"schema": "x", "version": 1, "eyelid_fit": 2}, "2"):
            with self.assertRaises(ValueError):
                D.validate_dna({**copy.deepcopy(self.dna), F.GROUP: bad})


class CornersAndLashesTest(unittest.TestCase):
    def test_corner_limits_reduce_folds_and_still_close(self):
        """Exact refit of ID-A (female, eye size 0.8): the corner limits never cost closure."""
        P = I.presets()
        with E.fit(2):
            v = E.shape({**body_preset("female"), "face.eye_size": 0.8}, P["ID-A"]["values"])
        saved = model.NO_OVERTAKE, model.ANGLE_UNTANGLE
        try:
            model.NO_OVERTAKE, model.ANGLE_UNTANGLE = None, 0
            old = model.blink_closed(v, "l")
        finally:
            model.NO_OVERTAKE, model.ANGLE_UNTANGLE = saved
        new = model.blink_closed(v, "l")

        def visible_folds(d):
            c, R = Q._eye(v, "l")
            t = Q._region_tris("l")
            p = v + d
            n0 = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
            n1 = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
            cen = v[t].mean(1)
            vis = (np.linalg.norm(cen - c, axis=1) - R > 0.0004) & ((cen - c)[:, 2] > 0)
            return int((((n0 * n1).sum(1) < 0) & vis).sum())
        self.assertLess(visible_folds(new), visible_folds(old))
        o = Q.exposure_per_eye(v)["l"]
        self.assertLessEqual(Q.exposure_per_eye(v + new)["l"] / o, 0.003)

    def test_smoothed_lash_turn_reduces_scatter_without_penetration(self):
        """Mercy-inspired (female body): closed-lash scatter falls by more than a fifth and never rises (across the
        18-case matrix it falls 5-62 %). It is not free: here 2 more strands dip more than 0.15 mm behind the skin
        than with per-triangle turning (0 -> 2), within the Phase 4A worst case (4) the matrix also holds to."""
        from forge_character_forge.v3 import lash_contact as LC
        P = I.presets()
        with E.fit(2):
            v = E.shape(body_preset("female"), P["MERCY-INSPIRED"]["values"])
            d = E.blink(body_preset("female"), P["MERCY-INSPIRED"]["values"])
        m = Q.measure(v, d, weights=(0.0, 0.25, 0.5, 0.75, 1.0))
        saved = LC.TURN_SIGMA
        try:
            LC.TURN_SIGMA = 0  # Phase 4A: each lash turns with its own root triangle's normals
            LC.turn_neighbours.cache_clear()
            m0 = Q.measure(v, d, weights=(0.0, 0.25, 0.5, 0.75, 1.0))
        finally:
            LC.TURN_SIGMA = saved
            LC.turn_neighbours.cache_clear()
        for s in "lr":
            new, old = m["lash_orientation_closed"][s], m0["lash_orientation_closed"][s]
            self.assertLessEqual(new["scatter_p95_deg"], old["scatter_p95_deg"], (s, new, old))
        self.assertLess(max(m["lash_orientation_closed"][s]["scatter_p95_deg"] for s in "lr"),
                        0.8 * max(m0["lash_orientation_closed"][s]["scatter_p95_deg"] for s in "lr"))
        self.assertLessEqual(Q.summary(m)["lash_penetrating_max"], 4)


if __name__ == "__main__":
    unittest.main()
