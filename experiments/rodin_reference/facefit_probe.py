"""Probe (not a pipeline): can the Rodin face drive the v3 identity basis?

A native v3 face (female body preset, identity 0; front face only, lids excluded because the Rodin eyes are sculpted
shut) is aligned to the Rodin head, then the 36 linear identity parameters are solved by ridge least squares
(point-to-plane), alternating with rigid ICP, 4 rounds. Writes results/facefit_<mode>.json and .jpg. Nothing is
saved as a preset or DNA.

  landmarks   start from three landmarks read off the Rodin mesh (nasal bridge at eye height, nose tip, chin);
              scale fixed by them
  free        no landmarks: similarity ICP from the nose tip, scale free (kept to show how it fails)

    python3 experiments/rodin_reference/facefit_probe.py landmarks|free
"""
import json
import sys

import numpy as np

from glb_mesh import HERE, ROOT, load
from forge_character_forge.params import preset
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet
from forge_character_forge.v3 import evaluate as E, identity, identity_dna as I, mh, model

sys.path.insert(0, str(ROOT / "tools"))
from identity_proof import head_items  # noqa: E402

LANDMARKS = np.array([[-0.100, 1.721, -0.013], [-0.101, 1.667, 0.000], [-0.103, 1.600, -0.036]])  # bridge, nose tip, chin
TRIM = 75  # percentile of correspondences kept (hair crosses the face)


def umeyama(X, Y, scale=None):
    mx, my = X.mean(0), Y.mean(0)
    Xc, Yc = X - mx, Y - my
    U, S, Vt = np.linalg.svd(Yc.T @ Xc / len(X))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = (S * np.diag(D)).sum() / (Xc ** 2).sum(1).mean() if scale is None else scale
    return s, R, my - s * R @ mx


def main(mode):
    P, Nr, _, F = load()
    b, f, _ = preset("female")
    ctl = {k: float(getattr(b if k.startswith("body.") else f, k.split(".")[1])) for k in E.control_defaults()}
    v = E.shape(ctl, {})
    em = np.mean([model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"], 0)
    body = model.body_vertex_ids()
    vb = v[body]
    rel = vb - em
    sel = (rel[:, 1] > -0.115) & (rel[:, 1] < 0.035) & (np.abs(rel[:, 0]) < 0.075) & (rel[:, 2] > -0.005)
    ids = np.setdiff1d(body[sel], np.concatenate([model.lid_region(s, 2) for s in "lr"]))
    B = np.stack([identity.basis(k)[ids] for k in I.KEYS_V1], 0)
    box = (P[:, 0] > -0.26) & (P[:, 0] < 0.06) & (P[:, 1] > 1.55) & (P[:, 1] < 1.82) & (P[:, 2] > -0.10)
    T, TN = P[box], Nr[box]

    def nn(X):
        j = np.empty(len(X), int)
        d = np.empty(len(X))
        for i in range(0, len(X), 256):
            D2 = ((X[i:i + 256, None] - T[None]) ** 2).sum(2)
            j[i:i + 256] = D2.argmin(1)
            d[i:i + 256] = np.sqrt(D2[np.arange(len(D2)), j[i:i + 256]])
        return j, d

    def icp(X, s, R, t, n, fix_scale):
        for _ in range(n):
            j, d = nn(s * X @ R.T + t)
            k = d <= np.percentile(d, TRIM)
            s, R, t = umeyama(X[k], T[j[k]], s if fix_scale else None)
        j, d = nn(s * X @ R.T + t)
        k = d <= np.percentile(d, TRIM)
        return s, R, t, j, d, k

    X0 = v[ids]
    if mode == "landmarks":
        col = vb[(np.abs(vb[:, 0]) < 0.003) & (vb[:, 2] > em[2] - 0.02) & (vb[:, 1] < em[1]) & (vb[:, 1] > em[1] - 0.14)]
        bridge = vb[(np.abs(vb[:, 0]) < 0.003) & (np.abs(vb[:, 1] - em[1]) < 0.003)]
        LV = np.array([bridge[np.argmax(bridge[:, 2])], col[np.argmax(col[:, 2])], col[np.argmin(col[:, 1])]])
        s, R, t = umeyama(LV, LANDMARKS)
        fix = True
    else:
        nose_v = X0[np.argmax(X0[:, 2])]
        s, R, t = 1.08, np.eye(3), LANDMARKS[1] - 1.08 * nose_v
        fix = False
    s, R, t, j, d, k = icp(X0, s, R, t, 30, fix)
    hist = [("aligned, identity 0", float(np.sqrt((d[k] ** 2).mean())))]
    w = np.zeros(len(I.KEYS_V1))
    for rnd in range(4):
        X = X0 + np.einsum("k,knj->nj", w, B)
        s, R, t, j, d, k = icp(X, s, R, t, 10, fix)
        n = TN[j] / np.linalg.norm(TN[j], axis=1, keepdims=True)
        r0 = (((s * X0 @ R.T + t) - T[j]) * n).sum(1)[k]
        A = np.einsum("knj,ij,nj->nk", B, s * R, n)[k]
        w = np.clip(np.linalg.solve(A.T @ A + 1e-6 * len(A) * np.eye(len(w)), -A.T @ r0), -1, 1)
        X = X0 + np.einsum("k,knj->nj", w, B)
        j, d = nn(s * X @ R.T + t)
        k = d <= np.percentile(d, TRIM)
        hist.append((f"identity round {rnd + 1}", float(np.sqrt((d[k] ** 2).mean()))))
        print(hist[-1], flush=True)
    vals = {key: round(float(x), 3) for key, x in zip(I.KEYS_V1, w) if abs(x) > 0.02}
    out = {"mode": mode, "face_vertices": int(len(ids)), "target_points": int(len(T)), "trim_percentile": TRIM,
           "scale_rodin_per_v3": round(float(s), 4), "pitch_deg": round(float(np.degrees(np.arctan2(R[2, 1], R[1, 1]))), 1),
           "trimmed_rms_mm": [(a, round(x * 1000, 2)) for a, x in hist], "identity_values": vals,
           "at_limit": [key for key, x in vals.items() if abs(x) >= 0.999]}
    (HERE / "results" / f"facefit_{mode}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    vf = E.shape(ctl, dict(zip(I.KEYS_V1, map(float, w))))
    Pv = ((P - t) @ R) / s  # the Rodin head brought into the v3 frame: identical cameras
    tiles = []
    for yaw in (0, 90):
        cam = Camera(yaw_deg=yaw, pitch_deg=2, target=tuple(em + [0, -0.03, 0]), distance=0.45, fov_deg=26)
        r = lambda items: rasterize(items, cam, W=320, H=360, background=(0.78, 0.8, 0.83), ground_y=None)
        tiles += [label(r([DrawItem(Pv, F, color=(0.75, 0.75, 0.77))]), f"Rodin in the v3 frame ({mode}), {yaw}", size=12),
                  label(r(head_items(v)), f"v3 female, identity 0, {yaw}", size=12),
                  label(r(head_items(vf)), f"v3 fitted to the Rodin face, {yaw}", size=12)]
    save(sheet(tiles, 3), HERE / "results" / f"facefit_{mode}.jpg")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "landmarks")
