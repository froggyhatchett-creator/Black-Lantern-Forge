"""SwordAsset: the immutable result of generate_sword()."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from forge.errors import GenerationError
from forge.mesh import Mesh, Vec3
from forge.sword.params import SwordParams

COMPONENT_ORDER = ("blade", "guard", "grip", "pommel")


@dataclass(frozen=True)
class SwordAsset:
    seed: int
    generator_version: int
    params: SwordParams
    components: tuple[Mesh, ...]  # always in COMPONENT_ORDER

    asset_type: ClassVar[str] = "short_sword"
    generator: ClassVar[str] = "forge.sword"

    def __post_init__(self) -> None:
        names = tuple(m.name for m in self.components)
        if names != COMPONENT_ORDER:
            raise GenerationError(f"sword components must be {COMPONENT_ORDER}; got {names}")

    @property
    def component_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.components)

    def component(self, name: str) -> Mesh:
        for m in self.components:
            if m.name == name:
                return m
        raise KeyError(f"sword has no component {name!r}; components are {COMPONENT_ORDER}")

    @property
    def vertex_count(self) -> int:
        return sum(m.vertex_count for m in self.components)

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.components)

    def bounds(self) -> tuple[Vec3, Vec3]:
        mins, maxs = zip(*(m.bounds() for m in self.components))
        return (
            (min(p[0] for p in mins), min(p[1] for p in mins), min(p[2] for p in mins)),
            (max(p[0] for p in maxs), max(p[1] for p in maxs), max(p[2] for p in maxs)),
        )

    def to_dict(self) -> dict:
        """JSON-ready description (parameters + mesh stats). Deterministic."""
        lo, hi = self.bounds()
        return {
            "asset_type": self.asset_type,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "units": "meters",
            "params": self.params.to_dict(),
            "derived": {"total_length": self.params.total_length},
            "mesh": {
                "components": [
                    {"name": m.name, "vertices": m.vertex_count, "triangles": m.triangle_count}
                    for m in self.components
                ],
                "vertices": self.vertex_count,
                "triangles": self.triangle_count,
                "bounds_min": list(lo),
                "bounds_max": list(hi),
            },
        }
