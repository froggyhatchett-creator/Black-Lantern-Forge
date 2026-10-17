"""Blender side of the experimental Forge job bridge. Runs INSIDE Blender (application or pip bpy), never in Forge.

    blender --background --factory-startup --python job_blender.py -- <job dir>/job.json
    <python with bpy> -I job_blender.py <job dir>/job.json

Reads job.json from its own job directory, imports the (read-only) input, performs ONE operation and writes
output/report.json (+ output/<name>.glb). Coordinates in job parameters and reports are glTF / Forge coordinates
(metres, +Y up, +Z front); Blender's importer converts glTF Y-up to Blender Z-up, the exporter converts back.

STATUS: written against the documented bpy API of Blender 4.2-5.2 but NOT YET EXECUTED (no Blender in the
development container at the time of writing). Treat every result as unverified until run.

Operations
  inspect          objects, transforms, mesh counts, UV layers, materials/textures, armatures, shape keys, bounds
  simplify         params {"ratio": 0..1}: Decimate (collapse) on every mesh, then export
  extract_region   params {"boxes": [{"centre": [x,y,z], "axes": [[3],[3],[3]], "half": [hx,hy,hz]}, ...],
                           "keep_largest": true}: copy the faces whose three vertices lie in any oriented box into a
                   new object (the source object is not modified), optionally keep the largest connected part,
                   then export it. Cut boundaries are left OPEN and reported (no automatic capping).
"""
import json
import sys
import time
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

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
    ws = [ob.matrix_world @ v.co for v in me.vertices]
    lo = [min(c[i] for c in ws) for i in range(3)] if ws else None
    hi = [max(c[i] for c in ws) for i in range(3)] if ws else None
    return {"vertices": len(me.vertices), "edges": len(me.edges), "polygons": len(me.polygons), "triangles": len(me.loop_triangles),
            "boundary_edges": boundary, "nonmanifold_edges": nonmanifold, "uv_layers": [u.name for u in me.uv_layers],
            "materials": [m.name if m else None for m in me.materials],
            "shape_keys": [k.name for k in me.shape_keys.key_blocks] if me.shape_keys else [],
            "vertex_groups": len(ob.vertex_groups),
            "bbox_gltf_min": [round(x, 5) for x in to_gltf(lo)] if lo else None, "bbox_gltf_max": [round(x, 5) for x in to_gltf(hi)] if hi else None}


def material_info(m):
    info = {"name": m.name, "use_nodes": m.use_nodes, "images": []}
    if m.use_nodes:
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


def extract_region(src, params):
    boxes = params["boxes"]
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.transform(src.matrix_world)
    inside = {v.index: in_boxes(to_gltf(v.co), boxes) for v in bm.verts}
    drop = [f for f in bm.faces if not all(inside[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    parts = []
    if params.get("keep_largest", True) and bm.faces:
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
        bmesh.ops.delete(bm, geom=[g for comp in parts[1:] for g in comp], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    me = bpy.data.meshes.new(src.data.name + "_region")
    bm.to_mesh(me)
    bm.free()
    for m in src.data.materials:
        me.materials.append(m)
    ob = bpy.data.objects.new(src.name + "_region", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob, {"parts_in_boxes": len(parts) or None, "kept_part_faces": len(parts[0]) if parts else None}


try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    t = time.time()
    # extract_region welds UV-seam duplicates on import (merge_vertices) so connectivity follows the surface, not the
    # UV layout; UVs survive because Blender stores them per face corner
    merge = job["operation"] == "extract_region" and job.get("params", {}).get("merge_vertices", True)
    bpy.ops.import_scene.gltf(filepath=str(JOB_DIR / job["input"]), merge_vertices=merge)
    report["import_merge_vertices"] = merge
    report["import_seconds"] = round(time.time() - t, 2)
    report["scene"] = scene_report()
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    op, params = job["operation"], job.get("params", {})
    if op == "simplify":
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
