"""Step 5B tests 50-55: the unchanged Step 4 viewer ingests every hafted family with no family code.

50-53  the independent viewer ingests each family's package (the goldens, and fresh exports)
54     the viewer imports nothing from Forge (no generator, no family code); its sources are unchanged
55     the viewer names no hafted family and has no branch on one
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge.catalog import REGISTRY
from forge.registry import export_asset
from forge_engine_viewer.ingest import ingest
from forge_engine_viewer.render import MODES, Camera, build_frame
from forge_engine_viewer.session import ViewerSession
from forge_engine_viewer.summary import summary_dict, summary_lines
from forge_test_support import REPO_ROOT
from hafted_support import COMPONENTS, EXAMPLES, FAMILIES, HAFTED_GOLDEN, LINEUP_SEEDS, NEW_IDENTIFIERS, presented, sha256

VIEWER_PKG = REPO_ROOT / "forge_engine_viewer"
STEP4_VIEWER = json.loads((REPO_ROOT / "tests" / "arsenal_frozen_sources.json").read_text())["viewer"]


def golden_dir(family):
    return EXAMPLES / f"{family}_seed1337_v1.forgepkg"


class TestIngest(unittest.TestCase):
    """50-53."""

    def check(self, family):
        g = HAFTED_GOLDEN[family]
        pkg = ingest(golden_dir(family))
        self.assertEqual((pkg.contract_id, pkg.contract_version), ("forge.engine-contract", 1))
        self.assertEqual(pkg.asset["asset_type"], family)
        self.assertEqual(pkg.root, family)
        self.assertEqual(tuple(m.node for m in pkg.meshes), COMPONENTS[family])
        self.assertEqual(sum(len(m.positions) for m in pkg.meshes), g["lod0"]["vertices"])
        self.assertEqual(sum(m.triangle_count for m in pkg.meshes), g["lod0"]["triangles"])
        self.assertEqual((len(pkg.checks), len(pkg.hashes_verified)), (16, 9))
        self.assertEqual(pkg.glb_sha256, g["files"]["asset.glb"]["sha256"])
        self.assertEqual({s.name: list(s.world.apply((0.0, 0.0, 0.0))) for s in pkg.sockets},
                         {k: v["translation"] for k, v in g["sockets"].items()})
        self.assertEqual((len(pkg.collision.positions), pkg.collision.triangle_count),
                         (g["collision"]["vertices"], g["collision"]["triangles"]))
        self.assertTrue(pkg.collision.closed)
        self.assertEqual(summary_dict(pkg)["asset"]["asset_type"], family)
        self.assertTrue(any(family in line for line in summary_lines(pkg)))
        for mode in MODES:
            for preset in ("three_quarter", "front", "side"):
                frame = build_frame(pkg, width=320, height=640, camera=Camera.preset(preset), mode=mode, show_sockets=True)
                self.assertGreater(len(frame.items), 0)
                markers = [i for i in frame.layer("socket") if type(i).__name__ == "Marker"]
                self.assertEqual(len(markers), len(g["sockets"]), "every socket is drawn, read from the package")
        session = ViewerSession()
        self.assertTrue(session.open(golden_dir(family)))
        with tempfile.TemporaryDirectory() as tmp:
            for seed in LINEUP_SEEDS[:4]:
                p = presented(family, seed)
                out = Path(tmp) / f"{seed}.forgepkg"
                export_asset(REGISTRY, p.asset, p, "glb", 1, out)
                fresh = ingest(out)
                self.assertEqual((fresh.asset["asset_type"], fresh.asset["seed"]), (family, str(seed)))

    def test_50_viewer_ingests_one_hand_axe(self):
        self.check("one_hand_axe")

    def test_51_viewer_ingests_two_hand_axe(self):
        self.check("two_hand_axe")

    def test_52_viewer_ingests_mace(self):
        self.check("mace")

    def test_53_viewer_ingests_war_hammer(self):
        self.check("war_hammer")
        self.assertEqual(len(ingest(golden_dir("war_hammer")).sockets), 5, "the extra socket comes through as data")

    def test_fresh_process_with_forge_absent_ingests_every_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(VIEWER_PKG, tmp / "forge_engine_viewer", ignore=shutil.ignore_patterns("__pycache__"))
            for family in FAMILIES:
                shutil.copytree(golden_dir(family), tmp / f"{family}.forgepkg")
            env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
            run = lambda *args: subprocess.run([sys.executable, "-E", "-s", *args], cwd=tmp, env=env,
                                               capture_output=True, text=True, timeout=120)
            self.assertNotEqual(run("-c", "import forge").returncode, 0)
            for family in FAMILIES:
                with self.subTest(family=family):
                    r = run("-m", "forge_engine_viewer", f"{family}.forgepkg", "--validate-only")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertTrue(r.stdout.startswith("VALID"))
                    r = run("-m", "forge_engine_viewer", f"{family}.forgepkg", "--dump-summary", "--json")
                    d = json.loads(r.stdout)
                    self.assertEqual(d["asset"]["asset_type"], family)
                    self.assertEqual(sha256((tmp / f"{family}.forgepkg" / "asset.glb").read_bytes()),
                                     HAFTED_GOLDEN[family]["files"]["asset.glb"]["sha256"])


def docstring_ids(t):
    return {id(n.body[0].value) for n in ast.walk(t)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


class TestViewerIndependence(unittest.TestCase):
    SOURCES = sorted(VIEWER_PKG.glob("*.py"))

    def test_54_viewer_needs_no_generator_imports(self):
        self.assertEqual({p.name for p in self.SOURCES}, set(STEP4_VIEWER))
        for path in self.SOURCES:
            self.assertEqual(sha256(path.read_bytes()), STEP4_VIEWER[path.name], f"{path.name} changed since Step 4")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(a.name == "forge" or a.name.startswith("forge.") for a in node.names))
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "") == "forge" or (node.module or "").startswith("forge."))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"__import__", "exec", "eval"})

    def test_55_viewer_contains_no_new_family_branches(self):
        for path in self.SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            skip = docstring_ids(tree)
            for node in ast.walk(tree):
                where = f"{path.name}:{getattr(node, 'lineno', '?')}"
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                    for word in NEW_IDENTIFIERS + ("axe", "hammer", "flange", "hafted"):
                        self.assertNotIn(word, node.value.lower(), f"{where} names a hafted family")
                if isinstance(node, ast.Compare):
                    for c in [node.left, *node.comparators]:
                        if isinstance(c, ast.Constant):
                            self.assertNotIn(c.value, FAMILIES, where)


if __name__ == "__main__":
    unittest.main()
