"""Step 2: normals, UVs, materials, and isolation from frozen geometry."""

import math
import unittest
from unittest import mock

from forge import generate_sword
from forge.errors import PresentationError, UnsupportedVersionError
from forge.hashing import geometry_sha256, materials_sha256, normals_sha256, uvs_sha256
from forge.presentation import (
    PRESENTATION_V1,
    PresentationVersions,
    derive_presentation,
)
from forge.presentation import materials as materials_mod
from forge.presentation.materials import PALETTES_V1, value_noise
from forge.presentation.normals import raw_face_normals
from forge.presentation.uv import diamond_angle
from forge.prng import stream_id
from forge.sword.v1 import STREAM_LABELS
from forge_test_support import float_bits
from step2_support import GOLDEN_1337, asset, presented

SEEDS = list(range(48)) + [1337, (1 << 64) - 1]


def corner_normals(comp):
    return [tuple(comp.normals[i] for i in tri) for tri in comp.normal_indices]


class TestNormals(unittest.TestCase):
    def test_1_normals_are_deterministic(self):
        for seed in (0, 1, 1337):
            a = derive_presentation(generate_sword(seed, 1), PRESENTATION_V1)
            b = derive_presentation(generate_sword(seed, 1), PRESENTATION_V1)
            self.assertEqual(normals_sha256(a), normals_sha256(b))
            self.assertEqual([c.normals for c in a.components], [c.normals for c in b.components])
            self.assertEqual([c.normal_indices for c in a.components], [c.normal_indices for c in b.components])

    def test_2_normals_are_finite(self):
        for seed in SEEDS:
            for comp in presented(seed).components:
                for n in comp.normals:
                    self.assertTrue(all(math.isfinite(c) for c in n), (seed, comp.name, n))

    def test_3_normals_are_unit_length(self):
        for seed in SEEDS:
            for comp in presented(seed).components:
                for n in comp.normals:
                    self.assertAlmostEqual(math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2), 1.0, delta=1e-12)

    def test_normals_point_outward_and_cover_every_corner(self):
        for seed in SEEDS[:16] + [1337]:
            p = presented(seed)
            for mesh, comp in zip(p.asset.components, p.components):
                self.assertEqual(len(comp.normal_indices), mesh.triangle_count)
                for face_n, corners in zip(raw_face_normals(mesh), corner_normals(comp)):
                    for n in corners:  # within the crease cone, so always on the face's outer side
                        self.assertGreater(n[0] * face_n[0] + n[1] * face_n[1] + n[2] * face_n[2], 0.0)

    def test_component_shading_modes(self):
        p = presented(1337)
        blade_mesh = p.asset.component("blade")
        blade = p.component("blade")
        # faceted: each triangle's three corners share one normal
        for tri in blade.normal_indices:
            self.assertEqual(len(set(tri)), 1)
        self.assertLessEqual(len(blade.normals), blade_mesh.triangle_count)
        # smoothed grip: fewer unique normals than corners, and corners of a triangle can differ
        grip = p.component("grip")
        self.assertTrue(any(len(set(tri)) > 1 for tri in grip.normal_indices))


class TestUVs(unittest.TestCase):
    def test_4_uvs_are_deterministic(self):
        for seed in (0, 1, 1337):
            a = derive_presentation(generate_sword(seed, 1), PRESENTATION_V1)
            b = derive_presentation(generate_sword(seed, 1), PRESENTATION_V1)
            self.assertEqual(uvs_sha256(a), uvs_sha256(b))

    def test_5_uvs_are_finite_in_unit_square_and_cover_every_corner(self):
        for seed in SEEDS:
            p = presented(seed)
            for mesh, comp in zip(p.asset.components, p.components):
                self.assertEqual(len(comp.uv_indices), mesh.triangle_count)
                for u, v in comp.uvs:
                    self.assertTrue(math.isfinite(u) and math.isfinite(v))
                    self.assertTrue(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0, (seed, comp.name, u, v))
                for tri in comp.uv_indices:
                    self.assertTrue(all(0 <= i < len(comp.uvs) for i in tri))

    def test_uv_triangles_are_not_collapsed(self):
        """Box/cylindrical mapping picks a projection per face, so no UV triangle is degenerate."""
        for seed in SEEDS[:16]:
            for comp in presented(seed).components:
                for tri in comp.uv_indices:
                    (u0, v0), (u1, v1), (u2, v2) = (comp.uvs[i] for i in tri)
                    self.assertGreater(abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)), 1e-9)

    def test_6_presentation_does_not_alter_geometry(self):
        for seed in (0, 7, 1337):
            fresh = generate_sword(seed, 1)
            before_bits = float_bits(fresh)
            before_tris = tuple(m.triangles for m in fresh.components)
            p = derive_presentation(fresh, PRESENTATION_V1)
            self.assertIs(p.asset, fresh)
            self.assertEqual(float_bits(fresh), before_bits)
            self.assertEqual(tuple(m.triangles for m in fresh.components), before_tris)
            self.assertEqual(geometry_sha256(fresh), geometry_sha256(generate_sword(seed, 1)))
        self.assertEqual(geometry_sha256(presented(1337).asset), GOLDEN_1337["geometry_sha256"])

    def test_diamond_angle(self):
        self.assertEqual(diamond_angle(1.0, 0.0), 0.0)
        self.assertEqual(diamond_angle(0.0, 1.0), 1.0)
        self.assertEqual(diamond_angle(-1.0, 0.0), 2.0)
        self.assertEqual(diamond_angle(0.0, -1.0), 3.0)
        prev = -1.0
        for x, z in ((1, 0.1), (1, 1), (0.1, 1), (-1, 1), (-1, -1), (1, -1), (1, -0.01)):
            a = diamond_angle(float(x), float(z))
            self.assertGreater(a, prev)  # monotonic counter-clockwise
            prev = a
        with self.assertRaises(PresentationError):
            diamond_angle(0.0, 0.0)


