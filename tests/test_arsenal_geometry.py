"""Step 5A tests 7-28 (+ structural contact, plausibility-guard and source-guard checks): blade geometry.

7-10   each family is deterministic, in-process and in a fresh interpreter
11-14  different seeds vary meaningfully
15     component PRNG streams are isolated
16-19  geometry is valid per family: closed, consistently wound shells whose parts meet
20-21  the curved sword is really, progressively curved, and its curvature is deterministic
22-24  plausible dimensions (great sword, dagger, long sword; the curved sword too)
25-28  no NaN, no infinity, indices in range, no degenerate triangles
"""

import ast
import json
import math
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from unittest import mock

from arsenal_support import (
    ARSENAL_GOLDEN,
    COMPONENTS,
    FAMILIES,
    LINEUP_SEEDS,
    area,
    asset,
    axial_extent,
    bounds,
    edge_problems,
)
from forge.blades import curved_sword, dagger, great_sword, long_sword
from forge.blades.build import CURVED_SEGMENTS, MIN_CURVE_END_TANGENT_Y, blade_shape
from forge.blades.lineage import grip_hands
from forge.blades.model import BladeAsset, validate
from forge.blades.shapes import curved_centerline
from forge.catalog import REGISTRY
from forge.errors import GenerationError, GeometryError
from forge.hashing import geometry_sha256
from forge.mesh import Mesh, check_closed_oriented
from forge.registry import generate_asset
from forge_test_support import REPO_ROOT, faces, float_bits

MODULES = {"dagger": dagger, "long_sword": long_sword, "curved_sword": curved_sword, "great_sword": great_sword}
SWEEP = tuple(LINEUP_SEEDS) + tuple(range(100, 160))
CONTACT_TOLERANCE_M = 1e-12        # parts touch exactly, up to floating-point rounding of the shared plane


def fresh(family, seed):
    return generate_asset(REGISTRY, family, seed, 1)


class TestDeterminism(unittest.TestCase):
    """7-10."""

    @classmethod
    def setUpClass(cls):
        code = ("import json, sys; sys.path.insert(0, sys.argv[1])\n"
                "from forge.catalog import REGISTRY\nfrom forge.registry import generate_asset\n"
                "from forge.hashing import geometry_sha256\n"
                "print(json.dumps({f: {s: geometry_sha256(generate_asset(REGISTRY, f, s, 1)) for s in (1, 7, 1337)}"
                " for f in ('dagger', 'long_sword', 'curved_sword', 'great_sword')}))\n")
        env = dict(os.environ, PYTHONHASHSEED="12345")
        r = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT)], capture_output=True, text=True, env=env,
                           timeout=300)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        cls.subprocess_hashes = json.loads(r.stdout)

    def check(self, family):
        for seed in (1, 7, 1337):
            a, b = fresh(family, seed), fresh(family, seed)
            self.assertIsNot(a, b)
            self.assertEqual(float_bits(a), float_bits(b))
            self.assertEqual(faces(a), faces(b))
            self.assertEqual(a.params, b.params)
            self.assertEqual(a.landmarks, b.landmarks)
            self.assertEqual(geometry_sha256(a), self.subprocess_hashes[family][str(seed)])
        self.assertEqual(geometry_sha256(fresh(family, 1337)), ARSENAL_GOLDEN[family]["integrity"]["geometry_sha256"])

    def test_07_dagger_deterministic(self):
        self.check("dagger")

    def test_08_long_sword_deterministic(self):
        self.check("long_sword")

    def test_09_curved_sword_deterministic(self):
        self.check("curved_sword")

    def test_10_great_sword_deterministic(self):
        self.check("great_sword")


