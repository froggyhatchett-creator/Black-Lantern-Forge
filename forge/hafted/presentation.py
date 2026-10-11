"""Hafted-family presentation: forge.hafted-presentation v1 (normals 1, uv 1, material 1).

A separate presentation family. The frozen forge.presentation v1 (short sword) and
forge.blade-presentation v1 (Step 5A) are untouched. This family serves one_hand_axe,
two_hand_axe, mace and war_hammer. It reads the frozen geometry and never writes it.

It outputs the frozen generic container (forge.presentation.model.PresentedSword: face-varying
normals and UVs plus one Material per component). Records, previews, OBJ format 2 and engine
packages therefore consume it unchanged.

normals_version 1 (this family)
  The face-normal and crease algorithm of Step 5A's blade presentation, called unchanged
  (forge.blades.presentation.compute_normals). The per-component modes are set here:
    haft, grip, collar, butt cap   smooth (crease cos 0.80 or 0.50): round, with hard cap edges
    axe head (eye, poll, collar)   crease cos 0.80: the forged eye's cheeks and rounded back shade
                                   smooth; its top, bottom, poll face and hammer or spike polls stay hard
    axe bit                        crease cos 0.94 (~20 deg): smooth along the curved edge, hard bevels
    mace head (core)               crease 30 deg: a 16-sided core shades round, an 8-sided one faceted
    mace flanges                   faceted
    hammer head, face, rear        faceted
uv_version 1 (this family)
  The box and cylindrical projections of Step 5A's blade presentation, called unchanged
  (forge.blades.presentation.compute_uvs):
    cylindrical  parts turned about the Y axis: haft, grip, collar, butt cap, mace head
    box          everything else
  Every value is in [0, 1].
material_version 1 (this family)
  The frozen Material and pattern classes:
    brushed  wood grain or steel
    patina   forged parts
    wrap     the grip
  Each component draws from its own PCG32 stream,
  "forge.hafted-presentation.material.v1.<asset_type>.<component>", so materials can never
  shift geometry. Stream draw order: the match flag (collars and butt caps only), preset (always
  drawn), tint, roughness_jitter, then the pattern draws.
  A part forged with another uses that part's preset; its own drawn preset is then unused:
    axe bit                    the head's preset
    mace flanges               the mace head's preset
    hammer face and rear       the head's preset
    a collar or butt cap       the head's preset when its "match" draw says so
Only + - * / and sqrt are used.
"""

from __future__ import annotations

from types import MappingProxyType

from forge.blades.presentation import compute_normals, compute_uvs
from forge.errors import PresentationError
from forge.hafted.model import HaftedAsset
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
from forge.prng import derive_stream
from forge.versioning import require_version

PRESENTATION_ID = "forge.hafted-presentation"
HAFTED_PRESENTATION_V1 = PresentationVersions(presentation_version=1, normals_version=1, uv_version=1,
                                              material_version=1)
MATERIAL_STREAM_PREFIX = "forge.hafted-presentation.material.v1."

# (preset, linear RGB, metallic, roughness)
WOODS = (
    ("ash_wood", (0.55, 0.42, 0.27), 0.0, 0.62),
    ("oak_wood", (0.42, 0.30, 0.18), 0.0, 0.66),
    ("hickory_wood", (0.50, 0.36, 0.22), 0.0, 0.60),
    ("dark_wood", (0.27, 0.17, 0.10), 0.0, 0.70),
)
METAL_HAFTS = (
    ("iron", (0.45, 0.45, 0.47), 1.0, 0.45),
    ("steel", (0.62, 0.64, 0.66), 1.0, 0.32),
)
WRAPS = (
    ("brown_leather", (0.32, 0.19, 0.11), 0.0, 0.72),
    ("black_leather", (0.09, 0.08, 0.08), 0.0, 0.62),
    ("oxblood_leather", (0.36, 0.09, 0.08), 0.0, 0.66),
    ("cord_wrap", (0.56, 0.47, 0.34), 0.0, 0.88),
)
HEAD_STEELS = (
    ("forged_iron", (0.38, 0.38, 0.40), 1.0, 0.50),
    ("grey_steel", (0.62, 0.64, 0.66), 1.0, 0.30),
    ("bright_steel", (0.78, 0.80, 0.83), 1.0, 0.22),
    ("blackened_steel", (0.20, 0.20, 0.22), 1.0, 0.50),
)
FITTINGS = (
    ("brass", (0.86, 0.69, 0.38), 1.0, 0.32),
    ("bronze", (0.74, 0.50, 0.28), 1.0, 0.38),
    ("steel", (0.70, 0.72, 0.75), 1.0, 0.28),
    ("iron", (0.45, 0.45, 0.47), 1.0, 0.45),
)

FACETED = ("faceted", 1.0)
ROUND = ("crease", 0.80)          # a 12- or 16-sided turned part shades round; caps stay hard
WRAP = ("crease", 0.50)
EDGE = ("crease", 0.94)
CORE = ("crease", 0.8660254037844386)
FORGED = ("crease", 0.80)         # a forged axe eye shades round across its cheeks; top, bottom and poll stay hard


