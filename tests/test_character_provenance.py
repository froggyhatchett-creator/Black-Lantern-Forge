import tempfile
import unittest
from pathlib import Path

from forge_character_studio.provenance import BaseMeshProvenance, BaseMeshRef, load_provenance, save_provenance


def _record(**overrides):
    fields = dict(
        source_name="Blender Studio Human Base Meshes",
        source_url="https://www.blender.org/download/demo/",
        version="1.4.1",
        license_id="CC0-1.0",
        archive_sha256="0" * 64,
        retrieved_date="2026-10-14",
    )
    fields.update(overrides)
    return BaseMeshProvenance(**fields)


class TestBaseMeshRef(unittest.TestCase):
    def test_valid_ref_constructs(self):
        ref = BaseMeshRef(source_name="Blender Studio Human Base Meshes", version="1.4.1",
                          archive_sha256="0" * 64)
        self.assertEqual(ref.source_name, "Blender Studio Human Base Meshes")
        self.assertEqual(ref.version, "1.4.1")
        self.assertEqual(ref.archive_sha256, "0" * 64)

    def test_ref_rejects_malformed_sha256(self):
        with self.assertRaises(ValueError):
            BaseMeshRef(source_name="x", version="1", archive_sha256="not-a-hash")

    def test_ref_rejects_empty_version(self):
        with self.assertRaises(ValueError):
            BaseMeshRef(source_name="x", version="", archive_sha256="0" * 64)


class TestBaseMeshProvenance(unittest.TestCase):
    def test_provenance_round_trips(self):
        record = _record()
        with tempfile.TemporaryDirectory() as tmp:
            path = save_provenance(record, Path(tmp) / "provenance.json")
            self.assertEqual(load_provenance(path), record)

    def test_provenance_rejects_non_cc0_license(self):
        with self.assertRaises(ValueError):
            _record(license_id="CC-BY-4.0")

    def test_provenance_rejects_malformed_sha256(self):
        with self.assertRaises(ValueError):
            _record(archive_sha256="not-a-hash")

    def test_provenance_rejects_uppercase_sha256(self):
        with self.assertRaises(ValueError):
            _record(archive_sha256="A" * 64)

    def test_provenance_rejects_empty_string_fields(self):
        for name in ("source_name", "source_url", "version", "retrieved_date"):
            with self.subTest(field=name):
                with self.assertRaises(ValueError):
                    _record(**{name: ""})

    def test_load_rejects_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_provenance(Path(tmp) / "missing.json")


if __name__ == "__main__":
    unittest.main()
