"""Read-only summaries of an ingested package: JSON-ready dict, text lines, and GUI detail sections.

Every value here is canonical package data (asset frame, meters). The viewer-space camera
transform never reaches this module.
"""

from __future__ import annotations

from forge_engine_viewer.ingest import IngestedPackage


def _v(values, digits: int = 6) -> str:
    return "(" + ", ".join(f"{c:.{digits}g}" for c in values) + ")"


def summary_dict(pkg: IngestedPackage) -> dict:
    c = pkg.coordinates
    return {
        "status": "valid",
        "package": pkg.path,
        "contract": {"id": pkg.contract_id, "version": pkg.contract_version},
        "asset": dict(pkg.asset),
        "presentation": {k: v for k, v in pkg.presentation.items() if k != "texcoord_0"},
        "exporter": pkg.package.get("exporter"),
        "coordinates": {"convention_id": c.get("convention_id"), "handedness": c["handedness"],
                        "up_axis": c["up_axis"], "units": c["units"], "meters_per_unit": c["meters_per_unit"],
                        "origin": c["origin"], "front_face_winding": c["front_face_winding"]},
        "render_scene": {"index": pkg.render_scene[0], "name": pkg.render_scene[1], "root": pkg.root,
                         "nodes": [m.node for m in pkg.meshes]},
        "materials": [{"name": m.name, "base_color_factor": list(m.base_color_factor),
                       "metallic_factor": m.metallic_factor, "roughness_factor": m.roughness_factor,
                       "preset": m.preset, "used_by": [x.node for x in pkg.meshes if x.material_index == m.index]}
                      for m in pkg.materials],
        "channels": pkg.channels,
        "sockets": [{"name": s.name, "node_index": s.node_index, "parent": s.parent,
                     "translation": list(s.world.translation), "rotation": list(s.world.rotation),
                     "frame": s.frame} for s in pkg.sockets],
        "collision": {"node": pkg.collision.node, "node_index": pkg.collision.node_index,
                      "scene": {"index": pkg.collision.scene_index, "name": pkg.collision.scene_name},
                      "representation": pkg.collision.representation, "vertices": len(pkg.collision.positions),
                      "triangles": pkg.collision.triangle_count, "closed": pkg.collision.closed},
        "lods": {"count": len(pkg.lods), "levels": [{"level": lv.level, "nodes": list(lv.nodes),
                                                     "vertices": lv.vertices, "triangles": lv.triangles}
                                                    for lv in pkg.lods], "note": pkg.lod_note},
        "hashes": {"glb_sha256": pkg.glb_sha256, "manifest_file_sha256": pkg.manifest_sha256,
                   "manifest_content_sha256": pkg.hashes["manifest_content_sha256"],
                   "semantic_sha256": pkg.hashes["semantic_sha256"],
                   "verified": list(pkg.hashes_verified), "provenance_not_verifiable": list(pkg.provenance_hashes)},
        "tags": list(pkg.tags),
        "checks": list(pkg.checks),
    }


def summary_lines(pkg: IngestedPackage) -> list[str]:
    d = summary_dict(pkg)
    a, c = d["asset"], d["coordinates"]
    lines = [
        "Forge Engine Viewer - package valid",
        f"  package            {pkg.path}",
        f"  contract           {pkg.contract_id} v{pkg.contract_version}",
        f"  asset              {a['asset_type']} ({a['display_name']})",
        f"  seed               {a['seed']}",
        f"  generator          {a['generator_id']} v{a['generator_version']}",
        f"  presentation       {pkg.presentation.get('presentation_id')} v{pkg.presentation.get('presentation_version')}",
        f"  exporter           {d['exporter']['format_id']}:{d['exporter']['format_version']}",
        f"  coordinates        {c['handedness']}-handed, {c['up_axis']} up, {c['units']} "
        f"(meters_per_unit {c['meters_per_unit']}), origin {c['origin']}",
        f"  convention         {c['convention_id']}",
        f"  render scene       {pkg.render_scene[0]} {pkg.render_scene[1]!r}: root {pkg.root}, "
        f"nodes {', '.join(m.node for m in pkg.meshes)}",
    ]
    for m in pkg.materials:
        lines.append(f"  material           {m.name}: baseColor {_v(m.base_color_factor, 4)}, "
                     f"metallic {m.metallic_factor:.4g}, roughness {m.roughness_factor:.4g}"
                     + (f" ({m.preset})" if m.preset else ""))
    for s in pkg.sockets:
        lines.append(f"  {s.name:<18} node {s.node_index}, translation {list(s.world.translation)} m, "
                     f"rotation {list(s.world.rotation)}")
    col = d["collision"]
    lines += [
        f"  collision          {col['node']} (node {col['node_index']}, scene {col['scene']['index']} "
        f"{col['scene']['name']!r}): {col['representation']}, {col['vertices']} vertices, {col['triangles']} triangles, "
        f"{'closed' if col['closed'] else 'OPEN'}",
        "  lod                " + "; ".join(f"LOD{lv['level']}: {len(lv['nodes'])} nodes, {lv['vertices']} vertices, "
                                          f"{lv['triangles']} triangles" for lv in d["lods"]["levels"])
        + " (LOD0 only)" * (d["lods"]["count"] == 1),
        f"  glb_sha256         {pkg.glb_sha256}",
        f"  manifest_sha256    {pkg.manifest_sha256} (file)",
        f"  manifest_content   {pkg.hashes['manifest_content_sha256']}",
        f"  hashes verified    {len(pkg.hashes_verified)}: {', '.join(pkg.hashes_verified)}",
        f"  provenance         {len(pkg.provenance_hashes)} source_* hashes reported, not verifiable from a package",
        f"  tags               {', '.join(pkg.tags)}",
        f"  checks passed      {len(pkg.checks)}: {', '.join(pkg.checks)}",
    ]
    return lines


