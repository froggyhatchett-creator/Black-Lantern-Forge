"""Phase 3D: identity as a versioned Character DNA group; identity combined with the body and face controls."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from forge.hashing import canonical_json
from forge_character_forge import dna as D
from forge_character_forge.v3 import evaluate, identity, identity_dna as I, metrics, model


class IdentityDNATest(unittest.TestCase):
    def test_keys_are_the_versioned_set(self):
        self.assertEqual(tuple(identity.KEYS), I.KEYS_V1)
        self.assertEqual(len(I.KEYS_V1), 36)
        self.assertEqual(identity.IDENTITY_VERSION, I.VERSION)

    def test_basis_matches_the_recorded_version(self):
        """Version 1 means exactly this geometry: any change to a parameter must become a new version."""
        rec = I.recorded()
        self.assertEqual(rec["keys"], list(I.KEYS_V1))
        for k in I.KEYS_V1:
            np.testing.assert_allclose(I.basis_moments(k), rec["moments"][k], rtol=1e-6, atol=1e-9, err_msg=k)

    def test_dna_without_identity_is_neutral_and_keeps_its_hash(self):
        dna = D.new_dna("female", name="legacy")
        D.validate_dna(dna)
        self.assertTrue(all(v == 0 for v in I.values_from_dna(dna).values()))
        old = hashlib.sha256(canonical_json({"identity": dna["identity"],
                                             "values": {k: t["value"] for k, t in dna["traits"].items()}})).hexdigest()
        self.assertEqual(D.dna_hash(dna), old)

    def test_save_and_load_are_deterministic_and_exact(self):
        for name, pr in I.presets().items():
            dna = I.set_identity(D.new_dna("neutral", name=name.lower()), {**pr["values"], "nose_width": 0.123456}, preset=name,
                                 locked=["eye_size"])
            with tempfile.TemporaryDirectory() as td:
                a, b = Path(td) / "a.dna.json", Path(td) / "b.dna.json"
                D.save_dna(dna, a)
                back = D.load_dna(a)
                D.save_dna(back, b)
                self.assertEqual(a.read_bytes(), b.read_bytes())
            vals = I.values_from_dna(back)
            for k in I.KEYS_V1:
                self.assertAlmostEqual(vals[k], round({**pr["values"], "nose_width": 0.123456}.get(k, 0.0), 4), places=9)
            self.assertEqual(back["face_identity"]["preset"], name)
            self.assertEqual(back["face_identity"]["locked"], ["eye_size"])
            self.assertNotEqual(D.dna_hash(back), D.dna_hash(D.new_dna("neutral", name=name.lower())))

    def test_invalid_groups_are_rejected_not_reinterpreted(self):
        good = I.make_group({"nose_width": 0.5})
        bad = [{**good, "version": 2}, {**good, "schema": "x"}, {**good, "values": {"nose_wide": 0.5}},
               {**good, "values": {"nose_width": 1.5}}, {**good, "values": {"nose_width": "0.5"}},
               {**good, "values": {"nose_width": True}}, {**good, "locked": ["nope"]}]
        for g in bad:
            dna = D.new_dna("neutral")
            dna["face_identity"] = g
            with self.assertRaises(ValueError, msg=json.dumps(g)[:120]):
                D.validate_dna(dna)

    def test_preset_affinity(self):
        for name, pr in I.presets().items():
            if pr["values"]:
                self.assertAlmostEqual(I.preset_affinity(pr["values"])[name], 1.0)
        self.assertTrue(all(a == 0 for a in I.preset_affinity({}).values()))


class ExactBuildRefusesV3Test(unittest.TestCase):
    def test_server_refuses_v3_and_identity_dna(self):
        """The Python exact build is the v2 engine: a v3 character must not silently come back as v2 geometry."""
        import threading
        import urllib.error
        import urllib.request
        from forge_character_forge.studio_server import DEFAULT_PACK, serve
        with tempfile.TemporaryDirectory() as td:
            httpd = serve(0, DEFAULT_PACK, Path(td))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                v3 = D.new_dna("female", name="v3")
                v3["identity"]["generator"] = {"id": "forge.character-forge", "version": 3}
                for dna in (v3, I.set_identity(D.new_dna("female", name="idn"), {"nose_width": 0.5}, "custom")):
                    req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/export", data=json.dumps(dna).encode(),
                                                 headers={"Content-Type": "application/json"}, method="POST")
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(req, timeout=30)
                    self.assertEqual(cm.exception.code, 400)
                    self.assertIn("generator v2 only", json.loads(cm.exception.read())["error"])
            finally:
                httpd.shutdown()


HEAD = None


def _head_ids():
    global HEAD
    if HEAD is None:
        rel = model.neutral() - identity.frame()
        HEAD = np.intersect1d(np.nonzero((rel[:, 1] > -0.17) & (np.abs(rel[:, 0]) < 0.12) & (rel[:, 2] > -0.2))[0],
                              model.body_vertex_ids())
    return HEAD


COMBOS = {  # identity preset + body/face controls, including slider ends acting together
    "ID-A + male build, big head, wide jaw": ("ID-A", {"body.femininity": 0.0, "body.head_size": 1.15, "face.jaw_width": 1.3}),
    "ID-B + feminine, large eyes, wide nose": ("ID-B", {"body.femininity": 1.0, "face.eye_size": 1.25, "face.nose_width": 1.3}),
    "Mercy-inspired + femininity, small head, long face": ("MERCY-INSPIRED", {"body.femininity": 1.0, "body.head_size": 0.9,
                                                                                "face.face_length": 1.2}),
}


class IdentityWithControlsTest(unittest.TestCase):
    def test_identity_adds_exactly_to_the_controls(self):
        vals = I.presets()["ID-B"]["values"]
        ctl = {"body.femininity": 0.8, "face.jaw_width": 1.2}
        with evaluate.fit(1):  # eyelid fit 1: the frozen basis v1 as is
            np.testing.assert_allclose(evaluate.shape(ctl, vals), evaluate.shape(ctl, {}) + identity.identity_delta(vals), atol=1e-12)
        with evaluate.fit(2):  # fit 2: each basis vector carries its own (linear) eyelid correction
            fitted = sum(s * evaluate.identity_term(k) for k, s in vals.items() if s)
            np.testing.assert_allclose(evaluate.shape(ctl, vals), evaluate.shape(ctl, {}) + fitted, atol=1e-12)

    def test_combined_shapes_are_healthy(self):
        for label, (preset, ctl) in COMBOS.items():
            vals = I.presets()[preset]["values"]
            v0, v = evaluate.shape(ctl, {}), evaluate.shape(ctl, vals)
            q = metrics.tri_quality(v0, v, _head_ids())
            self.assertEqual(q["flipped"], 0, label)
            self.assertLess(q["max_area_ratio"], 6.0, label)

    def test_each_identity_blinks_at_every_weight(self):
        """Studio blink (summed correctives + preset residual): closes, and opens monotonically, with the controls."""
        region = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
        cases = [(p, {}) for p in ("ID-A", "ID-B", "MERCY-INSPIRED")] + list(COMBOS.values())
        for preset, ctl in cases:
            vals = I.presets()[preset]["values"]
            v = evaluate.shape(ctl, vals)
            d = evaluate.blink(ctl, vals)
            o = metrics.eye_exposure_pixels(v)
            ex = [metrics.eye_exposure_pixels(v + w * d) / o for w in (0.25, 0.5, 0.75, 1.0)]
            self.assertLess(ex[-1], 0.02, (preset, ctl, ex))
            self.assertTrue(all(a > b for a, b in zip(ex[:3], ex[1:3])), (preset, ctl, ex))
            self.assertTrue(0.25 < ex[1] < 0.75, (preset, ctl, ex))
            self.assertLess(metrics.tri_quality(v, v + 0.5 * d, region)["flipped"], 30, (preset, ctl))


if __name__ == "__main__":
    unittest.main()
