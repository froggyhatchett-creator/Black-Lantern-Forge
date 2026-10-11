"""Step 5A tests 30-36, 57 and 60 (+ preview-framing checks): presentation, previews and OBJ.

30-33  normals per family          34  UVs per family          35  materials per family
36     previews render per family  57  OBJ behavior where supported
60     previews are deterministic and reproduce the seed-1337 goldens byte for byte
"""

import math
import re
import tempfile
import unittest
from pathlib import Path

from arsenal_support import (
    ARSENAL_GOLDEN,
    BLADE_PRESENTATION,
    COMPONENTS,
    EXAMPLES,
    FAMILIES,
    FIT_PREVIEW,
    LINEUP_SEEDS,
    asset,
    presented,
    sha256,
)
from forge.blades.presentation import NORMAL_MODES, PALETTES_V1, derive_blade_presentation
from forge.catalog import REGISTRY
from forge.errors import ForgeError, PresentationError, UnknownExportFormatError, UnsupportedExportVersionError
from forge.presentation.materials import Material
from forge.presentation.model import PresentationVersions, PresentedSword
from forge.registry import export_asset, preview_for, render_asset_preview
from forge.render import encode_preview_png, preview_metadata
from forge.render.camera import camera_for
from forge.render.fit import MARGIN, fit_camera
from forge.render.png import decode_png
from forge.render.settings import PreviewSettings
from forge.sword import generate_sword

V1 = PresentationVersions(1, 1, 1, 1)
BACKGROUND_TOLERANCE = 6


def face_normal(p, tri):
    a, b, c = (p[i] for i in tri)
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def object_rows_cols(image):
    """Rows and columns that hold anything other than the (vertical-gradient) background."""
    w, h, px = image.width, image.height, image.pixels
    rows, cols = set(), set()
    for y in range(h):
        bg = px[(y * w) * 3:(y * w) * 3 + 3]                  # the left edge is always background
        for x in range(w):
            i = (y * w + x) * 3
            if max(abs(px[i + k] - bg[k]) for k in range(3)) > BACKGROUND_TOLERANCE:
                rows.add(y)
                cols.add(x)
    return rows, cols


