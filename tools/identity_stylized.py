"""Phase 3C: Mercy-inspired stylised identity vs the neutral v3 default (bald, neutral material, identical cameras).

Writes examples/character_forge_aaa/humanity/v3_phase3c/: stylized_sheet.png (front, left profile, right profile,
three-quarter), stylized_eyes.png (eye close-ups: open, half-lidded, 50 % blink, closed), stylized_reference.png
(REF-001 beside the front view, for orientation only) and stylized_report.json.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from forge_character_forge.render import Camera, label, rasterize, save, sheet  # noqa: E402
from forge_character_forge.v3 import identity, metrics, mh, model  # noqa: E402
from identity_proof import aligned, cams, head_items, head_mask, health  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase3c"
STATES = (("open", 0.0), ("half-lidded", 0.35), ("50% blink", 0.5), ("closed", 1.0))
BG = (0.78, 0.8, 0.83)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    v0 = model.neutral()
    E = identity.frame()
    vid = identity.identity_mesh(identity.STYLIZED["MERCY-INSPIRED"])
    ctl = sum(model.control_delta(k, "hi")[0] * (val - 0.5) / 0.5 for k, val in identity.STYLIZED_CONTROLS["MERCY-INSPIRED"].items())
    faces = {"neutral (v3 default)": v0, "Mercy-inspired": vid + ctl, "identity only (no femininity control)": vid}

    def eye_mid(v):
        return np.mean([model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"], 0)
    # rigid alignment on the eyeball-centre midpoint (femininity also changes body height): same framing, shape only
    faces = {n: v + (eye_mid(v0) - eye_mid(v)) for n, v in faces.items()}
    rep = {"identity_version": identity.IDENTITY_VERSION, "values": identity.STYLIZED["MERCY-INSPIRED"],
           "controls": identity.STYLIZED_CONTROLS["MERCY-INSPIRED"], "faces": {}}
    tiles, eyes = [], []
    for name, v in faces.items():
        for view, cam in cams(E).items():
            tiles.append(label(rasterize(head_items(v), cam, W=330, H=380, background=BG, ground_y=None), f"{name}: {view}", size=13))
        d, fit = model.fit_blink(v)
        region = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
        o = metrics.eye_exposure_pixels(v)
        states = {}
        for tag, w in STATES:
            vv = v + w * d
            states[tag] = {"blink_weight": w, "eyeball_exposure": round(metrics.eye_exposure_pixels(vv) / o, 4),
                           **({"lid_quality": metrics.tri_quality(v, vv, region)} if w else {})}
            eyes.append(label(rasterize(head_items(vv), Camera(yaw_deg=15, pitch_deg=3, target=tuple(E + [0, 0.004, 0]), distance=0.2, fov_deg=26),
                                        W=420, H=260, background=BG, ground_y=None), f"{name}: {tag}", size=13))
        disp = np.linalg.norm(v - v0, axis=1)[head_mask(v0)]
        rep["faces"][name] = {"health_vs_neutral": health(v0, v), "blink_fit": fit, "states": states, "open_eye_pixels": o,
                              "displacement_mm": {"mean": round(float(disp.mean() * 1000), 2), "max": round(float(disp.max() * 1000), 2)}}
    rep["shape_distance_mm"] = {}
    for n in ("Mercy-inspired", "identity only (no femininity control)"):
        dd = np.linalg.norm(aligned(faces["neutral (v3 default)"]) - aligned(faces[n]), axis=1)
        rep["shape_distance_mm"][n] = {"mean": round(float(dd.mean() * 1000), 2), "p95": round(float(np.percentile(dd, 95) * 1000), 2)}
    save(sheet(tiles, 4), OUT / "stylized_sheet.png")
    save(sheet(eyes, 4), OUT / "stylized_eyes.png")
    # close front views, and REF-001 beside them for orientation (illustration; not a likeness target)
    close = [label(rasterize(head_items(v), Camera(yaw_deg=y, pitch_deg=2, target=tuple(E + [0, -0.04, 0]), distance=0.48, fov_deg=26),
                             W=420, H=500, background=BG, ground_y=None), f"{n} yaw {y}", size=14) for n, v in faces.items() for y in (0, 30)]
    ref = Image.open(ROOT / "examples/character_forge_aaa/benchmarks/REF-001_mercy.webp").convert("RGB").crop((500, 300, 800, 660)).resize((420, 500))
    close.append(label(np.asarray(ref), "REF-001 (illustration, orientation only)", size=14))
    save(sheet(close, 4), OUT / "stylized_closeups.png")
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "stylized_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ("shape_distance_mm", "seconds")}))
    for n, f in rep["faces"].items():
        print(n, json.dumps({"health": f["health_vs_neutral"], "fit": f["blink_fit"], "states": {k: s["eyeball_exposure"] for k, s in f["states"].items()},
                             "lid_flips": {k: s.get("lid_quality", {}).get("flipped") for k, s in f["states"].items()}, "disp": f["displacement_mm"]}))


if __name__ == "__main__":
    main()
