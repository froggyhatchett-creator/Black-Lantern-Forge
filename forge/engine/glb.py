"""Direct GLB (binary glTF 2.0) writer. Standard library only, byte-stable.

This module assembles the two chunks by hand: the JSON document and one binary
buffer. It does no scene logic; forge.engine.package decides what goes in.

Byte stability:
  * The JSON chunk is canonical JSON: sorted keys, compact separators, ASCII,
    no NaN. Python writes floats as their shortest round-trip repr.
  * Binary data is little-endian. Floats are IEEE-754 binary32, rounded to
    nearest-even by struct.pack.
  * Every bufferView starts on a 4-byte boundary. Gaps between views, and the
    end of the buffer, are filled with zero bytes.
  * The JSON chunk is padded with spaces (0x20) and the BIN chunk with zeros
    (0x00), each to a multiple of 4, as glTF 2.0 requires.
  * Nothing environmental goes in: no timestamps, paths, user or host names,
    process ids or random ids.
"""

from __future__ import annotations

import struct

from forge.engine.contract import (
    CHUNK_BIN,
    CHUNK_JSON,
    COMPONENT_FLOAT,
    COMPONENT_UNSIGNED_INT,
    COMPONENT_UNSIGNED_SHORT,
    GLB_MAGIC,
    GLB_VERSION,
    TARGET_ARRAY_BUFFER,
    TARGET_ELEMENT_ARRAY_BUFFER,
)
from forge.errors import ExportError
from forge.hashing import canonical_json

_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * (-len(data) % 4)


def f32_values(values) -> tuple[float, ...]:
    """Round each value to IEEE binary32 (nearest-even) and return it as an exact Python float."""
    values = tuple(values)
    return struct.unpack(f"<{len(values)}f", struct.pack(f"<{len(values)}f", *values))


class GlbBuilder:
    """Collects bufferViews and accessors over one binary buffer."""

    def __init__(self):
        self._bin = bytearray()
        self.buffer_views: list[dict] = []
        self.accessors: list[dict] = []

    def _view(self, payload: bytes, target: int) -> int:
        offset = len(self._bin)                     # always 4-aligned: see the padding below
        self._bin += payload
        self._bin += b"\0" * (-len(self._bin) % 4)
        self.buffer_views.append({"buffer": 0, "byteLength": len(payload), "byteOffset": offset,
                                  "target": target})
        return len(self.buffer_views) - 1

    def float_accessor(self, rows, accessor_type: str, *, bounds: bool = False) -> int:
        """Vertex attribute accessor: rows of floats, stored as binary32."""
        width = _WIDTH[accessor_type]
        rows = tuple(rows)
        if not rows or any(len(r) != width for r in rows):
            raise ExportError(f"accessor {accessor_type}: rows must be non-empty {width}-tuples")
        flat = f32_values(v for r in rows for v in r)
        view = self._view(struct.pack(f"<{len(flat)}f", *flat), TARGET_ARRAY_BUFFER)
        accessor = {"bufferView": view, "componentType": COMPONENT_FLOAT, "count": len(rows),
                    "type": accessor_type}
        if bounds:
            columns = [flat[i::width] for i in range(width)]
            accessor["min"] = [min(c) for c in columns]
            accessor["max"] = [max(c) for c in columns]
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def index_accessor(self, indices, vertex_count: int) -> int:
        """Triangle index accessor. u16 when every index fits below 65535 (the u16 restart value), else u32."""
        indices = tuple(indices)
        if not indices or len(indices) % 3:
            raise ExportError("index accessor: count must be a non-zero multiple of 3")
        if any(not 0 <= i < vertex_count for i in indices):
            raise ExportError("index accessor: index out of range")
        if vertex_count <= 0xFFFF:
            component, payload = COMPONENT_UNSIGNED_SHORT, struct.pack(f"<{len(indices)}H", *indices)
        else:
            component, payload = COMPONENT_UNSIGNED_INT, struct.pack(f"<{len(indices)}I", *indices)
        view = self._view(payload, TARGET_ELEMENT_ARRAY_BUFFER)
        self.accessors.append({"bufferView": view, "componentType": component, "count": len(indices),
                               "type": "SCALAR"})
        return len(self.accessors) - 1

    @property
    def bin_bytes(self) -> bytes:
        return bytes(self._bin)


def pack_glb(gltf: dict, bin_data: bytes) -> bytes:
    """header (12 bytes) + JSON chunk + BIN chunk."""
    json_chunk = _pad(canonical_json(gltf), b" ")
    bin_chunk = _pad(bin_data, b"\0")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    if total >= 1 << 32:
        raise ExportError("GLB exceeds the 4 GiB format limit")
    return b"".join((
        struct.pack("<III", GLB_MAGIC, GLB_VERSION, total),
        struct.pack("<II", len(json_chunk), CHUNK_JSON), json_chunk,
        struct.pack("<II", len(bin_chunk), CHUNK_BIN), bin_chunk,
    ))
