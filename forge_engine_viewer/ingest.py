"""Ingest a Contract v1 package from disk: discover, validate, parse, decode, and interpret it.

Load flow (each step must pass before the next one runs; nothing is rendered here):
   1. discover   the directory holds exactly asset.glb + manifest.json
   2. manifest   strict JSON, contract id + explicit supported version, canonical bytes,
                 sections, canonical coordinates
   3. hashes     glb_sha256 over the file bytes; manifest_content_sha256
   4. GLB        header, chunks, chunk hashes, document, buffers and views
   5. nodes      hierarchy, scenes, node transforms (translation + rotation; Contract v1 uses no scale/matrix)
   6. geometry   render meshes of the default scene: POSITION, NORMAL, TEXCOORD_0, indices
   7. materials  PBR metallic-roughness factors
   8. sockets    socket_grip / socket_tip from the node hierarchy, never recomputed
   9. collision  collision_hull from the collision scene, never recomputed: closed and consistently
                 wound, and (exact integer test) no render or hull vertex outside any hull face
  10. LOD        manifest LOD0 against the decoded render nodes
  11. identity   GLB asset.extras against the manifest
  12. semantic   render geometry, collision, sockets, materials and semantic hashes, recomputed from the
                 decoded data. This proves the decoder read exactly what the package declares.

Fail closed: the first problem raises IngestionError with a stable code. Nothing is repaired.
The package is only read (open(..., "rb")), never written.
No Forge module is imported, by design.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from forge_engine_viewer import contract_v1 as C
from forge_engine_viewer.errors import IngestionError, refuse, require
from forge_engine_viewer.glb import AccessorReader, read_glb, strict_json

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
IDENTITY_Q: Quat = (0.0, 0.0, 0.0, 1.0)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_SHA = re.compile(r"[0-9a-f]{64}")
_SEED = re.compile(r"0|[1-9][0-9]{0,19}")
_TOP_LEVEL = {"accessors", "asset", "bufferViews", "buffers", "images", "materials", "meshes", "nodes",
              "samplers", "scene", "scenes", "textures"}
_UNSUPPORTED_TOP_LEVEL = {"animations", "skins", "cameras", "extensions", "extensionsUsed", "extensionsRequired"}


# ------------------------------------------------------------------ the ingested model (immutable)

@dataclass(frozen=True)
class Transform:
    translation: Vec3 = (0.0, 0.0, 0.0)
    rotation: Quat = IDENTITY_Q

    def apply(self, p: Vec3) -> Vec3:
        x, y, z = rotate(self.rotation, p)
        tx, ty, tz = self.translation
        return (x + tx, y + ty, z + tz)

    def then(self, child: "Transform") -> "Transform":
        """This transform (parent) composed with a child's local transform."""
        return Transform(translation=self.apply(child.translation),
                         rotation=quat_mul(self.rotation, child.rotation))


@dataclass(frozen=True)
class MeshData:
    node: str
    node_index: int
    world: Transform
    positions: tuple[Vec3, ...]
    normals: tuple[Vec3, ...]
    texcoords: tuple[tuple[float, float], ...]
    indices: tuple[int, ...]
    material_index: int | None

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


@dataclass(frozen=True)
class MaterialData:
    index: int
    name: str
    base_color_factor: tuple[float, float, float, float]
    metallic_factor: float
    roughness_factor: float
    explicit: tuple[str, ...]            # which factors the package states (others are glTF defaults)
    alpha_mode: str
    double_sided: bool
    preset: str | None                   # informational, from material extras


@dataclass(frozen=True)
class SocketData:
    name: str
    node_index: int
    parent: str
    local: Transform                     # exactly the node's translation/rotation
    world: Transform                     # composed through the hierarchy
    frame: str
    derivation: str


@dataclass(frozen=True)
class CollisionData:
    node: str
    node_index: int
    scene_index: int
    scene_name: str
    representation: str
    world: Transform
    positions: tuple[Vec3, ...]
    indices: tuple[int, ...]
    closed: bool                         # every edge shared by exactly two triangles, consistently wound

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


@dataclass(frozen=True)
class LodLevel:
    level: int
    nodes: tuple[str, ...]
    vertices: int
    triangles: int


@dataclass(frozen=True)
class IngestedPackage:
    path: str
    contract_id: str
    contract_version: int
    asset: dict                          # manifest asset section (copy)
    presentation: dict
    coordinates: dict
    package: dict
    tags: tuple[str, ...]
    channels: dict                       # manifest materials.channels (supported vs populated)
    root: str
    render_scene: tuple[int, str]
    meshes: tuple[MeshData, ...]
    materials: tuple[MaterialData, ...]
    sockets: tuple[SocketData, ...]
    collision: CollisionData
    lods: tuple[LodLevel, ...]
    lod_note: str
    glb_sha256: str                      # computed from the file bytes (and equal to the manifest's)
    manifest_sha256: str                 # computed from the manifest file bytes
    hashes: dict                         # manifest hash name -> sha256, as declared
    hashes_verified: tuple[str, ...]
    provenance_hashes: tuple[str, ...]   # source_* entries: reported, not verifiable from the package
    checks: tuple[str, ...]

    def socket(self, name: str) -> SocketData:
        for s in self.sockets:
            if s.name == name:
                return s
        raise KeyError(name)


