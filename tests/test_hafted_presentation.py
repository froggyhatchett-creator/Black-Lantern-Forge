"""Step 5B tests 34-37, 40 and 60: presentation, previews and OBJ for the hafted families.

34  normals generate for all     35  UVs generate for all     36  materials generate for all
37  previews render for all      40  OBJ (format 2) exports all; format 1 is refused
60  previews are deterministic and reproduce the seed-1337 goldens byte for byte
"""

import math
import re
import tempfile
import unittest
from pathlib import Path

from forge.blades.presentation import PALETTES_V1 as BLADE_PALETTES
from forge.catalog import REGISTRY
from forge.errors import ForgeError, PresentationError, UnsupportedExportVersionError
from forge.hafted.presentation import (
    HAFTED_PRESENTATION_V1,
    MATERIAL_STREAM_PREFIX,
    PROFILES,
    derive_hafted_presentation,
)
from forge.presentation.materials import Material
from forge.presentation.model import PresentationVersions, PresentedSword
from forge.registry import export_asset, preview_for, render_asset_preview
from forge.render import encode_preview_png, preview_metadata
from forge.render.fit import MARGIN, fit_camera
from forge.render.png import decode_png
from forge.render.settings import PreviewSettings
from hafted_support import (
    COMPONENTS,
    EXAMPLES,
    FAMILIES,
    HAFTED_GOLDEN,
    LINEUP_SEEDS,
    asset,
    face_normal,
    object_rows_cols,
    presented,
    sha256,
)