class TestVariation(unittest.TestCase):
    """11-14: seeds give meaningfully different weapons, not jitter on one design."""

    def check(self, family):
        rules = MODULES[family].RULES
        assets = [asset(family, s) for s in range(1, 81)]
        self.assertEqual(len({geometry_sha256(a) for a in assets}), len(assets))
        lengths = [a.params.blade.length for a in assets]
        lo, hi = rules.blade["length"]
        self.assertGreater(max(lengths) - min(lengths), 0.6 * (hi - lo), "blade lengths barely vary")
        totals = [a.params.total_length for a in assets]
        self.assertGreater(max(totals) - min(totals), 0.10 * max(totals))
        for attr, allowed in (("guard.shape", rules.guard_shapes), ("pommel.shape", rules.pommel_shapes),
                              ("blade.point_shape", tuple(rules.point_shapes)),
                              ("blade.cross_section", rules.cross_sections)):
            part, field = attr.split(".")
            seen = {getattr(getattr(a.params, part), field) for a in assets}
            self.assertEqual(seen, set(allowed), f"{family}: {attr} should reach every allowed value")
        widths = [a.params.guard.width for a in assets]
        self.assertGreater(max(widths) / min(widths), 1.4)
        # the lineup seeds alone already differ in silhouette: blade length or guard shape or pommel shape
        lineup = [asset(family, s).params for s in LINEUP_SEEDS]
        self.assertEqual(len({(round(p.blade.length, 3), p.guard.shape, p.pommel.shape) for p in lineup}), 6)
        return assets

    def test_11_dagger_seeds_vary(self):
        self.check("dagger")

    def test_12_long_sword_seeds_vary(self):
        self.check("long_sword")

    def test_13_curved_sword_seeds_vary(self):
        assets = self.check("curved_sword")
        sag = [a.params.blade.sagitta_ratio for a in assets]
        bias = [a.params.blade.curve_bias for a in assets]
        self.assertGreater(max(sag) - min(sag), 0.6 * (0.060 - 0.015))
        self.assertGreater(max(bias) - min(bias), 0.6 * (0.9 - -0.5))

    def test_14_great_sword_seeds_vary(self):
        assets = self.check("great_sword")
        ric = [a.params.blade.ricasso_length for a in assets]
        self.assertGreater(max(ric) - min(ric), 0.04)


class _Recorder:
    """Wraps a PCG32 stream and logs every draw the generator makes from it."""

    def __init__(self, stream, log):
        self._s, self._log = stream, log

    def __getattr__(self, name):
        method = getattr(self._s, name)

        def call(*args):
            out = method(*args)
            self._log.append((name, args, out))
            return out
        return call


class TestStreams(unittest.TestCase):
    def draws(self, module, seed, perturb=None):
        logs = {}
        real = module.derive_stream

        def derive(s, label):
            logs.setdefault(label, [])
            return _Recorder(real(s ^ 1 if label == perturb else s, label), logs[label])
        with mock.patch.object(module, "derive_stream", derive):
            module.draw_params(seed)
        return logs

    def test_15_component_streams_are_isolated(self):
        all_labels = []
        for family, module in MODULES.items():
            labels = dict(module.STREAM_LABELS)
            for component in COMPONENTS:
                self.assertEqual(labels[component], f"forge.{family}.{component}")
            self.assertTrue(all(v.startswith(f"forge.{family}.") for v in labels.values()))
            all_labels += labels.values()
            for seed in (1, 1337):
                base = self.draws(module, seed)
                self.assertEqual(sorted(base), sorted(labels.values()), "every stream is read, no other is")
                for label in labels.values():
                    with self.subTest(family=family, seed=seed, perturbed=label):
                        other = self.draws(module, seed, perturb=label)
                        for name in labels.values():
                            if name == label:
                                self.assertNotEqual(other[name], base[name])
                                self.assertEqual([c[:2] for c in other[name]], [c[:2] for c in base[name]],
                                                 "the draw order never depends on the drawn values")
                            else:
                                self.assertEqual(other[name], base[name], f"{name} moved when {label} changed")
        self.assertEqual(len(all_labels), len(set(all_labels)), "no stream label is shared between families")
        self.assertFalse(any(label.startswith("forge.sword") for label in all_labels))

    def test_family_extra_streams(self):
        self.assertEqual(sorted(curved_sword.STREAM_LABELS), sorted(COMPONENTS + ("curvature",)))
        self.assertEqual(sorted(great_sword.STREAM_LABELS), sorted(COMPONENTS + ("ricasso",)))
        self.assertEqual(sorted(dagger.STREAM_LABELS), sorted(COMPONENTS))
        self.assertEqual(sorted(long_sword.STREAM_LABELS), sorted(COMPONENTS))


