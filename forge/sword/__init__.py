"""Procedural short sword: public entry point and generator-version registry."""

from __future__ import annotations

from typing import Callable

from forge.determinism import require_supported_float_environment
from forge.errors import UnsupportedGeneratorVersionError
from forge.seed import validate_seed
from forge.sword import v1
from forge.sword.asset import COMPONENT_ORDER, SwordAsset
from forge.sword.params import SwordParams

# version -> generator. Released versions are never edited, only added.
_GENERATORS: dict[int, Callable[[int], SwordAsset]] = {
    v1.GENERATOR_VERSION: v1.generate,
}
SUPPORTED_SWORD_VERSIONS: tuple[int, ...] = tuple(sorted(_GENERATORS))
LATEST_SWORD_VERSION: int = SUPPORTED_SWORD_VERSIONS[-1]


def validate_generator_version(version: object) -> int:
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnsupportedGeneratorVersionError(
            f"generator_version must be an int; got {type(version).__name__}: {version!r}"
        )
    if version not in _GENERATORS:
        raise UnsupportedGeneratorVersionError(
            f"unsupported short-sword generator_version {version}; supported: {list(SUPPORTED_SWORD_VERSIONS)}"
        )
    return int(version)


def generate_sword(seed: int, generator_version: int) -> SwordAsset:
    """Deterministically generate a procedural short sword.

    Same (seed, generator_version) -> same parameters, geometry, and OBJ bytes.
    Both arguments are required on purpose: there is no implicit "latest", so
    a future version bump can never silently change an existing caller's sword.

    Raises InvalidSeedError, UnsupportedGeneratorVersionError,
    EnvironmentNotSupportedError, or (on internal bugs) GenerationError /
    GeometryError.
    """
    seed = validate_seed(seed)
    version = validate_generator_version(generator_version)
    require_supported_float_environment()
    return _GENERATORS[version](seed)


__all__ = [
    "COMPONENT_ORDER",
    "LATEST_SWORD_VERSION",
    "SUPPORTED_SWORD_VERSIONS",
    "SwordAsset",
    "SwordParams",
    "generate_sword",
    "validate_generator_version",
]
