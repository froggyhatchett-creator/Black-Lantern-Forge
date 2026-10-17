"""Before/after of the copied-weight edit: one bone's weights as a heat map at rest (from each file's own skin data),
the posed left leg in the run clip (independent player), and the posed difference.

    python3 render_weights.py <source.glb> <edited.glb> <bone> <out.jpg>
"""
import sys
import tempfile

import numpy as np

import rig_compare as R
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet
from render_rig import posed

BG = (0.42, 0.43, 0.46)


def heat(w):
    """0 -> dark blue, 0.5 -> green, 1 -> yellow/red."""
    return np.clip(np.c_[w * 1.6 - 0.3, 1.0 - np.abs(w - 0.5) * 1.6, 0.9 - w * 1.5], 0.04, 1.0)


def main():
    src, dst, bone, out = sys.argv[1:5]
    S, D = R.G(src), R.G(dst)
    tiles = []
    cam = Camera(yaw_deg=-55, pitch_deg=4, target=(0.12, 0.45, 0.0), distance=1.9, fov_deg=22)
    ws = {}
    for lab, gg in (("source", S), ("Blender copy, smoothed", D)):
        js = [gg.name(i) for i in gg.g["skins"][0]["joints"]]
        b = R.meshes(gg)["body"]
        w = R.weights_by_name(b, js)[:, js.index(bone)]
        ws[lab] = (b, w)
        tiles.append(label(rasterize([DrawItem(b["P"], b["F"], colors=heat(w))], cam, W=420, H=520, background=BG, ground_y=None), f"{lab}: '{bone}' weight at rest", size=12))
    (a, wa), (b, wb) = ws.values()
    m, _ = R.match(a, b)
    dw = np.abs(wa[m] - wb)
    tiles.append(label(rasterize([DrawItem(b["P"], b["F"], colors=heat(np.clip(dw / max(dw.max(), 1e-9), 0, 1)))], cam, W=420, H=520, background=BG, ground_y=None),
                       f"|weight change| (max {dw.max():.3f} = red)", size=12))
    with tempfile.TemporaryDirectory() as tmp:
        frames = [5, 10, 15]
        pa = posed(src, tmp, "a", "run", frames, {}, ["body"])
        pb = posed(dst, tmp, "b", "run", frames, {}, ["body"])
    for f in frames:
        Pa, Fa = pa[f]["body"]
        Pb, Fb = pb[f]["body"]
        e = np.linalg.norm(Pa[m] - Pb, axis=1)
        c = Camera(yaw_deg=-70, pitch_deg=4, target=tuple(Pb[np.argmax(e)]), distance=0.9, fov_deg=22)
        tiles.append(label(rasterize([DrawItem(Pa, Fa, color=(0.85, 0.66, 0.55))], c, W=420, H=520, background=BG, ground_y=None), f"source: run t = {f}/30 s", size=12))
        tiles.append(label(rasterize([DrawItem(Pb, Fb, color=(0.85, 0.66, 0.55))], c, W=420, H=520, background=BG, ground_y=None), f"smoothed copy: run t = {f}/30 s", size=12))
        tiles.append(label(rasterize([DrawItem(Pb, Fb, colors=heat(np.clip(e / 0.004, 0, 1)))], c, W=420, H=520, background=BG, ground_y=None),
                           f"posed difference (red = 4 mm), max {e.max() * 1000:.2f} mm", size=12))
    save(sheet(tiles, 3), out)


if __name__ == "__main__":
    main()
