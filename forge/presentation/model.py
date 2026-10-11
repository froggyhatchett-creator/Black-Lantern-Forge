"""Presentation data model: what Step 2 layers on top of a frozen SwordAsset.

Design rule: presentation never copies or rewrites geometry. Normals and UVs
are *face-varying attribute streams*: each component carries its own list of
unique normals / UVs plus, for every triangle of the frozen mesh, a triple of
indices into those lists (parallel to mesh.triangles). Positions and position
indices stay exactly the frozen generator output. This is the same model OBJ
uses (`f v/vt/vn`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from forge.errors import PresentationError
from forge.mesh import Tri, Vec3

if TYPE_CHECKING:  # pragma: no cover
    from forge.presentation.materials import Material
    from forge.sword.asset import SwordAsset

Vec2 = tuple[float, float]

NORMAL_LENGTH_TOLERANCE = 1e-12


@dataclass(frozen=True)
class PresentationVersions:
    """Every algorithm version that shapes presentation output. Always explicit."""

    presentation_version: int  # composition: face-varying streams bound to frozen geometry
    normals_version: int
    uv_version: int
    material_version: int

    def to_dict(self) -> dict:
        return {
            "presentation_version": self.presentation_version,
            "normals_version": self.normals_version,
            "uv_version": self.uv_version,
            "material_version": self.material_version,
        }


@dataclass(frozen=True)
class ComponentPresentation:
    name: str
    normals: tuple[Vec3, ...]
    normal_indices: tuple[Tri, ...]   # parallel to the frozen mesh's triangles
    uvs: tuple[Vec2, ...]
    uv_indices: tuple[Tri, ...]       # parallel to the frozen mesh's triangles
    material: "Material"


@dataclass(frozen=True)
class PresentedSword:
    asset: "SwordAsset"
    versions: PresentationVersions
    components: tuple[ComponentPresentation, ...]  # same order as asset.components

    def __post_init__(self) -> None:
        validate_presented(self)

    def component(self, name: str) -> ComponentPresentation:
        for c in self.components:
            if c.name == name:
                return c
        raise KeyError(f"no presented component {name!r}")

    @property
    def materials(self) -> dict:
        return {c.name: c.material.to_dict() for c in self.components}


def validate_presented(p: PresentedSword) -> None:
    """Fail loudly if presentation data is inconsistent with the frozen geometry."""
    names = tuple(c.name for c in p.components)
    if names != p.asset.component_names:
        raise PresentationError(f"presented components {names} != asset components {p.asset.component_names}")
    for comp, mesh in zip(p.components, p.asset.components):
        where = f"component {comp.name!r}"
        if len(comp.normal_indices) != mesh.triangle_count or len(comp.uv_indices) != mesh.triangle_count:
            raise PresentationError(f"{where}: attribute index streams must have one triple per triangle")
        if not comp.normals or not comp.uvs:
            raise PresentationError(f"{where}: empty normal or UV list")
        for n in comp.normals:
            if len(n) != 3 or not all(type(c) is float and math.isfinite(c) for c in n):
                raise PresentationError(f"{where}: invalid normal {n!r}")
            length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
            if abs(length - 1.0) > NORMAL_LENGTH_TOLERANCE:
                raise PresentationError(f"{where}: normal {n!r} not unit length ({length!r})")
        for uv in comp.uvs:
            if len(uv) != 2 or not all(type(c) is float and math.isfinite(c) for c in uv):
                raise PresentationError(f"{where}: invalid UV {uv!r}")
        for stream, size, label in ((comp.normal_indices, len(comp.normals), "normal"),
                                    (comp.uv_indices, len(comp.uvs), "uv")):
            used = bytearray(size)
            for tri in stream:
                if len(tri) != 3:
                    raise PresentationError(f"{where}: {label} index triple {tri!r} malformed")
                for i in tri:
                    if type(i) is not int or not 0 <= i < size:
                        raise PresentationError(f"{where}: {label} index {i!r} out of range [0, {size})")
                    used[i] = 1
            if not all(used):
                raise PresentationError(f"{where}: unreferenced {label} entry {used.index(0)}")
        if comp.material.component != comp.name:
            raise PresentationError(f"{where}: bound to material for {comp.material.component!r}")
