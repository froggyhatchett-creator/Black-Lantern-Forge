"""Forge-side verification of a Blender job's output GLB. Independent of Blender: Forge's GLB reader and validator,
numpy only. A job is not called successful because Blender exported a valid file; this checks what it contains.

    python3 verify.py <job dir> [--source <source glb>]

Checks (written to <job dir>/verify.json)
  all ops         Forge validator (errors/warnings); node transforms applied (scale/axes); triangle count; normals
                  and UVs present; materials; bounding box vs the source
  extract_region  a numpy reference of the same selection (faces whose 3 vertices are in the boxes, largest welded
                  part): expected face count; every output vertex must coincide with a source vertex (<= 0.01 mm,
                  i.e. nothing invented or moved) and lie in a box; open cut boundary loops counted
  simplify        triangle ratio vs the requested ratio; one-sided surface deviation output -> source (sampled)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.validate import read_glb, validate_glb  # noqa: E402

TYPES = {5126: "<f4", 5125: "<u4", 5123: "<u2", 5121: "u1"}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _trs(node):
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    M = np.eye(4)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    M[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    M[:3, :3] *= np.array(node.get("scale", [1, 1, 1]))[None]
    M[:3, 3] = node.get("translation", [0, 0, 0])
    return M


def load_world(path):
    """All triangle primitives in world space (node transforms applied): positions, triangles, has-normals, has-UVs."""
    g, b = read_glb(path)

    def acc(i):
        a = g["accessors"][i]
        bv = g["bufferViews"][a["bufferView"]]
        n = NC[a["type"]]
        x = np.frombuffer(b, TYPES[a["componentType"]], a["count"] * n, bv.get("byteOffset", 0) + a.get("byteOffset", 0))
        return x.reshape(a["count"], n) if n > 1 else x

    Ps, Fs, info, off = [], [], {"normals": True, "uvs": True, "node_transforms": []}, 0

    def walk(ni, M):
        node = g["nodes"][ni]
        M = M @ _trs(node)
        nonlocal off
        if "mesh" in node:
            info["node_transforms"].append(np.round(M, 6).tolist())
            for p in g["meshes"][node["mesh"]]["primitives"]:
                if p.get("mode", 4) != 4:
                    continue
                P = acc(p["attributes"]["POSITION"]).astype(float)
                F = acc(p["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in p else np.arange(len(P)).reshape(-1, 3)
                info["normals"] = bool(info["normals"] and "NORMAL" in p["attributes"])
                info["uvs"] = bool(info["uvs"] and "TEXCOORD_0" in p["attributes"])
                Ps.append((np.c_[P, np.ones(len(P))] @ M.T)[:, :3])
                Fs.append(F + off)
                off += len(P)
        for c in node.get("children", []):
            walk(c, M)

    for r in g["scenes"][g.get("scene", 0)]["nodes"]:
        walk(r, np.eye(4))
    info["materials"] = [m.get("name") for m in g.get("materials", [])]
    info["images"] = len(g.get("images", []))
    return np.concatenate(Ps), np.concatenate(Fs), info


def weld(P):
    key, inv = np.unique(np.round(P, 6), axis=0, return_inverse=True)
    return key, inv.ravel()


def tri_edges(Fw):
    return np.unique(np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), 1), axis=0)


def components(E, n):
    """Vertex labels of the connected components of an edge list (min-label propagation)."""
    lab = np.arange(n)
    while True:
        m = np.minimum(lab[E[:, 0]], lab[E[:, 1]])
        new = lab.copy()
        np.minimum.at(new, E[:, 0], m)
        np.minimum.at(new, E[:, 1], m)
        new = new[new]
        if (new == lab).all():
            return lab
        lab = new


def boundary_loops(Fw):
    E = np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), 1)
    u, c = np.unique(E, axis=0, return_counts=True)
    bd = u[c == 1]
    if not len(bd):
        return 0, 0
    lab = components(bd, int(bd.max()) + 1)
    return int(len(np.unique(lab[np.unique(bd)]))), int(len(bd))


def in_boxes(P, boxes):
    m = np.zeros(len(P), bool)
    for b in boxes:
        d = (P - np.array(b["centre"])) @ np.array(b["axes"]).T
        m |= (np.abs(d) <= np.array(b["half"])).all(1)
    return m


def nearest_dist(Q, P, cell=0.02):
    """Distance from each point of Q to the nearest point of P (voxel hash; exact within cell, else capped at cell)."""
    keys = np.floor(P / cell).astype(np.int64)
    order = np.lexsort(keys.T[::-1])
    ks, Ps = keys[order], P[order]
    uk, start = np.unique(ks, axis=0, return_index=True)
    lut = {tuple(k): (s, e) for k, s, e in zip(uk, start, list(start[1:]) + [len(ks)])}
    out = np.full(len(Q), cell)
    for i, q in enumerate(Q):
        c = np.floor(q / cell).astype(np.int64)
        best = cell
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    r = lut.get((c[0] + dx, c[1] + dy, c[2] + dz))
                    if r:
                        best = min(best, float(np.sqrt(((Ps[r[0]:r[1]] - q) ** 2).sum(1)).min()))
        out[i] = best
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--source")
    a = ap.parse_args()
    jd = Path(a.job_dir)
    res = json.loads((jd / "result.json").read_text())
    job = res["job"]
    src = Path(a.source) if a.source else jd / ("input" + Path(job["input"]).suffix)
    S, SF, sinfo = load_world(src)
    v = {"operation": job["operation"], "source": {"triangles": len(SF), "bbox": [S.min(0).round(4).tolist(), S.max(0).round(4).tolist()]}}
    if job["operation"] != "inspect":
        out = jd / "output" / job["output"]
        val = validate_glb(out)
        O, OF, oinfo = load_world(out)
        v["validator"] = {"errors": val["errors"], "warnings": val["warnings"]}
        v["output"] = {"triangles": len(OF), "vertices": len(O), "bbox": [O.min(0).round(4).tolist(), O.max(0).round(4).tolist()], **oinfo}
        if job["operation"] == "extract_region":
            boxes = job["params"]["boxes"]
            key, inv = weld(S)
            Fw = inv[SF]
            sel = in_boxes(key, boxes)[Fw].all(1)
            Fs = Fw[sel]
            lab = components(tri_edges(Fs), len(key))
            fl = lab[Fs[:, 0]]
            vals, cnt = np.unique(fl, return_counts=True)
            expect = int(cnt.max()) if job["params"].get("keep_largest", True) else int(sel.sum())
            d = nearest_dist(O, key, cell=0.002)
            ok_inside = in_boxes(O, boxes)
            ok, oinv = weld(O)
            loops, bedges = boundary_loops(oinv[OF])
            v["extract"] = {"expected_triangles_numpy_reference": expect, "output_triangles": len(OF),
                            "match": bool(expect == len(OF)), "parts_in_boxes": int(len(vals)),
                            "vertex_max_deviation_from_source_mm": round(float(d.max()) * 1000, 4),
                            "vertices_outside_boxes": int((~ok_inside).sum()), "open_boundary_loops": loops, "open_boundary_edges": bedges}
            v["pass"] = bool(not val["errors"] and v["extract"]["match"] and d.max() <= 1e-5 and ok_inside.all())
        elif job["operation"] == "simplify":
            rng = np.random.default_rng(0)
            idx = rng.choice(len(O), min(4000, len(O)), replace=False)
            d = nearest_dist(O[idx], S, cell=0.02)
            ratio = len(OF) / len(SF)
            v["simplify"] = {"triangle_ratio": round(ratio, 4), "requested": job["params"]["ratio"],
                             "deviation_mm_p50_p99_max": np.round(np.percentile(d, [50, 99, 100]) * 1000, 3).tolist()}
            v["pass"] = bool(not val["errors"] and abs(ratio - job["params"]["ratio"]) < 0.05 and d.max() < 0.02
                             and np.allclose(O.min(0), S.min(0), atol=0.01) and np.allclose(O.max(0), S.max(0), atol=0.01))
    else:
        rep = res.get("report") or {}
        objs = [o for o in rep.get("scene", {}).get("objects", []) if o["type"] == "MESH"]
        tri = sum(o["mesh"]["triangles"] for o in objs)
        v["inspect"] = {"blender_triangles": tri, "blender_mesh_objects": len(objs), "match_triangles": tri == len(SF)}
        v["pass"] = bool(objs) and tri == len(SF)
    (jd / "verify.json").write_text(json.dumps(v, indent=1))
    print(json.dumps(v, indent=1))
    return 0 if v.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
