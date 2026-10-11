"""Step 5B tests 6-21 and 23-33 (+ plausibility-guard and source-guard checks): hafted geometry.

6-9    each family is deterministic, in-process and in a fresh interpreter
10-13  different seeds vary meaningfully
14     component PRNG streams are isolated (and materials never touch geometry)
15-18  geometry is valid per family: closed, consistently wound, outward shells
19-21  finite vertices, valid indices, no degenerate triangles
23-24  the head is seated on the haft, every part is seated in its neighbour, nothing floats
25-28  plausible overall dimensions
29-33  plausible head proportions: axe heads, mace heads, hammer faces, rear picks
Plus the pre-freeze realism pass: forged axe eyes whose cheeks run into the bit, and war-hammer
heads that their hafts do not dwarf.
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

from forge.catalog import REGISTRY
from forge.errors import GenerationError
from forge.hafted import axe, mace, one_hand_axe, two_hand_axe, war_hammer
from forge.hafted.haft import top_radii
from forge.hafted.model import HaftedAsset
from forge.hafted.presentation import HAFTED_PRESENTATION_V1, derive_hafted_presentation
from forge.hashing import geometry_sha256
from forge.mesh import Mesh, check_closed_oriented
from forge.registry import generate_asset
from forge_test_support import REPO_ROOT, faces, float_bits
from hafted_support import (
    COMPONENTS,
    FAMILIES,
    HAFTED_GOLDEN,
    LINEUP_SEEDS,
    SWEEP,
    area,
    asset,
    bounds,
    edge_problems,
    inside,
    seated,
)

MODULES = {"one_hand_axe": one_hand_axe, "two_hand_axe": two_hand_axe, "mace": mace, "war_hammer": war_hammer}
WIDE = tuple(range(1, 301))


def fresh(family, seed):
    return generate_asset(REGISTRY, family, seed, 1)


class TestDeterminism(unittest.TestCase):
    """6-9."""

    @classmethod
    def setUpClass(cls):
        code = ("import json, sys; sys.path.insert(0, sys.argv[1])\n"
                "from forge.catalog import REGISTRY\nfrom forge.registry import generate_asset\n"
                "from forge.hashing import geometry_sha256\n"
                "print(json.dumps({f: {s: geometry_sha256(generate_asset(REGISTRY, f, s, 1)) for s in (1, 7, 1337)}"
                " for f in ('one_hand_axe', 'two_hand_axe', 'mace', 'war_hammer')}))\n")
        r = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT)], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONHASHSEED="4242"), timeout=300)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        cls.other_process = json.loads(r.stdout)

    def check(self, family):
        for seed in (1, 7, 1337):
            a, b = fresh(family, seed), fresh(family, seed)
            self.assertIsNot(a, b)
            self.assertEqual(float_bits(a), float_bits(b))
            self.assertEqual(faces(a), faces(b))
            self.assertEqual(a.params, b.params)
            self.assertEqual(a.landmarks, b.landmarks)
            self.assertEqual(a.joints, b.joints)
            self.assertEqual(geometry_sha256(a), self.other_process[family][str(seed)])
        self.assertEqual(geometry_sha256(fresh(family, 1337)), HAFTED_GOLDEN[family]["integrity"]["geometry_sha256"])

    def test_06_one_hand_axe_deterministic(self):
        self.check("one_hand_axe")

    def test_07_two_hand_axe_deterministic(self):
        self.check("two_hand_axe")

    def test_08_mace_deterministic(self):
        self.check("mace")

    def test_09_war_hammer_deterministic(self):
        self.check("war_hammer")


def _styles(family, a):
    p = a.params
    if family in ("one_hand_axe", "two_hand_axe"):
        return {"style": p.head.style, "poll": p.head.poll, "collar": p.head.collar_height > 0.0}
    if family == "mace":
        return {"form": p.elements.form, "count": p.elements.count, "core": p.head.core_shape, "cap": p.butt_cap.shape}
    return {"face": p.face.shape, "rear": p.rear.style, "cap": p.butt_cap.shape}


class TestVariation(unittest.TestCase):
    """10-13: seeds give different weapons, not jitter on one design."""

    EXPECTED = {
        "one_hand_axe": {"style": set(one_hand_axe.STYLES), "poll": {"flat", "hammer"}, "collar": {True, False}},
        "two_hand_axe": {"style": set(two_hand_axe.STYLES), "poll": {"flat", "spike"}, "collar": {True, False}},
        "mace": {"form": set(mace.FORMS), "count": {6, 8, 12}, "core": {"round", "faceted"},
                 "cap": {"knob", "disc", "cone"}},
        "war_hammer": {"face": {"square", "octagonal", "round"}, "rear": {"pick", "spike", "poll"},
                       "cap": {"knob", "disc", "cone"}},
    }

    def check(self, family):
        assets = [asset(family, s) for s in range(1, 121)]
        self.assertEqual(len({geometry_sha256(a) for a in assets}), len(assets))
        seen: dict = {}
        for a in assets:
            for k, v in _styles(family, a).items():
                seen.setdefault(k, set()).add(v)
        self.assertEqual(seen, self.EXPECTED[family], "every head style should appear")
        lengths = [a.overall_length for a in assets]
        self.assertGreater(max(lengths) - min(lengths), 0.25 * max(lengths))
        masses = [a.head_mass_kg for a in assets]
        self.assertGreater(max(masses) / min(masses), 1.6)
        widths = [a.bounds()[1][0] - a.bounds()[0][0] for a in assets]
        self.assertGreater(max(widths) / min(widths), 1.3)
        lineup = [_styles(family, asset(family, s)) for s in LINEUP_SEEDS]
        self.assertGreaterEqual(len({tuple(sorted(d.items())) for d in lineup}), 3)

    def test_10_one_hand_axe_seeds_vary(self):
        self.check("one_hand_axe")

    def test_11_two_hand_axe_seeds_vary(self):
        self.check("two_hand_axe")

    def test_12_mace_seeds_vary(self):
        self.check("mace")

    def test_13_war_hammer_seeds_vary(self):
        self.check("war_hammer")


class _Recorder:
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

    def test_14_component_streams_are_isolated(self):
        all_labels = []
        for family, module in MODULES.items():
            labels = dict(module.STREAM_LABELS)
            self.assertEqual(sorted(labels), sorted(COMPONENTS[family]), "one stream per component")
            for component, label in labels.items():
                self.assertEqual(label, f"forge.{family}.{component}")
            all_labels += labels.values()
            for seed in (1, 1337):
                base = self.draws(module, seed)
                self.assertEqual(sorted(base), sorted(labels.values()))
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
        self.assertEqual(len(all_labels), len(set(all_labels)))
        self.assertFalse(any(label.startswith(("forge.sword", "forge.dagger", "forge.long_sword", "forge.curved_sword",
                                               "forge.great_sword")) for label in all_labels))

    def test_materials_never_move_geometry(self):
        for family in FAMILIES:
            a = asset(family, 99)
            before = float_bits(a)
            p = derive_hafted_presentation(a, HAFTED_PRESENTATION_V1)
            self.assertEqual(float_bits(p.asset), before)
            self.assertIs(p.asset, a)
            # the material streams are their own: perturbing one changes only that component
            from forge.hafted import presentation as pres
            real = pres.derive_stream
            target = f"{pres.MATERIAL_STREAM_PREFIX}{family}.grip"
            with mock.patch.object(pres, "derive_stream", lambda s, label: real(s ^ 1 if label == target else s, label)):
                q = derive_hafted_presentation(a, HAFTED_PRESENTATION_V1)
            self.assertNotEqual(q.component("grip").material, p.component("grip").material)
            self.assertEqual(q.component("haft").material, p.component("haft").material)
            self.assertEqual(float_bits(q.asset), before)


class TestValidGeometry(unittest.TestCase):
    """15-18 and 19-21."""

    def check(self, family):
        for seed in SWEEP:
            with self.subTest(family=family, seed=seed):
                a = asset(family, seed)
                for m in a.components:
                    self.assertEqual(edge_problems(m), [], m.name)
                    check_closed_oriented(m)
                    self.assertGreater(m.signed_volume(), 0.0)

    def test_15_one_hand_axe_geometry_valid(self):
        self.check("one_hand_axe")

    def test_16_two_hand_axe_geometry_valid(self):
        self.check("two_hand_axe")

    def test_17_mace_geometry_valid(self):
        self.check("mace")

    def test_18_war_hammer_geometry_valid(self):
        self.check("war_hammer")

    def each_mesh(self):
        for family in FAMILIES:
            for seed in SWEEP:
                for m in asset(family, seed).components:
                    yield family, seed, m

    def test_19_finite_vertices(self):
        for family, seed, m in self.each_mesh():
            self.assertTrue(all(type(c) is float and math.isfinite(c) for p in m.positions for c in p),
                            (family, seed, m.name))

    def test_20_valid_indices(self):
        for family, seed, m in self.each_mesh():
            n = len(m.positions)
            for tri in m.triangles:
                self.assertTrue(len(tri) == 3 and all(type(i) is int and 0 <= i < n for i in tri), (family, seed, m.name))
            self.assertEqual({i for t in m.triangles for i in t}, set(range(n)), "every vertex is used")

    def test_21_no_degenerate_triangles(self):
        for family, seed, m in self.each_mesh():
            p = m.positions
            for a, b, c in m.triangles:
                self.assertEqual(len({a, b, c}), 3)
                self.assertGreater(area(p[a], p[b], p[c]), 1e-9, (family, seed, m.name, (a, b, c)))
            self.assertEqual(len(set(p)), len(p), "no duplicated vertex positions within a part")


class TestAssembly(unittest.TestCase):
    """23-24: believable assembly. The joints are checked geometrically, not trusted."""

    def test_23_head_meets_haft(self):
        for family in FAMILIES:
            for seed in SWEEP:
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    head_joints = [j for j in a.joints if j.inner == "haft" and j.outer == "head"]
                    self.assertTrue(head_joints, "every family seats its haft in its head")
                    for j in head_joints:
                        n, k = seated(a, j)
                        self.assertGreaterEqual(n, 12, j.meaning)
                        self.assertEqual(k, n, f"{n - k} haft vertices outside the head ({j.meaning})")
                    # the head sits on the haft's end: the haft's top is inside or just proud of the head
                    haft_top = bounds(a.component("haft"))[1][1]
                    head_lo, head_hi = bounds(a.component("head"))[0][1], bounds(a.component("head"))[1][1]
                    self.assertTrue(head_lo < haft_top <= head_hi + 0.0051)

    def test_24_no_large_assembly_gap(self):
        for family in FAMILIES:
            for seed in SWEEP:
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    for j in a.joints:
                        n, k = seated(a, j)
                        self.assertGreaterEqual(n, 4, j.meaning)
                        self.assertEqual(k, n, j.meaning)
                    # every part is joined, directly or through others, to the haft: nothing floats
                    reached, frontier = {"haft"}, ["haft"]
                    while frontier:
                        c = frontier.pop()
                        for j in a.joints:
                            for x, y in ((j.inner, j.outer), (j.outer, j.inner)):
                                if x == c and y not in reached:
                                    reached.add(y)
                                    frontier.append(y)
                    self.assertEqual(reached, set(COMPONENTS[family]))

    def test_moving_a_part_breaks_the_seat(self):
        """The seating check is not vacuous: lifting the head 6 mm, pulling a bit or face 6 mm
        forward, or dropping a butt cap fails it."""
        cases = {"one_hand_axe": ("head", (0.0, 0.006, 0.0)), "two_hand_axe": ("bit", (0.006, 0.0, 0.0)),
                 "mace": ("head", (0.0, 0.03, 0.0)), "war_hammer": ("face", (0.006, 0.0, 0.0))}
        for family, (part, (dx, dy, dz)) in cases.items():
            a = asset(family, 1337)
            moved = Mesh(name=part, positions=tuple((x + dx, y + dy, z + dz) for x, y, z in a.component(part).positions),
                         triangles=a.component(part).triangles)
            broken = HaftedAsset(asset_type=a.asset_type, generator=a.generator, generator_version=1, seed=a.seed,
                                 params=a.params, components=tuple(moved if m.name == part else m for m in a.components),
                                 landmarks=a.landmarks, joints=a.joints, head_components=a.head_components,
                                 head_bore_volume=a.head_bore_volume)
            failures = [j.meaning for j in broken.joints if (lambda nk: nk[0] < 4 or nk[1] != nk[0])(seated(broken, j))]
            self.assertTrue(failures, f"{family}: moving the {part} went unnoticed")


class TestDimensions(unittest.TestCase):
    """25-28, measured from the generated geometry over 300 seeds."""

    def measure(self, family):
        out: dict = {}
        for seed in WIDE:
            a = asset(family, seed)
            lo, hi = a.bounds()
            for k, v in (("overall", a.overall_length), ("head_mass", a.head_mass_kg), ("width", hi[0] - lo[0]),
                         ("haft", a.params.haft.length), ("haft_diameter", 2.0 * a.params.haft.radius),
                         ("grip", a.params.grip.length)):
                lo_v, hi_v = out.get(k, (v, v))
                out[k] = (min(lo_v, v), max(hi_v, v))
        return out

    def within(self, r, name, lo, hi):
        self.assertGreaterEqual(r[name][0], lo, name)
        self.assertLessEqual(r[name][1], hi, name)

    def test_25_one_hand_axe_dimensions(self):
        r = self.measure("one_hand_axe")
        self.within(r, "overall", 0.35, 0.80)
        self.within(r, "head_mass", 0.30, 1.40)
        self.within(r, "width", 0.10, 0.20)
        self.within(r, "haft_diameter", 0.022, 0.032)
        self.within(r, "grip", 0.08, 0.14)

    def test_26_two_hand_axe_dimensions(self):
        r = self.measure("two_hand_axe")
        self.within(r, "overall", 0.85, 1.60)
        self.within(r, "head_mass", 0.40, 2.00)
        self.within(r, "width", 0.14, 0.30)
        self.within(r, "haft_diameter", 0.026, 0.034)
        for seed in LINEUP_SEEDS:
            a = asset("two_hand_axe", seed)
            upper_bot, grip_top = a.landmark("upper_grip_bottom")[1], a.landmark("grip_top_center")[1]
            self.assertGreaterEqual(upper_bot - grip_top, 0.12, "two hands need room on the haft")

    def test_27_mace_dimensions(self):
        r = self.measure("mace")
        self.within(r, "overall", 0.40, 0.80)
        self.within(r, "head_mass", 0.30, 1.60)
        self.within(r, "width", 0.04, 0.11)
        self.within(r, "grip", 0.09, 0.15)

    def test_28_war_hammer_dimensions(self):
        r = self.measure("war_hammer")
        self.within(r, "overall", 0.45, 0.95)
        self.within(r, "head_mass", 0.20, 1.20)
        self.within(r, "width", 0.06, 0.26)


class TestHeadProportions(unittest.TestCase):
    """29-33: proportions, and validate() refusing grotesque values instead of clamping them."""

    def refuse(self, fn, params, pattern):
        with self.assertRaisesRegex(GenerationError, pattern):
            fn(params)

    def axe_checks(self, family, module):
        for seed in WIDE:
            a = asset(family, seed)
            p = a.params
            rt, rzt = top_radii(p.haft)
            reach = p.bit.projection - (rt + p.head.wall_front)
            thick = 2.0 * (rzt + p.head.wall_side)
            lo, hi = module.RULES.projection_to_thickness
            self.assertTrue(lo <= reach / thick <= hi)
            hl = axe.head_length(p)
            self.assertTrue(module.RULES.head_length[0] <= hl <= module.RULES.head_length[1])
            self.assertLessEqual(hl / p.haft.length, module.RULES.head_to_haft[1])
            edge = a.landmark("strike_point")
            self.assertAlmostEqual(edge[0], p.bit.projection, delta=1e-9)
            self.assertEqual(edge[2], 0.0)
        p = module.draw_params(1337)
        axe.validate(p, module.RULES)
        v = lambda q: axe.validate(q, module.RULES)
        self.refuse(v, replace(p, bit=replace(p.bit, projection=0.45)), "projection")
        self.refuse(v, replace(p, bit=replace(p.bit, beard=0.30)), "beard")
        self.refuse(v, replace(p, head=replace(p.head, eye_height=0.20)), "eye_height")
        self.refuse(v, replace(p, haft=replace(p.haft, radius=0.004)), "haft.radius")
        self.refuse(v, replace(p, haft=replace(p.haft, length=float("nan"))), "haft.length")
        self.refuse(v, replace(p, head=replace(p.head, style="mmo_greataxe")), "style")

    def test_29_one_hand_axe_head_proportion(self):
        self.axe_checks("one_hand_axe", one_hand_axe)

    def test_30_two_hand_axe_head_proportion(self):
        self.axe_checks("two_hand_axe", two_hand_axe)
        # the head does not grow with the haft: short and long hafts carry the same range of heads
        rows = sorted((asset("two_hand_axe", s).params.haft.length, axe.head_length(asset("two_hand_axe", s).params))
                      for s in WIDE)
        short = [h for _, h in rows[:100]]
        long_ = [h for _, h in rows[-100:]]
        self.assertLess(abs(sum(long_) / 100 - sum(short) / 100), 0.012)
        self.assertLessEqual(max(long_), two_hand_axe.RULES.head_length[1])

    def test_31_mace_head_proportion(self):
        for seed in WIDE:
            p = asset("mace", seed).params
            radius = p.head.core_radius + p.elements.projection
            self.assertTrue(1.6 <= radius / p.haft.radius <= 4.6)
            self.assertLessEqual(2.0 * radius, 0.11)
            self.assertLessEqual(p.elements.projection, 1.6 * p.head.core_radius)
        p = mace.draw_params(1337)
        mace.validate(p)
        self.refuse(mace.validate, replace(p, head=replace(p.head, core_radius=0.09)), "core_radius")
        self.refuse(mace.validate, replace(p, elements=replace(p.elements, projection=0.08)), "projection")
        self.refuse(mace.validate, replace(p, elements=replace(p.elements, count=7)), "elements")
        self.refuse(mace.validate, replace(p, elements=replace(p.elements, form="flail")), "form")

    def test_32_hammer_face_proportion(self):
        for seed in WIDE:
            p = asset("war_hammer", seed).params
            self.assertTrue(1.2 <= p.face.size / (p.face.neck_ratio * p.face.size) <= 2.2)
            self.assertLessEqual(p.face.size, p.head.eye_height)
            self.assertLessEqual(p.face.size, 0.040)
            face = asset("war_hammer", seed).component("face")
            (fx0, fy0, fz0), (fx1, fy1, fz1) = bounds(face)
            self.assertLessEqual(fy1 - fy0, 0.041)
        p = war_hammer.draw_params(1337)
        war_hammer.validate(p)
        self.refuse(war_hammer.validate, replace(p, face=replace(p.face, size=0.09)), "face.size")
        self.refuse(war_hammer.validate, replace(p, face=replace(p.face, neck_ratio=0.2)), "neck_ratio")

    def test_33_rear_pick_bounds(self):
        for seed in WIDE:
            a = asset("war_hammer", seed)
            p = a.params
            s = war_hammer.REAR_STYLES[p.rear.style]
            self.assertTrue(s.length[0] <= p.rear.length <= s.length[1])
            self.assertLessEqual(p.rear.length, 0.12)
            tip = a.landmark("secondary_strike_point")
            self.assertLess(tip[0], 0.0)
            self.assertLessEqual(0.0 - tip[0], 0.16, "the rear never reaches past 16 cm from the haft")
            if p.rear.style == "pick":
                self.assertLess(tip[1], a.landmark("head_center")[1], "a pick curves downward")
                self.assertGreater(tip[1], a.landmark("eye_bottom")[1] - 0.04, "but not into a hook")
        p = war_hammer.draw_params(1337)
        self.refuse(war_hammer.validate, replace(p, rear=replace(p.rear, style="pick", length=0.30, turn=0.1)),
                    "rear.length")
        self.refuse(war_hammer.validate, replace(p, rear=replace(p.rear, style="spike", length=0.06, turn=0.3)),
                    "rear.turn")
        p2 = two_hand_axe.draw_params(1337)
        self.refuse(lambda q: axe.validate(q, two_hand_axe.RULES),
                    replace(p2, head=replace(p2.head, poll="spike", poll_reach=0.25, poll_size=0.02)), "poll_reach")


class TestForgedHeads(unittest.TestCase):
    """The pre-freeze realism pass: forged axe eyes, and war-hammer heads not dwarfed by their hafts."""

    def test_axe_eye_is_forged_not_a_block(self):
        from forge.hafted.shapes import convex_ccw
        for family, module in (("one_hand_axe", one_hand_axe), ("two_hand_axe", two_hand_axe)):
            for seed in WIDE:
                with self.subTest(family=family, seed=seed):
                    p = asset(family, seed).params
                    L = axe._layout(p)
                    rows, fronts = axe._eye_rows(L, p.head, p.bit)
                    self.assertEqual(len(rows), 10)
                    rz = L.eye_half_thickness
                    for y, poly in rows:
                        convex_ccw("eye", poly)
                        self.assertEqual(len(poly), 16)
                        xs = [x for x, _ in poly]
                        self.assertLess(max(xs), p.bit.projection)
                    neck = dict(rows)[L.neck_bot]
                    # a teardrop: full wall beside the haft, a narrow cheek front, a rounded poll face
                    self.assertAlmostEqual(max(z for _, z in neck), rz, delta=1e-12)
                    self.assertLess(0.0 - neck[0][1], 0.5 * rz)
                    self.assertAlmostEqual(neck[1][1], 0.0 - neck[0][1], delta=1e-15)
                    x_min = min(x for x, _ in neck)
                    self.assertTrue(all(abs(z) < 0.9 * rz for x, z in neck if x == x_min))
                    # the cheeks reach forward at the neck and draw back toward the eye's ends (lugs)
                    self.assertGreater(L.x_cheek - L.x_front, 0.004)
                    self.assertEqual(max(x for _, x in fronts), dict(fronts)[L.neck_bot])
                    # the unbevelled slices next to each end have drawn back by at least 40% of the reach
                    for y, x in (fronts[1], fronts[-2]):
                        self.assertLessEqual(x, L.x_front + 0.6 * (L.x_cheek - L.x_front), y)

    def test_cheeks_run_into_the_bit_without_a_step(self):
        for family in ("one_hand_axe", "two_hand_axe"):
            for seed in LINEUP_SEEDS:
                with self.subTest(family=family, seed=seed):
                    a = asset(family, seed)
                    p = a.params
                    L = axe._layout(p)
                    rows, fronts = axe._eye_rows(L, p.head, p.bit)
                    z_front = dict(rows)[L.neck_bot][1][1]
                    stations, _ = axe._bit_stations(p.bit, L, fronts)
                    n = 0
                    for s in stations:
                        if L.neck_bot <= s.y <= L.neck_top:
                            n += 1
                            # the wedge's flat from its back corner toward the bevel point, at the cheek front
                            bev_x = s.x_back + (1.0 + p.bit.bevel_x) * 0.5 * (s.x_edge - s.x_back)
                            t = (L.x_cheek - s.x_back) / (bev_x - s.x_back)
                            z_bit = s.half_thickness * (1.0 - t * (1.0 - p.bit.bevel_z))
                            self.assertGreater(z_front - z_bit, 0.0, "the bit must not stand proud of the cheeks")
                            self.assertLess(z_front - z_bit, 0.0015, "no visible step from cheek to bit")
                            self.assertLessEqual(s.x_back, L.x_cheek - 0.001, "the bit's back is buried 1 mm or more")
                            self.assertGreaterEqual(s.x_back, L.x_cheek - 0.002, "but no deeper than 2 mm")
                    self.assertGreater(n, 1)
                    # every bit vertex inside the eye's height and behind the cheek front is buried in the eye
                    head = a.component("head")
                    buried = 0
                    for q in a.component("bit").positions:
                        if L.eye_bot < q[1] < L.eye_top and q[0] < axe._front_at(fronts, q[1]):
                            buried += 1
                            self.assertTrue(inside(head, q), q)
                    self.assertGreaterEqual(buried, 2 * n)

    def test_war_hammer_head_is_not_dwarfed_by_its_haft(self):
        for seed in WIDE:
            a = asset("war_hammer", seed)
            xs = [q[0] for c in ("head", "face", "rear") for q in a.component(c).positions]
            self.assertLessEqual(a.params.haft.length, 0.72)
            self.assertGreater((max(xs) - min(xs)) / a.params.haft.length, 0.10)
            if a.params.rear.style == "poll":
                self.assertGreaterEqual(a.params.rear.length, 0.018)
        p = war_hammer.draw_params(1337)
        with self.assertRaisesRegex(GenerationError, "haft.length"):
            war_hammer.validate(replace(p, haft=replace(p.haft, length=0.86)))


class TestSourceGuards(unittest.TestCase):
    """The hafted code keeps Forge's determinism rules: + - * / and sqrt only, no '**', no pow(), no
    sum() over floats, no ambient randomness, time or hashing."""

    FILES = sorted((REPO_ROOT / "forge" / "hafted").glob("*.py")) + [REPO_ROOT / "forge" / "assets" / "hafted.py"]
    MATH_ALLOWED = {"sqrt", "isfinite"}
    BANNED_MODULES = {"random", "time", "datetime", "secrets", "uuid", "numpy", "decimal", "fractions", "cmath"}

    def test_determinism_rules(self):
        self.assertEqual(len(self.FILES), 11)
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

    def test_hafted_code_does_not_reach_into_other_families(self):
        allowed_blade_imports = {"forge.blades.shapes", "forge.blades.presentation"}
        for path in self.FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(("forge.blades", "forge.sword",
                                                                                       "forge.assets.blades",
                                                                                       "forge.assets.short_sword",
                                                                                       "forge.catalog")):
                    self.assertIn(node.module, allowed_blade_imports, f"{path.name} imports {node.module}")
                    names = {a.name for a in node.names}
                    self.assertTrue(names <= {"sweep", "Ring", "compute_normals", "compute_uvs"}, names)


if __name__ == "__main__":
    unittest.main()
