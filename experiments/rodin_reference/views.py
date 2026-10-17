"""Phase 3: display the Rodin GLB with Forge's own renderer (forge_character_forge.render), beside the source artwork
and a native v3 character (ID-A, committed Phase 4A regression GLB, posed by tools/glb_playback.mjs) at true scale.
The Rodin mesh is untextured (its GLB has UVs but no images), so it renders in plain grey.

    python3 experiments/rodin_reference/views.py
Writes results/*.jpg. Needs source/base.glb and source/artwork.webp (both git-ignored).
"""
import json
import subprocess

import numpy as np
from PIL import Image

from glb_mesh import HERE, ROOT, load
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet

OUT = HERE / "results"
BG = (0.13, 0.13, 0.15)
GREY = (0.74, 0.74, 0.76)
NATIVE_GLB = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb"
NATIVE_MESHES = ("body", "eye_l", "eye_r", "basic_top", "basic_shorts", "brows", "lashes", "hair_shoulder")
COL = {"body": (0.8, 0.62, 0.52), "eye_l": (0.9, 0.9, 0.9), "eye_r": (0.9, 0.9, 0.9), "basic_top": (0.33, 0.4, 0.5),
       "basic_shorts": (0.22, 0.24, 0.28), "brows": (0.1, 0.07, 0.05), "lashes": (0.05, 0.04, 0.03), "hair_shoulder": (0.16, 0.1, 0.06)}


def art_tile(W, H, crop=None, text="Source artwork"):
    a = Image.open(HERE / "source" / "artwork.webp").convert("RGB")
    if crop:
        a = a.crop(crop)
    a.thumbnail((W, H))
    can = Image.new("RGB", (W, H), (18, 18, 20))
    can.paste(a, ((W - a.width) // 2, (H - a.height) // 2))
    return label(np.asarray(can), text, size=13)


def native_items():
    pb = OUT / "_native_playback"
    subprocess.run(["node", str(ROOT / "tools/glb_playback.mjs"), str(NATIVE_GLB), str(pb), "--frames", "0", "--meshes", ",".join(NATIVE_MESHES)],
                   check=True, capture_output=True)
    idx = json.loads((pb / "index.json").read_text())
    return [DrawItem(np.fromfile(pb / f"{m}_f0.f4", "<f4").reshape(-1, 3).astype(float),
                     np.fromfile(pb / f"{m}_idx.u4", "<u4").reshape(-1, 3).astype(np.int64), color=COL[m],
                     double_sided=m in ("brows", "lashes", "hair_shoulder")) for m in idx["meshes"]]


def grid(img, H_m, cy, step=0.1):
    img = img.copy()
    h = img.shape[0]
    for k in range(-int(H_m / step), int(H_m / step) + 1):
        r = int(round(h * (0.5 - (k * step) / H_m)))
        if 0 <= r < h:
            img[r] = (img[r] * 0.45 + np.array([220, 170, 60]) * 0.55).astype(np.uint8)
    return img


def main():
    OUT.mkdir(exist_ok=True)
    P, N, UV, F = load()
    rodin = [DrawItem(P, F, color=GREY, roughness=0.5, specular=0.3)]
    cy = (P[:, 1].max() + P[:, 1].min()) / 2
    # 1. four views
    tiles = [label(rasterize(rodin, Camera(yaw_deg=y, pitch_deg=3, target=(0, cy, 0), distance=6.6, fov_deg=20), W=480, H=760, background=BG),
                   f"Rodin GLB, untextured: {n}", size=13) for n, y in (("front", 0), ("three-quarter", 35), ("profile", 90), ("rear", 180))]
    save(sheet(tiles, 4), OUT / "rodin_four_views.jpg")
    # 2. artwork vs the closest views (the artwork is a slightly low, near-frontal view)
    tiles = [art_tile(480, 760)] + [label(rasterize(rodin, Camera(yaw_deg=y, pitch_deg=-4, target=(0, cy, 0), distance=6.6, fov_deg=20), W=480, H=760, background=BG),
                                          f"Rodin GLB, yaw {y}", size=13) for y in (-15, 0, 15)]
    save(sheet(tiles, 4), OUT / "artwork_vs_rodin.jpg")
    # 3. head: artwork face crop vs Rodin head
    hc = (-0.10, 1.69, 0.0)
    tiles = [art_tile(420, 460, crop=(370, 60, 650, 340), text="Source artwork: face")]
    tiles += [label(rasterize(rodin, Camera(yaw_deg=y, pitch_deg=p, target=hc, distance=0.9, fov_deg=22), W=420, H=460, background=BG, ground_y=None),
                    f"Rodin head: yaw {y}, pitch {p}", size=13) for y, p in ((0, -10), (25, -10), (90, 0))]
    save(sheet(tiles, 4), OUT / "artwork_vs_rodin_head.jpg")
    # 4. true-scale line-up with a native v3 character, 10 cm grid, orthographic
    nat = native_items()
    H_m = 2.0
    tiles = [art_tile(440, 900, text="Source artwork (not to scale)")]
    for y, n in ((0, "front"), (90, "profile")):
        cam = Camera(yaw_deg=y, pitch_deg=0, target=(0, H_m / 2, 0), distance=10, ortho_height=H_m)
        tiles.append(label(grid(rasterize(rodin, cam, W=440, H=900, background=BG, ground_y=None), H_m, H_m / 2), f"Rodin {n}: {P[:, 1].max():.2f} m as exported", size=13))
        tiles.append(label(grid(rasterize(nat, cam, W=440, H=900, background=BG, ground_y=None), H_m, H_m / 2), f"Forge v3 ID-A {n}: 1.66 m", size=13))
    save(sheet(tiles, 5), OUT / "lineup_true_scale.jpg")
    # 5. head with a 1 cm grid (landmark reading)
    Hm, gc = 0.40, 1.70
    tiles = [label(grid(rasterize(rodin, Camera(yaw_deg=y, pitch_deg=0, target=(-0.12, gc, 0), distance=5, ortho_height=Hm), W=600, H=600, background=BG, ground_y=None), Hm, gc, 0.01),
                   f"Rodin head {n}: grid 1 cm, centre y {gc} m", size=13) for y, n in ((0, "front"), (90, "profile"))]
    save(sheet(tiles, 2), OUT / "rodin_head_grid.jpg")
    print("wrote", sorted(p.name for p in OUT.glob("*.jpg")))


if __name__ == "__main__":
    main()
