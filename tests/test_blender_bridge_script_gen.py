import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from forge_character_studio.blender_bridge.script_gen import generate_deform_script
from forge_character_studio.generate import generate_character


class BlenderDeformScriptGenTests(unittest.TestCase):
    def setUp(self):
        self.demo_asset = generate_character(1234)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def test_script_is_deterministic_for_same_inputs(self):
        base = self.tmp_path / "base.blend"
        out = self.tmp_path / "out.glb"
        a = generate_deform_script(self.demo_asset, base, out)
        b = generate_deform_script(self.demo_asset, base, out)
        self.assertIsInstance(a, str)
        self.assertEqual(a, b)

    def test_script_differs_for_different_seed(self):
        other = replace(self.demo_asset, seed=self.demo_asset.seed + 1)
        base = self.tmp_path / "base.blend"
        out = self.tmp_path / "out.glb"
        a = generate_deform_script(self.demo_asset, base, out)
        b = generate_deform_script(other, base, out)
        self.assertNotEqual(a, b)

    def test_script_differs_for_different_parameters(self):
        other = replace(self.demo_asset, parameters=replace(self.demo_asset.parameters, height_m=1.80))
        base = self.tmp_path / "base.blend"
        out = self.tmp_path / "out.glb"
        a = generate_deform_script(self.demo_asset, base, out)
        b = generate_deform_script(other, base, out)
        self.assertNotEqual(a, b)

    def test_script_embeds_the_paths_as_posix(self):
        base = self.tmp_path / "base.blend"
        out = self.tmp_path / "out.glb"
        script = generate_deform_script(self.demo_asset, base, out)
        self.assertIn(base.as_posix(), script)
        self.assertIn(out.as_posix(), script)
        self.assertNotIn("\\", script)

    def test_script_has_no_backslashes_for_windows_style_paths(self):
        base = Path(r"C:\work\assets\base.blend")
        out = Path(r"C:\work\out\character.glb")
        script = generate_deform_script(self.demo_asset, base, out)
        self.assertIn("C:/work/assets/base.blend", script)
        self.assertIn("C:/work/out/character.glb", script)
        self.assertNotIn("\\", script)


if __name__ == "__main__":
    unittest.main()
