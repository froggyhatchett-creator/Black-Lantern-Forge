"""Bake the Character Studio pack: base meshes + a linear morph basis per editable parameter.

Every studio parameter p gets one or two exact Python builds (at its studio low and high end).
Because all parts share fixed topologies, each build yields per-vertex deltas for every part and
per-joint deltas for the skeleton.  The browser evaluates

    verts = base + sum_p  w_p * delta_p(side)        (piecewise linear: low side / high side)
    verts += preset_correction                       (exact residual for the chosen preset)

so a single-parameter edit is exact at its endpoints and presets are exact at their defaults.
Exact geometry for any combination comes from exporting the DNA through the Python engine.

Pack format (``studio_pack.bin``, gzip):  b"FORGEPK1" + u32 json_len + json + binary blob.
The JSON manifest gives typed-array (offset, dtype, shape) entries into the blob.
"""

from __future__ import annotations

import gzip
import json
import math
import struct
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import fields
from pathlib import Path

import numpy as np

from forge_character_forge import accessories, clothing, mesher
from forge_character_forge import hair as hair_styles
from forge_character_forge.animation import CLIPS, clip as make_clip
from forge_character_forge.appearance import AppearanceParams, skin_vertex_colors
from forge_character_forge.appearance import hair_highlight_mask as appearance_hair_mask
from forge_character_forge.body import build_body
from forge_character_forge.expressions import expression_morphs
from forge_character_forge.params import BodyParams, FaceParams, preset
from forge_character_forge.skeleton import DEV_BONES, HUMANOID_MAP, PHYSICS_BONES

PACK_MAGIC = b"FORGEPK1"
PACK_VERSION = 1
BASE_APPEARANCE = AppearanceParams(skin_tone=0.3, hair_style="short")

# studio slider ranges (inside the engine's stability ranges); anatomy-detail params are developer-only
BODY_RANGES = {
    "height_m": (1.45, 2.10), "femininity": (0.0, 1.0), "body_fat": (0.0, 1.0), "muscle": (0.0, 1.0),
    "shoulder_width": (0.8, 1.25), "chest_width": (0.8, 1.25), "chest_depth": (0.8, 1.25), "waist_width": (0.8, 1.3),
    "hip_width": (0.8, 1.3), "glute_size": (0.6, 1.6), "belly": (0.0, 1.0), "torso_length": (0.85, 1.2),
    "neck_length": (0.8, 1.3), "neck_thickness": (0.8, 1.3), "arm_length": (0.85, 1.2), "arm_thickness": (0.75, 1.4),
    "leg_length": (0.85, 1.2), "thigh_thickness": (0.75, 1.4), "calf_thickness": (0.75, 1.4), "hand_size": (0.8, 1.25),
    "foot_size": (0.8, 1.25), "head_size": (0.85, 1.25), "breast_size": (0.0, 2.5), "breast_spacing": (0.8, 1.25),
    "breast_height": (0.85, 1.15), "breast_projection": (0.6, 1.6), "breast_sag": (0.0, 1.0),
}
FACE_RANGES = {n: (0.75, 1.3) for n in FaceParams.names()}
FACE_RANGES.update({"nose_upturn": (-1.0, 1.0), "eye_tilt": (-1.0, 1.0), "asymmetry": (0.0, 1.0),
                    "eye_size": (0.8, 1.25), "eye_spacing": (0.85, 1.2)})
GARMENT_SET = ("briefs", "bra", "tshirt", "shorts", "pants", "skirt", "robe", "loincloth")


def base_params() -> tuple[BodyParams, FaceParams]:
    b, f, _ = preset("neutral")
    return b, f


