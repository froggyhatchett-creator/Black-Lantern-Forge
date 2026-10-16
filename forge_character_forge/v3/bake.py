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
from forge_character_forge.v3 import GENERATOR, controls, garments, grooming, identity, identity_dna, mh, model, rig, textures

BLINK_RESHAPE_M = 0.0003  # a control side whose lid-region shape changes by more than this gets a blink corrective


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
                       "material": "eye" if name.startswith("eye") else "cornea", "double_sided": name.startswith("cornea"),
                       "uv": mh.eye_uvs()[ids]}
    for name, (ci, cw, t, off) in garments.shells().items():
        gj, gw = _blend_skin(joints, weights, ci, cw)
        parts[name] = {"comb": (ci, cw), "pos": (v[ci] * cw[:, :, None]).sum(1) + off, "tris": t, "joints": gj,
                       "weights": gw, "material": f"cloth_{name}", "double_sided": True}
    for name, g in grooming.parts().items():
        parts[name] = {"pos": g["pos"], "tris": g["tris"], "joints": g["joints"], "weights": g["weights"], "uv": g["uv"],
                       "material": f"strand_{g['kind']}", "double_sided": True, "anchor": g["anchor"],
                       "strand_points": g["points"], "color": g.get("color")}
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
        if p.get("anchor") is not None:  # re-evaluated from the live body in the studio (v3/grooming.py)
            A = p["anchor"]
            entry["anchor"] = {"mode": A["mode"], "root": blob.add(np.asarray(A["root"], "<u4")),
                               "tri": blob.add(np.asarray(A["tri"], "<u4")), "bary": blob.add(np.asarray(A["bary"], "<f4")),
                               "off": blob.add(np.asarray(A["off"], "<f4"))}
            if A["mode"] == "cage":  # per strand point (both ribbon vertices share it)
                entry["anchor"]["cage_idx"] = blob.add(np.asarray(A["cage_idx"], "<u4"))
                entry["anchor"]["cage_w"] = blob.add(np.round(np.asarray(A["cage_w"]) * 65535).astype("<u2"))
            entry["strand_points"] = int(p["strand_points"])
            if name == "lashes":  # lash contact (v3/lash_contact.py): the studio bends lashes on the lid skin
                from forge_character_forge.v3 import lash_contact as LC
                entry["contact"] = {**{f"tris_{s}_{'up' if up else 'lo'}": blob.add(np.asarray(t, "<u4")) for (s, up), t in LC.lid_tris().items()},
                                    "clear": LC.CLEAR, "max_depth": LC.MAX_DEPTH, "path_ts": list(LC.PATH_TS),
                                    "max_path_step": LC.MAX_PATH_STEP, "max_bend": LC.MAX_BEND, "max_bend_own": LC.MAX_BEND_OWN,
                                    "bend_ratio": LC.BEND_RATIO, "first_point": LC.FIRST_POINT}
        if p.get("color") is not None:
            entry["color"] = blob.add(np.clip(np.asarray(p["color"]) * 0.5 * 255, 0, 255).astype("u1"))  # x2 headroom
        if name == "body":
            entry["textures"] = {"albedo": "skin_albedo", "normal": "skin_normal", "albedo_mean": textures.ALBEDO_MEAN}
        elif p["material"] == "eye":
            entry["textures"] = {"albedo": "eye"}
            entry["iris"] = textures.eye_iris_stats(np.asarray(p["uv"]), np.asarray(p["pos"]))
            entry["iris_angle"] = entry["iris"]["angle"]  # the texture's iris, not a nominal radius
        elif p["material"].startswith("strand_"):
            entry["textures"] = {"albedo": "strand_hair" if name.startswith("hair_") else "strand_single"}
        if "weld" in p:
            entry["weld"] = blob.add(np.asarray(p["weld"], "<u4"))  # normals are averaged over seam copies
        if p["material"] in ("eye", "cornea"):
            entry["sphere"] = True  # eyeball centre = sphere fit (the shells are open at the back)
            if p["material"] == "cornea":  # the cornea's clear cap matches its eye's (texture) iris
                entry["iris_angle"] = man["parts"][f"eye_{name[-1]}"]["iris_angle"]
        man["parts"][name] = entry
    man["textures"] = {k: blob.add(np.frombuffer(b, "u1")) for k, b in textures.png_bytes().items()}
    # expressions: the blink (model 2, v3/model.blink_closed) of the neutral; correctives from v3/evaluate.py
    from forge_character_forge.v3 import evaluate
    bsrc = parts["body"]["src"]
    blink0, fit0 = evaluate.blink0()
    for s in "lr":
        man["expressions"].append({"name": f"blink_{s}", "body": _encode_delta(blob, blink0[s][bsrc])})
    blink_fits = {"neutral": fit0}
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
                    if p.get("anchor") is not None:
                        continue
                    enc = _encode_delta(blob, _part_delta(p, d, ed))
                    if enc:
                        se["parts"][name] = enc
                # blink corrective: where a control reshapes the lids, the blink is refitted at this end and the
                # difference is stored; the studio adds it scaled by (blink weight x control weight)
                if controls.CONTROLS[key][1] != "scale":  # height: post-scale
                    corr, fit = evaluate.control_corrective(key, side)
                    for s in "lr":
                        if corr[s] is not None:
                            blink_fits[f"{key}:{side}"] = fit
                            enc = _encode_delta(blob, corr[s][bsrc])
                            if enc:
                                se.setdefault("expr", {})[f"blink_{s}"] = enc
                pe["sides"][side] = se
            if quality == "direct" and controls.CONTROLS[key][1] == "scale":
                pe["mode"] = "uniform_scale"  # the studio scales the evaluated character to exactly this height
            man["params"][key] = pe
    man["identity"] = _identity_pack(blob, parts, v, j0, eyes0, log)
    for pname in ("male", "female", "neutral"):
        pb, pf, _ = preset(pname)
        man["presets"][pname] = {"values": {k: float(getattr(pb if k.startswith("body.") else pf, k.split(".")[1]))
                                            for k in man["params"]}, "parts": {}, "joints": None}
    for cname in CLIPS:
        c = make_clip(cname, 1.0)
        rot = {jn: blob.add(np.asarray(q, "<f4")) for jn, q in c.rotations.items() if jn in rig.NAMES}
        man["clips"][cname] = {"frames": int(len(c.times)), "fps": 30, "loop": bool(c.loop), "rot": rot,
                               "root": blob.add(np.asarray(c.root_translation, "<f4"))}
    man["blink_fits"] = blink_fits
    man["blink_model"] = model.BLINK_MODEL
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


