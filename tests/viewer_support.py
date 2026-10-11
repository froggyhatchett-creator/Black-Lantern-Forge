"""Helpers for the Step 4 viewer tests (not a test module).

The golden package is read from disk and never regenerated. Mutated variants are built from its
bytes and written to temporary directories. refresh() recomputes only the byte-level hashes
(GLB, chunks, manifest content), so a structural mutation reaches the check it targets instead of
stopping at a hash mismatch. Semantic hashes are deliberately left stale; the viewer checks them last.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import struct
from pathlib import Path

from forge_test_support import REPO_ROOT

GOLDEN_DIR = REPO_ROOT / "examples" / "short_sword_seed1337_v1.forgepkg"
FROZEN_GLB_SHA256 = "b91900f7a1fc95f3ec6678e3dc8fa875b91bcce115c3231bd14dc5d0e2828bc3"
FROZEN_MANIFEST_SHA256 = "4a4d552e82a2ff2caf9c55420488005240ece4879db1d191ec725a2acffc7aaf"
FROZEN_SOCKET_TIP = [0.0, 0.60488361120224, 0.0]
VIEWER_PKG = REPO_ROOT / "forge_engine_viewer"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def golden_bytes() -> tuple[bytes, bytes]:
    return (GOLDEN_DIR / "asset.glb").read_bytes(), (GOLDEN_DIR / "manifest.json").read_bytes()


def split(glb: bytes) -> tuple[dict, bytes, bytes]:
    json_len = struct.unpack_from("<I", glb, 12)[0]
    json_chunk = glb[20:20 + json_len]
    bin_len = struct.unpack_from("<I", glb, 20 + json_len)[0]
    return json.loads(json_chunk), json_chunk, glb[28 + json_len:28 + json_len + bin_len]


def pack(gltf: dict, bin_chunk: bytes) -> bytes:
    j = json.dumps(gltf, sort_keys=True, separators=(",", ":")).encode("ascii")
    j += b" " * (-len(j) % 4)
    b = bin_chunk + b"\0" * (-len(bin_chunk) % 4)
    total = 12 + 8 + len(j) + 8 + len(b)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(b), 0x004E4942) + b)


def manifest_bytes(m: dict) -> bytes:
    return (json.dumps(m, indent=2, sort_keys=True, ensure_ascii=True, separators=(",", ": ")) + "\n").encode("ascii")


def refresh(glb: bytes, manifest: dict) -> bytes:
    """Recompute the byte-level hashes (glb, json chunk, bin chunk, manifest content) for this GLB."""
    _, json_chunk, bin_chunk = split(glb)
    m = copy.deepcopy(manifest)
    h = m["hashes"]
    for name, data in (("glb_sha256", glb), ("gltf_json_sha256", json_chunk), ("gltf_bin_sha256", bin_chunk)):
        if name in h:
            h[name]["sha256"] = sha256(data)
    content = h.pop("manifest_content_sha256", None)
    digest = sha256(json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))
    h["manifest_content_sha256"] = content or {"covers": "", "verifiable_from_package": True}
    h["manifest_content_sha256"]["sha256"] = digest
    return manifest_bytes(m)


def write_package(directory: Path, glb: bytes, manifest: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "asset.glb").write_bytes(glb)
    (directory / "manifest.json").write_bytes(manifest)
    return directory


def variant(directory: Path, *, gltf_fn=None, bin_fn=None, manifest_fn=None, fix_hashes: bool = True) -> Path:
    """A mutated copy of the golden package in `directory`."""
    glb, man = golden_bytes()
    gltf, _, bin_chunk = split(glb)
    manifest = json.loads(man)
    if gltf_fn:
        gltf_fn(gltf)
    if bin_fn:
        bin_chunk = bin_fn(bytearray(bin_chunk))
    if manifest_fn:
        manifest_fn(manifest)
    new_glb = pack(gltf, bytes(bin_chunk))
    new_man = refresh(new_glb, manifest) if fix_hashes else manifest_bytes(manifest)
    return write_package(directory, new_glb, new_man)


def copy_golden(directory: Path) -> Path:
    shutil.copytree(GOLDEN_DIR, directory)
    return directory


def node(gltf: dict, name: str) -> tuple[int, dict]:
    for i, n in enumerate(gltf["nodes"]):
        if n["name"] == name:
            return i, n
    raise KeyError(name)


def prim(gltf: dict, name: str) -> dict:
    return gltf["meshes"][node(gltf, name)[1]["mesh"]]["primitives"][0]


def raw_rows(gltf: dict, bin_chunk: bytes, accessor: int) -> list[tuple]:
    """Test-local accessor read, for cross-checking the viewer's decoder."""
    a = gltf["accessors"][accessor]
    v = gltf["bufferViews"][a["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
    code = {5126: "f", 5123: "H", 5125: "I"}[a["componentType"]]
    vals = struct.unpack_from(f"<{a['count'] * width}{code}", bin_chunk, v.get("byteOffset", 0) + a.get("byteOffset", 0))
    return [tuple(vals[i:i + width]) for i in range(0, len(vals), width)]
