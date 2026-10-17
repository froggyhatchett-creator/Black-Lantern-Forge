"""Evidence renders of Blender job outputs with Forge's own renderer (no Blender).

    python3 render_results.py roundtrip <job dir>      results/roundtrip_vs_source.jpg (+ per-pixel difference)
    python3 render_results.py simplify <job dir>       results/simplify_10pct_vs_source.jpg
    python3 render_results.py board <job dir> <tag>    results/board_extracted_<tag>.jpg, results/board_selection_<tag>.jpg
"""
import sys
from pathlib import Path

import numpy as np

import verify
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "rodin_reference" / "source" / "base.glb"
OUT = HERE / "results"
BG = (0.13, 0.13, 0.15)


def full(P, F, yaw, W=420, H=700, color=(0.74, 0.74, 0.76)):
    return rasterize([DrawItem(P, F, color=color)], Camera(yaw_deg=yaw, pitch_deg=3, target=(0, 0.95, 0), distance=6.6, fov_deg=20),
                     W=W, H=H, background=BG, ground_y=None)


def cut_edges(O, OF):
    """Open boundary edges of a mesh as thin red bars (welded)."""
    key, inv = verify.weld(O)
    Fw = inv[OF]
    E = np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), 1)
    u, c = np.unique(E, axis=0, return_counts=True)
    bd = u[c == 1]
    if not len(bd):
        return None
    s = 0.0015
    V, T = [], []
    for i, (a, b) in enumerate(bd):
        p, q = key[a], key[b]
        m = (p + q) / 2
        V.append([p, q, m + [0, s, 0], m - [0, s, 0], m + [s, 0, 0], m + [0, 0, s]])
        T.append(np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4], [0, 1, 5]]) + 6 * i)
    return DrawItem(np.concatenate(V), np.concatenate(T), color=(0.9, 0.1, 0.1), double_sided=True)


def main():
    mode, jd = sys.argv[1], Path(sys.argv[2])
    OUT.mkdir(exist_ok=True)
    S, SF, _ = verify.load_world(SRC)
    out = next((jd / "output").glob("*.glb"))
    O, OF, _ = verify.load_world(out)
    if mode == "roundtrip":
        tiles = []
        for yaw in (0, 90):
            a, b = full(S, SF, yaw), full(O, OF, yaw)
            diff = np.abs(a.astype(int) - b.astype(int)).max(2)
            d = np.stack([np.clip(diff * 20, 0, 255)] * 3, 2).astype(np.uint8)
            tiles += [label(a, f"source GLB, yaw {yaw}", size=13), label(b, f"Blender round trip, yaw {yaw}", size=13),
                      label(d, f"|difference| x20, max {int(diff.max())}/255, {int((diff > 8).sum())} px > 8", size=13)]
        save(sheet(tiles, 6), OUT / "roundtrip_vs_source.jpg")
    elif mode == "simplify":
        tiles = []
        for yaw in (0, 90):
            tiles += [label(full(S, SF, yaw), f"source, {len(SF):,} triangles, yaw {yaw}", size=13),
                      label(full(O, OF, yaw), f"Blender Decimate 10 %, {len(OF):,} triangles, yaw {yaw}", size=13)]
        cam = Camera(yaw_deg=0, pitch_deg=0, target=(-0.1, 1.68, 0), distance=6, ortho_height=0.35)
        for P_, F_, t in ((S, SF, "source"), (O, OF, "10 %")):
            tiles.append(label(rasterize([DrawItem(P_, F_, color=(0.74, 0.74, 0.76))], cam, W=420, H=420, background=BG, ground_y=None), f"head, {t}", size=13))
        save(sheet(tiles, 3), OUT / "simplify_10pct_vs_source.jpg")
    elif mode == "board":
        tag = sys.argv[3]
        ctr = (O.min(0) + O.max(0)) / 2
        cuts = cut_edges(O, OF)
        tiles = [label(rasterize([DrawItem(O, OF, color=(0.78, 0.7, 0.55))] + ([cuts] if cuts else []),
                                 Camera(yaw_deg=y, pitch_deg=0, target=tuple(ctr), distance=6, ortho_height=1.15), W=440, H=560, background=BG, ground_y=None),
                       f"extracted board ({tag}), yaw {y}; red = open cuts", size=12) for y in (0, 90, 180, 270)]
        save(sheet(tiles, 4), OUT / f"board_extracted_{tag}.jpg")
        kv = lambda k: np.ascontiguousarray(k).view([("", np.int64)] * 9).ravel()
        sel = np.isin(kv(verify.tri_keys(S, SF)[0]), kv(verify.tri_keys(O, OF)[0]))
        tiles = [label(rasterize([DrawItem(S, SF[~sel], color=(0.6, 0.6, 0.62)), DrawItem(S, SF[sel], color=(0.95, 0.45, 0.25))],
                                 Camera(yaw_deg=y, pitch_deg=0, target=(0.2, 1.05, 0.0), distance=6, ortho_height=1.3), W=520, H=640, background=BG, ground_y=None),
                       f"{tag} selection in context, yaw {y}", size=13) for y in (0, 60, 120, 270)]
        save(sheet(tiles, 4), OUT / f"board_selection_{tag}.jpg")


if __name__ == "__main__":
    main()
