"""Structural correctness of generated geometry and of the validation that guards it."""

import dataclasses
import math
import unittest

from forge import GenerationError, GeometryError, generate_sword
from forge.mesh import Mesh, check_closed_oriented
from forge.primitives import Station, loft, unit_circle
from forge.sword import COMPONENT_ORDER, SwordAsset
from forge.sword.params import (
    BLADE_BOUNDS,
    GRIP_BOUNDS,
    GRIP_SEGMENTS,
    GUARD_BOUNDS,
    GUARD_SHAPES,
    POINT_LENGTH_RATIO,
    POINT_SHAPES,
    POMMEL_BOUNDS,
    POMMEL_SHAPES,
)
from forge_test_support import VERSION

TOL = 1e-12  # meters; components meet within 1 picometer
SAMPLE_SEEDS = list(range(256)) + [1337, (1 << 64) - 1]


def _assets():
    return [generate_sword(s, VERSION) for s in SAMPLE_SEEDS]


class TestGeneratedGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = _assets()

    def test_has_all_required_components_in_order(self):
        for a in self.assets:
            self.assertEqual(a.component_names, ("blade", "guard", "grip", "pommel"))
            self.assertEqual(a.component_names, COMPONENT_ORDER)

    def test_contains_vertices_and_faces(self):
        for a in self.assets:
            for m in a.components:
                self.assertGreater(m.vertex_count, 0, m.name)
                self.assertGreater(m.triangle_count, 0, m.name)

    def test_all_face_indices_are_valid(self):
        for a in self.assets:
            for m in a.components:
                n = m.vertex_count
                for tri in m.triangles:
                    self.assertEqual(len(tri), 3)
                    for i in tri:
                        self.assertIs(type(i), int)
                        self.assertTrue(0 <= i < n, (a.seed, m.name, tri))

    def test_all_coordinates_are_finite_floats(self):
        for a in self.assets:
            for m in a.components:
                for p in m.positions:
                    for c in p:
                        self.assertIs(type(c), float)
                        self.assertTrue(math.isfinite(c), (a.seed, m.name, p))

    def test_every_component_is_a_closed_outward_shell(self):
        for a in self.assets:
            for m in a.components:
                check_closed_oriented(m)  # raises on failure
                self.assertGreater(m.signed_volume(), 0.0)

    def test_parameters_within_documented_bounds(self):
        for a in self.assets:
            p = a.params
            p.validate()
            for part, table in ((p.blade, BLADE_BOUNDS), (p.guard, GUARD_BOUNDS),
                                (p.grip, GRIP_BOUNDS), (p.pommel, POMMEL_BOUNDS)):
                for key, (lo, hi) in table.items():
                    v = getattr(part, key)
                    self.assertTrue(lo <= v <= hi, f"seed {a.seed}: {key}={v} outside [{lo}, {hi}]")
            self.assertIn(p.blade.point_shape, POINT_SHAPES)
            lo, hi = POINT_LENGTH_RATIO[p.blade.point_shape]
            self.assertTrue(lo <= p.blade.point_length_ratio <= hi)
            self.assertIn(p.guard.shape, GUARD_SHAPES)
            self.assertIn(p.pommel.shape, POMMEL_SHAPES)
            self.assertTrue(GRIP_SEGMENTS[0] <= p.grip.segments <= GRIP_SEGMENTS[1])
            self.assertTrue(0.531 - TOL <= p.total_length <= 0.760 + TOL, p.total_length)

    def test_geometry_dimensions_match_parameters(self):
        for a in self.assets:
            p = a.params
            (bx0, by0, bz0), (bx1, by1, bz1) = a.component("blade").bounds()
            (gx0, gy0, gz0), (gx1, gy1, gz1) = a.component("guard").bounds()
            (hx0, hy0, hz0), (hx1, hy1, hz1) = a.component("grip").bounds()
            (px0, py0, pz0), (px1, py1, pz1) = a.component("pommel").bounds()
            with self.subTest(seed=a.seed):
                # blade: width along X, thickness along Z, length along +Y
                self.assertAlmostEqual(bx1 - bx0, p.blade.base_width, delta=TOL)
                self.assertAlmostEqual(bz1 - bz0, p.blade.thickness, delta=TOL)
                self.assertAlmostEqual(by1 - by0, p.blade.length, delta=TOL)
                # guard
                self.assertAlmostEqual(gx1 - gx0, p.guard.width, delta=TOL)
                self.assertAlmostEqual(gy1 - gy0, p.guard.thickness, delta=TOL)
                self.assertAlmostEqual(gz1 - gz0, p.guard.depth, delta=TOL)
                # grip: centered on the origin
                self.assertEqual(hy0, -p.grip.length * 0.5)
                self.assertEqual(hy1, p.grip.length * 0.5)
                self.assertTrue(p.grip.radius - TOL <= hx1 <= p.grip.radius * (1.0 + p.grip.swell) + TOL)
                # pommel
                self.assertAlmostEqual(py1 - py0, p.pommel.height, delta=TOL)
                self.assertAlmostEqual(px1, p.pommel.radius, delta=TOL)
                # stacking: pommel | grip | guard | blade, touching, no gaps or overlaps
                self.assertAlmostEqual(py1, hy0, delta=TOL)
                self.assertAlmostEqual(hy1, gy0, delta=TOL)
                self.assertAlmostEqual(gy1, by0, delta=TOL)
                # whole sword
                (_, y0, _), (_, y1, _) = a.bounds()
                self.assertAlmostEqual(y1 - y0, p.total_length, delta=4 * TOL)

    def test_sword_is_centered_on_axis_and_tip_points_up(self):
        for a in self.assets:
            blade = a.component("blade")
            tip = max(blade.positions, key=lambda q: q[1])
            self.assertEqual((tip[0], tip[2]), (0.0, 0.0))
            for m in a.components:
                (x0, _, z0), (x1, _, z1) = m.bounds()
                self.assertAlmostEqual(x0, -x1, delta=TOL, msg=m.name)
                self.assertAlmostEqual(z0, -z1, delta=TOL, msg=m.name)

    def test_asset_is_immutable(self):
        a = self.assets[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.seed = 5
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.params.blade.length = 1.0
        self.assertIsInstance(a.components, tuple)
        self.assertIsInstance(a.components[0].positions, tuple)

    def test_component_lookup(self):
        a = self.assets[0]
        self.assertEqual(a.component("pommel").name, "pommel")
        with self.assertRaises(KeyError):
            a.component("scabbard")


# A valid, outward-wound unit tetrahedron used to exercise validation.
TET_P = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
TET_F = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))


