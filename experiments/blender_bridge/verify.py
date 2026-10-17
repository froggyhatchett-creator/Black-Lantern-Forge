"""Forge-side verification of a Blender job's output GLB. Independent of Blender: Forge's GLB reader and validator,
numpy only. A job is not called successful because Blender exported a valid file; this checks what it contains.

    python3 verify.py <job dir> [--source <source glb>]

Checks (written to <job dir>/verify.json)
  all ops         Forge validator (errors/warnings); node transforms applied (scale/axes); triangle count; normals
                  and UVs present; materials; bounding box vs the source
  extract_region  a numpy reference of the same selection (faces whose 3 vertices are in the boxes, largest welded
                  part): expected face count; every output vertex must coincide with a source vertex (<= 0.01 mm,
                  i.e. nothing invented or moved) and lie in a box; open cut boundary loops counted
  simplify        triangle ratio vs the requested ratio; deviation output -> nearest source vertex (sampled; an upper
                  bound); no new open edges on welded geometry (a closed source must stay closed)
  roundtrip       every triangle matched exactly by position; per-corner normals and UVs; materials
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


def load_world(path, with_attributes=False):
    """All triangle primitives in world space (node transforms applied): positions, triangles, has-normals, has-UVs."""
    g, b = read_glb(path)

    def acc(i):
        a = g["accessors"][i]
        bv = g["bufferViews"][a["bufferView"]]
        n = NC[a["type"]]
        x = np.frombuffer(b, TYPES[a["componentType"]], a["count"] * n, bv.get("byteOffset", 0) + a.get("byteOffset", 0))
        return x.reshape(a["count"], n) if n > 1 else x

    Ps, Fs, Ns, UVs, info, off = [], [], [], [], {"normals": True, "uvs": True, "node_transforms": []}, 0

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
                Nm = acc(p["attributes"]["NORMAL"]).astype(float) @ np.linalg.inv(M[:3, :3]) if "NORMAL" in p["attributes"] else np.zeros_like(P)
                Ns.append(Nm / np.maximum(np.linalg.norm(Nm, axis=1, keepdims=True), 1e-20))
                UVs.append(acc(p["attributes"]["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in p["attributes"] else np.zeros((len(P), 2)))
                Fs.append(F + off)
                off += len(P)
        for c in node.get("children", []):
            walk(c, M)

    for r in g["scenes"][g.get("scene", 0)]["nodes"]:
        walk(r, np.eye(4))
    info["materials"] = [m.get("name") for m in g.get("materials", [])]
    info["material_values"] = [{"name": m.get("name"), "doubleSided": m.get("doubleSided", False), **m.get("pbrMetallicRoughness", {})} for m in g.get("materials", [])]
    info["images"] = len(g.get("images", []))
    info["generator"] = g["asset"].get("generator")
    if with_attributes:
        return np.concatenate(Ps), np.concatenate(Fs), info, np.concatenate(Ns), np.concatenate(UVs)
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


def tri_keys(P, F):
    """A triangle identified by its three corner positions (order-free, 1 micrometre); also the corner order used."""
    q = np.round(P[F] * 1e6).astype(np.int64)
    o = np.lexsort((q[:, :, 2], q[:, :, 1], q[:, :, 0]))
    return q[np.arange(len(F))[:, None], o].reshape(len(F), 9), o


def uv_islands(Fw, UVc):
    """Face island ids: faces joined across a welded edge only where both share the UVs at both ends (numpy version
    of Blender's Select Linked delimited by UV). UVc: per-face-corner UVs (F, 3, 2)."""
    nf = len(Fw)
    a, b = Fw, np.roll(Fw, -1, axis=1)
    ua, ub = UVc, np.roll(UVc, -1, axis=1)
    lo, hi = np.minimum(a, b).ravel(), np.maximum(a, b).ravel()
    swap = (a > b).ravel()
    ulo = np.where(swap[:, None], ub.reshape(-1, 2), ua.reshape(-1, 2))
    uhi = np.where(swap[:, None], ua.reshape(-1, 2), ub.reshape(-1, 2))
    face = np.repeat(np.arange(nf), 3)
    o = np.lexsort((hi, lo))
    lo, hi, ulo, uhi, face = lo[o], hi[o], ulo[o], uhi[o], face[o]
    same = (lo[1:] == lo[:-1]) & (hi[1:] == hi[:-1])
    cont = same & (np.abs(ulo[1:] - ulo[:-1]).max(1) < 1e-6) & (np.abs(uhi[1:] - uhi[:-1]).max(1) < 1e-6)
    pairs = np.c_[face[:-1][cont], face[1:][cont]]
    lab = components(pairs, nf)
    return np.unique(lab, return_inverse=True)[1].ravel()


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
        if job["operation"] == "roundtrip":
            S, SF, sinfo, SN, SUV = load_world(src, True)
            O, OF, oinfo, ON, OUV = load_world(out, True)

            ks, so = tri_keys(S, SF)
            ko, oo = tri_keys(O, OF)
            us, si = np.unique(ks, axis=0, return_index=True)
            pos = np.searchsorted(us.view([("", np.int64)] * 9).ravel(), ko.view([("", np.int64)] * 9).ravel())
            pos = np.clip(pos, 0, len(us) - 1)
            found = (us[pos] == ko).all(1)
            sidx = si[pos[found]]
            cs = SF[sidx][np.arange(found.sum())[:, None], so[sidx]]          # source corners in sorted order
            co = OF[found][np.arange(found.sum())[:, None], oo[found]]        # output corners in the same order
            dn = np.degrees(np.arccos(np.clip((SN[cs] * ON[co]).sum(2), -1, 1)))
            duv = np.abs(SUV[cs] - OUV[co]).max(2)
            v["roundtrip"] = {"source_triangles": len(SF), "output_triangles": len(OF), "output_vertices": len(O), "source_vertices": len(S),
                              "triangles_matched_exactly": int(found.sum()), "duplicate_source_triangles": int(len(SF) - len(us)),
                              "normal_angle_deg_p99_max": np.round(np.percentile(dn, [99, 100]), 4).tolist(),
                              "uv_abs_diff_max": float(duv.max()), "bbox_max_diff_mm": round(float(max(np.abs(O.min(0) - S.min(0)).max(), np.abs(O.max(0) - S.max(0)).max()) * 1000), 6),
                              "materials_source": sinfo["material_values"], "materials_output": oinfo["material_values"], "generator_output": oinfo["generator"]}
            mat_ok = len(sinfo["material_values"]) == len(oinfo["material_values"]) and all(
                np.allclose(a.get("baseColorFactor", [1, 1, 1, 1]), b.get("baseColorFactor", [1, 1, 1, 1]), atol=1e-4)
                and abs(a.get("metallicFactor", 1) - b.get("metallicFactor", 1)) < 1e-4 and abs(a.get("roughnessFactor", 1) - b.get("roughnessFactor", 1)) < 1e-4
                and a["doubleSided"] == b["doubleSided"] for a, b in zip(sinfo["material_values"], oinfo["material_values"]))
            v["roundtrip"]["materials_match"] = bool(mat_ok)
            v["pass"] = bool(not val["errors"] and found.all() and len(OF) == len(SF) and dn.max() < 0.5 and duv.max() < 1e-5 and mat_ok)
        elif job["operation"] == "extract_region":
            boxes = job["params"]["boxes"]
            key, inv = weld(S)
            Fw = inv[SF]
            if job["params"].get("select") == "uv_islands":
                S2, SF2, _, _, SUV = load_world(src, True)
                lab = uv_islands(Fw, SUV[SF])
                cen = S[SF].mean(1)
                n = lab.max() + 1
                tot = np.bincount(lab, minlength=n)
                take = np.bincount(lab, weights=in_boxes(cen, boxes).astype(float), minlength=n) >= job["params"].get("island_vote", 0.6) * tot
                for act, pts in (("exclude", job["params"].get("exclude_points", {})), ("include", job["params"].get("include_points", {}))):
                    for p_ in pts.values():
                        take[lab[np.argmin(((cen - np.array(p_)) ** 2).sum(1))]] = act == "include"
                sel = take[lab]
                ko, _ = tri_keys(O, OF)
                ke, _ = tri_keys(S, SF[sel])
                kv = lambda k: np.ascontiguousarray(k).view([("", np.int64)] * 9).ravel()
                v["extract_uv_islands"] = {"uv_islands_numpy": int(n), "islands_taken": int(take.sum()), "expected_triangles": int(sel.sum()),
                                           "output_triangles": len(OF), "same_triangle_set": bool(len(ke) == len(ko) and np.array_equal(np.sort(kv(ke)), np.sort(kv(ko))))}
            sel = in_boxes(key, boxes)[Fw].all(1) if job["params"].get("select") != "uv_islands" else sel
            Fs = Fw[sel]
            lab = components(tri_edges(Fs), len(key))
            fl = lab[Fs[:, 0]]
            vals, cnt = np.unique(fl, return_counts=True)
            expect = int(cnt.max()) if job["params"].get("keep_largest", True) else int(sel.sum())
            if "extract_uv_islands" in v:
                expect = v["extract_uv_islands"]["expected_triangles"]
            d = nearest_dist(O, key, cell=0.002)
            ok_inside = in_boxes(O, boxes) if job["params"].get("select") != "uv_islands" else np.ones(len(O), bool)  # islands may leave the box
            ok, oinv = weld(O)
            loops, bedges = boundary_loops(oinv[OF])
            v["extract"] = {"expected_triangles_numpy_reference": expect, "output_triangles": len(OF),
                            "match": bool(expect == len(OF)), "parts_in_boxes": int(len(vals)),
                            "vertex_max_deviation_from_source_mm": round(float(d.max()) * 1000, 4),
                            "vertices_outside_boxes": int((~ok_inside).sum()), "open_boundary_loops": loops, "open_boundary_edges": bedges}
            v["pass"] = bool(not val["errors"] and v["extract"]["match"] and d.max() <= 1e-5 and ok_inside.all()
                             and v.get("extract_uv_islands", {}).get("same_triangle_set", True))
        elif job["operation"] == "simplify":
            rng = np.random.default_rng(0)
            idx = rng.choice(len(O), min(4000, len(O)), replace=False)
            d = nearest_dist(O[idx], S, cell=0.02)
            ratio = len(OF) / len(SF)
            sk, sinv = weld(S)
            ok_, oinv_ = weld(O)
            s_open, o_open = boundary_loops(sinv[SF])[1], boundary_loops(oinv_[OF])[1]
            o_parts = len(np.unique(components(tri_edges(oinv_[OF]), len(ok_))[np.unique(oinv_[OF])]))
            v["simplify"] = {"triangle_ratio": round(ratio, 4), "requested": job["params"]["ratio"],
                             "deviation_to_nearest_source_vertex_mm_p50_p99_max": np.round(np.percentile(d, [50, 99, 100]) * 1000, 3).tolist(),
                             "welded_open_edges_source_output": [s_open, o_open], "welded_parts_output": o_parts}
            v["pass"] = bool(not val["errors"] and abs(ratio - job["params"]["ratio"]) < 0.05 and d.max() < 0.02 and o_open <= s_open
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
