"""Fail-closed Blender version pinning.

PINNED_BLENDER_VERSION is a placeholder until Phase 4 fixes the real installed version.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PINNED_BLENDER_VERSION = "4.2.0"

_VERSION_PATTERN = re.compile(r"^Blender\s+(\S+)", re.MULTILINE)


class BlenderVersionError(ValueError):
    """Raised when a Blender executable is missing, fails, or is not the pinned version."""


def check_blender_version(executable: Path) -> str:
    """Run `<executable> --version` and return the parsed version token."""
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BlenderVersionError(f"Blender executable not runnable: {executable}") from exc
    if result.returncode != 0:
        raise BlenderVersionError(
            f"Blender --version exited with code {result.returncode}: {executable}"
        )
    match = _VERSION_PATTERN.search(result.stdout)
    if match is None:
        raise BlenderVersionError(f"Could not parse Blender version from output: {executable}")
    return match.group(1)


def require_pinned_blender(executable: Path) -> Path:
    """Return the executable only if it reports exactly PINNED_BLENDER_VERSION."""
    version = check_blender_version(executable)
    if version != PINNED_BLENDER_VERSION:
        raise BlenderVersionError(
            f"Blender version {version} does not match pinned {PINNED_BLENDER_VERSION}"
        )
    return executable