class TestNormals(unittest.TestCase):
    """30-33."""

    def check(self, family):
        for seed in LINEUP_SEEDS:
            p = presented(family, seed)
            self.assertEqual(p.versions, V1)
            self.assertEqual(tuple(c.name for c in p.components), COMPONENTS)
            for mesh, comp in zip(p.asset.components, p.components):
                with self.subTest(family=family, seed=seed, component=mesh.name):
                    self.assertEqual(len(comp.normal_indices), len(mesh.triangles))
                    for n in comp.normals:
                        self.assertTrue(all(math.isfinite(c) for c in n))
                        self.assertAlmostEqual(math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]), 1.0, delta=1e-12)
                    for tri, idx in zip(mesh.triangles, comp.normal_indices):
                        fn = face_normal(mesh.positions, tri)
                        for k in idx:
                            self.assertTrue(0 <= k < len(comp.normals))
                            n = comp.normals[k]
                            self.assertGreater(n[0] * fn[0] + n[1] * fn[1] + n[2] * fn[2], 0.0,
                                               "a corner normal must face out of its own face")
                    mode, _ = NORMAL_MODES[family][mesh.name]
                    if mode == "faceted":
                        for tri, idx in zip(mesh.triangles, comp.normal_indices):
                            self.assertEqual(len(set(idx)), 1)
        again = derive_blade_presentation(asset(family, 1337), V1)
        self.assertEqual([c.normals for c in again.components], [c.normals for c in presented(family).components])

    def test_30_dagger_normals(self):
        self.check("dagger")

    def test_31_long_sword_normals(self):
        self.check("long_sword")

    def test_32_curved_sword_normals(self):
        self.check("curved_sword")
        # the curved blade is shaded smooth along its curve, not as 24 flat facets per side:
        # most corner normals are blended across neighbouring faces
        for seed in LINEUP_SEEDS:
            p = presented("curved_sword", seed)
            mesh, blade = p.asset.component("blade"), p.component("blade")
            blended = total = 0
            for tri, idx in zip(mesh.triangles, blade.normal_indices):
                fn = face_normal(mesh.positions, tri)
                length = math.sqrt(fn[0] * fn[0] + fn[1] * fn[1] + fn[2] * fn[2])
                for k in idx:
                    n = blade.normals[k]
                    total += 1
                    blended += (n[0] * fn[0] + n[1] * fn[1] + n[2] * fn[2]) / length < 1.0 - 1e-9
            self.assertGreater(blended, total // 2)

    def test_33_great_sword_normals(self):
        self.check("great_sword")


class TestUVsAndMaterials(unittest.TestCase):
    def test_34_uvs_per_family(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                for mesh, comp in zip(p.asset.components, p.components):
                    with self.subTest(family=family, seed=seed, component=mesh.name):
                        self.assertEqual(len(comp.uv_indices), len(mesh.triangles))
                        for u, v in comp.uvs:
                            self.assertTrue(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0)
                        us = [u for u, _ in comp.uvs]
                        vs = [v for _, v in comp.uvs]
                        self.assertGreater(max(us) - min(us), 0.5)
                        self.assertGreater(max(vs) - min(vs), 0.5)
                        for idx in comp.uv_indices:
                            self.assertTrue(all(0 <= k < len(comp.uvs) for k in idx))
        self.assertEqual(REGISTRY.presentation(BLADE_PRESENTATION, 1).uv_version, 1)

    def test_35_materials_per_family(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                with self.subTest(family=family, seed=seed):
                    for comp in p.components:
                        m = comp.material
                        self.assertIsInstance(m, Material)           # the frozen material model, reused
                        self.assertEqual(m.component, comp.name)
                        presets = {preset[0] for preset in PALETTES_V1[family][comp.name]}
                        if comp.name == "pommel":                   # a pommel may match its guard
                            presets |= {preset[0] for preset in PALETTES_V1[family]["guard"]}
                        self.assertIn(m.preset, presets)
                        self.assertTrue(all(0.0 <= c <= 1.0 for c in m.base_color))
                        self.assertTrue(0.0 <= m.roughness <= 1.0)
                    self.assertEqual(sorted(p.materials), sorted(COMPONENTS))
            # materials come from their own streams: they never move the geometry
            self.assertEqual(asset(family, 1337).components, presented(family, 1337).asset.components)
        self.assertEqual(derive_blade_presentation(asset("dagger", 9), V1).materials,
                         derive_blade_presentation(asset("dagger", 9), V1).materials)

    def test_presentation_is_explicit_and_fails_closed(self):
        with self.assertRaises(PresentationError):
            derive_blade_presentation(generate_sword(1337, 1), V1)
        for bad in (PresentationVersions(2, 1, 1, 1), PresentationVersions(1, 2, 1, 1),
                    PresentationVersions(1, 1, 2, 1), PresentationVersions(1, 1, 1, 2)):
            with self.assertRaises(ForgeError):
                derive_blade_presentation(asset("dagger"), bad)


class TestPreview(unittest.TestCase):
    SMALL = PreviewSettings(1, "front", 64, 192, 1)

    def test_36_preview_renders_per_family(self):
        for family in FAMILIES:
            self.assertEqual(preview_for(REGISTRY, family, 1, 1).render.__name__, "render_fit_preview")
            self.assertEqual(REGISTRY.asset(family).descriptor.preview_id, FIT_PREVIEW)
            for view in ("three_quarter", "front", "side"):
                with self.subTest(family=family, view=view):
                    settings = PreviewSettings(1, view, 64, 192, 1)
                    img = render_asset_preview(REGISTRY, presented(family), settings)
                    self.assertEqual((img.width, img.height), (64, 192))
                    self.assertEqual(len(img.pixels), 64 * 192 * 3)
                    rows, cols = object_rows_cols(img)
                    if view != "side":        # edge-on, a thin blade can fall between 1-sample pixels
                        self.assertGreater(len(rows), 0.70 * 192, "the weapon should fill the frame's height")
                    self.assertGreater(len(rows), 0)
                    self.assertGreater(min(rows), 0)
                    self.assertLess(max(rows), 191, "nothing is clipped at the frame edge")
                    self.assertGreater(min(cols), 0)
                    self.assertLess(max(cols), 63)

    def test_fit_frames_the_whole_asset_with_the_documented_margin(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                for view in ("three_quarter", "front", "side"):
                    cam = fit_camera(p, view, 120, 360)
                    base = camera_for(view, 120, 360)
                    self.assertEqual((cam.direction, cam.right, cam.up), (base.direction, base.right, base.up))
                    us, rs = [], []
                    for m in p.asset.components:
                        for q in m.positions:
                            d = tuple(q[k] - cam.target[k] for k in range(3))
                            rs.append(d[0] * cam.right[0] + d[1] * cam.right[1] + d[2] * cam.right[2])
                            us.append(d[0] * cam.up[0] + d[1] * cam.up[1] + d[2] * cam.up[2])
                    self.assertLessEqual(max(abs(u) for u in us), cam.half_height / (1.0 + MARGIN) + 1e-12)
                    self.assertLessEqual(max(abs(r) for r in rs), cam.half_width / (1.0 + MARGIN) + 1e-12)
                    # tight on the limiting axis
                    self.assertAlmostEqual(max(max(abs(u) for u in us) / cam.half_height,
                                               max(abs(r) for r in rs) / cam.half_width), 1.0 / (1.0 + MARGIN),
                                           delta=1e-9)

    def test_short_sword_keeps_fixed_preview_v1(self):
        d = REGISTRY.asset("short_sword").descriptor
        self.assertEqual(d.preview_id, "forge.preview")
        self.assertEqual(preview_for(REGISTRY, "short_sword", 1, 1).render.__name__, "render_preview")

    def test_60_previews_deterministic(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                g = ARSENAL_GOLDEN[family]["preview"]
                settings = PreviewSettings(1, g["view"], g["width"], g["height"], g["ssaa"])
                a = render_asset_preview(REGISTRY, presented(family), settings)
                b = render_asset_preview(REGISTRY, presented(family), settings)
                self.assertEqual(a.pixels, b.pixels)
                self.assertEqual(a.pixels_sha256, g["pixels_sha256"])
                record_content = ARSENAL_GOLDEN[family]["integrity"]["record_content_sha256"]
                png = encode_preview_png(a, preview_metadata(presented(family), a, record_content))
                example = EXAMPLES / f"{family}_preview_seed1337_three_quarter.png"
                self.assertEqual(png, example.read_bytes())
                self.assertEqual(sha256(png), g["png_sha256"])
                w, h, rgb, text = decode_png(example.read_bytes())
                self.assertEqual((w, h, rgb), (a.width, a.height, a.pixels))
                self.assertIn(f'"pixels_sha256":"{g["pixels_sha256"]}"', text["forge.preview"])


class TestObj(unittest.TestCase):
    def test_57_obj_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    p = presented(family)
                    out = Path(tmp) / f"{family}_seed1337_v1.obj"
                    written = export_asset(REGISTRY, p.asset, p, "obj", 2, out)
                    self.assertEqual([w.name for w in written], [out.name, f"{family}_seed1337_v1.mtl"])
                    g = ARSENAL_GOLDEN[family]["obj2"]
                    self.assertEqual(sha256(out.read_bytes()), g["obj_sha256"])
                    self.assertEqual({w.name: sha256(w.read_bytes()) for w in written[1:]}, g["mtl"])
                    text = out.read_text(encoding="ascii")
                    self.assertEqual(len(re.findall(r"^v ", text, re.M)), p.asset.vertex_count)
                    self.assertEqual(len(re.findall(r"^f ", text, re.M)), p.asset.triangle_count)
                    self.assertEqual(re.findall(r"^o (\w+)", text, re.M), list(COMPONENTS))
                    self.assertIn(f"mtllib {family}_seed1337_v1.mtl", text)
                    self.assertTrue(all(c.isascii() for c in text))
                    # OBJ format 1 is the frozen short-sword exporter: refused, nothing written
                    bad = Path(tmp) / f"{family}_v1.obj"
                    with self.assertRaises(UnsupportedExportVersionError):
                        export_asset(REGISTRY, p.asset, p, "obj", 1, bad)
                    self.assertFalse(bad.exists())
                    with self.assertRaises(UnknownExportFormatError):
                        export_asset(REGISTRY, p.asset, p, "fbx", 1, Path(tmp) / "x.fbx")
                    # OBJ 2 needs the presentation that belongs to this asset
                    with self.assertRaises(ForgeError):
                        export_asset(REGISTRY, p.asset, None, "obj", 2, Path(tmp) / "y.obj")
                    with self.assertRaises(ForgeError):
                        export_asset(REGISTRY, asset(family, 2), p, "obj", 2, Path(tmp) / "z.obj")

    def test_presented_container_is_the_generic_one(self):
        for family in FAMILIES:
            self.assertIsInstance(presented(family), PresentedSword)


if __name__ == "__main__":
    unittest.main()
