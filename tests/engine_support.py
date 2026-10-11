"""Helpers for the Step 3 engine-contract tests (not a test module).

The GLB reading helpers here are deliberately naive and separate from both
forge.engine.glb (the writer) and forge.engine.validate (the validator), so
the tests can pull a package apart and rebuild a mutated one independently.
"""

from __future__ import annotations

import functools
import hashlib
import json
import struct
from pathlib import Path

from forge.catalog import ASSET_ENTRIES, ENGINE_ADAPTERS, REGISTRY
from forge.engine.package import build_engine_package
from forge.registry import generate_asset, present_asset
from forge_test_support import REPO_ROOT

GOLDEN_DIR = REPO_ROOT / "examples" / "short_sword_seed1337_v1.forgepkg"
GOLDEN_RECORD = REPO_ROOT / "examples" / "engine_package_seed1337.golden.json"
GOLDEN = json.loads(GOLDEN_RECORD.read_text(encoding="ascii"))
GOLDEN_GLB_SHA256 = "b91900f7a1fc95f3ec6678e3dc8fa875b91bcce115c3231bd14dc5d0e2828bc3"
GOLDEN_MANIFEST_SHA256 = "4a4d552e82a2ff2caf9c55420488005240ece4879db1d191ec725a2acffc7aaf"
FROZEN_OBJ_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"
FROZEN_GEOMETRY_1337 = "558b91f33db8aba45a74eb390708aae9b12d4532a6c6f9de24681d687d047439"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def presented(seed: int = 1337):
    asset = generate_asset(REGISTRY, "short_sword", seed, 1)
    return present_asset(REGISTRY, asset, REGISTRY.presentation("forge.presentation", 1).versions)


def build(seed: int = 1337):
    p = presented(seed)
    entry = ASSET_ENTRIES["short_sword"]
    return build_engine_package(p.asset, p, entry.descriptor, ENGINE_ADAPTERS["short_sword"],
                                source_hashes=tuple((k, f(p.asset, p)) for k, f in entry.integrity),
                                exporter=("glb", 1), contract_version=1)


@functools.lru_cache(maxsize=None)
def cached(seed: int = 1337):
    return build(seed)


def split(glb: bytes) -> tuple[dict, bytes, bytes]:
    """(gltf dict, JSON chunk data, BIN chunk data). Assumes a well-formed two-chunk GLB."""
    json_len = struct.unpack_from("<I", glb, 12)[0]
    json_chunk = glb[20:20 + json_len]
    bin_len = struct.unpack_from("<I", glb, 20 + json_len)[0]
    bin_chunk = glb[28 + json_len:28 + json_len + bin_len]
    return json.loads(json_chunk), json_chunk, bin_chunk


def repack(gltf: dict, bin_chunk: bytes) -> bytes:
    """Independent GLB packer for building mutated packages."""
    j = json.dumps(gltf, sort_keys=True, separators=(",", ":")).encode("ascii")
    j += b" " * (-len(j) % 4)
    b = bin_chunk + b"\0" * (-len(bin_chunk) % 4)
    total = 12 + 8 + len(j) + 8 + len(b)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(b), 0x004E4942) + b)


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, separators=(",", ": ")) + "\n").encode("ascii")


def accessor_rows(gltf: dict, bin_chunk: bytes, index: int) -> list[tuple]:
    a = gltf["accessors"][index]
    v = gltf["bufferViews"][a["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    code = {5126: "f", 5123: "H", 5125: "I"}[a["componentType"]]
    vals = struct.unpack_from(f"<{a['count'] * width}{code}", bin_chunk, v.get("byteOffset", 0) + a.get("byteOffset", 0))
    return [tuple(vals[i:i + width]) for i in range(0, len(vals), width)]


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def write_package(directory: Path, glb: bytes, manifest: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "asset.glb").write_bytes(glb)
    (directory / "manifest.json").write_bytes(manifest)
    return directory


def node(gltf: dict, name: str) -> tuple[int, dict]:
    for i, n in enumerate(gltf["nodes"]):
        if n["name"] == name:
            return i, n
    raise KeyError(name)


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def rehash(glb: bytes, manifest: dict) -> bytes:
    """Recompute every package-verifiable hash for (glb, manifest); return canonical manifest bytes.

    A third, test-local implementation of the hash encodings, used to build mutated packages
    whose hashes are self-consistent, so a test isolates exactly one violation.
    """
    gltf, json_chunk, bin_chunk = split(glb)
    m = json.loads(json.dumps(manifest))
    h = m["hashes"]
    root = m["package"]["root_node"]

    def prim(name):
        return gltf["meshes"][node(gltf, name)[1]["mesh"]]["primitives"][0]

    geo = hashlib.sha256(b"forge.engine.render-geometry.v1\0")
    for name in m["lods"]["levels"][0]["nodes"]:
        p = prim(name)
        pos, nrm, uv = (accessor_rows(gltf, bin_chunk, p["attributes"][k]) for k in ("POSITION", "NORMAL", "TEXCOORD_0"))
        idx = [r[0] for r in accessor_rows(gltf, bin_chunk, p["indices"])]
        geo.update(name.encode() + b"\0" + gltf["materials"][p["material"]]["name"].encode() + b"\0")
        geo.update(struct.pack("<II", len(pos), len(idx)))
        for rows in (pos, nrm, uv):
            flat = [c for r in rows for c in r]
            geo.update(struct.pack(f"<{len(flat)}f", *flat))
        geo.update(struct.pack(f"<{len(idx)}I", *idx))
    col = hashlib.sha256(b"forge.engine.collision.v1\0")
    try:
        p = prim("collision_hull")
        pos = accessor_rows(gltf, bin_chunk, p["attributes"]["POSITION"])
        idx = [r[0] for r in accessor_rows(gltf, bin_chunk, p["indices"])]
        flat = [c for r in pos for c in r]
        col.update(b"collision_hull\0" + struct.pack("<II", len(pos), len(idx)) + struct.pack(f"<{len(flat)}f", *flat)
                   + struct.pack(f"<{len(idx)}I", *idx))
    except KeyError:
        pass
    sockets = [{"name": n["name"], "parent": root, "rotation": n["rotation"], "translation": n["translation"]}
               for n in gltf["nodes"] if n["name"].startswith("socket_")]
    digest = {
        "glb_sha256": sha256(glb), "gltf_json_sha256": sha256(json_chunk), "gltf_bin_sha256": sha256(bin_chunk),
        "render_geometry_sha256": geo.hexdigest(), "collision_sha256": col.hexdigest(),
        "sockets_sha256": sha256(_canon(sockets)), "pbr_materials_sha256": sha256(_canon(gltf["materials"])),
    }
    digest["semantic_sha256"] = sha256(_canon({
        "contract": {"id": m["contract"]["id"], "version": m["contract"]["version"]},
        "coordinates": m["coordinates"], "lods": m["lods"],
        **{k: digest[k] for k in ("collision_sha256", "pbr_materials_sha256", "render_geometry_sha256", "sockets_sha256")}}))
    for k, v in digest.items():
        if k in h:
            h[k]["sha256"] = v
    h.pop("manifest_content_sha256", None)
    content = sha256(_canon(m))
    h["manifest_content_sha256"] = {"covers": "canonical JSON of this manifest with hashes.manifest_content_sha256 removed",
                                    "sha256": content, "verifiable_from_package": True}
    return manifest_bytes(m)
