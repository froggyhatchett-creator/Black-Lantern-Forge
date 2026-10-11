"""Blade-family presentation: forge.blade-presentation v1 (normals 1, uv 1, material 1).

This is a separate presentation family from the frozen forge.presentation v1, which accepts only
the short sword and keys its tables to the sword's components and its seed. This family serves
dagger, long_sword, curved_sword and great_sword. It reads the frozen geometry and never writes it.

Its output uses the same container as the frozen family (forge.presentation.model.PresentedSword:
face-varying normals and UVs plus one Material per component). Records, previews, OBJ format 2
and engine packages therefore consume it unchanged.

normals_version 1 (this family)
  The same face-normal and crease rules as forge.presentation normals v1, with a per-family
  table of modes:
    blade   faceted, for the straight families: keeps the ridge and bevels crisp, as on the
            short sword
            crease 0.94 (about 20 deg), for curved_sword: smooths along the curve (each segment
            turns well under 5 deg) but keeps the spine (90 deg) and the edge bevel (over
            25 deg) hard
    guard   crease 30 deg     grip   crease 60 deg     pommel   crease 30 deg
uv_version 1 (this family)
  The same box and cylindrical projections as forge.presentation uv v1, with the projection
  chosen per component and shape:
    blade, guard          box
    grip                  cylindrical
    pommel                cylindrical, or box for a wheel pommel, whose axis is Z
  For curved blades, box mapping projects the flats (which face +-Z) orthographically, so the
  curve introduces no distortion. Every value is in [0, 1].
material_version 1 (this family)
  The frozen Material and pattern classes (brushed blade, patina guard and pommel, wrap grip),
  drawn from per-family palettes. Each component has its own PCG32 stream, labelled
  "forge.blade-presentation.material.v1.<asset_type>.<component>". Materials therefore differ
  between families for the same seed, and they can never shift any geometry stream.
  Draw order: the same as forge.presentation material v1:
    preset, tint, roughness_jitter, pattern draws
    pommel: match_guard (3 in 4), then preset (always drawn), then the rest
Only + - * / and sqrt are used.
"""

from __future__ import annotations

import math
from types import MappingProxyType

from forge.blades.model import BladeAsset
from forge.errors import PresentationError
from forge.mesh import Mesh, Tri, Vec3
from forge.presentation.materials import (
    BRUSHED_STRENGTH,
    PATINA_STRENGTH,
    ROUGHNESS_JITTER,
    TINT_RANGE,
    WRAP_BANDS,
    WRAP_CONTRAST,
    BrushedPattern,
    Material,
    PatinaPattern,
    WrapPattern,
    validate_material,
)
from forge.presentation.model import ComponentPresentation, PresentationVersions, PresentedSword
from forge.presentation.normals import raw_face_normals
from forge.presentation.uv import diamond_angle
from forge.prng import derive_stream
from forge.versioning import require_version

PRESENTATION_ID = "forge.blade-presentation"
BLADE_PRESENTATION_V1 = PresentationVersions(presentation_version=1, normals_version=1, uv_version=1,
                                             material_version=1)
MATERIAL_STREAM_PREFIX = "forge.blade-presentation.material.v1."
COS_30 = math.sqrt(3.0) * 0.5
COS_60 = 0.5
CURVED_BLADE_CREASE = 0.94

_STRAIGHT = MappingProxyType({"blade": ("faceted", 1.0), "guard": ("crease", COS_30), "grip": ("crease", COS_60),
                              "pommel": ("crease", COS_30)})
NORMAL_MODES = MappingProxyType({
    "dagger": _STRAIGHT,
    "long_sword": _STRAIGHT,
    "great_sword": _STRAIGHT,
    "curved_sword": MappingProxyType({**_STRAIGHT, "blade": ("crease", CURVED_BLADE_CREASE)}),
})

