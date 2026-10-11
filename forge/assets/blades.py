"""Blade families (Step 5A): registry entries for dagger, long_sword, curved_sword, great_sword.

Like forge/assets/short_sword.py, this module only *describes* families to the registries:
  descriptor   identity, presentation, preview, exports, convention, components
  generator    forge.<family> v1
  integrity    geometry, normals, uvs, materials (no obj_format1: OBJ format 1 is the frozen
               short-sword exporter)
  engine       ENGINE_ADAPTERS: socket_grip at the grip-centered origin; socket_tip at the
               blade's recorded terminal point, which for a curved blade isn't simply the
               highest vertex
Importing this module registers nothing. forge/catalog.py lists these constants explicitly.
"""

from __future__ import annotations

from types import MappingProxyType

from forge.blades import curved_sword, dagger, great_sword, long_sword
from forge.blades.lineage import BLADE_CLASSES, grip_hands
from forge.blades.presentation import PRESENTATION_ID, derive_blade_presentation
from forge.engine.package import IDENTITY_ROTATION, EngineAdapter, EngineSocket
from forge.errors import ExportError
from forge.hashing import geometry_sha256, materials_sha256, normals_sha256, uvs_sha256
from forge.registry import AssetDescriptor, AssetEntry, GeneratorEntry, PresentationEntry

FIT_PREVIEW_ID = "forge.preview.fit"
CONVENTION_ID = "forge.rh-y-up-meters.grip-origin.v1"
FAMILIES = (dagger, long_sword, curved_sword, great_sword)
DISPLAY_NAMES = MappingProxyType({"dagger": "procedural dagger", "long_sword": "procedural long sword",
                                  "curved_sword": "procedural curved sword", "great_sword": "procedural great sword"})

PRESENTATIONS = (
    PresentationEntry(presentation_id=PRESENTATION_ID, presentation_version=1, normals_version=1, uv_version=1,
                      material_version=1, preview_versions=(1,), derive=derive_blade_presentation),
)


def _geometry(asset, presented) -> str:
    return geometry_sha256(asset)


def _normals(asset, presented) -> str:
    return normals_sha256(presented)


def _uvs(asset, presented) -> str:
    return uvs_sha256(presented)


def _materials(asset, presented) -> str:
    return materials_sha256(presented)


INTEGRITY = (
    ("geometry_sha256", _geometry),
    ("normals_sha256", _normals),
    ("uvs_sha256", _uvs),
    ("materials_sha256", _materials),
)


def summary_lines(asset) -> tuple[str, ...]:
    p = asset.params
    b, g, h, m = p.blade, p.guard, p.grip, p.pommel
    curve = (f" | curved: sagitta {b.sagitta_ratio * b.length:.4f} m ({b.sagitta_ratio:.3f} of length), "
             f"bias {b.curve_bias:+.2f}") if b.sagitta_ratio > 0.0 else ""
    ricasso = (f" | ricasso {b.ricasso_length:.4f} m at {b.ricasso_width_ratio:.2f} width"
               if b.ricasso_length > 0.0 else "")
    tip = asset.landmark("blade_tip")
    return (
        f"  blade   length {b.length:.4f} m | base width {b.base_width:.4f} m | thickness {b.thickness:.4f} m | "
        f"{b.cross_section} | point {b.point_shape}{curve}{ricasso}",
        f"  guard   {g.shape} | width {g.width:.4f} m | thickness {g.thickness:.4f} m | depth {g.depth:.4f} m",
        f"  grip    length {h.length:.4f} m | radius {h.radius:.4f} m | swell {h.swell:+.3f} | "
        f"{grip_hands(h.length)}-handed",
        f"  pommel  {m.shape} | radius {m.radius:.4f} m | height {m.height:.4f} m",
        f"  total length       {p.total_length:.4f} m",
        f"  blade tip          ({tip[0]:.4f}, {tip[1]:.4f}, {tip[2]:.4f}) m",
        f"  mesh               {len(asset.components)} components, {asset.vertex_count} vertices, "
        f"{asset.triangle_count} triangles",
    )


SOCKET_FRAME = ("asset axes, identity rotation: +Y along the blade's base toward the tip, "
                "+X toward the (convex) edge side, +Z out of the blade flats")
GRIP_ORIGIN_TOLERANCE_M = 1e-9


def engine_sockets(asset) -> tuple[EngineSocket, ...]:
    """socket_grip: the grip-centered origin. socket_tip: the blade's terminal (apex) vertex, as generated."""
    lo, hi = asset.component("grip").bounds()
    center = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5)
    if any(abs(c) > GRIP_ORIGIN_TOLERANCE_M for c in center):
        raise ExportError(f"grip bounding-box center {center} is not at the origin; the convention is broken")
    tip = asset.landmark("blade_tip")
    if tip not in asset.component("blade").positions:
        raise ExportError("the recorded blade tip is not a blade vertex")
    return (
        EngineSocket(name="socket_grip", translation=(0.0, 0.0, 0.0), rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
                     derivation="the asset origin, which the coordinate convention defines as the grip center "
                                "(checked: grip bounding-box center within 1e-9 m of the origin)"),
        EngineSocket(name="socket_tip", translation=tip, rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
                     derivation="the blade's terminal point: the apex vertex where the blade sweep ends "
                                "(recorded by the generator; for a curved blade it is not chosen by height), "
                                "rounded to binary32"),
    )


def engine_tags(asset, presented) -> tuple[str, ...]:
    p = asset.params
    cls = BLADE_CLASSES[asset.asset_type]
    return (
        f"asset_type:{asset.asset_type}",
        "category:weapon",
        f"lineage:{cls.lineage}",
        f"edge:{cls.edge}",
        f"hands:{grip_hands(p.grip.length)}",
        f"blade.curvature:{'curved' if p.blade.sagitta_ratio > 0.0 else 'straight'}",
        f"blade.section:{p.blade.cross_section}",
        f"blade.point:{p.blade.point_shape}",
        f"guard.shape:{p.guard.shape}",
        f"pommel.shape:{p.pommel.shape}",
        *(f"material.{c.name}:{c.material.preset}" for c in presented.components),
    )


def _entries(module):
    descriptor = AssetDescriptor(
        asset_type=module.ASSET_TYPE, display_name=DISPLAY_NAMES[module.ASSET_TYPE],
        generator_id=module.GENERATOR_ID, presentation_id=PRESENTATION_ID,
        export_formats=(("glb", 1), ("obj", 2)), preview_id=FIT_PREVIEW_ID, record_versions=(1,),
        convention_id=CONVENTION_ID, components=("blade", "guard", "grip", "pommel"))
    asset = AssetEntry(descriptor=descriptor, integrity=INTEGRITY, summary_lines=summary_lines)
    generator = GeneratorEntry(generator_id=module.GENERATOR_ID, generator_version=module.GENERATOR_VERSION,
                               asset_type=module.ASSET_TYPE, generate=module.generate)
    adapter = EngineAdapter(asset_type=module.ASSET_TYPE, sockets=engine_sockets, tags=engine_tags)
    return asset, generator, adapter


_BUILT = tuple(_entries(m) for m in FAMILIES)
ASSETS = tuple(a for a, _, _ in _BUILT)
GENERATORS = tuple(g for _, g, _ in _BUILT)
ENGINE_ADAPTERS = tuple(e for _, _, e in _BUILT)
