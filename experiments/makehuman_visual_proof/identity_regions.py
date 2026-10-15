"""Coherent regional facial identity on MakeHuman hm08 topology, plus per-face eyelid rig refit (owner-approved
experiment, non-production). Target direction: REF-001's facial structure (artist-guided parameters, not measurements).

Identity = a small set of region parameters (one affine transform per region with a smooth compact 3D falloff), applied
to the whole head, so hidden surfaces stay consistent. Expression (half-lidded, blink) stays separate: it is an
eyelid pose using the face's own lid bones, with the closing angle refit for each face.
Outputs: ./out_regions.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from identity_warp import FEM, eye_px, landmarks, quality  # noqa: E402
from morph_proof import A, apply, face_cam, fit_mhclo, grid, items, label, load_obj, outward, rasterize, tris_of  # noqa: E402
from proof import bvh_frame_rotations, mh_lid_close  # noqa: E402

OUT = HERE / "out_regions"
MM = 0.001
# identity parameters (Mercy direction): every value is an artist-guided choice, recorded as such
IDENTITY = {
    "eye": {"tilt_deg": 7.0, "width": 1.12, "height": 0.90, "shift_lateral_mm": 1.0},
    "nose": {"width": 0.82, "length": 0.90, "projection": 0.82, "tip_upturn_deg": 5.0},
    "mouth": {"width": 0.86, "lip_height": 1.06, "lip_projection": 1.05},
    "cheekbone": {"lift_mm": (1.5, 2.5, 1.0)},
    "jaw": {"taper_at_chin": 0.14},
    "chin": {"width": 0.82, "shift_mm": (0.0, -2.5, 1.5)},
}


def falloff(v, c, r, plateau=0.65):
    """Full weight across the feature (q <= plateau), smooth C1 fade to zero at the region boundary (q = 1).
    (Run 1 used (1 - q^2)^2, which gave feature extremities only 10-40 % of the transform; see out_regions_v1_falloff_bug.)"""
    q = np.sqrt((((v - c) / r) ** 2).sum(1))
    t = np.clip((1 - q) / (1 - plateau), 0, 1)
    return t * t * (3 - 2 * t)


def rot(axis, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def affine(v, w, pivot, M, t=np.zeros(3)):
    return w[:, None] * (((v - pivot) @ M.T + pivot + t) - v)


def identity_displacement(v, L, cl, re, eye_helpers, P):
    """Sum of regional displacements (left side mirrored). Eyeball helper vertices move rigidly (translation only)."""
    d = np.zeros_like(v)
    tip, alar = v[L["nose_tip"]], v[L["alar"]]
    mc, ul, ll = v[L["mouth_corner"]], v[L["upper_lip_mid"]], v[L["lower_lip_mid"]]
    pog, gon, zyg = v[L["pogonion"]], v[L["gonion"]], v[L["cheekbone"]]
    eye_c = {}
    for s in (1.0, -1.0):
        S = np.array([s, 1, 1])
        c = cl * S
        e = P["eye"]
        M = rot("z", s * e["tilt_deg"]) @ np.diag([e["width"], e["height"], 1.0])
        t = np.array([s * e["shift_lateral_mm"] * MM, 0, 0])
        w = falloff(v, c, np.array([0.030, 0.024, 0.026]))
        de = affine(v, w, c, M, t)
        # keep lids and socket on their original distance from the eyeball centre, so they still hug the eye
        near = np.linalg.norm(v - c, axis=1) < re * 1.6
        r0 = np.linalg.norm(v[near] - c, axis=1)
        p1 = v[near] + de[near] - (c + t)
        de[near] = (c + t) + p1 / np.linalg.norm(p1, axis=1, keepdims=True) * r0[:, None] - v[near]
        d += de
        eye_c[s] = t
        # cheekbone lift
        lift = np.array(P["cheekbone"]["lift_mm"]) * MM * S
        d += falloff(v, zyg * S, np.array([0.022, 0.018, 0.02]))[:, None] * lift
    # nose: scale about its base on the face plane, slight upturn
    n = P["nose"]
    base = np.array([0.0, tip[1] + 0.008, tip[2] - 0.024])
    M = rot("x", -n["tip_upturn_deg"]) @ np.diag([n["width"], n["length"], n["projection"]])
    d += affine(v, falloff(v, (tip + base) / 2 + [0, 0.008, 0], np.array([0.024, 0.036, 0.03])), base, M)
    # mouth: about the mouth centre
    m = P["mouth"]
    mcen = np.array([0.0, (ul[1] + ll[1]) / 2, (ul[2] + ll[2]) / 2 - 0.004])
    d += affine(v, falloff(v, mcen, np.array([abs(mc[0]) * 1.6, 0.022, 0.024])), mcen,
                np.diag([m["width"], m["lip_height"], m["lip_projection"]]))
    # jaw taper: lateral scale shrinking toward the chin, front/lower face only (whole 3D jaw, including hidden sides)
    top_y, bot_y = mcen[1] + 0.01, pog[1] - 0.025
    tt = np.clip((top_y - v[:, 1]) / (top_y - bot_y), 0, 1)
    tt = tt * tt * (3 - 2 * tt)
    front = np.clip((v[:, 2] - (gon[2] - 0.035)) / 0.03, 0, 1)
    below_neck = np.clip((v[:, 1] - (bot_y - 0.03)) / 0.02, 0, 1)
    d[:, 0] += -P["jaw"]["taper_at_chin"] * v[:, 0] * tt * front * below_neck
    # chin: narrow and point
    ch = P["chin"]
    d += affine(v, falloff(v, pog + [0, -0.004, -0.008], np.array([0.026, 0.022, 0.022])), pog,
                np.diag([ch["width"], 1, 1]), np.array(ch["shift_mm"]) * MM)
    # eyeballs: rigid
    for s, t in eye_c.items():
        idx = eye_helpers[s]
        d[idx] = t
    return d


def lid_rig(skel, weights, rots):
    """Lid-closing pose with a scale factor on the face pose unit's closing rotation."""
    def pose(v, k):
        return mh_lid_close(v, skel, weights, {b: (r[0] * k, r[1], r[2]) for b, r in rots.items()}, 1)
    return pose


