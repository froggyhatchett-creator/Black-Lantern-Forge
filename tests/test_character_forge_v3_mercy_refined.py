"""Mercy face refinement: the MERCY-REFINED preset sits beside MERCY-INSPIRED without changing it or its blink."""
import hashlib
import json
import unittest

import numpy as np

from forge_character_forge.params import preset
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, identity, identity_dna as I, model


def controls(name):
    b, f, _ = preset("female")
    c = {k: float(getattr(b if k.startswith("body.") else f, k.split(".")[1])) for k in E.control_defaults()}
    return {**c, **I.presets()[name]["controls"]}


def head_flips(v):
    v0 = model.neutral()
    src, _, tris, _ = model.body_surface()
    t = src[tris]
    t = t[v0[t].mean(1)[:, 1] > v0[:, 1].max() - 0.3]
    n0 = np.cross(v0[t[:, 1]] - v0[t[:, 0]], v0[t[:, 2]] - v0[t[:, 0]])
    n1 = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    return int(((n0 * n1).sum(1) < 0).sum())


class MercyRefinedTest(unittest.TestCase):
    def test_old_preset_unchanged_and_new_one_in_range(self):
        old = identity.STYLIZED["MERCY-INSPIRED"]
        self.assertEqual(hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()[:16], "8dd7d60f03fb9281")
        self.assertEqual(identity.STYLIZED_CONTROLS["MERCY-INSPIRED"], {"body.femininity": 1.0})
        new = identity.STYLIZED["MERCY-REFINED"]
        self.assertTrue(set(new) <= set(I.KEYS_V1))
        self.assertTrue(all(I.RANGE[0] <= x <= I.RANGE[1] for x in new.values()))
        self.assertIn("MERCY-REFINED", I.presets())

    def test_no_blink_residual_so_existing_blinks_do_not_move(self):
        self.assertNotIn("MERCY-REFINED", I.RESIDUAL_PRESETS)
        self.assertNotIn("MERCY-REFINED", E.preset_residuals())
        for name in I.RESIDUAL_PRESETS:
            aff = I.preset_affinity(I.presets()[name]["values"])
            self.assertNotIn("MERCY-REFINED", aff)
            self.assertAlmostEqual(aff[name], 1.0)

    def test_no_flipped_head_triangles_in_either_eyelid_fit(self):
        ctl, iv = controls("MERCY-REFINED"), identity.STYLIZED["MERCY-REFINED"]
        for fit in (1, 2):
            with E.fit(fit):
                self.assertEqual(head_flips(E.shape(ctl, iv)), 0, fit)

    def test_blink_closes_through_the_studio_path(self):
        ctl, iv = controls("MERCY-REFINED"), identity.STYLIZED["MERCY-REFINED"]
        v = E.shape(ctl, iv)
        s = Q.summary(Q.measure(v, E.blink(ctl, iv)))
        self.assertLessEqual(s["exposure_closed_max"], 0.003, s)
        self.assertLessEqual(s["lid_in_eye_max_mm"], 0.5, s)
        self.assertLessEqual(s["folds_total_closed"], 14, s)
        self.assertLessEqual(s["symmetry_exposure_diff_max"], 0.003, s)


if __name__ == "__main__":
    unittest.main()
