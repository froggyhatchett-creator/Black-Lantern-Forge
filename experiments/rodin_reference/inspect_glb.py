"""Phase 1: structure and topology of the Rodin GLB (no modification). Writes results/inspection.json.

    python3 experiments/rodin_reference/inspect_glb.py
"""
import hashlib
import json

import numpy as np

from glb_mesh import HERE, SHA256, SOURCE, load, read_glb
from forge_character_forge.validate import validate_glb

raw = SOURCE.read_bytes()
sha = hashlib.sha256(raw).hexdigest()
assert sha == SHA256, f"source changed: {sha}"
g, _ = read_glb(SOURCE)
val = validate_glb(SOURCE)
out = {"source_sha256": sha, "bytes": len(raw), "generator": g["asset"].get("generator"),
       "nodes": [n.get("name") for n in g["nodes"]], "meshes": len(g["meshes"]),
       "primitives": sum(len(m["primitives"]) for m in g["meshes"]), "attributes": list(g["meshes"][0]["primitives"][0]["attributes"]),
       "materials": g.get("materials"), "images": len(g.get("images", [])), "textures": len(g.get("textures", [])),
       "skins": len(g.get("skins", [])), "animations": len(g.get("animations", [])),
       "morph_targets": sum(len(p.get("targets", [])) for m in g["meshes"] for p in m["primitives"]),
       "forge_validator": {"errors": val["errors"], "warnings": val["warnings"], "profile": val["stats"].get("profile")}}

P, N, UV, F = load()
key, inv = np.unique(np.round(P, 7), axis=0, return_inverse=True)
inv = inv.ravel()
Fw = inv[F]
out.update({"vertices": len(P), "welded_vertices": len(key), "uv_seam_split_vertices": len(P) - len(key), "triangles": len(F)})
e = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
area = np.linalg.norm(e, axis=1) / 2
out["degenerate_triangles"] = int(((Fw[:, 0] == Fw[:, 1]) | (Fw[:, 1] == Fw[:, 2]) | (Fw[:, 0] == Fw[:, 2])).sum())
out["zero_area_triangles"] = int((area < 1e-12).sum())
E = np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), 1)
u, c = np.unique(E, axis=0, return_counts=True)
out.update({"edges": len(u), "boundary_edges": int((c == 1).sum()), "nonmanifold_edges": int((c > 2).sum())})
d, dc = np.unique(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), axis=0, return_counts=True)
out["inconsistently_oriented_edges"] = int((dc > 1).sum())
lab = np.arange(len(key))
while True:  # connected components: min-label propagation over the edges
    m = np.minimum(lab[u[:, 0]], lab[u[:, 1]])
    new = lab.copy()
    np.minimum.at(new, u[:, 0], m)
    np.minimum.at(new, u[:, 1], m)
    new = new[new]
    if (new == lab).all():
        break
    lab = new
out["connected_components"] = int(len(np.unique(lab)))
chi = len(key) - len(u) + len(F)
out["euler_characteristic"] = int(chi)
out["genus_if_one_closed_shell"] = int((2 - chi) // 2)
out["signed_volume_m3"] = round(float(np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6), 5)
fn = e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-20)
vn = N[F].mean(1)
out["stored_normals_against_winding_fraction"] = round(float(((fn * vn).sum(1) < 0).mean()), 4)
el = np.linalg.norm(P[F[:, [1, 2, 0]]] - P[F], axis=2)
out["edge_length_mm_p1_p50_p99"] = np.round(np.percentile(el, [1, 50, 99]) * 1000, 2).tolist()
out["bbox_min_m"] = np.round(P.min(0), 4).tolist()
out["bbox_max_m"] = np.round(P.max(0), 4).tolist()
out["uv_range"] = [np.round(UV.min(0), 4).tolist(), np.round(UV.max(0), 4).tolist()]
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "inspection.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