class TestValidGeometry(unittest.TestCase):
    """16-19: every component is a closed, outward shell; neighbouring parts meet with no gap."""

    def check(self, family):
        for seed in SWEEP:
            with self.subTest(family=family, seed=seed):
                a = asset(family, seed)
                for m in a.components:
                    self.assertEqual(edge_problems(m), [], f"{m.name}")
                    check_closed_oriented(m)
                self.check_contacts(a)

    def check_contacts(self, a):
        blade, guard, grip, pommel = (a.component(n) for n in COMPONENTS)
        # along the central axis (x = 0, z = 0): pommel | grip | guard | blade, touching
        (b_lo, b_hi), (g_lo, g_hi), (h_lo, h_hi), (p_lo, p_hi) = (axial_extent(m) for m in
                                                                   (blade, guard, grip, pommel))
        self.assertLessEqual(abs(b_lo - g_hi), CONTACT_TOLERANCE_M, "blade does not meet the guard")
        self.assertLessEqual(abs(g_lo - h_hi), CONTACT_TOLERANCE_M, "guard does not meet the grip")
        self.assertLessEqual(abs(h_lo - p_hi), CONTACT_TOLERANCE_M, "grip does not meet the pommel")
        self.assertLess(p_lo, h_lo)
        self.assertLess(h_hi, b_hi)
        # the landmarks say the same thing as the geometry
        self.assertEqual(a.landmark("grip_center"), (0.0, 0.0, 0.0))
        self.assertEqual(bounds(grip)[1][1], a.landmark("grip_top_center")[1])
        self.assertEqual(bounds(grip)[0][1], a.landmark("grip_bottom_center")[1])
        self.assertEqual(bounds(blade)[0][1], a.landmark("blade_base_center")[1])
        self.assertLessEqual(abs(a.landmark("blade_base_center")[1] - g_hi), CONTACT_TOLERANCE_M)
        # each contact face is covered: the blade base and the grip top sit inside the guard's footprint
        base_y = a.landmark("blade_base_center")[1]
        base_ring = [p for p in blade.positions if p[1] == base_y]
        self.assertGreaterEqual(len(base_ring), 4)
        (gx0, _, gz0), (gx1, _, gz1) = bounds(guard)
        for x, _, z in base_ring:
            self.assertTrue(gx0 < x < gx1 and gz0 < z < gz1, "blade base overhangs the guard")
        top_y = a.landmark("grip_top_center")[1]
        for x, y, z in grip.positions:
            if y == top_y:
                self.assertTrue(gx0 < x < gx1 and gz0 < z < gz1, "grip top overhangs the guard")
        # nothing below the pommel, nothing above the tip
        lo, hi = a.bounds()
        self.assertEqual(lo[1], bounds(pommel)[0][1])
        self.assertEqual(hi[1], bounds(blade)[1][1])

    def test_contact_check_catches_a_gap(self):
        """The contact check is not vacuous: a 1 mm gap, or a part pushed into its neighbour, fails it."""
        a = asset("long_sword", 1337)
        for index, dy in ((3, -0.001), (1, 0.001), (0, 0.0005)):
            m = a.components[index]
            moved = Mesh(name=m.name, positions=tuple((x, y + dy, z) for x, y, z in m.positions), triangles=m.triangles)
            parts = list(a.components)
            parts[index] = moved
            broken = BladeAsset(asset_type=a.asset_type, generator=a.generator, generator_version=1, seed=a.seed,
                                params=a.params, components=tuple(parts), landmarks=a.landmarks)
            with self.assertRaises(AssertionError):
                self.check_contacts(broken)
        self.check_contacts(a)

    def test_16_dagger_geometry_valid(self):
        self.check("dagger")

    def test_17_long_sword_geometry_valid(self):
        self.check("long_sword")

    def test_18_curved_sword_geometry_valid(self):
        self.check("curved_sword")

    def test_19_great_sword_geometry_valid(self):
        self.check("great_sword")


