"""Step 5B tests 38, 39 and 59: generic record persistence for the hafted families.

38  a record saves for every family
39  reloading it reproduces geometry, materials, preview and the GLB package
59  records are deterministic, byte for byte, and the seed-1337 golden records reproduce
Records go through the unchanged generic forge.record module: there is no family-specific schema.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge.catalog import ASSET_ENTRIES, ASSETS, ENGINE_ADAPTERS, EXPORTERS, GENERATORS, PREVIEWS, PRESENTATIONS, REGISTRY
from forge.engine.package import build_engine_package
from forge.errors import RecordIntegrityError, UnknownAssetTypeError, UnknownGeneratorError
from forge.hashing import geometry_sha256
from forge.record import build_record, dumps_record, load_record, loads_record, save_record, validate_record
from forge.registry import build_registry, render_asset_preview
from forge.render.settings import PreviewSettings
from forge_test_support import REPO_ROOT, float_bits
from hafted_support import COMPONENTS, EXAMPLES, FAMILIES, GENERATOR_IDS, HAFTED_GOLDEN, LINEUP_SEEDS, presented, sha256

SMALL = PreviewSettings(1, "three_quarter", 48, 96, 1)


def record_for(family, seed, preview=True, version="test"):
    p = presented(family, seed)
    image = render_asset_preview(REGISTRY, p, SMALL) if preview else None
    return build_record(p, image, forge_version=version)


class TestRecords(unittest.TestCase):
    def test_38_records_save_for_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    path = save_record(record_for(family, 7), Path(tmp) / f"{family}.json")
                    data = json.loads(path.read_text(encoding="ascii"))
                    self.assertEqual((data["asset_type"], data["generator"], data["generator_version"], data["seed"]),
                                     (family, GENERATOR_IDS[family], 1, "7"))
                    self.assertEqual(sorted(data["presentation"]["materials"]), sorted(COMPONENTS[family]))
                    self.assertEqual(sorted(data["integrity"]), ["geometry_sha256", "materials_sha256", "normals_sha256",
                                                                 "record_content_sha256", "uvs_sha256"])
                    self.assertEqual(data["record_format"], "black-lantern-forge/asset-record")
                    self.assertEqual(data["record_version"], 1)
                    validate_record(data)

    def test_39_reload_reproduces_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                for seed in LINEUP_SEEDS:
                    with self.subTest(family=family, seed=seed):
                        rec = record_for(family, seed, preview=True)
                        path = save_record(rec, Path(tmp) / f"{family}{seed}.json")
                        loaded = load_record(path)
                        self.assertEqual(loaded.verified, ("record_content_sha256", "materials", "geometry_sha256",
                                                           "normals_sha256", "uvs_sha256", "materials_sha256"))
                        self.assertEqual(float_bits(loaded.asset), float_bits(presented(family, seed).asset))
                        self.assertEqual(loaded.presented.materials, presented(family, seed).materials)
                        # the preview reproduces from the record alone
                        again = render_asset_preview(REGISTRY, loaded.presented, loaded.spec.preview)
                        self.assertEqual(again.pixels_sha256, rec["preview"]["pixels_sha256"])
                # the GLB package reproduces from the reloaded asset
                loaded = load_record(save_record(record_for(family, 1337, preview=False), Path(tmp) / f"{family}.json"))
                entry = ASSET_ENTRIES[family]
                pkg = build_engine_package(loaded.asset, loaded.presented, entry.descriptor, ENGINE_ADAPTERS[family],
                                           source_hashes=tuple((k, f(loaded.asset, loaded.presented))
                                                               for k, f in entry.integrity),
                                           exporter=("glb", 1), contract_version=1)
                self.assertEqual(pkg.glb_sha256, HAFTED_GOLDEN[family]["files"]["asset.glb"]["sha256"])
                self.assertEqual(pkg.manifest_sha256, HAFTED_GOLDEN[family]["files"]["manifest.json"]["sha256"])

    def test_59_records_deterministic(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                self.assertEqual(dumps_record(record_for(family, 1337, version="0.6.0")),
                                 dumps_record(record_for(family, 1337, version="0.6.0")))
                g = HAFTED_GOLDEN[family]
                gp = g["preview"]
                p = presented(family)
                image = render_asset_preview(REGISTRY, p, PreviewSettings(1, gp["view"], gp["width"], gp["height"],
                                                                          gp["ssaa"]))
                fresh = dumps_record(build_record(p, image, forge_version="0.6.0")).encode("ascii")
                self.assertEqual(fresh, (EXAMPLES / f"{family}_record_seed1337.json").read_bytes())
                self.assertEqual(sha256(fresh), g["files"]["record.json"]["sha256"])
                self.assertEqual(json.loads(fresh)["integrity"], g["integrity"])

    def test_golden_records_load_and_preview_verifies(self):
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        for family in FAMILIES:
            with self.subTest(family=family):
                loaded = load_record(EXAMPLES / f"{family}_record_seed1337.json")
                self.assertEqual(geometry_sha256(loaded.asset), HAFTED_GOLDEN[family]["integrity"]["geometry_sha256"])
                with tempfile.TemporaryDirectory() as tmp:
                    r = subprocess.run([sys.executable, "-m", "forge", "preview",
                                        str(EXAMPLES / f"{family}_record_seed1337.json"), "--out", str(Path(tmp) / "p.png")],
                                       cwd=tmp, env=env, capture_output=True, text=True, timeout=300)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("verified against record", r.stdout)


class TestFailClosed(unittest.TestCase):
    def test_tampering_and_wrong_identity_are_refused(self):
        base = json.loads(dumps_record(record_for("mace", 42, preview=False)))
        rec = dict(base, seed="43")
        with self.assertRaises(RecordIntegrityError):
            loads_record(json.dumps(rec))
        for generator in ("forge.sword", "forge.dagger", "forge.war_hammer"):
            with self.assertRaises(UnknownGeneratorError):
                validate_record(dict(base, generator=generator))

    def test_a_registry_without_the_hafted_families_refuses_their_records(self):
        blades_only = build_registry(assets=ASSETS[:5], generators=GENERATORS[:5], presentations=PRESENTATIONS[:2],
                                     exporters=EXPORTERS, previews=PREVIEWS)
        text = dumps_record(record_for("one_hand_axe", 1, preview=False))
        with self.assertRaises(UnknownAssetTypeError):
            loads_record(text, registry=blades_only)
        loads_record(text)


if __name__ == "__main__":
    unittest.main()