# ------------------------------------------------------------------ math (quaternions are x, y, z, w)

def quat_mul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def rotate(q: Quat, v: Vec3) -> Vec3:
    if q == IDENTITY_Q:
        return (v[0] + 0.0, v[1] + 0.0, v[2] + 0.0)
    x, y, z, w = q
    # v' = v + 2w(q x v) + 2 q x (q x v)
    cx, cy, cz = y * v[2] - z * v[1], z * v[0] - x * v[2], x * v[1] - y * v[0]
    dx, dy, dz = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return (v[0] + 2.0 * (w * cx + dx), v[1] + 2.0 * (w * cy + dy), v[2] + 2.0 * (w * cz + dz))


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _pretty(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ": ")) + "\n").encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_only(path: Path) -> bytes:
    with open(path, "rb") as handle:          # the package is never opened for writing
        return handle.read()


def _num(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def _int(v) -> bool:
    return type(v) is int


def _obj(value, code: str, where: str) -> dict:
    require(isinstance(value, dict), code, f"{where} must be a JSON object")
    return value


# ------------------------------------------------------------------ ingestion

def ingest(path) -> IngestedPackage:
    """Validate and load a package. Raises IngestionError (and nothing else) for any package it refuses."""
    try:
        return _ingest(path)
    except IngestionError:
        raise
    except OSError as exc:
        raise IngestionError("unreadable", f"the package could not be read: {exc.strerror or exc}") from exc
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, struct.error) as exc:
        # Structure this viewer didn't anticipate is refused, never guessed around.
        raise IngestionError("malformed_package", f"unexpected package structure ({type(exc).__name__}: {exc})") from exc


