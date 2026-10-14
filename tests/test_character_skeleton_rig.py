import unittest

from forge_character_studio.skeleton_rig import BoneJoint, SkeletonRig, VertexWeights

IDENTITY_4X4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
CONTRACT_ID = "forge.character-skeleton-rig"


class CharacterSkeletonRigTests(unittest.TestCase):
    def test_valid_rig_constructs(self):
        root = BoneJoint("root", None, IDENTITY_4X4)
        child = BoneJoint("spine", "root", IDENTITY_4X4)
        weights = VertexWeights((0, 1, 0, 0), (0.7, 0.3, 0.0, 0.0))
        rig = SkeletonRig(CONTRACT_ID, 1, (root, child), (weights,))
        self.assertEqual(rig.bones[1].parent, "root")

    def test_rejects_weights_not_summing_to_one(self):
        with self.assertRaises(ValueError):
            VertexWeights((0, 1, 0, 0), (0.5, 0.2, 0.0, 0.0))

    def test_rejects_negative_weight(self):
        with self.assertRaises(ValueError):
            VertexWeights((0, 1, 0, 0), (1.2, -0.2, 0.0, 0.0))

    def test_rejects_unknown_parent_reference(self):
        with self.assertRaises(ValueError):
            SkeletonRig(CONTRACT_ID, 1,
                        (BoneJoint("a", "nonexistent", IDENTITY_4X4),), ())

    def test_rejects_cyclic_parent_chain(self):
        with self.assertRaises(ValueError):
            SkeletonRig(CONTRACT_ID, 1,
                        (BoneJoint("a", "b", IDENTITY_4X4), BoneJoint("b", "a", IDENTITY_4X4)), ())

    def test_rejects_self_parent(self):
        with self.assertRaises(ValueError):
            SkeletonRig(CONTRACT_ID, 1,
                        (BoneJoint("a", "a", IDENTITY_4X4),), ())

    def test_rejects_duplicate_bone_names_hiding_a_cycle(self):
        # The real pair x<->y is cyclic; the shadowing pair reuses the names with no parent.
        with self.assertRaises(ValueError):
            SkeletonRig(CONTRACT_ID, 1,
                        (BoneJoint("x", "y", IDENTITY_4X4),
                         BoneJoint("y", "x", IDENTITY_4X4),
                         BoneJoint("x", None, IDENTITY_4X4),
                         BoneJoint("y", None, IDENTITY_4X4)), ())

    def test_rejects_nan_weight(self):
        with self.assertRaises(ValueError):
            VertexWeights((0, 1, 0, 0), (float("nan"), 0.5, 0.5, 0.0))


if __name__ == "__main__":
    unittest.main()
