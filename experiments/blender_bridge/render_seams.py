"""Seam evidence for weight-edit variants: (1) the inner thigh at run t = 10/30 s on a white background, so a crack
shows as light lines; (2) the posed seam opening as a heat map (red = 1 mm); (3) the change of the exported vertex
normals against the source as a heat map (red = 30 degrees). Forge renderer + independent player; no Blender.

    python3 render_seams.py <source.glb> <out.jpg> <label>=<edited.glb> [...]
"""
import sys
import tempfile

import numpy as np

import rig_compare as R
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet
from render_rig import posed
from render_weights import heat


def measure(a, p, tmp, tag):
    b = R.meshes(R.G(p))["body"]
    m, _ = R.match(a, b)
    P, F = posed(p, tmp, tag, "run", [10], {}, ["body"])[10]["body"]
    key, inv = np.unique(np.round(b["P"] * 1e6).astype(np.int64), axis=0, return_inverse=True)
    inv = inv.ravel()
    centre = np.zeros((len(key), 3))
    np.add.at(centre, inv, P)
    centre /= np.bincount(inv)[:, None]
    gap = np.linalg.norm(P - centre[inv], axis=1) * 2
    ang = np.degrees(np.arccos(np.clip((a["N"][m] * b["N"]).sum(1) / np.linalg.norm(b["N"], axis=1), -1, 1)))
    return b, P, F, gap, ang


def main():
    src, out = sys.argv[1], sys.argv[2]
    variants = [a.split("=", 1) for a in sys.argv[3:]]
    a = R.meshes(R.G(src))["body"]
    with tempfile.TemporaryDirectory() as tmp:
        data = [measure(a, p, tmp, f"v{k}") for k, (_, p) in enumerate(variants)]
    # cameras aimed at measured locations: the widest seam opening (first variant that has one) and the largest normal
    # change (first variant that has one); every row uses the same two cameras
    gk = max(range(len(data)), key=lambda k: data[k][3].max())
    nk = max(range(len(data)), key=lambda k: data[k][4].max())
    def facing(P, F, i):
        """yaw/pitch that look at vertex i along its (area-weighted) surface normal."""
        fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        near = np.linalg.norm(P[F].mean(1) - P[i], axis=1) < 0.02
        n = fn[near].sum(0)
        n /= np.linalg.norm(n)
        return float(np.degrees(np.arctan2(n[0], n[2]))), float(np.degrees(np.arcsin(np.clip(n[1], -1, 1))))
    gi = int(np.argmax(data[gk][3]))
    crack_at = data[gk][1][gi]
    cy, cp = facing(data[gk][1], data[gk][2], gi)
    ni = int(np.argmax(data[nk][4]))
    normal_at = data[nk][0]["P"][ni]
    ny, np_ = facing(data[nk][0]["P"], data[nk][0]["F"], ni)
    cam_crack = Camera(yaw_deg=cy, pitch_deg=cp, target=tuple(crack_at), distance=0.12, fov_deg=24)
    cam_crack_heat = Camera(yaw_deg=cy, pitch_deg=cp, target=tuple(crack_at), distance=0.3, fov_deg=24)
    cam_norm = Camera(yaw_deg=ny, pitch_deg=np_, target=tuple(normal_at), distance=0.25, fov_deg=24)
    print("crack at", crack_at.round(3), "view", round(cy), round(cp), "| normal change at", normal_at.round(3), "view", round(ny), round(np_))
    tiles = []
    for (lab, _), (b, P, F, gap, ang) in zip(variants, data):
        tiles.append(label(rasterize([DrawItem(P, F, color=(0.62, 0.48, 0.42))], cam_crack, W=380, H=420, background=(1.0, 1.0, 1.0), ground_y=None),
                           f"{lab}: widest seam, run t = 10/30 s (white = background)", size=11))
        tiles.append(label(rasterize([DrawItem(P, F, colors=heat(np.clip(gap / 1e-3, 0, 1)))], cam_crack_heat, W=380, H=420, background=(0.42, 0.43, 0.46), ground_y=None),
                           f"seam opening (red = 1 mm): max {gap.max() * 1000:.2f} mm, {int((gap > 1e-4).sum())} vertices > 0.1 mm", size=11))
        tiles.append(label(rasterize([DrawItem(b["P"], b["F"], colors=heat(np.clip(ang / 30, 0, 1)))], cam_norm, W=380, H=420, background=(0.42, 0.43, 0.46), ground_y=None),
                           f"normal change vs source (red = 30 deg): {int((ang > 1).sum())} vertices > 1 deg, max {ang.max():.1f}", size=11))
    save(sheet(tiles, 3), out)


if __name__ == "__main__":
    main()
