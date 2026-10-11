"""short_sword: registry entries wrapping the frozen Step 1 / Step 2 implementation.

This module only *describes* the short sword to the registries. It calls the
frozen public functions exactly as before and changes none of their behavior:

  generator     forge.sword v1           -> forge.sword.generate_sword(seed, 1)
  presentation  forge.presentation v1    -> forge.presentation.derive_presentation
                                            (normals v1, uv v1, material v1; preview v1)
  integrity     the five Step 2 hashes, same definitions, same order
  engine        (Step 3) ENGINE_ADAPTER: sockets and tags for the Forge -> Engine
                contract package (export glb:1). Derived from the frozen asset;
                read-only.

Importing this module registers nothing. forge/catalog.py lists these
constants explicitly.
"""

from __future__ import annotations

from forge.engine.package import IDENTITY_ROTATION, EngineAdapter, EngineSocket
from forge.errors import ExportError
from forge.export.obj import obj_bytes
from forge.hashing import geometry_sha256, materials_sha256, normals_sha256, sha256_hex, uvs_sha256
from forge.presentation import derive_presentation
from forge.registry import AssetDescriptor, AssetEntry, GeneratorEntry, PresentationEntry
from forge.sword import generate_sword
from forge.sword.asset import COMPONENT_ORDER

DESCRIPTOR = AssetDescriptor(
    asset_type="short_sword",
    display_name="procedural short sword",
    generator_id="forge.sword",
    presentation_id="forge.presentation",
    export_formats=(("glb", 1), ("obj", 1), ("obj", 2)),   # sorted, as every registry listing is
    preview_id="forge.preview",
    record_versions=(1,),
    convention_id="forge.rh-y-up-meters.grip-origin.v1",
    components=COMPONENT_ORDER,
)


def generate_short_sword_v1(seed: int):
    """forge.sword v1: exactly the frozen Step 1 generator."""
    return generate_sword(seed, 1)


GENERATORS = (
    GeneratorEntry(generator_id="forge.sword", generator_version=1, asset_type="short_sword",
                   generate=generate_short_sword_v1),
)

PRESENTATIONS = (
    PresentationEntry(presentation_id="forge.presentation", presentation_version=1,
                      normals_version=1, uv_version=1, material_version=1,
                      preview_versions=(1,), derive=derive_presentation),
)


# ---- integrity hashes (Step 2 definitions; order = verification order)

def _geometry(asset, presented) -> str:
    return geometry_sha256(asset)


def _obj_format1(asset, presented) -> str:
    return sha256_hex(obj_bytes(asset))


def _normals(asset, presented) -> str:
    return normals_sha256(presented)


def _uvs(asset, presented) -> str:
    return uvs_sha256(presented)


def _materials(asset, presented) -> str:
    return materials_sha256(presented)


INTEGRITY = (
    ("geometry_sha256", _geometry),
    ("obj_format1_sha256", _obj_format1),
    ("normals_sha256", _normals),
    ("uvs_sha256", _uvs),
    ("materials_sha256", _materials),
)


def summary_lines(asset) -> tuple[str, ...]:
    """Parameter lines for CLI summaries (identical text to the Step 1 / Step 2 CLI)."""
    p = asset.params
    b, g, h, m = p.blade, p.guard, p.grip, p.pommel
    return (
        f"  blade   length {b.length:.4f} m | base width {b.base_width:.4f} m | "
        f"thickness {b.thickness:.4f} m | taper {b.taper:.3f} | point {b.point_shape}",
        f"  guard   {g.shape} | width {g.width:.4f} m | thickness {g.thickness:.4f} m | depth {g.depth:.4f} m",
        f"  grip    length {h.length:.4f} m | radius {h.radius:.4f} m | swell {h.swell:.3f} | segments {h.segments}",
        f"  pommel  {m.shape} | radius {m.radius:.4f} m | height {m.height:.4f} m",
        f"  total length       {p.total_length:.4f} m",
        f"  mesh               {len(asset.components)} components, "
        f"{asset.vertex_count} vertices, {asset.triangle_count} triangles",
    )


ASSET = AssetEntry(descriptor=DESCRIPTOR, integrity=INTEGRITY, summary_lines=summary_lines)


# ---- Step 3: Forge -> Engine contract adapter (sockets, tags). Geometry is read, never changed.

SOCKET_FRAME = ("asset axes, identity rotation: +Y along the blade toward the tip, "
                "+X toward the cutting edges, +Z out of the blade flats")
GRIP_ORIGIN_TOLERANCE_M = 1e-9


def engine_sockets(asset) -> tuple[EngineSocket, ...]:
    """socket_grip: the origin (the grip center, by convention); socket_tip: the blade apex vertex."""
    lo, hi = asset.component("grip").bounds()
    center = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5)
    if any(abs(c) > GRIP_ORIGIN_TOLERANCE_M for c in center):
        raise ExportError(f"grip bounding-box center {center} is not at the origin; the convention is broken")
    blade = asset.component("blade").positions
    top = max(p[1] for p in blade)
    apex = [p for p in blade if p[1] == top]
    if len(apex) != 1:
        raise ExportError(f"blade has {len(apex)} vertices at its greatest y; expected one apex")
    return (
        EngineSocket(name="socket_grip", translation=(0.0, 0.0, 0.0), rotation=IDENTITY_ROTATION,
                     frame=SOCKET_FRAME,
                     derivation="the asset origin, which the coordinate convention defines as the grip center "
                                "(checked: grip bounding-box center within 1e-9 m of the origin)"),
        EngineSocket(name="socket_tip", translation=apex[0], rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
                     derivation="the blade apex: the unique blade vertex with the greatest y "
                                "(the top point of the blade loft), rounded to binary32"),
    )


def engine_tags(asset, presented) -> tuple[str, ...]:
    p = asset.params
    return (
        f"asset_type:{asset.asset_type}",
        "category:weapon",
        f"blade.point:{p.blade.point_shape}",
        f"guard.shape:{p.guard.shape}",
        f"pommel.shape:{p.pommel.shape}",
        *(f"material.{c.name}:{c.material.preset}" for c in presented.components),
    )


ENGINE_ADAPTER = EngineAdapter(asset_type="short_sword", sockets=engine_sockets, tags=engine_tags)
