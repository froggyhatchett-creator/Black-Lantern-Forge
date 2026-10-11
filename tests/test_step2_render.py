"""Step 2: preview renderer, camera stability, PNG output."""

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from forge.errors import RenderError, UnsupportedVersionError
from forge.hashing import pixels_sha256
from forge.presentation.materials import WrapPattern
from forge.presentation.model import PresentedSword
from forge.render import (
    DEFAULT_PREVIEW,
    PreviewSettings,
    decode_png,
    preview_metadata,
    render_preview,
    write_preview_png,
)
from forge.render.camera import FRAME_HEIGHT, FRAME_TARGET, VIEW_DIRECTIONS, camera_for
from forge.render.raster import BACKGROUND_TOP
from step2_support import GOLDEN_1337_PIXELS_DEFAULT, GOLDEN_1337_PIXELS_SMALL, SMALL, asset, presented


def flat(p):
    """Same presentation with every procedural pattern neutralized."""
    comps = []
    for c in p.components:
        pat = c.material.pattern
        if isinstance(pat, WrapPattern):
            pat = dataclasses.replace(pat, contrast=0.0)
        else:
            pat = dataclasses.replace(pat, strength=0.0)
        comps.append(dataclasses.replace(c, material=dataclasses.replace(c.material, pattern=pat)))
    return PresentedSword(p.asset, p.versions, tuple(comps))


class TestRender(unittest.TestCase):
    def test_16_preview_generation_succeeds_for_every_view(self):
        for view, settings in SMALL.items():
            img = render_preview(presented(1337), settings)
            self.assertEqual((img.width, img.height), (96, 192))
            self.assertEqual(len(img.pixels), 96 * 192 * 3)
            self.assertEqual(img.camera.view, view)

    def test_preview_is_deterministic_and_matches_golden(self):
        for view, settings in SMALL.items():
            a = render_preview(presented(1337), settings)
            b = render_preview(presented(1337), settings)
            self.assertEqual(a.pixels, b.pixels)
            self.assertEqual(a.pixels_sha256, GOLDEN_1337_PIXELS_SMALL[view], view)

    def test_default_preview_matches_golden(self):
        img = render_preview(presented(1337), DEFAULT_PREVIEW)
        self.assertEqual((img.width, img.height, img.settings.ssaa), (480, 960, 2))
        self.assertEqual(img.pixels_sha256, GOLDEN_1337_PIXELS_DEFAULT)

    def test_preview_is_textured(self):
        """Procedural patterns (sampled through UVs) change the rendered pixels."""
        textured = render_preview(presented(1337), SMALL["three_quarter"]).pixels_sha256
        plain = render_preview(flat(presented(1337)), SMALL["three_quarter"]).pixels_sha256
        self.assertNotEqual(textured, plain)

    def test_different_swords_render_differently(self):
        hashes = {render_preview(presented(s), SMALL["three_quarter"]).pixels_sha256 for s in (0, 1, 2, 1337)}
        self.assertEqual(len(hashes), 4)

    def test_neutral_background_and_sword_present(self):
        img = render_preview(presented(1337), PreviewSettings(1, "front", 96, 192, 1))
        px = img.pixels
        top_left = tuple(px[0:3])
        for got, want in zip(top_left, BACKGROUND_TOP):
            self.assertLessEqual(abs(got - want * 255.0), 2.0)
        self.assertLessEqual(max(top_left) - min(top_left), 10, "background should be a near-neutral gray")
        background_rows = {px[(y * 96) * 3:(y * 96) * 3 + 3] for y in range(192)}
        sword_pixels = sum(1 for i in range(0, len(px), 3)
                           if px[i:i + 3] not in background_rows)
        self.assertGreater(sword_pixels, 300)

    def test_bad_settings_refuse(self):
        with self.assertRaises(UnsupportedVersionError):
            PreviewSettings(2, "front", 96, 96, 1)
        for kwargs in ({"view": "top"}, {"width": 8}, {"height": 5000}, {"ssaa": 0}, {"ssaa": 5},
                       {"width": 96.0}, {"ssaa": True}):
            args = {"preview_version": 1, "view": "front", "width": 96, "height": 96, "ssaa": 1, **kwargs}
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(RenderError):
                    PreviewSettings(**args)
        with self.assertRaises(RenderError):
            render_preview(asset(1), SMALL["front"])  # needs a PresentedSword


