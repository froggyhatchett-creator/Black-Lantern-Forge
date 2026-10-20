"""Stolen Fire E2: optional foot locks for the v3 walk and run clips (forge_character_forge/v3/footlock.py).

The browser twin (studio/footlock.js) is checked against the same fixtures by tools/footlock_parity.mjs, and the
exported GLBs by tools/footlock_report.py (docs/STOLEN_FIRE_E2.md)."""
import json
import math
import unittest
from pathlib import Path

import numpy as np

from forge_character_forge.v3 import footlock as FL

FIX = Path(__file__).parent / "fixtures" / "footlock"


def _rand_q(rng, deg):
    a = rng.normal(size=3)
    return FL._turn(a / np.linalg.norm(a), math.radians(deg))


def _chain(rng):
    """A random hip > knee > ankle with a bent knee: parent and source world turns, positions."""
    pw = _rand_q(rng, 20)
    WU = FL.qmul(pw, _rand_q(rng, 25))
    WL = FL.qmul(WU, FL._turn(np.array([1.0, 0, 0]), math.radians(rng.uniform(15, 60))))
    WB = FL.qmul(WL, _rand_q(rng, 15))
    a = rng.normal(size=3) * 0.1
    b = a + FL.qrot(WU, np.array([0, -0.42, 0]))
    c = b + FL.qrot(WL, np.array([0, -0.43, 0]))
    return pw, WU, WL, WB, a, b, c


def _apply(pw, a, r):
    """FK of the solved local turns from the hip: knee, ankle positions and the foot's world turn."""
    U = FL.qmul(pw, r[0])
    L = FL.qmul(U, r[1])
    return U, L, FL.qmul(L, r[2])


def _load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def _run(case, clip):
    c = case["clips"][clip]
    F = c["frames"]
    rot = {k: np.array(v).reshape(F, 4) for k, v in c["rot"].items()}
    root = np.array(c["root"]).reshape(F, 3) * case["u"]
    return rot, root, FL.lock_clip(case["names"], case["parents"], np.array(case["rest"]), rot, root, c["fps"])


class TwoBone(unittest.TestCase):
    def test_reaches_the_target_keeps_lengths_and_the_foot_turn(self):
        rng = np.random.default_rng(7)
        for _ in range(200):
            pw, WU, WL, WB, a, b, c = _chain(rng)
            P = c + rng.normal(size=3) * 0.05
            l1, l2 = np.linalg.norm(b - a), np.linalg.norm(c - b)
            if not abs(l1 - l2) + 1e-3 < np.linalg.norm(P - a) < l1 + l2 - 1e-3:
                continue  # out of reach: covered by test_out_of_reach_and_straight_legs_stay_finite
            WBt = FL._unit(FL.qmul(_rand_q(rng, 10), WB))
            r = FL.two_bone(pw, WU, WL, WBt, a, b, c, P)
            U, L, B = _apply(pw, a, r)
            knee = a + FL.qrot(U, FL.qrot(FL.qinv(WU), b - a))
            ankle = knee + FL.qrot(L, FL.qrot(FL.qinv(WL), c - b))
            self.assertLess(np.linalg.norm(ankle - P), 1e-9)
            self.assertAlmostEqual(np.linalg.norm(knee - a), np.linalg.norm(b - a), delta=1e-12)
            self.assertAlmostEqual(np.linalg.norm(ankle - knee), np.linalg.norm(c - b), delta=1e-12)
            self.assertGreater(abs(float(B @ WBt)), 1 - 1e-12)

    def test_keeps_the_knee_bending_direction(self):
        rng = np.random.default_rng(11)
        for _ in range(200):
            pw, WU, WL, WB, a, b, c = _chain(rng)
            axis0 = np.cross(a - b, c - b)
            r = FL.two_bone(pw, WU, WL, WB, a, b, c, c + rng.normal(size=3) * 0.08)
            U, L, _ = _apply(pw, a, r)
            knee = a + FL.qrot(U, FL.qrot(FL.qinv(WU), b - a))
            ankle = knee + FL.qrot(L, FL.qrot(FL.qinv(WL), c - b))
            # the bend axis turns with the thigh: compare it in the thigh's own frame
            axis1 = np.cross(a - knee, ankle - knee)
            self.assertGreater(float(FL.qrot(FL.qinv(WU), axis0) @ FL.qrot(FL.qinv(U), axis1)), 0)

    def test_out_of_reach_and_straight_legs_stay_finite(self):
        rng = np.random.default_rng(3)
        pw, WU, WL, WB, a, b, c = _chain(rng)
        far = a + (c - a) / np.linalg.norm(c - a) * 2.0
        r = FL.two_bone(pw, WU, WL, WB, a, b, c, far)
        self.assertTrue(all(np.isfinite(q).all() for q in r))
        # max_reach keeps the knee bent: the hip-ankle distance is clamped to it
        l1, l2 = np.linalg.norm(b - a), np.linalg.norm(c - b)
        dmax = math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * math.cos(math.radians(5)))
        U, L, _ = _apply(pw, a, FL.two_bone(pw, WU, WL, WB, a, b, c, far, dmax))
        knee = a + FL.qrot(U, FL.qrot(FL.qinv(WU), b - a))
        ankle = knee + FL.qrot(L, FL.qrot(FL.qinv(WL), c - b))
        self.assertAlmostEqual(np.linalg.norm(ankle - a), dmax, delta=1e-9)
        # a straight source leg (no bend plane) falls back to the thigh's X axis
        WLs = WU
        cs = b + FL.qrot(WLs, np.array([0, -0.43, 0]))
        r = FL.two_bone(pw, WU, WLs, WB, a, b, cs, cs + np.array([0, 0.1, 0.05]))
        self.assertTrue(all(np.isfinite(q).all() for q in r))

    def test_weights_blend_smoothly(self):
        w = [FL._weight(k, 10, 15, 3) for k in range(5, 21)]
        self.assertEqual(w[0], 0.0)
        self.assertEqual(w[-1], 0.0)
        self.assertTrue(all(x == 1.0 for x in w[5:11]))
        self.assertTrue(all(a <= b for a, b in zip(w[:6], w[1:6])))  # rises monotonically into the lock