class TestCurvature(unittest.TestCase):
    """20-21."""

    def test_20_curved_sword_is_really_curved(self):
        for seed in SWEEP:
            with self.subTest(seed=seed):
                a = asset("curved_sword", seed)
                b = a.params.blade
                self.assertGreater(b.sagitta_ratio, 0.0)
                cl = blade_shape(b, a.landmark("blade_base_center")[1]).centerline
                self.assertEqual(cl.segments, CURVED_SEGMENTS)
                pts = cl.points
                # the mesh follows the centerline: every ring lies across its local tangent
                blade = a.component("blade")
                n = 5                                           # single-edge profile points per ring
                for k in range(CURVED_SEGMENTS):
                    (cx, cy), (tx, ty) = pts[k], cl.tangents[k]
                    for j in range(n):
                        x, y, _ = blade.positions[k * n + j]
                        self.assertLess(abs((x - cx) * tx + (y - cy) * ty), 1e-12)
                # equal arc-length steps that turn the same way, by amounts that follow the bias
                step = b.length / CURVED_SEGMENTS
                dirs = []
                for p, q in zip(pts, pts[1:]):
                    dx, dy = q[0] - p[0], q[1] - p[1]
                    self.assertAlmostEqual(math.sqrt(dx * dx + dy * dy), step, delta=1e-12)
                    dirs.append((dx / step, dy / step))
                turns = [u[0] * v[1] - u[1] * v[0] for u, v in zip(dirs, dirs[1:])]
                self.assertTrue(all(t > 0.0 for t in turns), "the blade must keep bending one way")
                deltas = [t2 - t1 for t1, t2 in zip(turns, turns[1:])]
                if b.curve_bias > 0.01:
                    self.assertTrue(all(d > -1e-12 for d in deltas), "bias > 0 must tighten toward the tip")
                elif b.curve_bias < -0.01:
                    self.assertTrue(all(d < 1e-12 for d in deltas), "bias < 0 must ease toward the tip")
                # the drawn sagitta is reached
                (x0, y0), (x1, y1) = pts[0], pts[-1]
                chord = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
                sag = max(abs((x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)) / chord for x, y in pts)
                self.assertAlmostEqual(sag, b.sagitta_ratio * b.length, delta=1e-9)
                # it bends toward -X, edge on the convex side, and never past the turn limit
                tip, tangent = a.landmark("blade_tip"), a.landmark("blade_tip_tangent")
                self.assertLess(tip[0], -0.01)
                self.assertLess(tangent[0], 0.0)
                self.assertGreaterEqual(tangent[1], MIN_CURVE_END_TANGENT_Y)
                self.assertLess(min(p[0] for p in blade.positions), -0.5 * b.sagitta_ratio * b.length)
        for family in ("dagger", "long_sword", "great_sword"):
            for seed in LINEUP_SEEDS:
                a = asset(family, seed)
                self.assertEqual(a.params.blade.sagitta_ratio, 0.0)
                positions = a.component("blade").positions
                self.assertEqual(set(positions), {(0.0 - x, y, z) for x, y, z in positions},
                                 "a straight double-edged blade is mirror-symmetric")
                self.assertEqual(a.landmark("blade_tip")[0], 0.0)

    def test_21_curvature_deterministic(self):
        for seed in (1, 42, 1337):
            b = asset("curved_sword", seed).params.blade
            c1 = curved_centerline(0.1, b.length, CURVED_SEGMENTS, b.sagitta_ratio, b.curve_bias)
            c2 = curved_centerline(0.1, b.length, CURVED_SEGMENTS, b.sagitta_ratio, b.curve_bias)
            self.assertEqual(c1, c2)
            self.assertEqual([p.hex() for xy in c1.points for p in xy], [p.hex() for xy in c2.points for p in xy])
            self.assertEqual(float_bits(fresh("curved_sword", seed)), float_bits(asset("curved_sword", seed)))
        # a pure function of its inputs; the base height shifts it (to rounding: the bisection sees the
        # shifted coordinates, so bits may differ in the last place) and changes nothing else
        a = curved_centerline(0.0, 0.7, 24, 0.04, 0.3)
        b = curved_centerline(1.0, 0.7, 24, 0.04, 0.3)
        for p, q in zip(a.points, b.points):
            self.assertAlmostEqual(p[0], q[0], delta=1e-12)
            self.assertAlmostEqual(p[1] + 1.0, q[1], delta=1e-12)
        for bad in ((0.0, 0.7, 4, 0.04, 0.3), (0.0, 0.7, 24, 0.0, 0.3), (0.0, 0.7, 24, 0.2, 0.3),
                    (0.0, 0.7, 24, 0.04, 1.5)):
            with self.assertRaises(GeometryError):
                curved_centerline(*bad)