class TestPresentation(unittest.TestCase):
    def test_34_normals_generate_for_all(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                self.assertEqual(p.versions, HAFTED_PRESENTATION_V1)
                for mesh, comp in zip(p.asset.components, p.components):
                    with self.subTest(family=family, seed=seed, component=mesh.name):
                        self.assertEqual(len(comp.normal_indices), len(mesh.triangles))
                        for n in comp.normals:
                            self.assertAlmostEqual(math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]), 1.0, delta=1e-12)
                        for tri, idx in zip(mesh.triangles, comp.normal_indices):
                            fn = face_normal(mesh.positions, tri)
                            for k in idx:
                                n = comp.normals[k]
                                self.assertGreater(n[0] * fn[0] + n[1] * fn[1] + n[2] * fn[2], 0.0)
                        if PROFILES[family][mesh.name].normals[0] == "faceted":
                            self.assertTrue(all(len(set(i)) == 1 for i in comp.normal_indices))
            again = derive_hafted_presentation(asset(family), HAFTED_PRESENTATION_V1)
            self.assertEqual([c.normals for c in again.components], [c.normals for c in presented(family).components])

    def test_35_uvs_generate_for_all(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                for mesh, comp in zip(p.asset.components, p.components):
                    with self.subTest(family=family, seed=seed, component=mesh.name):
                        self.assertEqual(len(comp.uv_indices), len(mesh.triangles))
                        self.assertTrue(all(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in comp.uvs))
                        us, vs = [u for u, _ in comp.uvs], [v for _, v in comp.uvs]
                        self.assertGreater(max(us) - min(us), 0.5)
                        self.assertGreater(max(vs) - min(vs), 0.5)
        self.assertEqual(REGISTRY.presentation("forge.hafted-presentation", 1).uv_version, 1)

    def test_36_materials_generate_for_all(self):
        metals = {"forged_iron", "grey_steel", "bright_steel", "blackened_steel", "brass", "bronze", "steel", "iron"}
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                with self.subTest(family=family, seed=seed):
                    self.assertEqual(sorted(p.materials), sorted(COMPONENTS[family]))
                    for comp in p.components:
                        m = comp.material
                        self.assertIsInstance(m, Material)          # the frozen material model, reused
                        self.assertEqual(m.component, comp.name)
                        part = PROFILES[family][comp.name]
                        options = {preset[0] for preset in part.palette}
                        if part.follows:
                            options |= {preset[0] for preset in PROFILES[family][part.follows].palette}
                        self.assertIn(m.preset, options)
                    self.assertEqual(p.component("grip").material.metallic, 0.0)
                    head = p.component("head").material
                    self.assertIn(head.preset, metals)
                    self.assertEqual(head.metallic, 1.0)
                    for follower, leader in (("bit", "head"), ("face", "head"), ("rear", "head"), ("flanges", "head")):
                        if follower in COMPONENTS[family]:
                            self.assertEqual(p.component(follower).material.preset, p.component(leader).material.preset)
            self.assertTrue(all(name.startswith(MATERIAL_STREAM_PREFIX) for name in
                                (f"{MATERIAL_STREAM_PREFIX}{family}.{c}" for c in COMPONENTS[family])))
        self.assertNotIn("one_hand_axe", BLADE_PALETTES, "the blade presentation is untouched")

    def test_presentation_fails_closed(self):
        from forge.blades import dagger
        with self.assertRaises(PresentationError):
            derive_hafted_presentation(dagger.generate(1), HAFTED_PRESENTATION_V1)
        for bad in (PresentationVersions(2, 1, 1, 1), PresentationVersions(1, 1, 2, 1)):
            with self.assertRaises(ForgeError):
                derive_hafted_presentation(asset("mace"), bad)
        self.assertIsInstance(presented("mace"), PresentedSword)


class TestPreview(unittest.TestCase):
    def test_37_previews_render_for_all(self):
        for family in FAMILIES:
            self.assertEqual(preview_for(REGISTRY, family, 1, 1).render.__name__, "render_fit_preview")
            for view in ("three_quarter", "front", "side"):
                with self.subTest(family=family, view=view):
                    img = render_asset_preview(REGISTRY, presented(family), PreviewSettings(1, view, 64, 192, 1))
                    self.assertEqual(len(img.pixels), 64 * 192 * 3)
                    rows, cols = object_rows_cols(img)
                    self.assertGreater(len(rows), 0.7 * 192 if view != "side" else 0)
                    self.assertGreater(min(rows), 0)
                    self.assertLess(max(rows), 191, "nothing is clipped at the frame edge")
                    self.assertGreater(min(cols), 0)
                    self.assertLess(max(cols), 63)

    def test_fit_frames_every_hafted_asset(self):
        for family in FAMILIES:
            for seed in LINEUP_SEEDS:
                p = presented(family, seed)
                for view in ("three_quarter", "front", "side"):
                    cam = fit_camera(p, view, 120, 360)
                    worst = 0.0
                    for m in p.asset.components:
                        for q in m.positions:
                            d = tuple(q[k] - cam.target[k] for k in range(3))
                            u = abs(d[0] * cam.up[0] + d[1] * cam.up[1] + d[2] * cam.up[2]) / cam.half_height
                            r = abs(d[0] * cam.right[0] + d[1] * cam.right[1] + d[2] * cam.right[2]) / cam.half_width
                            worst = max(worst, u, r)
                    self.assertAlmostEqual(worst, 1.0 / (1.0 + MARGIN), delta=1e-9)

    def test_60_previews_deterministic(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                g = HAFTED_GOLDEN[family]["preview"]
                settings = PreviewSettings(1, g["view"], g["width"], g["height"], g["ssaa"])
                a = render_asset_preview(REGISTRY, presented(family), settings)
                b = render_asset_preview(REGISTRY, presented(family), settings)
                self.assertEqual(a.pixels, b.pixels)
                self.assertEqual(a.pixels_sha256, g["pixels_sha256"])
                content = HAFTED_GOLDEN[family]["integrity"]["record_content_sha256"]
                png = encode_preview_png(a, preview_metadata(presented(family), a, content))
                example = EXAMPLES / f"{family}_preview_seed1337_three_quarter.png"
                self.assertEqual(png, example.read_bytes())
                w, h, rgb, _ = decode_png(example.read_bytes())
                self.assertEqual((w, h, rgb), (a.width, a.height, a.pixels))


class TestObj(unittest.TestCase):
    def test_40_obj_exports_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    p = presented(family)
                    out = Path(tmp) / f"{family}_seed1337_v1.obj"
                    written = export_asset(REGISTRY, p.asset, p, "obj", 2, out)
                    g = HAFTED_GOLDEN[family]["obj2"]
                    self.assertEqual(sha256(out.read_bytes()), g["obj_sha256"])
                    self.assertEqual({w.name: sha256(w.read_bytes()) for w in written[1:]}, g["mtl"])
                    text = out.read_text(encoding="ascii")
                    self.assertEqual(len(re.findall(r"^v ", text, re.M)), p.asset.vertex_count)
                    self.assertEqual(len(re.findall(r"^f ", text, re.M)), p.asset.triangle_count)
                    self.assertEqual(re.findall(r"^o (\w+)", text, re.M), list(COMPONENTS[family]))
                    with self.assertRaises(UnsupportedExportVersionError):
                        export_asset(REGISTRY, p.asset, p, "obj", 1, Path(tmp) / "no.obj")
                    self.assertFalse((Path(tmp) / "no.obj").exists())


if __name__ == "__main__":
    unittest.main()