class Clips(unittest.TestCase):
    def test_matches_the_fixture_and_is_deterministic(self):
        for name in ("neutral", "long_legs"):
            case = _load(name)
            for clip in FL.CLIPS:
                c = case["clips"][clip]
                _, _, (a, rep) = _run(case, clip)
                _, _, (b, _) = _run(case, clip)
                for j, exp in c["expected"].items():
                    self.assertEqual(a[j].tobytes(), b[j].tobytes())
                    self.assertLess(np.abs(a[j].ravel() - np.array(exp)).max(), 1e-12, (name, clip, j))
                self.assertEqual({f: d.get("locked") for f, d in rep["feet"].items()}, c["expected_locked"])
                self.assertAlmostEqual(rep["ground_speed_m_s"], c["expected_ground_speed_m_s"], places=12)

    def test_locked_frames_pin_the_ankle_and_the_foot(self):
        for name in ("neutral", "long_legs"):
            case = _load(name)
            names, parents, rest = case["names"], case["parents"], np.array(case["rest"]).reshape(-1, 3)
            ix = {n: i for i, n in enumerate(names)}
            for clip in FL.CLIPS:
                rot, root, (new, rep) = _run(case, clip)
                F, v = len(root), rep["ground_speed_m_s"]
                self.assertGreater(v, 0)
                for U, L, B in FL.LEGS:
                    d = rep["feet"][B]
                    self.assertIsNotNone(d["locked"], (name, clip, B))
                    ls, n = d["locked_unwrapped_start"], d["locked"][1]
                    self.assertGreaterEqual(n, FL.MIN_SPAN)
                    ref = None
                    for k in range(ls, ls + n):
                        W, P = FL.fk(parents, rest, {ix[j]: new[j][k % F] for j in new}, root[k % F], ix["pelvis"])
                        g = P[ix[B]] + np.array([0, 0, v * k / 30])
                        q = FL._unit(W[ix[B]])  # the clips' float32 turns are unit to ~3e-8 only
                        if ref is None:
                            ref, qref = g, q
                        self.assertLess(np.linalg.norm(g - ref), 1e-6, (name, clip, B, k))
                        self.assertGreater(abs(float(q @ qref)), 1 - 1e-12)
                        d1, d2 = P[ix[L]] - P[ix[U]], P[ix[B]] - P[ix[L]]
                        flex = math.degrees(math.acos(float(d1 @ d2) / (np.linalg.norm(d1) * np.linalg.norm(d2))))
                        self.assertGreaterEqual(flex, FL.MIN_FLEX_DEG - 1e-4)
                        # 1e-7: the float32 parent turns (unit to ~3e-8) scale offsets slightly, in the source clip too
                        self.assertAlmostEqual(np.linalg.norm(d1), np.linalg.norm(rest[ix[L]] - rest[ix[U]]), delta=1e-7)

    def test_only_the_leg_channels_change(self):
        case = _load("neutral")
        for clip in FL.CLIPS:
            rot, _, (new, _) = _run(case, clip)
            legs = set(FL.LEGS[0] + FL.LEGS[1])
            self.assertEqual(set(new), set(rot))
            for j in rot:
                if j not in legs:
                    self.assertTrue(np.array_equal(new[j], rot[j]), j)
                self.assertTrue(np.allclose(np.linalg.norm(new[j], axis=1), 1, atol=1e-12))

    def test_a_clip_without_leg_channels_is_left_alone(self):
        case = _load("neutral")
        c = case["clips"]["walk"]
        F = c["frames"]
        rot = {k: np.array(v).reshape(F, 4) for k, v in c["rot"].items() if not k.startswith(("thigh", "calf", "foot"))}
        new, rep = FL.lock_clip(case["names"], case["parents"], np.array(case["rest"]), rot, np.zeros((F, 3)), 30)
        self.assertIs(new, rot)
        self.assertIsNone(rep["ground_speed_m_s"])

    def test_summary_record(self):
        case = _load("neutral")
        reps = {clip: _run(case, clip)[2][1] for clip in FL.CLIPS}
        rec = FL.summary(reps)["foot_lock"]
        self.assertEqual(rec["version"], FL.VERSION)
        self.assertEqual(set(rec["clips"]), set(FL.CLIPS))
        self.assertTrue(all(rec["clips"][c]["locked"]["foot_l"] for c in FL.CLIPS))
        json.dumps(rec)


if __name__ == "__main__":
    unittest.main()
