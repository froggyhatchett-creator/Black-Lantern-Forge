"""Identity range: can the MakeHuman hm08 topology express genuinely different adult characters, including a stylized
one, without breaking down?  Experiment only (owner-approved); outputs in ./out_identity.

Variants are built from CC0 targets only (no sculpting), all adult. The stress test extrapolates the stylized face's
targets to 2x and 3x and measures face flips and triangle quality on the head. Diversity is the mean distance between
corresponding head vertices after aligning the eye midpoints.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from morph_proof import (A, apply, body_cam, face_cam, fit_mhclo, grid, items, label, load_obj, outward,  # noqa: E402
                         rasterize, target, tris_of)

OUT = HERE / "out_identity"
MCUP = "breast/female-young-averagemuscle-averageweight-maxcup-averagefirmness.target"
FEM = "macrodetails/caucasian-female-young.target"
MALE = "macrodetails/caucasian-male-young.target"
STYLE = [  # adult stylized face: V-shaped jaw, narrow pointed chin, small nose and mouth, larger lifted eyes
    ("head/head-invertedtriangular.target", 0.8), ("chin/chin-width-decr.target", 0.8), ("chin/chin-prominent-incr.target", 0.3),
    ("nose/nose-scale-horiz-decr.target", 0.8), ("nose/nose-scale-vert-decr.target", 0.6), ("nose/nose-point-width-decr.target", 0.8),
    ("mouth/mouth-scale-horiz-decr.target", 0.6), ("eyes/l-eye-scale-incr.target", 1.0), ("eyes/r-eye-scale-incr.target", 1.0),
    ("eyes/l-eye-height2-incr.target", 0.8), ("eyes/r-eye-height2-incr.target", 0.8), ("eyes/l-eye-corner1-up.target", 0.6),
    ("eyes/r-eye-corner1-up.target", 0.6), ("cheek/l-cheek-bones-incr.target", 0.5), ("cheek/r-cheek-bones-incr.target", 0.5),
]
VARIANTS = {
    "A female (default)": [(FEM, 1.0), (MCUP, 0.5)],
    "B stylized adult (Mercy-direction)": [(FEM, 1.0), (MCUP, 0.8), ("macrodetails/universal-female-young-averagemuscle-minweight.target", 0.4)] + STYLE,
    "C athletic female": [(FEM, 1.0), (MCUP, 0.4), ("macrodetails/universal-female-young-maxmuscle-averageweight.target", 1.0), ("torso/torso-vshape-incr.target", 0.6)],
    "D heavy male": [(MALE, 1.0), ("macrodetails/universal-male-young-averagemuscle-maxweight.target", 1.0)],
    "E lean female, oval face": [(FEM, 1.0), (MCUP, 0.3), ("macrodetails/universal-female-young-averagemuscle-minweight.target", 1.0), ("head/head-oval.target", 0.8)],
}


def face_quality(v, t, ref_v, head):
    tri_head = head[t].all(1)
    tt = t[tri_head]
    n0 = np.cross(ref_v[tt[:, 1]] - ref_v[tt[:, 0]], ref_v[tt[:, 2]] - ref_v[tt[:, 0]])
    n1 = np.cross(v[tt[:, 1]] - v[tt[:, 0]], v[tt[:, 2]] - v[tt[:, 0]])
    flips = int((np.sum(n0 * n1, 1) < 0).sum())
    ang = []
    for k in range(3):
        a, b, c = v[tt[:, k]], v[tt[:, (k + 1) % 3]], v[tt[:, (k + 2) % 3]]
        u, w = b - a, c - a
        ang.append(np.degrees(np.arccos(np.clip(np.sum(u * w, 1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(w, axis=1) + 1e-12), -1, 1))))
    ang = np.min(np.stack(ang, 1), 1)
    return {"head_triangles": int(len(tt)), "flipped_vs_reference": flips, "min_angle_deg_p1": round(float(np.percentile(ang, 1)), 2),
            "degenerate_lt_2deg": int((ang < 2).sum())}


def aligned_head(v, eyes_fit, head):
    ev = eyes_fit(v)
    return v[head] - ev.mean(0)


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    base, groups = load_obj(A / "3dobjs" / "base.obj")
    bt = outward(base, tris_of(groups["body"]))
    _, eg = load_obj(A / "eyes" / "high-poly" / "high-poly.obj")
    et = tris_of([f for fs in eg.values() for f in fs])

    def eyes_fit(v):
        return fit_mhclo(A / "eyes" / "high-poly" / "high-poly.mhclo", v)

    vs = {name: apply(base, *spec) for name, spec in VARIANTS.items()}
    neck = np.percentile(base[:, 1], 86.5)  # head and neck region (top ~13.5% of height)
    head = base[:, 1] > neck
    rep = {"variants": {}, "stress": {}, "diversity_mm": {}}
    face_tiles, body_tiles = [], []
    for name, v in vs.items():
        h = v[:, 1].max() - v[:, 1].min()
        rep["variants"][name] = {"height_m": round(float(h), 3), "quality": face_quality(v, bt, base, head)}
        for yaw in (0, 35):
            face_tiles.append(label(rasterize(items(v, bt, et, eyes_fit), face_cam(v, eyes_fit, yaw), W=300, H=360), f"{name} {yaw}"))
        body_tiles.append(label(rasterize(items(v, bt, et, eyes_fit), body_cam(v, 20), W=240, H=460), name))
    grid(face_tiles, 4).save(OUT / "faces.png")
    grid(body_tiles, 5).save(OUT / "bodies_dev_only.png")
    names = list(vs)
    aligned = {n: aligned_head(vs[n], eyes_fit, head) for n in names}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            d = np.linalg.norm(aligned[names[i]] - aligned[names[j]], axis=1)
            rep["diversity_mm"][f"{names[i][:1]}-{names[j][:1]}"] = round(float(d.mean() * 1000), 2)
    # stress: extrapolate the stylized face beyond the targets' designed range
    fem = apply(base, *VARIANTS["A female (default)"])
    stress_tiles = []
    for w in (1.0, 2.0, 3.0):
        v = apply(fem, *[(r, s * w) for r, s in STYLE])
        rep["stress"][f"style x{w:g}"] = face_quality(v, bt, fem, head)
        stress_tiles.append(label(rasterize(items(v, bt, et, eyes_fit), face_cam(v, eyes_fit, 25), W=300, H=360), f"stylized face x{w:g}"))
    grid(stress_tiles, 3).save(OUT / "stress.png")
    # reference beside the stylized variant (geometry only: no hair, no materials, no accessories)
    ref = Image.open(HERE.parent.parent / "examples/character_forge_aaa/benchmarks/REF-001_mercy.webp").convert("RGB")
    face = ref.crop((500, 300, 800, 660)).resize((300, 360))  # face region of the 1152x1728 reference (verified)
    b = vs["B stylized adult (Mercy-direction)"]
    grid([label(np.asarray(face), "REF-001 (reference)"),
          label(rasterize(items(b, bt, et, eyes_fit), face_cam(b, eyes_fit, 20), W=300, H=360), "B: targets only, geometry only")], 2).save(OUT / "ref001_vs_stylized.png")
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "identity_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
