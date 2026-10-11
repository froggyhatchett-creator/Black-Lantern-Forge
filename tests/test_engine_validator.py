"""Step 3 tests 43-49 (+ extra fail-closed cases): the independent validator refuses bad packages.

Every mutation is rebuilt with self-consistent hashes (engine_support.rehash) when the point is
to prove a *specific* rule fires, not just the hash check.
"""

import copy
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from engine_support import (
    GOLDEN_DIR,
    accessor_rows,
    cached,
    manifest_bytes,
    node,
    presented,
    rehash,
    repack,
    split,
    write_package,
)
from forge.catalog import REGISTRY
from forge.engine.validate import parse_glb, validate_package, validate_package_bytes
from forge.errors import EngineContractError, ExportError
from forge.registry import export_asset


class Base(unittest.TestCase):
    def setUp(self):
        self.pkg = cached()
        self.gltf, self.json_chunk, self.bin = split(self.pkg.glb)
        self.m = copy.deepcopy(self.pkg.manifest_data)

    def refuse(self, glb, manifest, pattern):
        with self.assertRaisesRegex(EngineContractError, pattern):
            validate_package_bytes(glb, manifest)

    def mutate_glb(self, fn, pattern, *, fix_hashes=True):
        gltf = copy.deepcopy(self.gltf)
        fn(gltf)
        glb = repack(gltf, self.bin)
        manifest = rehash(glb, self.m) if fix_hashes else self.pkg.manifest
        self.refuse(glb, manifest, pattern)

    def mutate_manifest(self, fn, pattern, *, fix_hashes=True):
        m = copy.deepcopy(self.m)
        fn(m)
        self.refuse(self.pkg.glb, rehash(self.pkg.glb, m) if fix_hashes else manifest_bytes(m), pattern)


class TestBaseline(Base):
    def test_golden_package_is_valid(self):
        report = validate_package(GOLDEN_DIR)
        self.assertEqual(report.checks[-1], "hashes")
        self.assertEqual(len(report.checks), 24)
        self.assertEqual((report.asset_type, report.seed, report.exporter), ("short_sword", "1337", ("glb", 1)))

    def test_parser_reads_header_json_and_bin_independently(self):
        g = parse_glb(self.pkg.glb)
        self.assertEqual((g.version, g.length), (2, len(self.pkg.glb)))
        self.assertEqual(g.gltf, self.gltf)
        self.assertEqual(g.bin_chunk, self.bin)


