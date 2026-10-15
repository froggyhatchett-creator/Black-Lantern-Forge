"""Fast part preview: mesh only a box of the field (head / feet / hand) and render it."""
import sys, numpy as np
sys.path.insert(0, ".")
from forge_character_forge import mesher
from forge_character_forge.params import preset
from forge_character_forge.skeleton import build_skeleton
from forge_character_forge.anatomy import build_field
from forge_character_forge.render import DrawItem, Camera, rasterize, sheet, save, label


def sphere(c, r, n=24):
    th, ph = np.meshgrid(np.linspace(0, np.pi, n), np.linspace(0, 2 * np.pi, 2 * n, endpoint=False), indexing="ij")
    v = np.stack([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)], -1).reshape(-1, 3) * r + c
    tris = []
    for i in range(n - 1):
        for j in range(2 * n):
            a, b = i * 2 * n + j, i * 2 * n + (j + 1) % (2 * n)
            c2, d = a + 2 * n, b + 2 * n
            tris += [(a, b, d), (a, d, c2)]
    return v, np.array(tris)


def clipped(F, lo, hi):
    lo2, hi2 = lo + 0.01, hi - 0.01
    return lambda p: np.maximum(F.evaluate(p), np.max(np.maximum(lo2 - p, p - hi2), axis=1))


def main(part="head", name="neutral", out="part.png"):
    b, f, g = preset(name)
    sk = build_skeleton(b, f); F = build_field(b, f, sk)
    m = sk.marks
    items = []
    if part == "head":
        lo = np.array([-0.13, m["y_chin"] - 0.04, -0.15]); hi = np.array([0.13, m["y_crown"] + 0.02, 0.17])
        v, t = mesher.mesh_box(clipped(F, lo, hi), lo, hi, 0.0022)
        cams = [Camera(yaw_deg=y, pitch_deg=2, target=(0, m["y_chin"] + 0.12, 0), distance=0.75, fov_deg=24) for y in (0, 30, 90)]
        for lab in "lr":
            ev, et = sphere(sk[f"eye_{lab}"], m["eye_r"])
            col = np.tile([0.85, 0.85, 0.82], (len(ev), 1))
            front = (ev - sk[f"eye_{lab}"])[:, 2] / m["eye_r"]
            col[front > 0.80] = [0.25, 0.15, 0.08]; col[front > 0.93] = [0.02, 0.02, 0.02]
            items.append(DrawItem(ev, et, colors=col, roughness=0.2, specular=0.6))
    elif part == "feet":
        lo = np.array([-0.3, -0.03, -0.15]); hi = np.array([0.3, 0.25, 0.3])
        v, t = mesher.mesh_box(clipped(F, lo, hi), lo, hi, 0.004)
        cams = [Camera(yaw_deg=y, pitch_deg=12, target=(0.1, 0.06, 0.05), distance=1.0, fov_deg=24) for y in (0, 45, 90)]
    else:
        wr = sk["hand_l"]
        lo = wr - 0.16; hi = wr + 0.16
        v, t = mesher.mesh_box(clipped(F, lo, hi), lo, hi, 0.0022)
        cams = [Camera(yaw_deg=y, pitch_deg=0, target=tuple(wr + np.array([0.04, -0.05, 0])), distance=0.6, fov_deg=24) for y in (0, 70, 180)]
    items.insert(0, DrawItem(v, t, color=(0.78, 0.57, 0.47), sss=1.0, roughness=0.5))
    ims = [rasterize(items, c, W=420, H=480) for c in cams]
    save(sheet(ims, 3), out)
    print(part, len(v), "verts")

if __name__ == "__main__":
    main(*sys.argv[1:])
