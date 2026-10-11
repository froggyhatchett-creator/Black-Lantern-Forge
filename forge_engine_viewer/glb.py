"""Independent GLB reader for Contract v1 packages: header, chunks, JSON, buffers, views, accessors.

This is not a general glTF library. It reads exactly what Contract v1 allows and
refuses anything else instead of guessing:
  * sparse accessors
  * byteStride, normalized integers, URIs
  * extra chunks
  * extensions
Every read is bounds-checked before struct touches the bytes.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass

from forge_engine_viewer import contract_v1 as C
from forge_engine_viewer.errors import refuse, require

COMPONENTS = {C.FLOAT: ("f", 4, "FLOAT"), C.UNSIGNED_SHORT: ("H", 2, "UNSIGNED_SHORT"),
              C.UNSIGNED_INT: ("I", 4, "UNSIGNED_INT")}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def strict_json(data: bytes, where: str, code: str):
    """UTF-8 JSON with no BOM, no duplicate keys, and no NaN/Infinity."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        refuse(code, f"{where} is not valid UTF-8")
    require(not text.startswith("﻿"), code, f"{where} starts with a byte-order mark")

    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, code, f"{where} repeats the key {key!r}")
            out[key] = value
        return out

    def constant(name):
        refuse(code, f"{where} contains {name}, which is not JSON")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        refuse(code, f"{where} is not valid JSON ({exc.msg}, line {exc.lineno})")


@dataclass(frozen=True)
class GlbFile:
    version: int
    length: int
    json_chunk: bytes        # chunk data as stored, padding included
    bin_chunk: bytes         # chunk data as stored, padding included
    document: dict


def read_glb(data: bytes) -> GlbFile:
    """12-byte header, then exactly one JSON chunk and one BIN chunk (Contract v1)."""
    bad = "malformed_glb"
    require(len(data) >= 12, bad, f"asset.glb is {len(data)} bytes, shorter than the 12-byte GLB header")
    magic, version, length = struct.unpack_from("<III", data, 0)
    require(magic == C.GLB_MAGIC, bad, f"asset.glb does not start with the glTF magic (got 0x{magic:08x})")
    require(version == C.GLB_VERSION, bad, f"GLB container version is {version}; only version 2 is supported")
    require(length == len(data), bad, f"GLB header says {length} bytes, file has {len(data)}")
    require(length % 4 == 0, bad, "GLB length is not a multiple of 4")
    chunks, offset = [], 12
    while offset < length:
        require(length - offset >= 8, bad, f"truncated chunk header at byte {offset}")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        require(chunk_length % 4 == 0, bad, f"chunk at byte {offset - 8} is not 4-byte aligned")
        require(chunk_length <= length - offset, bad, f"chunk at byte {offset - 8} runs past the end of the file")
        chunks.append((chunk_type, data[offset:offset + chunk_length]))
        offset += chunk_length
    kinds = [kind for kind, _ in chunks]
    require(kinds == [C.CHUNK_JSON, C.CHUNK_BIN], bad,
            f"expected exactly a JSON chunk then a BIN chunk; found {['0x%08x' % k for k in kinds]}")
    json_chunk, bin_chunk = chunks[0][1], chunks[1][1]
    require(len(json_chunk) > 0, bad, "the JSON chunk is empty")
    document = strict_json(json_chunk, "the GLB JSON chunk", bad)
    require(isinstance(document, dict), bad, "the GLB JSON chunk is not a JSON object")
    return GlbFile(version=version, length=length, json_chunk=json_chunk, bin_chunk=bin_chunk, document=document)


def _int(value) -> bool:
    return type(value) is int


