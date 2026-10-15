"""Structural validation of exported GLB files (independent of the exporter's in-memory objects).

Checks the binary container, every accessor/bufferView range, index bounds,
attribute counts, normals, skin joints/weights, inverse bind matrices, morph
target shapes, animation channels, materials/textures, and the Forge profile
rules (no dev-only content in public files; public coverage satisfied).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

_COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path) -> tuple[dict, bytes]:
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError("file too short for GLB")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError("not a glTF 2.0 binary")
    if length != len(data):
        raise ValueError(f"header length {length} != file size {len(data)}")
    jl, jt = struct.unpack_from("<II", data, 12)
    if jt != 0x4E4F534A or jl % 4:
        raise ValueError("first chunk must be 4-aligned JSON")
    gltf = json.loads(data[20:20 + jl].decode("utf-8"))
    off = 20 + jl
    bin_ = b""
    if off < len(data):
        bl, bt = struct.unpack_from("<II", data, off)
        if bt != 0x004E4942 or bl % 4:
            raise ValueError("second chunk must be 4-aligned BIN")
        bin_ = data[off + 8: off + 8 + bl]
    return gltf, bin_


def _view_array(gltf, bin_, view_i, comp, count, offset=0):
    v = gltf["bufferViews"][view_i]
    fmt, size = _COMP[comp]
    start = v.get("byteOffset", 0) + offset
    if start + count * size > v.get("byteOffset", 0) + v["byteLength"] or start + count * size > len(bin_):
        raise ValueError(f"sparse data overruns bufferView {view_i}")
    return np.frombuffer(bin_, dtype="<" + fmt, count=count, offset=start)


def accessor(gltf: dict, bin_: bytes, i: int) -> np.ndarray:
    a = gltf["accessors"][i]
    if "bufferView" not in a:  # sparse (or all-zero) accessor
        n = _NC[a["type"]]
        fmt, _ = _COMP[a["componentType"]]
        out = np.zeros((a["count"], n), dtype="<" + fmt)
        sp = a.get("sparse")
        if sp:
            idx = _view_array(gltf, bin_, sp["indices"]["bufferView"], sp["indices"]["componentType"], sp["count"],
                              sp["indices"].get("byteOffset", 0))
            if len(idx) and (idx.max() >= a["count"] or np.any(np.diff(idx.astype(np.int64)) <= 0)):
                raise ValueError(f"accessor {i}: sparse indices out of range or not increasing")
            vals = _view_array(gltf, bin_, sp["values"]["bufferView"], a["componentType"], sp["count"] * n,
                               sp["values"].get("byteOffset", 0)).reshape(-1, n)
            out[idx] = vals
        return out if n > 1 else out[:, 0]
    v = gltf["bufferViews"][a["bufferView"]]
    fmt, size = _COMP[a["componentType"]]
    n = _NC[a["type"]]
    start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = v.get("byteStride", 0)
    if stride and stride != size * n:
        raise ValueError("strided accessors not used by this contract")
    nbytes = a["count"] * n * size
    if start + nbytes > v.get("byteOffset", 0) + v["byteLength"] or v.get("byteOffset", 0) + v["byteLength"] > len(bin_):
        raise ValueError(f"accessor {i} overruns its bufferView/buffer")
    arr = np.frombuffer(bin_, dtype="<" + fmt, count=a["count"] * n, offset=start)
    return arr.reshape(a["count"], n) if n > 1 else arr


def validate_glb(path, expect_profile: str | None = None) -> dict:
    gltf, bin_ = read_glb(path)
    errors, warnings = [], []
    stats = {"meshes": 0, "triangles": 0, "vertices": 0, "joints": 0, "morph_targets": 0, "animations": 0,
             "materials": len(gltf.get("materials", [])), "images": len(gltf.get("images", []))}

    def err(msg):
        errors.append(msg)

    if gltf.get("asset", {}).get("version") != "2.0":
        err("asset.version must be 2.0")
    if gltf["buffers"][0]["byteLength"] > len(bin_):
        err("buffer byteLength exceeds BIN chunk")
    for i, v in enumerate(gltf["bufferViews"]):
        if v.get("byteOffset", 0) % 4:
            err(f"bufferView {i} not 4-byte aligned")
        if v.get("byteOffset", 0) + v["byteLength"] > len(bin_):
            err(f"bufferView {i} overruns buffer")
    acc_cache = {}

    def A(i):
        if i not in acc_cache:
            acc_cache[i] = accessor(gltf, bin_, i)
        return acc_cache[i]

    for i, a in enumerate(gltf["accessors"]):
        try:
            arr = A(i)
        except ValueError as e:
            err(str(e))
            continue
        if a["componentType"] == 5126 and not np.all(np.isfinite(arr)):
            err(f"accessor {i} has non-finite floats")
        if "min" in a and a["componentType"] == 5126:
            mn = arr.reshape(a["count"], -1).min(0)
            mx = arr.reshape(a["count"], -1).max(0)
            if not (np.allclose(mn, a["min"], atol=1e-6) and np.allclose(mx, a["max"], atol=1e-6)):
                err(f"accessor {i} min/max do not match data")
    skins = gltf.get("skins", [])
    nodes = gltf["nodes"]
    if skins:
        sk = skins[0]
        stats["joints"] = len(sk["joints"])
        ibm = A(sk["inverseBindMatrices"])
        if len(ibm) != len(sk["joints"]):
            err("inverseBindMatrices count != joint count")
        # every joint must be reachable, and hierarchy acyclic
        parent = {}
        for ni, n in enumerate(nodes):
            for c in n.get("children", []):
                if c in parent:
                    err(f"node {c} has two parents")
                parent[c] = ni
        for j in sk["joints"]:
            seen, x = set(), j
            while x in parent:
                if x in seen:
                    err("cycle in node hierarchy")
                    break
                seen.add(x)
                x = parent[x]
        # IBM must invert the joint's rest world transform
        world = _world_matrices(nodes, parent)
        for k, j in enumerate(sk["joints"]):
            m = ibm[k].reshape(4, 4).T @ world[j]
            if not np.allclose(m, np.eye(4), atol=1e-4):
                err(f"inverseBindMatrix {k} does not invert joint {nodes[j]['name']} rest transform")
                break
    dev_names = set()
    for ni, n in enumerate(nodes):
        if n.get("extras", {}).get("dev_only"):
            dev_names.add(n.get("name"))
    for mi, m in enumerate(gltf.get("meshes", [])):
        stats["meshes"] += 1
        for p in m["primitives"]:
            at = p["attributes"]
            pos = A(at["POSITION"])
            V = len(pos)
            stats["vertices"] += V
            for key, idx in at.items():
                if gltf["accessors"][idx]["count"] != V:
                    err(f"mesh {m['name']}: {key} count mismatch")
            if "NORMAL" in at:
                nl = np.linalg.norm(A(at["NORMAL"]), axis=1)
                if np.any(np.abs(nl - 1) > 1e-3):
                    err(f"mesh {m['name']}: non-unit normals")
            ind = A(p["indices"])
            if len(ind) % 3:
                err(f"mesh {m['name']}: index count not a multiple of 3")
            if ind.max() >= V:
                err(f"mesh {m['name']}: index out of range")
            tri = ind.reshape(-1, 3)
            stats["triangles"] += len(tri)
            if np.any((tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2]) | (tri[:, 0] == tri[:, 2])):
                err(f"mesh {m['name']}: degenerate index triangle")
            if "JOINTS_0" in at:
                jj = A(at["JOINTS_0"])
                ww = A(at["WEIGHTS_0"])
                if jj.max() >= stats["joints"]:
                    err(f"mesh {m['name']}: joint index out of range")
                s = ww.sum(1)
                if np.any(np.abs(s - 1) > 2e-5):
                    err(f"mesh {m['name']}: weights do not sum to 1 (max dev {np.abs(s - 1).max():.2e})")
                if np.any(ww < 0):
                    err(f"mesh {m['name']}: negative weights")
            for t in p.get("targets", []):
                stats["morph_targets"] += 1
                if gltf["accessors"][t["POSITION"]]["count"] != V:
                    err(f"mesh {m['name']}: morph target count mismatch")
            if "targets" in p:
                names = m.get("extras", {}).get("targetNames", [])
                if len(names) != len(p["targets"]) or len(m.get("weights", [])) != len(p["targets"]):
                    err(f"mesh {m['name']}: targetNames/weights length mismatch")
            mat = p.get("material")
            if mat is None or mat >= len(gltf.get("materials", [])):
                err(f"mesh {m['name']}: missing material")
    for t in gltf.get("textures", []):
        if t["source"] >= len(gltf.get("images", [])):
            err("texture references missing image")
    for img in gltf.get("images", []):
        v = gltf["bufferViews"][img["bufferView"]]
        head = bin_[v.get("byteOffset", 0): v.get("byteOffset", 0) + 8]
        if head != b"\x89PNG\r\n\x1a\n":
            err(f"image {img.get('name')} is not a PNG")
    for an in gltf.get("animations", []):
        stats["animations"] += 1
        for ch in an["channels"]:
            s = an["samplers"][ch["sampler"]]
            tin = A(s["input"])
            out = A(s["output"])
            if len(tin) != len(out):
                err(f"animation {an['name']}: input/output count mismatch")
            if np.any(np.diff(tin) <= 0):
                err(f"animation {an['name']}: times not strictly increasing")
            if ch["target"]["path"] == "rotation" and np.any(np.abs(np.linalg.norm(out, axis=1) - 1) > 1e-3):
                err(f"animation {an['name']}: non-unit quaternion")
            if ch["target"]["node"] >= len(nodes):
                err("animation targets missing node")
    forge = gltf.get("asset", {}).get("extras", {}).get("forge", {})
    profile = forge.get("profile")
    if expect_profile and profile != expect_profile:
        err(f"profile {profile!r} != expected {expect_profile!r}")
    if profile == "public":
        if dev_names:
            err(f"public file contains dev-only nodes: {sorted(dev_names)}")
        if forge.get("dev_only_parts"):
            err("public file declares dev-only parts")
        cov = forge.get("coverage", {})
        missing = [r for r in cov.get("required", []) if not cov.get("covered_by", {}).get(r)]
        if missing:
            err(f"public file lacks garment coverage for {missing}")
        if any(n.get("name", "").startswith(("genital", "penis", "scrotum", "testicle")) for n in nodes):
            err("public file contains developer anatomy joints")
    stats["profile"] = profile
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats}


def _world_matrices(nodes, parent):
    local = []
    for n in nodes:
        m = np.eye(4)
        if "matrix" in n:
            m = np.array(n["matrix"]).reshape(4, 4).T
        else:
            if "rotation" in n:
                x, y, z, w = n["rotation"]
                m[:3, :3] = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            if "scale" in n:
                m[:3, :3] = m[:3, :3] @ np.diag(n["scale"])
            if "translation" in n:
                m[:3, 3] = n["translation"]
        local.append(m)
    world = [None] * len(nodes)

    def get(i):
        if world[i] is None:
            world[i] = local[i] if i not in parent else get(parent[i]) @ local[i]
        return world[i]

    return [get(i) for i in range(len(nodes))]
