"""Shared helpers for the Forge test suite (not a test module)."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION = 1  # generator version under test


def float_bits(asset) -> tuple:
    """Exact bit patterns of every coordinate (distinguishes -0.0 from 0.0)."""
    return tuple(
        (m.name, tuple(struct.pack("<3d", *p) for p in m.positions)) for m in asset.components
    )


def faces(asset) -> tuple:
    return tuple((m.name, m.triangles) for m in asset.components)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_obj(text: str) -> dict:
    """Minimal strict OBJ reader for the subset Forge writes. Raises on anything unexpected."""
    objects: list[str] = []
    vertices: list[tuple[float, float, float]] = []
    faces_: list[tuple[int, int, int]] = []
    comments: list[str] = []
    for lineno, line in enumerate(text.split("\n"), 1):
        if line == "":
            continue
        tag, _, rest = line.partition(" ")
        if tag == "#":
            comments.append(rest)
        elif tag == "o":
            objects.append(rest)
        elif tag == "v":
            parts = rest.split(" ")
            if len(parts) != 3:
                raise ValueError(f"line {lineno}: v needs 3 coords: {line!r}")
            vertices.append(tuple(float(x) for x in parts))
        elif tag == "f":
            parts = rest.split(" ")
            if len(parts) != 3:
                raise ValueError(f"line {lineno}: f needs 3 indices: {line!r}")
            faces_.append(tuple(int(x) for x in parts))
        elif tag == "s":
            if rest != "off":
                raise ValueError(f"line {lineno}: unexpected smoothing {line!r}")
        else:
            raise ValueError(f"line {lineno}: unexpected record {line!r}")
    return {"objects": objects, "vertices": vertices, "faces": faces_, "comments": comments}
