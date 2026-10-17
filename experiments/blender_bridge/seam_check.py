"""Independent checks of a skin-weight edit (Phase 1.1); numpy + Forge's independent player, no Blender.

    python3 seam_check.py <source.glb> <baseline.glb> <edited.glb> <out.json>

baseline = the same Blender round trip WITHOUT the edit, so differences baseline -> edited are the edit's alone.
  seams      every body position stored more than once (UV / normal seams): weights identical across the copies,
             and the largest posed opening over ALL frames of walk and run
  isolation  baseline vs edited, per matched vertex: positions, normals, UVs, triangles (by vertex index), morph
             deltas, and which meshes' weights changed
  garments   for every frame of walk and run: garment vertices (shorts, top) inside the body by > 1 mm (signed
             distance to the nearest body vertex along its posed normal), source vs edited
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

import rig_compare as R
from render_rig import posed

GARMENTS = ("basic_shorts", "basic_top")


def vnormals(P, F, inv, n):
    """Area-weighted normals on welded positions (seam copies share one normal)."""
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    acc = np.zeros((n, 3))
    for k in range(3):
        np.add.at(acc, inv[F[:, k]], fn)
    acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-20)
    return acc


def penetration(body_P, body_F, garm_P, inv, n, cell=0.01):
    key_P = np.zeros((n, 3))
    key_P[inv] = body_P
    N = vnormals(body_P, body_F, inv, n)
    keys = np.floor(key_P / cell).astype(np.int64)
    lut = {}
    for i, k in enumerate(map(tuple, keys)):
        lut.setdefault(k, []).append(i)
    depth = np.zeros(len(garm_P))
    for gi, p in enumerate(garm_P):
        c = np.floor(p / cell).astype(np.int64)
        cand = [i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) for i in lut.get((c[0] + dx, c[1] + dy, c[2] + dz), [])]
        if not cand:
            continue
        cand = np.array(cand)
        j = cand[np.argmin(((key_P[cand] - p) ** 2).sum(1))]
        depth[gi] = (p - key_P[j]) @ N[j]  # < 0: the garment vertex is inside the body
    return depth


def main():
    src, base, edit, outp = sys.argv[1:5]
    S, B, E = R.G(src), R.G(base), R.G(edit)
    rep = {}
    # --- isolation: baseline vs edited
    MB, ME = R.meshes(B), R.meshes(E)
    iso = {}
    jb = [B.name(i) for i in B.g["skins"][0]["joints"]]
    je = [E.name(i) for i in E.g["skins"][0]["joints"]]
    for name, a in MB.items():
        b = ME[name]
        same_idx = len(a["P"]) == len(b["P"]) and np.array_equal(a["F"], b["F"])
        r = {"same_vertex_order_and_triangles": bool(same_idx)}
        if same_idx:
            r["position_max_abs"] = float(np.abs(a["P"] - b["P"]).max())
            if "N" in a:
                r["normal_max_abs"] = float(np.abs(a["N"] - b["N"]).max())
            if "UV" in a:
                r["uv_max_abs"] = float(np.abs(a["UV"] - b["UV"]).max())
            r["morph_max_abs"] = max((float(np.abs(a["targets"][t] - b["targets"][t]).max()) for t in a["targets"]), default=0.0)
            if "W" in a:
                Wa = R.weights_by_name(a, jb)
                Wb = R.weights_by_name(b, je)[:, [je.index(n) for n in jb]]
                d = np.abs(Wa - Wb).max(1)
                r["weights_changed_vertices"] = int((d > 1e-6).sum())
                r["weights_max_change"] = float(d.max())
        iso[name] = r
    rep["isolation_baseline_vs_edited"] = iso
    # --- seams on the edited body
    body = ME["body"]
    key, inv = np.unique(np.round(body["P"] * 1e6).astype(np.int64), axis=0, return_inverse=True)
    inv = inv.ravel()
    groups = [np.nonzero(inv == k)[0] for k in np.nonzero(np.bincount(inv) > 1)[0]]
    W = R.weights_by_name(body, je)
    rep["seams"] = {"groups": len(groups), "groups_with_different_weights": int(sum(np.abs(W[g] - W[g[0]]).max() > 1e-6 for g in groups))}
    walk_f, run_f = list(range(0, 32)), list(range(0, 20))
    with tempfile.TemporaryDirectory() as tmp:
        frames = {}
        for tag, p in (("source", src), ("edited", edit)):
            frames[tag] = {"walk": posed(p, tmp, f"{tag}_w", "walk", walk_f, {}, ["body", *GARMENTS]), "run": posed(p, tmp, f"{tag}_r", "run", run_f, {}, ["body", *GARMENTS])}
    worst = 0.0
    for clip in ("walk", "run"):
        for f, geo in frames["edited"][clip].items():
            P = geo["body"][0]
            worst = max(worst, max(float(np.linalg.norm(P[g] - P[g[0]], axis=1).max()) for g in groups))
    rep["seams"]["max_posed_opening_mm_all_walk_run_frames"] = round(worst * 1000, 6)
    # --- garments
    gar = {}
    for tag, gg in (("source", S), ("edited", E)):
        b = R.meshes(gg)["body"]
        k_, inv_ = np.unique(np.round(b["P"] * 1e6).astype(np.int64), axis=0, return_inverse=True)
        inv_ = inv_.ravel()
        res = {}
        for clip in ("walk", "run"):
            for f, geo in frames[tag][clip].items():
                bP, bF = geo["body"]
                for gname in GARMENTS:
                    d = penetration(bP, bF, geo[gname][0], inv_, len(k_))
                    r = res.setdefault(gname, {"frames": 0, "inside_gt_1mm_total": 0, "inside_gt_1mm_max_per_frame": 0, "deepest_mm": 0.0, "left_leg_inside_gt_1mm_total": 0})
                    ins = d < -1e-3
                    r["frames"] += 1
                    r["inside_gt_1mm_total"] += int(ins.sum())
                    r["inside_gt_1mm_max_per_frame"] = max(r["inside_gt_1mm_max_per_frame"], int(ins.sum()))
                    r["deepest_mm"] = round(max(r["deepest_mm"], float(-d.min()) * 1000), 3)
                    r["left_leg_inside_gt_1mm_total"] += int((ins & (geo[gname][0][:, 0] > 0.02) & (geo[gname][0][:, 1] < 0.9)).sum())
        gar[tag] = res
    rep["garments_walk_run_all_frames"] = gar
    Path(outp).write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
