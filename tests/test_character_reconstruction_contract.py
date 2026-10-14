import dataclasses
import inspect
import tempfile
import unittest
from pathlib import Path

from forge_character_studio.integrations import CharacterDNA, ReconstructionProvider


class CharacterDNAContractTests(unittest.TestCase):
    def test_character_dna_wraps_a_recipe_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            dna = CharacterDNA("forge.character-recipe", 3, Path(tmp) / "r.json")
            self.assertEqual(dna.contract_id, "forge.character-recipe")
            self.assertEqual(dna.contract_version, 3)
            self.assertEqual(dna.recipe_path, Path(tmp) / "r.json")

    def test_character_dna_is_frozen(self):
        dna = CharacterDNA("forge.character-recipe", 3, Path("r.json"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dna.contract_version = 4

    def test_reconstruction_provider_protocol_still_a_protocol_boundary(self):
        # architecture guard: no concrete implementation ships in this module
        self.assertTrue(
            inspect.isabstract(ReconstructionProvider)
            or hasattr(ReconstructionProvider, "_is_protocol")
        )


if __name__ == "__main__":
    unittest.main()
