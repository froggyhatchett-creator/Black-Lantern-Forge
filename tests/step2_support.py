"""Shared fixtures and golden values for the Step 2 tests (not a test module)."""

from __future__ import annotations

from functools import lru_cache

from forge import generate_sword
from forge.presentation import PRESENTATION_V1, derive_presentation
from forge.render.settings import PreviewSettings

SMALL = {view: PreviewSettings(1, view, 96, 192, 1) for view in ("three_quarter", "front", "side")}

# Recorded from presentation v1 / preview v1 and verified bit-identical on CPython
# 3.10, 3.11, 3.12, 3.13 (x86-64 Linux). Regression locks: if one fails, a
# versioned algorithm changed. Restore it; put new behavior under a new version.
GOLDEN_1337 = {
    "geometry_sha256": "558b91f33db8aba45a74eb390708aae9b12d4532a6c6f9de24681d687d047439",
    "obj_format1_sha256": "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a",
    "normals_sha256": "e2918ee8a872619ce3ae310a70722368daf60175bb5bc8c01b293cdb150111aa",
    "uvs_sha256": "ecdf3f0dd367f41c65463791e3bdcf603bf5760432540d8aff691d74a1fc24ee",
    "materials_sha256": "c50f5bf1e734e534a008614385c0fab3093cb8cb297d6a1a4504ca5a6d5e8ec9",
}
GOLDEN_1337_RECORD_CONTENT_NO_PREVIEW = "4197741298ae716e03822108a858603ff05b554ae057220140ceae9afe427374"
GOLDEN_1337_PIXELS_SMALL = {
    "three_quarter": "cf00f9bcb9191b31c91c3805129095419839db3d671b99c9732a488767aeab35",
    "front": "c3a8e62a41fc2a13dff5b2a70b57e235dd87de01c2cc9d5bc2ad3857f3db9d46",
    "side": "caafc996b74b42746cf1792513781de3d06bc5948f7fd51b421ceaf032fed778",
}
GOLDEN_1337_PIXELS_DEFAULT = "52d42d8f293134a06e2abfdd2056bb983415e34aa9624a57a5830358bb960605"


@lru_cache(maxsize=None)
def asset(seed: int):
    return generate_sword(seed, 1)


@lru_cache(maxsize=None)
def presented(seed: int):
    return derive_presentation(asset(seed), PRESENTATION_V1)
