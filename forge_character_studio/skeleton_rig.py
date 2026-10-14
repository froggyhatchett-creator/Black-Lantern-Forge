"""Bone-weighted skeleton rig contract (bones, parent chain, per-vertex skin weights)."""

from __future__ import annotations

from dataclasses import dataclass

_WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class BoneJoint:
    """One bone: a name, the name of its parent (None for a root), and a row-major 4x4 bind matrix."""

    name: str
    parent: str | None
    bind_matrix: tuple[float, ...]


@dataclass(frozen=True)
class VertexWeights:
    """Up to four joint indices influencing one vertex, with weights that sum to 1."""

    joints: tuple[int, int, int, int]
    weights: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if not all(weight >= 0.0 for weight in self.weights):
            raise ValueError(f"vertex weights must be non-negative; got {self.weights!r}")
        if abs(sum(self.weights) - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"vertex weights must sum to 1.0; got {self.weights!r}")


@dataclass(frozen=True)
class SkeletonRig:
    """Bone hierarchy plus per-vertex skin weights for forge.character-skeleton-rig v1."""

    contract_id: str
    contract_version: int
    bones: tuple[BoneJoint, ...]
    vertex_weights: tuple[VertexWeights, ...]

    def __post_init__(self) -> None:
        by_name = {bone.name: bone for bone in self.bones}
        if len(by_name) != len(self.bones):
            raise ValueError("bone names must be unique")
        for bone in self.bones:
            if bone.parent is not None and bone.parent not in by_name:
                raise ValueError(f"bone {bone.name!r} has unknown parent {bone.parent!r}")
        for bone in self.bones:
            # Walk up the parent chain. Each step adds a previously unseen name to
            # `visited`, so the walk always terminates; revisiting a name means a cycle.
            visited = {bone.name}
            parent = bone.parent
            while parent is not None:
                if parent in visited:
                    raise ValueError(f"bone {bone.name!r} is part of a cyclic parent chain")
                visited.add(parent)
                parent = by_name[parent].parent
