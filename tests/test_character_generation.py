import unittest

from forge.errors import GeometryError
from forge.mesh import check_closed_oriented
from forge_character_studio.generate import generate_character
from forge_character_studio.model import CharacterParameters
from forge_character_studio.recipe import mesh_sha256


class TestCharacterGeneration(unittest.TestCase):
    def test_same_recipe_is_bit_deterministic(self):
        a = generate_character(1337)
        b = generate_character(1337)
        self.assertEqual(a.body.positions, b.body.positions)
        self.assertEqual(a.body.triangles, b.body.triangles)
        self.assertEqual(mesh_sha256(a), mesh_sha256(b))

    def test_seed_is_a_deterministic_morphology_input(self):
        self.assertNotEqual(mesh_sha256(generate_character(1)), mesh_sha256(generate_character(2)))

    def test_mesh_is_one_closed_outward_connected_surface(self):
        asset = generate_character(7)
        self.assertEqual(asset.component_names, ("body",))
        check_closed_oriented(asset.body)
        self.assertGreater(asset.body.signed_volume(), 0.0)

    def test_mesh_has_prototype_level_density(self):
        mesh = generate_character(7).body
        self.assertGreater(mesh.vertex_count, 4000)
        self.assertGreater(mesh.triangle_count, 8000)

    def test_height_control_changes_bounds(self):
        short = generate_character(7, CharacterParameters(height_m=1.4))
        tall = generate_character(7, CharacterParameters(height_m=2.1))
        sy = short.body.bounds()[1][1] - short.body.bounds()[0][1]
        ty = tall.body.bounds()[1][1] - tall.body.bounds()[0][1]
        self.assertGreater(ty, sy * 1.4)

    def test_each_requested_morphology_control_changes_geometry(self):
        base = mesh_sha256(generate_character(99))
        fields = ("torso_scale", "chest_scale", "waist_scale", "hip_scale", "arm_scale", "leg_scale")
        for field in fields:
            with self.subTest(field=field):
                values = CharacterParameters().__dict__.copy()
                values[field] = 1.2
                changed = generate_character(99, CharacterParameters(**values))
                self.assertNotEqual(base, mesh_sha256(changed))

    def test_parameter_bounds_fail_loudly(self):
        with self.assertRaises(GeometryError):
            CharacterParameters(height_m=0.5)
        with self.assertRaises(GeometryError):
            CharacterParameters(arm_scale=2.0)

    def test_extreme_supported_proportions_remain_valid(self):
        p = CharacterParameters(1.8, 1.35, 1.4, 0.72, 1.35, 1.3, 1.25)
        check_closed_oriented(generate_character(42, p).body)


if __name__ == "__main__":
    unittest.main()