class TestMaterials(unittest.TestCase):
    def test_7_material_selection_is_deterministic(self):
        for seed in (0, 1, 1337, (1 << 64) - 1):
            a = materials_mod.select_materials(seed, 1)
            b = materials_mod.select_materials(seed, 1)
            self.assertEqual(a, b)
            self.assertEqual({k: m.to_dict() for k, m in a.items()}, {k: m.to_dict() for k, m in b.items()})

    def test_materials_cover_all_components_and_stay_in_bounds(self):
        seen = {name: set() for name in PALETTES_V1}
        for seed in range(200):
            mats = materials_mod.select_materials(seed, 1)
            self.assertEqual(sorted(mats), ["blade", "grip", "guard", "pommel"])
            for name, m in mats.items():
                materials_mod.validate_material(m)
                seen[name].add(m.preset)
                self.assertEqual(m.component, name)
            self.assertEqual(mats["blade"].metallic, 1.0)
            self.assertEqual(mats["grip"].metallic, 0.0)
            self.assertEqual(mats["grip"].pattern.kind, "wrap")
        for name, palette in PALETTES_V1.items():
            self.assertEqual(seen[name], {preset[0] for preset in palette}, f"{name} presets never all appear")

    def test_materials_vary_by_seed(self):
        digests = {materials_sha256(presented(s)) for s in range(32)}
        self.assertEqual(len(digests), 32)

    def test_material_sampling_is_deterministic_and_bounded(self):
        for comp in presented(1337).components:
            m = comp.material
            for u, v in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.123, 0.987)):
                c1, c2 = m.sample(u, v), m.sample(u, v)
                self.assertEqual(c1, c2)
                self.assertTrue(all(0.0 <= c <= 1.0 for c in c1))

    def test_value_noise(self):
        vals = [value_noise(x * 0.37, y * 0.53, 99) for x in range(-20, 20) for y in range(-5, 5)]
        self.assertTrue(all(0.0 <= v < 1.0 for v in vals))
        self.assertGreater(len(set(vals)), 300)
        self.assertEqual(value_noise(3.0, 4.0, 7), value_noise(3.0, 4.0, 7))
        self.assertAlmostEqual(value_noise(2.0, 2.0, 5), value_noise(2.0 + 1e-9, 2.0, 5), delta=1e-6)


class TestIsolation(unittest.TestCase):
    def test_8a_presentation_streams_never_touch_geometry_streams(self):
        labels = []
        real = materials_mod.derive_stream

        def spy(seed, label):
            labels.append(label)
            return real(seed, label)

        with mock.patch.object(materials_mod, "derive_stream", side_effect=spy):
            materials_mod.select_materials(1337, 1)
        self.assertEqual(len(labels), 4)
        self.assertTrue(all(lbl.startswith("forge.presentation.material.v1.") for lbl in labels))
        geometry_ids = {stream_id(lbl) for lbl in STREAM_LABELS.values()}
        self.assertTrue(geometry_ids.isdisjoint({stream_id(lbl) for lbl in labels}))

    def test_8b_deriving_presentation_does_not_shift_geometry(self):
        before = {s: float_bits(generate_sword(s, 1)) for s in (0, 1, 2, 1337)}
        for s in (0, 1, 2, 1337):
            derive_presentation(generate_sword(s, 1), PRESENTATION_V1)
        after = {s: float_bits(generate_sword(s, 1)) for s in (0, 1, 2, 1337)}
        self.assertEqual(before, after)

    def test_8c_materials_depend_only_on_seed(self):
        """Same seed -> same materials, whatever geometry object they're attached to."""
        a = presented(42).materials
        self.assertEqual(materials_mod.select_materials(42, 1)["blade"].to_dict(), a["blade"])
        with mock.patch("forge.sword.v1.draw_params", side_effect=AssertionError("geometry was consulted")):
            self.assertEqual({k: m.to_dict() for k, m in materials_mod.select_materials(42, 1).items()}, a)

    def test_golden_presentation_v1(self):
        p = presented(1337)
        self.assertEqual(normals_sha256(p), GOLDEN_1337["normals_sha256"])
        self.assertEqual(uvs_sha256(p), GOLDEN_1337["uvs_sha256"])
        self.assertEqual(materials_sha256(p), GOLDEN_1337["materials_sha256"])


class TestVersions(unittest.TestCase):
    def test_unsupported_presentation_versions_refuse(self):
        a = asset(1)
        for bad in (PresentationVersions(2, 1, 1, 1), PresentationVersions(1, 2, 1, 1),
                    PresentationVersions(1, 1, 2, 1), PresentationVersions(1, 1, 1, 2),
                    PresentationVersions(True, 1, 1, 1), PresentationVersions(1, 1.0, 1, 1),
                    PresentationVersions(1, 1, "1", 1), PresentationVersions(1, 1, 1, None)):
            with self.subTest(versions=bad):
                with self.assertRaises(UnsupportedVersionError) as ctx:
                    derive_presentation(a, bad)
                self.assertIn("unsupported", str(ctx.exception))

    def test_versions_must_be_explicit(self):
        with self.assertRaises(TypeError):
            derive_presentation(asset(1))  # no implicit "latest"
        with self.assertRaises(PresentationError):
            derive_presentation(asset(1), {"presentation_version": 1})
        with self.assertRaises(PresentationError):
            derive_presentation("not an asset", PRESENTATION_V1)


if __name__ == "__main__":
    unittest.main()
