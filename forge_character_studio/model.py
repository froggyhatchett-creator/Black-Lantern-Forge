"""Versioned, body-plan-neutral data model for Character Studio."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from forge.errors import GeometryError
from forge.mesh import Mesh, check_closed_oriented

GENERATOR_ID = "forge.character.humanoid-base"
GENERATOR_VERSION = 2
RECIPE_CONTRACT_ID = "forge.character-recipe"
RECIPE_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class CharacterParameters:
    """Normalized morphology controls for the first neutral humanoid body plan.

    These controls describe geometry, not identity, sex, gender, species, or a
    future skeleton.  Later body-plan plugins may expose entirely different
    parameter sets under their own explicit generator identifiers.
    """

    height_m: float = 1.75
    torso_scale: float = 1.0
    chest_scale: float = 1.0
    waist_scale: float = 1.0
    hip_scale: float = 1.0
    arm_scale: float = 1.0
    leg_scale: float = 1.0
    head_scale: float = 1.0
    neck_scale: float = 1.0
    hand_scale: float = 1.0
    foot_scale: float = 1.0
    shoulder_width: float = 1.0
    pelvis_width: float = 1.0
    left_arm_scale: float = 1.0
    right_arm_scale: float = 1.0
    left_leg_scale: float = 1.0
    right_leg_scale: float = 1.0
    symmetry: float = 1.0
    subdivision: int = 1
    shoulder_corrective: float = 1.0
    hip_corrective: float = 1.0

    def __post_init__(self) -> None:
        values = asdict(self)
        subdivision = values.pop("subdivision")
        if type(subdivision) is not int or not 0 <= subdivision <= 2:
            raise GeometryError("subdivision must be an int in [0, 2]")
        for name, value in values.items():
            if type(value) is not float or not math.isfinite(value):
                raise GeometryError(f"character parameter {name} must be a finite float; got {value!r}")
        if not 1.20 <= self.height_m <= 2.40:
            raise GeometryError("height_m must be in [1.20, 2.40]")
        for name in ("torso_scale", "chest_scale", "waist_scale", "hip_scale", "arm_scale", "leg_scale",
                     "head_scale", "neck_scale", "hand_scale", "foot_scale", "shoulder_width", "pelvis_width",
                     "left_arm_scale", "right_arm_scale", "left_leg_scale", "right_leg_scale"):
            value = getattr(self, name)
            if not 0.65 <= value <= 1.55:
                raise GeometryError(f"{name} must be in [0.65, 1.55]")
        if not 0.0 <= self.symmetry <= 1.0:
            raise GeometryError("symmetry must be in [0.0, 1.0]")
        for name in ("shoulder_corrective", "hip_corrective"):
            if not 0.0 <= getattr(self, name) <= 1.5:
                raise GeometryError(f"{name} must be in [0.0, 1.5]")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterParameters":
        legacy = {"height_m", "torso_scale", "chest_scale", "waist_scale", "hip_scale", "arm_scale", "leg_scale"}
        if not isinstance(data, dict) or set(data) not in (legacy, set(cls.__dataclass_fields__)):
            raise GeometryError("character parameters have missing or unknown fields")
        return cls(**data)


@dataclass(frozen=True)
class CharacterAsset:
    seed: int
    generator_version: int
    parameters: CharacterParameters
    body_plan_id: str
    body: Mesh

    asset_type: str = "character"

    def __post_init__(self) -> None:
        if type(self.seed) is not int or not 0 <= self.seed < (1 << 64):
            raise GeometryError("character seed must be an unsigned 64-bit integer")
        if self.generator_version not in (1, GENERATOR_VERSION):
            raise GeometryError(f"unsupported character generator version {self.generator_version!r}")
        if self.body_plan_id not in ("humanoid.neutral.v1", "humanoid.neutral.v2"):
            raise GeometryError(f"unsupported body plan {self.body_plan_id!r}")
        if self.body.name != "body":
            raise GeometryError("the character mesh must be named 'body'")
        check_closed_oriented(self.body)

    @property
    def components(self) -> tuple[Mesh, ...]:
        return (self.body,)

    @property
    def component_names(self) -> tuple[str, ...]:
        return ("body",)