IDENTITY_GROUPS = [
    ("Skull & forehead", ["skull_length", "skull_width", "forehead_height", "forehead_slope"]),
    ("Brow & eyes", ["brow_ridge", "eye_depth", "eye_spacing", "eye_size", "eye_tilt", "eye_height", "eye_aperture",
                     "eye_outer_corner", "eye_length"]),
    ("Nose", ["nose_length", "nose_width", "nose_projection", "nose_bridge", "nose_tip_size", "nose_tip_angle"]),
    ("Cheeks", ["cheekbone_width", "cheekbone_height", "cheek_fullness", "midface_projection"]),
    ("Mouth & lips", ["mouth_width", "mouth_height", "upper_lip", "lower_lip", "lip_projection"]),
    ("Jaw & chin", ["jaw_width", "jaw_angle", "jaw_taper", "chin_width", "chin_height", "chin_projection"]),
    ("Overall", ["face_length", "face_width"]),
]


def _identity_pack(blob, parts, v, j0, eyes0, log=print) -> dict:
    """Identity basis for the studio (Phase 3D): per parameter the delta at s = +1 for every part (s = -1 is its
    negative: identity is exactly linear), the joint delta, and blink correctives at both ends (the blink refitted at
    s = +1 and s = -1; the studio scales the one on the side of s by |s|). Each preset also carries a blink residual
    (exact blink fit at the preset minus the summed correctives), faded by ``identity_dna.preset_affinity``."""
    from forge_character_forge.v3 import evaluate
    assert tuple(identity.KEYS) == identity_dna.KEYS_V1
    bsrc = parts["body"]["src"]
    labels = {p.key: p.label for p in identity.PARAMS}
    assert sorted(k for _, ks in IDENTITY_GROUPS for k in ks) == sorted(identity.KEYS)
    out = {"schema": identity_dna.SCHEMA, "version": identity_dna.VERSION, "keys": list(identity.KEYS),
           "labels": labels, "groups": IDENTITY_GROUPS, "range": list(identity_dna.RANGE), "params": {}, "presets": {},
           "fingerprints": identity_dna.recorded()["sha256"]}
    for key in identity.KEYS:
        d = identity.basis(key)
        ed = mh.fit_eyes(v + d) - eyes0
        pe = {"parts": {}, "joints": blob.add((rig.joint_rest(v + d) - j0).astype("<f4")), "expr": {}}
        for name, p in parts.items():
            if p.get("anchor") is not None:
                continue
            enc = _encode_delta(blob, _part_delta(p, d, ed))
            if enc:
                pe["parts"][name] = enc
        for sign, side in ((1, "hi"), (-1, "lo")):
            corr, _ = evaluate.identity_corrective(key, sign)
            for s in "lr":
                if corr[s] is not None:
                    enc = _encode_delta(blob, corr[s][bsrc])
                    if enc:
                        pe["expr"].setdefault(side, {})[f"blink_{s}"] = enc
        out["params"][key] = pe
    res = evaluate.preset_residuals()
    for name, pr in identity_dna.presets().items():
        entry = {"label": identity_dna.PRESET_LABELS.get(name, name), "values": {k: float(x) for k, x in pr["values"].items()},
                 "controls": pr["controls"]}
        if name in res:
            entry["blink_fit"] = res[name]["fit"]
            entry["residual"] = {}
            for s in "lr":
                enc = _encode_delta(blob, res[name][s][bsrc])
                if enc:
                    entry["residual"][f"blink_{s}"] = enc
        out["presets"][name] = entry
        log(f"identity preset {name}: {entry.get('blink_fit')}")
    return out


def studio_meta_v3() -> dict:
    """Studio meta for v3: v2's DNA schema and defaults, v3 garments and coverage, no hair styles yet."""
    from forge_character_forge.studio_bake import studio_meta
    m = studio_meta()
    m.update({"generator": GENERATOR, "hair_styles": ["bald", "shoulder"], "garments": list(garments.GARMENTS),
              "garment_colors": {k: list(c) for k, c in garments.COLORS.items()}, "covers": garments.COVERS,
              "coverage_defaults": garments.COVERAGE_DEFAULTS, "breast_support": {"basic_top": 1.15},
              "controls": {k: {"quality": q, "note": note} for k, (q, _, _, note) in controls.CONTROLS.items()},
              "preset_styling": {"male": {"outfit": ["basic_top", "basic_shorts"], "skin_tone": 0.45, "hair_style": "shoulder",
                                          "hair_color": "#1f1712", "hl_amount": 0},
                                 "female": {"outfit": ["basic_top", "basic_shorts"], "skin_tone": 0.3, "hair_style": "shoulder",
                                            "hair_color": "#3b2416", "hl_amount": 0}}})
    return m
