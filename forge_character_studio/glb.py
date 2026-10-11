"""Character Mesh Contract v1 GLB writer.

This is deliberately separate from frozen Forge -> Engine Contract v1, whose
required weapon sockets and collision rules are not a character contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from forge.engine.contract import MODE_TRIANGLES
from forge.engine.glb import GlbBuilder, pack_glb
from forge_character_studio.model import CharacterAsset, GENERATOR_ID
from forge_character_studio.skeleton import build_skeleton

CONTRACT_ID = "forge.character-mesh"
CONTRACT_VERSION = 2


def _vertex_normals(mesh) -> tuple[tuple[float, float, float], ...]:
    sums = [[0.0, 0.0, 0.0] for _ in mesh.positions]
    for a, b, c in mesh.triangles:
        pa, pb, pc = mesh.positions[a], mesh.positions[b], mesh.positions[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        for i in (a, b, c):
            sums[i][0] += n[0]
            sums[i][1] += n[1]
            sums[i][2] += n[2]
    out = []
    for n in sums:
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if not length > 0.0:
            raise ValueError("character mesh contains a vertex without a usable normal")
        out.append((n[0] / length, n[1] / length, n[2] / length))
    return tuple(out)


def _uvs(mesh) -> tuple[tuple[float, float], ...]:
    (x0, y0, _), (x1, y1, _) = mesh.bounds()
    dx, dy = x1 - x0, y1 - y0
    return tuple(((x - x0) / dx, 1.0 - (y - y0) / dy) for x, y, _ in mesh.positions)


def character_glb(asset: CharacterAsset) -> bytes:
    mesh = asset.body
    builder = GlbBuilder()
    attributes = {
        "NORMAL": builder.float_accessor(_vertex_normals(mesh), "VEC3"),
        "POSITION": builder.float_accessor(mesh.positions, "VEC3", bounds=True),
        "TEXCOORD_0": builder.float_accessor(_uvs(mesh), "VEC2"),
    }
    indices = tuple(i for triangle in mesh.triangles for i in triangle)
    index_accessor = builder.index_accessor(indices, mesh.vertex_count)
    identity = {
        "contract": {"id": CONTRACT_ID, "version": CONTRACT_VERSION},
        "body_plan_id": asset.body_plan_id,
        "generator": {"id": GENERATOR_ID, "version": asset.generator_version},
        "seed": str(asset.seed),
        "units": "meters",
        "up_axis": "+Y",
        "recipe_required_for_regeneration": True,
        "skeleton_landmarks": build_skeleton(asset.parameters).to_dict(),
    }
    gltf = {
        "accessors": builder.accessors,
        "asset": {"version": "2.0", "generator": "Black Lantern Forge Character Studio Step 6B",
                  "extras": identity},
        "bufferViews": builder.buffer_views,
        "buffers": [{"byteLength": len(builder.bin_bytes)}],
        "materials": [{"name": "character_neutral_skin", "doubleSided": False,
                       "pbrMetallicRoughness": {"baseColorFactor": [0.56, 0.36, 0.27, 1.0],
                                                 "metallicFactor": 0.0, "roughnessFactor": 0.72}}],
        "meshes": [{"name": "character_body", "primitives": [{"attributes": attributes,
                     "indices": index_accessor, "material": 0, "mode": MODE_TRIANGLES}]}],
        "nodes": [{"name": "character", "mesh": 0,
                   "extras": {"forge_role": "deformable_character_base", "body_plan_id": asset.body_plan_id}}],
        "scene": 0,
        "scenes": [{"name": "character_render", "nodes": [0]}],
    }
    return pack_glb(gltf, builder.bin_bytes)


def write_character_glb(asset: CharacterAsset, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".glb":
        raise ValueError("character GLB path must end in .glb")
    data = character_glb(asset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def glb_sha256(asset: CharacterAsset) -> str:
    return hashlib.sha256(character_glb(asset)).hexdigest()
