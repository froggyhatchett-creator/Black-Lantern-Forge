"""Reference side of the Myth proof of concept: our independent GLB player, not Myth.

Poses the GLB with tools/glb_playback.mjs (independent glTF reader: sparse morphs, LBS skinning, clip sampling) and
rasterizes it with forge_character_forge/render.py (CPU), with the same cameras the Myth script uses. Writes:

  reference/cameras.json           frame list: camera (eye, target, vertical fov), pose, blink weight
  reference/<frame>_beauty.png     shaded image, all meshes (for side-by-side viewing)
  reference/<frame>_mask.png       silhouette of the measured meshes (strand cards excluded, see below)
  reference/metrics.json           per frame: silhouette pixels, visible-eyeball pixels, garment pixels

Measurements use one rule on both sides: render the frame twice, once without the meshes in question; the pixels that
change are those meshes' visible area. Strand cards (brows, lashes, hair) are hidden in measurement passes on both
sides: they are alpha-masked textures, which this CPU rasterizer does not cut out, so they would compare renderers,
not geometry. Run from the repository root with Forge's own Python (numpy, Pillow) and Node:

    python3 experiments/myth_poc/make_reference.py
"""
import json
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from forge_character_forge.render import Camera, DrawItem, rasterize  # noqa: E402

HERE = Path(__file__).resolve().parent
GLB = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb"
OUT = HERE / "reference"
W, H = 640, 480
BG = (0.0, 0.0, 0.0)
MESHES = ("body", "eye_l", "cornea_l", "eye_r", "cornea_r", "basic_top", "basic_shorts", "brows", "lashes", "hair_shoulder")
STRANDS = ("brows", "lashes", "hair_shoulder")
EYES = ("eye_l", "cornea_l", "eye_r", "cornea_r")
GARMENTS = ("basic_top", "basic_shorts")
COLORS = {"body": (0.62, 0.48, 0.41), "eye_l": (0.85, 0.85, 0.82), "eye_r": (0.85, 0.85, 0.82), "cornea_l": (0.8, 0.85, 0.9),
          "cornea_r": (0.8, 0.85, 0.9), "basic_top": (0.33, 0.4, 0.5), "basic_shorts": (0.22, 0.24, 0.28), "brows": (0.1, 0.07, 0.05),
          "lashes": (0.04, 0.03, 0.02), "hair_shoulder": (0.16, 0.1, 0.06)}


def write_png(path, rgb_or_gray):
    """Minimal PNG writer (8-bit, filter 0), readable by compare.py without Pillow."""
    a = np.ascontiguousarray(rgb_or_gray, np.uint8)
    h, w = a.shape[:2]
    ctype = 0 if a.ndim == 2 else {3: 2, 4: 6}[a.shape[2]]
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def pose(anim, frame, blink):
    """{mesh: (positions, triangles)} from the independent GLB player."""
    with tempfile.TemporaryDirectory() as td:
        cmd = ["node", str(ROOT / "tools/glb_playback.mjs"), str(GLB), td, "--frames", str(frame),
               "--morph", f"blink_l={blink},blink_r={blink}", "--meshes", ",".join(MESHES)]
        if anim:
            cmd += ["--anim", anim]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        out = {}
        for m in MESHES:
            p = np.fromfile(Path(td) / f"{m}_f{frame}.f4", "<f4").reshape(-1, 3).astype(float)
            t = np.fromfile(Path(td) / f"{m}_idx.u4", "<u4").reshape(-1, 3).astype(np.int64)
            out[m] = (p, t)
        return out


def render(geo, cam, meshes, shaded=True):
    items = []
    for m in meshes:
        p, t = geo[m]
        items.append(DrawItem(p, t, color=COLORS[m], roughness=0.55, specular=0.15, sss=0.6 if m == "body" else 0.0,
                              double_sided=m in STRANDS or m in GARMENTS))
    return rasterize(items, cam, W=W, H=H, background=BG, ground_y=None)


def camera_dict(eye_target, yaw, pitch, dist, fov):
    t = np.asarray(eye_target, float)
    y, p = np.radians(yaw), np.radians(pitch)
    eye = t + dist * np.array([np.sin(y) * np.cos(p), np.sin(p), np.cos(y) * np.cos(p)])  # render.Camera.basis
    return {"eye": eye.round(6).tolist(), "target": t.round(6).tolist(), "fov_deg": fov, "yaw_deg": yaw, "pitch_deg": pitch, "distance": dist}


def frames():
    rest = pose(None, 0, 0.0)
    eyes_c = np.concatenate([rest["eye_l"][0], rest["eye_r"][0]]).mean(0)
    allp = np.concatenate([rest[m][0] for m in MESHES])
    body_c = (allp.min(0) + allp.max(0)) / 2
    walk = pose("walk", 10, 0.0)
    walk_all = np.concatenate([walk[m][0] for m in MESHES])
    walk_c = (walk_all.min(0) + walk_all.max(0)) / 2
    out = []
    for yaw, tag in ((0, "front"), (35, "34")):
        out.append({"name": f"full_{tag}_rest", "anim": None, "frame": 0, "blink": 0.0, "camera": camera_dict(body_c, yaw, 3, 4.6, 26)})
        for b in (0.0, 0.5, 1.0):
            out.append({"name": f"face_{tag}_blink{b}", "anim": None, "frame": 0, "blink": b,
                        "camera": camera_dict(eyes_c + [0, -0.01, 0], yaw, 3, 0.38, 26)})
    out.append({"name": "full_34_walk10", "anim": "walk", "frame": 10, "blink": 0.0, "camera": camera_dict(walk_c, 35, 3, 4.6, 26)})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fl = frames()
    metrics = {}
    measured = [m for m in MESHES if m not in STRANDS]
    for f in fl:
        geo = pose(f["anim"], f["frame"], f["blink"])
        c = f["camera"]
        cam = Camera(yaw_deg=c["yaw_deg"], pitch_deg=c["pitch_deg"], target=tuple(c["target"]), distance=c["distance"], fov_deg=c["fov_deg"])
        write_png(OUT / f"{f['name']}_beauty.png", render(geo, cam, MESHES))
        base = render(geo, cam, measured).astype(int)
        mask = np.abs(base - np.array(BG) * 255).max(2) > 8
        no_eyes = render(geo, cam, [m for m in measured if m not in EYES]).astype(int)
        no_garm = render(geo, cam, [m for m in measured if m not in GARMENTS]).astype(int)
        write_png(OUT / f"{f['name']}_mask.png", (mask * 255).astype(np.uint8))
        metrics[f["name"]] = {"silhouette_px": int(mask.sum()),
                              "eye_px": int((np.abs(base - no_eyes).max(2) > 8).sum()),
                              "garment_px": int((np.abs(base - no_garm).max(2) > 8).sum())}
        print(f["name"], metrics[f["name"]], flush=True)
    (OUT / "cameras.json").write_text(json.dumps({"glb": str(GLB.relative_to(ROOT)), "size": [W, H], "background": BG,
                                                  "measured_meshes": measured, "strands_excluded": list(STRANDS),
                                                  "eye_meshes": list(EYES), "garment_meshes": list(GARMENTS), "frames": fl}, indent=1))
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