def build_parts(body: BodyParams, face: FaceParams, want_colors: bool = False) -> dict:
    """Public-profile geometry for every studio part (all hair styles and all garments at once)."""
    bm = build_body(body.with_(nipple_size=0.0, areola_size=0.0), face, nipples=False)
    skel, tpl = bm.skeleton, bm.template
    verts = bm.verts
    morphs = expression_morphs(verts, skel, face, tpl.region_of_vertex)
    rest_close = morphs.pop("mouth_close") * 0.9
    verts = verts + rest_close
    normals = mesher.vertex_normals(verts, bm.tris)
    out = {"body": verts}
    if want_colors:
        out["_body_colors"] = skin_vertex_colors(verts, normals, tpl.tags, tpl.tag_names, bm.joints, bm.weights, skel,
                                                 BASE_APPEARANCE, body.with_(nipple_size=0.0, areola_size=0.0))
        expr = expression_morphs(verts, skel, face, tpl.region_of_vertex)
        expr.pop("mouth_close")
        expr["lips_part"] = -rest_close
        out["_expressions"] = expr
    parts = []
    parts += accessories.build_eyes(skel, BASE_APPEARANCE)
    parts += accessories.build_mouth(skel)
    parts += accessories.build_brows_lashes(skel, bm.field, BASE_APPEARANCE, face)
    parts += accessories.build_hair(verts, normals, tpl, skel, tpl.skeleton, AppearanceParams(hair_style="short"), bm.field)
    parts.append(accessories.hair_bun(skel))
    if want_colors:  # head-space styles are placed in the browser from the evaluated head frame; no deltas
        parts += [hair_styles.build_style(skel, s) for s in hair_styles.STYLES]
    parts += clothing.build_garments(GARMENT_SET, verts, normals, tpl, tpl.skeleton, skel, bm.field)
    for p in parts:
        out[p.name] = p.verts
    if want_colors:
        out["_parts"] = parts
    keep = [i for i, n in enumerate(skel.names) if n not in DEV_BONES]
    out["_joints"] = skel.rest[keep]
    out["_skel"] = skel
    out["_body_mesh"] = bm
    return out


def _generator_stamp() -> dict:
    from forge_character_forge.character import GENERATOR_ID, GENERATOR_VERSION
    return {"id": GENERATOR_ID, "version": GENERATOR_VERSION}


def stamp_generator(path, template_vertices: int) -> dict:
    """Record the generator version in an existing pack's manifest (the binary blob is left untouched)."""
    man, blob = read_pack(path)
    man["generator"] = dict(_generator_stamp(), template_vertices=int(template_vertices))
    js = json.dumps(man, separators=(",", ":")).encode()
    Path(path).write_bytes(gzip.compress(PACK_MAGIC + struct.pack("<I", len(js)) + js + blob, compresslevel=9, mtime=0))
    return man["generator"]


def _job(args):
    kind, name, value = args
    b, f = base_params()
    if kind == "body":
        b = b.with_(**{name: value})
    elif kind == "face":
        f = f.with_(**{name: value})
    elif kind == "preset":
        b, f, _ = preset(name)
    d = build_parts(b, f)
    return args, {k: v for k, v in d.items() if not k.startswith("_") or k == "_joints"}


def _jobs():
    b, f = base_params()
    jobs = []
    for group, ranges, obj in (("body", BODY_RANGES, b), ("face", FACE_RANGES, f)):
        for n, (lo, hi) in ranges.items():
            v0 = getattr(obj, n)
            if hi > v0 + 1e-9:
                jobs.append((group, n, float(hi)))
            if lo < v0 - 1e-9:
                jobs.append((group, n, float(lo)))
    jobs += [("preset", "male", 0.0), ("preset", "female", 0.0)]
    return jobs


class _Blob:
    def __init__(self):
        self.buf = bytearray()

    def add(self, arr: np.ndarray) -> dict:
        arr = np.ascontiguousarray(arr)
        self.buf += b"\0" * (-len(self.buf) % 8)
        off = len(self.buf)
        self.buf += arr.tobytes()
        return {"o": off, "t": arr.dtype.str.lstrip("<|"), "s": list(arr.shape)}


def _encode_delta(blob: _Blob, d: np.ndarray, tol: float = 5e-5):
    """Sparse int16 encoding of a (V,3) delta. Returns manifest entry or None when the delta is ~zero."""
    mag = np.abs(d).max(1)
    idx = np.nonzero(mag > tol)[0]
    if not len(idx):
        return None
    scale = float(np.abs(d[idx]).max()) / 32767.0
    q = np.round(d[idx] / scale).astype("<i2")
    dense = len(idx) > 0.6 * len(d)
    if dense:
        full = np.round(d / scale).astype("<i2")
        return {"dense": blob.add(full), "scale": scale}
    return {"idx": blob.add(idx.astype("<u4")), "val": blob.add(q), "scale": scale}


