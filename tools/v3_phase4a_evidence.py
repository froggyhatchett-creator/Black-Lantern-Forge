"""Phase 4A evidence: studio vs Python reference parity, before/after sheets, GLB walk + blink playback before/after.

1. Parity: the studio's body and lash geometry (dumps written by tools/studio_v3_blink.mjs --dump) against the
   independent Python evaluation (v3/evaluate.py blink model 2, lash contact from v3/lash_contact.py) at blink 0, 0.5, 1.
2. Sheets from the real studio screenshots (identical cameras): before (Phase 3D build) vs after (this build).
3. GLB playback before/after: the Phase 3D ID-A export and this build's ID-A export, each played by the independent
   loader (tools/glb_playback.mjs) through the walk clip with the blink morph applied, rendered from the files only.
usage: python3 tools/v3_phase4a_evidence.py
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet  # noqa: E402
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, model  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a"
SRC = model.body_surface()[0]
CASES = ("neutral", "ID-A", "ID-B", "MERCY-INSPIRED", "MERCY-INSPIRED_eye0.8")
LABEL = {"neutral": "Neutral", "ID-A": "ID-A", "ID-B": "ID-B", "MERCY-INSPIRED": "Mercy-inspired",
         "MERCY-INSPIRED_eye0.8": "Mercy-inspired + eye size 0.8 (stress)"}


def parity():
    out = {}
    for tag in CASES:
        rows = {}
        for w in (0, 0.5, 1):
            name = f"blink_{tag}_{w}"
            meta = json.loads((OUT / "dumps" / f"{name}.json").read_text())
            body = np.fromfile(OUT / "dumps" / f"{name}.f4", "<f4").reshape(-1, 3)
            lashes = np.fromfile(OUT / "dumps" / f"{name}_lashes.f4", "<f4").reshape(-1, 3)
            ctl, iv = meta["params"], meta["identity"]["values"]
            v = E.shape(ctl, iv)
            d = E.blink(ctl, iv)
            k = E.height_scale(v, ctl)
            ref = ((v + w * d) * k)[SRC]
            vs, ds = v * k, d * k  # lashes are evaluated on the scaled body (their offsets are absolute)
            c0 = Q.lash_points(vs)
            lref = c0 + w * (Q.lash_closed(vs, ds) - c0)
            K = lref.shape[1]
            lst = lashes.reshape(-1, K, 2, 3).mean(2)
            rows[str(w)] = {"body_max_mm": round(float(np.abs(body - ref).max() * 1000), 4),
                            "lashes_max_mm": round(float(np.linalg.norm(lst - lref, axis=2).max() * 1000), 4)}
        out[tag] = rows
        print(tag, json.dumps(rows), flush=True)
    return out


def shots_sheet():
    for yaw in (10, 50):
        tiles = []
        for tag in CASES:
            for w in (0.5, 1):
                for when in ("before", "after"):
                    p = OUT / "shots" / f"{when}_{tag}_w{w}_y{yaw}.png"
                    if p.is_file():
                        tiles.append(label(np.asarray(Image.open(p).convert("RGB").crop((0, 40, 604, 460))),
                                           f"{LABEL[tag]}: blink {w}, {when}", size=14))
        save(sheet(tiles, 4), OUT / f"blink_before_after_yaw{yaw}.png")


def glb_walk():
    """Walk frame 10 with the blink at 0.5 and 1, from the before and after ID-A GLBs (face close-up)."""
    glbs = {"before (Phase 3D export)": ROOT / "examples/character_forge_aaa/humanity/v3_phase3d/v3_identity_id_a.glb",
            "after (this build's export)": OUT / "regression/v3_identity_id_a.glb"}
    meshes = ("body", "eye_l", "eye_r", "basic_top", "basic_shorts", "brows", "lashes")
    tiles, report = [], {}
    for when, glb in glbs.items():
        for w in (0.5, 1):
            od = OUT / "playback" / f"{'before' if when.startswith('before') else 'after'}_w{w}"
            r = subprocess.run(["node", str(ROOT / "tools/glb_playback.mjs"), str(glb), str(od), "--anim", "walk", "--frames", "10",
                                "--morph", f"blink_l={w},blink_r={w}", "--meshes", ",".join(meshes)], capture_output=True, text=True, check=True)
            idx = json.loads(r.stdout.strip().splitlines()[-1])
            pos = {m: np.fromfile(od / f"{m}_f10.f4", "<f4").reshape(-1, 3).astype(float) for m in idx["meshes"]}
            tris = {m: np.fromfile(od / f"{m}_idx.u4", "<u4").reshape(-1, 3).astype(np.int64) for m in idx["meshes"]}
            if not any(m.startswith("basic_") for m in pos):
                raise RuntimeError("garments missing: public renders stay clothed")
            items = [DrawItem(pos["body"], tris["body"], color=(0.62, 0.48, 0.41), roughness=0.55, specular=0.15, sss=0.6)]
            col = {"eye_l": (0.75, 0.72, 0.68), "eye_r": (0.75, 0.72, 0.68), "basic_top": (0.33, 0.4, 0.5), "basic_shorts": (0.22, 0.24, 0.28),
                   "brows": (0.1, 0.07, 0.05), "lashes": (0.04, 0.03, 0.02)}
            for m, c in col.items():
                if m in pos:
                    items.append(DrawItem(pos[m], tris[m], color=c, roughness=0.6, specular=0.2, double_sided=True))
            eye = pos["eye_l"].mean(0)
            cam = Camera(yaw_deg=25, pitch_deg=3, target=tuple(eye + [-0.01, 0.0, 0.0]), distance=0.12, fov_deg=26)
            tiles.append(label(rasterize(items, cam, W=420, H=300, background=(0.8, 0.82, 0.85), ground_y=None),
                               f"ID-A GLB, walk frame 10, blink {w}: {when}", size=13))
            report[f"{when} blink {w}"] = {"head_world": idx["frames"][0]["head_world"], "morphs": idx["meshes"]["body"]["morphs_applied"],
                                           "lash_morphs": idx["meshes"]["lashes"]["morphs_applied"]}
    save(sheet(tiles, 2), OUT / "glb_walk_blink_before_after.png")
    return report


def main():
    rep = {"parity": parity()}
    shots_sheet()
    rep["glb_walk"] = glb_walk()
    (OUT / "phase4a_evidence.json").write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
