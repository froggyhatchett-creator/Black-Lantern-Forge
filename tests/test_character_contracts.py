import hashlib
import json
import unittest
from pathlib import Path

from forge_character_studio.generate import generate_character
from forge_character_studio.glb import character_glb
from forge_character_studio.model import CharacterParameters
from forge_character_studio.recipe import load_recipe, mesh_sha256, recipe_data
from forge_character_studio.validate_glb import CharacterGlbError, validate_character_glb_bytes

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "character_step6a_seed1337"


class TestRecipeContract(unittest.TestCase):
    def test_recipe_is_explicit_and_versioned(self):
        data = recipe_data(generate_character(5))
        self.assertEqual(data["contract"], {"id": "forge.character-recipe", "version": 2})
        self.assertEqual(data["generator"], {"id": "forge.character.humanoid-base", "version": 2})
        self.assertEqual(data["body_plan_id"], "humanoid.neutral.v2")

    def test_demo_recipe_regenerates_exact_mesh(self):
        asset = load_recipe(DEMO / "character.recipe.json")
        stored = json.loads((DEMO / "character.recipe.json").read_text(encoding="utf-8"))
        self.assertEqual(mesh_sha256(asset), stored["integrity"]["mesh_sha256"])

    def test_unknown_parameter_is_refused(self):
        data = CharacterParameters().to_dict()
        data["species"] = "hardcoded"
        with self.assertRaises(Exception):
            CharacterParameters.from_dict(data)


class TestCharacterGlbContract(unittest.TestCase):
    def test_glb_is_deterministic(self):
        a = character_glb(generate_character(1337))
        b = character_glb(generate_character(1337))
        self.assertEqual(hashlib.sha256(a).digest(), hashlib.sha256(b).digest())

    def test_independent_validator_accepts_generated_glb(self):
        result = validate_character_glb_bytes(character_glb(generate_character(1337)))
        self.assertEqual(result["contract"], {"id": "forge.character-mesh", "version": 2})
        self.assertGreater(result["vertices"], 4000)
        self.assertGreater(result["triangles"], 8000)

    def test_independent_validator_accepts_demo(self):
        result = validate_character_glb_bytes((DEMO / "character.glb").read_bytes())
        self.assertEqual((result["vertices"], result["triangles"]), (6366, 12728))

    def test_corrupt_glb_is_refused(self):
        data = bytearray(character_glb(generate_character(3)))
        data[0] ^= 0xFF
        with self.assertRaises(CharacterGlbError):
            validate_character_glb_bytes(bytes(data))

    def test_validator_has_no_generator_dependency(self):
        source = (ROOT / "forge_character_studio" / "validate_glb.py").read_text(encoding="utf-8")
        self.assertNotIn("forge_character_studio.generate", source)
        self.assertNotIn("forge_character_studio.model", source)


if __name__ == "__main__":
    unittest.main()
