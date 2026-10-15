"""Measure the body field (no meshing) at standard anthropometric landmarks."""
import sys
import numpy as np
sys.path.insert(0, ".")
from forge_character_forge.params import preset
from forge_character_forge.skeleton import build_skeleton
from forge_character_forge.anatomy import build_field


def extent(field, y, axis, x0=0.0, z0=0.0, lim=0.5, step=0.002, xlim=None):
    t = np.arange(-lim, lim, step)
    p = np.zeros((len(t), 3)); p[:, 1] = y
    if axis == 0: p[:, 0] = t; p[:, 2] = z0
    else: p[:, 2] = t; p[:, 0] = x0
    if xlim is not None:
        keep = np.abs(p[:, 0]) <= xlim
        p, t = p[keep], t[keep]
    ins = field.evaluate(p) < 0
    if not ins.any(): return 0.0
    return float(t[ins].max() - t[ins].min())


def report(name):
    b, f, g = preset(name)
    sk = build_skeleton(b, f); F = build_field(b, f, sk); m = sk.marks
    H = b.height_m
    out = {}
    out["shoulder_breadth(biacromial-ish, max width y in shoulder band)"] = extent(F, sk["upperarm_l"][1]+0.02, 0, z0=-0.01, lim=0.4)
    yc = m["y_hip"] + 0.72*m["torso_len"]
    out["chest_width"] = extent(F, yc, 0, z0=0.0, xlim=0.2)
    out["chest_depth"] = extent(F, yc, 2, x0=0.06 if b.breast_size>0 else 0.0)
    yw = m["y_hip"] + 0.33*m["torso_len"]
    out["waist_width"] = extent(F, yw, 0, xlim=0.25); out["waist_depth"] = extent(F, yw, 2)
    yh = m["y_hip"] - 0.01
    out["hip_width"] = extent(F, yh, 0, xlim=0.3); out["hip_depth"] = extent(F, yh, 2, x0=0.05)
    out["neck_width"] = extent(F, m["y_chin"]-0.03, 0, z0=-0.02, xlim=0.12)
    out["neck_depth"] = extent(F, m["y_chin"]-0.03, 2, x0=0.0)
    hip = sk["thigh_l"]
    out["thigh_depth"] = extent(F, hip[1]-0.10, 2, x0=hip[0])
    kn = sk["calf_l"]; out["calf_depth"] = extent(F, kn[1]-0.12, 2, x0=kn[0]*0.97)
    O = m["y_chin"]; hh = m["head_h"]
    out["head_width"] = extent(F, O + 0.6*hh, 0, z0=-0.02, xlim=0.13)
    out["head_depth"] = extent(F, O + 0.62*hh, 2, x0=0.0)
    out["head_height"] = hh
    print(f"== {name}  H={H}")
    for k, v in out.items():
        print(f"  {k:55s} {v:.3f} m  ({v/H:.3f} H)")

for n in sys.argv[1:] or ["male", "female"]:
    report(n)
