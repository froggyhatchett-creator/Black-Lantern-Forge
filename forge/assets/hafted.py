"""Hafted families (Step 5B): registry entries for one_hand_axe, two_hand_axe, mace, war_hammer.

Like forge/assets/short_sword.py and forge/assets/blades.py, this module only *describes* families
to the registries:
  descriptor   identity, presentation, preview, exports, convention, components
  generator    forge.<family> v1
  integrity    geometry, normals, uvs, materials
  engine       ENGINE_ADAPTERS: the sockets and tags for Contract v1
Importing this module registers nothing. forge/catalog.py lists these constants explicitly.

Sockets (identity rotations: Contract v1 as implemented by Forge's package builder allows no
other):
  socket_grip              the grip-centered origin
  socket_head              the head's reference center on the haft axis
  socket_strike            the primary striking point, always a render vertex:
                             axe     the edge's furthest-forward vertex, at the middle of its height
                             mace    the +X element's outer edge, at its widest slice
                             hammer  the face's center vertex
  socket_tip               Contract v1 requires it on every package. For a hafted weapon it is the
                           distal end on the primary axis: the haft's top center (axes, hammer) or
                           the head's top point (mace)
  socket_secondary_strike  war_hammer only: the rear's far end (pick or spike point, or poll face center)
"""

from __future__ import annotations

from types import MappingProxyType

from forge.engine.package import IDENTITY_ROTATION, EngineAdapter, EngineSocket
from forge.errors import ExportError
from forge.hafted import mace, one_hand_axe, two_hand_axe, war_hammer
from forge.hafted.axe import COMPONENTS as AXE_COMPONENTS
from forge.hafted.axe import head_length as axe_head_length
from forge.hafted.model import hands_for
from forge.hafted.presentation import PRESENTATION_ID, derive_hafted_presentation
from forge.hashing import geometry_sha256, materials_sha256, normals_sha256, uvs_sha256
from forge.registry import AssetDescriptor, AssetEntry, GeneratorEntry, PresentationEntry

FIT_PREVIEW_ID = "forge.preview.fit"
CONVENTION_ID = "forge.rh-y-up-meters.grip-origin.v1"
FAMILIES = (one_hand_axe, two_hand_axe, mace, war_hammer)
DISPLAY_NAMES = MappingProxyType({"one_hand_axe": "procedural one-hand axe", "two_hand_axe": "procedural two-hand axe",
                                  "mace": "procedural mace", "war_hammer": "procedural war hammer"})
COMPONENTS = MappingProxyType({"one_hand_axe": AXE_COMPONENTS, "two_hand_axe": AXE_COMPONENTS,
                               "mace": mace.COMPONENTS, "war_hammer": war_hammer.COMPONENTS})
CLASSES = MappingProxyType({"one_hand_axe": "axe", "two_hand_axe": "axe", "mace": "mace", "war_hammer": "hammer"})
NOMINAL_HANDS = MappingProxyType({"one_hand_axe": ("one",), "two_hand_axe": ("two",), "mace": ("one",),
                                  "war_hammer": ("one", "hand_and_half")})
STRIKE_PART = MappingProxyType({"one_hand_axe": "bit", "two_hand_axe": "bit", "mace": "flanges", "war_hammer": "face"})
TIP_PART = MappingProxyType({"one_hand_axe": "haft", "two_hand_axe": "haft", "mace": "head", "war_hammer": "haft"})
SECONDARY_PART = MappingProxyType({"war_hammer": "rear"})

