"""Step 4 tests 56-57 (+ exit codes): the CLI validates and summarizes with no GUI available."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge_engine_viewer.cli import main
from forge_test_support import REPO_ROOT
from viewer_support import FROZEN_GLB_SHA256, FROZEN_MANIFEST_SHA256, GOLDEN_DIR

NO_TK = (
    "import sys\n"
    "class Block:\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == 'tkinter' or name.startswith('tkinter.') or name == '_tkinter':\n"
    "            raise ImportError('no tkinter in this test')\n"
    "sys.meta_path.insert(0, Block())\n"
    "from forge_engine_viewer.cli import main\n"
    "code = main(sys.argv[1:])\n"
    "assert 'tkinter' not in sys.modules and 'forge_engine_viewer.window' not in sys.modules\n"
    "sys.exit(code)\n"
)


def run_no_tk(*argv):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    env.pop("DISPLAY", None)
    return subprocess.run([sys.executable, "-c", NO_TK, *argv], cwd=REPO_ROOT, env=env, capture_output=True,
                          text=True, timeout=120)


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:          # argparse errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TestHeadlessModes(unittest.TestCase):
    def test_56_validation_only_mode_works_without_gui(self):
        r = run_no_tk(str(GOLDEN_DIR), "--validate-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("VALID  "))
        self.assertIn(f"glb_sha256         {FROZEN_GLB_SHA256}", r.stdout)
        self.assertIn("checks passed      16:", r.stdout)
        r = run_no_tk(str(GOLDEN_DIR), "--validate-only", "--json")
        report = json.loads(r.stdout)
        self.assertEqual((report["status"], report["glb_sha256"], report["manifest_file_sha256"]),
                         ("valid", FROZEN_GLB_SHA256, FROZEN_MANIFEST_SHA256))
        self.assertEqual(len(report["hashes_verified"]), 9)

    def test_57_dump_summary_mode_works_without_gui(self):
        r = run_no_tk(str(GOLDEN_DIR), "--dump-summary")
        self.assertEqual(r.returncode, 0, r.stderr)
        for text in ("contract           forge.engine-contract v1", "seed               1337",
                     "generator          forge.sword v1", "socket_tip         node 6, translation [0.0, 0.60488361120224, 0.0] m",
                     "collision_hull (node 7, scene 1 'forge_collision'): convex_hull, 49 vertices, 94 triangles, closed",
                     "LOD0: 4 nodes, 379 vertices, 280 triangles (LOD0 only)",
                     "right-handed, +Y up, meters (meters_per_unit 1), origin grip_center"):
            self.assertIn(text, r.stdout)
        d = json.loads(run_no_tk(str(GOLDEN_DIR), "--dump-summary", "--json").stdout)
        self.assertEqual(d["asset"]["seed"], "1337")
        self.assertEqual(d["contract"], {"id": "forge.engine-contract", "version": 1})
        self.assertEqual([m["metallic_factor"] for m in d["materials"]], [1.0, 1.0, 0.0, 1.0])
        self.assertEqual(d["lods"]["levels"][0]["triangles"], 280)
        self.assertEqual(d["tags"][0], "asset_type:short_sword")

    def test_refusals_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.forgepkg"
            shutil.copytree(GOLDEN_DIR, bad)
            (bad / "manifest.json").unlink()
            r = run_no_tk(str(bad), "--validate-only")
            self.assertEqual(r.returncode, 3)
            self.assertIn("refused [missing_manifest]", r.stderr)
            r = run_no_tk(str(bad), "--dump-summary", "--json")
            self.assertEqual((r.returncode, json.loads(r.stdout)["code"]), (3, "missing_manifest"))
            r = run_no_tk(str(bad))                         # GUI mode refuses before any window or tkinter import
            self.assertEqual(r.returncode, 3)
        r = run_no_tk(str(GOLDEN_DIR))                      # valid package, GUI requested, no tkinter available
        self.assertEqual(r.returncode, 1)
        self.assertIn("needs Tkinter", r.stderr)
        self.assertEqual(run_main("--validate-only")[0], 2)
        self.assertEqual(run_main(str(GOLDEN_DIR), "--json")[0], 2)
        self.assertEqual(run_main(str(GOLDEN_DIR), "--validate-only", "--dump-summary")[0], 2)


if __name__ == "__main__":
    unittest.main()