class AccessorReader:
    """Checks buffers and bufferViews once, then decodes accessors on request (bounds-checked, cached)."""

    def __init__(self, glb: GlbFile):
        doc = glb.document
        self.doc, self.bin = doc, glb.bin_chunk
        buffers = doc.get("buffers")
        require(isinstance(buffers, list) and len(buffers) == 1, "malformed_glb",
                "Contract v1 GLBs have exactly one buffer")
        buf = buffers[0]
        require(isinstance(buf, dict) and "uri" not in buf, "unsupported_feature",
                "external buffer URIs are not part of Contract v1")
        n = buf.get("byteLength")
        require(_int(n) and 0 < n <= len(self.bin) and len(self.bin) - n < 4, "malformed_glb",
                f"buffers[0].byteLength {n!r} does not match the {len(self.bin)}-byte BIN chunk")
        self.buffer_length = n
        views = doc.get("bufferViews")
        require(isinstance(views, list) and views, "malformed_glb", "the GLB has no bufferViews")
        for i, v in enumerate(views):
            where = f"bufferViews[{i}]"
            require(isinstance(v, dict), "malformed_glb", f"{where} is not an object")
            require("byteStride" not in v, "unsupported_feature", f"{where} uses byteStride, which Contract v1 does not allow")
            require(v.get("buffer") == 0 and _int(v.get("buffer")), "malformed_glb", f"{where}.buffer must be 0")
            offset, size = v.get("byteOffset", 0), v.get("byteLength")
            require(_int(offset) and offset >= 0 and _int(size) and size > 0, "malformed_glb",
                    f"{where} has an invalid byteOffset/byteLength")
            require(offset + size <= n, "bad_accessor",
                    f"{where} covers bytes [{offset}, {offset + size}) but the buffer has {n}")
            require(v.get("target", C.ARRAY_BUFFER) in (C.ARRAY_BUFFER, C.ELEMENT_ARRAY_BUFFER), "malformed_glb",
                    f"{where}.target {v.get('target')!r} is invalid")
        self.views = views
        accessors = doc.get("accessors")
        require(isinstance(accessors, list) and accessors, "malformed_glb", "the GLB has no accessors")
        self.accessors = accessors
        self._cache: dict[int, tuple] = {}

    def decode(self, index, where: str, *, types: tuple[str, ...], components: tuple[int, ...]) -> tuple:
        """Rows of `index` as tuples (floats or ints), after checking type, component, count and bounds."""
        require(_int(index) and 0 <= index < len(self.accessors), "bad_accessor",
                f"{where} refers to accessor {index!r}, which does not exist")
        a = self.accessors[index]
        aw = f"accessors[{index}] ({where})"
        require(isinstance(a, dict), "bad_accessor", f"{aw} is not an object")
        require("sparse" not in a, "unsupported_feature", f"{aw} is sparse; Contract v1 does not allow sparse accessors")
        require(not a.get("normalized", False), "unsupported_accessor", f"{aw} is normalized; not part of Contract v1")
        require(a.get("componentType") in COMPONENTS, "unsupported_accessor",
                f"{aw} has componentType {a.get('componentType')!r}; Contract v1 uses FLOAT, UNSIGNED_SHORT, UNSIGNED_INT")
        require(a.get("type") in WIDTHS, "unsupported_accessor", f"{aw} has unknown type {a.get('type')!r}")
        require(a["type"] in types and a["componentType"] in components, "unsupported_accessor",
                f"{aw} is {a['type']}/{COMPONENTS[a['componentType']][2]}; expected "
                f"{'/'.join(types)} of {', '.join(COMPONENTS[c][2] for c in components)}")
        count = a.get("count")
        require(_int(count) and count > 0, "bad_accessor", f"{aw}.count must be a positive integer")
        view_index = a.get("bufferView")
        require(_int(view_index) and 0 <= view_index < len(self.views), "bad_accessor",
                f"{aw}.bufferView {view_index!r} does not exist")
        if index in self._cache:
            return self._cache[index]
        code, size, _ = COMPONENTS[a["componentType"]]
        width = WIDTHS[a["type"]]
        view = self.views[view_index]
        offset = a.get("byteOffset", 0)
        require(_int(offset) and offset >= 0, "bad_accessor", f"{aw}.byteOffset is invalid")
        start = view.get("byteOffset", 0) + offset
        require(start % size == 0, "bad_accessor", f"{aw} is not aligned to its {size}-byte components")
        need = count * width * size
        require(offset + need <= view["byteLength"], "bad_accessor",
                f"{aw} needs {offset + need} bytes but bufferViews[{view_index}] holds {view['byteLength']}")
        values = struct.unpack_from(f"<{count * width}{code}", self.bin, start)
        if code == "f":
            require(all(math.isfinite(x) for x in values), "bad_accessor", f"{aw} contains a non-finite float")
        rows = tuple(values[k:k + width] for k in range(0, len(values), width))
        if "min" in a or "max" in a:
            lo = [min(values[c::width]) for c in range(width)]
            hi = [max(values[c::width]) for c in range(width)]
            require(a.get("min") == lo and a.get("max") == hi, "bad_accessor",
                    f"{aw} declares min/max {a.get('min')}/{a.get('max')} but its data spans {lo}/{hi}")
        self._cache[index] = rows
        return rows

    def view_target(self, accessor_index: int):
        return self.views[self.accessors[accessor_index]["bufferView"]].get("target")
