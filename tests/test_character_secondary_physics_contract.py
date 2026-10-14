import unittest

from forge_character_studio.secondary_physics import (
    REGION_KINDS,
    PhysicsRegion,
    SecondaryPhysicsContract,
)

CONTRACT_ID = "forge.character-secondary-physics"


class CharacterSecondaryPhysicsContractTests(unittest.TestCase):
    def test_valid_contract_builds(self):
        region = PhysicsRegion("chest_soft", (10, 11, 12), "soft_body")
        contract = SecondaryPhysicsContract(CONTRACT_ID, 1, (region,))
        self.assertEqual(contract.contract_id, CONTRACT_ID)
        self.assertEqual(contract.contract_version, 1)
        self.assertEqual(contract.regions[0].region_kind, "soft_body")

    def test_region_kinds_are_soft_body_and_collision_volume(self):
        self.assertEqual(REGION_KINDS, ("soft_body", "collision_volume"))

    def test_rejects_unknown_region_kind(self):
        with self.assertRaises(ValueError):
            PhysicsRegion("x", (1,), "rigid_body")

    def test_rejects_duplicate_region_names(self):
        region = PhysicsRegion("chest_soft", (1,), "soft_body")
        with self.assertRaises(ValueError):
            SecondaryPhysicsContract(CONTRACT_ID, 1, (region, region))

    def test_rejects_empty_attachment_indices(self):
        with self.assertRaises(ValueError):
            PhysicsRegion("x", (), "soft_body")


if __name__ == "__main__":
    unittest.main()
