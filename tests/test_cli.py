"""Command-line entry point: python -m forge sword ..."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge import generate_sword, obj_bytes
from forge_test_support import REPO_ROOT, sha256


def run_cli(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run([sys.executable, "-m", "forge", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


class TestCli(unittest.TestCase):
    def test_generates_obj_identical_to_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.obj"
            res = run_cli("sword", "--seed", "1337", "--out", str(out), cwd=tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = out.read_bytes()
            self.assertEqual(data, obj_bytes(generate_sword(1337, 1)))
            self.assertIn(sha256(data), res.stdout)
            self.assertIn("generator_version  1", res.stdout)

    def test_default_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_cli("sword", "--seed", "7", cwd=tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue((Path(tmp) / "output" / "short_sword_seed7_v1.obj").is_file())

    def test_json_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_cli("sword", "--seed", "42", "--generator-version", "1",
                          "--out", "x.obj", "--json", cwd=tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            record = json.loads(res.stdout)
            self.assertEqual(record["seed"], 42)
            self.assertEqual(record["generator_version"], 1)
            self.assertEqual(record["params"], generate_sword(42, 1).params.to_dict())
            self.assertEqual(record["obj"]["sha256"], sha256((Path(tmp) / "x.obj").read_bytes()))

    def test_invalid_input_exits_2_with_clear_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args, needle in ((["--seed", "-5"], "seed"), (["--seed", "abc"], "seed"),
                                 (["--seed", "18446744073709551616"], "seed"),
                                 (["--seed", "1", "--generator-version", "9"], "generator_version"),
                                 (["--seed", "1", "--out", "sword.fbx"], ".obj")):
                with self.subTest(args=args):
                    res = run_cli("sword", *args, cwd=tmp)
                    self.assertEqual(res.returncode, 2)
                    self.assertIn("forge: error:", res.stderr)
                    self.assertIn(needle, res.stderr)
            self.assertFalse((Path(tmp) / "output").exists(), "nothing written on invalid input")


if __name__ == "__main__":
    unittest.main()
