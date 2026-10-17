"""Tests of the parts that do not need Blender: the runner's contract (fake launcher) and the verifier (synthetic GLBs).

    python3 -m unittest experiments/blender_bridge/test_bridge.py
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge  # noqa: E402
import verify  # noqa: E402


def write_glb(path, P, F, name="m"):
    """Minimal single-primitive GLB (positions, normals, indices) for tests."""
    P = np.asarray(P, "<f4")
    N = np.tile(np.array([0, 0, 1], "<f4"), (len(P), 1))
    I = np.asarray(F, "<u4").ravel()
    blob = P.tobytes() + N.tobytes() + I.tobytes()
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": P.nbytes}, {"buffer": 0, "byteOffset": P.nbytes, "byteLength": N.nbytes},
             {"buffer": 0, "byteOffset": P.nbytes + N.nbytes, "byteLength": I.nbytes}]
    g = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
         "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
         "materials": [{"name": "m", "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.5, 0.5, 1]}}],
         "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(P), "type": "VEC3", "min": P.min(0).tolist(), "max": P.max(0).tolist()},
                       {"bufferView": 1, "componentType": 5126, "count": len(P), "type": "VEC3"},
                       {"bufferView": 2, "componentType": 5125, "count": len(I), "type": "SCALAR"}],
         "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(g).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\0") + blob
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def grid(n=8, z=0.0):
    xs = np.linspace(0, 1, n)
    P = np.array([[x, y, z] for y in xs for x in xs])
    F = [[j * n + i, j * n + i + 1, (j + 1) * n + i] for j in range(n - 1) for i in range(n - 1)]
    F += [[j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i] for j in range(n - 1) for i in range(n - 1)]
    return P, np.array(F)


STUB = textwrap.dedent("""
    import json, sys
    from pathlib import Path
    job = Path(sys.argv[-1]); out = job.parent / "output"
    mode = json.loads(job.read_text()).get("params", {}).get("stub", "ok")
    if mode == "stray": (job.parent / "stray.txt").write_text("x")
    if mode == "sleep":
        import time; time.sleep(5)
    (out / "result.glb").write_bytes(b"glb")
    (out / "report.json").write_text(json.dumps({"ok": mode != "fail"}))
""")


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "in.glb").write_bytes(b"source bytes")
        self.stub = self.tmp / "stub.py"
        self.stub.write_text(STUB)

    def job(self, **kw):
        j = {"schema": "forge.blender-job", "schema_version": 1, "operation": "simplify", "input": "in.glb",
             "input_sha256": bridge.sha256(self.tmp / "in.glb"), "output": "result.glb", "params": {}}
        j.update(kw)
        p = self.tmp / "job.json"
        p.write_text(json.dumps(j))
        return p

    def run_stub(self, **kw):
        with mock.patch.object(bridge, "JOB_SCRIPT", self.stub):
            return bridge.run(self.job(**kw), "bpy", sys.executable, self.tmp / "jobs", timeout=3, check_version=False)

    def test_contract_rejects_bad_jobs(self):
        for bad in ({"schema": "x"}, {"operation": "rig_everything"}, {"output": "../escape.glb"}, {"output": "x.blend"}, {"input_sha256": ""}):
            with self.assertRaises(bridge.BridgeError, msg=bad):
                bridge.load_job(self.job(**bad))

    def test_checksum_mismatch_refused_before_blender_runs(self):
        with self.assertRaises(bridge.BridgeError):
            self.run_stub(input_sha256="0" * 64)
        self.assertFalse((self.tmp / "jobs").exists())

    def test_successful_job_is_sandboxed_and_hashed(self):
        r = self.run_stub()
        jd = Path(r["job_dir"])
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["input_unchanged"])
        self.assertEqual(set(r["outputs"]), {"report.json", "result.glb"})
        self.assertFalse(os.access(jd / "input.glb", os.W_OK) and os.geteuid() != 0)
        self.assertEqual((self.tmp / "in.glb").read_bytes(), b"source bytes")
        self.assertTrue((jd / "result.json").is_file())

    def test_failures_are_reported_not_hidden(self):
        self.assertFalse(self.run_stub(params={"stub": "fail"})["ok"])
        r = self.run_stub(params={"stub": "stray"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["unexpected_files"], ["stray.txt"])
        r = self.run_stub(params={"stub": "sleep"})
        self.assertEqual(r["exit_code"], "timeout")
        self.assertFalse(r["ok"])

    def test_version_pin_fails_closed(self):
        fake = subprocess.CompletedProcess([], 0, stdout="BLENDER_VERSION 4.2.0\n", stderr="")
        with mock.patch.object(bridge.subprocess, "run", return_value=fake):
            with self.assertRaises(bridge.BridgeError):
                bridge.run(self.job(), "bpy", "python", self.tmp / "jobs")
        with self.assertRaises(bridge.BridgeError):
            bridge.blender_version("bpy", str(self.tmp / "no-such-python"))


class VerifierTest(unittest.TestCase):
    """verify.py on synthetic outputs: a correct extraction passes; moved, rescaled or incomplete ones fail."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        P, F = grid()
        self.P, self.F = P, F
        self.box = {"centre": [0.25, 0.5, 0.0], "axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "half": [0.3, 0.6, 0.1]}
        write_glb(self.tmp / "input.glb", P, F)
        inside = verify.in_boxes(P, [self.box])
        self.sel = F[inside[F].all(1)]

    def check(self, P, F):
        jd = self.tmp / "job"
        (jd / "output").mkdir(parents=True, exist_ok=True)
        used = np.unique(F)
        remap = -np.ones(len(P), int)
        remap[used] = np.arange(len(used))
        write_glb(jd / "output" / "out.glb", P[used], remap[F])
        job = {"operation": "extract_region", "input": "x.glb", "output": "out.glb", "params": {"boxes": [self.box], "keep_largest": True}}
        (jd / "result.json").write_text(json.dumps({"job": job}))
        with mock.patch.object(sys, "argv", ["verify.py", str(jd), "--source", str(self.tmp / "input.glb")]), mock.patch("builtins.print"):
            verify.main()
        return json.loads((jd / "verify.json").read_text())

    def test_correct_extraction_passes(self):
        v = self.check(self.P, self.sel)
        self.assertTrue(v["pass"], v)
        self.assertEqual(v["extract"]["open_boundary_loops"], 1)

    def test_moved_rescaled_or_partial_output_fails(self):
        moved = self.P.copy()
        moved[self.sel[0, 0]] += [0, 0, 0.001]
        self.assertFalse(self.check(moved, self.sel)["pass"])
        self.assertFalse(self.check(self.P * 1.01, self.sel)["pass"])
        self.assertFalse(self.check(self.P, self.sel[:-2])["pass"])


if __name__ == "__main__":
    unittest.main()