def bake(out_path, workers: int = 4, log=print) -> dict:
    t0 = time.time()
    b, f = base_params()
    log("building base ...")
    base = build_parts(b, f, want_colors=True)
    skel = base["_skel"]
    bm = base["_body_mesh"]
    tpl = bm.template
    part_objs = {p.name: p for p in base["_parts"]}
    part_names = ["body"] + [p.name for p in base["_parts"]]
    jobs = _jobs()
    log(f"baking {len(jobs)} exact builds with {workers} workers ...")
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, (args, res) in enumerate(ex.map(_job, jobs)):
            results[args] = res
            if i % 10 == 0:
                log(f"  {i + 1}/{len(jobs)} ({time.time() - t0:.0f}s)")
    blob = _Blob()
    keep_names = [n for n in skel.names if n not in DEV_BONES]
    parents = []
    for n in keep_names:
        p = skel.parents[skel.index(n)]
        parents.append(keep_names.index(skel.names[p]) if p >= 0 else -1)
    man = {"magic": "FORGEPK1", "version": PACK_VERSION, "units": "meters", "up": "+Y", "front": "+Z",
           "skeleton": {"names": keep_names, "parents": parents, "rest": blob.add(base["_joints"].astype("<f4")),
                        "humanoid": {k: v for k, v in HUMANOID_MAP.items() if k in keep_names},
                        "physics": [n for n in keep_names if n in PHYSICS_BONES], "marks": {
                            k: (float(v) if np.isscalar(v) else [float(x) for x in v])
                            for k, v in skel.marks.items() if np.isscalar(v) or (hasattr(v, "__len__") and len(v) == 3)}},
           "parts": {}, "params": {}, "presets": {}, "clips": {}, "expressions": [],
           "generator": _generator_stamp()}
    remap = np.full(len(skel.names), 0, np.int64)
    for i, n in enumerate(keep_names):
        remap[skel.index(n)] = i
    unstable = []
    for name in part_names:
        if name == "body":
            v, t, j, w = base["body"], bm.tris, bm.joints, bm.weights
            mat, ds, colors = "skin", False, base["_body_colors"] / np.asarray(BASE_APPEARANCE.skin_linear())
            uv = None
        else:
            p = part_objs[name]
            v, t, j, w, mat, ds = p.verts, p.tris, p.joints, p.weights, p.material, p.double_sided
            colors = p.colors
            uv = p.uvs
        head_space = name != "body" and part_objs[name].extras.get("head_space")
        if head_space:
            v = hair_styles.unit_mesh(part_objs[name].extras["style"])[0]
        wq = np.round(np.asarray(w) * 255).astype(np.int32)
        wq[:, 0] += 255 - wq.sum(1)
        entry = {"material": mat, "double_sided": bool(ds), "n": int(len(v)),
                 "pos": blob.add(np.asarray(v, "<f4")), "idx": blob.add(np.asarray(t, "<u4")),
                 "joints": blob.add(remap[np.asarray(j)].astype("u1")), "weights": blob.add(wq.astype("u1"))}
        if head_space:
            entry["frame"] = "head"  # pos is in unit head space: world = O + pos * k (studio.js headFrame)
        if mat == "hair":
            from forge_character_forge.anatomy import head_frame
            O_, h_ = head_frame(skel)
            unit = v if head_space else (np.asarray(v) - O_) / (h_ / 0.23)
            entry["highlight"] = blob.add(np.round(appearance_hair_mask(unit) * 255).astype("u1"))
        if colors is not None:
            entry["color"] = blob.add(np.clip(np.asarray(colors) * 0.5 * 255, 0, 255).astype("u1"))  # x2 headroom
        if uv is not None:
            entry["uv"] = blob.add(np.asarray(uv, "<f4"))
        man["parts"][name] = entry
    # expressions (body only)
    for ename, d in sorted(base["_expressions"].items()):
        enc = _encode_delta(blob, d)
        if enc:
            man["expressions"].append({"name": ename, "body": enc})
    # parameter basis
    defaults = {"body": b, "face": f}
    for group, ranges in (("body", BODY_RANGES), ("face", FACE_RANGES)):
        for n, (lo, hi) in ranges.items():
            v0 = float(getattr(defaults[group], n))
            pe = {"group": group, "default": v0, "min": lo, "max": hi, "sides": {}}
            for side, val in (("hi", hi), ("lo", lo)):
                key = (group, n, float(val))
                if key not in results:
                    continue
                r = results[key]
                side_e = {"at": float(val), "parts": {}, "joints": None}
                for pn in part_names:
                    if pn in r and r[pn].shape == base[pn].shape and not man["parts"][pn].get("rigid"):
                        enc = _encode_delta(blob, r[pn] - base[pn])
                        if enc:
                            side_e["parts"][pn] = enc
                    elif pn in r and r[pn].shape != base[pn].shape:
                        unstable.append((n, pn))
                side_e["joints"] = blob.add((r["_joints"] - base["_joints"]).astype("<f4"))
                pe["sides"][side] = side_e
            man["params"][f"{group}.{n}"] = pe
    # preset corrections: exact preset minus base minus the linear model's prediction
    for pname in ("male", "female"):
        pb, pf, _ = preset(pname)
        r = results[("preset", pname, 0.0)]
        values = {}
        pred = {pn: np.zeros_like(base[pn]) for pn in part_names}
        pred_j = np.zeros_like(base["_joints"])
        for key, pe in man["params"].items():
            g, n = key.split(".", 1)
            val = float(getattr(pb if g == "body" else pf, n))
            values[key] = val
            dv = val - pe["default"]
            side = "hi" if dv > 0 else "lo"
            if abs(dv) < 1e-9 or side not in pe["sides"]:
                continue
            se = pe["sides"][side]
            t_ = dv / (se["at"] - pe["default"])
            for pn in part_names:
                if pn in se["parts"]:
                    pred[pn] += t_ * _decode(blob, se["parts"][pn], len(base[pn]))
            pred_j += t_ * np.frombuffer(bytes(blob.buf[se["joints"]["o"]:se["joints"]["o"] + pred_j.size * 4]),
                                         "<f4").reshape(pred_j.shape)
        corr = {}
        for pn in part_names:
            if pn in r and r[pn].shape == base[pn].shape and not man["parts"][pn].get("rigid"):
                enc = _encode_delta(blob, r[pn] - base[pn] - pred[pn])
                if enc:
                    corr[pn] = enc
        man["presets"][pname] = {"values": values, "parts": corr,
                                 "joints": blob.add((r["_joints"] - base["_joints"] - pred_j).astype("<f4"))}
    man["presets"]["neutral"] = {"values": {k: pe["default"] for k, pe in man["params"].items()}, "parts": {}, "joints": None}
    # animation clips (joint-local quaternions; root translation per unit height)
    for cname in CLIPS:
        c = make_clip(cname, 1.0)
        rot = {jn: blob.add(np.asarray(q, "<f4")) for jn, q in c.rotations.items() if jn in keep_names}
        man["clips"][cname] = {"frames": int(len(c.times)), "fps": 30, "loop": bool(c.loop), "rot": rot,
                               "root": blob.add(np.asarray(c.root_translation, "<f4"))}
    man["unstable_topology"] = sorted(set(f"{a}:{b}" for a, b in unstable))
    man["bake_seconds"] = round(time.time() - t0, 1)
    js = json.dumps(man, separators=(",", ":")).encode()
    raw = PACK_MAGIC + struct.pack("<I", len(js)) + js + bytes(blob.buf)
    data = gzip.compress(raw, compresslevel=9, mtime=0)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    log(f"wrote {out_path} ({len(data) / 1e6:.1f} MB gz, {len(raw) / 1e6:.1f} MB raw) in {time.time() - t0:.0f}s")
    return man


