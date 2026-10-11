"""Step 2 CLI: sword --save/--preview/--obj-format, load, preview. Step 1 CLI unchanged."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge.record import record_content_sha256
from forge.render import decode_png
from forge.hashing import pixels_sha256
from forge_test_support import REPO_ROOT, sha256
from step2_support import GOLDEN_1337

SMALL_ARGS = ["--width", "96", "--height", "192", "--ssaa", "1"]


def run(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run([sys.executable, "-m", "forge", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


class TestStep2Cli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def save(self, seed="1337"):
        res = run("sword", "--seed", seed, "--save", "r.json", "--preview", "p.png", *SMALL_ARGS, cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res

    def test_step1_invocation_is_unchanged(self):
        res = run("sword", "--seed", "1337", cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sorted(p.name for p in (self.tmp / "output").iterdir()), ["short_sword_seed1337_v1.obj"])
        self.assertIn(GOLDEN_1337["obj_format1_sha256"], res.stdout)
        for step2_word in ("record", "preview", "pixels", "materials"):
            self.assertNotIn(step2_word, res.stdout)

    def test_sword_save_and_preview(self):
        res = self.save()
        record = json.loads((self.tmp / "r.json").read_text())
        self.assertEqual(record["seed"], "1337")
        self.assertEqual(record["integrity"]["obj_format1_sha256"], GOLDEN_1337["obj_format1_sha256"])
        w, h, pixels, text = decode_png((self.tmp / "p.png").read_bytes())
        self.assertEqual((w, h), (96, 192))
        self.assertEqual(record["preview"]["pixels_sha256"], pixels_sha256(w, h, pixels))
        meta = json.loads(text["forge.preview"])
        self.assertEqual(meta["record_content_sha256"], record["integrity"]["record_content_sha256"])
        self.assertIn(record["integrity"]["record_content_sha256"], res.stdout)

    def test_load_verifies_and_reexports(self):
        self.save()
        res = run("load", "r.json", "--out", "again.obj", cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("asset record verified", res.stdout)
        self.assertEqual(sha256((self.tmp / "again.obj").read_bytes()), GOLDEN_1337["obj_format1_sha256"])
        res = run("load", "r.json", "--json", "--out", "rich.obj", "--obj-format", "2", cwd=self.tmp)
        report = json.loads(res.stdout)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["generator_version"], 1)
        self.assertEqual(report["uv_version"], 1)
        self.assertIn("uvs_sha256", report["checks_passed"])
        self.assertTrue((self.tmp / "rich.mtl").is_file())

    def test_preview_from_record_verifies_pixels(self):
        self.save()
        res = run("preview", "r.json", cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("verified against record", res.stdout)
        self.assertEqual(decode_png((self.tmp / "r_three_quarter.png").read_bytes())[2],
                         decode_png((self.tmp / "p.png").read_bytes())[2])
        res = run("preview", "r.json", "--view", "side", "--out", "side.png", cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not compared", res.stdout)
        self.assertTrue((self.tmp / "side.png").is_file())

    def test_sword_enriched_obj(self):
        res = run("sword", "--seed", "5", "--obj-format", "2", "--out", "s.obj", cwd=self.tmp)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("mtllib s.mtl", (self.tmp / "s.obj").read_text())
        self.assertTrue((self.tmp / "s.mtl").is_file())

    def test_malformed_and_unsupported_records_exit_2(self):
        self.save()
        good = json.loads((self.tmp / "r.json").read_text())
        cases = {
            "garbage.json": "{not json",
            "noseed.json": json.dumps({k: v for k, v in good.items() if k != "seed"}),
            "v9.json": json.dumps({**good, "record_version": 9}),
            "uv2.json": json.dumps({**good, "presentation": {**good["presentation"], "uv_version": 2}}),
        }
        for name, text in cases.items():
            (self.tmp / name).write_text(text)
            for cmd in ("load", "preview"):
                with self.subTest(file=name, cmd=cmd):
                    res = run(cmd, name, cwd=self.tmp)
                    self.assertEqual(res.returncode, 2, res.stdout)
                    self.assertIn("forge: error:", res.stderr)
        self.assertEqual(run("load", "missing.json", cwd=self.tmp).returncode, 2)

    def test_tampered_records_exit_3(self):
        self.save()
        rec = json.loads((self.tmp / "r.json").read_text())
        rec["presentation"]["materials"]["blade"]["roughness"] = 0.9
        (self.tmp / "t1.json").write_text(json.dumps(rec))           # content hash now stale
        rec["integrity"]["record_content_sha256"] = record_content_sha256(rec)
        (self.tmp / "t2.json").write_text(json.dumps(rec))           # resealed; materials don't reproduce
        for name in ("t1.json", "t2.json"):
            res = run("load", name, cwd=self.tmp)
            self.assertEqual(res.returncode, 3, name)
            self.assertIn("verification failed", res.stderr)

        rec = json.loads((self.tmp / "r.json").read_text())
        rec["preview"]["pixels_sha256"] = "0" * 64
        rec["integrity"]["record_content_sha256"] = record_content_sha256(rec)
        (self.tmp / "t3.json").write_text(json.dumps(rec))
        res = run("preview", "t3.json", cwd=self.tmp)
        self.assertEqual(res.returncode, 3)
        self.assertIn("pixels_sha256", res.stderr)
        self.assertFalse((self.tmp / "t3_three_quarter.png").exists())

    def test_invalid_step2_flags_write_nothing(self):
        for args in (["--save", "r.txt"], ["--preview", "p.jpg"], ["--preview", "p.png", "--ssaa", "9"],
                     ["--preview", "p.png", "--width", "4"]):
            with self.subTest(args=args):
                res = run("sword", "--seed", "1", *args, cwd=self.tmp)
                self.assertEqual(res.returncode, 2, res.stdout)
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
