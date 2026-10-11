"""Step 2: asset record persistence, reload, validation, and canonical hashing."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from forge.errors import (
    InvalidSeedError,
    RecordFormatError,
    RecordIntegrityError,
    UnsupportedGeneratorVersionError,
    UnsupportedVersionError,
)
from forge.hashing import canonical_json, uvs_sha256, normals_sha256
from forge.record import (
    CONVENTIONS_V1,
    build_record,
    dumps_record,
    load_record,
    loads_record,
    record_content_sha256,
    save_record,
    validate_record,
)
from forge.render.settings import DEFAULT_PREVIEW
from forge_test_support import REPO_ROOT, float_bits
from step2_support import GOLDEN_1337, GOLDEN_1337_RECORD_CONTENT_NO_PREVIEW, presented


def fresh_record(seed=1337, **kw):
    return build_record(presented(seed), **kw)


def reseal(rec):
    """Recompute record_content_sha256 after an intentional edit (to test deeper checks)."""
    rec["integrity"]["record_content_sha256"] = record_content_sha256(rec)
    return rec


class TestSaveReload(unittest.TestCase):
    def roundtrip(self, seed):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_record(fresh_record(seed, preview=DEFAULT_PREVIEW), Path(tmp) / "r.json")
            return load_record(path)

    def test_9_reload_reproduces_seed(self):
        for seed in (0, 1337, (1 << 64) - 1):
            self.assertEqual(self.roundtrip(seed).asset.seed, seed)

    def test_10_reload_reproduces_generator_version(self):
        loaded = self.roundtrip(1337)
        self.assertEqual(loaded.asset.generator_version, 1)
        self.assertEqual(loaded.spec.generator_version, 1)

    def test_11_reload_reproduces_material_state(self):
        loaded = self.roundtrip(1337)
        self.assertEqual(loaded.presented.materials, presented(1337).materials)
        self.assertIn("materials", loaded.verified)
        self.assertIn("materials_sha256", loaded.verified)

    def test_12_reload_reproduces_uv_and_normal_state(self):
        loaded = self.roundtrip(1337)
        self.assertEqual(uvs_sha256(loaded.presented), GOLDEN_1337["uvs_sha256"])
        self.assertEqual(normals_sha256(loaded.presented), GOLDEN_1337["normals_sha256"])
        self.assertEqual(float_bits(loaded.asset), float_bits(presented(1337).asset))
        self.assertEqual(loaded.presented.versions, presented(1337).versions)
        self.assertEqual(loaded.spec.preview, DEFAULT_PREVIEW)

    def test_all_integrity_checks_run(self):
        loaded = self.roundtrip(7)
        self.assertEqual(set(loaded.verified), {"record_content_sha256", "materials", "geometry_sha256",
                                                "obj_format1_sha256", "normals_sha256", "uvs_sha256",
                                                "materials_sha256"})

    def test_recipe_only_record_without_integrity_loads(self):
        rec = fresh_record(include_integrity=False)
        loaded = loads_record(dumps_record(rec))
        self.assertEqual(loaded.verified, ("materials",))
        self.assertEqual(loaded.asset.seed, 1337)

    def test_record_contains_no_geometry_and_no_timestamps(self):
        text = dumps_record(fresh_record())
        for forbidden in ("positions", "triangles", "vertices", "created", "timestamp", "date", "time"):
            self.assertNotIn(f'"{forbidden}', text)
        self.assertLess(len(text), 5000)

    def test_example_record_loads_and_verifies(self):
        loaded = load_record(REPO_ROOT / "examples" / "asset_record_seed1337.json")
        self.assertEqual(loaded.asset.seed, 1337)
        self.assertIn("record_content_sha256", loaded.verified)


class TestCanonicalHashes(unittest.TestCase):
    def test_15a_canonical_hashes_reproduce_exactly(self):
        rec = fresh_record(forge_version="any")
        self.assertEqual(record_content_sha256(rec), GOLDEN_1337_RECORD_CONTENT_NO_PREVIEW)
        for key, value in GOLDEN_1337.items():
            self.assertEqual(rec["integrity"][key], value, key)

    def test_15b_saving_twice_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = save_record(fresh_record(), Path(tmp) / "a.json").read_bytes()
            b = save_record(fresh_record(), Path(tmp) / "b.json").read_bytes()
            self.assertEqual(a, b)
            c = save_record(load_record(Path(tmp) / "a.json").spec.raw, Path(tmp) / "c.json").read_bytes()
            self.assertEqual(a, c)

    def test_15c_content_hash_ignores_formatting_key_order_and_info(self):
        rec = fresh_record()
        base = record_content_sha256(rec)
        shuffled = json.loads(json.dumps(rec, indent=None, sort_keys=False))
        shuffled = dict(reversed(list(shuffled.items())))
        self.assertEqual(record_content_sha256(shuffled), base)
        noted = copy.deepcopy(rec)
        noted["info"] = {"note": "edited by hand", "forge_version": "9.9.9"}
        self.assertEqual(record_content_sha256(noted), base)
        loads_record(json.dumps(noted, indent=4))  # still verifies

    def test_15d_canonical_json_form(self):
        self.assertEqual(canonical_json({"b": [1.0, 0.1], "a": "x"}), b'{"a":"x","b":[1.0,0.1]}')
        with self.assertRaises(ValueError):
            canonical_json({"x": float("nan")})


class TestMalformedRecords(unittest.TestCase):
    """13. Malformed records refuse clearly."""

    def assertRefuses(self, mutate, exc=RecordFormatError, needle=None):
        rec = copy.deepcopy(fresh_record())
        mutate(rec)
        with self.assertRaises(exc) as ctx:
            loads_record(json.dumps(rec))
        if needle:
            self.assertIn(needle, str(ctx.exception))

    def test_bad_json_and_shapes(self):
        for text in ("", "{", "[]", "42", '"x"', "null", '{"a":1,"a":2}', '{"x": NaN}', '{"x": Infinity}'):
            with self.subTest(text=text):
                with self.assertRaises(RecordFormatError):
                    loads_record(text)

    def test_missing_and_unknown_fields(self):
        for key in ("record_format", "record_version", "asset_type", "generator", "generator_version",
                    "seed", "conventions", "presentation"):
            with self.subTest(missing=key):
                self.assertRefuses(lambda r, k=key: r.pop(k), needle=key)
        self.assertRefuses(lambda r: r.update(vertices=[1, 2, 3]), needle="vertices")
        self.assertRefuses(lambda r: r["presentation"].update(shader="x"), needle="shader")
        self.assertRefuses(lambda r: r["presentation"].pop("uv_version"), needle="uv_version")
        self.assertRefuses(lambda r: r["presentation"]["materials"].pop("grip"), needle="grip")
        self.assertRefuses(lambda r: r["presentation"]["materials"].update(scabbard={}), needle="scabbard")
        self.assertRefuses(lambda r: r["integrity"].update(made_up_sha256="0" * 64), needle="made_up")

    def test_wrong_identity_fields(self):
        self.assertRefuses(lambda r: r.update(record_format="something-else"), needle="record_format")
        self.assertRefuses(lambda r: r.update(asset_type="long_sword"), needle="asset_type")
        self.assertRefuses(lambda r: r.update(generator="forge.axe"), needle="generator")

    def test_invalid_seeds(self):
        for bad in (1337, "-1", "1.5", "0x10", " 1337", "", "18446744073709551616", None, True):
            with self.subTest(seed=bad):
                self.assertRefuses(lambda r, b=bad: r.update(seed=b), exc=InvalidSeedError, needle="seed")

    def test_unknown_or_altered_conventions(self):
        self.assertRefuses(lambda r: r["conventions"].update(id="z-up-centimeters"), needle="convention")
        self.assertRefuses(lambda r: r["conventions"].update(units="centimeters"), needle="conventions")
        self.assertRefuses(lambda r: r.update(conventions="rh-y-up"), needle="convention")
        self.assertEqual(fresh_record()["conventions"], CONVENTIONS_V1)

    def test_bad_types(self):
        self.assertRefuses(lambda r: r.update(presentation=[]), needle="presentation")
        self.assertRefuses(lambda r: r["presentation"]["materials"].update(blade="steel"), needle="blade")
        self.assertRefuses(lambda r: r["integrity"].update(geometry_sha256="abc"), needle="geometry_sha256")
        self.assertRefuses(lambda r: r["integrity"].update(geometry_sha256="A" * 64), needle="geometry_sha256")
        self.assertRefuses(lambda r: r.update(info="note"), needle="info")
        self.assertRefuses(lambda r: r.update(preview={"view": "front"}), needle="preview")
        self.assertRefuses(lambda r: r.update(preview={**DEFAULT_PREVIEW.to_dict(), "view": "top"}), needle="view")
        self.assertRefuses(lambda r: r.update(preview={**DEFAULT_PREVIEW.to_dict(), "width": 0}), needle="width")

    def test_file_level_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RecordFormatError):
                load_record(Path(tmp) / "missing.json")
            bad = Path(tmp) / "bad.json"
            bad.write_bytes(b"\xff\xfe{}")
            with self.assertRaises(RecordFormatError):
                load_record(bad)
            with self.assertRaises(RecordFormatError):
                save_record(fresh_record(), Path(tmp) / "record.txt")
            broken = fresh_record()
            broken["seed"] = "nope"
            with self.assertRaises(InvalidSeedError):
                save_record(broken, Path(tmp) / "x.json")
            self.assertFalse((Path(tmp) / "x.json").exists())


class TestUnsupportedVersions(unittest.TestCase):
    """14. Unsupported versions refuse clearly. Never upgraded or defaulted."""

    def test_each_version_field(self):
        cases = [
            (lambda r: r.update(record_version=2), UnsupportedVersionError, "record_version"),
            (lambda r: r.update(generator_version=2), UnsupportedGeneratorVersionError, "generator_version"),
            (lambda r: r["presentation"].update(presentation_version=2), UnsupportedVersionError, "presentation_version"),
            (lambda r: r["presentation"].update(normals_version=2), UnsupportedVersionError, "normals_version"),
            (lambda r: r["presentation"].update(uv_version=0), UnsupportedVersionError, "uv_version"),
            (lambda r: r["presentation"].update(material_version=99), UnsupportedVersionError, "material_version"),
            (lambda r: r["presentation"].update(uv_version="1"), UnsupportedVersionError, "uv_version"),
            (lambda r: r["presentation"].update(material_version=1.0), UnsupportedVersionError, "material_version"),
            (lambda r: r["presentation"].update(normals_version=True), UnsupportedVersionError, "normals_version"),
            (lambda r: r.update(preview={**DEFAULT_PREVIEW.to_dict(), "preview_version": 2}),
             UnsupportedVersionError, "preview_version"),
        ]
        for mutate, exc, needle in cases:
            with self.subTest(field=needle):
                rec = copy.deepcopy(fresh_record())
                mutate(rec)
                with self.assertRaises(exc) as ctx:
                    validate_record(rec)
                self.assertIn(needle, str(ctx.exception))
                self.assertIn("supported", str(ctx.exception))


class TestTamperDetection(unittest.TestCase):
    def test_edited_recipe_fails_content_hash(self):
        rec = fresh_record()
        rec["seed"] = "1338"
        with self.assertRaises(RecordIntegrityError) as ctx:
            loads_record(json.dumps(rec))
        self.assertIn("record_content_sha256", str(ctx.exception))

    def test_edited_material_fails_reproduction(self):
        rec = fresh_record()
        rec["presentation"]["materials"]["grip"]["roughness"] = 0.5
        reseal(rec)
        with self.assertRaises(RecordIntegrityError) as ctx:
            loads_record(json.dumps(rec))
        self.assertIn("presentation.materials.grip.roughness", str(ctx.exception))

    def test_material_type_change_is_detected(self):
        rec = fresh_record(include_integrity=False)
        rec["presentation"]["materials"]["blade"]["metallic"] = 1  # int, not float
        with self.assertRaises(RecordIntegrityError):
            loads_record(json.dumps(rec))

    def test_wrong_hash_values_fail(self):
        for key in ("geometry_sha256", "obj_format1_sha256", "normals_sha256", "uvs_sha256", "materials_sha256"):
            with self.subTest(key=key):
                rec = fresh_record()
                rec["integrity"][key] = "0" * 64
                reseal(rec)
                with self.assertRaises(RecordIntegrityError) as ctx:
                    loads_record(json.dumps(rec))
                self.assertIn(key, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
