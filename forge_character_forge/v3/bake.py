"""Write the generator v3 studio pack (``studio_pack_v3.bin``) and meta (``studio_meta_v3.json``).

Same container format as v2 (``FORGEPK1``, see studio_bake), so the studio, the GLB exporter and ``pack_array`` read
it unchanged. No SDF bake: MakeHuman targets are already linear deltas, so each control side is evaluated directly
(seconds, not minutes). Presets carry no residual: the v3 model is linear in its controls except height (a uniform
scale), whose cross terms with other controls are not modelled (reported).
"""

from __future__ import annotations

import gzip
import json
import struct
import time
from pathlib import Path

import numpy as np

from forge_character_forge.animation import CLIPS, clip as make_clip
from forge_character_forge.params import preset
from forge_character_forge.skeleton import HUMANOID_MAP
from forge_character_forge.studio_bake import (BODY_RANGES, FACE_RANGES, PACK_MAGIC, PACK_VERSION, _Blob, _encode_delta,
                                               base_params, compact_pack)
from forge_character_forge.v3 import GENERATOR, controls, garments, mh, model, rig

IRIS_RADIUS_M = 0.006  # anatomical iris radius; with the fitted eyeball radius it gives the shader's iris angle


def _weights_u1(w):
    wq = np.round(np.asarray(w) * 255).astype(np.int32)
    wq[:, 0] += 255 - wq.sum(1)
    return wq.astype("u1")


def _marks(v, j) -> dict:
    J = {n: j[k] for k, n in enumerate(rig.NAMES)}
    joints, _, _ = rig.skin(len(v))
    body = model.body_vertex_ids()
    jaw = body[(joints[body, 0] == rig.NAMES.index("jaw")) & (np.abs(v[body, 0]) < 0.006)]
    y_chin = float(v[jaw, 1].min())
    y_crown = float(v[body, 1].max())
    bones, _ = mh.skeleton()
    jp = mh.joint_positions(v)
    ev = mh.fit_eyes(v)
    _, r_eye = model.sphere_fit(ev[model.eye_parts()["eye_l"][0]])
    return {"scale": model.HEIGHT_M, "height": y_crown, "y_hip": float(J["thigh_l"][1]), "y_knee": float(J["calf_l"][1]),
            "y_ankle": float(J["foot_l"][1]), "y_neck_base": float(J["neck_01"][1]), "y_chin": y_chin, "y_crown": y_crown,
            "head_h": y_crown - y_chin, "head_z": float(J["head"][2]), "eye_r": r_eye,
            "nipple_l": [float(x) for x in jp[bones["breast.L"]["tail"]]], "nipple_r": [float(x) for x in jp[bones["breast.R"]["tail"]]]}


def part_arrays():
    """Rest geometry and skinning for every v3 part (body split at UV seams, eyes, corneas, garments)."""
    v = model.neutral()
    joints, weights, skin_report = rig.skin(len(v))
    src, uv, tris, weld = model.body_surface()
    parts = {"body": {"src": src, "pos": v[src], "tris": tris, "joints": joints[src], "weights": weights[src],
                      "material": "skin", "uv": uv, "weld": weld}}
    ev = mh.fit_eyes(v)
    for name, (ids, t) in model.eye_parts().items():
        s = name[-1]
        n = len(ids)
        jj = np.zeros((n, 4), np.int64)
        jj[:, 0] = rig.NAMES.index(f"eye_{s}")
        ww = np.zeros((n, 4))
        ww[:, 0] = 1
        parts[name] = {"eye_ids": ids, "pos": ev[ids], "tris": t, "joints": jj, "weights": ww,
                       "material": "eye" if name.startswith("eye") else "cornea", "double_sided": name.startswith("cornea")}
    for name, (ci, cw, t, off) in garments.shells().items():
        gj, gw = _blend_skin(joints, weights, ci, cw)
        parts[name] = {"comb": (ci, cw), "pos": (v[ci] * cw[:, :, None]).sum(1) + off, "tris": t, "joints": gj,
                       "weights": gw, "material": f"cloth_{name}", "double_sided": True}
    return parts, skin_report


def _blend_skin(joints, weights, ci, cw):
    """Skin of interpolated garment vertices: blended joint weights, top four, renormalised."""
    acc = np.zeros((len(ci), joints.max() + 1))
    for c in range(ci.shape[1]):
        for k in range(4):
            np.add.at(acc, (np.arange(len(ci)), joints[ci[:, c], k]), weights[ci[:, c], k] * cw[:, c])
    order = np.argsort(-acc, 1)[:, :4]
    w = np.take_along_axis(acc, order, 1)
    return order, w / w.sum(1, keepdims=True)


def _part_delta(p, d_full, eye_delta):
    if "eye_ids" in p:
        return eye_delta[p["eye_ids"]]
    if "comb" in p:
        ci, cw = p["comb"]
        return (d_full[ci] * cw[:, :, None]).sum(1)
    return d_full[p["src"]]