def detail_sections(pkg: IngestedPackage) -> list[tuple[str, list[tuple[str, str]]]]:
    """Rows for the GUI side panel, grouped by section."""
    d = summary_dict(pkg)
    a, c, col = d["asset"], d["coordinates"], d["collision"]
    sections = [
        ("Asset", [("Type", f"{a['asset_type']} ({a['display_name']})"), ("Seed", a["seed"]),
                   ("Generator", f"{a['generator_id']} v{a['generator_version']}"),
                   ("Presentation", f"{pkg.presentation.get('presentation_id')} "
                                    f"v{pkg.presentation.get('presentation_version')}"),
                   ("Exporter", f"{d['exporter']['format_id']}:{d['exporter']['format_version']}"),
                   ("Tags", ", ".join(pkg.tags))]),
        ("Contract", [("Contract", f"{pkg.contract_id} v{pkg.contract_version}"),
                      ("Convention", str(c["convention_id"])),
                      ("Frame", f"{c['handedness']}-handed, {c['up_axis']} up"),
                      ("Units", f"{c['units']} (meters_per_unit {c['meters_per_unit']})"),
                      ("Origin", c["origin"]), ("Winding", c["front_face_winding"])]),
        ("Materials", [(m.name, f"base {_v(m.base_color_factor, 4)} · metallic {m.metallic_factor:.4g} · "
                                f"roughness {m.roughness_factor:.4g}" + (f" · {m.preset}" if m.preset else ""))
                       for m in pkg.materials]
         + [("Channels", ", ".join(f"{k}={v}" for k, v in sorted(pkg.channels.get("populated", {}).items())))]),
        ("Sockets", [(s.name, f"{list(s.world.translation)} m · rotation {list(s.world.rotation)} · "
                              f"node {s.node_index} (from the GLB node hierarchy)") for s in pkg.sockets]),
        ("Collision", [("Node", f"{col['node']} (node {col['node_index']}, scene {col['scene']['index']} "
                                f"{col['scene']['name']})"),
                       ("Representation", col["representation"]),
                       ("Mesh", f"{col['vertices']} vertices · {col['triangles']} triangles · "
                                f"{'closed' if col['closed'] else 'open'}")]),
        ("LOD", [(f"LOD{lv['level']}", f"{', '.join(lv['nodes'])} · {lv['vertices']} vertices · "
                                       f"{lv['triangles']} triangles") for lv in d["lods"]["levels"]]
         + [("Levels", f"{d['lods']['count']} (LOD0 only)" if d["lods"]["count"] == 1 else str(d["lods"]["count"]))]),
        ("Hashes", [("glb_sha256", pkg.glb_sha256), ("manifest file", pkg.manifest_sha256),
                    ("manifest content", pkg.hashes["manifest_content_sha256"]),
                    ("Verified", f"{len(pkg.hashes_verified)} of {len(pkg.hashes) - len(pkg.provenance_hashes)} "
                                 "package-verifiable hashes"),
                    ("Provenance", f"{len(pkg.provenance_hashes)} source_* (not verifiable from a package)")]),
        ("Validation", [("Checks", f"{len(pkg.checks)} passed"), ("Last", pkg.checks[-1])]),
    ]
    return sections
