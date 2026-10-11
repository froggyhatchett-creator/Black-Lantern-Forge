"""Independent validator for Character Mesh Contract v1.

This module intentionally imports no Character Studio generator code.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
CONTRACT_ID = "forge.character-mesh"


class CharacterGlbError(ValueError):
    pass


def validate_character_glb_bytes(data: bytes) -> dict:
    if not isinstance(data, bytes) or len(data) < 28:
        raise CharacterGlbError("GLB is too short")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if (magic, version, total) != (MAGIC, 2, len(data)):
        raise CharacterGlbError("invalid GLB header")
    json_len, json_kind = struct.unpack_from("<II", data, 12)
    if json_kind != JSON_CHUNK or 20 + json_len + 8 > len(data):
        raise CharacterGlbError("invalid JSON chunk")
    try:
        document = json.loads(data[20:20 + json_len].rstrip(b" ").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CharacterGlbError("GLB JSON does not parse") from exc
    bin_offset = 20 + json_len
    bin_len, bin_kind = struct.unpack_from("<II", data, bin_offset)
    if bin_kind != BIN_CHUNK or bin_offset + 8 + bin_len != len(data):
        raise CharacterGlbError("invalid BIN chunk")
    extras = document.get("asset", {}).get("extras", {})
    if extras.get("contract") not in ({"id": CONTRACT_ID, "version": 1}, {"id": CONTRACT_ID, "version": 2}):
        raise CharacterGlbError("unsupported or missing character contract")
    if extras.get("units") != "meters" or extras.get("up_axis") != "+Y":
        raise CharacterGlbError("unsupported character coordinates")
    if extras["contract"]["version"] == 2:
        skeleton = extras.get("skeleton_landmarks", {})
        if skeleton.get("contract") != {"id": "forge.character-skeleton-landmarks", "version": 1}:
            raise CharacterGlbError("v2 character is missing skeleton landmarks")
        if len(skeleton.get("joints", [])) < 20:
            raise CharacterGlbError("v2 skeleton landmark set is incomplete")
    meshes = document.get("meshes")
    nodes = document.get("nodes")
    if not isinstance(meshes, list) or len(meshes) != 1 or not isinstance(nodes, list) or len(nodes) != 1:
        raise CharacterGlbError("contract v1 requires exactly one body mesh and one node")
    primitives = meshes[0].get("primitives", [])
    if len(primitives) != 1 or primitives[0].get("mode") != 4:
        raise CharacterGlbError("body must be one triangle primitive")
    attrs = primitives[0].get("attributes", {})
    if set(attrs) != {"POSITION", "NORMAL", "TEXCOORD_0"} or "indices" not in primitives[0]:
        raise CharacterGlbError("body attributes are incomplete")
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    if not isinstance(accessors, list) or not isinstance(views, list):
        raise CharacterGlbError("accessor tables are missing")
    for accessor in accessors:
        vi = accessor.get("bufferView")
        if type(vi) is not int or not 0 <= vi < len(views) or not accessor.get("count", 0) > 0:
            raise CharacterGlbError("invalid accessor")
        view = views[vi]
        if view.get("buffer") != 0 or view.get("byteOffset", 0) + view.get("byteLength", 0) > bin_len:
            raise CharacterGlbError("buffer view is out of bounds")
    pos = accessors[attrs["POSITION"]]
    normal = accessors[attrs["NORMAL"]]
    uv = accessors[attrs["TEXCOORD_0"]]
    indices = accessors[primitives[0]["indices"]]
    if pos.get("type") != "VEC3" or normal.get("type") != "VEC3" or uv.get("type") != "VEC2":
        raise CharacterGlbError("attribute accessor types are wrong")
    if not pos["count"] == normal["count"] == uv["count"] or indices.get("count", 0) % 3:
        raise CharacterGlbError("attribute counts or triangle indices are inconsistent")
    return {"contract": extras["contract"], "body_plan_id": extras.get("body_plan_id"),
            "vertices": pos["count"], "triangles": indices["count"] // 3}


def validate_character_glb(path: str | Path) -> dict:
    return validate_character_glb_bytes(Path(path).read_bytes())
