"""Blender side of the experimental Forge job bridge. Runs INSIDE Blender (application or pip bpy), never in Forge.

    blender --background --factory-startup --python job_blender.py -- <job dir>/job.json
    <python with bpy> -I job_blender.py <job dir>/job.json

Reads job.json from its own job directory, imports the (read-only) input, performs ONE operation and writes
output/report.json (+ output/<name>.glb). Coordinates in job parameters and reports are glTF / Forge coordinates
(metres, +Y up, +Z front); Blender's importer converts glTF Y-up to Blender Z-up, the exporter converts back.

STATUS: run with Blender 5.2.2 (pip bpy) on 2026-10-17; outputs verified by verify.py (see the Phase 0 report).
Written for the documented bpy API; other Blender versions are untested.

Operations
  inspect          objects, transforms, mesh counts, UV layers, materials/textures, armatures, shape keys, bounds
  roundtrip        import and export everything with no edits (tests the importer/exporter pair)
  simplify         params {"ratio": 0..1}: Decimate (collapse) on every mesh, then export
  extract_region   params {"boxes": [{"centre": [x,y,z], "axes": [[3],[3],[3]], "half": [hx,hy,hz]}, ...],
                           "keep_largest": true}: copy the faces whose three vertices lie in any oriented box into a
                   new object (the source object is not modified), optionally keep the largest connected part,
                   then export it. Cut boundaries are left OPEN and reported (no automatic capping).
                   With "select": "uv_islands": whole UV islands voted by the boxes ("island_vote", default 0.6),
                   edited by operator picks ("exclude_points" / "include_points": surface points; each resolves to
                   the island of the nearest face centre).
"""
import json
import sys
import time
from pathlib import Path

import bpy  # first: with the pip bpy module, bmesh and mathutils exist only after bpy is imported
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

T0 = time.time()
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
JOB_PATH = Path(argv[0]).resolve()
JOB_DIR = JOB_PATH.parent
OUT = JOB_DIR / "output"
job = json.loads(JOB_PATH.read_text())
report = {"ok": False, "blender_version": bpy.app.version_string, "operation": job["operation"], "params": job.get("params", {})}

# glTF (x, y, z) <-> Blender (x, -z, y)
def to_gltf(v):
    return [v[0], v[2], -v[1]]


def to_blender(p):
    return Vector((p[0], -p[2], p[1]))


def mesh_stats(ob):
    me = ob.data
    me.calc_loop_triangles()
    bm = bmesh.new()
    bm.from_mesh(me)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonmanifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    bm.free()
    ws = [to_gltf(ob.matrix_world @ v.co) for v in me.vertices]  # convert first, then bound (the axis flip swaps min/max)
    lo = [min(c[i] for c in ws) for i in range(3)] if ws else None
    hi = [max(c[i] for c in ws) for i in range(3)] if ws else None
    return {"vertices": len(me.vertices), "edges": len(me.edges), "polygons": len(me.polygons), "triangles": len(me.loop_triangles),
            "boundary_edges": boundary, "nonmanifold_edges": nonmanifold, "uv_layers": [u.name for u in me.uv_layers],
            "materials": [m.name if m else None for m in me.materials],
            "shape_keys": [k.name for k in me.shape_keys.key_blocks] if me.shape_keys else [],
            "vertex_groups": len(ob.vertex_groups),
            "bbox_gltf_min": [round(x, 5) for x in lo] if lo else None, "bbox_gltf_max": [round(x, 5) for x in hi] if hi else None}


def material_info(m):
    info = {"name": m.name, "images": []}
    if m.node_tree:
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                info["base_color"] = [round(x, 4) for x in n.inputs["Base Color"].default_value]
                info["metallic"] = round(n.inputs["Metallic"].default_value, 4)
                info["roughness"] = round(n.inputs["Roughness"].default_value, 4)
            if n.type == "TEX_IMAGE" and n.image:
                info["images"].append(n.image.name)
    return info


def scene_report():
    obs = []
    for ob in bpy.data.objects:
        d = {"name": ob.name, "type": ob.type, "parent": ob.parent.name if ob.parent else None,
             "matrix_world": [list(map(lambda x: round(x, 6), r)) for r in ob.matrix_world]}
        if ob.type == "MESH":
            d["mesh"] = mesh_stats(ob)
        if ob.type == "ARMATURE":
            d["bones"] = len(ob.data.bones)
        obs.append(d)
    return {"objects": obs, "materials": [material_info(m) for m in bpy.data.materials],
            "images": [{"name": i.name, "size": list(i.size)} for i in bpy.data.images],
            "actions": [a.name for a in bpy.data.actions]}


def export(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    path = OUT / name
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_yup=True, export_apply=True)
    return {"file": name, "bytes": path.stat().st_size}


def in_boxes(p, boxes):
    for b in boxes:
        d = [p[i] - b["centre"][i] for i in range(3)]
        if all(abs(sum(d[i] * b["axes"][k][i] for i in range(3))) <= b["half"][k] for k in range(3)):
            return True
    return False


def uv_islands(bm):
    """Face -> island id, faces joined across an edge only where both sides share the UVs (Select Linked, delimit UV)."""
    uv = bm.loops.layers.uv.active
    lab, k = {}, 0
    for f in bm.faces:
        if f in lab:
            continue
        lab[f], stack = k, [f]
        while stack:
            g = stack.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h is g or h in lab:
                        continue
                    a = {l.vert: l[uv].uv for l in g.loops if l.vert in e.verts}
                    b = {l.vert: l[uv].uv for l in h.loops if l.vert in e.verts}
                    if all((a[v] - b[v]).length < 1e-6 for v in a):
                        lab[h] = k
                        stack.append(h)
        k += 1
    return lab, k