# (preset, linear RGB, metallic, roughness)
_STEEL = (
    ("bright_steel", (0.78, 0.80, 0.83), 1.0, 0.22),
    ("grey_steel", (0.62, 0.64, 0.66), 1.0, 0.30),
    ("dark_iron", (0.40, 0.40, 0.42), 1.0, 0.42),
)
_HILT_METAL = (
    ("brass", (0.86, 0.69, 0.38), 1.0, 0.32),
    ("bronze", (0.74, 0.50, 0.28), 1.0, 0.38),
    ("steel", (0.70, 0.72, 0.75), 1.0, 0.28),
    ("blackened_steel", (0.20, 0.20, 0.22), 1.0, 0.50),
)
_LEATHER = (
    ("brown_leather", (0.32, 0.19, 0.11), 0.0, 0.72),
    ("black_leather", (0.09, 0.08, 0.08), 0.0, 0.62),
    ("oxblood_leather", (0.36, 0.09, 0.08), 0.0, 0.66),
)
_WOOD = ("dark_wood", (0.27, 0.17, 0.10), 0.0, 0.70)
_CORD = ("cord_wrap", (0.56, 0.47, 0.34), 0.0, 0.88)
PALETTES_V1 = MappingProxyType({
    "dagger": MappingProxyType({"blade": _STEEL + (("bronze", (0.80, 0.57, 0.34), 1.0, 0.30),),
                                "guard": _HILT_METAL,
                                "grip": _LEATHER[:2] + (_WOOD, ("horn", (0.30, 0.26, 0.20), 0.0, 0.45)),
                                "pommel": _HILT_METAL}),
    "long_sword": MappingProxyType({"blade": _STEEL + (("blued_steel", (0.42, 0.49, 0.60), 1.0, 0.30),),
                                    "guard": _HILT_METAL, "grip": _LEATHER + (_CORD,), "pommel": _HILT_METAL}),
    "curved_sword": MappingProxyType({"blade": _STEEL + (("polished_steel", (0.82, 0.83, 0.85), 1.0, 0.16),),
                                      "guard": _HILT_METAL,
                                      "grip": (_CORD, ("black_cord", (0.08, 0.08, 0.09), 0.0, 0.80),
                                               _LEATHER[0], ("pale_wrap", (0.72, 0.66, 0.55), 0.0, 0.85)),
                                      "pommel": _HILT_METAL}),
    "great_sword": MappingProxyType({"blade": _STEEL + (("blackened_steel", (0.20, 0.20, 0.22), 1.0, 0.50),),
                                     "guard": _HILT_METAL, "grip": _LEATHER[:2] + (_WOOD, _CORD),
                                     "pommel": _HILT_METAL}),
})


# ------------------------------------------------------------------ normals

def _unit(v: Vec3, what: str) -> Vec3:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not (length > 0.0 and math.isfinite(length)):
        raise PresentationError(f"cannot normalize {what}: {v!r}")
    return (v[0] / length, v[1] / length, v[2] / length)


def _dedupe(corners):
    index, values, triples = {}, [], []
    for tri in corners:
        ids = []
        for value in tri:
            i = index.get(value)
            if i is None:
                i = index[value] = len(values)
                values.append(value)
            ids.append(i)
        triples.append((ids[0], ids[1], ids[2]))
    return tuple(values), tuple(triples)


def compute_normals(mesh: Mesh, mode: str, cos_limit: float) -> tuple[tuple[Vec3, ...], tuple[Tri, ...]]:
    raw = raw_face_normals(mesh)
    unit = [_unit(n, f"face normal of {mesh.name!r} triangle {f}") for f, n in enumerate(raw)]
    if mode == "faceted":
        return _dedupe([(u, u, u) for u in unit])
    incident: list[list[int]] = [[] for _ in range(mesh.vertex_count)]
    for f, tri in enumerate(mesh.triangles):
        for v in tri:
            incident[v].append(f)
    corners = []
    for f, tri in enumerate(mesh.triangles):
        uf = unit[f]
        out = []
        for v in tri:
            sx = sy = sz = 0.0
            for g in incident[v]:
                ug = unit[g]
                if ug[0] * uf[0] + ug[1] * uf[1] + ug[2] * uf[2] >= cos_limit:
                    rg = raw[g]
                    sx += rg[0]
                    sy += rg[1]
                    sz += rg[2]
            out.append(_unit((sx, sy, sz), f"smoothed normal at vertex {v}"))
        corners.append(tuple(out))
    return _dedupe(corners)


# ------------------------------------------------------------------ UVs

def _dominant_axis(n) -> str:
    ax, ay, az = abs(n[0]), abs(n[1]), abs(n[2])
    if ay >= ax and ay >= az:
        return "y"
    if az >= ax:
        return "z"
    return "x"


def compute_uvs(mesh: Mesh, mapping: str):
    (x0, y0, z0), (x1, y1, z1) = mesh.bounds()
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    if not (dx > 0.0 and dy > 0.0 and dz > 0.0):
        raise PresentationError(f"component {mesh.name!r} has a zero-extent axis; cannot map UVs")
    p = mesh.positions
    corners = []
    for tri, n in zip(mesh.triangles, raw_face_normals(mesh)):
        pts = [p[i] for i in tri]
        axis = _dominant_axis(n)
        if mapping == "box":
            if axis == "z":
                uvs = [((q[0] - x0) / dx, (q[1] - y0) / dy) for q in pts]
            elif axis == "x":
                uvs = [((q[2] - z0) / dz, (q[1] - y0) / dy) for q in pts]
            else:
                uvs = [((q[0] - x0) / dx, (q[2] - z0) / dz) for q in pts]
        else:
            if axis == "y" or any(q[0] == 0.0 and q[2] == 0.0 for q in pts):
                uvs = [((q[0] - x0) / dx, (q[2] - z0) / dz) for q in pts]
            else:
                us = [diamond_angle(q[0], q[2]) / 4.0 for q in pts]
                if max(us) - min(us) > 0.5:
                    us = [u + 1.0 if u < 0.5 else u for u in us]
                uvs = [(u, (q[1] - y0) / dy) for u, q in zip(us, pts)]
        for uv in uvs:
            if not (0.0 <= uv[0] <= 1.0 and 0.0 <= uv[1] <= 1.0):
                raise PresentationError(f"component {mesh.name!r}: UV {uv!r} outside [0, 1]")
        corners.append(tuple(uvs))
    return _dedupe(corners)


