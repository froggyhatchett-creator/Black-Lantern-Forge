"""Step 2 guards: frozen Step 1 output is untouched; Step 2 code keeps the determinism rules."""

import ast
import unittest

from forge import export_obj, generate_sword, obj_bytes
from forge.hashing import geometry_sha256
from forge.presentation import PRESENTATION_V1, derive_presentation
from forge_test_support import REPO_ROOT, sha256
from step2_support import GOLDEN_1337
from test_determinism import GOLDEN_V1  # the frozen Step 1 goldens, imported, not copied


class TestFrozenStep1(unittest.TestCase):
    def test_20_frozen_golden_geometry_is_unchanged(self):
        """Step 1 goldens still hold after Step 2 code has been imported and exercised."""
        for seed in GOLDEN_V1:
            derive_presentation(generate_sword(seed, 1), PRESENTATION_V1)  # exercise Step 2 first
        for seed, (obj_hash, _, _) in GOLDEN_V1.items():
            self.assertEqual(sha256(obj_bytes(generate_sword(seed, 1))), obj_hash)
        self.assertEqual(GOLDEN_V1[1337][0], GOLDEN_1337["obj_format1_sha256"])
        self.assertEqual(geometry_sha256(generate_sword(1337, 1)), GOLDEN_1337["geometry_sha256"])

    def test_format1_header_has_no_step2_fields(self):
        text = export_obj(generate_sword(1337, 1))
        self.assertIn("# obj_format: 1\n", text)
        for word in ("vt ", "vn ", "mtllib", "usemtl", "presentation"):
            self.assertNotIn(word, text)


class TestStep2Static(unittest.TestCase):
    """Pixel/normal/UV determinism rests on correctly rounded IEEE ops only."""

    BANNED_MATH = {"sin", "cos", "tan", "asin", "acos", "atan", "atan2", "exp", "expm1", "log", "log1p",
                   "log2", "log10", "pow", "hypot", "fsum", "dist", "erf", "gamma"}

    def files(self):
        pkg = REPO_ROOT / "forge"
        out = sorted((pkg / "presentation").glob("*.py")) + sorted((pkg / "render").glob("*.py"))
        out += [pkg / "hashing.py", pkg / "record.py", pkg / "export" / "obj_enriched.py"]
        self.assertGreaterEqual(len(out), 12)
        return out

    def test_no_libm_transcendentals_or_float_pow(self):
        for path in self.files():
            rel = path.relative_to(REPO_ROOT)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math":
                    self.assertNotIn(node.attr, self.BANNED_MATH, f"{rel}: math.{node.attr}")
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                    self.fail(f"{rel}: '**' operator (use explicit multiplication or _ipow)")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("pow", "sum"):
                    self.fail(f"{rel}: builtin {node.func.id}() in Step 2 numeric code")

    def test_no_wall_clock_or_entropy(self):
        banned = {"random", "time", "datetime", "secrets", "uuid"}
        for path in self.files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & banned, path.name)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], banned, path.name)


if __name__ == "__main__":
    unittest.main()
