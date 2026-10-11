"""Vertex normals, derived purely from frozen mesh geometry.

normals_version 1
-----------------
For every triangle f, the raw face normal is n_f = (p1 - p0) x (p2 - p0); its
length is twice the triangle area. Its unit form is u_f = n_f / |n_f|.

Each component uses one of two modes:

  faceted         every corner of f gets u_f.
  crease(theta)   the corner of f at vertex v gets the normalized sum of n_g
                  (area weighted) over every triangle g that touches v and
                  satisfies u_g . u_f >= cos(theta). Faces past the crease angle
                  don't blend, so hard edges stay hard. Summation runs in
                  ascending triangle index.

Component modes (v1):
  blade   faceted        keeps the diamond ridge, cutting edges, and point crisp.
                         (No single crease angle separates the ridge from loft
                         triangulation twist across the v1 range, so faceted
                         is the honest choice; see docs/PRESENTATION.md.)
  guard   crease 30 deg  box edges (90) hard; oval 16-gon sides (22.5) smooth.
  grip    crease 60 deg  octagon sides (45) smooth; end caps (90) hard.
  pommel  crease 30 deg  disc/orb 16-gon (22.5) smooth; faceted 8-gon (45) and
                         the disc bevel stay hard.

Unique normals are deduplicated by exact value in first-seen (triangle, corner)
order, giving a list of normals plus one index triple per triangle.

Only + - * / and sqrt are used, so results are bit-identical on IEEE-754
platforms. Positions and position indices are never modified.
"""

from __future__ import annotations

import math

from forge.errors import PresentationError
from forge.mesh import Mesh, Tri, Vec3
from forge.versioning import require_version

COS_30 = math.sqrt(3.0) * 0.5
COS_60 = 0.5

NORMALS_V1_MODES: dict[str, tuple[str, float]] = {
    "blade": ("faceted", 1.0),
    "guard": ("crease", COS_30),
    "grip": ("crease", COS_60),
    "pommel": ("crease", COS_30),
}

SUPPORTED_NORMALS_VERSIONS = (1,)


def raw_face_normals(mesh: Mesh) -> list[Vec3]:
    out = []
    p = mesh.positions
    for a, b, c in mesh.triangles:
        ax, ay, az = p[a]
        ux, uy, uz = p[b][0] - ax, p[b][1] - ay, p[b][2] - az
        vx, vy, vz = p[c][0] - ax, p[c][1] - ay, p[c][2] - az
        out.append((uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx))
    return out


def _unit(v: Vec3, what: str) -> Vec3:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not (length > 0.0 and math.isfinite(length)):
        raise PresentationError(f"cannot normalize {what}: {v!r}")
    return (v[0] / length, v[1] / length, v[2] / length)


def compute_normals_v1(mesh: Mesh) -> tuple[tuple[Vec3, ...], tuple[Tri, ...]]:
    if mesh.name not in NORMALS_V1_MODES:
        raise PresentationError(f"normals v1 has no mode for component {mesh.name!r}")
    mode, cos_limit = NORMALS_V1_MODES[mesh.name]
    raw = raw_face_normals(mesh)
    unit = [_unit(n, f"face normal of {mesh.name!r} triangle {f}") for f, n in enumerate(raw)]

    if mode == "faceted":
        corner = [(u, u, u) for u in unit]
    else:
        incident: list[list[int]] = [[] for _ in range(mesh.vertex_count)]
        for f, tri in enumerate(mesh.triangles):
            for v in tri:
                incident[v].append(f)  # ascending f by construction
        corner = []
        for f, tri in enumerate(mesh.triangles):
            uf = unit[f]
            normals_for_tri = []
            for v in tri:
                sx = sy = sz = 0.0
                for g in incident[v]:
                    ug = unit[g]
                    if ug[0] * uf[0] + ug[1] * uf[1] + ug[2] * uf[2] >= cos_limit:
                        rg = raw[g]
                        sx += rg[0]
                        sy += rg[1]
                        sz += rg[2]
                normals_for_tri.append(_unit((sx, sy, sz), f"smoothed normal at vertex {v}"))
            corner.append(tuple(normals_for_tri))

    return _dedupe(corner)


def _dedupe(corner: list[tuple[Vec3, Vec3, Vec3]]) -> tuple[tuple[Vec3, ...], tuple[Tri, ...]]:
    index: dict[Vec3, int] = {}
    values: list[Vec3] = []
    triples: list[Tri] = []
    for tri in corner:
        ids = []
        for n in tri:
            i = index.get(n)
            if i is None:
                i = index[n] = len(values)
                values.append(n)
            ids.append(i)
        triples.append((ids[0], ids[1], ids[2]))
    return tuple(values), tuple(triples)


def compute_normals(mesh: Mesh, normals_version: int) -> tuple[tuple[Vec3, ...], tuple[Tri, ...]]:
    require_version("normals_version", normals_version, SUPPORTED_NORMALS_VERSIONS)
    return compute_normals_v1(mesh)