def bake(out_path, log=print) -> dict:
    t0 = time.time()
    v = model.neutral()
    parts, skin_report = part_arrays()
    blob = _Blob()
    j0 = rig.joint_rest(v)
    man = {"magic": "FORGEPK1", "version": PACK_VERSION, "units": "meters", "up": "+Y", "front": "+Z",
           "skeleton": {"names": rig.NAMES, "parents": rig.PARENTS, "rest": blob.add(j0.astype("<f4")),
                        "humanoid": {k: v_ for k, v_ in HUMANOID_MAP.items() if k in rig.NAMES},
                        "physics": ["breast_l", "breast_r"], "marks": _marks(v, j0)},
           "parts": {}, "params": {}, "presets": {}, "clips": {}, "expressions": [], "generator": GENERATOR,
           "foundation": {"name": "MakeHuman hm08", "license": "CC0 1.0", "provenance": "forge_character_forge/v3/assets/PROVENANCE.json"}}
    eyes0 = mh.fit_eyes(v)
    for name, p in parts.items():
        entry = {"material": p["material"], "double_sided": bool(p.get("double_sided", False)), "n": int(len(p["pos"])),
                 "pos": blob.add(np.asarray(p["pos"], "<f4")), "idx": blob.add(np.asarray(p["tris"], "<u4")),
                 "joints": blob.add(np.asarray(p["joints"]).astype("u1")), "weights": blob.add(_weights_u1(p["weights"]))}
        if "uv" in p:
            entry["uv"] = blob.add(np.asarray(p["uv"], "<f4"))
        if "weld" in p:
            entry["weld"] = blob.add(np.asarray(p["weld"], "<u4"))  # normals are averaged over seam copies
        if p["material"] in ("eye", "cornea"):
            c, r = model.sphere_fit(np.asarray(p["pos"]))
            entry["sphere"] = True  # eyeball centre = sphere fit (the shells are open at the back)
            entry["iris_angle"] = float(np.arcsin(min(IRIS_RADIUS_M / r, 0.9)))
        man["parts"][name] = entry
    # expressions: the corrected blink
    for s in "lr":
        d = model.blink_delta(v, s)
        enc = _encode_delta(blob, d[parts["body"]["src"]])
        man["expressions"].append({"name": f"blink_{s}", "body": enc})
    # control basis
    b, f = base_params()
    defaults = {"body": b, "face": f}
    for group, ranges in (("body", BODY_RANGES), ("face", FACE_RANGES)):
        for n in ranges:
            key = f"{group}.{n}"
            quality, _, _, note = controls.CONTROLS[key]
            lo_, hi_ = ranges[n]
            pe = {"group": group, "default": float(getattr(defaults[group], n)), "min": lo_, "max": hi_, "sides": {},
                  "quality": quality, "note": note}
            for side in ("hi", "lo"):
                r = model.control_delta(key, side)
                if r is None or abs(r[1] - pe["default"]) < 1e-9:
                    continue
                d, at = r
                ed = mh.fit_eyes(v + d) - eyes0
                se = {"at": float(at), "parts": {}, "joints": blob.add((rig.joint_rest(v + d) - j0).astype("<f4"))}
                for name, p in parts.items():
                    enc = _encode_delta(blob, _part_delta(p, d, ed))
                    if enc:
                        se["parts"][name] = enc
                pe["sides"][side] = se
            if quality == "direct" and controls.CONTROLS[key][1] == "scale":
                pe["mode"] = "uniform_scale"  # the studio scales the evaluated character to exactly this height
            man["params"][key] = pe
    for pname in ("male", "female", "neutral"):
        pb, pf, _ = preset(pname)
        man["presets"][pname] = {"values": {k: float(getattr(pb if k.startswith("body.") else pf, k.split(".")[1]))
                                            for k in man["params"]}, "parts": {}, "joints": None}
    for cname in CLIPS:
        c = make_clip(cname, 1.0)
        rot = {jn: blob.add(np.asarray(q, "<f4")) for jn, q in c.rotations.items() if jn in rig.NAMES}
        man["clips"][cname] = {"frames": int(len(c.times)), "fps": 30, "loop": bool(c.loop), "rot": rot,
                               "root": blob.add(np.asarray(c.root_translation, "<f4"))}
    man["rig"] = {**rig.merge_report(), "skin": skin_report, "renderer_joint_limit": 80, "export_joint_limit": 64}
    man["controls"] = controls.summary()
    man["unstable_topology"] = []
    man["bake_seconds"] = round(time.time() - t0, 1)
    js = json.dumps(man, separators=(",", ":")).encode()
    raw = PACK_MAGIC + struct.pack("<I", len(js)) + js + bytes(blob.buf)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    compact_pack(out_path)
    log(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.2f} MB) in {time.time() - t0:.0f}s")
    return man


def studio_meta_v3() -> dict:
    """Studio meta for v3: v2's DNA schema and defaults, v3 garments and coverage, no hair styles yet."""
    from forge_character_forge.studio_bake import studio_meta
    m = studio_meta()
    m.update({"generator": GENERATOR, "hair_styles": [], "garments": list(garments.GARMENTS),
              "garment_colors": {k: list(c) for k, c in garments.COLORS.items()}, "covers": garments.COVERS,
              "coverage_defaults": garments.COVERAGE_DEFAULTS, "breast_support": {"basic_top": 1.15},
              "controls": {k: {"quality": q, "note": note} for k, (q, _, _, note) in controls.CONTROLS.items()},
              "preset_styling": {"male": {"outfit": ["basic_top", "basic_shorts"], "skin_tone": 0.45},
                                 "female": {"outfit": ["basic_top", "basic_shorts"], "skin_tone": 0.3}}})
    return m
