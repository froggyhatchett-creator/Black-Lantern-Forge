"""Independent comparison of a rigged Forge GLB and its Blender round trip (Phase 1). Forge's reader and validator,
numpy, PIL and Forge's independent Node player (tools/glb_playback.mjs); nothing from Blender is trusted.

    python3 rig_compare.py <source.glb> <roundtrip.glb> <out.json>

Sections: validator; asset metadata; skin (joint names, order, hierarchy, inverse bind matrices, rest transforms);
meshes (counts, attributes, triangle sets, then per matched vertex: position, normal, UV, skin weights by joint
name, morph deltas by target name); materials and image pixels; animations (names, channels, durations, key counts,
values sampled at the source's key times); playback (walk frames and blink weights through glb_playback.mjs, posed
vertices compared through the vertex matching).
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.validate import read_glb, validate_glb  # noqa: E402

NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
DT = {5126: "<f4", 5125: "<u4", 5123: "<u2", 5121: "u1", 5122: "<i2", 5120: "i1"}
NORM = {5121: 255.0, 5123: 65535.0, 5120: 127.0, 5122: 32767.0}


class G:
    def __init__(self, path):
        self.g, self.b = read_glb(path)
        self.path = path
        g = self.g
        self.parent = {}
        for i, n in enumerate(g["nodes"]):
            for c in n.get("children", []):
                self.parent[c] = i

    def acc(self, i):
        a = self.g["accessors"][i]
        n = NC[a["type"]]
        if "bufferView" in a:
            bv = self.g["bufferViews"][a["bufferView"]]
            stride = bv.get("byteStride")
            dt = np.dtype(DT[a["componentType"]])
            off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
            if stride and stride != dt.itemsize * n:
                raw = np.frombuffer(self.b, np.uint8, stride * (a["count"] - 1) + dt.itemsize * n, off)
                x = np.stack([np.frombuffer(raw[k * stride:k * stride + dt.itemsize * n].tobytes(), dt) for k in range(a["count"])])
            else:
                x = np.frombuffer(self.b, dt, a["count"] * n, off).reshape(a["count"], n)
            x = x.astype(float)
            if a.get("normalized") and a["componentType"] in NORM:
                x = x / NORM[a["componentType"]]
        else:
            x = np.zeros((a["count"], n))
        if "sparse" in a:
            sp = a["sparse"]
            ib = self.g["bufferViews"][sp["indices"]["bufferView"]]
            idx = np.frombuffer(self.b, DT[sp["indices"]["componentType"]], sp["count"], ib.get("byteOffset", 0) + sp["indices"].get("byteOffset", 0))
            vb = self.g["bufferViews"][sp["values"]["bufferView"]]
            val = np.frombuffer(self.b, DT[a["componentType"]], sp["count"] * n, vb.get("byteOffset", 0) + sp["values"].get("byteOffset", 0)).reshape(-1, n)
            x = x.copy()
            x[idx.astype(int)] = val
        return x if n > 1 else x[:, 0]

    def local(self, i):
        n = self.g["nodes"][i]
        if "matrix" in n:
            return np.array(n["matrix"], float).reshape(4, 4).T
        return trs(n.get("translation", [0, 0, 0]), n.get("rotation", [0, 0, 0, 1]), n.get("scale", [1, 1, 1]))

    def world(self, i):
        M = self.local(i)
        while i in self.parent:
            i = self.parent[i]
            M = self.local(i) @ M
        return M

    def name(self, i):
        return self.g["nodes"][i].get("name", f"#{i}")


def trs(t, q, s):
    x, y, z, w = q
    M = np.eye(4)
    M[:3, :3] = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]) * np.array(s)[None]
    M[:3, 3] = t
    return M


def rot_deg(A, B):
    R = A[:3, :3] @ np.linalg.inv(B[:3, :3])
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def meshes(gg):
    """mesh name -> dict of attributes (first primitive; Forge characters have one primitive per mesh)."""
    out = {}
    for ni, n in enumerate(gg.g["nodes"]):
        if "mesh" not in n:
            continue
        m = gg.g["meshes"][n["mesh"]]
        prims = m["primitives"]
        p = prims[0]
        d = {"node": ni, "primitives": len(prims), "attributes": sorted(p["attributes"]), "material": gg.g["materials"][p["material"]]["name"] if "material" in p else None,
             "P": gg.acc(p["attributes"]["POSITION"]), "F": gg.acc(p["indices"]).astype(int).reshape(-1, 3)}
        for k, a in (("N", "NORMAL"), ("UV", "TEXCOORD_0"), ("J", "JOINTS_0"), ("W", "WEIGHTS_0"), ("C", "COLOR_0")):
            if a in p["attributes"]:
                d[k] = gg.acc(p["attributes"][a])
        names = (m.get("extras") or {}).get("targetNames", [])
        d["targets"] = {names[k] if k < len(names) else f"#{k}": gg.acc(t["POSITION"]) for k, t in enumerate(p.get("targets", []))}
        d["skin"] = n.get("skin")
        out[m.get("name") or gg.name(ni)] = d
    return out


def match(src, dst):
    """For each dst vertex, the src vertex with the same position (1 um) and UV; nearest position as fallback."""
    def key(d):
        k = np.round(d["P"] * 1e6).astype(np.int64)
        if "UV" in d:
            k = np.c_[k, np.round(d["UV"] * 1e6).astype(np.int64)]
        return k
    ks, kd = key(src), key(dst)
    lut = {tuple(r): i for i, r in enumerate(ks)}
    m = np.array([lut.get(tuple(r), -1) for r in kd])
    miss = np.nonzero(m < 0)[0]
    for i in miss:
        m[i] = int(np.argmin(((src["P"] - dst["P"][i]) ** 2).sum(1)))
    return m, len(miss)


def weights_by_name(d, joint_names):
    W = np.zeros((len(d["P"]), len(joint_names)))
    J = d["J"].astype(int)
    for c in range(J.shape[1]):
        np.add.at(W, (np.arange(len(J)), J[:, c]), d["W"][:, c])
    return W


def sample(times, vals, t, path):
    """LINEAR sampling (slerp-equivalent normalized lerp for rotations, sign-aligned)."""
    t = np.clip(t, times[0], times[-1])
    j = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2)
    if len(times) == 1:
        return np.repeat(vals[:1], len(t), 0)
    a = (t - times[j]) / np.maximum(times[j + 1] - times[j], 1e-12)
    v0, v1 = vals[j], vals[j + 1]
    if path == "rotation":
        v1 = np.where(((v0 * v1).sum(1) < 0)[:, None], -v1, v1)
        r = v0 * (1 - a)[:, None] + v1 * a[:, None]
        return r / np.linalg.norm(r, axis=1, keepdims=True)
    return v0 * (1 - a)[:, None] + v1 * a[:, None]


def main():
    srcp, dstp, outp = sys.argv[1:4]
    S, D = G(srcp), G(dstp)
    rep = {"source": str(srcp), "roundtrip": str(dstp)}
    for tag, p in (("source", srcp), ("roundtrip", dstp)):
        v = validate_glb(p)
        rep[f"validator_{tag}"] = {"errors": v["errors"], "warnings": v["warnings"], "stats": v["stats"]}
    rep["asset"] = {"source_generator": S.g["asset"].get("generator"), "roundtrip_generator": D.g["asset"].get("generator"),
                    "source_has_forge_extras": "forge" in (S.g["asset"].get("extras") or {}),
                    "roundtrip_has_forge_extras": "forge" in (D.g["asset"].get("extras") or {})}
    # --- skin
    sk_s, sk_d = S.g["skins"][0], D.g["skins"][0]
    js, jd = [S.name(i) for i in sk_s["joints"]], [D.name(i) for i in sk_d["joints"]]
    ibm_s = S.acc(sk_s["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    ibm_d = D.acc(sk_d["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    pos_d = {n: k for k, n in enumerate(jd)}
    common = [n for n in js if n in pos_d]
    par = lambda gg, sk, i: gg.name(gg.parent[i]) if i in gg.parent else None
    hier_s = {S.name(i): par(S, sk_s, i) for i in sk_s["joints"]}
    hier_d = {D.name(i): par(D, sk_d, i) for i in sk_d["joints"]}
    ibm_diff = max(np.abs(ibm_s[k] - ibm_d[pos_d[n]]).max() for k, n in enumerate(js) if n in pos_d)
    rest_t, rest_r, bind_err_s, bind_err_d = [], [], [], []
    for k, n in enumerate(js):
        if n not in pos_d:
            continue
        Ws, Wd = S.world(sk_s["joints"][k]), D.world(sk_d["joints"][pos_d[n]])
        rest_t.append(np.linalg.norm(Ws[:3, 3] - Wd[:3, 3]))
        rest_r.append(rot_deg(Ws, Wd))
        bind_err_s.append(np.abs(Ws @ ibm_s[k] - np.eye(4)).max())
        bind_err_d.append(np.abs(Wd @ ibm_d[pos_d[n]] - np.eye(4)).max())
    rep["skin"] = {"joints_source": len(js), "joints_roundtrip": len(jd), "same_names": sorted(js) == sorted(jd), "same_order": js == jd,
                   "hierarchy_same": all(hier_s[n] == hier_d.get(n) for n in js),
                   "inverse_bind_max_abs_diff": round(float(ibm_diff), 7),
                   "rest_joint_position_max_mm": round(float(max(rest_t)) * 1000, 4),
                   "rest_joint_rotation_max_deg": round(float(max(rest_r)), 4),
                   "rest_x_inverse_bind_identity_err_source": round(float(max(bind_err_s)), 7),
                   "rest_x_inverse_bind_identity_err_roundtrip": round(float(max(bind_err_d)), 7),
                   "extra_nodes_roundtrip": sorted(set(D.name(i) for i in range(len(D.g["nodes"]))) - set(S.name(i) for i in range(len(S.g["nodes"]))))}
    # --- meshes
    MS, MD = meshes(S), meshes(D)
    rep["meshes"] = {}
    matches = {}
    for name, a in MS.items():
        b = MD.get(name)
        if b is None:
            rep["meshes"][name] = {"missing_in_roundtrip": True}
            continue
        m, miss = match(a, b)
        matches[name] = m
        r = {"vertices": [len(a["P"]), len(b["P"])], "triangles": [len(a["F"]), len(b["F"])], "primitives_roundtrip": b["primitives"],
             "attributes": [a["attributes"], b["attributes"]], "material": [a["material"], b["material"]],
             "unmatched_vertices": int(miss), "position_max_mm": round(float(np.abs(a["P"][m] - b["P"]).max()) * 1000, 5)}
        qa = np.sort(np.sort(np.round(a["P"][a["F"]] * 1e6).astype(np.int64).reshape(len(a["F"]), 3, 3).view([("", np.int64)] * 3)[..., 0], 1), 1)
        qb = np.sort(np.sort(np.round(b["P"][b["F"]] * 1e6).astype(np.int64).reshape(len(b["F"]), 3, 3).view([("", np.int64)] * 3)[..., 0], 1), 1)
        r["same_triangle_set"] = bool(len(qa) == len(qb) and (np.sort(qa.view([("", qa.dtype)] * 3).ravel()) == np.sort(qb.view([("", qb.dtype)] * 3).ravel())).all())
        if "N" in a and "N" in b:
            r["normal_max_deg"] = round(float(np.degrees(np.arccos(np.clip((a["N"][m] * b["N"]).sum(1) / np.linalg.norm(b["N"], axis=1), -1, 1))).max()), 4)
        if "UV" in a and "UV" in b:
            r["uv_max_abs_diff"] = float(np.abs(a["UV"][m] - b["UV"]).max())
        if "C" in a:
            r["color_max_abs_diff"] = float(np.abs(a["C"][m][:, :3] - b["C"][:, :3]).max()) if "C" in b else "missing"
        if "W" in a and "W" in b:
            Wa = weights_by_name(a, js)
            Wb = weights_by_name(b, jd)[:, [pos_d[n] for n in js]]
            r["skin_weight_max_abs_diff"] = round(float(np.abs(Wa[m] - Wb).max()), 6)
        r["morph_targets"] = [list(a["targets"]), list(b["targets"])]
        r["morph_delta_max_mm"] = {t: round(float(np.abs(a["targets"][t][m] - b["targets"][t]).max()) * 1000, 5) if t in b["targets"] else "missing" for t in a["targets"]}
        rep["meshes"][name] = r
    rep["meshes_extra_in_roundtrip"] = sorted(set(MD) - set(MS))
    # --- materials and images
    def img(gg, ti):
        im = gg.g["images"][gg.g["textures"][ti]["source"]]
        bv = gg.g["bufferViews"][im["bufferView"]]
        data = gg.b[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
        return im.get("name"), np.asarray(Image.open(io.BytesIO(data)).convert("RGBA")).astype(int), gg.g["textures"][ti].get("sampler")
    mats = {}
    md = {m["name"]: m for m in D.g["materials"]}
    for ma in S.g["materials"]:
        mb = md.get(ma["name"])
        if mb is None:
            mats[ma["name"]] = "missing"
            continue
        pa, pb = ma.get("pbrMetallicRoughness", {}), mb.get("pbrMetallicRoughness", {})
        r = {"baseColorFactor": [pa.get("baseColorFactor", [1, 1, 1, 1]), pb.get("baseColorFactor", [1, 1, 1, 1])],
             "metallic_roughness": [[pa.get("metallicFactor", 1), pa.get("roughnessFactor", 1)], [pb.get("metallicFactor", 1), pb.get("roughnessFactor", 1)]],
             "alphaMode": [ma.get("alphaMode", "OPAQUE"), mb.get("alphaMode", "OPAQUE")], "alphaCutoff": [ma.get("alphaCutoff"), mb.get("alphaCutoff")],
             "doubleSided": [ma.get("doubleSided", False), mb.get("doubleSided", False)], "textures": {}}
        for slot, ga, gb in (("baseColor", pa.get("baseColorTexture"), pb.get("baseColorTexture")), ("normal", ma.get("normalTexture"), mb.get("normalTexture")),
                             ("metallicRoughness", pa.get("metallicRoughnessTexture"), pb.get("metallicRoughnessTexture"))):
            if not ga and not gb:
                continue
            if not ga or not gb:
                r["textures"][slot] = {"present": [bool(ga), bool(gb)]}
                continue
            na, ia, sa = img(S, ga["index"])
            nb, ib, sb = img(D, gb["index"])
            r["textures"][slot] = {"image": [na, nb], "size": [list(ia.shape[:2]), list(ib.shape[:2])],
                                   "pixel_max_abs_diff": int(np.abs(ia - ib).max()) if ia.shape == ib.shape else "size differs",
                                   "sampler": [S.g["samplers"][sa] if sa is not None else None, D.g["samplers"][sb] if sb is not None else None],
                                   "scale": [ga.get("scale"), gb.get("scale")]}
        mats[ma["name"]] = r
    rep["materials"] = mats
    # --- animations
    anims = {}
    ad = {a["name"]: a for a in D.g.get("animations", [])}
    for an in S.g["animations"]:
        bn = ad.get(an["name"])
        if bn is None:
            anims[an["name"]] = "missing"
            continue
        def chans(gg, a):
            out = {}
            for c in a["channels"]:
                s = a["samplers"][c["sampler"]]
                out[(gg.name(c["target"]["node"]), c["target"]["path"])] = (gg.acc(s["input"]), gg.acc(s["output"]), s.get("interpolation", "LINEAR"))
            return out
        ca, cb = chans(S, an), chans(D, bn)
        worst = {"rotation": 0.0, "translation": 0.0, "scale": 0.0}
        constant_extra = 0
        for k, (ta, va, ia) in ca.items():
            if k not in cb:
                continue
            tb, vb, ib = cb[k]
            sa, sb = sample(ta, va, ta, k[1]), sample(tb, vb, ta, k[1])
            if k[1] == "rotation":
                worst["rotation"] = max(worst["rotation"], float(np.degrees(2 * np.arccos(np.clip(np.abs((sa * sb).sum(1)), 0, 1))).max()))
            else:
                worst[k[1]] = max(worst[k[1]], float(np.abs(sa - sb).max()))
        for k in set(cb) - set(ca):  # channels Blender added: are they constant at the rest value?
            tb, vb, _ = cb[k]
            if np.ptp(vb, axis=0).max() < 1e-6:
                constant_extra += 1
        dur = lambda c: max(float(v[0][-1]) for v in c.values())
        anims[an["name"]] = {"channels": [len(ca), len(cb)], "source_channels_missing": len(set(ca) - set(cb)), "extra_channels": len(set(cb) - set(ca)),
                             "extra_channels_constant": constant_extra, "duration_s": [round(dur(ca), 5), round(dur(cb), 5)],
                             "keys_per_channel": [sorted({len(v[0]) for v in ca.values()}), sorted({len(v[0]) for v in cb.values()})],
                             "interpolation": [sorted({v[2] for v in ca.values()}), sorted({v[2] for v in cb.values()})],
                             "max_rotation_deg_at_source_keys": round(worst["rotation"], 5), "max_translation_mm_at_source_keys": round(worst["translation"] * 1000, 5),
                             "max_scale_diff": round(worst["scale"], 7)}
    rep["animations"] = anims
    rep["animations_extra_in_roundtrip"] = sorted(set(ad) - {a["name"] for a in S.g["animations"]})
    # --- playback through the independent player
    play = {}
    want = ",".join(n for n in MS if n in MD)
    with tempfile.TemporaryDirectory() as tmp:
        def run(p, tag, args):
            o = Path(tmp) / tag
            r = subprocess.run(["node", str(ROOT / "tools/glb_playback.mjs"), str(p), str(o), "--meshes", want, *args], capture_output=True, text=True)
            if r.returncode:
                raise RuntimeError(r.stderr[-1500:])
            return o
        cases = [("walk", [0, 4, 8, 12, 16, 20, 24, 28, 31], {}), (None, [0], {"blink_l": 0.5, "blink_r": 0.5}), (None, [0], {"blink_l": 1, "blink_r": 1}),
                 ("run", [0, 5, 10, 15, 19], {}), ("wave", [0, 13, 26, 39], {"blink_l": 1, "blink_r": 1})]
        for anim, frames, morph in cases:
            args = ["--frames", ",".join(map(str, frames))] + (["--anim", anim] if anim else []) + (["--morph", ",".join(f"{k}={v}" for k, v in morph.items())] if morph else [])
            tag = f"{anim or 'rest'}_{'_'.join(f'{k}{v}' for k, v in morph.items()) or 'nomorph'}"
            oa, ob = run(srcp, "a_" + tag, args), run(dstp, "b_" + tag, args)
            worst, per = 0.0, {}
            for f in frames:
                for name, m in matches.items():
                    pa = np.fromfile(oa / f"{name}_f{f}.f4", "<f4").reshape(-1, 3)
                    pb = np.fromfile(ob / f"{name}_f{f}.f4", "<f4").reshape(-1, 3)
                    e = float(np.abs(pa[m] - pb).max())
                    per[name] = max(per.get(name, 0.0), e)
                    worst = max(worst, e)
            play[tag] = {"frames": frames, "max_mm": round(worst * 1000, 4), "worst_mesh": max(per, key=per.get), "per_mesh_max_mm": {k: round(v * 1000, 4) for k, v in per.items()}}
    rep["playback"] = play
    Path(outp).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({"skin": rep["skin"], "playback": {k: (v["max_mm"], v["worst_mesh"]) for k, v in play.items()}}, indent=1))


if __name__ == "__main__":
    main()
