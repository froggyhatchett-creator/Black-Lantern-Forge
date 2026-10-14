"""Named corrective blend shapes (shape keys) driven by a joint angle range, with per-vertex deltas."""

from __future__ import annotations

import math
from dataclasses import dataclass

CONTRACT_ID = "forge.character-blendshapes"
CONTRACT_VERSION = 1


@dataclass(frozen=True)
class BlendShape:
    """One corrective shape: active between two joint angles, moving each vertex by a delta."""

    name: str
    driven_by: str
    min_angle_degrees: float
    max_angle_degrees: float
    vertex_deltas: tuple[tuple[float, float, float], ...]

    def __post_init__(self) -> None:
        if not self.driven_by.strip():
            raise ValueError(f"blend shape {self.name!r} must name a driving parameter")
        if not (math.isfinite(self.min_angle_degrees) and math.isfinite(self.max_angle_degrees)):
            raise ValueError(f"blend shape {self.name!r} angles must be finite")
        # Written as `not (a < b)`, not `a >= b`, so the check stays strict for any input.
        if not self.min_angle_degrees < self.max_angle_degrees:
            raise ValueError(
                f"blend shape {self.name!r} requires min_angle_degrees < max_angle_degrees; "
                f"got {self.min_angle_degrees!r} and {self.max_angle_degrees!r}"
            )
        for delta in self.vertex_deltas:
            if len(delta) != 3:
                raise ValueError(f"blend shape {self.name!r} deltas must have 3 components")
            for component in delta:
                if isinstance(component, bool) or not isinstance(component, (int, float)):
                    raise ValueError(f"blend shape {self.name!r} delta component must be a number")
                # math.isfinite rejects NaN and both infinities; NaN compares False to everything,
                # so range checks like `component < 0` would silently let it through.
                if not math.isfinite(component):
                    raise ValueError(f"blend shape {self.name!r} delta components must be finite")


@dataclass(frozen=True)
class BlendShapeSet:
    """The blend shapes for one character, for forge.character-blendshapes v1."""

    contract_id: str
    contract_version: int
    shapes: tuple[BlendShape, ...]


def build_blend_shape_set(base_vertex_count: int, shapes: tuple[BlendShape, ...]) -> BlendShapeSet:
    """Validate every shape against the base mesh's vertex count and build the set."""
    if base_vertex_count < 0:
        raise ValueError(f"base_vertex_count must be non-negative; got {base_vertex_count!r}")
    for shape in shapes:
        if len(shape.vertex_deltas) != base_vertex_count:
            raise ValueError(
                f"blend shape {shape.name!r} has {len(shape.vertex_deltas)} vertex deltas; "
                f"expected {base_vertex_count}"
            )
    return BlendShapeSet(CONTRACT_ID, CONTRACT_VERSION, tuple(shapes))
