import json
import unittest
from pathlib import Path

from forge.mesh import check_closed_oriented
from forge_character_studio.diagnostics import deformation_diagnostics, joint_topology_diagnostics, surface_quality
from forge_character_studio.generate import generate_character
from forge_character_studio.glb import character_glb
from forge_character_studio.model import CharacterParameters
from forge_character_studio.recipe import load_recipe, mesh_sha256, save_recipe
from forge_character_studio.skeleton import SKELETON_CONTRACT_ID, build_skeleton
from forge_character_studio.validate_glb import validate_character_glb_bytes

ROOT = Path(__file__).resolve().parents[1]


class TestStep6BAnatomy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asset = generate_character(1337)

    def test_surface_is_closed_connected_genus_zero(self):
        check_closed_oriented(self.asset.body)
        self.assertEqual(surface_quality(self.asset)["euler_characteristic"], 2)

    def test_surface_has_nontrivial_anatomical_depth(self):
        lo, hi = self.asset.body.bounds()
        self.assertGreater(hi[2] - lo[2], .25)
        self.assertGreater(hi[1] - lo[1], 1.6)

    def test_joint_regions_have_dense_radial_support(self):
        for diagnostic in joint_topology_diagnostics(self.asset):
            with self.subTest(joint=diagnostic.joint):
                self.assertGreaterEqual(diagnostic.nearby_vertices, 100)
                self.assertGreaterEqual(diagnostic.radial_rings, 4)
                self.assertLess(diagnostic.max_normalized_gap, .05)

    def test_canonical_deformation_diagnostics_pass(self):
        report = deformation_diagnostics(self.asset)
        self.assertEqual(set(report), {"arm_raise", "elbow_bend", "knee_bend", "hip_rotation"})
        self.assertTrue(all(item["passes"] for item in report.values()))

    def test_skeleton_landmark_contract_is_complete(self):
        skeleton = build_skeleton(self.asset.parameters)
        self.assertEqual(skeleton.contract_id, SKELETON_CONTRACT_ID)
        names = set(skeleton.by_name())
        for required in ("root", "spine_lower", "spine_chest", "neck", "head", "left_shoulder",
                         "right_wrist", "left_hip", "right_knee", "left_foot"):
            self.assertIn(required, names)
        self.assertGreaterEqual(len(names), 21)

    def test_v2_glb_embeds_valid_landmarks(self):
        result = validate_character_glb_bytes(character_glb(self.asset))
        self.assertEqual(result["contract"]["version"], 2)

    def test_subdivision_is_configurable_and_stable(self):
        low = generate_character(8, CharacterParameters(subdivision=0))
        high = generate_character(8, CharacterParameters(subdivision=1))
        self.assertGreater(high.body.vertex_count, low.body.vertex_count * 1.35)
        check_closed_oriented(low.body)

    def test_asymmetry_changes_one_sided_landmarks_and_geometry(self):
        symmetric = CharacterParameters(subdivision=0)
        asymmetric = CharacterParameters(left_arm_scale=1.25, symmetry=0.0, subdivision=0)
        a = build_skeleton(symmetric).by_name()
        b = build_skeleton(asymmetric).by_name()
        self.assertNotEqual(a["left_wrist"].position, b["left_wrist"].position)
        self.assertEqual(a["right_wrist"].position, b["right_wrist"].position)
        self.assertNotEqual(mesh_sha256(generate_character(9, symmetric)), mesh_sha256(generate_character(9, asymmetric)))

    def test_v1_recipe_remains_exactly_reproducible(self):
        path = ROOT / "examples" / "character_step6a_seed1337" / "character.recipe.json"
        expected = json.loads(path.read_text(encoding="utf-8"))["integrity"]["mesh_sha256"]
        self.assertEqual(mesh_sha256(load_recipe(path)), expected)

    def test_v2_recipe_round_trip(self):
        path = ROOT / "tests" / "_step6b_roundtrip.recipe.json"
        try:
            save_recipe(self.asset, path)
            self.assertEqual(mesh_sha256(load_recipe(path)), mesh_sha256(self.asset))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