def _decode(blob: _Blob, enc: dict, n: int) -> np.ndarray:
    def arr(e):
        cnt = int(np.prod(e["s"]))
        return np.frombuffer(bytes(blob.buf[e["o"]:e["o"] + cnt * np.dtype(e["t"]).itemsize]), e["t"]).reshape(e["s"])
    out = np.zeros((n, 3))
    if "dense" in enc:
        out[:] = arr(enc["dense"]) * enc["scale"]
    else:
        out[arr(enc["idx"])] = arr(enc["val"]) * enc["scale"]
    return out


def read_pack(path) -> tuple[dict, bytes]:
    raw = gzip.decompress(Path(path).read_bytes())
    if raw[:8] != PACK_MAGIC:
        raise ValueError("not a Character Forge studio pack")
    n = struct.unpack("<I", raw[8:12])[0]
    return json.loads(raw[12:12 + n]), raw[12 + n:]


def studio_meta() -> dict:
    """Static data the studio needs to emit valid Character DNA and match engine colors."""
    from forge_character_forge.appearance import EYE_COLORS, HAIR_STYLES, _SKIN_SRGB
    from forge_character_forge.clothing import COLORS, COVERS, GARMENTS
    from forge_character_forge.dna import DNA_SCHEMA, DNA_VERSION
    from forge_character_forge.params import GenitalParams
    b, f = base_params()
    presets = {}
    for name in ("male", "female", "neutral"):
        pb, pf, pg = preset(name)
        presets[name] = {"body": pb.to_dict(), "face": pf.to_dict(), "genital": pg.to_dict()}
    return {
        "dna": {"schema": DNA_SCHEMA, "version": DNA_VERSION},
        "defaults": {"body": b.to_dict(), "face": f.to_dict(), "genital": GenitalParams().to_dict(),
                     "appearance": AppearanceParams().to_dict()},
        "presets": presets,
        "skin_srgb": [list(c) for c in _SKIN_SRGB],
        "eye_colors": {k: list(v) for k, v in EYE_COLORS.items()},
        "hair_styles": list(HAIR_STYLES),
        "garments": list(GARMENTS), "garment_colors": {k: list(v) for k, v in COLORS.items()},
        "covers": {k: sorted(v) for k, v in COVERS.items()},
        "base_skin_tone": BASE_APPEARANCE.skin_tone,
        "studio_ranges": {**{f"body.{k}": v for k, v in BODY_RANGES.items()}, **{f"face.{k}": v for k, v in FACE_RANGES.items()}},
    }