def uv_mapping(asset: BladeAsset, component: str) -> str:
    if component == "grip" or (component == "pommel" and asset.params.pommel.shape != "wheel"):
        return "cylindrical"
    return "box"


# ------------------------------------------------------------------ materials

def _finish(preset, rng):
    name, color, metallic, roughness = preset
    k = 1.0 + rng.uniform(*TINT_RANGE)
    jitter = rng.uniform(*ROUGHNESS_JITTER)
    return name, (color[0] * k, color[1] * k, color[2] * k), metallic, roughness + jitter


def select_materials(asset_type: str, seed: int) -> dict[str, Material]:
    if asset_type not in PALETTES_V1:
        raise PresentationError(f"no blade-presentation palette for {asset_type!r}")
    pal = PALETTES_V1[asset_type]
    prefix = MATERIAL_STREAM_PREFIX + asset_type + "."
    out = {}
    r = derive_stream(seed, prefix + "blade")
    name, color, metal, rough = _finish(r.choice(pal["blade"]), r)
    out["blade"] = Material("blade", name, color, metal, rough,
                            BrushedPattern(seed=r.next_u32(), strength=r.uniform(*BRUSHED_STRENGTH)))
    r = derive_stream(seed, prefix + "guard")
    guard_preset = r.choice(pal["guard"])
    name, color, metal, rough = _finish(guard_preset, r)
    out["guard"] = Material("guard", name, color, metal, rough,
                            PatinaPattern(seed=r.next_u32(), strength=r.uniform(*PATINA_STRENGTH)))
    r = derive_stream(seed, prefix + "grip")
    name, color, metal, rough = _finish(r.choice(pal["grip"]), r)
    lo, hi = WRAP_BANDS
    out["grip"] = Material("grip", name, color, metal, rough, WrapPattern(
        seed=r.next_u32(), bands=lo + r.next_bounded(hi - lo + 1), contrast=r.uniform(*WRAP_CONTRAST),
        twist=r.next_bounded(2)))
    r = derive_stream(seed, prefix + "pommel")
    match_guard = r.next_bounded(4) != 0
    drawn = r.choice(pal["pommel"])
    name, color, metal, rough = _finish(guard_preset if match_guard else drawn, r)
    out["pommel"] = Material("pommel", name, color, metal, rough,
                             PatinaPattern(seed=r.next_u32(), strength=r.uniform(*PATINA_STRENGTH)))
    for m in out.values():
        validate_material(m)
    return out


# ------------------------------------------------------------------ the derive entry point

def derive_blade_presentation(asset, versions: PresentationVersions) -> PresentedSword:
    """Pure function of (asset, versions). Reads geometry only."""
    if not isinstance(asset, BladeAsset):
        raise PresentationError(f"blade presentation expects a BladeAsset; got {type(asset).__name__}")
    if not isinstance(versions, PresentationVersions):
        raise PresentationError(f"expected PresentationVersions; got {type(versions).__name__}")
    for field_name in ("presentation_version", "normals_version", "uv_version", "material_version"):
        require_version(field_name, getattr(versions, field_name), (1,))
    if asset.asset_type not in NORMAL_MODES:
        raise PresentationError(f"no blade presentation profile for {asset.asset_type!r}")
    modes = NORMAL_MODES[asset.asset_type]
    materials = select_materials(asset.asset_type, asset.seed)
    comps = []
    for mesh in asset.components:
        mode, cos_limit = modes[mesh.name]
        normals, normal_idx = compute_normals(mesh, mode, cos_limit)
        uvs, uv_idx = compute_uvs(mesh, uv_mapping(asset, mesh.name))
        comps.append(ComponentPresentation(name=mesh.name, normals=normals, normal_indices=normal_idx, uvs=uvs,
                                           uv_indices=uv_idx, material=materials[mesh.name]))
    return PresentedSword(asset=asset, versions=versions, components=tuple(comps))
