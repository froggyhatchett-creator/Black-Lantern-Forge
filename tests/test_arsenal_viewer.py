"""Step 5A tests 50-54: the unchanged Step 4 viewer ingests every blade family with no family code.

50-53  the independent viewer ingests each family's package (the goldens, and fresh exports)
54     the viewer imports nothing from Forge and names no asset family; its sources are unchanged
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

from arsenal_support import ARSENAL_GOLDEN, COMPONENTS, EXAMPLES, FAMILIES, LINEUP_SEEDS, presented, sha256
from forge.catalog import REGISTRY
from forge.registry import export_asset
from forge_engine_viewer.ingest import ingest
from forge_engine_viewer.render import MODES, Camera, build_frame
from forge_engine_viewer.session import ViewerSession
from forge_engine_viewer.summary import summary_dict, summary_lines
from forge_test_support import REPO_ROOT

VIEWER_PKG = REPO_ROOT / "forge_engine_viewer"
FAMILY_WORDS = ("dagger", "long_sword", "curved_sword", "great_sword", "short_sword", "sword", "blade-presentation",
                "preview.fit")


def golden_dir(family):
    return EXAMPLES / f"{family}_seed1337_v1.forgepkg"


class TestIngest(unittest.TestCase):
    """50-53."""

    def check(self, family):
        g = ARSENAL_GOLDEN[family]
        pkg = ingest(golden_dir(family))
        self.assertEqual((pkg.contract_id, pkg.contract_version), ("forge.engine-contract", 1))
        self.assertEqual(pkg.asset["asset_type"], family)
        self.assertEqual((pkg.asset["generator_id"], pkg.asset["generator_version"], pkg.asset["seed"]),
                         (g["identity"]["generator_id"], 1, "1337"))
        self.assertEqual(pkg.root, family)
        self.assertEqual(tuple(m.node for m in pkg.meshes), COMPONENTS)
        self.assertEqual(sum(len(m.positions) for m in pkg.meshes), g["lod0"]["vertices"])
        self.assertEqual(sum(m.triangle_count for m in pkg.meshes), g["lod0"]["triangles"])
        self.assertEqual(len(pkg.checks), 16)
        self.assertEqual(len(pkg.hashes_verified), 9)
        self.assertEqual(pkg.glb_sha256, g["files"]["asset.glb"]["sha256"])
        self.assertEqual(pkg.manifest_sha256, g["files"]["manifest.json"]["sha256"])
        for name, expected in g["sockets"].items():
            s = pkg.socket(name)
            self.assertEqual(list(s.world.apply((0.0, 0.0, 0.0))), expected["translation"])
        self.assertEqual((len(pkg.collision.positions), pkg.collision.triangle_count),
                         (g["collision"]["vertices"], g["collision"]["triangles"]))
        self.assertTrue(pkg.collision.closed)
        self.assertEqual(tuple(pkg.tags), tuple(g["tags"]))
        d = summary_dict(pkg)
        self.assertEqual(d["asset"]["asset_type"], family)
        self.assertTrue(any(family in line for line in summary_lines(pkg)))
        for mode in MODES:
            for preset in ("three_quarter", "front", "side"):
                frame = build_frame(pkg, width=320, height=640, camera=Camera.preset(preset), mode=mode,
                                    show_sockets=True)
                self.assertGreater(len(frame.items), 0)
        session = ViewerSession()
        self.assertTrue(session.open(golden_dir(family)))
        self.assertEqual(session.status_kind, "ok")
        # fresh exports of other seeds are ingested the same way
        with tempfile.TemporaryDirectory() as tmp:
            for seed in LINEUP_SEEDS[:5]:
                p = presented(family, seed)
                out = Path(tmp) / f"{seed}.forgepkg"
                export_asset(REGISTRY, p.asset, p, "glb", 1, out)
                fresh = ingest(out)
                self.assertEqual((fresh.asset["asset_type"], fresh.asset["seed"]), (family, str(seed)))
                tip = fresh.socket("socket_tip").world.apply((0.0, 0.0, 0.0))
                self.assertEqual(tip, tuple(fresh_tip(p.asset)))

    def test_50_viewer_ingests_dagger(self):
        self.check("dagger")

    def test_51_viewer_ingests_long_sword(self):
        self.check("long_sword")

    def test_52_viewer_ingests_curved_sword(self):
        self.check("curved_sword")
        tip = ingest(golden_dir("curved_sword")).socket("socket_tip").world.apply((0.0, 0.0, 0.0))
        self.assertLess(tip[0], -0.1)

    def test_53_viewer_ingests_great_sword(self):
        self.check("great_sword")

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
                    r = run("-m", "forge_engine_viewer", f"{family}.forgepkg", "--dump-summary", "--json")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    d = json.loads(r.stdout)
                    self.assertEqual(d["asset"]["asset_type"], family)
                    self.assertEqual({s["name"]: s["translation"] for s in d["sockets"]},
                                     {k: v["translation"] for k, v in ARSENAL_GOLDEN[family]["sockets"].items()})
                    r = run("-m", "forge_engine_viewer", f"{family}.forgepkg", "--validate-only")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertTrue(r.stdout.startswith("VALID"))
                    self.assertEqual(sha256((tmp / f"{family}.forgepkg" / "asset.glb").read_bytes()),
                                     ARSENAL_GOLDEN[family]["files"]["asset.glb"]["sha256"])


def fresh_tip(asset):
    import struct
    return [struct.unpack("<f", struct.pack("<f", c))[0] for c in asset.landmark("blade_tip")]


class TestViewerIndependence(unittest.TestCase):
    """54."""

    # SHA-256 of every viewer source as Step 4 froze it. Step 5A changed none of them.
    STEP4_SOURCES = {
        "__init__.py", "__main__.py", "cli.py", "contract_v1.py", "errors.py", "glb.py", "ingest.py", "render.py",
        "session.py", "summary.py", "window.py",
    }

    def test_54_viewer_has_no_family_specific_generation_import(self):
        sources = sorted(VIEWER_PKG.glob("*.py"))
        self.assertEqual({p.name for p in sources}, self.STEP4_SOURCES)
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                          if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                          and n.body and isinstance(n.body[0], ast.Expr)
                          and isinstance(n.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                where = f"{path.name}:{getattr(node, 'lineno', '?')}"
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name == "forge" or alias.name.startswith("forge."), where)
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    self.assertFalse(mod == "forge" or mod.startswith("forge."), where)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    self.fail(f"dynamic import in {where}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                    for word in FAMILY_WORDS:
                        self.assertNotIn(word, node.value.lower(), f"{where}: the viewer names an asset family")
        for path in sources:
            self.assertEqual(sha256(path.read_bytes()), STEP4_VIEWER_SHA256[path.name], path.name)


STEP4_VIEWER_SHA256 = json.loads((Path(__file__).with_name("arsenal_frozen_sources.json")).read_text())["viewer"]


if __name__ == "__main__":
    unittest.main()