def _ingest(path) -> IngestedPackage:
    checks: list[str] = []
    root_path = Path(path)

    # 1. discover
    require(root_path.is_dir(), "not_a_package", f"{str(root_path)!r} is not a package directory")
    entries = sorted(p.name for p in root_path.iterdir())
    require(C.MANIFEST_FILE in entries, "missing_manifest", f"{C.MANIFEST_FILE} is missing from the package")
    require(C.GLB_FILE in entries, "missing_glb", f"{C.GLB_FILE} is missing from the package")
    extra = [e for e in entries if e not in (C.GLB_FILE, C.MANIFEST_FILE)]
    require(not extra, "unexpected_entry", f"a Contract v1 package holds only asset.glb and manifest.json; found {extra}")
    require((root_path / C.MANIFEST_FILE).is_file(), "missing_manifest", "manifest.json is not a file")
    require((root_path / C.GLB_FILE).is_file(), "missing_glb", "asset.glb is not a file")
    manifest_bytes = _read_only(root_path / C.MANIFEST_FILE)
    glb_bytes = _read_only(root_path / C.GLB_FILE)
    checks.append("package.discovered")

    # 2. manifest
    m = strict_json(manifest_bytes, "manifest.json", "bad_manifest")
    _obj(m, "bad_manifest", "manifest.json")
    contract = m.get("contract")
    require(isinstance(contract, dict) and contract.get("id") == C.CONTRACT_ID, "unsupported_contract",
            f"manifest contract id is {contract.get('id') if isinstance(contract, dict) else None!r}; "
            f"this viewer reads {C.CONTRACT_ID!r}")
    version = contract.get("version")
    require(_int(version) and version in C.SUPPORTED_VERSIONS, "unsupported_contract",
            f"contract version {version!r} is not supported; this viewer reads {list(C.SUPPORTED_VERSIONS)} "
            "(an explicit integer; there is no implicit latest)")
    checks.append("manifest.contract")
    require(manifest_bytes == _pretty(m), "bad_manifest", "manifest.json is not in the contract's canonical form")
    missing = sorted(set(C.MANIFEST_SECTIONS) - set(m))
    unknown = sorted(set(m) - set(C.MANIFEST_SECTIONS))
    require(not missing and not unknown, "bad_manifest",
            f"manifest sections differ from Contract v1 (missing {missing}, unknown {unknown})")
    for section in C.MANIFEST_SECTIONS:
        if section not in ("sockets", "tags"):
            _obj(m[section], "bad_manifest", f"manifest {section}")
    checks.append("manifest.schema")
    coords = m["coordinates"]
    for key, value in C.COORDINATES.items():
        require(key in coords, "bad_coordinates", f"coordinates.{key} is missing")
        require(coords[key] == value and type(coords[key]) is type(value), "bad_coordinates",
                f"coordinates.{key} is {coords[key]!r}; Contract v1 requires {value!r}")
    require(coords["origin"] in C.KNOWN_ORIGINS, "bad_coordinates", f"unknown origin convention {coords['origin']!r}")
    checks.append("manifest.coordinates")

    # 3. file-level hashes
    hashes = _obj(m["hashes"], "bad_manifest", "manifest hashes")
    declared = {}
    for name, entry in hashes.items():
        require(isinstance(entry, dict) and isinstance(entry.get("sha256"), str)
                and _SHA.fullmatch(entry["sha256"]) is not None, "bad_manifest",
                f"hashes.{name} must hold a 64-digit lowercase sha256")
        declared[name] = entry["sha256"]
    for name in (*C.BYTE_HASHES, *C.SEMANTIC_HASHES, C.CONTENT_HASH):
        require(name in declared, "bad_manifest", f"hashes.{name} is missing")
    glb_sha = _sha(glb_bytes)
    require(declared["glb_sha256"] == glb_sha, "hash_mismatch",
            f"asset.glb hashes to {glb_sha}, but the manifest declares {declared['glb_sha256']}")
    without = {**m, "hashes": {k: v for k, v in hashes.items() if k != C.CONTENT_HASH}}
    content = _sha(_canonical(without))
    require(declared[C.CONTENT_HASH] == content, "hash_mismatch",
            f"manifest content hashes to {content}, but it declares {declared[C.CONTENT_HASH]}")
    verified = ["glb_sha256", C.CONTENT_HASH]
    checks.append("hashes.file")

    # 4. GLB
    glb = read_glb(glb_bytes)
    checks.append("glb.header_and_chunks")
    for name, data in (("gltf_json_sha256", glb.json_chunk), ("gltf_bin_sha256", glb.bin_chunk)):
        require(declared[name] == _sha(data), "hash_mismatch", f"{name} does not match the GLB chunk")
        verified.append(name)
    doc = glb.document
    asset_block = _obj(doc.get("asset"), "malformed_glb", "glTF asset")
    require(asset_block.get("version") == C.GLTF_VERSION, "malformed_glb",
            f"glTF asset.version is {asset_block.get('version')!r}; this viewer reads glTF 2.0")
    for key in sorted(set(doc) & _UNSUPPORTED_TOP_LEVEL):
        refuse("unsupported_feature", f"the GLB declares {key!r}, which Contract v1 does not use")
    for key in sorted(set(doc) - _TOP_LEVEL - _UNSUPPORTED_TOP_LEVEL):
        refuse("unsupported_feature", f"the GLB has an unknown top-level field {key!r}")
    for key in ("images", "textures", "samplers"):
        if key in doc:
            refuse("unsupported_feature", f"the GLB carries {key}. Contract v1 allows embedded textures, but this "
                                          "viewer does not support them yet (glb:1 writes none)")
    reader = AccessorReader(glb)
    checks.append("glb.buffers")

    # 5. nodes, scenes, transforms
    nodes, parent, world, by_name = _nodes(doc)
    checks.append("gltf.nodes")
    scenes = doc.get("scenes")
    require(_int(doc.get("scene")) and doc["scene"] == 0, "bad_scene",
            f"the default scene must be scene 0; got {doc.get('scene')!r}")
    require(isinstance(scenes, list) and len(scenes) == 2, "bad_scene",
            "Contract v1 GLBs have exactly two scenes: render (0) and collision (1)")
    for i, s in enumerate(scenes):
        _obj(s, "bad_scene", f"scenes[{i}]")
        roots = s.get("nodes")
        require(isinstance(roots, list) and roots and all(_int(r) and 0 <= r < len(nodes) for r in roots),
                "bad_scene", f"scenes[{i}] refers to a node that does not exist")
        require(all(r not in parent for r in roots), "bad_scene", f"scenes[{i}] lists a non-root node as a root")
    require(scenes[0].get("name") == C.RENDER_SCENE and scenes[1].get("name") == C.COLLISION_SCENE, "bad_scene",
            f"scenes must be named {C.RENDER_SCENE!r} (0) and {C.COLLISION_SCENE!r} (1)")
    require(len(scenes[0]["nodes"]) == 1, "bad_scene", "the render scene must have exactly one root (the asset root)")
    root_index = scenes[0]["nodes"][0]
    root_node = nodes[root_index]
    require(root_node["name"] == m["package"].get("root_node"), "bad_scene",
            f"the render scene root is {root_node['name']!r}, but the manifest names {m['package'].get('root_node')!r}")
    require(not ({"translation", "rotation", "mesh"} & set(root_node)), "bad_transform",
            "the asset root must carry no transform and no mesh")
    render_set = _subtree(nodes, root_index)
    collision_scene = set()
    for r in scenes[1]["nodes"]:
        collision_scene |= _subtree(nodes, r)
    require(not (render_set & collision_scene), "bad_scene", "a node appears in both the render and collision scenes")
    checks.append("gltf.scenes")

    # 6. render geometry (default scene only)
    meshes = []
    for i in sorted(render_set):
        n = nodes[i]
        if "mesh" not in n:
            continue
        meshes.append(_render_mesh(doc, reader, i, n, world[i]))
    require(meshes, "bad_scene", "the render scene contains no mesh")
    checks.append("geometry.decoded")

    # 7. materials
    materials = _materials(doc)
    for mesh in meshes:
        require(mesh.material_index is not None and 0 <= mesh.material_index < len(materials), "bad_material",
                f"render node {mesh.node!r} refers to material {mesh.material_index!r}, which does not exist")
    _check_manifest_materials(m["materials"], materials, meshes)
    checks.append("materials.loaded")

    # 8. sockets: straight from the node hierarchy
    sockets = _sockets(m, nodes, parent, world, by_name, root_index)
    checks.append("sockets.located")

    # 9. collision: straight from the collision scene
    collision = _collision(m, doc, reader, nodes, by_name, world, render_set, scenes,
                           [mesh.world.apply(p) for mesh in meshes for p in mesh.positions])
    checks.append("collision.located")

    # 10. LOD
    lods, note = _lods(m["lods"], meshes)
    checks.append("lod.checked")

    # 11. identity
    _identity(m, asset_block)
    checks.append("identity.matched")

    # 12. semantic hashes, recomputed from what this viewer decoded
    verified += _semantic_hashes(m, declared, doc, meshes, materials, collision, nodes, root_node["name"], lods)
    checks.append("hashes.semantic")

    return IngestedPackage(
        path=str(root_path), contract_id=C.CONTRACT_ID, contract_version=version,
        asset=dict(m["asset"]), presentation=dict(m["presentation"]), coordinates=dict(coords),
        package=dict(m["package"]), tags=tuple(m["tags"]),
        channels=json.loads(json.dumps(m["materials"].get("channels", {}))),
        root=root_node["name"], render_scene=(0, scenes[0]["name"]),
        meshes=tuple(meshes), materials=tuple(materials), sockets=tuple(sockets), collision=collision,
        lods=lods, lod_note=note, glb_sha256=glb_sha, manifest_sha256=_sha(manifest_bytes),
        hashes=dict(declared), hashes_verified=tuple(sorted(verified)),
        provenance_hashes=tuple(sorted(k for k in declared if k.startswith(C.SOURCE_HASH_PREFIX))),
        checks=tuple(checks),
    )


