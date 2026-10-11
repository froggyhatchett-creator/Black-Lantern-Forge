"""Build and write a Forge -> Engine Asset Contract v1 package (asset.glb + manifest.json).

Inputs:
  * a frozen asset and its frozen presentation (both already derived through
    the registry)
  * the asset type's descriptor and EngineAdapter
  * its Step 2 integrity hashes, recorded as provenance

Asset generation, presentation, and the existing OBJ exports are only read
here, never changed.

Mapping (contract v1, exporter glb:1):
  render nodes   one node and mesh per component, in component order.
                 Face-varying attributes are unwelded into unique
                 (position, normal, uv) corners, in first-seen (triangle,
                 corner) order. Positions and normals are binary32, and
                 TEXCOORD_0 = (u, 1 - v), since glTF's UV origin is the image's
                 top-left. Triangle order and winding are the frozen mesh's.
  materials      one PBR metallic-roughness material per component: the
                 frozen material v1 factors, unchanged. The procedural pattern
                 isn't baked into textures; its parameters ride along in
                 extras and the manifest.
  sockets        empty child nodes of the root (EngineAdapter.sockets).
                 Translations are rounded to binary32.
  collision      an exact convex hull of every render position, in a separate
                 non-default scene.
  LOD            LOD0 only.

Before any file is written, the package is checked by the independent
validator (forge.engine.validate). Forge never writes a package it would
itself refuse.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from forge.conventions import convention_dict
from forge.engine.contract import CONTENT_HASH_COVERS, MODE_TRIANGLES, ContractSpec, contract_spec
from forge.engine.glb import GlbBuilder, f32_values, pack_glb
from forge.engine.hull import convex_hull
from forge.engine.validate import validate_package_bytes
from forge.errors import EngineContractError, ExportError, GeometryError
from forge.hashing import canonical_sha256

Vec3 = tuple[float, float, float]
IDENTITY_ROTATION = (0.0, 0.0, 0.0, 1.0)


@dataclass(frozen=True)
class EngineSocket:
    """A named attachment frame, as the asset adapter derives it (float64 values; binary32 on export)."""

    name: str
    translation: Vec3
    rotation: tuple[float, float, float, float]   # unit quaternion (x, y, z, w)
    frame: str                                     # what the socket's local axes mean
    derivation: str                                # how the translation is derived from the asset


@dataclass(frozen=True)
class EngineAdapter:
    """How one asset type maps onto the engine contract. Pure derivations; no I/O, no state."""

    asset_type: str
    sockets: Callable[[Any], tuple[EngineSocket, ...]]       # asset -> sockets
    tags: Callable[[Any, Any], tuple[str, ...]]               # (asset, presented) -> tags


@dataclass(frozen=True)
class EnginePackage:
    glb: bytes
    manifest: bytes
    manifest_data: dict

    @property
    def glb_sha256(self) -> str:
        return hashlib.sha256(self.glb).hexdigest()

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.manifest).hexdigest()


def dumps_manifest(manifest: dict) -> bytes:
    """The one canonical byte form of a manifest: sorted keys, 2-space indent, ASCII, trailing newline."""
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ": ")) + "\n").encode("ascii")


# ------------------------------------------------------------------ geometry

@dataclass(frozen=True)
class _RenderMesh:
    name: str
    material: str
    positions: tuple[Vec3, ...]    # binary32 values
    normals: tuple[Vec3, ...]      # binary32 values
    texcoords: tuple[tuple[float, float], ...]
    indices: tuple[int, ...]


def _rows(flat, width):
    return tuple(tuple(flat[i:i + width]) for i in range(0, len(flat), width))


def _render_mesh(mesh, comp) -> _RenderMesh:
    corner_index: dict[tuple[int, int, int], int] = {}
    positions, normals, texcoords, indices = [], [], [], []
    for t, tri in enumerate(mesh.triangles):
        ni, ui = comp.normal_indices[t], comp.uv_indices[t]
        for k in range(3):
            key = (tri[k], ni[k], ui[k])
            j = corner_index.get(key)
            if j is None:
                j = len(positions)
                corner_index[key] = j
                positions.append(mesh.positions[tri[k]])
                normals.append(comp.normals[ni[k]])
                u, v = comp.uvs[ui[k]]
                texcoords.append((u, 1.0 - v))
            indices.append(j)
    pos = _rows(f32_values(c for p in positions for c in p), 3)
    for i in range(0, len(indices), 3):
        a, b, c = pos[indices[i]], pos[indices[i + 1]], pos[indices[i + 2]]
        if a == b or b == c or a == c:
            raise ExportError(f"component {mesh.name!r}: binary32 rounding collapsed triangle {i // 3}")
    return _RenderMesh(
        name=mesh.name,
        material=f"forge_{comp.name}",
        positions=pos,
        normals=_rows(f32_values(c for n in normals for c in n), 3),
        texcoords=_rows(f32_values(c for uv in texcoords for c in uv), 2),
        indices=tuple(indices),
    )


def render_geometry_sha256(meshes) -> str:
    h = hashlib.sha256(b"forge.engine.render-geometry.v1\0")
    for m in meshes:
        h.update(m.name.encode("ascii") + b"\0" + m.material.encode("ascii") + b"\0")
        h.update(struct.pack("<II", len(m.positions), len(m.indices)))
        for rows in (m.positions, m.normals, m.texcoords):
            flat = [c for r in rows for c in r]
            h.update(struct.pack(f"<{len(flat)}f", *flat))
        h.update(struct.pack(f"<{len(m.indices)}I", *m.indices))
    return h.hexdigest()


def collision_sha256(name: str, positions, indices) -> str:
    h = hashlib.sha256(b"forge.engine.collision.v1\0")
    h.update(name.encode("ascii") + b"\0")
    h.update(struct.pack("<II", len(positions), len(indices)))
    flat = [c for p in positions for c in p]
    h.update(struct.pack(f"<{len(flat)}f", *flat))
    h.update(struct.pack(f"<{len(indices)}I", *indices))
    return h.hexdigest()


# ------------------------------------------------------------------ build

def build_engine_package(asset, presented, descriptor, adapter: EngineAdapter, *,
                         source_hashes: tuple[tuple[str, str], ...], exporter: tuple[str, int],
                         contract_version: int) -> EnginePackage:
    """Pure: the same inputs always give the same bytes. Validated before it is returned."""
    spec = contract_spec(contract_version)
    if presented.asset is not asset:
        raise ExportError("presentation belongs to a different asset")
    if adapter.asset_type != asset.asset_type or descriptor.asset_type != asset.asset_type:
        raise ExportError(f"engine adapter {adapter.asset_type!r} cannot export {asset.asset_type!r}")

    meshes = tuple(_render_mesh(m, c) for m, c in zip(asset.components, presented.components))
    try:
        hull = convex_hull(p for m in meshes for p in m.positions)
    except GeometryError as exc:
        raise ExportError(f"collision hull: {exc}") from exc
    sockets = _sockets(adapter.sockets(asset), spec)

    b = GlbBuilder()
    gltf_meshes = []
    for i, m in enumerate(meshes):
        attributes = {"NORMAL": b.float_accessor(m.normals, "VEC3"),
                      "POSITION": b.float_accessor(m.positions, "VEC3", bounds=True),
                      "TEXCOORD_0": b.float_accessor(m.texcoords, "VEC2")}
        gltf_meshes.append({"name": m.name, "primitives": [{
            "attributes": attributes, "indices": b.index_accessor(m.indices, len(m.positions)),
            "material": i, "mode": MODE_TRIANGLES}]})
    hull_indices = tuple(i for t in hull.triangles for i in t)
    gltf_meshes.append({"name": spec.collision_node, "primitives": [{
        "attributes": {"POSITION": b.float_accessor(hull.positions, "VEC3", bounds=True)},
        "indices": b.index_accessor(hull_indices, len(hull.positions)), "mode": MODE_TRIANGLES}]})

    materials = [_material(c) for c in presented.components]

    root = asset.asset_type
    n_render = len(meshes)
    socket_base = 1 + n_render
    collision_index = socket_base + len(sockets)
    nodes = [{"name": root, "children": list(range(1, collision_index)), "extras": {"forge_role": "asset_root"}}]
    for i, m in enumerate(meshes):
        nodes.append({"name": m.name, "mesh": i,
                      "extras": {"forge_component": m.name, "forge_lod": 0, "forge_role": "render"}})
    for s in sockets:
        nodes.append({"name": s["name"], "rotation": list(s["rotation"]), "translation": list(s["translation"]),
                      "extras": {"forge_role": "socket"}})
    nodes.append({"name": spec.collision_node, "mesh": n_render,
                  "extras": {"forge_collision": spec.collision_representations[0], "forge_role": "collision"}})

    identity = {
        "forge_asset_type": asset.asset_type,
        "forge_contract": {"id": spec.contract_id, "version": spec.version},
        "forge_exporter": {"format_id": exporter[0], "format_version": exporter[1]},
        "forge_generator": {"id": descriptor.generator_id, "version": asset.generator_version},
        "forge_presentation": {"id": descriptor.presentation_id,
                               "version": presented.versions.presentation_version},
        "forge_seed": str(asset.seed),
    }
    gltf = {
        "accessors": b.accessors,
        "asset": {"extras": identity, "generator": f"Black Lantern Forge {exporter[0]} exporter format {exporter[1]}",
                  "version": "2.0"},
        "bufferViews": b.buffer_views,
        "buffers": [{"byteLength": len(b.bin_bytes)}],
        "materials": materials,
        "meshes": gltf_meshes,
        "nodes": nodes,
        "scene": 0,
        "scenes": [{"name": spec.render_scene, "nodes": [0]},
                   {"name": spec.collision_scene, "nodes": [collision_index]}],
    }
    glb = pack_glb(gltf, b.bin_bytes)

    manifest = _manifest(spec, asset, presented, descriptor, adapter, exporter, meshes, hull, hull_indices,
                         sockets, socket_base, collision_index, materials, glb, source_hashes)
    package = EnginePackage(glb=glb, manifest=dumps_manifest(manifest), manifest_data=manifest)

    try:
        validate_package_bytes(package.glb, package.manifest)
    except EngineContractError as exc:
        raise ExportError(f"internal error: the package failed its own contract validation: {exc}") from exc
    return package


def _sockets(raw, spec: ContractSpec) -> list[dict]:
    names = [s.name for s in raw]
    if len(set(names)) != len(names) or not set(spec.required_sockets) <= set(names):
        raise ExportError(f"sockets {names} must be unique and include {list(spec.required_sockets)}")
    out = []
    for s in sorted(raw, key=lambda s: s.name):
        if not s.name.startswith(spec.socket_prefix) or not s.frame or not s.derivation:
            raise ExportError(f"socket {s.name!r}: needs the {spec.socket_prefix!r} prefix, a frame and a derivation")
        if tuple(s.rotation) != IDENTITY_ROTATION:
            raise ExportError(f"socket {s.name!r}: contract v1 sockets use the identity rotation")
        out.append({"name": s.name, "translation": f32_values(s.translation), "rotation": IDENTITY_ROTATION,
                    "frame": s.frame, "derivation": s.derivation})
    return out


def _material(comp) -> dict:
    m = comp.material
    return {
        "alphaMode": "OPAQUE",
        "doubleSided": False,
        "extras": {"forge_component": comp.name, "forge_pattern_baked": False, "forge_preset": m.preset,
                   "forge_procedural_pattern": m.pattern.to_dict()},
        "name": f"forge_{comp.name}",
        "pbrMetallicRoughness": {"baseColorFactor": [*m.base_color, 1.0], "metallicFactor": m.metallic,
                                 "roughnessFactor": m.roughness},
    }


def _manifest(spec, asset, presented, descriptor, adapter, exporter, meshes, hull, hull_indices, sockets,
              socket_base, collision_index, materials, glb, source_hashes) -> dict:
    json_len = struct.unpack_from("<I", glb, 12)[0]
    json_chunk = glb[20:20 + json_len]
    bin_chunk = glb[20 + json_len + 8:]

    convention = convention_dict(descriptor.convention_id)
    coordinates = {"convention_id": convention.pop("id"), **convention, "meters_per_unit": 1,
                   "conversion": "none: native glTF 2.0 frame; engine-side axis and unit conversion is the importer's job"}
    lods = {"count": 1, "levels": [{"level": 0, "nodes": [m.name for m in meshes],
                                    "triangles": sum(len(m.indices) for m in meshes) // 3,
                                    "vertices": sum(len(m.positions) for m in meshes)}],
            "note": "LOD0 only. Contract v1 declares no reduced levels and none are generated."}
    socket_entries = [{"name": s["name"], "node_index": socket_base + i, "parent": asset.asset_type,
                       "translation": list(s["translation"]), "rotation": list(s["rotation"]),
                       "frame": s["frame"], "derivation": s["derivation"]} for i, s in enumerate(sockets)]
    contract = {"id": spec.contract_id, "version": spec.version}

    digests = {
        "glb_sha256": hashlib.sha256(glb).hexdigest(),
        "gltf_json_sha256": hashlib.sha256(json_chunk).hexdigest(),
        "gltf_bin_sha256": hashlib.sha256(bin_chunk).hexdigest(),
        "render_geometry_sha256": render_geometry_sha256(meshes),
        "collision_sha256": collision_sha256(spec.collision_node, hull.positions, hull_indices),
        "sockets_sha256": canonical_sha256([{"name": s["name"], "parent": asset.asset_type,
                                             "rotation": list(s["rotation"]),
                                             "translation": list(s["translation"])} for s in sockets]),
        "pbr_materials_sha256": canonical_sha256(materials),
    }
    digests["semantic_sha256"] = canonical_sha256({
        "contract": contract, "coordinates": coordinates, "lods": lods,
        **{k: digests[k] for k in ("collision_sha256", "pbr_materials_sha256", "render_geometry_sha256",
                                   "sockets_sha256")}})
    hashes = {name: {"covers": spec.package_hashes[name], "sha256": digests[name], "verifiable_from_package": True}
              for name in spec.package_hashes}
    for key, value in source_hashes:
        hashes[spec.source_hash_prefix + key] = {
            "covers": f"provenance: Forge's Step 2 integrity hash {key} of the source asset; "
                      "reproducible with Forge from the asset section, not from this package",
            "sha256": value, "verifiable_from_package": False}

    channels = {c: "absent" for c in spec.channels}
    channels.update({"base_color": "factor", "metallic_roughness": "factor"})
    manifest = {
        "asset": {"asset_type": asset.asset_type, "display_name": descriptor.display_name,
                  "generator_id": descriptor.generator_id, "generator_version": asset.generator_version,
                  "seed": str(asset.seed)},
        "collision": {"node": spec.collision_node, "node_index": collision_index,
                      "representation": spec.collision_representations[0],
                      "gltf_representation": "triangle mesh (mode 4) with POSITION and indices only, no material, "
                                             "as the only root of the non-default scene "
                                             f"{spec.collision_scene!r}",
                      "derivation": "exact convex hull (integer arithmetic) of every LOD0 render vertex position "
                                    "after binary32 rounding; its vertices are exactly the extreme points",
                      "scene": spec.collision_scene, "scene_index": 1,
                      "triangles": len(hull.triangles), "vertices": len(hull.positions)},
        "contract": {"id": spec.contract_id, "name": spec.name, "version": spec.version},
        "coordinates": coordinates,
        "hashes": hashes,
        "lods": lods,
        "materials": {
            "base_color_space": "linear (Forge material v1 factors, passed through unchanged)",
            "channels": {"populated": channels, "supported": list(spec.channels)},
            "components": [{"base_color_factor": mat["pbrMetallicRoughness"]["baseColorFactor"],
                            "component": comp.name, "material": mat["name"], "material_index": i,
                            "metallic_factor": mat["pbrMetallicRoughness"]["metallicFactor"],
                            "node": comp.name, "preset": comp.material.preset,
                            "procedural_pattern": comp.material.pattern.to_dict(),
                            "roughness_factor": mat["pbrMetallicRoughness"]["roughnessFactor"]}
                           for i, (comp, mat) in enumerate(zip(presented.components, materials))],
            "model": spec.material_model,
            "procedural_patterns": "not baked: no textures are written; parameters are informational",
            "textures": [],
        },
        "package": {"exporter": {"format_id": exporter[0], "format_version": exporter[1]},
                    "glb": spec.glb_file, "layout": "directory", "manifest": spec.manifest_file,
                    "render_scene": spec.render_scene, "render_scene_index": 0, "root_node": asset.asset_type},
        "presentation": {"presentation_id": descriptor.presentation_id, **presented.versions.to_dict(),
                         "texcoord_0": "(u, 1 - v) of Forge uv v1: glTF's UV origin is the image's top-left"},
        "sockets": socket_entries,
        "tags": sorted(set(adapter.tags(asset, presented))),
    }
    hashes[spec.content_hash] = {"covers": CONTENT_HASH_COVERS,
                                 "sha256": canonical_sha256(manifest), "verifiable_from_package": True}
    return manifest


# ------------------------------------------------------------------ write

def write_engine_package(package: EnginePackage, path, spec: ContractSpec) -> tuple[Path, Path]:
    """Write <path>/asset.glb and <path>/manifest.json. path must end in the package suffix.

    An existing package directory is overwritten in place. Anything else at the
    path is refused rather than mixed in: a file, or a directory that holds
    other entries.
    """
    path = Path(path)
    if path.suffix.lower() != spec.package_suffix:
        raise ExportError(f"package path must end in {spec.package_suffix}; got {str(path)!r}")
    allowed = {spec.glb_file, spec.manifest_file}
    if path.exists():
        if not path.is_dir():
            raise ExportError(f"{str(path)!r} exists and is not a package directory")
        foreign = sorted(p.name for p in path.iterdir() if p.name not in allowed)
        if foreign:
            raise ExportError(f"{str(path)!r} holds other entries {foreign}; refusing to mix them into a package")
    path.mkdir(parents=True, exist_ok=True)
    glb_path, manifest_path = path / spec.glb_file, path / spec.manifest_file
    glb_path.write_bytes(package.glb)
    manifest_path.write_bytes(package.manifest)
    return glb_path, manifest_path