def refit_close(v, pose, up_idx, lo_idx, overlap=0.3 * MM):
    """Smallest closing factor that brings the upper-lid midpoint down to the lower-lid midpoint."""
    target = v[lo_idx, 1] + overlap
    lo, hi = 0.2, 3.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if pose(v, mid)[up_idx, 1] > target:
            lo = mid
        else:
            hi = mid
    return hi


def penetration(v, centers, re, lid_idx):
    out = 0
    for c in centers:
        dist = np.linalg.norm(v[lid_idx] - c, axis=1)
        out += int((dist < re * 0.985).sum())
    return out


def smoothness(v, faces_t, head):
    """Mean |umbrella Laplacian| over head vertices (surface noise proxy)."""
    nb = {}
    for a, b, c in faces_t:
        for x, y in ((a, b), (b, c), (c, a)):
            nb.setdefault(x, set()).add(y)
            nb.setdefault(y, set()).add(x)
    idx = [i for i in np.nonzero(head)[0] if i in nb]
    lap = np.array([np.linalg.norm(v[list(nb[i])].mean(0) - v[i]) for i in idx])
    return float(lap.mean() * 1000)


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    base, groups = load_obj(A / "3dobjs" / "base.obj")
    bt = outward(base, tris_of(groups["body"]))
    _, eg = load_obj(A / "eyes" / "high-poly" / "high-poly.obj")
    et = tris_of([f for fs in eg.values() for f in fs])

    def eyes_fit(v):
        return fit_mhclo(A / "eyes" / "high-poly" / "high-poly.mhclo", v)

    helpers = {1.0: np.unique(np.concatenate([np.array(f) for f in groups["helper-l-eye"]])),
               -1.0: np.unique(np.concatenate([np.array(f) for f in groups["helper-r-eye"]]))}
    # MakeHuman's "l" is the character's left; make sure each helper set sits on the matching x side
    if base[helpers[1.0], 0].mean() < 0:
        helpers = {1.0: helpers[-1.0], -1.0: helpers[1.0]}
    fem = apply(base, *FEM)
    ev = eyes_fit(fem)
    L, cl, re = landmarks(fem, ev)
    mod = fem + identity_displacement(fem, L, cl, re, helpers, IDENTITY)
    head = fem[:, 1] > fem[L["pogonion"]][1] - 0.045
    dv = np.linalg.norm(mod - fem, axis=1)
    rep = {"identity_parameters": IDENTITY,
           "displacement_mm": {"head_mean": round(float(dv[head].mean() * 1000), 2), "head_p95": round(float(np.percentile(dv[head], 95) * 1000), 2),
                               "max": round(float(dv.max() * 1000), 2), "vertices_moved_gt_1mm": int((dv > 0.001).sum())},
           "landmark_shift_mm": {k: round(float(dv[i] * 1000), 2) for k, i in L.items()},
           "quality_vs_original": quality(mod, fem, bt, head),
           "smoothness_mean_laplacian_mm": {"original": round(smoothness(fem, bt, head), 4), "modified": round(smoothness(mod, bt, head), 4)},
           "topology_uv": "unchanged (vertex positions only)"}
    # eyelid animation, refit per face
    skel = json.load(open(A / "rigs" / "default.mhskel"))
    wts = json.load(open(A / "rigs" / "default_weights.mhw"))["weights"]
    rots = {}
    for unit in ("LeftUpperLidClosed", "RightUpperLidClosed"):
        rots.update(bvh_frame_rotations(A / "poseunits" / "face-poseunits.bvh", A / "poseunits" / "face-poseunits.json", unit))
    pose = lid_rig(skel, wts, rots)
    # lid vertices: strongly weighted (> 0.3) to the closing bones
    lid_idx = np.unique(np.concatenate([np.array(wts[b])[np.array(wts[b])[:, 1] > 0.3, 0].astype(int) for b in rots if b in wts]))
    anim = {}
    seqs = {}
    for name, v in (("original", fem), ("modified", mod)):
        Lv, clv, rev = landmarks(v, eyes_fit(v))
        k_close = refit_close(v, pose, Lv["upper_lid_mid"], Lv["lower_lid_mid"])
        centers = [eyes_fit(v)[eyes_fit(v)[:, 0] > 0].mean(0), eyes_fit(v)[eyes_fit(v)[:, 0] <= 0].mean(0)]
        cam = face_cam(v, eyes_fit, 0)
        open_px = eye_px(v, bt, et, eyes_fit, cam)
        res = {"closing_factor_refit": round(k_close, 3), "closing_angle_deg": round(33.22731 * k_close, 2),
               "fixed_pose_unit_angle_deg": 33.23}
        frames = {}
        for tag, f in (("open", 0.0), ("half-lidded", 0.45), ("blink 50%", 0.5), ("closed", 1.0), ("neutral again", 0.0)):
            vp = pose(v, k_close * f) if f > 0 else v.copy()
            px = eye_px(vp, bt, et, eyes_fit, cam)
            q = quality(vp, v, bt, head)
            res[tag] = {"eye_exposure": round(px / max(open_px, 1), 3), "lid_vertices_inside_eyeball": penetration(vp, centers, rev, lid_idx),
                        "flipped": q["flipped"], "min_angle_deg_p1": q["min_angle_deg_p1"], "max_area_change": q["max_area_change_ratio"]}
            frames[tag] = vp
        res["neutral_return_max_error_mm"] = round(float(np.abs(frames["neutral again"] - v).max() * 1000), 6)
        fixed = pose(v, 1.0)
        res["closed_with_fixed_angle_exposure"] = round(eye_px(fixed, bt, et, eyes_fit, cam) / max(open_px, 1), 3)
        anim[name] = res
        seqs[name] = frames
    rep["eyelid_animation"] = anim
    # renders: identical lights, camera framing rule and materials
    tiles = []
    from PIL import Image
    ref = Image.open(HERE.parent.parent / "examples/character_forge_aaa/benchmarks/REF-001_mercy.webp").convert("RGB")
    refc = np.asarray(ref.crop((500, 300, 800, 660)).resize((300, 360)))
    for yaw, tag in ((0, "front"), (35, "3/4"), (90, "profile")):
        for name, v in (("MakeHuman original", fem), ("Forge regional identity", mod)):
            tiles.append(label(rasterize(items(v, bt, et, eyes_fit), face_cam(v, eyes_fit, yaw), W=300, H=360), f"{name} {tag}"))
        tiles.append(label(refc, "REF-001 (artistic target)") if yaw == 0 else
                     label(rasterize(items(mod, bt, et, eyes_fit), face_cam(mod, eyes_fit, -yaw if yaw != 90 else -90), W=300, H=360),
                           f"Forge identity, other side {tag}"))
    grid(tiles, 3).save(OUT / "identity_regions.png")
    blink_tiles = []
    for name in ("original", "modified"):
        for tag, vp in seqs[name].items():
            blink_tiles.append(label(rasterize(items(vp, bt, et, eyes_fit), face_cam(vp, eyes_fit, 0), W=240, H=200), f"{name}: {tag}"))
        blink_tiles.append(label(rasterize(items(seqs[name]["closed"], bt, et, eyes_fit), face_cam(seqs[name]["closed"], eyes_fit, 35), W=240, H=200), f"{name}: closed 3/4"))
    grid(blink_tiles, 6).save(OUT / "eyelids.png")
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "regions_report.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps(rep, indent=1, default=float))


if __name__ == "__main__":
    main()