def _subtree(nodes, start: int) -> set:
    out, stack = set(), [start]
    while stack:
        k = stack.pop()
        out.add(k)
        stack.extend(nodes[k].get("children", ()))
    return out


def _local_transform(node: dict, where: str) -> Transform:
    for key in ("matrix", "scale"):
        require(key not in node, "bad_transform", f"{where} uses {key!r}; Contract v1 nodes use translation and "
                                                  "rotation only")
    t = node.get("translation", [0.0, 0.0, 0.0])
    q = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    require(isinstance(t, list) and len(t) == 3 and all(_num(c) for c in t), "bad_transform",
            f"{where}.translation must be 3 finite numbers")
    require(isinstance(q, list) and len(q) == 4 and all(_num(c) for c in q), "bad_transform",
            f"{where}.rotation must be 4 finite numbers (x, y, z, w)")
    length = math.sqrt(sum(c * c for c in q))
    require(abs(length - 1.0) <= 1e-6, "bad_transform", f"{where}.rotation is not a unit quaternion (|q| = {length!r})")
    return Transform(translation=tuple(float(c) for c in t), rotation=tuple(float(c) for c in q))


def _nodes(doc):
    nodes = doc.get("nodes")
    require(isinstance(nodes, list) and nodes, "bad_node", "the GLB has no nodes")
    by_name, parent = {}, {}
    for i, n in enumerate(nodes):
        where = f"nodes[{i}]"
        _obj(n, "bad_node", where)
        name = n.get("name")
        require(isinstance(name, str) and _NAME.fullmatch(name) is not None, "bad_node", f"{where} has an invalid name")
        require(name not in by_name, "bad_node", f"node name {name!r} is used twice")
        by_name[name] = i
        for key in ("camera", "skin", "weights"):
            require(key not in n, "unsupported_feature", f"{where} uses {key!r}, which Contract v1 does not use")
        children = n.get("children", [])
        require(isinstance(children, list), "bad_node", f"{where}.children must be a list")
        for c in children:
            require(_int(c) and 0 <= c < len(nodes) and c != i, "bad_node", f"{where} has an invalid child {c!r}")
            require(c not in parent, "bad_node", f"node {c} has two parents")
            parent[c] = i
        if "mesh" in n:
            require(_int(n["mesh"]) and 0 <= n["mesh"] < len(doc.get("meshes", [])), "bad_node",
                    f"{where} refers to mesh {n['mesh']!r}, which does not exist")
    for i in range(len(nodes)):
        seen, k = set(), i
        while k in parent:
            require(k not in seen, "bad_node", "the node hierarchy has a cycle")
            seen.add(k)
            k = parent[k]
    local = [_local_transform(n, f"nodes[{i}] ({n['name']})") for i, n in enumerate(nodes)]
    world: dict[int, Transform] = {}

    def resolve(i: int) -> Transform:
        if i not in world:
            world[i] = resolve(parent[i]).then(local[i]) if i in parent else local[i]
        return world[i]

    for i in range(len(nodes)):
        resolve(i)
    return nodes, parent, world, by_name