class TestPlausibleDimensions(unittest.TestCase):
    """22-24 (+ the curved sword): measured from the generated geometry, over many seeds."""

    SEEDS = tuple(range(1, 301))

    def measured(self, a):
        blade = a.component("blade")
        base_y = a.landmark("blade_base_center")[1]
        tip = a.landmark("blade_tip")
        (bx0, _, bz0), (bx1, _, bz1) = bounds(blade)
        lo, hi = a.bounds()
        g0, g1 = bounds(a.component("guard"))
        h0, h1 = bounds(a.component("grip"))
        return {
            "blade_reach": tip[1] - base_y,                         # straight-line height of the tip above the guard
            "blade_width": bx1 - bx0, "blade_thickness": bz1 - bz0,
            "overall": hi[1] - lo[1],
            "guard_width": g1[0] - g0[0],
            "grip_length": h1[1] - h0[1],
        }

    def ranges(self, family):
        out = {}
        for seed in self.SEEDS:
            for k, v in self.measured(asset(family, seed)).items():
                lo, hi = out.get(k, (v, v))
                out[k] = (min(lo, v), max(hi, v))
        return out

    def within(self, r, name, lo, hi):
        self.assertGreaterEqual(r[name][0], lo, name)
        self.assertLessEqual(r[name][1], hi, name)

    def test_22_great_sword_plausible(self):
        r = self.ranges("great_sword")
        self.within(r, "blade_reach", 1.0, 1.5)
        self.within(r, "overall", 1.30, 2.05)          # Zweihander-class; never a 3 m cartoon
        self.within(r, "blade_width", 0.04, 0.07)
        self.within(r, "guard_width", 0.20, 0.50)
        self.within(r, "grip_length", 0.26, 0.47)       # two hands
        for seed in self.SEEDS:
            self.assertEqual(grip_hands(asset("great_sword", seed).params.grip.length), "two")

    def test_23_dagger_plausible(self):
        r = self.ranges("dagger")
        self.within(r, "blade_reach", 0.18, 0.45)
        self.within(r, "overall", 0.27, 0.62)
        self.within(r, "blade_width", 0.018, 0.045)
        self.within(r, "grip_length", 0.08, 0.12)       # one hand
        self.within(r, "guard_width", 0.03, 0.15)

    def test_24_long_sword_plausible(self):
        r = self.ranges("long_sword")
        self.within(r, "blade_reach", 0.75, 1.10)
        self.within(r, "overall", 0.95, 1.50)
        self.within(r, "blade_width", 0.035, 0.06)
        self.within(r, "grip_length", 0.15, 0.26)       # hand-and-a-half
        self.within(r, "guard_width", 0.13, 0.33)

    def test_curved_sword_plausible(self):
        r = self.ranges("curved_sword")
        self.within(r, "blade_reach", 0.55, 0.90)      # the chord is shorter than the curved blade
        self.within(r, "overall", 0.70, 1.20)
        self.within(r, "grip_length", 0.10, 0.26)
        for seed in self.SEEDS:
            b = asset("curved_sword", seed).params.blade
            self.assertTrue(0.015 <= b.sagitta_ratio <= 0.060)

    def test_family_size_order(self):
        """Typical sizes rank dagger < curved sword < long sword < great sword. Ranges may overlap at the
        extremes (a large long sword can outreach a small great sword); a dagger never reaches a sword."""
        overall = {f: sorted(self.measured(asset(f, s))["overall"] for s in self.SEEDS) for f in FAMILIES}
        medians = [overall[f][len(self.SEEDS) // 2] for f in ("dagger", "curved_sword", "long_sword", "great_sword")]
        self.assertEqual(medians, sorted(medians))
        self.assertLess(overall["dagger"][-1], min(overall[f][0] for f in FAMILIES if f != "dagger"))


class TestPlausibilityGuards(unittest.TestCase):
    """validate() fails closed on an implausible weapon; nothing is clamped or repaired."""

    def refuse(self, module, params, pattern):
        with self.assertRaisesRegex(GenerationError, pattern):
            validate(params, module.RULES)

    def test_guards(self):
        p = dagger.draw_params(1337)
        validate(p, dagger.RULES)
        self.refuse(dagger, replace(p, blade=replace(p.blade, length=0.60)), "blade.length")
        self.refuse(dagger, replace(p, blade=replace(p.blade, sagitta_ratio=0.03)), "curvature")
        self.refuse(dagger, replace(p, blade=replace(p.blade, length=float("nan"))), "blade.length")
        self.refuse(dagger, replace(p, guard=replace(p.guard, shape="halberd")), "guard shape")
        self.refuse(dagger, replace(p, grip=replace(p.grip, segments=9)), "segments")
        g = great_sword.draw_params(1337)
        validate(g, great_sword.RULES)
        self.refuse(great_sword, replace(g, blade=replace(g.blade, length=2.4)), "blade.length")
        self.refuse(great_sword, replace(g, guard=replace(g.guard, width=0.06)), "guard")
        self.refuse(great_sword, replace(g, pommel=replace(g.pommel, radius=0.09)), "pommel")
        L = long_sword.draw_params(1337)
        validate(L, long_sword.RULES)
        self.refuse(long_sword, replace(L, blade=replace(L.blade, ricasso_length=0.1)), "ricasso")
        self.refuse(long_sword, replace(L, blade=replace(L.blade, cross_section="diamond", flat_fraction=0.5)),
                    "diamond")
        c = curved_sword.draw_params(1337)
        validate(c, curved_sword.RULES)
        self.refuse(curved_sword, replace(c, blade=replace(c.blade, sagitta_ratio=0.2)), "sagitta")
        self.refuse(curved_sword, replace(c, blade=replace(c.blade, point_shape="leaf")), "point shape")
        self.refuse(curved_sword, replace(c, blade=replace(c.blade, cross_section="diamond")), "cross section")


class TestMeshHygiene(unittest.TestCase):
    """25-28, over every family and the whole seed sweep."""

    def each_mesh(self):
        for family in FAMILIES:
            for seed in SWEEP:
                for m in asset(family, seed).components:
                    yield family, seed, m

    def test_25_no_nan_vertices(self):
        for family, seed, m in self.each_mesh():
            self.assertFalse(any(c != c for p in m.positions for c in p), (family, seed, m.name))

    def test_26_no_infinite_vertices(self):
        for family, seed, m in self.each_mesh():
            self.assertTrue(all(math.isfinite(c) for p in m.positions for c in p), (family, seed, m.name))
            self.assertTrue(all(type(c) is float for p in m.positions for c in p))

    def test_27_indices_in_range(self):
        for family, seed, m in self.each_mesh():
            n = len(m.positions)
            for tri in m.triangles:
                self.assertEqual(len(tri), 3)
                self.assertTrue(all(type(i) is int and 0 <= i < n for i in tri), (family, seed, m.name, tri))
            used = {i for t in m.triangles for i in t}
            self.assertEqual(used, set(range(n)), "every vertex is used")

    def test_28_no_degenerate_triangles(self):
        for family, seed, m in self.each_mesh():
            p = m.positions
            for a, b, c in m.triangles:
                self.assertEqual(len({a, b, c}), 3)
                self.assertGreater(area(p[a], p[b], p[c]), 1e-9, (family, seed, m.name, (a, b, c)))
            self.assertEqual(len(set(p)), len(p), "no duplicated vertex positions within a component")


class TestSourceGuards(unittest.TestCase):
    """The blade code keeps Forge's determinism rules: + - * / and sqrt, no transcendentals,
    no '**', no pow(), no sum() over floats, no ambient randomness, time or hashing."""

    FILES = sorted((REPO_ROOT / "forge" / "blades").glob("*.py")) + [REPO_ROOT / "forge" / "render" / "fit.py",
                                                                      REPO_ROOT / "forge" / "assets" / "blades.py"]
    MATH_ALLOWED = {"sqrt", "isfinite"}
    BANNED_MODULES = {"random", "time", "datetime", "secrets", "uuid", "numpy", "decimal", "fractions", "cmath"}

    def test_determinism_rules(self):
        self.assertEqual(len(self.FILES), 13)
        for path in self.FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                where = f"{path.relative_to(REPO_ROOT)}:{getattr(node, 'lineno', '?')}"
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math":
                    self.assertIn(node.attr, self.MATH_ALLOWED, where)
                self.assertNotIsInstance(node, ast.Pow, where)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"pow", "sum", "hash", "id", "eval", "exec"}, where)
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], self.BANNED_MODULES, where)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], self.BANNED_MODULES, where)
                    if node.module == "math":
                        self.assertTrue({a.name for a in node.names} <= self.MATH_ALLOWED, where)


if __name__ == "__main__":
    unittest.main()
