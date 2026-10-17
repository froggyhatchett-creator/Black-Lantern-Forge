"""Probe (runs INSIDE Blender): do Blender's own part-finding tools see a board boundary on the Rodin mesh?

    .bpy-venv/bin/python -I probe_blender_selection.py <source glb> <out json>

1. Separate by Loose Parts after welding: how many parts.
2. UV islands (Blender's "Select Linked" delimited by UV): count, sizes, and for each island the fraction of its faces
   inside the v0 board slab. An island boundary that followed the board outline would give islands that are almost
   entirely inside or outside it.
3. Sharp-edge islands (Select Linked delimited by edges sharper than 30 degrees, either convexity).
Writes per-face island ids for rendering (<out>.uv_island.npy, <out>.sharp_island.npy) in source triangle order.
"""
import json
import sys
from pathlib import Path

import bpy  # first: bmesh exists only after bpy (pip module)
import bmesh  # noqa: E402
import numpy as np  # noqa: E402

src, out = sys.argv[1], sys.argv[2]
box = json.loads((Path(__file__).resolve().parent / "jobspecs/extract_board_slab_v0.json").read_text())["params"]["boxes"][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
ob = [o for o in bpy.data.objects if o.type == "MESH"][0]
bm = bmesh.new()
bm.from_mesh(ob.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
bm.faces.ensure_lookup_table()
uv = bm.loops.layers.uv.active
nf = len(bm.faces)
res = {"faces": nf, "vertices_welded": len(bm.verts)}


def islands(connected):
    lab = -np.ones(nf, int)
    k = 0
    for f in bm.faces:
        if lab[f.index] >= 0:
            continue
        stack = [f]
        lab[f.index] = k
        while stack:
            g = stack.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h is not g and lab[h.index] < 0 and connected(g, h, e):
                        lab[h.index] = k
                        stack.append(h)
        k += 1
    return lab


def same_uv(g, h, e):
    a = {l.vert.index: l[uv].uv.copy() for l in g.loops if l.vert in e.verts}
    b = {l.vert.index: l[uv].uv.copy() for l in h.loops if l.vert in e.verts}
    return all((a[i] - b[i]).length < 1e-6 for i in a)


def smooth(g, h, e):
    return g.normal.angle(h.normal, 0.0) < np.radians(30)


loose = islands(lambda g, h, e: True)
res["loose_parts_after_weld"] = int(loose.max() + 1)
cen = np.array([[c for c in (lambda v: (v.x, v.z, -v.y))(f.calc_center_median())] for f in bm.faces])  # glTF axes
d = (cen - np.array(box["centre"])) @ np.array(box["axes"]).T
inside = (np.abs(d) <= np.array(box["half"])).all(1)
for name, fn in (("uv_island", same_uv), ("sharp_island", smooth)):
    lab = islands(fn)
    n = lab.max() + 1
    cnt = np.bincount(lab, minlength=n)
    frac = np.bincount(lab, weights=inside.astype(float), minlength=n) / np.maximum(cnt, 1)
    touching = frac > 0
    mixed = touching & (frac < 0.95) & (frac > 0.05)
    res[name] = {"islands": int(n), "faces_p50_p99_max": np.percentile(cnt, [50, 99, 100]).astype(int).tolist(),
                 "islands_touching_slab": int(touching.sum()),
                 "mixed_islands_5_to_95pct_inside": int(mixed.sum()),
                 "faces_in_mixed_islands": int(cnt[mixed].sum()),
                 "largest_island_fraction_of_mesh": round(float(cnt.max() / nf), 4)}
    np.save(f"{out}.{name}.npy", lab)
# face order: Blender keeps the glTF triangle order on import (checked here against the source centroids by the caller)
np.save(f"{out}.centroids.npy", cen)
Path(out).write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