def _planes(a: np.ndarray) -> bytes:
    b = np.frombuffer(np.ascontiguousarray(a).tobytes(), "u1").reshape(-1, a.dtype.itemsize)
    return b.T.copy().tobytes()


def compact_pack(src, dst=None) -> dict:
    """Re-encode a pack for size: int16 deltas -> first differences along the vertex axis (wrapping int16),
    uint32 sparse indices and triangle lists -> differences; all stored as byte planes. Exactly reversible."""
    man, blob = read_pack(src)
    out = _Blob()

    def arr(e):
        cnt = int(np.prod(e["s"]))
        return np.frombuffer(blob[e["o"]:e["o"] + cnt * np.dtype(e["t"]).itemsize], e["t"]).reshape(e["s"])

    def walk(o, key=None):
        if isinstance(o, dict):
            if {"o", "t", "s"} <= set(o):
                a = arr(o)
                if o["t"] == "i2":
                    d = np.diff(a.astype(np.int32), axis=0, prepend=0).astype("<i2")
                    e = out.add(np.frombuffer(_planes(d), "u1"))
                    return {"o": e["o"], "t": "i2", "s": o["s"], "enc": "d1p"}
                if o["t"] == "u4":  # sparse indices (ascending) and triangle lists (neighbouring rows are close)
                    d = np.diff(a.astype(np.int64), axis=0, prepend=0).astype("<u4")
                    e = out.add(np.frombuffer(_planes(d), "u1"))
                    return {"o": e["o"], "t": "u4", "s": o["s"], "enc": "d1p"}
                e = out.add(np.ascontiguousarray(a))
                return {"o": e["o"], "t": o["t"], "s": o["s"]}
            res = {}
            for k, v in o.items():
                kk = "idx_sparse" if (k == "idx" and isinstance(v, dict) and "val" in o) else k
                res[k] = walk(v, kk)
            return res
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    man2 = walk(man)
    man2["encoding"] = "d1p"
    js = json.dumps(man2, separators=(",", ":")).encode()
    raw = PACK_MAGIC + struct.pack("<I", len(js)) + js + bytes(out.buf)
    data = gzip.compress(raw, compresslevel=9, mtime=0)
    Path(dst or src).write_bytes(data)
    return {"bytes": len(data), "raw": len(raw)}


