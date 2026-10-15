"""Character Forge experiment: Character DNA (provenance, locks, regeneration) and secondary physics."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from forge_character_forge import dna as D
from forge_character_forge import physics as P
from forge_character_forge.anatomy import build_field
from forge_character_forge.animation import clip
from forge_character_forge.params import preset
from forge_character_forge.skeleton import build_skeleton


class DnaTests(unittest.TestCase):
    def test_round_trip_and_spec(self):
        d = D.new_dna("female", name="x")
        with tempfile.TemporaryDirectory() as t:
            p = D.save_dna(d, Path(t) / "x.json")
            d2 = D.load_dna(p)
        self.assertEqual(D.dna_hash(d), D.dna_hash(d2))
        spec = D.to_spec(d2)
        self.assertEqual(spec.body, preset("female")[0])

    def test_set_validates_and_marks_user(self):
        d = D.set_trait(D.new_dna(), "body.height_m", 1.9)
        self.assertEqual(d["traits"]["body.height_m"]["provenance"], "user")
        with self.assertRaises(Exception):
            D.set_trait(d, "body.height_m", 9.0)
        with self.assertRaises(KeyError):
            D.set_trait(d, "body.wings", 1.0)

    def test_locks_survive_regeneration_and_estimates(self):
        d = D.new_dna("male")
        d = D.set_trait(d, "face.jaw_width", 1.3, lock=True)
        d = D.lock(d, ["appearance.hair_color"])
        r = D.regenerate(d, "face", seed=5)
        self.assertEqual(r["traits"]["face.jaw_width"]["value"], 1.3)
        changed = r["history"][-1]["changed"]
        self.assertIn("face.nose_length", changed)
        self.assertNotIn("face.jaw_width", changed)
        self.assertEqual(r["traits"]["face.nose_length"]["provenance"], "invented")
        r2 = D.regenerate(d, "face", seed=5)
        self.assertEqual(D.dna_hash(r), D.dna_hash(r2), "regeneration is seeded and deterministic")
        e = D.apply_estimates(r, {"face.jaw_width": (0.8, "observed", 0.7, "x"),
                                  "appearance.hair_color": ("#ffffff", "observed", 0.7, "x"),
                                  "face.chin_width": (1.1, "observed", 0.6, "fit")}, ["src1"])
        self.assertEqual(e["traits"]["face.jaw_width"]["value"], 1.3)
        self.assertEqual(e["traits"]["appearance.hair_color"]["value"], d["traits"]["appearance.hair_color"]["value"])
        self.assertEqual(e["traits"]["face.chin_width"]["sources"], ["src1"])

    def test_malformed_dna(self):
        with self.assertRaises(ValueError):
            D.validate_dna({"schema": "nope"})
        d = D.new_dna()
        d["traits"]["body.height_m"]["provenance"] = "guessed"
        with self.assertRaises(ValueError):
            D.validate_dna(d)


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b, f, g = preset("female")
        cls.sk = build_skeleton(b, f, g)
        build_field(b, f, cls.sk)
        bm, fm, gm = preset("male")
        cls.skm = build_skeleton(bm, fm, gm)
        build_field(bm, fm, cls.skm)
        cls.jump = clip("jump")
        cls.walk = clip("walk")

    def _breast(self, params=None):
        return [c for c in P.default_chains(self.sk, params) if c.kind == "breast"]

    def test_motion_responds_to_movement(self):
        idle = P.simulate(self.sk, clip("idle"), self._breast())
        jump = P.simulate(self.sk, self.jump, self._breast())
        self.assertTrue(idle.stable and jump.stable)
        self.assertGreater(P.amplitude(jump, "breast_l"), 5 * P.amplitude(idle, "breast_l"))
        self.assertGreater(P.amplitude(jump, "breast_l"), 0.005)

    def test_damping_and_stiffness_are_tunable(self):
        soft = P.simulate(self.sk, self.jump, self._breast({"breast": P.SpringParams(1.6, 0.12, 60, 0.035)}))
        stiff = P.simulate(self.sk, self.jump, self._breast({"breast": P.SpringParams(4.0, 0.6, 60, 0.035)}))
        self.assertGreater(P.amplitude(soft, "breast_l"), 1.5 * P.amplitude(stiff, "breast_l"))

    def test_garment_support_reduces_motion(self):
        ch = self._breast()
        free = P.simulate(self.sk, self.jump, ch)
        bra = P.simulate(self.sk, self.jump, ch, containment=P.garment_containment(self.sk, ("bra",), ch))
        self.assertLess(P.amplitude(bra, "breast_l"), 0.7 * P.amplitude(free, "breast_l"))

    def test_limits_and_stability_extremes(self):
        for sp in (P.SpringParams(30.0, 0.0, 10, 0.03), P.SpringParams(0.2, 3.0, 120, 0.0)):
            r = P.simulate(self.sk, self.jump, self._breast({"breast": sp}))
            self.assertTrue(r.stable)
            # collision resolution has priority over the cone limit, so allow a small excess
            self.assertLessEqual(r.angles_deg["breast_l"].max(), sp.max_angle_deg + 1.0)
            self.assertTrue(all(np.all(np.isfinite(q)) for q in r.rotations.values()))
        with self.assertRaises(ValueError):
            P.SpringParams(frequency_hz=100.0)

    def test_collision_constraint(self):
        ch = [c for c in P.default_chains(self.skm) if c.kind in ("penis", "testicle")]
        on = P.simulate(self.skm, self.walk, ch, collide=True)
        off = P.simulate(self.skm, self.walk, ch, collide=False)
        self.assertLess(on.max_penetration, 0.001)
        self.assertGreater(on.raw_max_penetration, 0.0, "contacts actually occurred and were resolved")
        self.assertGreater(off.max_penetration, on.max_penetration, "without colliders the chain penetrates the thighs")

    def test_bake_adds_channels(self):
        r = P.simulate(self.sk, self.jump, self._breast())
        baked = P.bake(self.jump, r)
        self.assertIn("breast_l", baked.rotations)
        self.assertEqual(baked.rotations["breast_l"].shape, (len(self.jump.times), 4))

    def test_public_chains_exclude_dev_anatomy(self):
        names = {b for c in P.default_chains(self.skm, include_dev=False) for b in c.bones}
        self.assertFalse(any(n.startswith(("penis", "testicle")) for n in names))


if __name__ == "__main__":
    unittest.main()
