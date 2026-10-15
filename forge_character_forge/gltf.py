"""GLB (glTF 2.0) export: skinned meshes, morph targets, PBR materials with embedded textures, animations.

Contract ``forge.character-forge.glb`` v1:
  * meters, +Y up, character faces +Z, right-handed (glTF native)
  * one skin over every exported joint; joint rest orientations are identity
  * inverseBindMatrices are the inverse rest translations
  * JOINTS_0 is UNSIGNED_SHORT, WEIGHTS_0 FLOAT, sums to 1 (+-1e-5)
  * morph targets are POSITION deltas; names in mesh.extras.targetNames
  * asset.extras.forge carries profile, recipe hash, coverage and dev-only declarations
Output bytes are deterministic for identical inputs on the same platform/numpy.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np

from forge.hashing import canonical_json
from forge_character_forge import appearance as appx
from forge_character_forge.animation import Clip
from forge_character_forge.skeleton import HUMANOID_MAP, PHYSICS_BONES

CONTRACT_ID = "forge.character-forge.glb"
CONTRACT_VERSION = 1
FLOAT, USHORT, UINT = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


class _Bin:
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def view(self, payload: bytes, target: int | None = None) -> int:
        off = len(self.data)
        self.data += payload
        self.data += b"\0" * (-len(self.data) % 4)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(payload)}
        if target:
            v["target"] = target
        self.views.append(v)
        return len(self.views) - 1

    def acc(self, arr: np.ndarray, kind: str, comp: int = FLOAT, target: int | None = ARRAY_BUFFER,
            minmax: bool = False, normalized: bool = False) -> int:
        dtype = {FLOAT: "<f4", USHORT: "<u2", UINT: "<u4"}[comp]
        a = np.ascontiguousarray(np.asarray(arr).astype(dtype))
        if not np.all(np.isfinite(a.astype(float))):
            raise ValueError("non-finite value in accessor")
        a2 = a.reshape(len(a), -1) if a.ndim > 1 else a.reshape(-1, 1)
        acc = {"bufferView": self.view(a.tobytes(), target), "componentType": comp, "count": int(len(a2)),
               "type": kind}
        if minmax:
            acc["min"] = [float(x) for x in a2.min(0)]
            acc["max"] = [float(x) for x in a2.max(0)]
        if normalized:
            acc["normalized"] = True
        self.accessors.append(acc)
        return len(self.accessors) - 1


    def sparse_vec3(self, delta: np.ndarray, eps: float = 1e-7) -> int:
        """Sparse accessor for a morph target: zero base, only displaced vertices stored."""
        d = np.asarray(delta, np.float32)
        idx = np.nonzero(np.abs(d).max(1) > eps)[0].astype("<u4")
        acc = {"componentType": FLOAT, "count": int(len(d)), "type": "VEC3",
               "min": [float(x) for x in d.min(0)], "max": [float(x) for x in d.max(0)]}
        if len(idx):
            acc["sparse"] = {"count": int(len(idx)),
                             "indices": {"bufferView": self.view(idx.tobytes()), "componentType": UINT},
                             "values": {"bufferView": self.view(np.ascontiguousarray(d[idx]).astype("<f4").tobytes())}}
        else:
            acc["min"] = [0.0, 0.0, 0.0]
            acc["max"] = [0.0, 0.0, 0.0]
        self.accessors.append(acc)
        return len(self.accessors) - 1


# ---------------------------------------------------------------- body UVs

def cylindrical_uv_layout(skel, verts: np.ndarray, tris: np.ndarray, dom: np.ndarray, scale: float = 10.0):
    """Cylindrical UVs around each vertex's dominant bone, with seam vertices duplicated.

    Returns (src_index, tris, uv): src_index maps every exported vertex to an input vertex."""
    v = verts
    ang = np.zeros(len(v))
    along = np.zeros(len(v))
    radius = np.zeros(len(v))
    for j in np.unique(dom):
        sel = dom == j
        kids = [i for i, p in enumerate(skel.parents) if p == j]
        a = skel.rest[j]
        b = skel.rest[kids[0]] if kids else a + np.array([0, 0.1, 0])
        if skel.names[j] in ("pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head", "jaw"):
            b = a + np.array([0.0, 0.1, 0.0])
        ax = (b - a) / np.linalg.norm(b - a)
        ref = np.array([0.0, 0.0, 1.0]) if abs(ax[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        e1 = ref - ax * (ref @ ax)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(ax, e1)
        q = v[sel] - a
        ang[sel] = np.arctan2(q @ e2, q @ e1)
        along[sel] = q @ ax + j * 0.37  # offset each bone's band in V
        radius[sel] = np.linalg.norm(q - np.outer(q @ ax, ax), axis=1).mean()
    tris = np.array(tris, np.int64, copy=True)
    src = list(range(len(v)))
    angs = list(ang)
    extra = {}
    ta = ang[tris]
    wrap = (ta.max(1) - ta.min(1)) > math.pi
    for f in np.nonzero(wrap)[0]:
        for k in range(3):
            vi = tris[f, k]
            if ang[vi] < 0:
                if vi not in extra:
                    extra[vi] = len(src)
                    src.append(vi)
                    angs.append(ang[vi] + 2 * math.pi)
                tris[f, k] = extra[vi]
    src = np.array(src)
    angs = np.array(angs)
    uv = np.stack([angs * radius[src], along[src]], 1) * scale
    return src, tris, uv


def body_uv_layout(tpl, scale: float = 10.0):
    """Template body layout (cached on the template object); every character shares it."""
    cached = getattr(tpl, "_uv_layout", None)
    if cached is None:
        cached = cylindrical_uv_layout(tpl.skeleton, tpl.verts, tpl.tris, tpl.joints[:, 0], scale)
        tpl._uv_layout = cached
    return cached


def part_uv_layout(ch, part):
    if getattr(part, "uv_layout", None) is not None:
        return part.uv_layout
    return body_uv_layout(ch.template)


# ---------------------------------------------------------------- materials

def _materials(ch, bin_: _Bin, images: list, textures: list):
    app = ch.spec.appearance

    def add_image(name, data: bytes) -> int:
        images.append({"bufferView": bin_.view(data), "mimeType": "image/png", "name": name})
        textures.append({"sampler": 0, "source": len(images) - 1, "name": name})
        return len(textures) - 1

    skin_tex = appx.skin_textures()
    t_skin_n = add_image("skin_detail_normal", skin_tex["skin_normal"])
    t_skin_mr = add_image("skin_roughness", skin_tex["skin_mr"])
    t_iris = add_image("iris", appx.iris_texture(app.eye_linear()))
    t_strand = add_image("hair_strands", appx.strand_texture())
    t_card = add_image("hair_cards", appx.strand_texture(alpha_cards=True))
    t_fabric = add_image("fabric_weave", appx.fabric_textures()["fabric_normal"])
    # with highlights the hair color lives in COLOR_0 (hair + streaks), so the factor is neutral
    hair = [1.0, 1.0, 1.0, 1.0] if app.hair_highlight_amount > 0 else list(map(float, app.hair_linear())) + [1.0]
    brow = list(map(float, app.brow_linear())) + [1.0]
    mats = {
        "skin": {"name": "skin", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0,
                 "roughnessFactor": 0.9 + 0.2 * app.skin_roughness, "metallicRoughnessTexture": {"index": t_skin_mr}},
                 "normalTexture": {"index": t_skin_n, "scale": 0.35},
                 "extras": {"forge_shading": "skin", "subsurface_hint": [0.9, 0.35, 0.25]}},
        "eye": {"name": "eye", "pbrMetallicRoughness": {"baseColorTexture": {"index": t_iris}, "metallicFactor": 0.0,
                "roughnessFactor": 0.35}},
        "cornea": {"name": "cornea", "alphaMode": "BLEND", "pbrMetallicRoughness": {
            "baseColorFactor": [1.0, 1.0, 1.0, 0.06], "metallicFactor": 0.0, "roughnessFactor": 0.03}},
        "teeth": {"name": "teeth", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0,
                  "roughnessFactor": 0.35}},
        "brow": {"name": "brow", "alphaMode": "MASK", "alphaCutoff": 0.4, "doubleSided": True,
                 "pbrMetallicRoughness": {"baseColorFactor": brow, "baseColorTexture": {"index": t_card},
                                          "metallicFactor": 0.0, "roughnessFactor": 0.6}},
        "lash": {"name": "lash", "alphaMode": "MASK", "alphaCutoff": 0.4, "doubleSided": True,
                 "pbrMetallicRoughness": {"baseColorFactor": [0.02, 0.015, 0.012, 1.0],
                                          "baseColorTexture": {"index": t_card}, "metallicFactor": 0.0,
                                          "roughnessFactor": 0.5}},
        "hair": {"name": "hair", "doubleSided": True,
                 "pbrMetallicRoughness": {"baseColorFactor": hair, "baseColorTexture": {"index": t_strand},
                                          "metallicFactor": 0.0, "roughnessFactor": 0.45}},
    }
    # generic materials for attached assets built with forge_character_forge.kit (props, armor, weapons)
    mats["kit_metal"] = {"name": "kit_metal", "pbrMetallicRoughness": {"baseColorFactor": [0.56, 0.57, 0.58, 1.0],
                                                                       "metallicFactor": 1.0, "roughnessFactor": 0.35}}
    mats["kit_glass"] = {"name": "kit_glass", "alphaMode": "BLEND", "pbrMetallicRoughness": {
        "baseColorFactor": [1.0, 0.78, 0.35, 0.55], "metallicFactor": 0.0, "roughnessFactor": 0.1},
        "emissiveFactor": [1.0, 0.62, 0.2]}
    mats["kit_leather"] = {"name": "kit_leather", "pbrMetallicRoughness": {"baseColorFactor": [0.24, 0.14, 0.08, 1.0],
                                                                           "metallicFactor": 0.0, "roughnessFactor": 0.7}}
    from forge_character_forge.clothing import COLORS
    for g in COLORS:
        c = ch.spec.garment_color(g)
        mats[f"cloth_{g}"] = {"name": f"cloth_{g}", "doubleSided": True,
                              "normalTexture": {"index": t_fabric, "scale": 0.6},
                              "pbrMetallicRoughness": {"baseColorFactor": list(c) + [1.0], "metallicFactor": 0.0,
                                                       "roughnessFactor": 0.88}}
    return mats


# ---------------------------------------------------------------- export

def character_gltf(ch, clips: list[Clip] = (), extra_meta: dict | None = None) -> tuple[dict, bytes]:
    b = _Bin()
    skel = ch.skeleton
    J = len(skel.names)
    images, textures = [], []
    mats = _materials(ch, b, images, textures)
    used_mats = []
    nodes = []
    # joints first: node index == joint index
    offs = skel.local_offsets()
    for j, name in enumerate(skel.names):
        node = {"name": name, "translation": [float(x) for x in offs[j]]}
        kids = [i for i, p in enumerate(skel.parents) if p == j]
        if kids:
            node["children"] = kids
        ex = {}
        if name in HUMANOID_MAP:
            ex["humanoid"] = HUMANOID_MAP[name]
        if name in PHYSICS_BONES:
            ex["secondary_motion"] = True
        if name.startswith(("genital", "penis", "scrotum", "testicle")):
            ex["dev_only"] = True
        if ex:
            node["extras"] = ex
        nodes.append(node)
    ibm = np.zeros((J, 4, 4), np.float64)
    for j in range(J):
        m = np.eye(4)
        m[:3, 3] = -skel.rest[j]
        ibm[j] = m.T  # column-major storage
    ibm_acc = b.acc(ibm.reshape(J, 16), "MAT4", target=None)
    skin = {"name": "forge_skin", "joints": list(range(J)), "inverseBindMatrices": ibm_acc, "skeleton": 0}
    meshes = []
    mesh_nodes = []
    for part in ch.parts:
        if part.material not in used_mats:
            used_mats.append(part.material)
        verts, normals, tris = part.verts, part.normals, part.tris
        uvs, colors, joints, weights = part.uvs, part.colors, part.joints, part.weights
        morphs = part.morphs
        if part.name == "body":
            src, tris, uvs = part_uv_layout(ch, part)
            verts, normals = verts[src], normals[src]
            colors = colors[src] if colors is not None else None
            joints, weights = joints[src], weights[src]
            morphs = {k: d[src] for k, d in morphs.items()}
        if weights.shape[1] != 4:
            raise ValueError("expected 4 influences")
        w = np.asarray(weights, np.float32).astype(np.float64)
        w /= w.sum(1, keepdims=True)
        attrs = {"POSITION": b.acc(verts, "VEC3", minmax=True),
                 "NORMAL": b.acc(normals, "VEC3"),
                 "JOINTS_0": b.acc(joints, "VEC4", USHORT),
                 "WEIGHTS_0": b.acc(w, "VEC4")}
        if uvs is not None:
            attrs["TEXCOORD_0"] = b.acc(uvs, "VEC2")
        if colors is not None:
            attrs["COLOR_0"] = b.acc(np.clip(colors, 0, 1), "VEC3")
        idx_comp = USHORT if len(verts) < 65535 else UINT
        prim = {"attributes": attrs, "indices": b.acc(tris.reshape(-1), "SCALAR", idx_comp, ELEMENT_ARRAY_BUFFER),
                "material": used_mats.index(part.material), "mode": 4}
        mesh = {"name": part.name, "primitives": [prim]}
        if morphs:
            names = sorted(morphs)
            prim["targets"] = [{"POSITION": b.sparse_vec3(morphs[n])} for n in names]
            mesh["weights"] = [0.0] * len(names)
            mesh["extras"] = {"targetNames": names}
        meshes.append(mesh)
        node = {"name": part.name, "mesh": len(meshes) - 1, "skin": 0}
        ex = dict(part.extras)
        if part.dev_only:
            ex["dev_only"] = True
        if ex:
            node["extras"] = _jsonable(ex)
        nodes.append(node)
        mesh_nodes.append(len(nodes) - 1)
    root_node = {"name": ch.spec.name or "character", "children": [0] + mesh_nodes}
    nodes.append(root_node)
    anims = []
    for c in clips:
        times = b.acc(c.times, "SCALAR", target=None, minmax=True)
        samplers, channels = [], []
        for jn in sorted(c.rotations):
            if jn not in skel.names:
                continue
            q = np.asarray(c.rotations[jn], float)
            q = q / np.linalg.norm(q, axis=1, keepdims=True)
            for i in range(1, len(q)):  # keep hemisphere continuity for clean interpolation
                if np.dot(q[i], q[i - 1]) < 0:
                    q[i] = -q[i]
            samplers.append({"input": times, "output": b.acc(q, "VEC4", target=None), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": skel.index(jn), "path": "rotation"}})
        if c.root_translation is not None and np.any(c.root_translation):
            pel = skel.index("pelvis")
            tr = skel.local_offsets()[pel] + c.root_translation
            samplers.append({"input": times, "output": b.acc(tr, "VEC3", target=None), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": pel, "path": "translation"}})
        anims.append({"name": c.name, "samplers": samplers, "channels": channels})
    from forge_character_forge.character import GENERATOR_ID, GENERATOR_VERSION  # lazy: character imports this module
    meta = {
        "contract": {"id": CONTRACT_ID, "version": CONTRACT_VERSION},
        "profile": ch.profile,
        "units": "meters", "up_axis": "+Y", "front_axis": "+Z", "handedness": "right",
        "joint_rest_orientation": "identity",
        "dev_only_parts": [p.name for p in ch.parts if p.dev_only],
        "coverage": _jsonable(ch.coverage),
        "fixed_topology_vertices": int(len(ch.body.verts)),
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "physics_bones": [n for n in skel.names if n in PHYSICS_BONES],
        "geometry_source": "procedural SDF anatomy (Black Lantern Character Forge); no third-party mesh",
    }
    if extra_meta:
        meta.update(_jsonable(extra_meta))
    gltf = {
        "asset": {"version": "2.0", "generator": "Black Lantern Character Forge (experiment/character-forge-aaa-oneshot)",
                  "extras": {"forge": meta}},
        "scene": 0, "scenes": [{"name": "character", "nodes": [len(nodes) - 1]}],
        "nodes": nodes, "meshes": meshes, "skins": [skin],
        "materials": [mats[m] for m in used_mats],
        "textures": textures, "images": images,
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "accessors": b.accessors, "bufferViews": b.views, "buffers": [{"byteLength": len(b.data)}],
    }
    if anims:
        gltf["animations"] = anims
    # drop textures that no used material references (keeps images minimal)
    return gltf, bytes(b.data)


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


def pack_glb(gltf: dict, bin_data: bytes) -> bytes:
    js = canonical_json(gltf)
    js += b" " * (-len(js) % 4)
    bd = bin_data + b"\0" * (-len(bin_data) % 4)
    total = 12 + 8 + len(js) + 8 + len(bd)
    return b"".join([struct.pack("<III", 0x46546C67, 2, total), struct.pack("<II", len(js), 0x4E4F534A), js,
                     struct.pack("<II", len(bd), 0x004E4942), bd])


def write_glb(ch, path, clips=(), extra_meta=None) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".glb":
        raise ValueError("output must end in .glb")
    if ch.profile == "public" and path.name.endswith(".dev.glb"):
        raise ValueError("public exports must not use the .dev.glb suffix")
    if ch.profile == "developer" and not path.name.endswith(".dev.glb"):
        raise ValueError("developer exports must be named *.dev.glb so they are never mistaken for public assets")
    gltf, data = character_gltf(ch, clips, extra_meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack_glb(gltf, data))
    return path


def pose_check_data(ch, c: Clip, frame: int, count: int = 600) -> dict:
    """Body vertex positions (exported vertex order) for clip frame, computed by the Python pipeline."""
    from forge_character_forge.rig import forward_kinematics, lbs, skinning_matrices

    pose = {j: q[frame] for j, q in c.rotations.items() if j in ch.skeleton.names}
    G = forward_kinematics(ch.skeleton, pose, local_trans={"pelvis": c.root_translation[frame]})
    S = skinning_matrices(ch.skeleton, G)
    body = ch.body
    src, _, _ = part_uv_layout(ch, body)
    v = body.verts[src].astype(np.float32).astype(np.float64)
    w = np.asarray(body.weights[src], np.float32).astype(np.float64)
    w /= w.sum(1, keepdims=True)
    posed = lbs(v, body.joints[src], w, S)
    idx = np.linspace(0, len(v) - 1, count).astype(int)
    return {"clip": c.name, "frame": frame, "indices": idx.tolist(), "positions": posed[idx].tolist(),
            "rest_positions": v[idx].tolist()}
