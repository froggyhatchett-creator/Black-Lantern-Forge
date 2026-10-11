"""Deterministic content hashes (SHA-256, lowercase hex).

Every digest is over an explicit, documented byte encoding. Binary encodings
are little-endian and use IEEE-754 binary64 for floats, so they are
platform-independent. Each encoding starts with an ASCII tag naming its
encoding version; changing an encoding means a new tag.

  geometry_sha256   b"forge.geometry.v1\\0" + per component, in order:
                    name + b"\\0" + u32 vertex_count + u32 triangle_count
                    + positions as 3 x f64 each + triangles as 3 x u32 each.
                    Full precision: covers exactly what the frozen generator produced.
  normals_sha256    b"forge.normals.v1\\0" + per component: name + b"\\0"
                    + u32 normal_count + u32 triangle_count
                    + normals as 3 x f64 + normal index triples as 3 x u32.
  uvs_sha256        b"forge.uvs.v1\\0" + per component: name + b"\\0"
                    + u32 uv_count + u32 triangle_count
                    + uvs as 2 x f64 + uv index triples as 3 x u32.
  materials_sha256  canonical JSON (below) of {component: material dict}.
  pixels_sha256     b"forge.pixels.rgb8\\0" + u32 width + u32 height + RGB8 rows, top to bottom.

Canonical JSON: json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=True, allow_nan=False), encoded as ASCII. Python serializes floats
with repr() (shortest round-trip form), so parsed-then-reserialized records
hash identically.
"""

from __future__ import annotations

import hashlib
import json
import struct


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def canonical_sha256(obj) -> str:
    return sha256_hex(canonical_json(obj))


def geometry_sha256(asset) -> str:
    h = hashlib.sha256(b"forge.geometry.v1\0")
    for m in asset.components:
        h.update(m.name.encode("ascii") + b"\0")
        h.update(struct.pack("<II", m.vertex_count, m.triangle_count))
        for p in m.positions:
            h.update(struct.pack("<3d", *p))
        for t in m.triangles:
            h.update(struct.pack("<3I", *t))
    return h.hexdigest()


def normals_sha256(presented) -> str:
    h = hashlib.sha256(b"forge.normals.v1\0")
    for c in presented.components:
        h.update(c.name.encode("ascii") + b"\0")
        h.update(struct.pack("<II", len(c.normals), len(c.normal_indices)))
        for n in c.normals:
            h.update(struct.pack("<3d", *n))
        for t in c.normal_indices:
            h.update(struct.pack("<3I", *t))
    return h.hexdigest()


def uvs_sha256(presented) -> str:
    h = hashlib.sha256(b"forge.uvs.v1\0")
    for c in presented.components:
        h.update(c.name.encode("ascii") + b"\0")
        h.update(struct.pack("<II", len(c.uvs), len(c.uv_indices)))
        for uv in c.uvs:
            h.update(struct.pack("<2d", *uv))
        for t in c.uv_indices:
            h.update(struct.pack("<3I", *t))
    return h.hexdigest()


def materials_sha256(presented) -> str:
    return canonical_sha256(presented.materials)


def pixels_sha256(width: int, height: int, pixels: bytes) -> str:
    return sha256_hex(b"forge.pixels.rgb8\0" + struct.pack("<II", width, height) + pixels)
