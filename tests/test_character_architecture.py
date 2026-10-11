import ast
import unittest
from pathlib import Path

from forge_character_studio.generate import generate_character
from forge_character_studio.integrations import MotionStudioBridge, ReconstructionProvider
from forge_character_studio.presentation import present_character

ROOT = Path(__file__).resolve().parents[1]


class TestCharacterArchitecture(unittest.TestCase):
    def test_character_code_does_not_modify_weapon_packages(self):
        for path in (ROOT / "forge_character_studio").rglob("*.py"):
            imports = []
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
            self.assertFalse(any(name.startswith(("forge.sword", "forge.hafted", "forge.assets")) for name in imports), path)

    def test_presentation_is_compatible_with_existing_renderer(self):
        presented = present_character(generate_character(11))
        self.assertEqual(presented.asset.asset_type, "character")
        self.assertEqual(tuple(c.name for c in presented.components), ("body",))

    def test_future_integrations_are_protocol_boundaries(self):
        self.assertTrue(hasattr(ReconstructionProvider, "reconstruct"))
        self.assertTrue(hasattr(MotionStudioBridge, "accept_character"))

    def test_no_motion_studio_implementation_is_present(self):
        names = {p.name.lower() for p in (ROOT / "forge_character_studio").iterdir()}
        self.assertNotIn("motion_studio.py", names)


if __name__ == "__main__":
    unittest.main()
