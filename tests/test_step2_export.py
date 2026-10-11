"""Step 2: enriched OBJ (obj_format 2) + MTL. obj_format 1 must be untouched."""

import tempfile
import unittest
from pathlib import Path

from forge import export_obj
from forge.errors import ExportError
from forge.export.obj_enriched import export_enriched_obj, export_mtl, material_name, write_enriched_obj
from forge.export.obj import format_coord
from forge_test_support import sha256
from step2_support import GOLDEN_1337, presented

GOLDEN_1337_OBJ2 = "69a545afc45357397d68093fb1e7e6f292e97fba2cbaacc522b943e2e40d1010"  # mtllib sword.mtl
GOLDEN_1337_MTL = "52f06f226b88911add23bbc1da8c1a7d6edbd8a8135ac1ce034ae7904bcdc306"


def records(text, tag):
    return [line for line in text.splitlines() if line.startswith(tag + " ")]


class TestEnrichedObj(unittest.TestCase):
    def test_format1_is_unchanged(self):
        self.assertEqual(sha256(export_obj(presented(1337).asset).encode("ascii")), GOLDEN_1337["obj_format1_sha256"])

    def test_vertex_lines_identical_to_format1(self):
        for seed in (0, 1, 2, 1337):
            p = presented(seed)
            self.assertEqual(records(export_enriched_obj(p, "s.mtl"), "v"), records(export_obj(p.asset), "v"))

    def test_face_position_indices_identical_to_format1(self):
        p = presented(1337)
        f1 = [tuple(line.split()[1:]) for line in records(export_obj(p.asset), "f")]
        f2 = [tuple(c.split("/")[0] for c in line.split()[1:]) for line in records(export_enriched_obj(p, "s.mtl"), "f")]
        self.assertEqual(f1, f2)

    def test_attribute_counts_and_index_ranges(self):
        p = presented(7)
        text = export_enriched_obj(p, "s.mtl")
        n_v, n_vt, n_vn = (len(records(text, t)) for t in ("v", "vt", "vn"))
        self.assertEqual(n_v, p.asset.vertex_count)
        self.assertEqual(n_vt, sum(len(c.uvs) for c in p.components))
        self.assertEqual(n_vn, sum(len(c.normals) for c in p.components))
        faces = records(text, "f")
        self.assertEqual(len(faces), p.asset.triangle_count)
        for line in faces:
            corners = line.split()[1:]
            self.assertEqual(len(corners), 3)
            for corner in corners:
                v, vt, vn = (int(x) for x in corner.split("/"))
                self.assertTrue(1 <= v <= n_v and 1 <= vt <= n_vt and 1 <= vn <= n_vn)
        for line in records(text, "vn"):
            x, y, z = (float(c) for c in line.split()[1:])
            self.assertAlmostEqual((x * x + y * y + z * z) ** 0.5, 1.0, delta=2e-6)
        self.assertEqual(records(text, "usemtl"), [f"usemtl {material_name(c.name)}" for c in p.components])
        self.assertIn("# obj_format: 2\n", text)
        self.assertIn("mtllib s.mtl\n", text)

    def test_mtl_matches_materials(self):
        p = presented(1337)
        mtl = export_mtl(p)
        self.assertEqual(records(mtl, "newmtl"), [f"newmtl {material_name(c.name)}" for c in p.components])
        kd = records(mtl, "Kd")
        for line, comp in zip(kd, p.components):
            self.assertEqual(line, "Kd " + " ".join(format_coord(c) for c in comp.material.base_color))
        self.assertEqual(records(mtl, "Pm"), [f"Pm {format_coord(c.material.metallic)}" for c in p.components])

    def test_enriched_export_is_deterministic_and_golden(self):
        p = presented(1337)
        self.assertEqual(export_enriched_obj(p, "sword.mtl"), export_enriched_obj(p, "sword.mtl"))
        self.assertEqual(sha256(export_enriched_obj(p, "sword.mtl").encode("ascii")), GOLDEN_1337_OBJ2)
        self.assertEqual(sha256(export_mtl(p).encode("ascii")), GOLDEN_1337_MTL)

    def test_write_enriched_obj(self):
        p = presented(1337)
        with tempfile.TemporaryDirectory() as tmp:
            obj, mtl = write_enriched_obj(p, Path(tmp) / "out" / "sword.obj")
            self.assertEqual(mtl.name, "sword.mtl")
            self.assertEqual(sha256(obj.read_bytes()), GOLDEN_1337_OBJ2)
            self.assertEqual(sha256(mtl.read_bytes()), GOLDEN_1337_MTL)
            with self.assertRaises(ExportError):
                write_enriched_obj(p, Path(tmp) / "sword.fbx")
        for bad in ("dir/x.mtl", "x.txt", "has space.mtl"):
            with self.assertRaises(ExportError):
                export_enriched_obj(p, bad)
        with self.assertRaises(ExportError):
            export_enriched_obj(p.asset, "x.mtl")


if __name__ == "__main__":
    unittest.main()
