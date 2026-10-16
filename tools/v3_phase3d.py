"""Phase 3D/3E analysis of the studio evidence (tools/studio_v3_identity.mjs writes the dumps, GLBs and screenshots).

1. Studio geometry vs the independent Python reference (v3/evaluate.py) for every identity preset and combination,
   at blink weights 0-1: max vertex error.
2. Blink per identity from the studio's own geometry: eyeball exposure and folded lid triangles at every weight.
3. Identity combined with body/face controls: triangle health of the studio geometry.
4. GLB exports: validator, the independent skinning check (walk frame 8), independent playback (tools/glb_playback.mjs)
   with the blink morph at 0/0.5/1 compared against the studio and the reference, and walk frames rendered with the
   blink applied (Python rasterizer, from the exported file only).
5. Sheets of the studio screenshots.
Writes examples/character_forge_aaa/humanity/v3_phase3d/phase3d_report.json and the sheets.
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
from forge_character_forge.v3 import evaluate as E, identity, metrics, model  # noqa: E402
from forge_character_forge.validate import validate_glb  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase3d"
D = OUT / "dumps"
SRC = model.body_surface()[0]
LID = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
WEIGHTS = (0, 0.25, 0.5, 0.75, 1)
PRESETS = ("neutral", "ID-A", "ID-B", "MERCY-INSPIRED")
MESHES = ("body", "eye_l", "eye_r", "basic_top", "basic_shorts", "brows", "lashes", "hair_shoulder")  # everything but the clear corneas
COLORS = {"eye_l": (0.75, 0.72, 0.68), "eye_r": (0.75, 0.72, 0.68), "basic_top": (0.33, 0.4, 0.5), "basic_shorts": (0.22, 0.24, 0.28),
          "brows": (0.1, 0.07, 0.05), "lashes": (0.05, 0.04, 0.03), "hair_shoulder": (0.16, 0.1, 0.06)}
GLBS = {"ID-A": "v3_identity_id_a", "ID-B": "v3_identity_id_b", "MERCY-INSPIRED": "v3_identity_mercy_inspired"}


def head_ids():
    rel = model.neutral() - identity.frame()
    m = (rel[:, 1] > -0.17) & (np.abs(rel[:, 0]) < 0.12) & (rel[:, 2] > -0.2)
    return np.intersect1d(np.nonzero(m)[0], model.body_vertex_ids())


def load(tag):
    return np.fromfile(D / f"{tag}.f4", "<f4").reshape(-1, 3).astype(float), json.loads((D / f"{tag}.json").read_text())


def reference(meta, w):
    """(scaled split-body positions, full unscaled base vertices, scale) from the Python reference evaluation."""
    ctl, iv = meta["params"], meta["identity"]["values"]
    v = E.shape(ctl, iv) + w * E.blink(ctl, iv)
    k = E.height_scale(v, ctl)
    return v[SRC] * k, v, k


def full_from_studio(body, v_ref, k):
    v = v_ref.copy()
    v[SRC] = body / k  # the studio's own skin; eyeballs placed by the (linear) helper vertices
    return v


def blink_series(prefix, weights):
    rows, err, base = {}, 0.0, None
    for w in weights:
        body, meta = load(f"{prefix}_blink{w}")
        ref, v_ref, k = reference(meta, w)
        err = max(err, float(np.abs(body - ref).max()))
        v = full_from_studio(body, v_ref, k)
        if base is None:
            base, open_px = v, metrics.eye_exposure_pixels(v)
        rows[str(w)] = {"exposure": round(metrics.eye_exposure_pixels(v) / open_px, 3),
                        "folded_lid_triangles": metrics.tri_quality(base, v, LID)["flipped"]}
    return {"studio_vs_reference_max_mm": round(err * 1000, 4), "blink": rows}, base, meta


def node(*args):
    r = subprocess.run(["node", *map(str, args)], capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1] if args[0].name == "glb_playback.mjs" else r.stdout)


def playback(glb, tag, frames, w, anim=None):
    out = OUT / "playback" / f"{tag}"
    a = [ROOT / "tools/glb_playback.mjs", glb, out, "--frames", ",".join(map(str, frames)), "--morph", f"blink_l={w},blink_r={w}",
         "--meshes", ",".join(MESHES)]
    if anim:
        a += ["--anim", anim]
    idx = node(*a)
    res = {}
    for f in frames:
        res[f] = {m: np.fromfile(out / f"{m}_f{f}.f4", "<f4").reshape(-1, 3) for m in idx["meshes"]}
    tris = {m: np.fromfile(out / f"{m}_idx.u4", "<u4").reshape(-1, 3) for m in idx["meshes"]}
    return res, tris, idx


def render_posed(pos, tris, cam, W=360, H=420):
    """Everything the GLB carries (clothed, as exported): refuses to draw a body without its garments."""
    if not any(m.startswith("basic_") for m in pos):
        raise RuntimeError("garments missing from the playback: public renders stay clothed")
    items = [DrawItem(pos["body"].astype(float), tris["body"].astype(np.int64), color=(0.62, 0.48, 0.41), roughness=0.55, specular=0.15, sss=0.6)]
    for m, c in COLORS.items():
        if m in pos:
            items.append(DrawItem(pos[m].astype(float), tris[m].astype(np.int64), color=c, roughness=0.6, specular=0.2, double_sided=True))
    return rasterize(items, cam, W=W, H=H, background=(0.8, 0.82, 0.85), ground_y=None)


def shots_sheet(names, cols, out, labels=None):
    tiles = []
    for i, n in enumerate(names):
        p = OUT / "shots" / f"{n}.png"
        if not p.is_file():
            continue
        tiles.append(label(np.asarray(Image.open(p).convert("RGB")), (labels or names)[i], size=14))
    if tiles:
        save(sheet(tiles, cols), OUT / out)


def main():
    rep = {"presets": {}, "combinations": {}, "glb": {}}
    H = head_ids()
    for p in PRESETS:
        r, _, _ = blink_series(f"preset_{p}", WEIGHTS)
        rep["presets"][p] = r
        print(p, json.dumps(r))
    for f in sorted(D.glob("combo_*_blink0.json")):
        tag = f.name[len("combo_"):-len("_blink0.json")]
        r, base, meta = blink_series(f"combo_{tag}", (0, 0.5, 1))
        ctl = meta["params"]
        q = metrics.tri_quality(E.shape(ctl, {}), base, H)
        r["head_health_vs_same_controls_without_identity"] = q
        r["identity_preset"], r["controls_changed"] = meta["identity"]["preset"], {k: v for k, v in ctl.items() if abs(v - E.control_defaults()[k]) > 1e-6}
        rep["combinations"][tag] = r
        print(tag, json.dumps(r))
    # GLB exports
    play_tiles = []
    for p, name in GLBS.items():
        glb = OUT / f"{name}.glb"
        g = {"bytes": glb.stat().st_size}
        v = validate_glb(glb, expect_profile="public")
        g["validate_glb"] = {"ok": v["ok"], "errors": v["errors"], "warnings": v["warnings"], "stats": v["stats"]}
        ind = node(ROOT / "tools/glb_independent_check.mjs", glb, "--anim", "walk", "--frame", "8")
        g["independent_skinning_walk8"] = {"ok": ind["ok"], "maxWeightSumError": ind["maxWeightSumError"], "animations": ind["animations"],
                                           "body_vertices_moved": ind["meshes"]["body"]["verticesMovedBySkinning"],
                                           "morph_targets": {m: x["morphTargets"] for m, x in ind["meshes"].items() if x["morphTargets"]}}
        studio_body, meta = load(f"export_{p}")
        rows, open_px, base = {}, None, None
        for w in (0, 0.5, 1):
            pos, _, idx = playback(glb, f"{name}_rest_w{w}", [0], w)
            body = pos[0]["body"].astype(float)
            ref, v_ref, k = reference(meta, w)
            vf = full_from_studio(body, v_ref, k)
            if base is None:
                base, open_px = vf, metrics.eye_exposure_pixels(vf)
            rows[str(w)] = {"glb_vs_studio_max_mm": round(float(np.abs(body - studio_body).max() * 1000), 4) if w == 0 else None,
                            "glb_vs_reference_max_mm": round(float(np.abs(body - ref).max() * 1000), 4),
                            "exposure": round(metrics.eye_exposure_pixels(vf) / open_px, 3),
                            "folded_lid_triangles": metrics.tri_quality(base, vf, LID)["flipped"],
                            "morphs_applied": idx["meshes"]["body"]["morphs_applied"]}
        g["rest_blink"] = rows
        walk = {}
        for w, frames in ((0, [0, 20]), (1, [10])):
            pos, tris, idx = playback(glb, f"{name}_walk_w{w}", frames, w, anim="walk")
            for fr in idx["frames"]:
                b = pos[fr["frame"]]["body"]
                walk[fr["frame"]] = {"blink": w, "head_world": [round(x, 4) for x in fr["head_world"]], "finite": bool(np.isfinite(b).all()),
                                     "bbox_min": [round(float(x), 3) for x in b.min(0)], "bbox_max": [round(float(x), 3) for x in b.max(0)]}
                hw = np.array(fr["head_world"])
                close = fr["frame"] == 10
                cam = (Camera(yaw_deg=20, pitch_deg=4, target=tuple(hw + [0, 0.01, 0.06]), distance=0.52, fov_deg=26) if close else
                       Camera(yaw_deg=40, pitch_deg=4, target=(hw[0], 0.86, hw[2]), distance=4.6, fov_deg=26))
                play_tiles.append((p, fr["frame"], label(render_posed(pos[fr["frame"]], tris, cam), f"{p} GLB walk f{fr['frame']} blink {w}", size=13)))
        heads = [np.array(walk[f]["head_world"]) for f in (0, 10, 20)]
        g["walk_playback"] = {"frames": walk, "head_travel_m": round(float(np.linalg.norm(heads[2] - heads[0])), 3)}
        rep["glb"][p] = g
        print(p, json.dumps({k: g[k] for k in ("validate_glb", "rest_blink", "walk_playback")})[:1500])
    play_tiles.sort(key=lambda t: (list(GLBS).index(t[0]), t[1]))
    save(sheet([t[2] for t in play_tiles], 3), OUT / "glb_playback_sheet.png")
    shots_sheet([f"face_{p}_{y}" for p in PRESETS for y in (0, 35, 90)], 3, "studio_faces_sheet.png",
                [f"{p}: {['front', 'three-quarter', 'profile'][i]}" for p in PRESETS for i in range(3)])
    shots_sheet([f"bald_{p}_{y}" for y in (0, 35, 90) for p in PRESETS], 4, "studio_faces_bald_sheet.png",
                [f"{p}: {v} (hair style bald)" for v in ("front", "three-quarter", "profile") for p in PRESETS])
    shots_sheet([f"blink_{p}_{w}" for p in GLBS for w in (0, 0.5, 1)], 3, "studio_blink_sheet.png",
                [f"{p}: blink {w}" for p in GLBS for w in (0, 0.5, 1)])
    shots_sheet([f"walk_blink_{p}" for p in GLBS], 3, "studio_walk_blink_sheet.png", [f"{p}: walk frame 10, blinking" for p in GLBS])
    (OUT / "phase3d_report.json").write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
