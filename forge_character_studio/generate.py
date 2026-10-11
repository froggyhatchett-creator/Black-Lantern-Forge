"""Deterministic Step 6A humanoid base generator."""

from __future__ import annotations

from forge.prng import derive_stream
from forge_character_studio.implicit import FieldVolume, OrganicField, extract_surface
from forge_character_studio.model import CharacterAsset, CharacterParameters, GENERATOR_VERSION


def _v(x, y, z, rx, ry, rz, weight=1.0):
    return FieldVolume((float(x), float(y), float(z)), (float(rx), float(ry), float(rz)), float(weight))


def _volumes(seed: int, p: CharacterParameters) -> tuple[FieldVolume, ...]:
    h = p.height_m
    rng = derive_stream(seed, "forge.character.humanoid-base.v1.morphology")
    variation = rng.uniform(0.985, 1.015)
    hip_y = h * (0.475 + 0.025 * (p.leg_scale - 1.0))
    shoulder_y = hip_y + h * 0.245 * p.torso_scale
    waist_y = hip_y + (shoulder_y - hip_y) * 0.48
    chest_y = hip_y + (shoulder_y - hip_y) * 0.78
    hip_x = h * 0.070 * p.hip_scale
    leg_r = h * 0.060 * variation
    arm_r = h * 0.047 * p.arm_scale * variation
    shoulder_x = h * 0.145 * p.chest_scale
    hand_y = shoulder_y - h * 0.30 * p.arm_scale
    volumes = [
        _v(0, hip_y, 0, h * 0.135 * p.hip_scale, h * 0.115, h * 0.088 * p.hip_scale, 1.15),
        _v(0, waist_y, 0, h * 0.105 * p.waist_scale, h * 0.135, h * 0.075 * p.waist_scale, 1.10),
        _v(0, chest_y, 0, h * 0.145 * p.chest_scale, h * 0.145, h * 0.093 * p.chest_scale, 1.15),
        _v(0, shoulder_y, 0, h * 0.175 * p.chest_scale, h * 0.085, h * 0.085, 1.05),
        _v(0, shoulder_y + h * 0.105, 0, h * 0.052, h * 0.085, h * 0.050, 1.0),
        _v(0, shoulder_y + h * 0.205, 0, h * 0.076, h * 0.112, h * 0.084, 1.10),
    ]
    for side in (-1.0, 1.0):
        x = side * hip_x
        knee_y = hip_y * 0.52
        ankle_y = h * 0.075
        volumes.extend((
            _v(x, hip_y - h * 0.095, 0, leg_r * 1.12, h * 0.165 * p.leg_scale, leg_r * 1.05, 1.15),
            _v(x, knee_y, 0, leg_r, h * 0.155 * p.leg_scale, leg_r * 0.95, 1.05),
            _v(x, ankle_y + h * 0.105, 0, leg_r * 0.82, h * 0.145 * p.leg_scale, leg_r * 0.82, 1.0),
            _v(x, h * 0.035, -h * 0.030, leg_r * 0.90, h * 0.042, h * 0.090, 1.10),
        ))
        sx = side * shoulder_x
        elbow_x = side * (shoulder_x + h * 0.055 * p.arm_scale)
        wrist_x = side * (shoulder_x + h * 0.075 * p.arm_scale)
        volumes.extend((
            _v(sx, shoulder_y - h * 0.035, 0, arm_r * 1.30, h * 0.110, arm_r * 1.25, 1.20),
            _v(elbow_x, shoulder_y - h * 0.145 * p.arm_scale, 0, arm_r, h * 0.135 * p.arm_scale, arm_r, 1.05),
            _v(wrist_x, hand_y + h * 0.070, 0, arm_r * 0.82, h * 0.115 * p.arm_scale, arm_r * 0.82, 1.0),
            _v(wrist_x, hand_y, -h * 0.004, arm_r * 0.92, h * 0.065, arm_r * 0.65, 1.0),
        ))
    return tuple(volumes)


def generate_character(seed: int, parameters: CharacterParameters | None = None,
                       generator_version: int = GENERATOR_VERSION) -> CharacterAsset:
    if type(seed) is not int or not 0 <= seed < (1 << 64):
        raise ValueError("seed must be an unsigned 64-bit integer")
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"unsupported character generator version {generator_version!r}")
    p = CharacterParameters() if parameters is None else parameters
    if not isinstance(p, CharacterParameters):
        raise TypeError("parameters must be CharacterParameters")
    h = p.height_m
    field = OrganicField(_volumes(seed, p))
    top = max(1.08, 0.475 + 0.025 * (p.leg_scale - 1.0) + 0.245 * p.torso_scale + 0.34)
    mesh = extract_surface(field, ((-0.42 * h, -0.025 * h, -0.22 * h),
                                   (0.42 * h, top * h, 0.22 * h)))
    return CharacterAsset(seed, generator_version, p, "humanoid.neutral.v1", mesh)
