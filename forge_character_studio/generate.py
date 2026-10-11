"""Deterministic Step 6B anatomy-aware humanoid generator."""
from __future__ import annotations

from forge.prng import derive_stream
from forge_character_studio.implicit import FieldVolume, OrganicField, extract_surface
from forge_character_studio.legacy_v1 import generate_character_v1
from forge_character_studio.model import CharacterAsset, CharacterParameters, GENERATOR_VERSION
from forge_character_studio.skeleton import build_skeleton


def _v(x, y, z, rx, ry, rz, weight=1.0):
    return FieldVolume((float(x), float(y), float(z)), (float(rx), float(ry), float(rz)), float(weight))


def _local(value: float, symmetry: float) -> float:
    return 1.0 + (value - 1.0) * (1.0 - symmetry)


def _volumes(seed: int, p: CharacterParameters) -> tuple[FieldVolume, ...]:
    h = p.height_m
    variation = derive_stream(seed, "forge.character.humanoid-base.v2.anatomy").uniform(.992, 1.008)
    sk = build_skeleton(p).by_name()
    hip_y = sk["root"].position[1]
    shoulder_y = sk["left_shoulder"].position[1]
    waist_y = hip_y + (shoulder_y - hip_y) * .44
    chest_y = hip_y + (shoulder_y - hip_y) * .74
    volumes = [
        _v(0, hip_y, .004*h, .112*h*p.hip_scale*p.pelvis_width, .095*h, .080*h*p.hip_scale, 1.13),
        _v(0, waist_y, .002*h, .094*h*p.waist_scale, .105*h, .068*h*p.waist_scale, 1.06),
        _v(0, chest_y, .008*h, .132*h*p.chest_scale, .12*h, .086*h*p.chest_scale, 1.14),
        _v(0, shoulder_y-.018*h, 0, .155*h*p.chest_scale*p.shoulder_width, .063*h, .072*h, 1.0),
        _v(0, shoulder_y+.025*h, -.008*h, .12*h*p.shoulder_width, .035*h, .048*h, .72),
        _v(0, shoulder_y+.075*h, 0, .042*h*p.neck_scale, .07*h, .041*h*p.neck_scale, 1.0),
        _v(0, shoulder_y+.185*h, .002*h, .069*h*p.head_scale, .091*h*p.head_scale, .075*h*p.head_scale, 1.12),
        _v(0, shoulder_y+.125*h, -.012*h, .057*h*p.head_scale, .052*h, .058*h*p.head_scale, .92),
        _v(0, shoulder_y+.177*h, -.058*h, .024*h, .032*h, .025*h, .34),
        _v(0, shoulder_y+.205*h, .052*h, .054*h, .06*h, .042*h, .54),
    ]
    for label, side in (("left", 1.0), ("right", -1.0)):
        arm_factor = p.arm_scale * _local(getattr(p, f"{label}_arm_scale"), p.symmetry)
        leg_factor = p.leg_scale * _local(getattr(p, f"{label}_leg_scale"), p.symmetry)
        shoulder, elbow, wrist = (sk[f"{label}_{n}"].position for n in ("shoulder", "elbow", "wrist"))
        hip, knee, ankle = (sk[f"{label}_{n}"].position for n in ("hip", "knee", "ankle"))
        arm_r, leg_r = h*.043*variation, h*.055*variation
        volumes.extend((
            _v(*shoulder, arm_r*1.04, h*.060, arm_r*1.02, .86+p.shoulder_corrective*.08),
            _v((shoulder[0]+elbow[0])*.5, (shoulder[1]+elbow[1])*.5, 0, arm_r*1.08, h*.102*arm_factor, arm_r*1.02, 1.12),
            _v(*elbow, arm_r*.82, h*.034, arm_r*.80, .88),
            _v((elbow[0]+wrist[0])*.5, (elbow[1]+wrist[1])*.5, 0, arm_r*.86, h*.090*arm_factor, arm_r*.83, 1.06),
            _v(*wrist, arm_r*.62, h*.026, arm_r*.58, .86),
            _v(wrist[0], wrist[1]-h*.047*p.hand_scale, -h*.011, arm_r*.92*p.hand_scale, h*.062*p.hand_scale, arm_r*.62*p.hand_scale, 1.0),
            _v(*hip, leg_r*1.02, h*.060, leg_r*.98, .82+p.hip_corrective*.10),
            _v(hip[0], (hip[1]+knee[1])*.53, .006*h, leg_r*1.12, h*.158*leg_factor, leg_r*1.05, 1.15),
            _v(*knee, leg_r*.78, h*.037, leg_r*.76, .88),
            _v(ankle[0], (knee[1]+ankle[1])*.48, 0, leg_r*.84, h*.148*leg_factor, leg_r*.80, 1.06),
            _v(*ankle, leg_r*.58, h*.027, leg_r*.56, .86),
            _v(ankle[0], h*.031, -h*.052, leg_r*.84*p.foot_scale, h*.035, h*.093*p.foot_scale, 1.08),
        ))
    return tuple(volumes)


def generate_character(seed: int, parameters: CharacterParameters | None = None,
                       generator_version: int = GENERATOR_VERSION) -> CharacterAsset:
    if type(seed) is not int or not 0 <= seed < (1 << 64):
        raise ValueError("seed must be an unsigned 64-bit integer")
    p = CharacterParameters() if parameters is None else parameters
    if not isinstance(p, CharacterParameters):
        raise TypeError("parameters must be CharacterParameters")
    if generator_version == 1:
        return generate_character_v1(seed, p)
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"unsupported character generator version {generator_version!r}")
    h = p.height_m
    field = OrganicField(_volumes(seed, p))
    # Odd lattice counts keep bilateral and front/back symmetry planes between
    # samples, avoiding zero-area tetrahedra while preserving a symmetric field.
    cells = ((31, 55, 27), (39, 69, 33), (47, 83, 39))[p.subdivision]
    mesh = extract_surface(field, ((-.43*h, -.025*h, -.23*h), (.43*h, 1.13*h, .23*h)),
                           cells=cells, iso=.07391246751, relaxation_passes=2)
    return CharacterAsset(seed, 2, p, "humanoid.neutral.v2", mesh)
