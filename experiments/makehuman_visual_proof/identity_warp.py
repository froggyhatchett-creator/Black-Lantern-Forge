"""Forge-owned facial identity warp on MakeHuman hm08 topology, aimed at REF-001's facial structure.

Experiment only (owner-approved, non-production). Landmarks are located geometrically on the MakeHuman female head and
are approximations. Target offsets are ARTIST-GUIDED estimates read from the reference by eye, not measurements.
A Gaussian RBF interpolates the offsets; zero-displacement anchors keep the warp local; a falloff protects the neck.
Topology and UVs are untouched (vertex positions only). Outputs: ./out_warp.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from morph_proof import (A, apply, face_cam, fit_mhclo, grid, items, label, load_obj, outward, rasterize,  # noqa: E402
                         tris_of)
from proof import DrawItem, _project, bvh_frame_rotations, mh_lid_close  # noqa: E402

OUT = HERE / "out_warp"
FEM = [("macrodetails/caucasian-female-young.target", 1.0),
       ("breast/female-young-averagemuscle-averageweight-maxcup-averagefirmness.target", 0.5)]
MM = 0.001
# artist-guided offsets toward REF-001 (metres, for the LEFT side: +x is lateral; mirrored for the right side)
OFFSETS = {
    "outer_canthus": (3.0, 2.5, -0.5),     # longer, upward-tilted almond eye
    "inner_canthus": (-0.8, -0.3, 0.0),
    "upper_lid_mid": (0.0, -1.6, 0.0),     # heavier, half-lidded upper lid
    "lower_lid_mid": (0.0, 0.6, 0.0),
    "nose_tip": (0.0, 1.2, -2.5),          # smaller, slightly upturned nose (midline)
    "alar": (-2.2, 0.3, -0.8),             # narrower nostril wings
    "mouth_corner": (-2.6, 1.2, 0.0),      # narrower mouth, faintly lifted corners
    "upper_lip_mid": (0.0, 0.0, 0.6),      # fuller lips (midline)
    "lower_lip_mid": (0.0, -0.3, 1.0),
    "cheekbone": (1.8, 2.0, 0.5),          # higher, more defined cheekbones
    "gonion": (-6.5, 2.5, 0.0),            # narrow V-shaped jaw
    "chin_side": (-2.5, -0.5, 0.5),        # narrow chin
    "pogonion": (0.0, -2.0, 1.8),          # slightly longer, pointed chin (midline)
}


def landmarks(v, eyes_v):
    """Approximate surface landmarks on the head (left side + midline). Returns name -> vertex index."""
    left = eyes_v[:, 0] > 0
    cl = eyes_v[left].mean(0)
    re = float(np.linalg.norm(eyes_v[left] - cl, axis=1).mean())
    L = {}
    d = v - cl
    dist = np.linalg.norm(d, axis=1)
    rim = np.nonzero((dist > re * 0.98) & (dist < re * 1.35) & (d[:, 2] > re * 0.2))[0]
    lat, mid = rim[np.abs(d[rim, 1]) < 0.35 * re], rim[np.abs(d[rim, 0]) < 0.25 * re]
    L["outer_canthus"] = lat[np.argmax(d[lat, 0])]
    L["inner_canthus"] = lat[np.argmin(d[lat, 0])]
    up, lo = mid[d[mid, 1] > 0], mid[d[mid, 1] < 0]
    L["upper_lid_mid"] = up[np.argmin(dist[up])]
    L["lower_lid_mid"] = lo[np.argmin(dist[lo])]
    midline = np.abs(v[:, 0]) < 0.004
    band = midline & (v[:, 1] < cl[1] - 0.015) & (v[:, 1] > cl[1] - 0.08)
    tip = np.nonzero(band)[0][np.argmax(v[band, 2])]
    L["nose_tip"] = tip
    t = v[tip]
    al = np.nonzero((v[:, 1] > t[1] - 0.015) & (v[:, 1] < t[1] + 0.002) & (v[:, 2] > t[2] - 0.03) & (v[:, 0] > 0))[0]
    L["alar"] = al[np.argmax(v[al, 0])]
    lips = np.nonzero(midline & (v[:, 1] < t[1] - 0.012) & (v[:, 1] > t[1] - 0.06))[0]
    lips = lips[np.argsort(-v[lips, 1])]  # top to bottom
    z = v[lips, 2]
    peaks = [i for i in range(1, len(lips) - 1) if z[i] >= z[i - 1] and z[i] >= z[i + 1]]
    peaks = sorted(peaks, key=lambda i: -z[i])[:2] if len(peaks) >= 2 else [int(np.argmax(z))] * 2
    a, b = sorted(peaks, key=lambda i: -v[lips[i], 1])
    L["upper_lip_mid"], L["lower_lip_mid"] = lips[a], lips[b]
    my = (v[lips[a], 1] + v[lips[b], 1]) / 2
    mc = np.nonzero((np.abs(v[:, 1] - my) < 0.006) & (v[:, 2] > v[lips[a], 2] - 0.03) & (v[:, 0] > 0))[0]
    L["mouth_corner"] = mc[np.argmax(v[mc, 0])]
    ch = np.nonzero(midline & (v[:, 1] < my - 0.02) & (v[:, 1] > my - 0.07))[0]
    L["pogonion"] = ch[np.argmax(v[ch, 2])]
    pg = v[L["pogonion"]]
    cs = np.nonzero((np.abs(v[:, 1] - (pg[1] - 0.004)) < 0.004) & (v[:, 2] > pg[2] - 0.02) & (v[:, 0] > 0.012) & (v[:, 0] < 0.03))[0]
    L["chin_side"] = cs[np.argmax(v[cs, 2])] if len(cs) else L["pogonion"]
    gn = np.nonzero((v[:, 1] > pg[1]) & (v[:, 1] < my) & (v[:, 2] < cl[2] - 0.04) & (v[:, 0] > 0))[0]
    L["gonion"] = gn[np.argmax(v[gn, 0])]
    zy = np.nonzero((v[:, 1] > cl[1] - 0.03) & (v[:, 1] < cl[1] - 0.008) & (v[:, 2] > cl[2] - 0.045) & (v[:, 2] < cl[2] + 0.01) & (v[:, 0] > 0))[0]
    L["cheekbone"] = zy[np.argmax(v[zy, 0])]
    return {k: int(x) for k, x in L.items()}, cl, re


def anchors(v, cl, re):
    """Zero-displacement points keeping the warp local (left side; mirrored later)."""
    pts = [cl, cl + [0, 0.055, 0.03], cl + [0.035, 0.035, -0.02], cl + [0.0, 0.025, 0.035],     # eye centre, forehead, temple, brow
           [0.0, cl[1] + 0.005, cl[2] + 0.04], [0.0, cl[1] + 0.06, cl[2] + 0.02]]                 # nose root, forehead midline
    ear = np.nonzero((np.abs(v[:, 1] - (cl[1] - 0.01)) < 0.01) & (v[:, 2] < cl[2] - 0.07) & (v[:, 0] > 0))[0]
    if len(ear):
        pts.append(v[ear[np.argmax(v[ear, 0])]])
    return np.array(pts, float)


def rbf_warp(v, src, disp, sigma=0.016, reg=1e-6):
    D = np.linalg.norm(src[:, None] - src[None], axis=2)
    Phi = np.exp(-(D / sigma) ** 2) + reg * np.eye(len(src))
    W = np.linalg.solve(Phi, disp)
    K = np.exp(-(np.linalg.norm(v[:, None] - src[None], axis=2) / sigma) ** 2)
    return K @ W


def quality(v, ref, t, mask):
    tt = t[mask[t].all(1)]
    n0 = np.cross(ref[tt[:, 1]] - ref[tt[:, 0]], ref[tt[:, 2]] - ref[tt[:, 0]])
    n1 = np.cross(v[tt[:, 1]] - v[tt[:, 0]], v[tt[:, 2]] - v[tt[:, 0]])
    ang = []
    for k in range(3):
        a, b, c = v[tt[:, k]], v[tt[:, (k + 1) % 3]], v[tt[:, (k + 2) % 3]]
        u, w = b - a, c - a
        ang.append(np.degrees(np.arccos(np.clip(np.sum(u * w, 1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(w, axis=1) + 1e-12), -1, 1))))
    ang = np.min(np.stack(ang, 1), 1)
    a0 = np.linalg.norm(n0, axis=1)
    a1 = np.linalg.norm(n1, axis=1)
    return {"face_triangles": int(len(tt)), "flipped": int((np.sum(n0 * n1, 1) < 0).sum()),
            "min_angle_deg_p1": round(float(np.percentile(ang, 1)), 2), "degenerate_lt_2deg": int((ang < 2).sum()),
            "max_area_change_ratio": round(float(np.max(np.maximum(a1 / (a0 + 1e-15), a0 / (a1 + 1e-15)))), 2)}


def eye_px(v, bt, et, eyes_fit, cam, W=420, H=480):
    ev = eyes_fit(v)
    img = rasterize([DrawItem(v, bt, color=(0.55, 0.55, 0.55), roughness=1, specular=0),
                     DrawItem(ev, et, color=(1, 0, 0), roughness=1, specular=0, double_sided=True)], cam, W=W, H=H,
                    background=(1, 1, 1), ground_y=None, ssaa=1).astype(int)
    return int(((img[:, :, 0] > 120) & (img[:, :, 1] < 70) & (img[:, :, 2] < 70)).sum())


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    base, groups = load_obj(A / "3dobjs" / "base.obj")
    bt = outward(base, tris_of(groups["body"]))
    _, eg = load_obj(A / "eyes" / "high-poly" / "high-poly.obj")
    et = tris_of([f for fs in eg.values() for f in fs])

    def eyes_fit(v):
        return fit_mhclo(A / "eyes" / "high-poly" / "high-poly.mhclo", v)

    fem = apply(base, *FEM)
    ev = eyes_fit(fem)
    L, cl, re = landmarks(fem, ev)
    # control points: left landmarks + mirrored right ones (midline landmarks once), anchors on both sides
    src, disp, names = [], [], []
    for k, idx in L.items():
        p = fem[idx]
        o = np.array(OFFSETS[k]) * MM
        if abs(p[0]) < 0.004:
            src.append(p), disp.append(o), names.append(k)
        else:
            src.append(p), disp.append(o), names.append(k + ".L")
            src.append(p * [-1, 1, 1]), disp.append(o * [-1, 1, 1]), names.append(k + ".R")
    an = anchors(fem, cl, re)
    for a in an:
        for s in ((1, 1, 1), (-1, 1, 1)):
            q = a * s
            if not any(np.linalg.norm(q - x) < 1e-4 for x in src):
                src.append(q), disp.append(np.zeros(3)), names.append("anchor")
    src, disp = np.array(src), np.array(disp)
    # protect the neck and everything below the jaw; warp only the head
    menton_y = fem[L["pogonion"]][1] - 0.015
    w = np.clip((fem[:, 1] - (menton_y - 0.03)) / 0.03, 0, 1)
    w = w * w * (3 - 2 * w)
    warped = fem + rbf_warp(fem, src, disp) * w[:, None]
    head = fem[:, 1] > menton_y - 0.03
    dv = np.linalg.norm(warped - fem, axis=1)
    rep = {"landmarks_vertex_index": L,
           "landmark_displacement_mm": {n: round(float(np.linalg.norm(warped[np.argmin(np.linalg.norm(fem - p, axis=1))] - p) * 1000), 2)
                                        for n, p in zip(names, src) if n != "anchor"},
           "requested_offset_mm": {k: round(float(np.linalg.norm(OFFSETS[k])), 2) for k in OFFSETS},
           "head_displacement_mm": {"mean": round(float(dv[head].mean() * 1000), 2), "p95": round(float(np.percentile(dv[head], 95) * 1000), 2),
                                    "max": round(float(dv.max() * 1000), 2), "vertices_moved_gt_0_5mm": int((dv > 0.0005).sum())},
           "quality_vs_female": quality(warped, fem, bt, head),
           "topology_uv": "unchanged (vertex positions only; same faces and UV indices)"}
    # blink after reshaping (lid bones from the face pose units; same method as proof.py)
    import json as _j
    skel = _j.load(open(A / "rigs" / "default.mhskel"))
    wts = _j.load(open(A / "rigs" / "default_weights.mhw"))["weights"]
    rots = {}
    for unit in ("LeftUpperLidClosed", "RightUpperLidClosed"):
        rots.update(bvh_frame_rotations(A / "poseunits" / "face-poseunits.bvh", A / "poseunits" / "face-poseunits.json", unit))
    blink = {}
    closed = {}
    for name, v in (("female", fem), ("warped", warped)):
        cam = face_cam(v, eyes_fit, 0)
        o = eye_px(v, bt, et, eyes_fit, cam)
        c = mh_lid_close(v, skel, wts, rots, 1)
        closed[name] = c
        x = eye_px(c, bt, et, eyes_fit, cam)
        blink[name] = {"open_eye_pixels": o, "closed_eye_pixels": x, "visible_fraction_closed": round(x / max(o, 1), 3)}
    rep["blink"] = blink
    rep["quality_blink_warped"] = quality(closed["warped"], warped, bt, head)
    # renders
    tiles = []
    ref = Image.open(HERE.parent.parent / "examples/character_forge_aaa/benchmarks/REF-001_mercy.webp").convert("RGB")
    refc = np.asarray(ref.crop((500, 300, 800, 660)).resize((300, 360)))
    for yaw, tag in ((0, "front"), (35, "3/4"), (90, "profile")):
        for name, v in (("MakeHuman female (untouched)", fem), ("Forge identity warp", warped)):
            tiles.append(label(rasterize(items(v, bt, et, eyes_fit), face_cam(v, eyes_fit, yaw), W=300, H=360), f"{name} {tag}"))
        tiles.append(label(refc, "REF-001 (reference)") if yaw == 0 else np.full((360, 300, 3), 20, np.uint8))
    for name in ("female", "warped"):
        v = closed[name]
        tiles.append(label(rasterize(items(v, bt, et, eyes_fit), face_cam(v, eyes_fit, 0), W=300, H=360), f"{name}: blink = 1"))
    # landmark debug overlay
    cam = face_cam(fem, eyes_fit, 0)
    dbg = Image.fromarray(rasterize(items(fem, bt, et, eyes_fit), cam, W=300, H=360))
    scr, _, _, _ = _project(src, cam, 300, 360)
    dr = ImageDraw.Draw(dbg)
    for (x, y), n in zip(scr, names):
        col = (0, 200, 255) if n == "anchor" else (255, 40, 40)
        dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=col)
    tiles.append(label(np.asarray(dbg), "landmarks (red) / anchors (cyan)"))
    grid(tiles, 3).save(OUT / "identity_warp.png")
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "warp_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
