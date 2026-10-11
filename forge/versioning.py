"""Shared strict version check for Step 2 version fields."""

from __future__ import annotations

from forge.errors import UnsupportedVersionError


def require_version(field: str, value: object, supported: tuple[int, ...]) -> int:
    """Return value if it is a plain int listed in `supported`; else raise UnsupportedVersionError.

    bool and float are rejected even when equal to a supported int (True == 1, 1.0 == 1).
    """
    if type(value) is not int or value not in supported:
        raise UnsupportedVersionError(
            f"unsupported {field} {value!r}; supported: {list(supported)}"
        )
    return value
