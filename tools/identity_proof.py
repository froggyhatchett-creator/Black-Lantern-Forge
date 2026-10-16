"""Phase 3B proof: two Forge identities on the same v3 topology, bald, neutral material, identical cameras and light.

Writes examples/character_forge_aaa/humanity/v3_phase3/: identity_sheet.png (rows: neutral, ID-A, ID-B; columns:
front, left profile, right profile, three-quarter, closed blink) and identity_report.json (geometry health, blink,
identity distances). Python software rasterizer: no studio, no materials, no hair (identity only).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet  # noqa: E402
from forge_character_forge.v3 import identity, metrics, mh, model, rig  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase3"
SKIN = (0.60, 0.47, 0.40)  # one neutral material for every head


def head_items(v):
    src, _, tris, _ = model.body_surface()
    ev = mh.fit_eyes(v)
    items = [DrawItem(v[src], tris, color=SKIN, roughness=0.55, specular=0.15, sss=0.6)]
    for s in "lr":
        ids, t = model.eye_parts()[f"eye_{s}"]
        q = ev[ids]
        c, _ = model.sphere_fit(q)
        d = (q - c) / np.linalg.norm(q - c, axis=1, keepdims=True)
        ang = np.arccos(np.clip(d[:, 2], -1, 1))
        col = np.where((ang < 0.40)[:, None], [0.16, 0.10, 0.06], [0.82, 0.80, 0.76])
        col[ang < 0.16] = 0.02
        items.append(DrawItem(q, t, colors=col, roughness=0.2, specular=0.5, double_sided=True))
    return items


def cams(E):
    t = tuple(E + np.array([0, -0.035, -0.03]))
    return {"front": Camera(yaw_deg=0, pitch_deg=2, target=t, distance=0.75, fov_deg=26),
            "left profile": Camera(yaw_deg=90, pitch_deg=2, target=t, distance=0.75, fov_deg=26),
            "right profile": Camera(yaw_deg=-90, pitch_deg=2, target=t, distance=0.75, fov_deg=26),
            "three-quarter": Camera(yaw_deg=35, pitch_deg=2, target=t, distance=0.75, fov_deg=26)}


def head_mask(v):
    E = identity.frame()
    rel = model.neutral() - E
    return (rel[:, 1] > -0.17) & (np.abs(rel[:, 0]) < 0.12) & (rel[:, 2] > -0.2)


def health(v0, v):
    src, _, tris, _ = model.body_surface()
    body = model.body_vertex_ids()
    head = np.intersect1d(np.nonzero(head_mask(v0))[0], body)
    q = metrics.tri_quality(v0, v, head)
    t = src[tris]
    t = t[np.isin(t, head).all(1)]
    ang = []
    for k in range(3):
        a, b, c = v[t[:, k]], v[t[:, (k + 1) % 3]], v[t[:, (k + 2) % 3]]
        u, w = b - a, c - a
        ang.append(np.degrees(np.arccos(np.clip((u * w).sum(1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(w, axis=1) + 1e-15), -1, 1))))
    ang = np.min(ang, 0)
    nb = model._neighbours()
    idx = [i for i in head if i in nb]
    lap = np.array([np.linalg.norm(v[list(nb[i])].mean(0) - v[i]) for i in idx])
    lap0 = np.array([np.linalg.norm(v0[list(nb[i])].mean(0) - v0[i]) for i in idx])
    # eyelids stay on the eyeballs: lid vertices inside the cornea sphere, and the eyeball centre vs the eye joint
    inside = 0
    for s in "lr":
        cc, R = model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"cornea_{s}"][0]])
        lid = model.lid_region(s)
        inside += int((np.linalg.norm(v[lid] - cc, axis=1) < R * 0.985).sum())
    J = rig.joint_rest(v)
    ec = [model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"]
    eye_joint_err = max(np.linalg.norm(J[rig.NAMES.index(f"eye_{s}")] - c) for s, c in zip("lr", ec))
    return {**q, "min_angle_p1_deg": round(float(np.percentile(ang, 1)), 2), "degenerate_lt_2deg": int((ang < 2).sum()),
            "laplacian_mean_mm": round(float(lap.mean() * 1000), 3), "laplacian_mean_neutral_mm": round(float(lap0.mean() * 1000), 3),
            "laplacian_max_ratio_vs_neutral": round(float(np.percentile(lap / np.maximum(lap0, 1e-6), 99.9)), 2),
            "lid_vertices_inside_cornea": inside, "eye_joint_to_eyeball_centre_mm": round(float(eye_joint_err * 1000), 2)}


def aligned(v):
    """Head vertices relative to the eyeball-centre midpoint (pose-free comparison of shape)."""
    ec = [model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"]
    m = head_mask(model.neutral()) & np.isin(np.arange(len(v)), model.body_vertex_ids())
    return v[m] - (ec[0] + ec[1]) / 2


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    v0 = model.neutral()
    E = identity.frame()
    faces = {"neutral (v3 default)": v0, **{k: identity.identity_mesh(vals) for k, vals in identity.IDENTITIES.items()}}
    rep = {"identity_version": identity.IDENTITY_VERSION, "parameters": len(identity.KEYS), "faces": {}, "distances_mm": {}}
    tiles = []
    open_px = {}
    for name, v in faces.items():
        C = cams(E)
        for view, cam in C.items():
            tiles.append(label(rasterize(head_items(v), cam, W=330, H=380, background=(0.78, 0.8, 0.83), ground_y=None), f"{name}: {view}", size=13))
        d, fit = model.fit_blink(v)
        closed = v + d
        tiles.append(label(rasterize(head_items(closed), C["front"], W=330, H=380, background=(0.78, 0.8, 0.83), ground_y=None), f"{name}: closed blink", size=13))
        region = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
        open_px[name] = metrics.eye_exposure_pixels(v)
        half = metrics.eye_exposure_pixels(v + 0.5 * d) / open_px[name]
        rep["faces"][name] = {
            "health_vs_neutral": health(v0, v) if name != "neutral (v3 default)" else health(v0, v0),
            "blink": {**fit, "half_exposure": round(half, 3), "closed_quality": metrics.tri_quality(v, closed, region)},
            "displacement_mm": {"mean": round(float(np.linalg.norm(v - v0, axis=1)[head_mask(v0)].mean() * 1000), 2),
                                "p95": round(float(np.percentile(np.linalg.norm(v - v0, axis=1)[head_mask(v0)], 95) * 1000), 2),
                                "max": round(float(np.linalg.norm(v - v0, axis=1)[head_mask(v0)].max() * 1000), 2)},
        }
    names = list(faces)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            dd = np.linalg.norm(aligned(faces[names[i]]) - aligned(faces[names[j]]), axis=1)
            rep["distances_mm"][f"{names[i]} vs {names[j]}"] = {"mean": round(float(dd.mean() * 1000), 2), "p95": round(float(np.percentile(dd, 95) * 1000), 2)}
    rep["reference_distances_mm"] = {"MakeHuman female variants (identity_proof.py, 2026-10-15)": "0.0-2.8",
                                     "MakeHuman female vs male macro": "5.2-5.7",
                                     "earlier regional identity experiment (identity_regions.py)": "1.28 mean"}
    save(sheet(tiles, 5), OUT / "identity_sheet.png")
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "identity_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ("distances_mm", "seconds")}, indent=1))
    for n, f in rep["faces"].items():
        print(n, json.dumps({"health": f["health_vs_neutral"], "blink": f["blink"], "disp": f["displacement_mm"]}))


if __name__ == "__main__":
    main()
