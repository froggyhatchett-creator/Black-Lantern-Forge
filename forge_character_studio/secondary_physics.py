"""Schema for named soft-body and collision attachment regions on a character.

This module is a contract stub: it defines data shape and validation only. It contains no
simulation, no physics runtime, and nothing that moves or computes forces.
"""

from __future__ import annotations

from dataclasses import dataclass

CONTRACT_ID = "forge.character-secondary-physics"
CONTRACT_VERSION = 1

REGION_KINDS = ("soft_body", "collision_volume")


@dataclass(frozen=True)
class PhysicsRegion:
    """One named region attached to base-mesh vertices, typed as a soft body or collision volume."""

    name: str
    attachment_vertex_indices: tuple[int, ...]
    region_kind: str

    def __post_init__(self) -> None:
        if self.region_kind not in REGION_KINDS:
            raise ValueError(
                f"physics region {self.name!r} has unknown region_kind {self.region_kind!r}; "
                f"expected one of {REGION_KINDS}"
            )
        if len(self.attachment_vertex_indices) == 0:
            raise ValueError(f"physics region {self.name!r} must attach to at least one vertex")


@dataclass(frozen=True)
class SecondaryPhysicsContract:
    """The physics regions for one character, for forge.character-secondary-physics v1."""

    contract_id: str
    contract_version: int
    regions: tuple[PhysicsRegion, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for region in self.regions:
            if region.name in seen:
                raise ValueError(f"duplicate physics region name {region.name!r}")
            seen.add(region.name)