class TestMeshValidationFailsLoudly(unittest.TestCase):
    def test_valid_tetrahedron(self):
        m = Mesh("tet", TET_P, TET_F)
        check_closed_oriented(m)
        self.assertAlmostEqual(m.signed_volume(), 1.0 / 6.0)

    def test_rejects_corrupt_meshes(self):
        nan, inf = float("nan"), float("inf")
        cases = {
            "index out of range": (TET_P, TET_F[:3] + ((1, 2, 4),)),
            "negative index": (TET_P, TET_F[:3] + ((1, 2, -1),)),
            "non-int index": (TET_P, TET_F[:3] + ((1, 2, 3.0),)),
            "NaN coordinate": (TET_P[:3] + ((0.0, nan, 1.0),), TET_F),
            "infinite coordinate": (TET_P[:3] + ((0.0, 0.0, inf),), TET_F),
            "int coordinate": (TET_P[:3] + ((0, 0, 1),), TET_F),
            "repeated index": (TET_P, TET_F[:3] + ((1, 1, 3),)),
            "degenerate face": (TET_P[:3] + ((2.0, 0.0, 0.0),), ((0, 1, 3), (0, 2, 1))),
            "unreferenced vertex": (TET_P + ((5.0, 5.0, 5.0),), TET_F),
            "no vertices": ((), ()),
            "no faces": (TET_P, ()),
            "list not tuple": (list(TET_P), TET_F),
            "2-index face": (TET_P, TET_F[:3] + ((1, 2),)),
        }
        for label, (pos, tris) in cases.items():
            with self.subTest(label):
                with self.assertRaises(GeometryError):
                    Mesh("bad", pos, tris)

    def test_rejects_bad_names(self):
        for name in ("", "1blade", "has space", "blade\n", None):
            with self.subTest(name=name):
                with self.assertRaises(GeometryError):
                    Mesh(name, TET_P, TET_F)

    def test_closed_shell_check_catches_open_and_flipped(self):
        open_mesh = Mesh("open", TET_P, TET_F[:3])
        with self.assertRaises(GeometryError):
            check_closed_oriented(open_mesh)
        flipped = Mesh("flipped", TET_P, TET_F[:3] + ((1, 3, 2),))
        with self.assertRaises(GeometryError):
            check_closed_oriented(flipped)
        inside_out = Mesh("inside_out", TET_P, tuple((a, c, b) for a, b, c in TET_F))
        with self.assertRaises(GeometryError):
            check_closed_oriented(inside_out)

    def test_primitives_validate_inputs(self):
        with self.assertRaises(GeometryError):
            unit_circle(5)
        with self.assertRaises(GeometryError):
            loft("x", unit_circle(8), [Station(1.0, 1.0, 1.0), Station(0.5, 1.0, 1.0)], 0.0, 2.0)
        with self.assertRaises(GeometryError):
            loft("x", unit_circle(8), [Station(0.0, 0.0, 1.0)], 0.0, 1.0)

    def test_unit_circles_are_exactly_symmetric(self):
        for n in (4, 8, 12, 16):
            pts = unit_circle(n)
            self.assertEqual(len(pts), n)
            self.assertEqual(pts[0], (1.0, 0.0))
            for x, z in pts:
                self.assertAlmostEqual(x * x + z * z, 1.0, delta=4e-16)
            for k in range(n):  # point k and point k + n/2 are exact negatives
                x, z = pts[k]
                ox, oz = pts[(k + n // 2) % n]
                self.assertEqual((x, z), (0.0 - ox, 0.0 - oz))


class TestParameterValidationFailsLoudly(unittest.TestCase):
    def setUp(self):
        self.params = generate_sword(1337, VERSION).params

    def _with(self, part, **changes):
        return dataclasses.replace(self.params, **{part: dataclasses.replace(getattr(self.params, part), **changes)})

    def test_out_of_bounds_values_are_rejected(self):
        bad = [
            ("blade", {"length": 0.70}), ("blade", {"thickness": 0.0}), ("blade", {"taper": float("nan")}),
            ("blade", {"point_shape": "hook"}), ("blade", {"point_length_ratio": 0.5}),
            ("guard", {"width": 0.01}), ("guard", {"shape": "basket"}),
            ("grip", {"segments": 6}), ("grip", {"segments": 3.0}), ("grip", {"radius": 1}),
            ("pommel", {"height": -0.02}), ("pommel", {"shape": None}),
        ]
        for part, change in bad:
            with self.subTest(part=part, change=change):
                with self.assertRaises(GenerationError):
                    self._with(part, **change).validate()

    def test_asset_rejects_missing_or_misordered_components(self):
        a = generate_sword(1337, VERSION)
        with self.assertRaises(GenerationError):
            SwordAsset(a.seed, a.generator_version, a.params, a.components[:3])
        with self.assertRaises(GenerationError):
            SwordAsset(a.seed, a.generator_version, a.params, tuple(reversed(a.components)))


if __name__ == "__main__":
    unittest.main()
