"""Mercy face refinement: Mercy-inspired (Phase 3C) vs Mercy-inspired (refined), both on the female body preset with
the preset's own controls, as the Studio applies them.

1. Mesh health of the head (flipped and degenerate triangles, lids inside the cornea) under eyelid fit 1 and fit 2.
2. Blink quality through the Studio path (blink_quality.summary): closure, folds, lid in the eye, lashes.
3. Simple proportions from the bald geometry (eye opening, lower face, nose, lips vs chin in profile).
4. With <studio-dir> (tools/studio_v3_mercy_refined.mjs output): Studio geometry vs the Python reference at blink
   0 / 0.35 / 1, GLB validation, and sheets of the Studio screenshots.
5. CPU review sheets: bald front / three-quarter / profile, eye close-ups open / half-lidded (0.35) / closed.
usage: python3 tools/v3_mercy_refined.py <outdir> [<studio-dir>]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from forge_character_forge.params import preset  # noqa: E402
from forge_character_forge.render import Camera, label, rasterize, save, sheet  # noqa: E402
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, identity_dna as I, metrics, mh, model  # noqa: E402
from forge_character_forge.validate import validate_glb  # noqa: E402
from identity_proof import head_items, health  # noqa: E402

PRESETS = {"MERCY-INSPIRED": "Mercy-inspired (Phase 3C)", "MERCY-REFINED": "Mercy-inspired (refined)"}
BG = (0.78, 0.8, 0.83)


def controls(name):
    b, f, _ = preset("female")
    c = {k: float(getattr(b if k.startswith("body.") else f, k.split(".")[1])) for k in E.control_defaults()}
    return {**c, **I.presets()[name]["controls"]}


def eye_mid(v):
    return np.mean([model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"], 0)


def proportions(v):
    """mm, relative to the eyeball-centre midpoint; midline profile from the bald body surface (approximate)."""
    em = eye_mid(v)
    body = model.body_vertex_ids()
    p = v[body] - em
    mid = p[(np.abs(p[:, 0]) < 0.002) & (p[:, 2] > 0.02) & (p[:, 1] < 0.0) & (p[:, 1] > -0.16)]
    nose = mid[np.argmax(mid[:, 2])]
    below = mid[mid[:, 1] < nose[1] - 0.012]
    chin_y = below[:, 1].min() if len(below) else np.nan
    span = nose[1] - 0.012 - chin_y
    lips = below[below[:, 1] > chin_y + 0.55 * span]
    chin = below[below[:, 1] < chin_y + 0.35 * span]
    return {"lower_face_eye_to_chin_mm": round(float(-chin_y * 1000), 2), "nose_tip_projection_mm": round(float(nose[2] * 1000), 2),
            "lips_ahead_of_chin_mm": round(float((lips[:, 2].max() - chin[:, 2].max()) * 1000), 2)}


def tile(v, cam, text, W=300, H=340):
    return label(rasterize(head_items(v), cam, W=W, H=H, background=BG, ground_y=None), text, size=12)


def main():
    out = Path(sys.argv[1]).resolve()
    studio = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    out.mkdir(parents=True, exist_ok=True)
    v0 = model.neutral()
    rep = {"presets": {}, "values": {n: I.presets()[n] for n in PRESETS}}
    geo = {}
    for name, lab in PRESETS.items():
        ctl, iv = controls(name), I.presets()[name]["values"]
        r = {"controls": {k: ctl[k] for k in ("body.femininity", "face.eye_size")}}
        for fit in (1, 2):
            with E.fit(fit):
                v = E.shape(ctl, iv)
            r[f"health_fit{fit}"] = health(v0, v)
        v = E.shape(ctl, iv)
        d = E.blink(ctl, iv)
        r["blink"] = Q.summary(Q.measure(v, d))
        r["eye_exposure_px_open"] = int(metrics.eye_exposure_pixels(v))
        r["proportions"] = proportions(v)
        r["preset_affinity"] = {k: round(a, 3) for k, a in I.preset_affinity(iv).items() if a}
        rep["presets"][name] = r
        geo[name] = (v, d)
        print(name, json.dumps({k: r[k] for k in ("proportions", "eye_exposure_px_open")}), flush=True)

    # review sheets: identical cameras on the eye midpoint, both faces aligned there
    target = tuple(eye_mid(v0) + [0, -0.03, 0])
    rows = []
    for name, lab in PRESETS.items():
        v, _ = geo[name]
        v = v + (eye_mid(v0) - eye_mid(v))
        for view, yaw in (("front", 0), ("three-quarter", 35), ("profile", 90)):
            rows.append(tile(v, Camera(yaw_deg=yaw, pitch_deg=2, target=target, distance=0.42, fov_deg=26), f"{lab}: {view}"))
    save(sheet(rows, 3), out / "bald_current_vs_refined.jpg")
    rows = []
    for name, lab in PRESETS.items():
        v, d = geo[name]
        sh = eye_mid(v0) - eye_mid(v)
        for w, wl in ((0, "open"), (0.35, "half-lidded 0.35"), (1, "closed")):
            cam = Camera(yaw_deg=12, pitch_deg=2, target=tuple(eye_mid(v0) + [0, 0.005, 0]), distance=0.2, fov_deg=26)
            rows.append(tile(v + w * d + sh, cam, f"{lab}: {wl}", W=360, H=240))
    save(sheet(rows, 3), out / "eyes_blink_current_vs_refined.jpg")

    if studio:
        sd = studio / "dumps"
        src = model.body_surface()[0]
        rep["studio"] = {"checks": json.loads((studio / "studio_checks.json").read_text())["checks"], "vs_reference_max_mm": {}, "glb": {}}
        for name in PRESETS:
            for w in (0, 0.35, 1):
                body = np.fromfile(sd / f"{name}_blink{w}.f4", "<f4").reshape(-1, 3).astype(float)
                meta = json.loads((sd / f"{name}_blink{w}.json").read_text())
                ctl, iv = meta["params"], meta["identity"]["values"]
                with E.fit(meta.get("lidFit", 1)):
                    v = E.shape(ctl, iv) + w * E.blink(ctl, iv)
                k = E.height_scale(v, ctl)
                rep["studio"]["vs_reference_max_mm"][f"{name} blink {w}"] = round(float(np.abs(body - v[src] * k).max() * 1000), 4)
            g = studio / f"v3_identity_{name.lower().replace('-', '_')}.glb"
            val = validate_glb(g)
            rep["studio"]["glb"][name] = {"errors": val.get("errors"), "stats": val.get("stats"), "bytes": g.stat().st_size}
        for kind, shots, cols in (("bald", [f"bald_{{}}_{y}" for y in (0, 35, 90)], 3),
                                  ("eyes", [f"eyes_{{}}_{w}" for w in (0, 0.35, 1)], 3),
                                  ("hair", [f"hair_{{}}_{y}" for y in (0, 35)], 2)):
            tiles = [label(np.asarray(Image.open(studio / "shots" / f"{s.format(n)}.png").convert("RGB")), f"{PRESETS[n]}: {s.split('_', 2)[-1].replace('{}_', '')}", size=13)
                     for n in PRESETS for s in shots]
            save(sheet(tiles, cols), out / f"studio_{kind}.jpg")
    (out / "mercy_refined_report.json").write_text(json.dumps(rep, indent=1))
    print("wrote", out / "mercy_refined_report.json")


if __name__ == "__main__":
    main()
