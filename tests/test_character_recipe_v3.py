import json
import tempfile
import unittest
from pathlib import Path

from forge_character_studio.generate import generate_character
from forge_character_studio.model import CharacterParameters
from forge_character_studio.provenance import BaseMeshRef
from forge_character_studio.recipe import (
    RECIPE_CONTRACT_VERSION_V3,
    load_recipe,
    load_recipe_v3,
    recipe_data_v3,
    save_recipe,
    save_recipe_v3,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_V1 = ROOT / "examples" / "character_step6a_seed1337" / "character.recipe.json"
SHA = "ab" * 32


class TestRecipeV3(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.asset = generate_character(7)
        self.base_mesh = BaseMeshRef(source_name="demo-base", version="1.0", archive_sha256=SHA)

    def tearDown(self):
        self._tmp.cleanup()

    def test_recipe_v3_round_trips(self):
        path = save_recipe_v3(self.asset, self.base_mesh, "4.2.3", self.tmp_path / "r.json")
        asset, base_mesh, blender_build = load_recipe_v3(path)
        self.assertEqual(asset, self.asset)
        self.assertEqual(base_mesh, self.base_mesh)
        self.assertIsInstance(base_mesh, BaseMeshRef)
        self.assertEqual(blender_build, "4.2.3")

    def test_recipe_v3_contract_and_pipeline_sections(self):
        data = recipe_data_v3(self.asset, self.base_mesh, "4.2.3")
        self.assertEqual(RECIPE_CONTRACT_VERSION_V3, 3)
        self.assertEqual(data["contract"], {"id": "forge.character-recipe", "version": 3})
        self.assertEqual(data["pipeline"], {
            "base_mesh": {"source_name": "demo-base", "version": "1.0", "archive_sha256": SHA},
            "blender_build": "4.2.3",
        })

    def test_recipe_v3_is_additive_over_v2_sections(self):
        data = recipe_data_v3(self.asset, self.base_mesh, "4.2.3")
        self.assertEqual(data["generator"], {"id": "forge.character.humanoid-base", "version": self.asset.generator_version})
        self.assertEqual(set(data), {"contract", "generator", "body_plan_id", "seed", "parameters", "integrity", "pipeline"})

    def test_recipe_v2_still_loads_unchanged(self):
        # existing v1/v2 save/load path must be untouched by this task
        v1_asset = load_recipe(DEMO_V1)
        self.assertEqual(v1_asset.generator_version, 1)
        v2_asset = generate_character(7, CharacterParameters(), 2)
        self.assertEqual(v2_asset.generator_version, 2)
        path = save_recipe(v2_asset, self.tmp_path / "v2.json")
        loaded = load_recipe(path)
        self.assertEqual(loaded.generator_version, 2)
        self.assertEqual(loaded, v2_asset)

    def test_recipe_v3_rejects_missing_pipeline_section(self):
        path = self.tmp_path / "bad.json"
        path.write_text('{"contract": {"id": "forge.character-recipe", "version": 3}}')
        with self.assertRaises(ValueError):
            load_recipe_v3(path)

    def test_recipe_v3_rejects_bad_base_mesh_digest(self):
        data = recipe_data_v3(self.asset, self.base_mesh, "4.2.3")
        data["pipeline"]["base_mesh"]["archive_sha256"] = "NOT-A-DIGEST"
        path = self.tmp_path / "bad_sha.json"
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            load_recipe_v3(path)

    def test_recipe_v3_rejects_extra_base_mesh_field(self):
        data = recipe_data_v3(self.asset, self.base_mesh, "4.2.3")
        data["pipeline"]["base_mesh"]["license_id"] = "CC0-1.0"
        path = self.tmp_path / "extra.json"
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            load_recipe_v3(path)

    def test_recipe_v3_rejects_non_json_path(self):
        with self.assertRaises(ValueError):
            save_recipe_v3(self.asset, self.base_mesh, "4.2.3", self.tmp_path / "r.txt")


if __name__ == "__main__":
    unittest.main()
