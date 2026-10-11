"""Step 2.5 anti-abstraction test: a test-only asset family flows through the
UNMODIFIED generic loader, hashing core, preview dispatch, and CLI routing, purely
by registering explicit versioned entries. (Not shipped; not in forge.catalog.)"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from forge.catalog import REGISTRY
from forge.cli import main
from forge.errors import UnknownAssetTypeError
from forge.record import build_record, load_record, save_record
from forge.registry import generate_asset, present_asset, render_asset_preview
from forge.render.settings import PreviewSettings
from registry_fixtures import registry_with_tetra


class TestNewFamilyNeedsOnlyRegistration(unittest.TestCase):
    def setUp(self):
        self.reg = registry_with_tetra()
        self.versions = self.reg.presentation("test.presentation", 1).versions

    def make(self, seed=5):
        asset = generate_asset(self.reg, "test_tetra", seed, 1)
        return asset, present_asset(self.reg, asset, self.versions)

    def test_generation_and_presentation_dispatch(self):
        a1, p1 = self.make()
        a2, p2 = self.make()
        self.assertEqual(a1, a2)
        self.assertEqual(p1.materials, p2.materials)
        self.assertEqual(a1.asset_type, "test_tetra")

    def test_record_round_trip_through_generic_loader(self):
        _, p = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            path = save_record(build_record(p, forge_version="t", registry=self.reg),
                               Path(tmp) / "tetra.json", registry=self.reg)
            loaded = load_record(path, registry=self.reg)
            self.assertEqual(loaded.verified, ("record_content_sha256", "materials", "geometry_sha256",
                                               "normals_sha256", "materials_sha256"))
            self.assertEqual(loaded.spec.asset_type, "test_tetra")
            with self.assertRaises(UnknownAssetTypeError):   # production catalog doesn't know it
                load_record(path)

    def test_preview_dispatch(self):
        _, p = self.make()
        img = render_asset_preview(self.reg, p, PreviewSettings(1, "front", 64, 128, 1))
        self.assertEqual(len(img.pixels), 64 * 128 * 3)

    def test_cli_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["generate", "test_tetra", "--seed", "3", "--generator-version", "1",
                             "--presentation-version", "1", "--save", f"{tmp}/t.json"], registry=self.reg)
            self.assertEqual(code, 0)
            self.assertIn("Black Lantern Forge - test tetrahedron", out.getvalue())
            self.assertIn("size", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["load", f"{tmp}/t.json"], registry=self.reg), 0)
            self.assertIn("asset record verified", out.getvalue())

    def test_production_catalog_is_unchanged(self):
        self.assertEqual(REGISTRY.asset_types(), ("curved_sword", "dagger", "great_sword", "long_sword", "mace",
                                                  "one_hand_axe", "short_sword", "two_hand_axe", "war_hammer"))
        self.assertEqual(self.reg.asset_types(), ("curved_sword", "dagger", "great_sword", "long_sword", "mace",
                                                  "one_hand_axe", "short_sword", "test_tetra", "two_hand_axe",
                                                  "war_hammer"))


if __name__ == "__main__":
    unittest.main()
