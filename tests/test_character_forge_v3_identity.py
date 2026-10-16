"""Generator v3 identity layer (Phase 3A/3B): Forge-owned regional facial transforms."""

import unittest

import numpy as np

from forge_character_forge.v3 import identity, metrics, mh, model


def _aligned(v):
    ec = [model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"]
    rel = model.neutral() - identity.frame()
    m = (rel[:, 1] > -0.17) & (np.abs(rel[:, 0]) < 0.12)
    m &= np.isin(np.arange(len(v)), model.body_vertex_ids())
    return v[m] - (ec[0] + ec[1]) / 2


class IdentityLayerTests(unittest.TestCase):
    def test_parameters_are_linear_and_composable(self):
        a = identity.identity_delta({"nose_length": 0.5})
        np.testing.assert_allclose(identity.identity_delta({"nose_length": 1.0}), 2 * a, atol=1e-12)
        both = identity.identity_delta({"nose_length": 0.5, "jaw_width": -0.3})
        np.testing.assert_allclose(both, a + identity.identity_delta({"jaw_width": -0.3}), atol=1e-12)

    def test_zero_identity_is_the_neutral_and_unknown_keys_fail(self):
        np.testing.assert_array_equal(identity.identity_mesh({}), model.neutral())
        np.testing.assert_array_equal(identity.identity_mesh({k: 0.0 for k in identity.KEYS}), model.neutral())
        with self.assertRaises(KeyError):
            identity.identity_delta({"nose_lenght": 0.5})

    def test_parameters_are_local_to_the_head(self):
        rel = model.neutral() - identity.frame()
        far = rel[:, 1] < -0.3  # torso and below
        for k in identity.KEYS:
            self.assertLess(float(np.abs(identity.basis(k)[far]).max()), 1e-6, k)  # under a micrometre

    def test_two_identities_are_distinct_and_healthy(self):
        v0 = model.neutral()
        A, B = (identity.identity_mesh(identity.IDENTITIES[k]) for k in ("ID-A", "ID-B"))
        d = np.linalg.norm(_aligned(A) - _aligned(B), axis=1).mean()
        self.assertGreater(d, 0.009)  # MakeHuman's own female variants differ by 0-2.8 mm, female vs male by ~5.5 mm
        body = model.body_vertex_ids()
        for v in (A, B):
            q = metrics.tri_quality(v0, v, body)
            self.assertEqual(q["flipped"], 0)
            self.assertLess(q["max_area_ratio"], 4.0)

    def test_eyeballs_follow_their_lids_and_blink_still_closes(self):
        for k in ("ID-A", "ID-B"):
            v = identity.identity_mesh(identity.IDENTITIES[k])
            _, fit = model.fit_blink(v)
            self.assertLessEqual(fit["exposure"], 0.005, k)
            for s in "lr":  # eyeball centre still between the lid corners (no detached eyeball)
                c, _ = model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])
                lid = v[model.lid_region(s)]
                self.assertTrue((lid.min(0)[:2] < c[:2]).all() and (c[:2] < lid.max(0)[:2]).all(), k)

    def test_ears_keep_their_shape(self):
        v = identity.identity_mesh(identity.IDENTITIES["ID-B"])
        for side, m in identity.ear_mask().items():
            core = m > 0.999  # fully rigid part (the rim blends into the head)
            d = v[core] - model.neutral()[core]
            self.assertLess(float(np.ptp(d, axis=0).max()), 1e-6)  # rigid translation only


class EyeApertureTests(unittest.TestCase):
    """Phase 3C lid-only operators: the opening changes shape, the eyeball does not move."""

    def test_eyeball_stays_put_and_lids_keep_their_distance(self):
        v0 = model.neutral()
        for k in ("eye_aperture", "eye_outer_corner", "eye_length"):
            v = identity.identity_mesh({k: 1.0})
            for s in "lr":
                ids = model.eye_parts()[f"eye_{s}"][0]
                np.testing.assert_allclose(mh.fit_eyes(v)[ids], mh.fit_eyes(v0)[ids], atol=1e-9, err_msg=k)
            if k != "eye_length":  # rotations about the eyeball centre (linearised): radius preserved to < 0.2 mm
                for side, (c, wu, wl) in identity._lid_weights().items():
                    lid = np.nonzero((wu + wl) > 0.5)[0]
                    dr = np.linalg.norm(v[lid] - c, axis=1) - np.linalg.norm(v0[lid] - c, axis=1)
                    self.assertLess(float(np.abs(dr).max()), 0.0002, k)

    def test_aperture_narrows_the_opening(self):
        v0 = model.neutral()
        o = metrics.eye_exposure_pixels(v0)
        self.assertLess(metrics.eye_exposure_pixels(identity.identity_mesh({"eye_aperture": 1.0})), 0.9 * o)
        self.assertGreater(metrics.eye_exposure_pixels(identity.identity_mesh({"eye_aperture": -1.0})), 1.05 * o)

    def test_stylized_identity_is_healthy_and_blinks(self):
        v = identity.identity_mesh(identity.STYLIZED["MERCY-INSPIRED"])
        q = metrics.tri_quality(model.neutral(), v, model.body_vertex_ids())
        self.assertEqual(q["flipped"], 0)
        _, fit = model.fit_blink(v)
        self.assertLessEqual(fit["exposure"], 0.005)


if __name__ == "__main__":
    unittest.main()
