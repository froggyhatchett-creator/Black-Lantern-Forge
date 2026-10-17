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
  rig_roundtrip    the same for a skinned, animated character: rig report (bones, hierarchy, rest matrices, weights,
                   shape keys, actions, NLA, materials), then export meshes + armature with skins, morphs and
                   animations. params: scene_fps (set before import), import_options, export_options (recorded)
  weights_smooth_copy  duplicate one skinned mesh, smooth ONE bone's weights on the copy (Smooth, Normalize All,
                   Limit Total 4), export the character with the copy in place of the original; report what changed
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
from mathutils import Matrix, Vector  # noqa: E402

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


# Rigged-export contract (Phase 1.1, each measured against the source with rig_compare.py):
# - no forced sampling: the actions' own keys are written, so channel sets, key counts and key times stay exactly the
#   source's (sampling added constant 2-key channels for all 62 joints x T/R/S: 186 per clip);
# - no "keep animated armature" padding;
# - extras on: the per-joint metadata (humanoid mapping, secondary_motion) survives (it was dropped in Phase 1).
# Limitation: unsampled export writes keyframes as they are; actions driven by constraints or drivers would need
# sampling (none in Forge's clips).
RIG_EXPORT = {"export_apply": False, "export_skins": True, "export_morph": True, "export_animations": True,
              "export_animation_mode": "ACTIONS", "export_force_sampling": False,
              "export_optimize_animation_keep_anim_armature": False, "export_extras": True}


def detect_fps(path):
    """Frame rate of a GLB's animations from its own key times (read directly from the file, before Blender sees it):
    the smallest common rate at which every key lands on a whole frame (within 1e-4 frame)."""
    import struct
    b = Path(path).read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    g = json.loads(b[20:20 + jl])
    bin_off = 20 + jl + 8
    times = set()
    for a in g.get("animations", []):
        for smp in a["samplers"]:
            acc = g["accessors"][smp["input"]]
            bv = g["bufferViews"][acc["bufferView"]]
            off = bin_off + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            times.update(struct.unpack_from(f"<{acc['count']}f", b, off))
    info = {"key_times": len(times), "clips": [a.get("name") for a in g.get("animations", [])]}
    if not times:
        return info
    for fps in (24, 25, 30, 48, 50, 60, 120):
        if all(abs(t * fps - round(t * fps)) < 1e-4 * max(1.0, t * fps) for t in times):
            info["fps"] = fps
            return info
    return info


def export(objs, name, **options):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    path = OUT / name
    opts = {"export_format": "GLB", "use_selection": True, "export_yup": True, "export_apply": True, **options}
    bpy.ops.export_scene.gltf(filepath=str(path), **opts)
    return {"file": name, "bytes": path.stat().st_size, "options": {k: v for k, v in opts.items()}}


def r6(v):
    return [round(float(x), 6) for x in v]