def _primitive(doc, node, where):
    meshes = doc.get("meshes")
    mesh = meshes[node["mesh"]]
    _obj(mesh, "bad_mesh", where)
    prims = mesh.get("primitives")
    require(isinstance(prims, list) and len(prims) == 1, "bad_mesh", f"{where} must have exactly one primitive")
    p = _obj(prims[0], "bad_mesh", f"{where} primitive")
    require("targets" not in p, "unsupported_feature", f"{where} uses morph targets")
    require(p.get("mode") == C.TRIANGLES and _int(p.get("mode")), "bad_mesh",
            f"{where} primitive mode is {p.get('mode')!r}; Contract v1 meshes are indexed triangle lists (mode 4)")
    require("indices" in p, "bad_mesh", f"{where} primitive is not indexed")
    attrs = p.get("attributes")
    require(isinstance(attrs, dict), "bad_mesh", f"{where} primitive has no attributes")
    return p, attrs


def _indices(reader, p, vertex_count, where):
    rows = reader.decode(p["indices"], f"{where} indices", types=("SCALAR",),
                         components=(C.UNSIGNED_SHORT, C.UNSIGNED_INT))
    require(reader.view_target(p["indices"]) == C.ELEMENT_ARRAY_BUFFER, "bad_accessor",
            f"{where} indices must live in an ELEMENT_ARRAY_BUFFER bufferView")
    indices = tuple(r[0] for r in rows)
    require(len(indices) % 3 == 0, "bad_mesh", f"{where} index count {len(indices)} is not a multiple of 3")
    restart = 0xFFFF if reader.accessors[p["indices"]]["componentType"] == C.UNSIGNED_SHORT else 0xFFFFFFFF
    for k in indices:
        require(k < vertex_count and k != restart, "bad_accessor",
                f"{where} index {k} is out of range for {vertex_count} vertices")
    for t in range(0, len(indices), 3):
        a, b, c = indices[t:t + 3]
        require(a != b and b != c and a != c, "bad_mesh", f"{where} triangle {t // 3} repeats a vertex")
    return indices


def _render_mesh(doc, reader, index, node, world) -> MeshData:
    where = f"render node {node['name']!r}"
    p, attrs = _primitive(doc, node, where)
    for name in C.RENDER_ATTRIBUTES:
        require(name in attrs, "missing_attribute", f"{where} has no {name} attribute")
    extra = sorted(set(attrs) - set(C.RENDER_ATTRIBUTES))
    require(not extra, "unsupported_feature", f"{where} carries attributes {extra} that Contract v1 does not define")
    positions = reader.decode(attrs["POSITION"], f"{where} POSITION", types=("VEC3",), components=(C.FLOAT,))
    require("min" in reader.accessors[attrs["POSITION"]], "bad_accessor", f"{where} POSITION must declare min/max")
    normals = reader.decode(attrs["NORMAL"], f"{where} NORMAL", types=("VEC3",), components=(C.FLOAT,))
    texcoords = reader.decode(attrs["TEXCOORD_0"], f"{where} TEXCOORD_0", types=("VEC2",), components=(C.FLOAT,))
    require(len(positions) == len(normals) == len(texcoords), "bad_accessor",
            f"{where} attribute counts differ ({len(positions)}, {len(normals)}, {len(texcoords)})")
    for name in C.RENDER_ATTRIBUTES:
        require(reader.view_target(attrs[name]) == C.ARRAY_BUFFER, "bad_accessor",
                f"{where} {name} must live in an ARRAY_BUFFER bufferView")
    for k, nrm in enumerate(normals):
        length = math.sqrt(nrm[0] * nrm[0] + nrm[1] * nrm[1] + nrm[2] * nrm[2])
        require(abs(length - 1.0) <= 1e-5, "bad_mesh", f"{where} NORMAL {k} is not unit length")
    material = p.get("material")
    require(material is None or _int(material), "bad_material", f"{where} has an invalid material reference")
    return MeshData(node=node["name"], node_index=index, world=world, positions=positions, normals=normals,
                    texcoords=texcoords, indices=_indices(reader, p, len(positions), where), material_index=material)


