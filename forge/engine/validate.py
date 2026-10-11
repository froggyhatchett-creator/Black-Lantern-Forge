"""Independent validator for Forge -> Engine Asset Contract packages.

It checks a package (asset.glb + manifest.json) without the generator. It
doesn't regenerate anything, and it shares no code with the writer
(forge.engine.glb, forge.engine.package, forge.engine.hull) or with
forge.hashing. Its only shared input is the contract definition itself
(forge.engine.contract). The GLB parser below is its own: struct for the
header and chunks, json for the JSON chunk, struct again for every accessor.

Fail closed:
  * The first violation raises EngineContractError, naming what is wrong.
  * Nothing is repaired, defaulted or skipped. Unknown fields, extra chunks,
    unexpected attributes, extensions, and non-canonical manifest bytes are
    all refusals.

Check order (each name is reported when it passes):
  manifest.json, manifest.contract, glb.header, glb.chunks, gltf.json,
  gltf.buffers, gltf.buffer_views, gltf.accessors, gltf.materials,
  gltf.meshes, gltf.nodes, gltf.scenes, manifest.canonical, manifest.schema,
  manifest.identity, manifest.coordinates, manifest.package, contract.sockets,
  contract.collision, manifest.lods, manifest.materials, manifest.tags,
  hygiene, hashes
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from forge.engine.contract import (
    CHANNEL_ABSENT,
    CHANNEL_FACTOR,
    CHANNEL_STATES,
    CHANNEL_TEXTURE,
    CHUNK_BIN,
    CHUNK_JSON,
    COMPONENT_FLOAT,
    COMPONENT_UNSIGNED_INT,
    COMPONENT_UNSIGNED_SHORT,
    CONTENT_HASH_COVERS,
    CONTRACT_ID,
    GLB_HEADER_BYTES,
    GLB_MAGIC,
    GLB_VERSION,
    GLTF_VERSION,
    MODE_TRIANGLES,
    TARGET_ARRAY_BUFFER,
    TARGET_ELEMENT_ARRAY_BUFFER,
    ContractSpec,
    contract_spec,
)
from forge.errors import EngineContractError

_COMPONENTS = {COMPONENT_FLOAT: ("f", 4), COMPONENT_UNSIGNED_SHORT: ("H", 2), COMPONENT_UNSIGNED_INT: ("I", 4)}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_NORMAL_TOLERANCE = 1e-5
_QUATERNION_TOLERANCE = 1e-6

_ID = re.compile(r"[a-z][a-z0-9_]*")
_DOTTED_ID = re.compile(r"[a-z][a-z0-9_.-]*")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_SEED = re.compile(r"0|[1-9][0-9]{0,19}")
_SHA = re.compile(r"[0-9a-f]{64}")
_TAG = re.compile(r"[a-z0-9_.]+:[a-z0-9_.+-]+")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_ABSOLUTE = re.compile(r"(^/)|(^[A-Za-z]:[\\/])|(^\\\\)|(^~[\\/])|(/home/)|(/Users/)|(/tmp/)|(\\Users\\)")
_ENVIRONMENT_KEYS = {"timestamp", "time", "date", "datetime", "created", "modified", "pid", "hostname",
                     "host", "user", "username", "machine", "uuid", "guid", "cwd", "abspath"}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_FORMATS = {2: "rgb8", 6: "rgba8"}
_SRGB_CHANNELS = ("base_color", "emissive")
_TEXTURE_SLOTS = {
    "base_color": ("pbrMetallicRoughness", "baseColorTexture"),
    "metallic_roughness": ("pbrMetallicRoughness", "metallicRoughnessTexture"),
    "normal": (None, "normalTexture"),
    "occlusion": (None, "occlusionTexture"),
    "emissive": (None, "emissiveTexture"),
}


def _fail(message: str):
    raise EngineContractError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _is_int(v) -> bool:
    return type(v) is int


def _is_num(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def _keys(obj, required: set, optional: set, where: str) -> None:
    _require(isinstance(obj, dict), f"{where} must be a JSON object")
    missing = sorted(required - set(obj))
    unknown = sorted(set(obj) - required - optional)
    _require(not missing, f"{where} is missing {missing}")
    _require(not unknown, f"{where} has unknown fields {unknown}")


def _strict_json(data: bytes, where: str):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(f"{where} is not valid UTF-8 ({exc.reason})")
    _require(not text.startswith("﻿"), f"{where} starts with a byte-order mark")

    def pairs(items):
        out = {}
        for k, v in items:
            _require(k not in out, f"{where} repeats key {k!r}")
            out[k] = v
        return out

    def constant(name):
        _fail(f"{where} contains the non-JSON constant {name}")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        _fail(f"{where} is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}")


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _canonical_sha(obj) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _pretty(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ": ")) + "\n").encode("ascii")


# ------------------------------------------------------------------ GLB container

@dataclass(frozen=True)
class ParsedGLB:
    version: int
    length: int
    json_chunk: bytes      # stored chunk data, padding included
    bin_chunk: bytes       # stored chunk data, padding included
    gltf: dict


def parse_glb(data: bytes) -> ParsedGLB:
    """Parse the GLB container: 12-byte header, then exactly a JSON chunk and a BIN chunk."""
    _require(isinstance(data, (bytes, bytearray)), "GLB data must be bytes")
    data = bytes(data)
    _require(len(data) >= GLB_HEADER_BYTES, f"GLB is {len(data)} bytes, shorter than its 12-byte header")
    magic, version, length = struct.unpack_from("<III", data, 0)
    _require(magic == GLB_MAGIC, f"GLB magic is 0x{magic:08x}, not 0x{GLB_MAGIC:08x} ('glTF')")
    _require(version == GLB_VERSION, f"GLB container version is {version}, not {GLB_VERSION}")
    _require(length == len(data), f"GLB header length {length} != actual size {len(data)}")
    _require(length % 4 == 0, "GLB length is not a multiple of 4")
    chunks, offset = [], GLB_HEADER_BYTES
    while offset < length:
        _require(length - offset >= 8, f"truncated chunk header at byte {offset}")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        _require(chunk_length % 4 == 0, f"chunk at byte {offset - 8} has length {chunk_length}, not 4-aligned")
        _require(chunk_length <= length - offset, f"chunk at byte {offset - 8} overruns the GLB")
        chunks.append((chunk_type, data[offset:offset + chunk_length]))
        offset += chunk_length
    types = [t for t, _ in chunks]
    _require(types == [CHUNK_JSON, CHUNK_BIN],
             f"contract GLBs hold exactly a JSON chunk then a BIN chunk; found chunk types "
             f"{['0x%08x' % t for t in types]}")
    json_chunk, bin_chunk = chunks[0][1], chunks[1][1]
    _require(len(json_chunk) > 0, "JSON chunk is empty")
    gltf = _strict_json(json_chunk, "GLB JSON chunk")
    _require(isinstance(gltf, dict), "GLB JSON chunk is not a JSON object")
    return ParsedGLB(version=version, length=length, json_chunk=json_chunk, bin_chunk=bin_chunk, gltf=gltf)


# ------------------------------------------------------------------ glTF document

_TOP_LEVEL = {"accessors", "asset", "bufferViews", "buffers", "images", "materials", "meshes", "nodes",
              "samplers", "scene", "scenes", "textures"}


class _Gltf:
    """Structural checks over the parsed document plus exact reads from the BIN chunk."""

    def __init__(self, glb: ParsedGLB, checks: list):
        self.glb, self.doc, self.checks = glb, glb.gltf, checks
        d = self.doc
        _keys(d, {"accessors", "asset", "bufferViews", "buffers", "materials", "meshes", "nodes", "scene",
                  "scenes"}, {"images", "samplers", "textures"}, "glTF document")
        _keys(d["asset"], {"version", "generator", "extras"}, set(), "glTF asset")
        _require(d["asset"]["version"] == GLTF_VERSION, f"glTF asset.version is {d['asset']['version']!r}, not '2.0'")
        _require(isinstance(d["asset"]["generator"], str), "glTF asset.generator must be a string")
        for name in sorted(set(d) & _TOP_LEVEL - {"asset", "scene"}):
            _require(isinstance(d[name], list) and d[name], f"glTF {name} must be a non-empty array")
        checks.append("gltf.json")
        self._buffers()
        self._views()
        self.accessor_data = [self._accessor(i, a) for i, a in enumerate(d["accessors"])]
        checks.append("gltf.accessors")
        self._images()
        self._materials()
        self._meshes()
        self._nodes()
        self._scenes()

    # ---- buffers and views
    def _buffers(self):
        buffers = self.doc["buffers"]
        _require(len(buffers) == 1, f"contract GLBs hold exactly one buffer; found {len(buffers)}")
        _keys(buffers[0], {"byteLength"}, set(), "buffers[0]")
        n = buffers[0]["byteLength"]
        size = len(self.glb.bin_chunk)
        _require(_is_int(n) and 0 < n <= size and size - n < 4,
                 f"buffers[0].byteLength {n!r} does not match the {size}-byte BIN chunk")
        _require(not any(self.glb.bin_chunk[n:]), "BIN chunk padding is not zero bytes")
        self.buffer_length = n
        self.checks.append("gltf.buffers")

    def _views(self):
        for i, v in enumerate(self.doc["bufferViews"]):
            where = f"bufferViews[{i}]"
            _keys(v, {"buffer", "byteLength"}, {"byteOffset", "target"}, where)
            offset = v.get("byteOffset", 0)
            _require(v["buffer"] == 0 and _is_int(v["buffer"]), f"{where}.buffer must be 0")
            _require(_is_int(offset) and offset >= 0 and offset % 4 == 0, f"{where}.byteOffset {offset!r} invalid or not 4-aligned")
            _require(_is_int(v["byteLength"]) and v["byteLength"] > 0, f"{where}.byteLength must be a positive int")
            _require(offset + v["byteLength"] <= self.buffer_length,
                     f"{where} [{offset}, {offset + v['byteLength']}) runs past the {self.buffer_length}-byte buffer")
            _require(v.get("target", TARGET_ARRAY_BUFFER) in (TARGET_ARRAY_BUFFER, TARGET_ELEMENT_ARRAY_BUFFER),
                     f"{where}.target {v.get('target')!r} invalid")
        self.checks.append("gltf.buffer_views")

    def _accessor(self, i, a):
        where = f"accessors[{i}]"
        _keys(a, {"bufferView", "componentType", "count", "type"}, {"byteOffset", "min", "max"}, where)
        views = self.doc["bufferViews"]
        _require(_is_int(a["bufferView"]) and 0 <= a["bufferView"] < len(views), f"{where}.bufferView out of range")
        _require(a["componentType"] in _COMPONENTS, f"{where}.componentType {a['componentType']!r} not allowed")
        _require(a["type"] in _WIDTH, f"{where}.type {a['type']!r} invalid")
        _require(_is_int(a["count"]) and a["count"] > 0, f"{where}.count must be a positive int")
        code, size = _COMPONENTS[a["componentType"]]
        width = _WIDTH[a["type"]]
        view = views[a["bufferView"]]
        offset = a.get("byteOffset", 0)
        _require(_is_int(offset) and offset >= 0 and offset % size == 0, f"{where}.byteOffset {offset!r} misaligned")
        start = view.get("byteOffset", 0) + offset
        _require(start % size == 0, f"{where} is not aligned to its {size}-byte component size")
        nbytes = a["count"] * width * size
        _require(offset + nbytes <= view["byteLength"],
                 f"{where} needs {offset + nbytes} bytes but bufferViews[{a['bufferView']}] has {view['byteLength']}")
        values = struct.unpack_from(f"<{a['count'] * width}{code}", self.glb.bin_chunk, start)
        if code == "f":
            _require(all(math.isfinite(x) for x in values), f"{where} holds a non-finite float")
        rows = tuple(values[k:k + width] for k in range(0, len(values), width))
        if "min" in a or "max" in a:
            _require("min" in a and "max" in a, f"{where} must declare both min and max")
            actual_min = [min(values[c::width]) for c in range(width)]
            actual_max = [max(values[c::width]) for c in range(width)]
            _require(a["min"] == actual_min and a["max"] == actual_max,
                     f"{where} min/max {a['min']}/{a['max']} != data {actual_min}/{actual_max}")
        return rows

    def _accessor_of(self, index, where, *, types, components):
        _require(_is_int(index) and 0 <= index < len(self.doc["accessors"]), f"{where} accessor index out of range")
        a = self.doc["accessors"][index]
        _require(a["type"] in types and a["componentType"] in components,
                 f"{where} must be {'/'.join(types)} of component types {components}; got {a['type']}/{a['componentType']}")
        return a, self.accessor_data[index]

    # ---- images and textures (contract v1 allows embedded PNG only)
    def _images(self):
        d = self.doc
        self.image_info = []
        for i, img in enumerate(d.get("images", ())):
            where = f"images[{i}]"
            _keys(img, {"bufferView", "mimeType"}, {"name"}, where)
            _require(img["mimeType"] == "image/png", f"{where}.mimeType must be image/png")
            _require(_is_int(img["bufferView"]) and 0 <= img["bufferView"] < len(d["bufferViews"]),
                     f"{where}.bufferView out of range")
            view = d["bufferViews"][img["bufferView"]]
            _require("target" not in view, f"{where} bufferView must not declare a vertex/index target")
            start = view.get("byteOffset", 0)
            data = self.glb.bin_chunk[start:start + view["byteLength"]]
            _require(data[:8] == _PNG_SIGNATURE and data[12:16] == b"IHDR" and len(data) >= 33,
                     f"{where} is not a PNG")
            w, h, depth, color = struct.unpack(">IIBB", data[16:26])
            _require(depth == 8 and color in _PNG_FORMATS, f"{where}: only 8-bit RGB/RGBA PNG is allowed")
            self.image_info.append({"width": w, "height": h, "pixel_format": _PNG_FORMATS[color]})
        for i, s in enumerate(d.get("samplers", ())):
            _keys(s, set(), {"magFilter", "minFilter", "wrapS", "wrapT"}, f"samplers[{i}]")
        for i, t in enumerate(d.get("textures", ())):
            where = f"textures[{i}]"
            _keys(t, {"source"}, {"sampler"}, where)
            _require(_is_int(t["source"]) and 0 <= t["source"] < len(d.get("images", ())), f"{where}.source out of range")
            if "sampler" in t:
                _require(_is_int(t["sampler"]) and 0 <= t["sampler"] < len(d.get("samplers", ())),
                         f"{where}.sampler out of range")

    def _texture_ref(self, ref, where):
        _keys(ref, {"index"}, {"texCoord", "scale", "strength"}, where)
        _require(_is_int(ref["index"]) and 0 <= ref["index"] < len(self.doc.get("textures", ())),
                 f"{where}.index out of range")
        _require(ref.get("texCoord", 0) == 0, f"{where}.texCoord must be 0")
        return ref["index"]

    def _materials(self):
        self.material_channels = []
        for i, m in enumerate(self.doc["materials"]):
            where = f"materials[{i}]"
            _keys(m, {"name", "pbrMetallicRoughness"},
                  {"alphaMode", "doubleSided", "extras", "normalTexture", "occlusionTexture", "emissiveTexture",
                   "emissiveFactor"}, where)
            _require(isinstance(m["name"], str) and _NAME.fullmatch(m["name"]) is not None, f"{where}.name invalid")
            pbr = m["pbrMetallicRoughness"]
            _keys(pbr, set(), {"baseColorFactor", "metallicFactor", "roughnessFactor", "baseColorTexture",
                               "metallicRoughnessTexture"}, f"{where}.pbrMetallicRoughness")
            if "baseColorFactor" in pbr:
                f = pbr["baseColorFactor"]
                _require(isinstance(f, list) and len(f) == 4 and all(_is_num(c) and 0 <= c <= 1 for c in f),
                         f"{where} baseColorFactor must be 4 numbers in [0, 1]")
            for key in ("metallicFactor", "roughnessFactor"):
                if key in pbr:
                    _require(_is_num(pbr[key]) and 0 <= pbr[key] <= 1, f"{where} {key} must be in [0, 1]")
            if "emissiveFactor" in m:
                f = m["emissiveFactor"]
                _require(isinstance(f, list) and len(f) == 3 and all(_is_num(c) and 0 <= c <= 1 for c in f),
                         f"{where} emissiveFactor must be 3 numbers in [0, 1]")
            _require(m.get("alphaMode", "OPAQUE") == "OPAQUE", f"{where}: contract v1 materials are OPAQUE")
            _require(type(m.get("doubleSided", False)) is bool, f"{where}.doubleSided must be a boolean")
            states, textures = {}, {}
            for channel, (parent, slot) in _TEXTURE_SLOTS.items():
                holder = pbr if parent else m
                if slot in holder:
                    textures[channel] = self._texture_ref(holder[slot], f"{where}.{slot}")
                    states[channel] = CHANNEL_TEXTURE
                else:
                    states[channel] = CHANNEL_ABSENT
            if states["base_color"] == CHANNEL_ABSENT and "baseColorFactor" in pbr:
                states["base_color"] = CHANNEL_FACTOR
            if states["metallic_roughness"] == CHANNEL_ABSENT and ("metallicFactor" in pbr or "roughnessFactor" in pbr):
                states["metallic_roughness"] = CHANNEL_FACTOR
            if states["emissive"] == CHANNEL_ABSENT and any(m.get("emissiveFactor", [0, 0, 0])):
                states["emissive"] = CHANNEL_FACTOR
            self.material_channels.append((states, textures))
        self.checks.append("gltf.materials")

    # ---- meshes
    def _meshes(self):
        self.mesh_info = []
        for i, mesh in enumerate(self.doc["meshes"]):
            where = f"meshes[{i}]"
            _keys(mesh, {"name", "primitives"}, set(), where)
            _require(isinstance(mesh["name"], str) and _NAME.fullmatch(mesh["name"]) is not None, f"{where}.name invalid")
            prims = mesh["primitives"]
            _require(isinstance(prims, list) and len(prims) == 1, f"{where} must have exactly one primitive")
            p = prims[0]
            pw = f"{where}.primitives[0]"
            _keys(p, {"attributes", "indices", "mode"}, {"material"}, pw)
            _require(p["mode"] == MODE_TRIANGLES and _is_int(p["mode"]),
                     f"{pw}.mode is {p['mode']!r}; contract meshes are indexed triangle lists (mode 4)")
            attrs = p["attributes"]
            _require(isinstance(attrs, dict) and "POSITION" in attrs, f"{pw} has no POSITION")
            names = set(attrs)
            _require(names in ({"POSITION"}, {"POSITION", "NORMAL", "TEXCOORD_0"}),
                     f"{pw} attributes {sorted(names)}: render primitives carry POSITION, NORMAL, TEXCOORD_0; "
                     "the collision primitive carries POSITION only")
            pos_acc, positions = self._accessor_of(attrs["POSITION"], f"{pw} POSITION", types=("VEC3",),
                                                   components=(COMPONENT_FLOAT,))
            _require("min" in pos_acc, f"{pw} POSITION accessor must declare min and max")
            n = len(positions)
            normals = texcoords = None
            if "NORMAL" in attrs:
                _, normals = self._accessor_of(attrs["NORMAL"], f"{pw} NORMAL", types=("VEC3",),
                                               components=(COMPONENT_FLOAT,))
                _, texcoords = self._accessor_of(attrs["TEXCOORD_0"], f"{pw} TEXCOORD_0", types=("VEC2",),
                                                 components=(COMPONENT_FLOAT,))
                _require(len(normals) == n and len(texcoords) == n, f"{pw} attribute counts differ")
                for k, nrm in enumerate(normals):
                    length = math.sqrt(nrm[0] * nrm[0] + nrm[1] * nrm[1] + nrm[2] * nrm[2])
                    _require(abs(length - 1.0) <= _NORMAL_TOLERANCE, f"{pw} NORMAL {k} is not unit length ({length!r})")
            idx_acc, idx_rows = self._accessor_of(p["indices"], f"{pw} indices", types=("SCALAR",),
                                                  components=(COMPONENT_UNSIGNED_SHORT, COMPONENT_UNSIGNED_INT))
            view = self.doc["bufferViews"][idx_acc["bufferView"]]
            _require(view.get("target") == TARGET_ELEMENT_ARRAY_BUFFER, f"{pw} index bufferView target must be 34963")
            for name in attrs:
                av = self.doc["bufferViews"][self.doc["accessors"][attrs[name]]["bufferView"]]
                _require(av.get("target") == TARGET_ARRAY_BUFFER, f"{pw} {name} bufferView target must be 34962")
            indices = tuple(r[0] for r in idx_rows)
            restart = 0xFFFF if idx_acc["componentType"] == COMPONENT_UNSIGNED_SHORT else 0xFFFFFFFF
            _require(len(indices) % 3 == 0, f"{pw} index count {len(indices)} is not a multiple of 3")
            for k in indices:
                _require(k < n and k != restart, f"{pw} index {k} out of range for {n} vertices")
            scaled = _exact_points(positions)
            for t in range(0, len(indices), 3):
                a, b, c = indices[t], indices[t + 1], indices[t + 2]
                _require(a != b and b != c and a != c, f"{pw} triangle {t // 3} repeats a vertex")
                _require(not _cross_zero(scaled[a], scaled[b], scaled[c]), f"{pw} triangle {t // 3} has zero area")
            if "material" in p:
                _require(_is_int(p["material"]) and 0 <= p["material"] < len(self.doc["materials"]),
                         f"{pw}.material out of range")
            self.mesh_info.append({"name": mesh["name"], "positions": positions, "normals": normals,
                                   "texcoords": texcoords, "indices": indices, "material": p.get("material"),
                                   "render": normals is not None})
        self.checks.append("gltf.meshes")

    # ---- nodes and scenes
    def _nodes(self):
        nodes = self.doc["nodes"]
        names, parent = {}, {}
        for i, node in enumerate(nodes):
            where = f"nodes[{i}]"
            _keys(node, {"name"}, {"children", "mesh", "translation", "rotation", "extras"}, where)
            name = node["name"]
            _require(isinstance(name, str) and _NAME.fullmatch(name) is not None, f"{where}.name {name!r} invalid")
            _require(name not in names, f"node name {name!r} is used twice")
            names[name] = i
            for child in node.get("children", ()):
                _require(_is_int(child) and 0 <= child < len(nodes) and child != i, f"{where} child {child!r} invalid")
                _require(child not in parent, f"node {child} has two parents")
                parent[child] = i
            if "mesh" in node:
                _require(_is_int(node["mesh"]) and 0 <= node["mesh"] < len(self.doc["meshes"]), f"{where}.mesh out of range")
            if "translation" in node:
                t = node["translation"]
                _require(isinstance(t, list) and len(t) == 3 and all(_is_num(c) for c in t), f"{where}.translation invalid")
            if "rotation" in node:
                q = node["rotation"]
                _require(isinstance(q, list) and len(q) == 4 and all(_is_num(c) for c in q), f"{where}.rotation invalid")
                length = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
                _require(abs(length - 1.0) <= _QUATERNION_TOLERANCE, f"{where}.rotation is not a unit quaternion")
        meshes_used = [n["mesh"] for n in nodes if "mesh" in n]
        _require(len(meshes_used) == len(set(meshes_used)) == len(self.doc["meshes"]),
                 "every mesh must be used by exactly one node")
        for i in range(len(nodes)):           # no cycles: walking up must terminate
            seen, k = set(), i
            while k in parent:
                _require(k not in seen, "node hierarchy has a cycle")
                seen.add(k)
                k = parent[k]
        self.node_index, self.parent = names, parent
        self.checks.append("gltf.nodes")

    def _scenes(self):
        d = self.doc
        _require(_is_int(d["scene"]) and d["scene"] == 0, "the default scene must be scene 0")
        for i, s in enumerate(d["scenes"]):
            _keys(s, {"name", "nodes"}, set(), f"scenes[{i}]")
            _require(isinstance(s["nodes"], list) and s["nodes"], f"scenes[{i}] has no nodes")
            for n in s["nodes"]:
                _require(_is_int(n) and 0 <= n < len(d["nodes"]) and n not in self.parent,
                         f"scenes[{i}] root {n!r} invalid or not a root node")
        reachable = set()
        for s in d["scenes"]:
            stack = list(s["nodes"])
            while stack:
                k = stack.pop()
                _require(k not in reachable, f"node {k} appears in more than one scene")
                reachable.add(k)
                stack.extend(d["nodes"][k].get("children", ()))
        _require(reachable == set(range(len(d["nodes"]))), "some nodes are not in any scene")
        self.checks.append("gltf.scenes")

    def subtree(self, root: int) -> set:
        out, stack = set(), [root]
        while stack:
            k = stack.pop()
            out.add(k)
            stack.extend(self.doc["nodes"][k].get("children", ()))
        return out


# ------------------------------------------------------------------ exact geometry

def _exact_points(points):
    ratios = [tuple(float(v).as_integer_ratio() for v in p) for p in points]
    den = 1
    for r in ratios:
        for _, d in r:
            den = max(den, d)
    return [tuple(n * (den // d) for n, d in r) for r in ratios]


def _cross_zero(a, b, c) -> bool:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return uy * vz - uz * vy == 0 and uz * vx - ux * vz == 0 and ux * vy - uy * vx == 0


def _orient(a, b, c, d) -> int:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    wx, wy, wz = d[0] - a[0], d[1] - a[1], d[2] - a[2]
    return ux * (vy * wz - vz * wy) - uy * (vx * wz - vz * wx) + uz * (vx * wy - vy * wx)


def _check_convex_hull(hull_positions, hull_indices, render_positions, where):
    """Closed 2-manifold, Euler 2, extreme vertices only, and every hull vertex and render vertex
    on or inside every face (exact integer arithmetic)."""
    edges = set()
    for t in range(0, len(hull_indices), 3):
        a, b, c = hull_indices[t:t + 3]
        for e in ((a, b), (b, c), (c, a)):
            _require(e not in edges, f"{where}: directed edge {e} appears twice (not 2-manifold)")
            edges.add(e)
    for a, b in edges:
        _require((b, a) in edges, f"{where}: edge {(a, b)} has no opposite; the hull is not closed")
    used = set(hull_indices)
    _require(used == set(range(len(hull_positions))), f"{where}: unreferenced hull vertex")
    faces = len(hull_indices) // 3
    _require(len(used) - len(edges) // 2 + faces == 2, f"{where}: Euler characteristic is not 2")
    points = _exact_points(list(hull_positions) + list(render_positions))
    hull = points[:len(hull_positions)]
    planes = {}
    for t in range(0, len(hull_indices), 3):
        tri = hull_indices[t:t + 3]
        a, b, c = (hull[i] for i in tri)
        n = (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]), \
            (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]), \
            (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        g = math.gcd(math.gcd(abs(n[0]), abs(n[1])), abs(n[2]))
        _require(g != 0, f"{where}: face {t // 3} is degenerate")
        for i in tri:
            planes.setdefault(i, set()).add((n[0] // g, n[1] // g, n[2] // g))
    _require(all(len(s) >= 3 for s in planes.values()),
             f"{where}: a hull vertex lies flat inside a face or edge; a convex_hull lists extreme points only")
    for t in range(0, len(hull_indices), 3):
        a, b, c = (hull[i] for i in hull_indices[t:t + 3])
        for q in points:
            _require(_orient(a, b, c, q) <= 0,
                     f"{where}: a vertex lies outside face {t // 3}; the hull is not convex, not outward, "
                     "or does not contain the render geometry")


# ------------------------------------------------------------------ report

@dataclass(frozen=True)
class PackageReport:
    contract_id: str
    contract_version: int
    asset_type: str
    seed: str
    generator_id: str
    generator_version: int
    presentation: tuple[tuple[str, object], ...]   # the manifest presentation section, key order sorted
    exporter: tuple[str, int]
    checks: tuple[str, ...]
    hashes_verified: tuple[str, ...]
    glb_sha256: str
    manifest_sha256: str
    render_nodes: tuple[str, ...]
    vertices: int
    triangles: int
    collision_vertices: int
    collision_triangles: int
    sockets: tuple[tuple[str, tuple[float, float, float]], ...]

    def to_dict(self) -> dict:
        return {
            "status": "valid",
            "contract": {"id": self.contract_id, "version": self.contract_version},
            "asset_type": self.asset_type,
            "seed": self.seed,
            "generator": {"id": self.generator_id, "version": self.generator_version},
            "presentation": dict(self.presentation),
            "exporter": {"format_id": self.exporter[0], "format_version": self.exporter[1]},
            "checks": list(self.checks),
            "hashes_verified": list(self.hashes_verified),
            "glb_sha256": self.glb_sha256,
            "manifest_sha256": self.manifest_sha256,
            "lod0": {"nodes": list(self.render_nodes), "vertices": self.vertices, "triangles": self.triangles},
            "collision": {"vertices": self.collision_vertices, "triangles": self.collision_triangles},
            "sockets": {name: list(t) for name, t in self.sockets},
        }


# ------------------------------------------------------------------ package validation

def validate_package(path) -> PackageReport:
    """Validate a package directory: exactly asset.glb + manifest.json, nothing else."""
    path = Path(path)
    _require(path.is_dir(), f"{str(path)!r} is not a package directory")
    entries = sorted(p.name for p in path.iterdir())
    manifest_bytes = (path / "manifest.json").read_bytes() if (path / "manifest.json").is_file() else None
    _require(manifest_bytes is not None, f"{str(path)!r} has no manifest.json")
    spec = _manifest_spec(_strict_json(manifest_bytes, "manifest.json"))
    expected = sorted((spec.glb_file, spec.manifest_file))
    _require(entries == expected, f"package directory must hold exactly {expected}; found {entries}")
    return validate_package_bytes((path / spec.glb_file).read_bytes(), manifest_bytes)


def _manifest_spec(manifest) -> ContractSpec:
    _require(isinstance(manifest, dict), "manifest.json is not a JSON object")
    contract = manifest.get("contract")
    _require(isinstance(contract, dict) and "version" in contract,
             "manifest declares no explicit contract version (there is no implicit latest)")
    _require(contract.get("id") == CONTRACT_ID, f"manifest contract id {contract.get('id')!r} is not {CONTRACT_ID!r}")
    return contract_spec(contract["version"])


def validate_package_bytes(glb_bytes: bytes, manifest_bytes: bytes) -> PackageReport:
    checks: list[str] = []
    manifest = _strict_json(manifest_bytes, "manifest.json")
    checks.append("manifest.json")
    spec = _manifest_spec(manifest)
    _require(manifest["contract"] == {"id": spec.contract_id, "name": spec.name, "version": spec.version},
             f"manifest contract block must be exactly id/name/version of contract v{spec.version}")
    checks.append("manifest.contract")

    glb = parse_glb(glb_bytes)
    checks += ["glb.header", "glb.chunks"]
    g = _Gltf(glb, checks)

    _require(manifest_bytes == _pretty(manifest), "manifest.json is not in canonical form "
             "(sorted keys, 2-space indent, ASCII, LF, trailing newline)")
    checks.append("manifest.canonical")
    m = manifest
    _keys(m, set(spec.manifest_sections), set(), "manifest")
    checks.append("manifest.schema")

    _check_identity(m, g.doc, spec)
    checks.append("manifest.identity")
    _check_coordinates(m["coordinates"], spec)
    checks.append("manifest.coordinates")
    root = _check_package(m["package"], g, spec)
    checks.append("manifest.package")
    sockets = _check_sockets(m["sockets"], g, spec, root)
    checks.append("contract.sockets")
    render, collision = _check_collision(m["collision"], g, spec, root)
    checks.append("contract.collision")
    _check_lods(m["lods"], g, spec, render)
    checks.append("manifest.lods")
    _check_materials(m["materials"], g, spec, render)
    checks.append("manifest.materials")
    _check_tags(m["tags"])
    checks.append("manifest.tags")
    _check_hygiene(m, "manifest")
    _check_hygiene(g.doc, "glTF JSON")
    checks.append("hygiene")
    verified = _check_hashes(m, g, spec, glb_bytes, render, collision, sockets)
    checks.append("hashes")

    lod_nodes = tuple(m["lods"]["levels"][0]["nodes"])
    return PackageReport(
        contract_id=spec.contract_id,
        contract_version=spec.version,
        asset_type=m["asset"]["asset_type"],
        seed=m["asset"]["seed"],
        generator_id=m["asset"]["generator_id"],
        generator_version=m["asset"]["generator_version"],
        presentation=tuple(sorted(m["presentation"].items())),
        exporter=(m["package"]["exporter"]["format_id"], m["package"]["exporter"]["format_version"]),
        checks=tuple(checks),
        hashes_verified=verified,
        glb_sha256=hashlib.sha256(glb_bytes).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        render_nodes=lod_nodes,
        vertices=m["lods"]["levels"][0]["vertices"],
        triangles=m["lods"]["levels"][0]["triangles"],
        collision_vertices=len(collision["positions"]),
        collision_triangles=len(collision["indices"]) // 3,
        sockets=tuple((s["name"], tuple(s["translation"])) for s in m["sockets"]),
    )


def _version(v, where):
    _require(_is_int(v) and v >= 1, f"{where} must be an explicit integer version >= 1; got {v!r}")


def _check_identity(m, doc, spec):
    a = m["asset"]
    _keys(a, {"asset_type", "display_name", "generator_id", "generator_version", "seed"}, set(), "manifest asset")
    _require(isinstance(a["asset_type"], str) and _ID.fullmatch(a["asset_type"]) is not None, "asset.asset_type invalid")
    _require(isinstance(a["display_name"], str) and a["display_name"], "asset.display_name invalid")
    _require(isinstance(a["generator_id"], str) and _DOTTED_ID.fullmatch(a["generator_id"]) is not None,
             "asset.generator_id invalid")
    _version(a["generator_version"], "asset.generator_version")
    _require(isinstance(a["seed"], str) and _SEED.fullmatch(a["seed"]) is not None and int(a["seed"]) < 1 << 64,
             f"asset.seed {a['seed']!r} must be a decimal string in [0, 2**64 - 1]")
    p = m["presentation"]
    _keys(p, {"presentation_id", "presentation_version", "normals_version", "uv_version", "material_version",
              "texcoord_0"}, set(), "manifest presentation")
    _require(isinstance(p["presentation_id"], str) and _DOTTED_ID.fullmatch(p["presentation_id"]) is not None,
             "presentation.presentation_id invalid")
    for key in ("presentation_version", "normals_version", "uv_version", "material_version"):
        _version(p[key], f"presentation.{key}")
    exporter = m["package"].get("exporter") if isinstance(m["package"], dict) else None
    extras = doc["asset"]["extras"]
    expected = {
        "forge_asset_type": a["asset_type"],
        "forge_contract": {"id": spec.contract_id, "version": spec.version},
        "forge_exporter": exporter,
        "forge_generator": {"id": a["generator_id"], "version": a["generator_version"]},
        "forge_presentation": {"id": p["presentation_id"], "version": p["presentation_version"]},
        "forge_seed": a["seed"],
    }
    _require(extras == expected, "glTF asset.extras identity does not match the manifest")


def _check_coordinates(c, spec):
    _require(isinstance(c, dict), "manifest coordinates must be an object")
    for key, value in spec.coordinates.items():
        _require(key in c, f"coordinates.{key} is missing")
        _require(c[key] == value and type(c[key]) is type(value),
                 f"coordinates.{key} is {c[key]!r}; contract v{spec.version} requires {value!r}")
    _require(isinstance(c.get("convention_id"), str) and _DOTTED_ID.fullmatch(c["convention_id"]) is not None,
             "coordinates.convention_id invalid")
    _require(isinstance(c.get("conversion"), str) and c["conversion"].startswith("none"),
             "coordinates.conversion must state that no conversion was applied")
    for key, value in c.items():
        _require(isinstance(value, str) or key == "meters_per_unit", f"coordinates.{key} must be a string")


def _check_package(p, g, spec):
    _keys(p, {"exporter", "glb", "layout", "manifest", "render_scene", "render_scene_index", "root_node"}, set(),
          "manifest package")
    _keys(p["exporter"], {"format_id", "format_version"}, set(), "package.exporter")
    _require(isinstance(p["exporter"]["format_id"], str) and _ID.fullmatch(p["exporter"]["format_id"]) is not None,
             "package.exporter.format_id invalid")
    _version(p["exporter"]["format_version"], "package.exporter.format_version")
    _require((p["glb"], p["manifest"], p["layout"]) == (spec.glb_file, spec.manifest_file, "directory"),
             f"package files must be {spec.glb_file} + {spec.manifest_file} in a directory")
    _require(p["render_scene"] == spec.render_scene and p["render_scene_index"] == 0,
             f"package render scene must be {spec.render_scene!r} at index 0")
    doc = g.doc
    _require(doc["scenes"][0]["name"] == spec.render_scene, "scene 0 is not the render scene")
    _require(p["root_node"] in g.node_index, f"root node {p['root_node']!r} not found")
    root = g.node_index[p["root_node"]]
    _require(p["root_node"] == doc["asset"]["extras"]["forge_asset_type"], "root node must be named after the asset type")
    _require(doc["scenes"][0]["nodes"] == [root], "the render scene must have exactly the asset root node as its root")
    node = doc["nodes"][root]
    _require(not ({"mesh", "translation", "rotation"} & set(node)), "the asset root node must carry no mesh or transform")
    return root


def _check_sockets(sockets, g, spec, root):
    doc = g.doc
    _require(isinstance(sockets, list), "manifest sockets must be a list")
    declared = []
    for i, s in enumerate(sockets):
        where = f"sockets[{i}]"
        _keys(s, {"name", "node_index", "parent", "translation", "rotation", "frame", "derivation"}, set(), where)
        name = s["name"]
        _require(isinstance(name, str) and name.startswith(spec.socket_prefix) and _NAME.fullmatch(name) is not None,
                 f"{where}.name {name!r} invalid")
        _require(name in g.node_index, f"socket {name!r} has no node in the GLB")
        k = g.node_index[name]
        node = doc["nodes"][k]
        _require(s["node_index"] == k, f"socket {name!r} node_index {s['node_index']!r} != {k}")
        _require(g.parent.get(k) == root and s["parent"] == doc["nodes"][root]["name"],
                 f"socket {name!r} must be a direct child of the asset root")
        _require("mesh" not in node and not node.get("children"), f"socket {name!r} node must be empty")
        _require("translation" in node and "rotation" in node, f"socket {name!r} node must state translation and rotation")
        _require(s["translation"] == node["translation"] and s["rotation"] == node["rotation"],
                 f"socket {name!r} transform differs between manifest and GLB")
        _require(isinstance(s["frame"], str) and s["frame"] and isinstance(s["derivation"], str) and s["derivation"],
                 f"socket {name!r} must document its frame and derivation")
        declared.append(name)
    socket_nodes = sorted(n for n in g.node_index if n.startswith(spec.socket_prefix))
    for name in spec.required_sockets:
        _require(name in g.node_index, f"required socket {name!r} is missing from the GLB")
        _require(name in declared, f"required socket {name!r} is missing from the manifest")
    _require(sorted(declared) == socket_nodes and len(set(declared)) == len(declared),
             "manifest sockets and GLB socket nodes differ")
    _require([s["node_index"] for s in sockets] == sorted(s["node_index"] for s in sockets),
             "manifest sockets must be listed in node order")
    origin = doc["nodes"][g.node_index[spec.origin_socket]]
    _require(origin["translation"] == [0, 0, 0] or origin["translation"] == [0.0, 0.0, 0.0],
             f"{spec.origin_socket} must sit exactly at the origin (the grip center)")
    return [doc["nodes"][g.node_index[n]] for n in sorted(declared, key=lambda n: g.node_index[n])]


def _check_collision(c, g, spec, root):
    doc = g.doc
    _keys(c, {"node", "node_index", "representation", "gltf_representation", "derivation", "scene", "scene_index",
              "triangles", "vertices"}, set(), "manifest collision")
    _require(c["node"] == spec.collision_node, f"collision node must be named {spec.collision_node!r}")
    _require(spec.collision_node in g.node_index, f"{spec.collision_node!r} node is missing from the GLB")
    k = g.node_index[spec.collision_node]
    _require(c["node_index"] == k, "collision.node_index does not match the GLB")
    _require(c["representation"] in spec.collision_representations,
             f"collision representation {c['representation']!r} not in {list(spec.collision_representations)}")
    _require(c["scene"] == spec.collision_scene and c["scene_index"] == 1, "collision scene must be index 1")
    _require(len(doc["scenes"]) == 2 and doc["scenes"][1]["name"] == spec.collision_scene
             and doc["scenes"][1]["nodes"] == [k],
             f"the collision node must be the only root of scene 1 ({spec.collision_scene!r})")
    _require(k not in g.subtree(root), "the collision node must not be part of the render hierarchy")
    node = doc["nodes"][k]
    _require("mesh" in node and not ({"translation", "rotation", "children"} & set(node)),
             "the collision node must hold a mesh and no transform or children")
    info = g.mesh_info[node["mesh"]]
    _require(not info["render"] and info["material"] is None,
             "the collision mesh must carry POSITION + indices only and no material")
    render_nodes = [i for i in sorted(g.subtree(root)) if "mesh" in doc["nodes"][i]]
    render = [(doc["nodes"][i]["name"], g.mesh_info[doc["nodes"][i]["mesh"]]) for i in render_nodes]
    for name, mi in render:
        _require(mi["render"], f"render node {name!r} mesh lacks NORMAL/TEXCOORD_0")
    all_render = [p for _, mi in render for p in mi["positions"]]
    _check_convex_hull(info["positions"], info["indices"], all_render, "collision_hull")
    _require(c["vertices"] == len(info["positions"]) and c["triangles"] == len(info["indices"]) // 3,
             "collision vertex/triangle counts do not match the GLB")
    return dict(render), info


def _check_lods(lods, g, spec, render):
    _keys(lods, {"count", "levels", "note"}, set(), "manifest lods")
    levels = lods["levels"]
    _require(isinstance(levels, list) and lods["count"] == len(levels) and
             [lv.get("level") if isinstance(lv, dict) else None for lv in levels] == list(spec.lod_levels),
             f"contract v{spec.version} packages declare exactly LOD levels {list(spec.lod_levels)}")
    lv = levels[0]
    _keys(lv, {"level", "nodes", "triangles", "vertices"}, set(), "lods.levels[0]")
    names = [n for n in g.node_index if n in render]
    ordered = sorted(names, key=lambda n: g.node_index[n])
    _require(lv["nodes"] == ordered, f"LOD0 nodes {lv['nodes']} must list every render node in node order {ordered}")
    _require(lv["vertices"] == sum(len(render[n]["positions"]) for n in ordered)
             and lv["triangles"] == sum(len(render[n]["indices"]) for n in ordered) // 3,
             "LOD0 vertex/triangle counts do not match the GLB")
    for n in ordered:
        extras = g.doc["nodes"][g.node_index[n]].get("extras", {})
        _require(extras.get("forge_lod") == 0, f"render node {n!r} must be tagged forge_lod 0")


def _check_materials(mats, g, spec, render):
    doc = g.doc
    _keys(mats, {"base_color_space", "channels", "components", "model", "procedural_patterns", "textures"}, set(),
          "manifest materials")
    _require(mats["model"] == spec.material_model, f"materials.model must be {spec.material_model!r}")
    ch = mats["channels"]
    _keys(ch, {"populated", "supported"}, set(), "materials.channels")
    _require(ch["supported"] == list(spec.channels), f"materials.channels.supported must be {list(spec.channels)}")
    _keys(ch["populated"], set(spec.channels), set(), "materials.channels.populated")
    _require(all(v in CHANNEL_STATES for v in ch["populated"].values()), "unknown channel state")
    for i, (states, _) in enumerate(g.material_channels):
        _require(states == ch["populated"], f"materials[{i}] channel usage {states} != manifest {ch['populated']}")
    comps = mats["components"]
    _require(isinstance(comps, list) and len(comps) == len(doc["materials"]) == len(render),
             "one manifest material entry per glTF material and render node")
    for i, c in enumerate(comps):
        where = f"materials.components[{i}]"
        _keys(c, {"base_color_factor", "component", "material", "material_index", "metallic_factor", "node", "preset",
                  "procedural_pattern", "roughness_factor"}, set(), where)
        _require(c["material_index"] == i and doc["materials"][i]["name"] == c["material"],
                 f"{where} does not match glTF material {i}")
        pbr = doc["materials"][i]["pbrMetallicRoughness"]
        _require(c["base_color_factor"] == pbr.get("baseColorFactor") and c["metallic_factor"] == pbr.get("metallicFactor")
                 and c["roughness_factor"] == pbr.get("roughnessFactor"), f"{where} factors differ from the GLB")
        _require(c["node"] in render and render[c["node"]]["material"] == i,
                 f"{where}: node {c['node']!r} does not use material {i}")
    textures = mats["textures"]
    _require(isinstance(textures, list), "materials.textures must be a list")
    used = sorted({(i, ch_) for i, (_, refs) in enumerate(g.material_channels) for ch_ in refs})
    declared = []
    for k, t in enumerate(textures):
        where = f"materials.textures[{k}]"
        _keys(t, {"channel", "color_space", "height", "image_index", "material", "mime_type", "pixel_format",
                  "texture_index", "width"}, set(), where)
        _require(t["channel"] in spec.channels, f"{where}.channel invalid")
        mi = next((i for i, m in enumerate(doc["materials"]) if m["name"] == t["material"]), None)
        _require(mi is not None and g.material_channels[mi][1].get(t["channel"]) == t["texture_index"],
                 f"{where} does not match the GLB material's texture reference")
        _require(doc["textures"][t["texture_index"]]["source"] == t["image_index"], f"{where}.image_index mismatch")
        info = g.image_info[t["image_index"]]
        _require((t["width"], t["height"], t["pixel_format"], t["mime_type"]) ==
                 (info["width"], info["height"], info["pixel_format"], "image/png"),
                 f"{where} dimensions/pixel format/MIME type differ from the embedded image")
        want = "srgb" if t["channel"] in _SRGB_CHANNELS else "linear"
        _require(t["color_space"] == want, f"{where}.color_space must be {want!r} for {t['channel']}")
        declared.append((mi, t["channel"]))
    _require(sorted(declared) == used, "manifest textures and GLB texture references differ")


def _check_tags(tags):
    _require(isinstance(tags, list) and all(isinstance(t, str) and _TAG.fullmatch(t) for t in tags),
             "tags must be strings like 'key:value' (lowercase)")
    _require(tags == sorted(set(tags)), "tags must be sorted and unique")


def _check_hygiene(obj, where, path="$"):
    """No timestamps, absolute paths, process ids, host/user names, or UUIDs anywhere."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _require(k.lower() not in _ENVIRONMENT_KEYS, f"{where} {path}: environment-specific key {k!r}")
            _check_hygiene(k, where, path)
            _check_hygiene(v, where, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_hygiene(v, where, f"{path}[{i}]")
    elif isinstance(obj, str):
        _require(_UUID.search(obj) is None, f"{where} {path}: contains a UUID")
        _require(_TIMESTAMP.search(obj) is None, f"{where} {path}: contains a timestamp")
        _require(_ABSOLUTE.search(obj) is None, f"{where} {path}: contains an absolute path")


def _f32(values) -> bytes:
    values = list(values)
    return struct.pack(f"<{len(values)}f", *values)


def _check_hashes(m, g, spec, glb_bytes, render, collision, sockets):
    hashes = m["hashes"]
    _require(isinstance(hashes, dict), "manifest hashes must be an object")
    required = set(spec.package_hashes) | {spec.content_hash}
    _require(required <= set(hashes), f"manifest hashes are missing {sorted(required - set(hashes))}")
    for name, entry in hashes.items():
        _keys(entry, {"covers", "sha256", "verifiable_from_package"}, set(), f"hashes.{name}")
        _require(isinstance(entry["sha256"], str) and _SHA.fullmatch(entry["sha256"]) is not None,
                 f"hashes.{name}.sha256 is not 64 lowercase hex digits")
        if name in spec.package_hashes:
            _require(entry["covers"] == spec.package_hashes[name] and entry["verifiable_from_package"] is True,
                     f"hashes.{name} must state exactly what contract v{spec.version} says it covers")
        elif name == spec.content_hash:
            _require(entry["covers"] == CONTENT_HASH_COVERS and entry["verifiable_from_package"] is True,
                     f"hashes.{name} covers text is wrong")
        else:
            _require(name.startswith(spec.source_hash_prefix) and entry["verifiable_from_package"] is False
                     and isinstance(entry["covers"], str) and entry["covers"],
                     f"hashes.{name}: only '{spec.source_hash_prefix}*' provenance hashes may be added, "
                     "and they are not verifiable from the package")

    root_name = m["package"]["root_node"]
    lod_nodes = m["lods"]["levels"][0]["nodes"]
    h = hashlib.sha256(b"forge.engine.render-geometry.v1\0")
    for name in lod_nodes:
        mi = render[name]
        h.update(name.encode("ascii") + b"\0" + g.doc["materials"][mi["material"]]["name"].encode("ascii") + b"\0")
        h.update(struct.pack("<II", len(mi["positions"]), len(mi["indices"])))
        for rows in (mi["positions"], mi["normals"], mi["texcoords"]):
            h.update(_f32(c for r in rows for c in r))
        h.update(struct.pack(f"<{len(mi['indices'])}I", *mi["indices"]))
    hc = hashlib.sha256(b"forge.engine.collision.v1\0")
    hc.update(spec.collision_node.encode("ascii") + b"\0")
    hc.update(struct.pack("<II", len(collision["positions"]), len(collision["indices"])))
    hc.update(_f32(c for p in collision["positions"] for c in p))
    hc.update(struct.pack(f"<{len(collision['indices'])}I", *collision["indices"]))

    json_length = struct.unpack_from("<I", glb_bytes, 12)[0]
    actual = {
        "glb_sha256": hashlib.sha256(glb_bytes).hexdigest(),
        "gltf_json_sha256": hashlib.sha256(g.glb.json_chunk).hexdigest(),
        "gltf_bin_sha256": hashlib.sha256(g.glb.bin_chunk).hexdigest(),
        "render_geometry_sha256": h.hexdigest(),
        "collision_sha256": hc.hexdigest(),
        "sockets_sha256": _canonical_sha([{"name": n["name"], "parent": root_name, "rotation": n["rotation"],
                                           "translation": n["translation"]} for n in sockets]),
        "pbr_materials_sha256": _canonical_sha(g.doc["materials"]),
    }
    _require(json_length == len(g.glb.json_chunk), "GLB JSON chunk length changed during validation")
    actual["semantic_sha256"] = _canonical_sha({
        "contract": {"id": spec.contract_id, "version": spec.version},
        "coordinates": m["coordinates"], "lods": m["lods"],
        **{k: actual[k] for k in ("collision_sha256", "pbr_materials_sha256", "render_geometry_sha256",
                                  "sockets_sha256")}})
    without_self = {**m, "hashes": {k: v for k, v in hashes.items() if k != spec.content_hash}}
    actual[spec.content_hash] = _canonical_sha(without_self)
    verified = []
    for name in sorted(actual):
        _require(hashes[name]["sha256"] == actual[name],
                 f"hash mismatch: {name} declares {hashes[name]['sha256']} but the package gives {actual[name]}")
        verified.append(name)
    return tuple(verified)
