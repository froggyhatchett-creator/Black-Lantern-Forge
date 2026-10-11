"""Step 5A tests 37, 38 and 59 (+ golden-record and fail-closed checks): generic record persistence.

37  a record saves for every family          38  reloading it reproduces the asset exactly
59  records are deterministic, byte for byte, and the seed-1337 golden records reproduce

Records go through the unchanged generic forge.record module. Nothing here is family-specific
beyond the family names.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from arsenal_support import (
    ARSENAL_GOLDEN,
    COMPONENTS,
    EXAMPLES,
    FAMILIES,
    GENERATOR_IDS,
    LINEUP_SEEDS,
    presented,
    sha256,
)
from forge.catalog import ASSETS, EXPORTERS, GENERATORS, PREVIEWS, PRESENTATIONS, REGISTRY
from forge.errors import RecordIntegrityError, UnknownAssetTypeError, UnknownGeneratorError, UnsupportedVersionError
from forge.hashing import geometry_sha256
from forge.record import build_record, dumps_record, load_record, loads_record, save_record, validate_record
from forge.registry import build_registry, render_asset_preview
from forge.render.settings import PreviewSettings
from forge_test_support import REPO_ROOT, float_bits

SMALL = PreviewSettings(1, "three_quarter", 48, 96, 1)
BLADE_INTEGRITY = ["geometry_sha256", "materials_sha256", "normals_sha256", "record_content_sha256", "uvs_sha256"]


def record_for(family, seed, preview=True, version="test"):
    p = presented(family, seed)
    image = render_asset_preview(REGISTRY, p, SMALL) if preview else None
    return build_record(p, image, forge_version=version)


class TestRecords(unittest.TestCase):
    def test_37_record_saves_per_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                with self.subTest(family=family):
                    rec = record_for(family, 7)
                    path = save_record(rec, Path(tmp) / f"{family}.json")
                    data = json.loads(path.read_text(encoding="ascii"))
                    self.assertEqual((data["asset_type"], data["generator"], data["generator_version"], data["seed"]),
                                     (family, GENERATOR_IDS[family], 1, "7"))
                    self.assertEqual(data["presentation"]["presentation_version"], 1)
                    self.assertEqual(sorted(data["presentation"]["materials"]), sorted(COMPONENTS))
                    self.assertEqual(sorted(data["integrity"]), BLADE_INTEGRITY)
                    self.assertEqual(data["preview"]["preview_version"], 1)
                    self.assertEqual(data["conventions"]["id"], "forge.rh-y-up-meters.grip-origin.v1")
                    validate_record(data)
                    self.assertTrue(path.read_bytes().isascii())

    def test_38_record_reload_reproduces_each_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            for family in FAMILIES:
                for seed in LINEUP_SEEDS:
                    with self.subTest(family=family, seed=seed):
                        path = save_record(record_for(family, seed, preview=False), Path(tmp) / f"{family}{seed}.json")
                        loaded = load_record(path)
                        self.assertEqual(loaded.verified, ("record_content_sha256", "materials", "geometry_sha256",
                                                           "normals_sha256", "uvs_sha256", "materials_sha256"))
                        self.assertEqual(float_bits(loaded.asset), float_bits(presented(family, seed).asset))
                        self.assertEqual(loaded.asset.params, presented(family, seed).asset.params)
                        self.assertEqual(loaded.presented.materials, presented(family, seed).materials)

    def test_59_records_deterministic(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                a = dumps_record(record_for(family, 1337, version="0.5.0"))
                b = dumps_record(record_for(family, 1337, version="0.5.0"))
                self.assertEqual(a, b)
                # the golden: same content hash; with the golden's own preview settings, the same bytes
                g = ARSENAL_GOLDEN[family]
                p = presented(family)
                gp = g["preview"]
                image = render_asset_preview(REGISTRY, p, PreviewSettings(1, gp["view"], gp["width"], gp["height"],
                                                                          gp["ssaa"]))
                fresh = dumps_record(build_record(p, image, forge_version="0.5.0")).encode("ascii")
                example = EXAMPLES / f"{family}_record_seed1337.json"
                self.assertEqual(fresh, example.read_bytes())
                self.assertEqual(sha256(fresh), g["files"]["record.json"]["sha256"])
                self.assertEqual(json.loads(fresh)["integrity"], g["integrity"])
                # the info block is excluded from every hash
                other = dumps_record(build_record(p, image, forge_version="9.9.9"))
                self.assertEqual(json.loads(other)["integrity"], g["integrity"])

    def test_golden_records_load_and_preview_verifies(self):
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        for family in FAMILIES:
            with self.subTest(family=family):
                loaded = load_record(EXAMPLES / f"{family}_record_seed1337.json")
                self.assertEqual(loaded.record_content_sha256, ARSENAL_GOLDEN[family]["integrity"]["record_content_sha256"])
                self.assertEqual(geometry_sha256(loaded.asset), ARSENAL_GOLDEN[family]["integrity"]["geometry_sha256"])
                with tempfile.TemporaryDirectory() as tmp:
                    r = subprocess.run([sys.executable, "-m", "forge", "preview",
                                        str(EXAMPLES / f"{family}_record_seed1337.json"), "--out", str(Path(tmp) / "p.png")],
                                       cwd=tmp, env=env, capture_output=True, text=True, timeout=300)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("verified against record", r.stdout)
                    self.assertEqual((Path(tmp) / "p.png").read_bytes(),
                                     (EXAMPLES / f"{family}_preview_seed1337_three_quarter.png").read_bytes())


class TestFailClosed(unittest.TestCase):
    def base(self, family="curved_sword"):
        return json.loads(dumps_record(record_for(family, 42, preview=False)))

    def test_tampered_records_are_refused(self):
        rec = self.base()
        rec["seed"] = "43"
        with self.assertRaises(RecordIntegrityError):
            loads_record(json.dumps(rec))
        rec = self.base()
        rec["presentation"]["materials"]["blade"]["roughness"] = 0.5
        with self.assertRaises(RecordIntegrityError):
            loads_record(json.dumps(rec))

    def test_wrong_generator_for_the_family_is_refused(self):
        for generator in ("forge.sword", "forge.dagger", "forge.axe"):
            rec = self.base("long_sword")
            rec["generator"] = generator
            with self.assertRaises(UnknownGeneratorError):
                validate_record(rec)

    def test_no_implicit_latest(self):
        for field, value in (("generator_version", 2), ("record_version", 2)):
            rec = self.base()
            rec[field] = value
            with self.assertRaises(Exception):
                validate_record(rec)
        rec = self.base()
        rec["presentation"]["presentation_version"] = 2
        with self.assertRaises(UnsupportedVersionError):
            validate_record(rec)

    def test_a_registry_without_the_family_refuses_its_records(self):
        """Persistence routes through the registry; it does not know the families by itself."""
        short_only = build_registry(assets=ASSETS[:1], generators=GENERATORS[:1], presentations=PRESENTATIONS[:1],
                                    exporters=EXPORTERS, previews=PREVIEWS)
        self.assertEqual(short_only.asset_types(), ("short_sword",))
        text = dumps_record(record_for("dagger", 1, preview=False))
        with self.assertRaises(UnknownAssetTypeError):
            loads_record(text, registry=short_only)
        loads_record(text)


if __name__ == "__main__":
    unittest.main()