PRESENTATIONS = (
    PresentationEntry(presentation_id=PRESENTATION_ID, presentation_version=1, normals_version=1, uv_version=1,
                      material_version=1, preview_versions=(1,), derive=derive_hafted_presentation),
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


def hands(asset) -> str:
    return hands_for(asset.params.grip.length, NOMINAL_HANDS[asset.asset_type])


def _head_line(asset) -> str:
    p = asset.params
    if asset.asset_type in ("one_hand_axe", "two_hand_axe"):
        e, b = p.head, p.bit
        poll = e.poll if e.poll == "flat" else f"{e.poll} {e.poll_reach:.4f} m"
        return (f"  head    {e.style} | eye {e.eye_height:.4f} m | edge reach {b.projection:.4f} m | "
                f"head length {axe_head_length(p):.4f} m | poll {poll} | collar {'yes' if e.collar_height else 'no'}")
    if asset.asset_type == "mace":
        h, e = p.head, p.elements
        return (f"  head    {e.count} {e.form} on a {h.core_shape} core | head height {h.height:.4f} m | "
                f"head width {2.0 * (h.core_radius + e.projection):.4f} m")
    f, r = p.face, p.rear
    return (f"  head    {f.shape} face {f.size:.4f} m | neck {f.neck_length:.4f} m | rear {r.style} "
            f"{r.length:.4f} m | socket {p.head.eye_height:.4f} m")


def summary_lines(asset) -> tuple[str, ...]:
    h, g = asset.params.haft, asset.params.grip
    strike = asset.landmark("strike_point")
    return (
        f"  haft    length {h.length:.4f} m | {2.0 * h.radius:.4f} x {2.0 * h.radius * h.flatten:.4f} m | "
        f"taper {h.taper:+.3f}",
        f"  grip    length {g.length:.4f} m | wrap {g.wrap:.4f} m | {hands(asset)}-handed",
        _head_line(asset),
        f"  overall length     {asset.overall_length:.4f} m",
        f"  head mass          {asset.head_mass_kg:.3f} kg (steel, from mesh volume)",
        f"  strike point       ({strike[0]:.4f}, {strike[1]:.4f}, {strike[2]:.4f}) m",
        f"  mesh               {len(asset.components)} components, {asset.vertex_count} vertices, "
        f"{asset.triangle_count} triangles",
    )


SOCKET_FRAME = ("asset axes, identity rotation: +Y along the haft toward the head, +X toward the striking side "
                "(edge, face or reference element), +Z across the head's thickness")
GRIP_ORIGIN_TOLERANCE_M = 1e-9
_STRIKE_DERIVATION = MappingProxyType({
    "one_hand_axe": "the cutting edge's furthest-forward vertex, at the middle of the edge's height (a bit vertex)",
    "two_hand_axe": "the cutting edge's furthest-forward vertex, at the middle of the edge's height (a bit vertex)",
    "mace": "the outer edge vertex of the +X striking element at its widest slice (a flanges vertex)",
    "war_hammer": "the center vertex of the hammer face (a face vertex)",
})


def _vertex(asset, landmark: str, part: str):
    point = asset.landmark(landmark)
    if point not in asset.component(part).positions:
        raise ExportError(f"the recorded {landmark} is not a {part} vertex")
    return point


def engine_sockets(asset) -> tuple[EngineSocket, ...]:
    family = asset.asset_type
    lo, hi = asset.component("grip").bounds()
    center = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5)
    if any(abs(c) > GRIP_ORIGIN_TOLERANCE_M for c in center):
        raise ExportError(f"grip bounding-box center {center} is not at the origin; the convention is broken")
    head = asset.landmark("head_center")
    if head[0] != 0.0 or head[2] != 0.0:
        raise ExportError("the head center must lie on the haft axis")
    sockets = [
        EngineSocket(name="socket_grip", translation=(0.0, 0.0, 0.0), rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
                     derivation="the asset origin, which the coordinate convention defines as the grip center "
                                "(checked: grip bounding-box center within 1e-9 m of the origin)"),
        EngineSocket(name="socket_head", translation=head, rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
                     derivation="the head's reference center on the haft axis: the middle of the socket's height "
                                "(axes, hammer) or of the head's height (mace)"),
        EngineSocket(name="socket_strike", translation=_vertex(asset, "strike_point", STRIKE_PART[family]),
                     rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
                     derivation=_STRIKE_DERIVATION[family] + ", rounded to binary32"),
        EngineSocket(name="socket_tip", translation=_vertex(asset, "tip", TIP_PART[family]), rotation=IDENTITY_ROTATION,
                     frame=SOCKET_FRAME,
                     derivation="the weapon's distal end on its primary axis: the "
                                + ("head's top point" if TIP_PART[family] == "head" else "haft's top center")
                                + " (Contract v1 requires socket_tip), rounded to binary32"),
    ]
    if family in SECONDARY_PART:
        sockets.append(EngineSocket(
            name="socket_secondary_strike", translation=_vertex(asset, "secondary_strike_point", SECONDARY_PART[family]),
            rotation=IDENTITY_ROTATION, frame=SOCKET_FRAME,
            derivation="the rear's far end: the point of a pick or spike, or the center of a poll's face, "
                       "rounded to binary32"))
    return tuple(sockets)


def _style_tags(asset) -> tuple[str, ...]:
    p = asset.params
    if CLASSES[asset.asset_type] == "axe":
        return (f"head.style:{p.head.style}", f"head.poll:{p.head.poll}",
                f"head.collar:{'yes' if p.head.collar_height else 'no'}")
    if asset.asset_type == "mace":
        return (f"head.core:{p.head.core_shape}", f"head.form:{p.elements.form}", f"head.elements:{p.elements.count}",
                f"butt_cap.shape:{p.butt_cap.shape}")
    return (f"face.shape:{p.face.shape}", f"rear.style:{p.rear.style}", f"butt_cap.shape:{p.butt_cap.shape}")


def engine_tags(asset, presented) -> tuple[str, ...]:
    return (
        f"asset_type:{asset.asset_type}",
        "category:weapon",
        "lineage:hafted",
        f"class:{CLASSES[asset.asset_type]}",
        f"hands:{hands(asset)}",
        *_style_tags(asset),
        *(f"material.{c.name}:{c.material.preset}" for c in presented.components),
    )


def _entries(module):
    descriptor = AssetDescriptor(
        asset_type=module.ASSET_TYPE, display_name=DISPLAY_NAMES[module.ASSET_TYPE],
        generator_id=module.GENERATOR_ID, presentation_id=PRESENTATION_ID,
        export_formats=(("glb", 1), ("obj", 2)), preview_id=FIT_PREVIEW_ID, record_versions=(1,),
        convention_id=CONVENTION_ID, components=COMPONENTS[module.ASSET_TYPE])
    asset = AssetEntry(descriptor=descriptor, integrity=INTEGRITY, summary_lines=summary_lines)
    generator = GeneratorEntry(generator_id=module.GENERATOR_ID, generator_version=module.GENERATOR_VERSION,
                               asset_type=module.ASSET_TYPE, generate=module.generate)
    adapter = EngineAdapter(asset_type=module.ASSET_TYPE, sockets=engine_sockets, tags=engine_tags)
    return asset, generator, adapter


_BUILT = tuple(_entries(m) for m in FAMILIES)
ASSETS = tuple(a for a, _, _ in _BUILT)
GENERATORS = tuple(g for _, g, _ in _BUILT)
ENGINE_ADAPTERS = tuple(e for _, _, e in _BUILT)