def _materials(doc) -> list[MaterialData]:
    mats = doc.get("materials")
    require(isinstance(mats, list) and mats, "bad_material", "the GLB has no materials")
    out = []
    for i, mat in enumerate(mats):
        where = f"materials[{i}]"
        _obj(mat, "bad_material", where)
        name = mat.get("name")
        require(isinstance(name, str) and _NAME.fullmatch(name) is not None, "bad_material", f"{where} has an invalid name")
        for slot in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            require(slot not in mat, "unsupported_feature", f"{where} uses {slot}; this viewer does not support textures")
        require(mat.get("alphaMode", "OPAQUE") == "OPAQUE", "unsupported_feature",
                f"{where} alphaMode {mat.get('alphaMode')!r}: Contract v1 materials are OPAQUE")
        pbr = mat.get("pbrMetallicRoughness")
        require(isinstance(pbr, dict), "unsupported_feature",
                f"{where} has no pbrMetallicRoughness block; Contract v1 materials are PBR metallic-roughness")
        for slot in ("baseColorTexture", "metallicRoughnessTexture"):
            require(slot not in pbr, "unsupported_feature", f"{where} uses {slot}; this viewer does not support textures")
        unknown = sorted(set(pbr) - {"baseColorFactor", "metallicFactor", "roughnessFactor"})
        require(not unknown, "unsupported_feature", f"{where}.pbrMetallicRoughness has unknown fields {unknown}")
        base = pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
        require(isinstance(base, list) and len(base) == 4 and all(_num(c) and 0 <= c <= 1 for c in base),
                "bad_material", f"{where} baseColorFactor must be 4 numbers in [0, 1]")
        metallic, roughness = pbr.get("metallicFactor", 1.0), pbr.get("roughnessFactor", 1.0)
        for label, value in (("metallicFactor", metallic), ("roughnessFactor", roughness)):
            require(_num(value) and 0 <= value <= 1, "bad_material", f"{where} {label} must be a number in [0, 1]")
        extras = mat.get("extras") if isinstance(mat.get("extras"), dict) else {}
        out.append(MaterialData(
            index=i, name=name, base_color_factor=tuple(float(c) for c in base), metallic_factor=float(metallic),
            roughness_factor=float(roughness),
            explicit=tuple(k for k in ("baseColorFactor", "metallicFactor", "roughnessFactor") if k in pbr),
            alpha_mode=mat.get("alphaMode", "OPAQUE"), double_sided=bool(mat.get("doubleSided", False)),
            preset=extras.get("forge_preset") if isinstance(extras.get("forge_preset"), str) else None))
    return out


def _check_manifest_materials(section, materials, meshes):
    require(section.get("model") == C.MATERIAL_MODEL, "bad_material",
            f"manifest materials.model must be {C.MATERIAL_MODEL!r}")
    comps = section.get("components")
    require(isinstance(comps, list) and len(comps) == len(materials), "bad_material",
            "the manifest must list one material entry per glTF material")
    by_node = {mesh.node: mesh for mesh in meshes}
    for i, c in enumerate(comps):
        where = f"manifest materials.components[{i}]"
        _obj(c, "bad_material", where)
        mat = materials[i] if c.get("material_index") == i else None
        require(mat is not None and c.get("material") == mat.name, "bad_material", f"{where} does not match material {i}")
        require(c.get("base_color_factor") == list(mat.base_color_factor)
                and c.get("metallic_factor") == mat.metallic_factor
                and c.get("roughness_factor") == mat.roughness_factor, "bad_material",
                f"{where} factors differ from the GLB")
        require(c.get("node") in by_node and by_node[c["node"]].material_index == i, "bad_material",
                f"{where}: node {c.get('node')!r} does not use material {i}")
    channels = section.get("channels")
    require(isinstance(channels, dict) and isinstance(channels.get("populated"), dict), "bad_material",
            "manifest materials.channels.populated is missing")
    textured = sorted(k for k, v in channels["populated"].items() if v == "texture")
    require(not textured and section.get("textures") == [], "unsupported_feature",
            f"the manifest declares textured channels {textured}; this viewer does not support textures")