def rig_report():
    """Armatures (bones, hierarchy, rest matrices in glTF axes), skin weights, shape keys, actions/NLA, materials."""
    C = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))  # Blender Z-up -> glTF Y-up
    out = {"scene_fps": bpy.context.scene.render.fps / bpy.context.scene.render.fps_base, "armatures": {}, "meshes": {}, "actions": {}, "materials": {}}
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE":
            bones = ob.data.bones
            out["armatures"][ob.name] = {
                "bones": len(bones), "roots": [b.name for b in bones if not b.parent],
                "parents": {b.name: (b.parent.name if b.parent else None) for b in bones},
                "rest_world_gltf": {b.name: [r6(r) for r in (C @ ob.matrix_world @ b.matrix_local)] for b in bones},
                "nla_tracks": [{"name": t.name, "strips": [st.action.name for st in t.strips if st.action]} for t in (ob.animation_data.nla_tracks if ob.animation_data else [])],
                "active_action": ob.animation_data.action.name if ob.animation_data and ob.animation_data.action else None}
        if ob.type == "MESH":
            me = ob.data
            groups = {g.index: g.name for g in ob.vertex_groups}
            infl = [len([g for g in v.groups if g.weight > 0]) for v in me.vertices]
            sums = [sum(g.weight for g in v.groups) for v in me.vertices]
            keys = {}
            if me.shape_keys:
                basis = me.shape_keys.reference_key
                for k in me.shape_keys.key_blocks:
                    if k == basis:
                        continue
                    d = [(a.co - b.co).length for a, b in zip(k.data, basis.data)]
                    keys[k.name] = {"moved_vertices": sum(1 for x in d if x > 1e-7), "max_m": round(max(d), 6)}
            out["meshes"][ob.name] = {"vertices": len(me.vertices), "vertex_groups": len(groups),
                                      "armature_modifier": [m.object.name if m.object else None for m in ob.modifiers if m.type == "ARMATURE"],
                                      "max_influences": max(infl) if infl else 0, "weight_sum_min_max": [round(min(sums), 6), round(max(sums), 6)] if sums else None,
                                      "shape_keys": keys, "color_attributes": [a.name for a in me.color_attributes], "uv_layers": [u.name for u in me.uv_layers]}
    for a in bpy.data.actions:
        curves = [fc for layer in getattr(a, "layers", []) for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves] or list(getattr(a, "fcurves", []))
        out["actions"][a.name] = {"frame_range": r6(a.frame_range), "fcurves": len(curves),
                                  "keyframes": sum(len(fc.keyframe_points) for fc in curves),
                                  "interpolations": sorted({k.interpolation for fc in curves for k in fc.keyframe_points})}
    for m in bpy.data.materials:
        texs = {}
        if m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    texs[n.image.name] = [l.to_socket.name for o in n.outputs for l in o.links]
        out["materials"][m.name] = {"textures": texs, "render_method": getattr(m, "surface_render_method", None)}
    out["images"] = {i.name: list(i.size) for i in bpy.data.images}
    return out


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
    params = job.get("params", {})
    # the importer converts key times to frames at the scene rate and the exporter samples whole frames: at a rate
    # that does not divide the key times, every clip is resampled and shortened (Phase 1: walk off by 74 mm)
    fps_info = detect_fps(JOB_DIR / job["input"])
    report["animation_timing"] = fps_info
    fps = params.get("scene_fps", fps_info.get("fps"))
    if params.get("scene_fps") and fps_info.get("fps") and int(params["scene_fps"]) != fps_info["fps"]:
        raise RuntimeError(f"scene_fps {params['scene_fps']} contradicts the source's key times ({fps_info['fps']} fps)")
    if fps:
        bpy.context.scene.render.fps, bpy.context.scene.render.fps_base = int(fps), 1.0
    elif fps_info["key_times"]:
        raise RuntimeError("animation key times fit no supported frame rate; refusing to resample them")
    bpy.ops.import_scene.gltf(filepath=str(JOB_DIR / job["input"]), merge_vertices=merge, **params.get("import_options", {}))
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
    if op == "weights_edit_seam_safe":
        # Seam-safe weight editing (Phase 1.1). glTF stores a vertex once per UV/normal seam side; Blender's weight
        # tools treat those copies as unconnected, so editing them directly cracks the posed mesh (Phase 1: 1.6 mm),
        # and welding the edited mesh destroys its per-corner normals (Phase 1: 1,062 vertices). Instead:
        #   1. the edit runs on a TEMPORARY welded proxy (one vertex per position: a connected surface);
        #   2. the result is written back to a copy of the original mesh by vertex position, so every seam copy gets
        #      identical weights; the copy's geometry, UVs, normals, topology and materials are never touched;
        #   3. the proxy is deleted; the original object is renamed, left unchanged and out of the export.
        mesh_name = params.get("mesh", "body")
        src = bpy.data.objects[mesh_name]
        before = {v.index: {src.vertex_groups[g.group].name: g.weight for g in v.groups} for v in src.data.vertices}
        cp = src.copy()
        cp.data = src.data.copy()
        bpy.context.scene.collection.objects.link(cp)
        proxy = src.copy()
        proxy.data = src.data.copy()
        bpy.context.scene.collection.objects.link(proxy)
        proxy.data.shape_keys and proxy.shape_key_clear()
        bm = bmesh.new()
        bm.from_mesh(proxy.data)
        n0 = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bm.to_mesh(proxy.data)
        bm.free()
        proxy.data.update()
        report["proxy"] = {"vertices_before_weld": n0, "vertices_after_weld": len(proxy.data.vertices)}
        bpy.ops.object.select_all(action="DESELECT")
        proxy.select_set(True)
        bpy.context.view_layer.objects.active = proxy
        proxy.vertex_groups.active_index = proxy.vertex_groups[params["group"]].index
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")  # the vertex-group tools refuse Object mode when headless
        t = time.time()
        bpy.ops.object.vertex_group_smooth(group_select_mode="ACTIVE", factor=float(params.get("factor", 0.5)), repeat=int(params.get("repeat", 2)))
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="BONE_DEFORM", lock_active=False)
        bpy.ops.object.vertex_group_limit_total(group_select_mode="BONE_DEFORM", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="BONE_DEFORM", lock_active=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        key = lambda co: tuple(round(c * 1e6) for c in co)
        pw = {key(v.co): {proxy.vertex_groups[g.group].name: g.weight for g in v.groups if g.weight > 0} for v in proxy.data.vertices}
        missing = 0
        for v in cp.data.vertices:  # write back: replace this vertex's deform weights with the proxy's at its position
            w = pw.get(key(v.co))
            if w is None:
                missing += 1
                continue
            for g in list(v.groups):
                cp.vertex_groups[g.group].remove([v.index])
            for name, wt in w.items():
                cp.vertex_groups[name].add([v.index], wt, "REPLACE")
        if missing:
            raise RuntimeError(f"{missing} vertices had no proxy vertex at their position")
        report["op_seconds"] = round(time.time() - t, 3)
        bpy.data.objects.remove(proxy, do_unlink=True)
        src.name, src.data.name = mesh_name + "_original", src.data.name + "_original"
        cp.name, cp.data.name = mesh_name, mesh_name
        after = {v.index: {cp.vertex_groups[g.group].name: g.weight for g in v.groups if g.weight > 0} for v in cp.data.vertices}
        diff = [max(abs(after[i].get(k, 0) - before[i].get(k, 0)) for k in set(before[i]) | set(after[i])) for i in before]
        seams = {}
        for v in cp.data.vertices:
            seams.setdefault(key(v.co), []).append(after[v.index])
        seam_mismatch = sum(1 for ws in seams.values() if len(ws) > 1 and any(w != ws[0] for w in ws[1:]))
        report["weights"] = {"group": params["group"], "vertices": len(diff), "changed_vertices": sum(1 for d in diff if d > 1e-6),
                             "max_change": round(max(diff), 6), "max_influences_after": max(len(a) for a in after.values()),
                             "weight_sum_min_max_after": [round(min(sum(a.values()) for a in after.values()), 6), round(max(sum(a.values()) for a in after.values()), 6)],
                             "seam_groups": sum(1 for ws in seams.values() if len(ws) > 1), "seam_groups_with_different_weights": seam_mismatch,
                             "geometry_unchanged": all((a.co - b.co).length == 0 for a, b in zip(src.data.vertices, cp.data.vertices)),
                             "original_object_unchanged": all({src.vertex_groups[g.group].name: g.weight for g in v.groups} == before[v.index] for v in src.data.vertices)}
        shapes = {pb.custom_shape for a in bpy.data.objects if a.type == "ARMATURE" for pb in a.pose.bones if pb.custom_shape}
        allobs = [o for o in bpy.data.objects if o.type in ("MESH", "ARMATURE") and o not in shapes and o is not src]
        report["export"] = export(allobs, job["output"], **{**RIG_EXPORT, **params.get("export_options", {})})
    elif op == "weights_smooth_copy":
        # non-destructive: the mesh is duplicated, the ORIGINAL object is renamed and left out of the export, and only
        # the copy's weights are edited (smooth one bone's group, renormalize, limit to 4 influences)
        src = bpy.data.objects[params.get("mesh", "body")]
        arm = src.find_armature()
        before = {v.index: {src.vertex_groups[g.group].name: g.weight for g in v.groups} for v in src.data.vertices}
        cp = src.copy()
        cp.data = src.data.copy()
        bpy.context.scene.collection.objects.link(cp)
        src.name, src.data.name = src.name + "_original", src.data.name + "_original"
        cp.name, cp.data.name = params.get("mesh", "body"), params.get("mesh", "body")
        bpy.ops.object.select_all(action="DESELECT")
        cp.select_set(True)
        bpy.context.view_layer.objects.active = cp
        cp.vertex_groups.active_index = cp.vertex_groups[params["group"]].index
        if params.get("weld_before"):  # optional mitigation: glTF seam copies are separate vertices to Blender's weight
            # tools, so smoothing gives the two sides of a UV seam different weights and the posed mesh cracks (measured)
            bm = bmesh.new()
            bm.from_mesh(cp.data)
            n0 = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
            bm.to_mesh(cp.data)
            bm.free()
            cp.data.update()
            report["weld"] = {"vertices_before": n0, "vertices_after": len(cp.data.vertices)}
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")  # the vertex-group tools refuse Object mode when headless (measured)
        t = time.time()
        bpy.ops.object.vertex_group_smooth(group_select_mode="ACTIVE", factor=float(params.get("factor", 0.5)), repeat=int(params.get("repeat", 2)))
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="BONE_DEFORM", lock_active=False)
        bpy.ops.object.vertex_group_limit_total(group_select_mode="BONE_DEFORM", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="BONE_DEFORM", lock_active=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        report["op_seconds"] = round(time.time() - t, 3)
        pos = {tuple(round(c, 6) for c in v.co): v.index for v in cp.data.vertices}
        after_cp = {v.index: {cp.vertex_groups[g.group].name: g.weight for g in v.groups if g.weight > 0} for v in cp.data.vertices}
        after = {v.index: after_cp[pos[tuple(round(c, 6) for c in v.co)]] for v in src.data.vertices}  # per ORIGINAL vertex
        diff = [max(abs(after[i].get(k, 0) - before[i].get(k, 0)) for k in set(before[i]) | set(after[i])) for i in before]
        report["weights"] = {"group": params["group"], "vertices": len(diff), "changed_vertices": sum(1 for d in diff if d > 1e-6),
                             "max_change": round(max(diff), 6), "groups_touched": sorted({k for i in before for k in set(before[i]) | set(after[i])
                                                                                          if abs(after[i].get(k, 0) - before[i].get(k, 0)) > 1e-6}),
                             "max_influences_after": max(len(a) for a in after.values()),
                             "weight_sum_min_max_after": [round(min(sum(a.values()) for a in after.values()), 6), round(max(sum(a.values()) for a in after.values()), 6)],
                             "original_object_unchanged": all({src.vertex_groups[g.group].name: g.weight for g in v.groups} == before[v.index] for v in src.data.vertices)}
        shapes = {pb.custom_shape for a in bpy.data.objects if a.type == "ARMATURE" for pb in a.pose.bones if pb.custom_shape}
        allobs = [o for o in bpy.data.objects if o.type in ("MESH", "ARMATURE") and o not in shapes and o is not src]
        opts = {**RIG_EXPORT, **params.get("export_options", {})}
        report["export"] = export(allobs, job["output"], **opts)
    elif op == "rig_roundtrip":
        report["rig"] = rig_report()
        # the importer adds bone display shapes (an "Icosphere" mesh used as pose-bone custom shapes); they are not
        # part of the character and must not be exported
        shapes = {pb.custom_shape for a in bpy.data.objects if a.type == "ARMATURE" for pb in a.pose.bones if pb.custom_shape}
        allobs = [o for o in bpy.data.objects if o.type in ("MESH", "ARMATURE", "EMPTY") and o not in shapes]
        report["excluded_import_helpers"] = sorted(o.name for o in shapes)
        opts = {**RIG_EXPORT, **params.get("export_options", {})}
        report["export"] = export(allobs, job["output"], **opts)
    elif op == "roundtrip":
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
