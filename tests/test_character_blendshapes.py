import unittest

from forge_character_studio.blendshapes import BlendShape, BlendShapeSet, build_blend_shape_set

ZERO_DELTA = (0.0, 0.0, 0.0)


class CharacterBlendShapesTests(unittest.TestCase):
    def test_valid_set_builds(self):
        shape = BlendShape("left_elbow_bend", "left_elbow", 0.0, 95.0, (ZERO_DELTA,) * 10)
        bss = build_blend_shape_set(10, (shape,))
        self.assertIsInstance(bss, BlendShapeSet)
        self.assertEqual(bss.contract_id, "forge.character-blendshapes")
        self.assertEqual(bss.contract_version, 1)
        self.assertEqual(bss.shapes[0].name, "left_elbow_bend")

    def test_rejects_mismatched_vertex_delta_count(self):
        shape = BlendShape("x", "left_elbow", 0.0, 95.0, (ZERO_DELTA,) * 5)
        with self.assertRaises(ValueError):
            build_blend_shape_set(10, (shape,))

    def test_rejects_min_not_less_than_max(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "left_elbow", 95.0, 0.0, (ZERO_DELTA,))

    def test_rejects_equal_min_and_max(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "left_elbow", 45.0, 45.0, (ZERO_DELTA,))

    def test_rejects_non_finite_delta(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "left_elbow", 0.0, 95.0, ((float("nan"), 0.0, 0.0),))

    def test_rejects_infinite_delta(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "left_elbow", 0.0, 95.0, ((float("inf"), 0.0, 0.0),))

    def test_rejects_empty_driven_by(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "", 0.0, 95.0, (ZERO_DELTA,))

    def test_rejects_non_numeric_delta_component(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "left_elbow", 0.0, 95.0, (("0.0", 0.0, 0.0),))

    def test_rejects_non_finite_angle(self):
        with self.assertRaises(ValueError):
            BlendShape("x", "left_elbow", float("nan"), 95.0, (ZERO_DELTA,))

    def test_empty_deltas_match_zero_vertex_count(self):
        shape = BlendShape("x", "left_elbow", 0.0, 95.0, ())
        bss = build_blend_shape_set(0, (shape,))
        self.assertEqual(bss.shapes[0].vertex_deltas, ())

    def test_rejects_negative_base_vertex_count(self):
        with self.assertRaises(ValueError):
            build_blend_shape_set(-1, ())


if __name__ == "__main__":
    unittest.main()
