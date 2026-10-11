"""Connected organic surface extraction for the Step 6A humanoid prototype.

The body is represented as one smooth compact-support scalar field and meshed
with a deterministic marching-tetrahedra pass.  Anatomical volumes overlap in
the field; they are not exported as intersecting spheres or capsules.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge.errors import GeometryError
from forge.mesh import Mesh


@dataclass(frozen=True)
class FieldVolume:
    center: tuple[float, float, float]
    radii: tuple[float, float, float]
    weight: float = 1.0

    def sample(self, p: tuple[float, float, float]) -> float:
        dx = (p[0] - self.center[0]) / self.radii[0]
        dy = (p[1] - self.center[1]) / self.radii[1]
        dz = (p[2] - self.center[2]) / self.radii[2]
        q = dx * dx + dy * dy + dz * dz
        if q >= 1.0:
            return 0.0
        t = 1.0 - q
        return self.weight * t * t * t

    def gradient(self, p: tuple[float, float, float]) -> tuple[float, float, float]:
        dx = p[0] - self.center[0]
        dy = p[1] - self.center[1]
        dz = p[2] - self.center[2]
        rx2, ry2, rz2 = (r * r for r in self.radii)
        q = dx * dx / rx2 + dy * dy / ry2 + dz * dz / rz2
        if q >= 1.0:
            return (0.0, 0.0, 0.0)
        k = -6.0 * self.weight * (1.0 - q) * (1.0 - q)
        return (k * dx / rx2, k * dy / ry2, k * dz / rz2)


class OrganicField:
    def __init__(self, volumes: tuple[FieldVolume, ...]):
        if not volumes:
            raise GeometryError("an organic field needs at least one volume")
        self.volumes = volumes

    def sample(self, p: tuple[float, float, float]) -> float:
        total = 0.0
        for volume in self.volumes:
            total += volume.sample(p)
        return total

    def gradient(self, p: tuple[float, float, float]) -> tuple[float, float, float]:
        x = y = z = 0.0
        for volume in self.volumes:
            gx, gy, gz = volume.gradient(p)
            x += gx
            y += gy
            z += gz
        return (x, y, z)


_TETS = (
    (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6),
    (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6),
)


def _project_to_field(field: OrganicField, p, iso: float, iterations: int = 3):
    x, y, z = p
    for _ in range(iterations):
        value = field.sample((x, y, z)) - iso
        gx, gy, gz = field.gradient((x, y, z))
        norm2 = gx * gx + gy * gy + gz * gz
        if norm2 <= 1e-18:
            break
        step = max(-0.015, min(0.015, value / norm2))
        x -= step * gx
        y -= step * gy
        z -= step * gz
    return (float(x), float(y), float(z))


def _anatomical_relax(mesh: Mesh, field: OrganicField, iso: float, passes: int) -> Mesh:
    """Tangential relaxation followed by field projection preserves anatomy."""
    if passes <= 0:
        return mesh
    neighbors = [set() for _ in mesh.positions]
    for a, b, c in mesh.triangles:
        neighbors[a].update((b, c)); neighbors[b].update((a, c)); neighbors[c].update((a, b))
    positions = mesh.positions
    for _ in range(passes):
        relaxed = []
        for index, point in enumerate(positions):
            ring = neighbors[index]
            center = tuple(sum(positions[n][axis] for n in ring) / len(ring) for axis in range(3))
            candidate = tuple(point[axis] * .72 + center[axis] * .28 for axis in range(3))
            relaxed.append(_project_to_field(field, candidate, iso))
        positions = tuple(relaxed)
    return Mesh(mesh.name, positions, mesh.triangles)


def extract_surface(field: OrganicField, bounds, cells=(30, 52, 24), iso: float = 0.07123456789,
                    relaxation_passes: int = 0) -> Mesh:
    """Extract one indexed, closed, outward-wound triangle surface."""
    (x0, y0, z0), (x1, y1, z1) = bounds
    nx, ny, nz = cells
    if min(nx, ny, nz) < 4 or not 0.0 < iso < 1.0:
        raise GeometryError("invalid character meshing settings")
    xs = tuple(x0 + (x1 - x0) * i / nx for i in range(nx + 1))
    ys = tuple(y0 + (y1 - y0) * i / ny for i in range(ny + 1))
    zs = tuple(z0 + (z1 - z0) * i / nz for i in range(nz + 1))
    stride_y, stride_z = nx + 1, (nx + 1) * (ny + 1)

    def gid(i, j, k):
        return i + stride_y * j + stride_z * k

    points: dict[int, tuple[float, float, float]] = {}
    values: dict[int, float] = {}
    for k, z in enumerate(zs):
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                n = gid(i, j, k)
                p = (float(x), float(y), float(z))
                points[n] = p
                values[n] = field.sample(p)

    positions: list[tuple[float, float, float]] = []
    edge_vertices: dict[tuple[int, int], int] = {}
    triangles: list[tuple[int, int, int]] = []

    def crossing(a: int, b: int) -> int:
        key = (a, b) if a < b else (b, a)
        found = edge_vertices.get(key)
        if found is not None:
            return found
        fa, fb = values[a], values[b]
        if (fa >= iso) == (fb >= iso) or fa == fb:
            raise GeometryError("internal marching-tetrahedra edge error")
        t = (iso - fa) / (fb - fa)
        pa, pb = points[a], points[b]
        p = (float(pa[0] + (pb[0] - pa[0]) * t),
             float(pa[1] + (pb[1] - pa[1]) * t),
             float(pa[2] + (pb[2] - pa[2]) * t))
        idx = len(positions)
        positions.append(p)
        edge_vertices[key] = idx
        return idx

    def add_triangle(a: int, b: int, c: int) -> None:
        triangles.append((a, b, c))

    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                cube = (
                    gid(i, j, k), gid(i + 1, j, k), gid(i + 1, j + 1, k), gid(i, j + 1, k),
                    gid(i, j, k + 1), gid(i + 1, j, k + 1), gid(i + 1, j + 1, k + 1), gid(i, j + 1, k + 1),
                )
                for tet in _TETS:
                    ids = tuple(cube[n] for n in tet)
                    inside = [n for n in ids if values[n] >= iso]
                    outside = [n for n in ids if values[n] < iso]
                    if not inside or not outside:
                        continue
                    if len(inside) == 1:
                        v = [crossing(inside[0], n) for n in outside]
                        add_triangle(v[0], v[1], v[2])
                    elif len(inside) == 3:
                        v = [crossing(outside[0], n) for n in inside]
                        add_triangle(v[0], v[1], v[2])
                    else:
                        a, b = inside
                        c, d = outside
                        ac, ad = crossing(a, c), crossing(a, d)
                        bc, bd = crossing(b, c), crossing(b, d)
                        add_triangle(ac, ad, bd)
                        add_triangle(ac, bd, bc)
    if not triangles:
        raise GeometryError("character field produced no surface")

    # Orient the indexed surface topologically.  Per-triangle gradient tests are
    # vulnerable near symmetric field saddles; adjacency gives an exact answer.
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fi, triangle in enumerate(triangles):
        a, b, c = triangle
        for u, v in ((a, b), (b, c), (c, a)):
            edge_faces.setdefault((min(u, v), max(u, v)), []).append(fi)
    bad = [edge for edge, faces in edge_faces.items() if len(faces) != 2]
    if bad:
        raise GeometryError(f"character surface is not manifold at edge {bad[0]}")
    oriented = list(triangles)
    visited = {0}
    stack = [0]

    def direction(triangle, edge):
        a, b, c = triangle
        for u, v in ((a, b), (b, c), (c, a)):
            if {u, v} == {edge[0], edge[1]}:
                return (u, v)
        raise AssertionError("edge missing from triangle")

    while stack:
        fi = stack.pop()
        tri = oriented[fi]
        for u, v in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge = (min(u, v), max(u, v))
            adjacent = edge_faces[edge]
            other = adjacent[0] if adjacent[1] == fi else adjacent[1]
            if other in visited:
                continue
            ou, ov = direction(oriented[other], edge)
            if (ou, ov) == (u, v):
                a, b, c = oriented[other]
                oriented[other] = (a, c, b)
            visited.add(other)
            stack.append(other)
    if len(visited) != len(oriented):
        raise GeometryError("character surface contains disconnected shells")
    mesh = Mesh("body", tuple(positions), tuple(oriented))
    if mesh.signed_volume() < 0.0:
        mesh = Mesh("body", mesh.positions, tuple((a, c, b) for a, b, c in mesh.triangles))
    return _anatomical_relax(mesh, field, iso, relaxation_passes)