def refresh_hair(src, dst) -> dict:
    """Swap an existing (uncompacted) pack's hair to the current head-space styles without re-baking
    (and re-write the animation clips, which never depend on the parameter basis).

    Head-space parts carry no parameter deltas, so only their base entries change: the old ``hair_long``
    curtain (with its deltas) is dropped, the volumetric styles are added, and every hair part gets a
    highlight mask.  The result is identical to what ``bake`` now writes for those parts."""
    from forge_character_forge.anatomy import head_frame
    from forge_character_forge.skeleton import build_skeleton
    man, blob = read_pack(src)
    if man.get("encoding"):
        raise ValueError("refresh_hair needs the uncompacted pack")
    out = _Blob()
    drop = {"hair_long", *[f"hair_{s}" for s in hair_styles.STYLES]}

    def copy(o):
        if isinstance(o, dict):
            if {"o", "t", "s"} <= set(o):
                cnt = int(np.prod(o["s"])) * np.dtype(o["t"]).itemsize
                return out.add(np.frombuffer(blob[o["o"]:o["o"] + cnt], "u1")) | {"t": o["t"], "s": o["s"]}
            return {k: copy(v) for k, v in o.items() if k not in drop}
        if isinstance(o, list):
            return [copy(v) for v in o]
        return o

    man = copy(man)
    b, f = base_params()
    skel = build_skeleton(b, f)
    O, h = head_frame(skel)
    k = h / 0.23
    names = man["skeleton"]["names"]
    for pn in ("hair_cap", "hair_bun"):
        e = man["parts"][pn]
        cnt = int(np.prod(e["pos"]["s"]))
        pos = np.frombuffer(bytes(out.buf[e["pos"]["o"]:e["pos"]["o"] + cnt * 4]), "<f4").reshape(-1, 3)
        e["highlight"] = out.add(np.round(appearance_hair_mask((pos - O) / k) * 255).astype("u1"))
    for style in hair_styles.STYLES:
        v, t = hair_styles.unit_mesh(style)
        J, W = hair_styles.hair_weights(skel, v, style)
        Jk = np.array([[names.index(skel.names[j]) for j in row] for row in J], "u1")
        wq = np.round(W * 255).astype(np.int32)
        wq[:, 0] += 255 - wq.sum(1)
        man["parts"][f"hair_{style}"] = {
            "material": "hair", "double_sided": True, "n": int(len(v)), "frame": "head",
            "pos": out.add(np.asarray(v, "<f4")), "idx": out.add(np.asarray(t, "<u4")),
            "joints": out.add(Jk), "weights": out.add(wq.astype("u1")),
            "uv": out.add(np.asarray(hair_styles._uv(v), "<f4")),
            "highlight": out.add(np.round(appearance_hair_mask(v) * 255).astype("u1"))}
    man["clips"] = {}
    for cname in CLIPS:
        c = make_clip(cname, 1.0)
        man["clips"][cname] = {"frames": int(len(c.times)), "fps": 30, "loop": bool(c.loop),
                               "rot": {jn: out.add(np.asarray(q, "<f4")) for jn, q in c.rotations.items() if jn in names},
                               "root": out.add(np.asarray(c.root_translation, "<f4"))}
    js = json.dumps(man, separators=(",", ":")).encode()
    raw = PACK_MAGIC + struct.pack("<I", len(js)) + js + bytes(out.buf)
    Path(dst).write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    return {"parts": list(man["parts"]), "clips": list(man["clips"])}


def pack_array(entry: dict, blob: bytes) -> np.ndarray:
    """Decode one typed-array entry of a (possibly compacted) pack — the Python twin of studio.js ``arr``."""
    cnt = int(np.prod(entry["s"]))
    size = np.dtype(entry["t"]).itemsize
    raw = np.frombuffer(blob[entry["o"]:entry["o"] + cnt * size], "u1")
    if entry.get("enc") == "d1p":
        raw = raw.reshape(size, cnt).T.copy()
        a = np.frombuffer(raw.tobytes(), entry["t"]).reshape(entry["s"])
        wrapped = np.cumsum(a.astype(np.int64), axis=0) % (1 << (8 * size))  # same wrap as the typed-array store
        return wrapped.astype(np.uint32 if size == 4 else np.uint16).view(np.dtype(entry["t"]))
    return np.frombuffer(raw.tobytes(), entry["t"]).reshape(entry["s"])


def pack_text_chunks(src, out_dir, chunk_bytes: int = 9_000_000) -> list[str]:
    """Base64 text chunks of a pack (``studio_pack.N.txt`` + ``studio_pack.parts.json``) for static hosts that
    serve only text/web types.  studio.js falls back to these when ``studio_pack.bin`` is unavailable."""
    import base64
    data = Path(src).read_bytes()
    out_dir = Path(out_dir)
    step = chunk_bytes // 4 * 3  # whole base64 quanta per chunk
    names = []
    for i in range(0, len(data), step):
        name = f"studio_pack.{len(names)}.txt"
        (out_dir / name).write_text(base64.b64encode(data[i:i + step]).decode("ascii"))
        names.append(name)
    (out_dir / "studio_pack.parts.json").write_text(json.dumps({"bytes": len(data), "parts": names}))
    return names