class Test43MalformedGlb(Base):
    def test_43_malformed_glb_refuses(self):
        glb = self.pkg.glb
        man = self.pkg.manifest
        cases = {
            "empty": (b"", "shorter than its 12-byte header"),
            "bad magic": (b"gltf" + glb[4:], "magic"),
            "version 1": (glb[:4] + struct.pack("<I", 1) + glb[8:], "container version is 1"),
            "length lies": (glb[:8] + struct.pack("<I", len(glb) + 4) + glb[12:], "header length"),
            "truncated": (glb[:8] + struct.pack("<I", len(glb) - 8) + glb[12:-8], "overruns|length"),
            "trailing bytes": (glb[:8] + struct.pack("<I", len(glb) + 8) + glb[12:] + b"\0" * 8, "exactly a JSON chunk"),
            "chunk type": (glb[:16] + b"JSOX" + glb[20:], "exactly a JSON chunk"),
        }
        bad_json = b"{not json}  "
        cases["json syntax"] = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(bad_json) + 8 + len(self.bin))
                                + struct.pack("<II", len(bad_json), 0x4E4F534A) + bad_json
                                + struct.pack("<II", len(self.bin), 0x004E4942) + self.bin, "not valid JSON")
        dup = b'{"scene":0,"scene":0}   '
        cases["duplicate key"] = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(dup) + 8 + len(self.bin))
                                  + struct.pack("<II", len(dup), 0x4E4F534A) + dup
                                  + struct.pack("<II", len(self.bin), 0x004E4942) + self.bin, "repeats key")
        for name, (data, pattern) in cases.items():
            with self.subTest(case=name):
                self.refuse(data, man, pattern)

    def test_43b_structural_glb_violations_refuse(self):
        def mode_lines(g):
            g["meshes"][0]["primitives"][0]["mode"] = 1

        def extra_attribute(g):
            g["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"] = g["meshes"][0]["primitives"][0]["attributes"]["NORMAL"]

        def accessor_overrun(g):
            g["accessors"][0]["count"] += 1

        def index_out_of_view(g):
            g["bufferViews"][3]["byteOffset"] = g["buffers"][0]["byteLength"]

        def extension_required(g):
            g["extensionsRequired"] = ["KHR_draco_mesh_compression"]

        def bad_minmax(g):
            g["accessors"][1]["max"][1] += 1.0

        def matrix_on_node(g):
            g["nodes"][1]["matrix"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

        def orphan_node(g):
            g["nodes"].append({"name": "stray"})

        for fn, pattern in ((mode_lines, "mode 4"), (extra_attribute, "attributes"),
                            (accessor_overrun, "needs .* bytes"), (index_out_of_view, "runs past"),
                            (extension_required, "unknown fields"), (bad_minmax, "min/max"),
                            (matrix_on_node, "unknown fields"), (orphan_node, "not in any scene")):
            with self.subTest(case=fn.__name__):
                self.mutate_glb(fn, pattern, fix_hashes=False)      # structure is checked before any hash


class Test44To49Refusals(Base):
    def test_44_missing_socket_refuses(self):
        def rename_tip(g):
            node(g, "socket_tip")[1]["name"] = "socket_point"
        self.mutate_glb(rename_tip, "socket_tip")

        def drop_from_manifest(m):
            m["sockets"] = [s for s in m["sockets"] if s["name"] != "socket_tip"]
        self.mutate_manifest(drop_from_manifest, "required socket 'socket_tip' is missing from the manifest")

        def drop_node(g):                       # remove the node and re-index everything after it
            i, _ = node(g, "socket_tip")
            del g["nodes"][i]
            g["nodes"][0]["children"] = [c if c < i else c - 1 for c in g["nodes"][0]["children"] if c != i]
            g["scenes"][1]["nodes"] = [n - 1 for n in g["scenes"][1]["nodes"]]
        self.mutate_glb(drop_node, "socket_tip")

        def grip_moved(g):
            node(g, "socket_grip")[1]["translation"] = [0.0, 0.001, 0.0]
        m = copy.deepcopy(self.m)
        m["sockets"][0]["translation"] = [0.0, 0.001, 0.0]
        gltf = copy.deepcopy(self.gltf)
        grip_moved(gltf)
        glb = repack(gltf, self.bin)
        self.refuse(glb, rehash(glb, m), "must sit exactly at the origin")

    def test_45_missing_collision_refuses(self):
        def rename(g):
            node(g, "collision_hull")[1]["name"] = "hull"
        self.mutate_glb(rename, "collision_hull")

        def drop(g):
            i, n = node(g, "collision_hull")
            del g["nodes"][i]
            del g["meshes"][n["mesh"]]
            del g["scenes"][1]
        self.mutate_glb(drop, "collision_hull")

        def into_render_scene(g):
            i, _ = node(g, "collision_hull")
            g["nodes"][0]["children"].append(i)
            del g["scenes"][1]
        self.mutate_glb(into_render_scene, "scene 1|render hierarchy|collision")

        def with_material(g):
            g["meshes"][node(g, "collision_hull")[1]["mesh"]]["primitives"][0]["material"] = 0
        self.mutate_glb(with_material, "no material")

    def test_46_wrong_units_refuse(self):
        for key, value, pattern in (("units", "centimeters", "units"), ("meters_per_unit", 100, "meters_per_unit"),
                                    ("meters_per_unit", 1.0, "meters_per_unit"), ("up_axis", "+Z", "up_axis"),
                                    ("handedness", "left", "handedness"), ("origin", "pommel_base", "origin")):
            with self.subTest(key=key, value=value):
                self.mutate_manifest(lambda m: m["coordinates"].__setitem__(key, value), pattern)
        self.mutate_manifest(lambda m: m["coordinates"].pop("units"), "units is missing")

    def test_47_wrong_contract_version_refuses(self):
        for bad in (2, 0, "1", True, 1.0, None):
            with self.subTest(version=bad):
                self.mutate_manifest(lambda m: m["contract"].__setitem__("version", bad),
                                     "unsupported contract version", fix_hashes=False)
        self.mutate_manifest(lambda m: m["contract"].pop("version"), "no explicit contract version", fix_hashes=False)
        self.mutate_manifest(lambda m: m["contract"].__setitem__("id", "other.contract"), "contract id", fix_hashes=False)
        self.mutate_glb(lambda g: g["asset"]["extras"]["forge_contract"].__setitem__("version", 2), "identity")

    def test_48_corrupted_bin_refuses(self):
        n = len(self.bin)
        offsets = sorted({(k * 2654435761) % n for k in range(48)} | {0, n - 1, n // 2})
        for off in offsets:
            with self.subTest(offset=off):
                corrupted = bytearray(self.bin)
                corrupted[off] ^= 0x41
                glb = repack(self.gltf, bytes(corrupted))
                with self.assertRaises(EngineContractError):
                    validate_package_bytes(glb, self.pkg.manifest)

    def test_48b_bin_corruption_is_caught_by_the_hash_even_when_structure_survives(self):
        _, n = node(self.gltf, "blade")
        uv = self.gltf["meshes"][n["mesh"]]["primitives"][0]["attributes"]["TEXCOORD_0"]
        view = self.gltf["bufferViews"][self.gltf["accessors"][uv]["bufferView"]]
        corrupted = bytearray(self.bin)
        corrupted[view["byteOffset"]] ^= 0x01                  # nudges one UV mantissa bit: structurally fine
        glb = repack(self.gltf, bytes(corrupted))
        self.refuse(glb, self.pkg.manifest, "hash mismatch: (glb|gltf_bin|render_geometry)")

    def test_49_corrupted_manifest_hash_refuses(self):
        for name in ("glb_sha256", "gltf_bin_sha256", "render_geometry_sha256", "collision_sha256",
                     "sockets_sha256", "semantic_sha256", "manifest_content_sha256"):
            with self.subTest(hash=name):
                m = copy.deepcopy(self.m)
                digest = m["hashes"][name]["sha256"]
                m["hashes"][name]["sha256"] = ("0" if digest[0] != "0" else "1") + digest[1:]
                self.refuse(self.pkg.glb, manifest_bytes(m), "hash mismatch")
        m = copy.deepcopy(self.m)
        m["hashes"]["source_geometry_sha256"]["sha256"] = "0" * 64          # provenance edits break the content hash
        self.refuse(self.pkg.glb, manifest_bytes(m), "hash mismatch: manifest_content_sha256")
        self.mutate_manifest(lambda m: m["hashes"]["glb_sha256"].__setitem__("sha256", m["hashes"]["glb_sha256"]["sha256"].upper()),
                             "64 lowercase hex", fix_hashes=False)
        self.mutate_manifest(lambda m: m["hashes"].pop("collision_sha256"), "missing")
        self.mutate_manifest(lambda m: m["hashes"]["glb_sha256"].__setitem__("covers", "the GLB"), "exactly what")
        self.mutate_manifest(lambda m: m["hashes"].__setitem__(
            "extra_sha256", {"covers": "x", "sha256": "0" * 64, "verifiable_from_package": True}), "provenance")


class TestMoreFailClosed(Base):
    def test_non_canonical_manifest_refuses(self):
        compact = json.dumps(self.m, sort_keys=True).encode()
        self.refuse(self.pkg.glb, compact, "canonical")
        self.refuse(self.pkg.glb, self.pkg.manifest.rstrip(b"\n"), "canonical")
        self.refuse(self.pkg.glb, self.pkg.manifest.replace(b"\n", b"\r\n"), "canonical")

    def test_unknown_or_missing_manifest_sections_refuse(self):
        self.mutate_manifest(lambda m: m.__setitem__("generated_at", "x"), "unknown fields")
        self.mutate_manifest(lambda m: m.pop("tags"), "missing")
        self.mutate_manifest(lambda m: m["tags"].append("Bad Tag"), "tags")
        self.mutate_manifest(lambda m: m["tags"].reverse(), "sorted")
        self.mutate_manifest(lambda m: m["asset"].__setitem__("seed", 1337), "seed")
        self.mutate_manifest(lambda m: m["asset"].__setitem__("seed", "01337"), "seed")
        self.mutate_manifest(lambda m: m["lods"]["levels"].append({**m["lods"]["levels"][0], "level": 1}), "LOD")
        self.mutate_manifest(lambda m: m["materials"]["components"][0].__setitem__("roughness_factor", 0.5), "factors")
        self.mutate_manifest(lambda m: m["materials"]["channels"]["populated"].__setitem__("normal", "texture"),
                             "channel usage")

    def test_environment_leaks_refuse(self):
        self.mutate_manifest(lambda m: m["asset"].__setitem__("display_name", "/home/doc/sword"), "absolute path")
        self.mutate_manifest(lambda m: m["asset"].__setitem__("display_name", "built 2026-10-07T12:00"), "timestamp")
        self.mutate_manifest(lambda m: m["asset"].__setitem__(
            "display_name", "id 123e4567-e89b-12d3-a456-426614174000"), "UUID")
        self.mutate_glb(lambda g: g["nodes"][0]["extras"].__setitem__("pid", 4242), "environment-specific key")

    def _hull_mutation(self, edit_positions=None, edit_indices=None):
        gltf = copy.deepcopy(self.gltf)
        _, n = node(gltf, "collision_hull")
        prim = gltf["meshes"][n["mesh"]]["primitives"][0]
        acc_p = gltf["accessors"][prim["attributes"]["POSITION"]]
        acc_i = gltf["accessors"][prim["indices"]]
        pos = [list(r) for r in accessor_rows(gltf, self.bin, prim["attributes"]["POSITION"])]
        idx = [r[0] for r in accessor_rows(gltf, self.bin, prim["indices"])]
        if edit_positions:
            edit_positions(pos)
        if edit_indices:
            edit_indices(idx)
        data = bytearray(self.bin)
        flat = [c for r in pos for c in r]
        struct.pack_into(f"<{len(flat)}f", data, gltf["bufferViews"][acc_p["bufferView"]]["byteOffset"], *flat)
        struct.pack_into(f"<{len(idx)}H", data, gltf["bufferViews"][acc_i["bufferView"]]["byteOffset"], *idx)
        stored = [list(r) for r in struct.iter_unpack("<3f", struct.pack(f"<{len(flat)}f", *flat))]
        acc_p["min"] = [min(r[k] for r in stored) for k in range(3)]
        acc_p["max"] = [max(r[k] for r in stored) for k in range(3)]
        glb = repack(gltf, bytes(data))
        return glb, rehash(glb, self.m)

    def test_collision_must_be_convex_closed_outward_and_containing(self):
        def shrink(pos):                                 # pull every hull vertex 10% toward the center
            for r in pos:
                r[0], r[2] = r[0] * 0.9, r[2] * 0.9
        self.refuse(*self._hull_mutation(edit_positions=shrink), "outside face")

        def flip(idx):                                   # inward-facing triangles
            for t in range(0, len(idx), 3):
                idx[t + 1], idx[t + 2] = idx[t + 2], idx[t + 1]
        self.refuse(*self._hull_mutation(edit_indices=flip), "outside face|not convex")

        def open_shell(idx):                             # duplicate one triangle over another: open + doubled edges
            idx[0:3] = idx[3:6]
        self.refuse(*self._hull_mutation(edit_indices=open_shell), "appears twice|no opposite|unreferenced")

        def dent(pos):                                   # push one vertex inward: no longer convex
            pos[0] = [c * 0.5 for c in pos[0]]
        self.refuse(*self._hull_mutation(edit_positions=dent), "outside face|flat|degenerate")

    def test_package_directory_must_hold_exactly_the_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write_package(Path(tmp) / "p.forgepkg", self.pkg.glb, self.pkg.manifest)
            validate_package(d)
            (d / "notes.txt").write_text("hi")
            with self.assertRaisesRegex(EngineContractError, "exactly"):
                validate_package(d)
            (d / "notes.txt").unlink()
            (d / "manifest.json").unlink()
            with self.assertRaisesRegex(EngineContractError, "no manifest.json"):
                validate_package(d)
            with self.assertRaisesRegex(EngineContractError, "not a package directory"):
                validate_package(Path(tmp) / "missing.forgepkg")


class TestHullCheckUnit(unittest.TestCase):
    """The validator's exact hull check on a unit cube: accepted as is, refused with a flat extra vertex."""

    def test_flat_vertex_is_refused(self):
        from forge.engine.hull import convex_hull
        from forge.engine.validate import _check_convex_hull
        cube = convex_hull([(x, y, z) for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)])
        positions, tris = list(cube.positions), [list(t) for t in cube.triangles]
        flat = lambda t: all(positions[i][2] == 0.0 for i in t)
        _check_convex_hull(positions, [i for t in tris for i in t], positions, "cube")     # valid
        bottom = [t for t in tris if flat(t)]
        edges = {(t[k], t[(k + 1) % 3]) for t in bottom for k in range(3)}
        boundary = [(a, b) for a, b in edges if (b, a) not in edges]
        positions.append((0.5, 0.5, 0.0))                                                  # exactly on the face
        fan = [t for t in tris if not flat(t)] + [[a, b, 8] for a, b in sorted(boundary)]
        with self.assertRaisesRegex(EngineContractError, "lies flat"):
            _check_convex_hull(positions, [i for t in fan for i in t], positions, "cube")


class TestWriterFailsClosed(unittest.TestCase):
    def test_writer_never_writes_a_package_it_would_refuse(self):
        p = presented()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("forge.engine.package.validate_package_bytes", side_effect=EngineContractError("boom")):
            with self.assertRaisesRegex(ExportError, "failed its own contract validation: boom"):
                export_asset(REGISTRY, p.asset, p, "glb", 1, Path(tmp) / "x.forgepkg")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_writer_refuses_to_mix_into_foreign_paths(self):
        p = presented()
        with tempfile.TemporaryDirectory() as tmp:
            foreign = Path(tmp) / "busy.forgepkg"
            foreign.mkdir()
            (foreign / "keep.txt").write_text("mine")
            with self.assertRaisesRegex(ExportError, "other entries"):
                export_asset(REGISTRY, p.asset, p, "glb", 1, foreign)
            self.assertEqual(sorted(x.name for x in foreign.iterdir()), ["keep.txt"])
            blocker = Path(tmp) / "file.forgepkg"
            blocker.write_text("x")
            with self.assertRaisesRegex(ExportError, "not a package directory"):
                export_asset(REGISTRY, p.asset, p, "glb", 1, blocker)
            again = Path(tmp) / "ok.forgepkg"
            first = [w.read_bytes() for w in export_asset(REGISTRY, p.asset, p, "glb", 1, again)]
            second = [w.read_bytes() for w in export_asset(REGISTRY, p.asset, p, "glb", 1, again)]   # overwrite in place
            self.assertEqual(first, second)


class TestTextureSlots(Base):
    """The contract supports texture channels even though glb:1 populates none.

    A synthetic package (one embedded 2x2 PNG on base_color) checks that the validator
    accepts a consistent texture declaration and refuses inconsistent ones.
    """

    @staticmethod
    def png(w=2, h=2):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        raw = b"".join(b"\0" + b"\x80\x80\x80" * w for _ in range(h))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def textured(self, *, declare=True, color_space="srgb", width=2):
        gltf = copy.deepcopy(self.gltf)
        png = self.png()
        offset = len(self.bin)
        data = self.bin + png + b"\0" * (-len(png) % 4)
        gltf["buffers"][0]["byteLength"] = len(data)
        gltf["bufferViews"].append({"buffer": 0, "byteLength": len(png), "byteOffset": offset})
        gltf["images"] = [{"bufferView": len(gltf["bufferViews"]) - 1, "mimeType": "image/png"}]
        gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
        gltf["textures"] = [{"sampler": 0, "source": 0}]
        for mat in gltf["materials"]:
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
        m = copy.deepcopy(self.m)
        if declare:
            m["materials"]["channels"]["populated"]["base_color"] = "texture"
            m["materials"]["textures"] = [
                {"channel": "base_color", "color_space": color_space, "height": 2, "image_index": 0,
                 "material": mat["name"], "mime_type": "image/png", "pixel_format": "rgb8", "texture_index": 0,
                 "width": width} for mat in gltf["materials"]]
        glb = repack(gltf, data)
        return glb, rehash(glb, m)

    def test_consistent_texture_declaration_is_accepted(self):
        report = validate_package_bytes(*self.textured())
        self.assertEqual(report.checks[-1], "hashes")

    def test_inconsistent_texture_declarations_refuse(self):
        self.refuse(*self.textured(declare=False), "channel usage")
        self.refuse(*self.textured(color_space="linear"), "color_space must be 'srgb'")
        self.refuse(*self.textured(width=4), "dimensions")


if __name__ == "__main__":
    unittest.main()
