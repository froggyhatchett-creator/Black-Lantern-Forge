"""OBJ export: syntax, content, and stability."""

import tempfile
import unittest
from pathlib import Path

from forge import ExportError, export_obj, generate_sword, obj_bytes, write_obj
from forge.export.obj import format_coord
from forge_test_support import VERSION, parse_obj


class TestObjExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = [generate_sword(s, VERSION) for s in (0, 1, 2, 3, 1337, (1 << 64) - 1)]

    def test_export_succeeds_and_is_clean_ascii_lf(self):
        for a in self.assets:
            text = export_obj(a)
            self.assertTrue(text.isascii())
            self.assertNotIn("\r", text)
            self.assertTrue(text.endswith("\n"))
            self.assertFalse(text.endswith("\n\n"))
            self.assertEqual(obj_bytes(a), text.encode("ascii"))

    def test_contains_expected_vertex_and_face_records(self):
        for a in self.assets:
            obj = parse_obj(export_obj(a))  # strict: raises on any unexpected record
            self.assertEqual(obj["objects"], ["blade", "guard", "grip", "pommel"])
            self.assertEqual(len(obj["vertices"]), a.vertex_count)
            self.assertEqual(len(obj["faces"]), a.triangle_count)
            n = len(obj["vertices"])
            for f in obj["faces"]:
                for i in f:
                    self.assertTrue(1 <= i <= n, f)

    def test_vertex_and_face_content_round_trips(self):
        for a in self.assets:
            obj = parse_obj(export_obj(a))
            expected_v = [p for m in a.components for p in m.positions]
            for got, want in zip(obj["vertices"], expected_v):
                for g, w in zip(got, want):
                    self.assertLessEqual(abs(g - w), 5e-7 + 1e-15)  # 6-decimal quantization
            expected_f, offset = [], 1
            for m in a.components:
                expected_f += [(i + offset, j + offset, k + offset) for i, j, k in m.triangles]
                offset += m.vertex_count
            self.assertEqual(obj["faces"], expected_f)

    def test_header_records_identity_and_conventions(self):
        a = self.assets[4]
        text = export_obj(a)
        header = text[: text.index("\no ") + 1]
        for line in ("# obj_format: 1", "# asset_type: short_sword", "# generator: forge.sword",
                     "# generator_version: 1", "# seed: 1337", "# units: meters",
                     f"# vertices: {a.vertex_count}", f"# triangles: {a.triangle_count}"):
            self.assertIn(line + "\n", header)

    def test_no_negative_zero_and_fixed_precision(self):
        for a in self.assets:
            for line in export_obj(a).splitlines():
                if line.startswith("v "):
                    for tok in line.split()[1:]:
                        self.assertNotEqual(tok, "-0.000000")
                        self.assertEqual(len(tok.split(".")[1]), 6, tok)

    def test_format_coord(self):
        self.assertEqual(format_coord(0.0), "0.000000")
        self.assertEqual(format_coord(-0.0), "0.000000")
        self.assertEqual(format_coord(-1e-9), "0.000000")
        self.assertEqual(format_coord(1.0000004), "1.000000")
        self.assertEqual(format_coord(1.0000006), "1.000001")
        self.assertEqual(format_coord(-0.25), "-0.250000")
        for bad in (float("nan"), float("inf"), -float("inf"), 1, None):
            with self.assertRaises(ExportError):
                format_coord(bad)

    def test_write_obj_writes_identical_bytes_and_creates_dirs(self):
        a = self.assets[4]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_obj(a, Path(tmp) / "nested" / "dir" / "sword.obj")
            self.assertEqual(path.read_bytes(), obj_bytes(a))
            path2 = write_obj(a, Path(tmp) / "again.obj")
            self.assertEqual(path2.read_bytes(), path.read_bytes())

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ExportError):
            export_obj("not an asset")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExportError):
                write_obj(self.assets[0], Path(tmp) / "sword.txt")


if __name__ == "__main__":
    unittest.main()