def select_uv_islands(bm, params):
    """Whole UV islands: those with >= island_vote of their faces in the boxes, minus islands hit by exclude_points,
    plus islands hit by include_points (a point resolves to the island of the nearest face centre)."""
    lab, n = uv_islands(bm)
    faces = list(bm.faces)
    cen = [to_gltf(f.calc_center_median()) for f in faces]
    tot, ins = [0] * n, [0] * n
    for f, c in zip(faces, cen):
        tot[lab[f]] += 1
        ins[lab[f]] += in_boxes(c, params["boxes"])
    take = {i for i in range(n) if ins[i] >= params.get("island_vote", 0.6) * tot[i]}

    def island_at(p):
        j = min(range(len(faces)), key=lambda i: sum((cen[i][d] - p[d]) ** 2 for d in range(3)))
        return lab[faces[j]]
    picks = {}
    for name, p in params.get("exclude_points", {}).items():
        picks[name] = ("exclude", island_at(p))
        take.discard(picks[name][1])
    for name, p in params.get("include_points", {}).items():
        picks[name] = ("include", island_at(p))
        take.add(picks[name][1])
    keep = {f for f in faces if lab[f] in take}
    return keep, {"uv_islands": n, "islands_taken": len(take), "picks": {k: {"action": a, "island_faces": tot[i]} for k, (a, i) in picks.items()}}


def extract_region(src, params):
    boxes = params["boxes"]
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.transform(src.matrix_world)
    info = {}
    if params.get("select", "faces") == "uv_islands":
        keep, info = select_uv_islands(bm, params)
        drop = [f for f in bm.faces if f not in keep]
    else:
        inside = {v.index: in_boxes(to_gltf(v.co), boxes) for v in bm.verts}
        drop = [f for f in bm.faces if not all(inside[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    parts = []
    if bm.faces:
        seen = set()  # BMFace objects (indices are stale after the deletions above)
        for f in bm.faces:
            if f in seen:
                continue
            comp, stack = [], [f]
            while stack:
                g = stack.pop()
                if g in seen:
                    continue
                seen.add(g)
                comp.append(g)
                stack += [h for e in g.edges for h in e.link_faces if h not in seen]
            parts.append(comp)
        parts.sort(key=len, reverse=True)
        if params.get("keep_largest", True):
            bmesh.ops.delete(bm, geom=[g for comp in parts[1:] for g in comp], context="FACES")
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    me = bpy.data.meshes.new(src.data.name + "_region")
    bm.to_mesh(me)
    bm.free()
    for m in src.data.materials:
        me.materials.append(m)
    ob = bpy.data.objects.new(src.name + "_region", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob, {**info, "parts": len(parts) or None, "kept_part_faces": len(parts[0]) if parts else None}


try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    t = time.time()
    # extract_region and simplify weld UV-seam duplicates on import (merge_vertices) so connectivity follows the surface, not the
    # UV layout; UVs survive because Blender stores them per face corner
    # (simplify too: decimating the seam-split import cracked the closed shell into 4,240 pieces; measured)
    merge = job["operation"] in ("extract_region", "simplify") and job.get("params", {}).get("merge_vertices", True)
    bpy.ops.import_scene.gltf(filepath=str(JOB_DIR / job["input"]), merge_vertices=merge)
    report["import_merge_vertices"] = merge
    if merge:  # the importer's merge keeps vertices whose normals/UVs differ (measured: 504,919 -> 487,197, still
        # 383,648 open edges); weld by position explicitly. UVs live on face corners, so they are kept.
        dist = float(job.get("params", {}).get("weld_distance", 1e-6))
        for o in [o for o in bpy.data.objects if o.type == "MESH"]:
            bm = bmesh.new()
            bm.from_mesh(o.data)
            n0 = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
            bm.to_mesh(o.data)
            bm.free()
            o.data.update()
            report.setdefault("weld", {})[o.name] = {"distance": dist, "vertices_before": n0, "vertices_after": len(o.data.vertices)}
    report["import_seconds"] = round(time.time() - t, 2)
    report["scene"] = scene_report()
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    op, params = job["operation"], job.get("params", {})
    if op == "roundtrip":
        report["export"] = export(meshes, job["output"])
    elif op == "simplify":
        t = time.time()
        for o in meshes:
            mod = o.modifiers.new("forge_decimate", "DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = float(params["ratio"])
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.modifier_apply(modifier=mod.name)
        report["op_seconds"] = round(time.time() - t, 2)
        report["result"] = {o.name: mesh_stats(o) for o in meshes}
        report["export"] = export(meshes, job["output"])
    elif op == "extract_region":
        if len(meshes) != 1:
            raise RuntimeError(f"extract_region expects one mesh object, found {len(meshes)}")
        t = time.time()
        ob, info = extract_region(meshes[0], params)
        report["op_seconds"] = round(time.time() - t, 2)
        report["result"] = {**info, **mesh_stats(ob)}
        before = next(o["mesh"]["polygons"] for o in report["scene"]["objects"] if o["name"] == meshes[0].name)
        report["source_object_unchanged"] = len(meshes[0].data.polygons) == before
        report["export"] = export([ob], job["output"])
    report["ok"] = True
except Exception as e:  # reported, and the process exits non-zero
    import traceback
    report["error"] = f"{type(e).__name__}: {e}"
    report["traceback"] = traceback.format_exc()[-4000:]
report["seconds"] = round(time.time() - T0, 2)
OUT.mkdir(exist_ok=True)
(OUT / "report.json").write_text(json.dumps(report, indent=1))
print("FORGE_JOB_DONE", report["ok"])
sys.exit(0 if report["ok"] else 3)
