"""Matched renders of a rigged GLB and its round trips: poses come from Forge's independent player
(tools/glb_playback.mjs), colours from each file's OWN materials (base colour texture sampled at the vertex UVs, times
the base colour factor), drawn with Forge's renderer. Strand cards are drawn solid (the renderer has no alpha mask).

    python3 render_rig.py <out prefix> <label>=<glb> [<label>=<glb> ...]
Writes <prefix>_rest.jpg, <prefix>_walk.jpg, <prefix>_run.jpg, <prefix>_blink.jpg, <prefix>_diff.jpg (first two files, |difference| x10).
"""
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import rig_compare as R
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet

ROOT = Path(__file__).resolve().parents[2]
BG = (0.42, 0.43, 0.46)


def colours(gg):
    """mesh name -> per-vertex linear colour from the file's own material."""
    out = {}
    for name, d in R.meshes(gg).items():
        n = gg.g["nodes"][d["node"]]
        p = gg.g["meshes"][n["mesh"]]["primitives"][0]
        mat = gg.g["materials"][p["material"]]
        pbr = mat.get("pbrMetallicRoughness", {})
        f = np.array(pbr.get("baseColorFactor", [1, 1, 1, 1])[:3])
        c = np.tile(f, (len(d["P"]), 1))
        t = pbr.get("baseColorTexture")
        if t is not None and "UV" in d and mat.get("alphaMode", "OPAQUE") == "OPAQUE":
            im = gg.g["images"][gg.g["textures"][t["index"]]["source"]]
            bv = gg.g["bufferViews"][im["bufferView"]]
            a = np.asarray(Image.open(io.BytesIO(gg.b[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]])).convert("RGB")) / 255.0
            h, w = a.shape[:2]
            uv = d["UV"]
            px = a[np.clip((uv[:, 1] * h).astype(int), 0, h - 1), np.clip((uv[:, 0] * w).astype(int), 0, w - 1)]
            c = (px ** 2.2) * f
        if "C" in d:
            c = c * d["C"][:, :3]
        out[name] = np.clip(c, 0, 1)
    return out


def posed(glb, tmp, tag, anim, frames, morph, names):
    o = Path(tmp) / tag
    args = ["node", str(ROOT / "tools/glb_playback.mjs"), str(glb), str(o), "--meshes", ",".join(names), "--frames", ",".join(map(str, frames))]
    if anim:
        args += ["--anim", anim]
    if morph:
        args += ["--morph", ",".join(f"{k}={v}" for k, v in morph.items())]
    subprocess.run(args, check=True, capture_output=True)
    return {f: {n: (np.fromfile(o / f"{n}_f{f}.f4", "<f4").reshape(-1, 3).astype(float), np.fromfile(o / f"{n}_idx.u4", "<u4").reshape(-1, 3).astype(np.int64))
                for n in names} for f in frames}


def items(geo, col, skip=()):
    return [DrawItem(P, F, colors=col[n], double_sided=n in ("brows", "lashes", "hair_shoulder")) for n, (P, F) in geo.items() if n not in skip]


def main():
    prefix = sys.argv[1]
    files = [a.split("=", 1) for a in sys.argv[2:]]
    gs = [(lab, R.G(p), p) for lab, p in files]
    names = [n for n in R.meshes(gs[0][1]) if n not in ("cornea_l", "cornea_r")]  # clear corneas would hide the eyes
    cols = [colours(g) for _, g, _ in gs]
    with tempfile.TemporaryDirectory() as tmp:
        rest = [posed(p, tmp, f"rest{k}", None, [0], {}, names)[0] for k, (_, _, p) in enumerate(gs)]
        walkf = [0, 8, 16, 24]
        walk = [posed(p, tmp, f"walk{k}", "walk", walkf, {}, names) for k, (_, _, p) in enumerate(gs)]
        runf = [0, 5, 10, 15]
        run = [posed(p, tmp, f"run{k}", "run", runf, {}, names) for k, (_, _, p) in enumerate(gs)]
        blinks = [0, 0.5, 1]
        blink = [[posed(p, tmp, f"blink{k}_{w}", None, [0], {"blink_l": w, "blink_r": w}, names)[0] for w in blinks] for k, (_, _, p) in enumerate(gs)]
    tiles, imgs = [], {}
    for yaw in (0, 35):
        for k, (lab, _, _) in enumerate(gs):
            im = rasterize(items(rest[k], cols[k]), Camera(yaw_deg=yaw, pitch_deg=3, target=(0, 0.85, 0), distance=5.2, fov_deg=22), W=360, H=640, background=BG, ground_y=0.0)
            imgs[("rest", yaw, k)] = im
            tiles.append(label(im, f"{lab}: rest, yaw {yaw}", size=12))
    save(sheet(tiles, len(gs)), f"{prefix}_rest.jpg")
    tiles = []
    for k, (lab, _, _) in enumerate(gs):
        for f in walkf:
            im = rasterize(items(walk[k][f], cols[k]), Camera(yaw_deg=60, pitch_deg=3, target=(0, 0.85, 0), distance=5.2, fov_deg=22), W=300, H=560, background=BG, ground_y=0.0)
            imgs[("walk", f, k)] = im
            tiles.append(label(im, f"{lab}: walk t = {f}/30 s", size=12))
    save(sheet(tiles, len(walkf)), f"{prefix}_walk.jpg")
    tiles = []
    for k, (lab, _, _) in enumerate(gs):
        for f in runf:
            im = rasterize(items(run[k][f], cols[k]), Camera(yaw_deg=60, pitch_deg=3, target=(0, 0.85, 0), distance=5.2, fov_deg=22), W=300, H=560, background=BG, ground_y=0.0)
            imgs[("run", f, k)] = im
            tiles.append(label(im, f"{lab}: run t = {f}/30 s", size=12))
    save(sheet(tiles, len(runf)), f"{prefix}_run.jpg")
    tiles = []
    for k, (lab, _, _) in enumerate(gs):
        for j, w in enumerate(blinks):
            head = rest[k]["body"][0]
            em = head[head[:, 1] > 1.45].mean(0)
            im = rasterize(items(blink[k][j], cols[k], skip=("hair_shoulder",)), Camera(yaw_deg=12, pitch_deg=2, target=(em[0], 1.535, em[2] + 0.05), distance=0.3, fov_deg=26),
                           W=360, H=240, background=BG, ground_y=None)
            imgs[("blink", w, k)] = im
            tiles.append(label(im, f"{lab}: blink {w}", size=12))
    save(sheet(tiles, len(blinks)), f"{prefix}_blink.jpg")
    tiles = []
    for key in [("rest", 0), ("rest", 35)] + [("walk", f) for f in walkf] + [("run", f) for f in runf] + [("blink", w) for w in blinks]:
        for k in range(1, len(gs)):
            a, b = imgs[key + (0,)], imgs[key + (k,)]
            dif = np.abs(a.astype(int) - b.astype(int)).max(2)
            d = np.stack([np.clip(dif * 10, 0, 255)] * 3, 2).astype(np.uint8)
            tiles.append(label(d, f"|{gs[0][0]} - {gs[k][0]}| x10, {key[0]} {key[1]}: max {int(dif.max())}, {int((dif > 16).sum())} px > 16", size=11))
    save(sheet(tiles, 2 * (len(gs) - 1)), f"{prefix}_diff.jpg")


if __name__ == "__main__":
    main()
