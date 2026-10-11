"""Enriched OBJ + MTL export (obj_format 2). Opt-in; obj_format 1 is unchanged.

obj_format 2 = obj_format 1 plus presentation data:
  * header also records presentation/normals/uv/material versions and `mtllib`
  * per component, in COMPONENT_ORDER:
      o <component>
      v  ...   identical lines, in identical order, to obj_format 1
      vt u v   the component's unique UVs (6 decimals)
      vn x y z the component's unique normals (6 decimals; re-normalize on import if needed)
      usemtl forge_<component>
      s off
      f v/vt/vn ...   position indices exactly as in obj_format 1; global 1-based
  * the .mtl next to it holds one material per component: Kd, Ks, Ns (classic)
    plus Pr / Pm (widely supported PBR extension: roughness / metallic).
    Procedural patterns are recorded as comments; textures are not baked in Step 2.

Same presented sword -> same OBJ bytes and same MTL bytes.
"""

from __future__ import annotations

from pathlib import Path

from forge.errors import ExportError
from forge.export.obj import format_coord
from forge.hashing import canonical_json
from forge.presentation.model import PresentedSword
from forge.render.raster import shininess

OBJ_ENRICHED_FORMAT_VERSION = 2


def material_name(component: str) -> str:
    return f"forge_{component}"


def export_enriched_obj(presented: PresentedSword, mtl_filename: str) -> str:
    if not isinstance(presented, PresentedSword):
        raise ExportError(f"export_enriched_obj expects a PresentedSword; got {type(presented).__name__}")
    if "/" in mtl_filename or "\\" in mtl_filename or not mtl_filename.endswith(".mtl") or " " in mtl_filename:
        raise ExportError(f"mtl filename must be a bare name ending in .mtl without spaces; got {mtl_filename!r}")
    asset = presented.asset
    v = presented.versions
    lines = [
        "# Black Lantern Forge OBJ export",
        f"# obj_format: {OBJ_ENRICHED_FORMAT_VERSION}",
        f"# asset_type: {asset.asset_type}",
        f"# generator: {asset.generator}",
        f"# generator_version: {asset.generator_version}",
        f"# seed: {asset.seed}",
        f"# presentation_version: {v.presentation_version}",
        f"# normals_version: {v.normals_version}",
        f"# uv_version: {v.uv_version}",
        f"# material_version: {v.material_version}",
        "# units: meters",
        "# axes: right-handed, +Y up, blade tip +Y, blade edges +/-X, origin at grip center",
        "# winding: counter-clockwise front faces (outward normals)",
        f"# components: {' '.join(asset.component_names)}",
        f"# vertices: {asset.vertex_count}",
        f"# triangles: {asset.triangle_count}",
        f"mtllib {mtl_filename}",
    ]
    v_off = vt_off = vn_off = 1
    for mesh, comp in zip(asset.components, presented.components):
        lines.append(f"o {mesh.name}")
        for x, y, z in mesh.positions:
            lines.append(f"v {format_coord(x)} {format_coord(y)} {format_coord(z)}")
        for uu, vv in comp.uvs:
            lines.append(f"vt {format_coord(uu)} {format_coord(vv)}")
        for nx, ny, nz in comp.normals:
            lines.append(f"vn {format_coord(nx)} {format_coord(ny)} {format_coord(nz)}")
        lines.append(f"usemtl {material_name(mesh.name)}")
        lines.append("s off")
        for tri, ti, ni in zip(mesh.triangles, comp.uv_indices, comp.normal_indices):
            corners = (f"{tri[k] + v_off}/{ti[k] + vt_off}/{ni[k] + vn_off}" for k in range(3))
            lines.append("f " + " ".join(corners))
        v_off += mesh.vertex_count
        vt_off += len(comp.uvs)
        vn_off += len(comp.normals)
    return "\n".join(lines) + "\n"


def export_mtl(presented: PresentedSword) -> str:
    if not isinstance(presented, PresentedSword):
        raise ExportError(f"export_mtl expects a PresentedSword; got {type(presented).__name__}")
    lines = [
        "# Black Lantern Forge MTL export",
        f"# obj_format: {OBJ_ENRICHED_FORMAT_VERSION}",
        f"# material_version: {presented.versions.material_version}",
        "# Pr = roughness, Pm = metallic (PBR extension). Patterns are procedural and not baked.",
    ]
    for comp in presented.components:
        m = comp.material
        spec = tuple(0.04 + (c - 0.04) * m.metallic for c in m.base_color)
        lines += [
            "",
            f"newmtl {material_name(comp.name)}",
            f"# preset: {m.preset}",
            f"# pattern: {canonical_json(m.pattern.to_dict()).decode('ascii')}",
            "Kd " + " ".join(format_coord(c) for c in m.base_color),
            "Ks " + " ".join(format_coord(c) for c in spec),
            f"Ns {shininess(m.roughness)}",
            f"Pr {format_coord(m.roughness)}",
            f"Pm {format_coord(m.metallic)}",
            "d 1.000000",
            "illum 2",
        ]
    return "\n".join(lines) + "\n"


def write_enriched_obj(presented: PresentedSword, path: str | Path) -> tuple[Path, Path]:
    """Write <path> (.obj) and its sibling .mtl. Returns (obj_path, mtl_path)."""
    path = Path(path)
    if path.suffix.lower() != ".obj":
        raise ExportError(f"output path must end in .obj; got {str(path)!r}")
    mtl_path = path.with_suffix(".mtl")
    obj_text = export_enriched_obj(presented, mtl_path.name)
    mtl_text = export_mtl(presented)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(obj_text.encode("ascii"))
    mtl_path.write_bytes(mtl_text.encode("ascii"))
    return path, mtl_path
