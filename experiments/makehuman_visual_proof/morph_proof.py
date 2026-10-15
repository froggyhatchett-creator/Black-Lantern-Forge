"""MakeHuman morph-data discovery: real CC0 macro and detail targets on hm08, rendered with Forge's rasterizer.

Experiment only (owner-approved). Shows female/male body shapes from the macro targets, tests a representative set of
body and face targets, maps Forge's 53 studio parameters onto MakeHuman modifiers, and checks garment-fitting risks.
Outputs go to ./out_morph.  Nothing here touches Forge generators, Character DNA, rigging or export.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from proof import A, SKIN, DrawItem, eye_colors, fit_mhclo, load_obj, outward, rasterize, tris_of  # noqa: E402
from proof import Camera  # noqa: E402

OUT = HERE / "out_morph"
T = A / "targets"


def target(rel):
    d = {}
    for line in open(T / rel):
        if line.startswith("#") or not line.strip():
            continue
        i, x, y, z = line.split()
        d[int(i)] = (float(x) * 0.1, float(y) * 0.1, float(z) * 0.1)  # decimeters -> meters
    return d


def apply(base, *weighted):
    v = base.copy()
    for rel, w in weighted:
        for i, dlt in target(rel).items():
            v[i] += np.array(dlt) * w
    return v


def items(v, bt, eyes_t, eyes_fit):
    ev = eyes_fit(v)
    left = ev[:, 0] > 0
    c = [ev[left].mean(0), ev[~left].mean(0)]
    col = np.where(left[:, None], eye_colors(ev, c[0]), eye_colors(ev, c[1]))
    return [DrawItem(v, bt, color=SKIN, roughness=0.5, specular=0.25, sss=1.0),
            DrawItem(ev, eyes_t, colors=col, roughness=0.15, specular=0.8, double_sided=True)]


def body_cam(v, yaw):
    lo, hi = v.min(0), v.max(0)
    h = hi[1] - lo[1]
    return Camera(yaw_deg=yaw, pitch_deg=0, target=(0, lo[1] + h / 2, 0), distance=6.0, ortho_height=h * 1.08)


def face_cam(v, eyes_fit, yaw=25):
    ev = eyes_fit(v)
    m = ev.mean(0)
    ipd = np.linalg.norm(ev[ev[:, 0] > 0].mean(0) - ev[ev[:, 0] <= 0].mean(0))
    return Camera(yaw_deg=yaw, pitch_deg=0, target=(m[0], m[1] - 0.02, m[2]), distance=6.5 * ipd, fov_deg=24)


def label(img, text):
    im = Image.fromarray(img)
    ImageDraw.Draw(im).text((8, 8), text, fill=(255, 255, 0))
    return np.asarray(im)


def grid(tiles, cols):
    h = max(t.shape[0] for t in tiles)
    w = max(t.shape[1] for t in tiles)
    rows = -(-len(tiles) // cols)
    out = Image.new("RGB", (cols * (w + 6), rows * (h + 6)), (20, 20, 20))
    for k, t in enumerate(tiles):
        out.paste(Image.fromarray(t), ((k % cols) * (w + 6), (k // cols) * (h + 6)))
    return out


def boundary_loops(faces, nverts):
    from collections import Counter
    cnt = Counter()
    for f in faces:
        for k in range(len(f)):
            a, b = f[k], f[(k + 1) % len(f)]
            cnt[(min(a, b), max(a, b))] += 1
    bnd = [e for e, c in cnt.items() if c == 1]
    adj = {}
    for a, b in bnd:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen, loops = set(), []
    for s in adj:
        if s in seen:
            continue
        stack, comp = [s], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack += adj[x]
        loops.append(comp)
    return loops


# Forge studio parameter -> MakeHuman modifier(s); quality: direct / approximate / derived / missing
MAPPING = {
    "body.height_m": ("macrodetails-height/Height", "direct", "needs a metres calibration curve"),
    "body.femininity": ("macrodetails/Gender (inverted)", "direct", ""),
    "body.body_fat": ("macrodetails-universal/Weight", "approximate", "MH weight = fat + mass, not fat alone"),
    "body.muscle": ("macrodetails-universal/Muscle", "direct", ""),
    "body.shoulder_width": ("torso/torso-vshape, armslegs upperarm-shoulder-muscle", "approximate", ""),
    "body.chest_width": ("torso/torso-scale-horiz", "approximate", "scales the whole torso width"),
    "body.chest_depth": ("torso/torso-scale-depth", "approximate", ""),
    "body.waist_width": ("hip/hip-waist + stomach", "approximate", "no isolated waist-width target"),
    "body.hip_width": ("hip/hip-scale-horiz", "direct", ""),
    "body.glute_size": ("buttocks/buttocks-volume", "direct", ""),
    "body.belly": ("stomach/stomach-pregnant", "approximate", "pregnancy shape, not abdominal fat"),
    "body.torso_length": ("torso/torso-scale-vert", "direct", ""),
    "body.neck_length": ("neck/neck-scale-vert", "direct", ""),
    "body.neck_thickness": ("neck/neck-scale-horiz + depth", "direct", ""),
    "body.arm_length": ("armslegs upperarm/lowerarm-scale-vert", "direct", ""),
    "body.arm_thickness": ("armslegs upperarm/lowerarm-scale-horiz/depth, -fat, -muscle", "direct", ""),
    "body.leg_length": ("armslegs upperleg/lowerleg-scale-vert, BodyProportions", "direct", ""),
    "body.thigh_thickness": ("armslegs upperleg-scale-horiz / fat", "direct", ""),
    "body.calf_thickness": ("armslegs lowerleg-scale-horiz / fat", "direct", ""),
    "body.hand_size": ("armslegs l/r-hand-scale", "direct", ""),
    "body.foot_size": ("armslegs l/r-foot-scale", "direct", ""),
    "body.head_size": ("head/head-scale-horiz+vert+depth", "direct", ""),
    "body.breast_size": ("breast/BreastSize (cup)", "direct", "macro-dependent target sets"),
    "body.breast_spacing": ("breast/breast-dist", "direct", ""),
    "body.breast_height": ("breast/breast-trans down/up", "direct", ""),
    "body.breast_projection": ("breast/breast-point", "approximate", ""),
    "body.breast_sag": ("breast/BreastFirmness (inverted)", "direct", ""),
    "face.face_width": ("head/head-scale-horiz", "approximate", "whole head, not the face only"),
    "face.face_length": ("head/head-scale-vert + chin-height", "approximate", ""),
    "face.jaw_width": ("chin/chin-bones", "approximate", ""),
    "face.jaw_angle": ("head/head-square / head-rectangular", "approximate", ""),
    "face.chin_width": ("chin/chin-width", "direct", ""),
    "face.chin_length": ("chin/chin-height", "direct", ""),
    "face.chin_projection": ("chin/chin-prominent", "direct", ""),
    "face.cheekbone_width": ("cheek/l+r-cheek-bones", "direct", ""),
    "face.cheekbone_height": ("cheek/l+r-cheek-trans", "direct", ""),
    "face.cheek_fullness": ("cheek/l+r-cheek-volume", "direct", ""),
    "face.asymmetry": ("(l/r modifier pairs at unequal weights)", "derived", "no single target; synthesize from left/right pairs"),
    "face.nose_length": ("nose/nose-scale-vert", "direct", ""),
    "face.nose_width": ("nose/nose-scale-horiz", "direct", ""),
    "face.nose_bridge": ("nose/nose-greek, nose-hump", "approximate", ""),
    "face.nose_tip": ("nose/nose-point-width, nose-volume", "approximate", ""),
    "face.nose_upturn": ("nose/nose-point down/up", "direct", ""),
    "face.eye_size": ("eyes/l+r-eye-scale", "direct", ""),
    "face.eye_spacing": ("eyes/l+r-eye-trans in/out", "direct", ""),
    "face.eye_tilt": ("eyes/l+r-eye-corner1/2, eyefold-angle", "approximate", ""),
    "face.brow_height": ("eyebrows/eyebrows-trans down/up", "direct", ""),
    "face.brow_prominence": ("eyebrows/eyebrows-trans backward/forward, forehead", "approximate", ""),
    "face.lip_upper": ("mouth/mouth-upperlip-volume, -height", "direct", ""),
    "face.lip_lower": ("mouth/mouth-lowerlip-volume, -height", "direct", ""),
    "face.mouth_width": ("mouth/mouth-scale-horiz", "direct", ""),
    "face.ear_size": ("ears/l+r-ear-scale", "direct", ""),
    "face.ear_protrusion": ("ears/l+r-ear-rot, ear-wing", "approximate", ""),
}


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    base, groups = load_obj(A / "3dobjs" / "base.obj")
    body_faces = groups["body"]
    bt = outward(base, tris_of(body_faces))
    _, eg = load_obj(A / "eyes" / "high-poly" / "high-poly.obj")
    et = tris_of([f for fs in eg.values() for f in fs])

    def eyes_fit(v):
        return fit_mhclo(A / "eyes" / "high-poly" / "high-poly.mhclo", v)  # eyes follow the morphed face

    rep = {"targets": {}}
    female = apply(base, ("macrodetails/caucasian-female-young.target", 1.0),
                   ("breast/female-young-averagemuscle-averageweight-maxcup-averagefirmness.target", 0.5))
    male = apply(base, ("macrodetails/caucasian-male-young.target", 1.0))
    for name, v in (("base", base), ("female", female), ("male", male)):
        h = v[:, 1].max() - v[:, 1].min()
        rep[name] = {"height_m": round(float(h), 3), "shoulder_width_m": round(float(np.ptp(v[np.abs(v[:, 1] - (v[:, 1].min() + 0.82 * h)) < 0.01, 0])), 3),
                     "hip_width_m": round(float(np.ptp(v[np.abs(v[:, 1] - (v[:, 1].min() + 0.52 * h)) < 0.01, 0])), 3)}
    # body shapes
    tiles = []
    for name, v in (("base (MakeHuman default)", base), ("female: caucasian-female-young + breast cup 0.5", female),
                    ("male: caucasian-male-young", male)):
        for yaw in (0, 90):
            tiles.append(label(rasterize(items(v, bt, et, eyes_fit), body_cam(v, yaw), W=300, H=560), f"{name} {'front' if yaw == 0 else 'side'}"))
    grid(tiles, 6).save(OUT / "bodies.png")
    for name, v in (("female", female), ("male", male)):
        tiles = [label(rasterize(items(v, bt, et, eyes_fit), face_cam(v, eyes_fit, yaw), W=360, H=420), f"{name} face {yaw}")
                 for yaw in (0, 35)]
        grid(tiles, 2).save(OUT / f"face_{name}.png")
    # representative morphs on the female shape
    tests = [
        ("body", "macrodetails/universal-female-young-maxmuscle-averageweight.target", "Muscle max"),
        ("body", "macrodetails/universal-female-young-averagemuscle-maxweight.target", "Weight max"),
        ("body", "hip/hip-scale-horiz-incr.target", "hip width +"),
        ("body", "buttocks/buttocks-volume-incr.target", "glutes +"),
        ("body", "torso/torso-vshape-incr.target", "torso V-shape +"),
        ("face", "nose/nose-scale-horiz-incr.target", "nose width +"),
        ("face", "mouth/mouth-upperlip-volume-incr.target", "upper lip volume +"),
        ("face", "chin/chin-width-incr.target", "chin width +"),
        ("face", ("eyes/l-eye-scale-incr.target", "eyes/r-eye-scale-incr.target"), "eye scale +"),
        ("face", ("cheek/l-cheek-bones-incr.target", "cheek/r-cheek-bones-incr.target"), "cheekbones +"),
    ]
    body_tiles, face_tiles = [], []
    for kind, rels, title in tests:
        rels = rels if isinstance(rels, tuple) else (rels,)
        v = apply(female, *[(r, 1.0) for r in rels])
        d = np.linalg.norm(v - female, axis=1)
        rep["targets"][title] = {"files": list(rels), "vertices_moved": int((d > 1e-6).sum()), "max_offset_mm": round(float(d.max() * 1000), 2)}
        if kind == "body":
            for vv, tag in ((female, "female"), (v, title)):
                body_tiles.append(label(rasterize(items(vv, bt, et, eyes_fit), body_cam(vv, 30), W=260, H=480), tag))
        else:
            for vv, tag in ((female, "female"), (v, title)):
                face_tiles.append(label(rasterize(items(vv, bt, et, eyes_fit), face_cam(vv, eyes_fit, 25), W=300, H=340), tag))
    grid(body_tiles, 6).save(OUT / "morphs_body.png")
    grid(face_tiles, 4).save(OUT / "morphs_face.png")
    # coverage and garment-fitting checks
    q = {}
    for k, (_, quality, _) in MAPPING.items():
        q[quality] = q.get(quality, 0) + 1
    rep["coverage"] = {"forge_parameters": len(MAPPING), "by_quality": q, "mapping": MAPPING}
    loops = boundary_loops(body_faces, len(base))
    rep["garment_fitting"] = {
        "body_group_boundary_loops": len(loops),
        "loop_sizes": sorted(len(x) for x in loops),
        "helper_groups": sorted(g for g in groups if g.startswith("helper")),
        "body_vertices_used": int(len(np.unique(np.concatenate([np.array(f) for f in body_faces])))),
    }
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "morph_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != "coverage"} | {"coverage": rep["coverage"]["by_quality"]}, indent=1))


if __name__ == "__main__":
    main()