def _sockets(m, nodes, parent, world, by_name, root_index) -> list[SocketData]:
    root_name = nodes[root_index]["name"]
    for name in C.REQUIRED_SOCKETS:
        require(name in by_name, "missing_socket", f"required socket {name!r} is not a node in the GLB")
    declared = m["sockets"]
    require(isinstance(declared, list), "bad_manifest", "manifest sockets must be a list")
    entries = {}
    for i, s in enumerate(declared):
        _obj(s, "bad_manifest", f"manifest sockets[{i}]")
        entries[s.get("name")] = s
    for name in C.REQUIRED_SOCKETS:
        require(name in entries, "missing_socket", f"required socket {name!r} is not declared in the manifest")
    socket_nodes = sorted((i for n, i in by_name.items() if n.startswith(C.SOCKET_PREFIX)))
    require(sorted(by_name[n] for n in entries if n in by_name) == socket_nodes and len(entries) == len(socket_nodes),
            "identity_mismatch", "the manifest's sockets and the GLB's socket_* nodes differ")
    out = []
    for i in socket_nodes:
        node = nodes[i]
        name = node["name"]
        s = entries[name]
        where = f"socket {name!r}"
        require(parent.get(i) == root_index, "bad_node", f"{where} must be a direct child of the asset root")
        require("mesh" not in node and not node.get("children"), "bad_node", f"{where} must be an empty node")
        require("translation" in node and "rotation" in node, "bad_transform",
                f"{where} must state its translation and rotation explicitly")
        require(s.get("node_index") == i and s.get("parent") == root_name, "identity_mismatch",
                f"{where}: the manifest's node index or parent differs from the GLB")
        require(s.get("translation") == node["translation"] and s.get("rotation") == node["rotation"],
                "identity_mismatch", f"{where}: the manifest transform differs from the GLB node")
        local = Transform(translation=tuple(float(c) for c in node["translation"]),
                          rotation=tuple(float(c) for c in node["rotation"]))
        out.append(SocketData(name=name, node_index=i, parent=root_name, local=local, world=world[i],
                              frame=str(s.get("frame", "")), derivation=str(s.get("derivation", ""))))
    origin = next(s for s in out if s.name == C.ORIGIN_SOCKET)
    require(all(c == 0.0 for c in origin.world.translation), "bad_coordinates",
            f"{C.ORIGIN_SOCKET} is at {list(origin.world.translation)}, not at the origin (the grip center)")
    return out


