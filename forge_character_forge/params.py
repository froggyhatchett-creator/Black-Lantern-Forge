"""Editable morphology parameters (body, face, developer anatomy) and presets.

Ranges are stability limits, not taste limits: they stop the field from
self-intersecting badly or the template projection from tearing.  Within them
any combination is legal, including stylized or exaggerated adult designs.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields, replace

PARAMS_SCHEMA = "forge.character-forge.params"
PARAMS_VERSION = 1


class ParameterError(ValueError):
    pass


def _check(obj, ranges: dict[str, tuple[float, float]]) -> None:
    for f in fields(obj):
        v = getattr(obj, f.name)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise ParameterError(f"{type(obj).__name__}.{f.name} must be a finite number; got {v!r}")
        lo, hi = ranges.get(f.name, (0.5, 1.6))
        if not lo <= float(v) <= hi:
            raise ParameterError(f"{type(obj).__name__}.{f.name}={v} outside stability range [{lo}, {hi}]")


class _Base:
    RANGES: dict = {}

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, int) and not isinstance(v, bool):
                object.__setattr__(self, f.name, float(v))
        _check(self, self.RANGES)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ParameterError(f"unknown {cls.__name__} fields: {sorted(unknown)}")
        return cls(**data)

    def with_(self, **kw):
        return replace(self, **kw)

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))


@dataclass(frozen=True)
class BodyParams(_Base):
    height_m: float = 1.75
    femininity: float = 0.5      # 0 = male skeletal/fat pattern, 1 = female
    body_fat: float = 0.35       # 0..1
    muscle: float = 0.45         # 0..1
    shoulder_width: float = 1.0
    chest_width: float = 1.0
    chest_depth: float = 1.0
    waist_width: float = 1.0
    hip_width: float = 1.0
    glute_size: float = 1.0
    belly: float = 0.0           # 0..1 extra abdominal volume
    torso_length: float = 1.0
    neck_length: float = 1.0
    neck_thickness: float = 1.0
    arm_length: float = 1.0
    arm_thickness: float = 1.0
    leg_length: float = 1.0
    thigh_thickness: float = 1.0
    calf_thickness: float = 1.0
    hand_size: float = 1.0
    foot_size: float = 1.0
    head_size: float = 1.0
    breast_size: float = 0.0     # 0 = flat/male chest, 1 = average, up to 3 exaggerated
    breast_spacing: float = 1.0
    breast_height: float = 1.0
    breast_projection: float = 1.0
    breast_sag: float = 0.3      # 0..1
    nipple_size: float = 1.0     # developer anatomy detail; public profile sets 0
    areola_size: float = 1.0

    RANGES = {
        "height_m": (1.30, 2.50), "femininity": (0.0, 1.0), "body_fat": (0.0, 1.0), "muscle": (0.0, 1.0),
        "belly": (0.0, 1.0), "breast_size": (0.0, 3.0), "breast_sag": (0.0, 1.0),
        "nipple_size": (0.0, 2.5), "areola_size": (0.0, 2.5), "head_size": (0.75, 1.45),
        "breast_projection": (0.5, 1.8), "breast_spacing": (0.7, 1.4), "breast_height": (0.8, 1.2),
        "glute_size": (0.5, 1.8),
    }


@dataclass(frozen=True)
class FaceParams(_Base):
    face_width: float = 1.0
    face_length: float = 1.0
    jaw_width: float = 1.0
    jaw_angle: float = 1.0       # squareness of the mandible angle
    chin_width: float = 1.0
    chin_length: float = 1.0
    chin_projection: float = 1.0
    cheekbone_width: float = 1.0
    cheekbone_height: float = 1.0
    cheek_fullness: float = 1.0
    nose_length: float = 1.0
    nose_width: float = 1.0
    nose_bridge: float = 1.0
    nose_tip: float = 1.0
    nose_upturn: float = 0.0     # -1..1
    brow_height: float = 1.0
    brow_prominence: float = 1.0
    eye_size: float = 1.0
    eye_spacing: float = 1.0
    eye_tilt: float = 0.0        # -1..1 canthal tilt
    lip_upper: float = 1.0
    lip_lower: float = 1.0
    mouth_width: float = 1.0
    ear_size: float = 1.0
    ear_protrusion: float = 1.0
    asymmetry: float = 0.0       # 0..1, deterministic left/right variation

    RANGES = {"nose_upturn": (-1.0, 1.0), "eye_tilt": (-1.0, 1.0), "asymmetry": (0.0, 1.0),
              "eye_size": (0.7, 1.4), "eye_spacing": (0.8, 1.25)}


@dataclass(frozen=True)
class GenitalParams(_Base):
    """Developer-anatomy male genital geometry (only built in the developer profile)."""

    enabled: float = 0.0          # 0/1 flag stored as float for uniform serialization
    penis_length: float = 1.0
    penis_girth: float = 1.0
    glans_size: float = 1.0
    penis_curve: float = 0.0      # -1..1 rest droop/lift
    scrotum_size: float = 1.0
    testicle_size: float = 1.0
    testicle_asymmetry: float = 0.4   # left typically hangs lower (0..1)

    RANGES = {"enabled": (0.0, 1.0), "penis_length": (0.4, 2.5), "penis_girth": (0.5, 2.0),
              "glans_size": (0.6, 1.6), "penis_curve": (-1.0, 1.0), "scrotum_size": (0.5, 2.0),
              "testicle_size": (0.5, 2.0), "testicle_asymmetry": (0.0, 1.0)}


def preset(name: str) -> tuple[BodyParams, FaceParams, GenitalParams]:
    """Named starting points. They are only defaults; every value stays editable."""
    if name == "male":
        return (BodyParams(height_m=1.78, femininity=0.0, body_fat=0.22, muscle=0.6, shoulder_width=1.08,
                           chest_width=1.06, waist_width=1.0, hip_width=0.96, glute_size=0.95,
                           neck_thickness=1.12, arm_thickness=1.08, breast_size=0.0, nipple_size=0.8,
                           areola_size=0.8),
                FaceParams(face_width=1.04, jaw_width=1.12, jaw_angle=1.2, chin_width=1.12, chin_length=1.05,
                           brow_prominence=1.25, brow_height=0.97, cheek_fullness=0.9, lip_upper=0.85,
                           lip_lower=0.92, nose_length=1.05, nose_width=1.08, nose_bridge=1.1),
                GenitalParams(enabled=1.0))
    if name == "female":
        return (BodyParams(height_m=1.66, femininity=1.0, body_fat=0.38, muscle=0.35, shoulder_width=0.94,
                           chest_width=0.95, waist_width=0.97, hip_width=0.98, glute_size=1.08,
                           neck_thickness=0.9, neck_length=1.05, arm_thickness=0.92, thigh_thickness=1.04,
                           breast_size=1.0, hand_size=0.94, foot_size=0.92),
                FaceParams(face_width=0.96, face_length=0.97, jaw_width=0.9, jaw_angle=0.8, chin_width=0.88,
                           chin_length=0.95, brow_prominence=0.75, brow_height=1.04, cheekbone_height=1.04,
                           cheek_fullness=1.08, lip_upper=1.12, lip_lower=1.12, nose_length=0.94,
                           nose_width=0.9, nose_bridge=0.92, nose_tip=0.92, eye_size=1.06),
                GenitalParams(enabled=0.0))
    if name == "neutral":
        return BodyParams(), FaceParams(), GenitalParams()
    raise ParameterError(f"unknown preset {name!r}; choose male, female or neutral")