class TestCamera(unittest.TestCase):
    def test_17a_camera_is_fixed_and_documented(self):
        self.assertEqual(FRAME_TARGET, (0.0, 0.295, 0.0))
        self.assertEqual(FRAME_HEIGHT, 0.84)
        self.assertEqual(VIEW_DIRECTIONS["three_quarter"], (1.0, 0.5, 2.0))
        self.assertEqual(DEFAULT_PREVIEW.view, "three_quarter")
        for view in VIEW_DIRECTIONS:
            a, b = camera_for(view, 480, 960), camera_for(view, 480, 960)
            self.assertEqual(a, b)
            for vec in (a.direction, a.right, a.up):
                self.assertAlmostEqual(sum(c * c for c in vec), 1.0, delta=1e-12)
            self.assertAlmostEqual(sum(x * y for x, y in zip(a.right, a.up)), 0.0, delta=1e-12)
            self.assertGreater(a.up[1], 0.9, "screen up must stay world +Y")

    def test_17b_camera_does_not_depend_on_the_asset(self):
        cams = {render_preview(presented(s), SMALL["three_quarter"]).camera for s in (0, 1, 1337)}
        self.assertEqual(len(cams), 1)

    def test_17c_every_sword_fits_in_frame_for_every_view(self):
        for view in VIEW_DIRECTIONS:
            cam = camera_for(view, 480, 960)
            for seed in list(range(64)) + [1337, (1 << 64) - 1]:
                for mesh in asset(seed).components:
                    for p in mesh.positions:
                        x, y, _ = cam.project(p)
                        self.assertTrue(4.0 < x < 476.0 and 4.0 < y < 956.0, (view, seed, mesh.name, x, y))

    def test_front_view_axes(self):
        cam = camera_for("front", 100, 200)
        cx, cy, _ = cam.project(FRAME_TARGET)
        self.assertEqual((cx, cy), (50.0, 100.0))
        right, _, _ = cam.project((0.1, 0.295, 0.0))
        _, up, _ = cam.project((0.0, 0.395, 0.0))
        self.assertGreater(right, cx)  # +X is screen right
        self.assertLess(up, cy)        # +Y is screen up (pixel rows grow downward)


class TestPng(unittest.TestCase):
    def test_18_preview_file_exists_is_non_empty_and_decodes(self):
        p = presented(1337)
        img = render_preview(p, SMALL["three_quarter"])
        with tempfile.TemporaryDirectory() as tmp:
            path = write_preview_png(img, Path(tmp) / "nested" / "preview.png", p, "ab" * 32)
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 500)
            w, h, pixels, text = decode_png(path.read_bytes())
        self.assertEqual((w, h), (96, 192))
        self.assertEqual(pixels, img.pixels)
        self.assertEqual(pixels_sha256(w, h, pixels), img.pixels_sha256)
        meta = json.loads(text["forge.preview"])
        self.assertEqual(meta, preview_metadata(p, img, "ab" * 32))
        self.assertEqual(meta["seed"], "1337")
        self.assertEqual(meta["pixels_sha256"], img.pixels_sha256)
        self.assertEqual(meta["camera"]["projection"], "orthographic")
        for key in meta:
            self.assertFalse(any(word in key.lower() for word in ("time", "date", "created")), key)

    def test_png_bad_inputs(self):
        img = render_preview(presented(1), SMALL["front"])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RenderError):
                write_preview_png(img, Path(tmp) / "x.jpg", presented(1))
        with self.assertRaises(RenderError):
            decode_png(b"not a png")


if __name__ == "__main__":
    unittest.main()