class _Part:
    """How one component is presented: normal mode, UV projection, palette, pattern, and preset source."""

    def __init__(self, normals, uv, palette, pattern, follows=None, match_draw=False):
        self.normals, self.uv, self.palette, self.pattern = normals, uv, palette, pattern
        self.follows, self.match_draw = follows, match_draw


_AXE = MappingProxyType({
    "haft": _Part(ROUND, "cylindrical", WOODS, "brushed"),
    "grip": _Part(WRAP, "cylindrical", WRAPS, "wrap"),
    "head": _Part(FORGED, "box", HEAD_STEELS, "patina"),
    "bit": _Part(EDGE, "box", HEAD_STEELS, "brushed", follows="head"),
})
PROFILES = MappingProxyType({
    "one_hand_axe": _AXE,
    "two_hand_axe": _AXE,
    "mace": MappingProxyType({
        "haft": _Part(ROUND, "cylindrical", WOODS + METAL_HAFTS, "brushed"),
        "grip": _Part(WRAP, "cylindrical", WRAPS, "wrap"),
        "collar": _Part(ROUND, "cylindrical", FITTINGS, "patina", follows="head", match_draw=True),
        "head": _Part(CORE, "cylindrical", HEAD_STEELS + (FITTINGS[1],), "patina"),
        "flanges": _Part(FACETED, "box", HEAD_STEELS, "patina", follows="head"),
        "butt_cap": _Part(ROUND, "cylindrical", FITTINGS, "patina", follows="head", match_draw=True),
    }),
    "war_hammer": MappingProxyType({
        "haft": _Part(ROUND, "cylindrical", WOODS + METAL_HAFTS, "brushed"),
        "grip": _Part(WRAP, "cylindrical", WRAPS, "wrap"),
        "head": _Part(FACETED, "box", HEAD_STEELS, "patina"),
        "face": _Part(FACETED, "box", HEAD_STEELS, "brushed", follows="head"),
        "rear": _Part(FACETED, "box", HEAD_STEELS, "brushed", follows="head"),
        "butt_cap": _Part(ROUND, "cylindrical", FITTINGS, "patina", follows="head", match_draw=True),
    }),
})


def _pattern(kind: str, r):
    if kind == "brushed":
        return BrushedPattern(seed=r.next_u32(), strength=r.uniform(*BRUSHED_STRENGTH))
    if kind == "patina":
        return PatinaPattern(seed=r.next_u32(), strength=r.uniform(*PATINA_STRENGTH))
    lo, hi = WRAP_BANDS
    return WrapPattern(seed=r.next_u32(), bands=lo + r.next_bounded(hi - lo + 1),
                       contrast=r.uniform(*WRAP_CONTRAST), twist=r.next_bounded(2))


def select_materials(asset_type: str, seed: int, components: tuple[str, ...]) -> dict[str, Material]:
    if asset_type not in PROFILES:
        raise PresentationError(f"no hafted-presentation profile for {asset_type!r}")
    profile = PROFILES[asset_type]
    if tuple(profile) != components:
        raise PresentationError(f"{asset_type}: presentation profile {tuple(profile)} != components {components}")
    prefix = MATERIAL_STREAM_PREFIX + asset_type + "."
    drawn = {}
    for name, part in profile.items():                 # each component reads only its own stream
        r = derive_stream(seed, prefix + name)
        match = r.next_bounded(2) == 0 if part.match_draw else True
        preset = r.choice(part.palette)
        tint = 1.0 + r.uniform(*TINT_RANGE)
        jitter = r.uniform(*ROUGHNESS_JITTER)
        drawn[name] = (match, preset, tint, jitter, _pattern(part.pattern, r))

    def resolved(name: str) -> tuple:
        part, (match, preset, _, _, _) = profile[name], drawn[name]
        return resolved(part.follows) if part.follows is not None and match else preset

    out: dict[str, Material] = {}
    for name in profile:
        _, _, k, jitter, pattern = drawn[name]
        label, color, metallic, roughness = resolved(name)
        out[name] = Material(name, label, (color[0] * k, color[1] * k, color[2] * k), metallic, roughness + jitter,
                             pattern)
        validate_material(out[name])
    return out


def derive_hafted_presentation(asset, versions: PresentationVersions) -> PresentedSword:
    """Pure function of (asset, versions). Reads geometry only."""
    if not isinstance(asset, HaftedAsset):
        raise PresentationError(f"hafted presentation expects a HaftedAsset; got {type(asset).__name__}")
    if not isinstance(versions, PresentationVersions):
        raise PresentationError(f"expected PresentationVersions; got {type(versions).__name__}")
    for field_name in ("presentation_version", "normals_version", "uv_version", "material_version"):
        require_version(field_name, getattr(versions, field_name), (1,))
    materials = select_materials(asset.asset_type, asset.seed, asset.component_names)
    profile = PROFILES[asset.asset_type]
    comps = []
    for mesh in asset.components:
        part = profile[mesh.name]
        mode, cos_limit = part.normals
        normals, normal_idx = compute_normals(mesh, mode, cos_limit)
        uvs, uv_idx = compute_uvs(mesh, part.uv)
        comps.append(ComponentPresentation(name=mesh.name, normals=normals, normal_indices=normal_idx, uvs=uvs,
                                           uv_indices=uv_idx, material=materials[mesh.name]))
    return PresentedSword(asset=asset, versions=versions, components=tuple(comps))