def _exact(points):
    """Binary floats -> integers over one shared power-of-two denominator (exact, no epsilon)."""
    ratios = [tuple(float(c).as_integer_ratio() for c in p) for p in points]
    den = max(d for r in ratios for _, d in r)
    return [tuple(n * (den // d) for n, d in r) for r in ratios]


def _check_convex_and_containing(hull, indices, render_positions, where):
    """The declared representation is convex_hull: no hull vertex and no render vertex may lie
    outside any hull face. This checks the shipped hull. It does not build one."""
    pts = _exact(list(hull) + list(render_positions))
    h = pts[:len(hull)]
    for t in range(0, len(indices), 3):
        a, b, c = h[indices[t]], h[indices[t + 1]], h[indices[t + 2]]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        require((nx, ny, nz) != (0, 0, 0), "bad_collision", f"{where} triangle {t // 3} is degenerate")
        for q in pts:
            require(nx * (q[0] - a[0]) + ny * (q[1] - a[1]) + nz * (q[2] - a[2]) <= 0, "bad_collision",
                    f"{where} is not a convex hull of the render geometry: a vertex lies outside triangle {t // 3}")


def _collision(m, doc, reader, nodes, by_name, world, render_set, scenes, render_positions) -> CollisionData:
    require(C.COLLISION_NODE in by_name, "missing_collision", f"{C.COLLISION_NODE!r} is not a node in the GLB")
    i = by_name[C.COLLISION_NODE]
    node = nodes[i]
    require(i not in render_set, "bad_scene", f"{C.COLLISION_NODE!r} is part of the render scene; it must not be drawn")
    require(scenes[1]["nodes"] == [i], "bad_scene", f"{C.COLLISION_NODE!r} must be the only root of scene 1")
    require("mesh" in node, "missing_collision", f"{C.COLLISION_NODE!r} holds no mesh")
    require(not ({"translation", "rotation", "children"} & set(node)), "bad_transform",
            f"{C.COLLISION_NODE!r} must sit in the asset frame: no transform, no children")
    where = f"collision node {C.COLLISION_NODE!r}"
    p, attrs = _primitive(doc, node, where)
    require(set(attrs) == set(C.COLLISION_ATTRIBUTES), "bad_collision",
            f"{where} must carry POSITION only; found {sorted(attrs)}")
    require("material" not in p, "bad_collision", f"{where} must not reference a material")
    positions = reader.decode(attrs["POSITION"], f"{where} POSITION", types=("VEC3",), components=(C.FLOAT,))
    indices = _indices(reader, p, len(positions), where)
    edges = {}
    for t in range(0, len(indices), 3):
        a, b, c = indices[t:t + 3]
        for e in ((a, b), (b, c), (c, a)):
            edges[e] = edges.get(e, 0) + 1
    closed = all(n == 1 and edges.get((b, a)) == 1 for (a, b), n in edges.items())
    section = m["collision"]
    representation = section.get("representation")
    require(representation in C.COLLISION_REPRESENTATIONS, "bad_collision",
            f"collision representation {representation!r} is not one Contract v1 defines")
    require(section.get("node") == C.COLLISION_NODE and section.get("node_index") == i
            and section.get("scene_index") == 1 and section.get("scene") == C.COLLISION_SCENE, "bad_collision",
            "the manifest's collision section does not match the GLB")
    require(section.get("vertices") == len(positions) and section.get("triangles") == len(indices) // 3,
            "bad_collision", "the manifest's collision counts do not match the GLB")
    require(closed, "bad_collision", f"{where} is not a closed, consistently wound surface")
    _check_convex_and_containing(positions, indices, render_positions, where)
    return CollisionData(node=C.COLLISION_NODE, node_index=i, scene_index=1, scene_name=scenes[1]["name"],
                         representation=representation, world=world[i], positions=positions, indices=indices,
                         closed=closed)


def _lods(section, meshes):
    levels = section.get("levels")
    require(isinstance(levels, list) and section.get("count") == len(levels)
            and [lv.get("level") if isinstance(lv, dict) else None for lv in levels] == list(C.LOD_LEVELS),
            "bad_lod", f"Contract v1 packages declare exactly LOD levels {list(C.LOD_LEVELS)}")
    lv = levels[0]
    names = [mesh.node for mesh in meshes]
    require(lv.get("nodes") == names, "bad_lod", f"LOD0 nodes {lv.get('nodes')} differ from the render nodes {names}")
    require(lv.get("vertices") == sum(len(mesh.positions) for mesh in meshes)
            and lv.get("triangles") == sum(mesh.triangle_count for mesh in meshes), "bad_lod",
            "LOD0 vertex/triangle counts do not match the decoded geometry")
    out = (LodLevel(level=0, nodes=tuple(names), vertices=lv["vertices"], triangles=lv["triangles"]),)
    return out, str(section.get("note", ""))


def _identity(m, asset_block):
    a, p = m["asset"], m["presentation"]
    for key in ("asset_type", "generator_id", "display_name"):
        require(isinstance(a.get(key), str) and a[key], "bad_manifest", f"asset.{key} is missing")
    require(_int(a.get("generator_version")) and a["generator_version"] >= 1, "bad_manifest",
            "asset.generator_version must be an explicit integer")
    require(isinstance(a.get("seed"), str) and _SEED.fullmatch(a["seed"]) is not None and int(a["seed"]) < 1 << 64,
            "bad_manifest", "asset.seed must be a decimal string in [0, 2**64 - 1]")
    extras = asset_block.get("extras")
    expected = {
        "forge_asset_type": a["asset_type"],
        "forge_contract": {"id": C.CONTRACT_ID, "version": m["contract"]["version"]},
        "forge_exporter": m["package"].get("exporter"),
        "forge_generator": {"id": a["generator_id"], "version": a["generator_version"]},
        "forge_presentation": {"id": p.get("presentation_id"), "version": p.get("presentation_version")},
        "forge_seed": a["seed"],
    }
    require(extras == expected, "identity_mismatch", "the GLB's asset.extras identity does not match the manifest")


def _f32(values) -> bytes:
    values = list(values)
    return struct.pack(f"<{len(values)}f", *values)


def _semantic_hashes(m, declared, doc, meshes, materials, collision, nodes, root_name, lods) -> list[str]:
    """Recompute the contract's semantic hashes from the data this viewer decoded (contract section 13)."""
    h = hashlib.sha256(C.RENDER_GEOMETRY_TAG)
    for mesh in meshes:                                   # LOD0 order == node order (checked above)
        h.update(mesh.node.encode("ascii") + b"\0" + materials[mesh.material_index].name.encode("ascii") + b"\0")
        h.update(struct.pack("<II", len(mesh.positions), len(mesh.indices)))
        for rows in (mesh.positions, mesh.normals, mesh.texcoords):
            h.update(_f32(c for r in rows for c in r))
        h.update(struct.pack(f"<{len(mesh.indices)}I", *mesh.indices))
    hc = hashlib.sha256(C.COLLISION_TAG)
    hc.update(collision.node.encode("ascii") + b"\0")
    hc.update(struct.pack("<II", len(collision.positions), len(collision.indices)))
    hc.update(_f32(c for p in collision.positions for c in p))
    hc.update(struct.pack(f"<{len(collision.indices)}I", *collision.indices))
    socket_nodes = [n for n in nodes if n["name"].startswith(C.SOCKET_PREFIX)]
    actual = {
        "render_geometry_sha256": h.hexdigest(),
        "collision_sha256": hc.hexdigest(),
        "sockets_sha256": _sha(_canonical([{"name": n["name"], "parent": root_name, "rotation": n["rotation"],
                                            "translation": n["translation"]} for n in socket_nodes])),
        "pbr_materials_sha256": _sha(_canonical(doc["materials"])),
    }
    actual["semantic_sha256"] = _sha(_canonical({
        "contract": {"id": C.CONTRACT_ID, "version": m["contract"]["version"]},
        "coordinates": m["coordinates"], "lods": m["lods"], **actual}))
    for name in C.SEMANTIC_HASHES:
        require(declared[name] == actual[name], "hash_mismatch",
                f"{name}: the decoded package gives {actual[name]}, but the manifest declares {declared[name]}")
    return list(C.SEMANTIC_HASHES)
