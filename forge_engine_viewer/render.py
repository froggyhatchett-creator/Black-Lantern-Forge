"""Headless renderer: turns an ingested package into a frame of 2D draw items (no Tk here).

Coordinate boundary (the only conversion this viewer makes):
  canonical asset space  right-handed, +Y up, meters, grip-centered origin (exactly the package)
      | camera rotation: yaw about +Y by azimuth, then pitch about +X by elevation
  viewer space           x right, y up, z toward the viewer (still meters)
      | orthographic fit: screen_x = cx + s * x, screen_y = cy - s * y  (screen y grows downward)
  screen space           canvas pixels
Everything a user reads (socket values, manifest values, hashes) stays canonical. This module only
reads the ingested model and never writes back into it.

Shading is a small approximation driven by the package's PBR factors. It is not PBR:
  * diffuse  = baseColor * (1 - metallic) * (ambient + Lambert)
  * specular = Blinn-Phong whose tint goes from 0.04 to baseColor with metallic, and whose
               sharpness comes from roughness
  * a faint sky/ground term stands in for environment reflection on metals
Normals come from the package's NORMAL attribute (the triangle's three corner normals, averaged).
Visibility: back faces are culled with the contract's declared front-face winding
(counter-clockwise), then the remaining triangles are drawn far-to-near (painter's algorithm).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from forge_engine_viewer.ingest import IngestedPackage, rotate

VIEWS = {                     # name -> (azimuth, elevation) in degrees, canonical frame
    "three_quarter": (-35.0, 20.0),
    "front": (0.0, 0.0),      # camera on +Z looking at -Z: +X right, +Y up (blade flats face the camera)
    "side": (-90.0, 0.0),     # camera on +X looking at -X: -Z right, +Y up (blade edge-on)
}
DEFAULT_VIEW = "three_quarter"
MODES = ("render", "render+collision", "collision")
MODE_LABELS = {"render": "Render", "render+collision": "Render + collision", "collision": "Collision only"}
SOCKET_AXIS_LENGTH_M = 0.05
_LIGHT = (-0.45, 0.65, 0.62)
_BACKGROUND = "#1c1d21"


def _normalize(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n else (0.0, 0.0, 1.0)


LIGHT = _normalize(_LIGHT)
HALF = _normalize((LIGHT[0], LIGHT[1], LIGHT[2] + 1.0))


@dataclass(frozen=True)
class Camera:
    azimuth: float = VIEWS[DEFAULT_VIEW][0]
    elevation: float = VIEWS[DEFAULT_VIEW][1]
    name: str = DEFAULT_VIEW

    @staticmethod
    def preset(name: str) -> "Camera":
        az, el = VIEWS[name]
        return Camera(az, el, name)

    def orbited(self, d_azimuth: float, d_elevation: float) -> "Camera":
        return Camera(self.azimuth + d_azimuth, max(-89.0, min(89.0, self.elevation + d_elevation)), "orbit")

    def to_view(self, p):
        """Canonical point/direction -> viewer space. Pure; the input is not modified."""
        a, e = math.radians(self.azimuth), math.radians(self.elevation)
        ca, sa, ce, se = math.cos(a), math.sin(a), math.cos(e), math.sin(e)
        x = p[0] * ca + p[2] * sa
        z = -p[0] * sa + p[2] * ca
        y = p[1]
        return (x, y * ce - z * se, y * se + z * ce)


@dataclass(frozen=True)
class Polygon:
    points: tuple
    fill: str
    outline: str
    depth: float
    layer: str          # "render" | "collision"
    source: str         # node name


@dataclass(frozen=True)
class Line:
    a: tuple
    b: tuple
    fill: str
    width: float
    dash: tuple
    layer: str          # "collision" | "socket" | "gizmo"


@dataclass(frozen=True)
class Marker:
    center: tuple
    radius: float
    fill: str
    label: str
    layer: str = "socket"


@dataclass(frozen=True)
class Text:
    position: tuple
    text: str
    fill: str
    layer: str = "gizmo"


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    camera: Camera
    mode: str
    show_sockets: bool
    background: str
    items: tuple
    stats: dict = field(default_factory=dict)

    def layer(self, name: str) -> tuple:
        return tuple(i for i in self.items if i.layer == name)


def _srgb(c: float) -> int:
    c = min(1.0, max(0.0, c))
    s = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return int(round(s * 255))


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(_srgb(c) for c in rgb)


def shade(material, normal_view) -> tuple[float, float, float]:
    """Linear RGB for a facet with this view-space normal under the fixed key light."""
    n = _normalize(normal_view)
    base = material.base_color_factor[:3]
    m, r = material.metallic_factor, material.roughness_factor
    lambert = max(0.0, n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2])
    sky = 0.5 + 0.5 * n[1]
    ambient = 0.10 + 0.14 * sky
    shininess = 4.0 + (1.0 - r) ** 2 * 160.0
    spec = max(0.0, n[0] * HALF[0] + n[1] * HALF[1] + n[2] * HALF[2]) ** shininess * (1.0 - 0.6 * r)
    out = []
    for c in base:
        kd = c * (1.0 - m)
        ks = 0.04 * (1.0 - m) + c * m
        env = ks * m * (0.18 + 0.32 * sky)
        out.append(kd * (ambient + 0.9 * lambert) + ks * spec * 1.4 + env)
    return tuple(out)


def _fit(points, width, height, side=28, top=52, bottom=40):
    """Orthographic fit of viewer-space points into the canvas (a band at the top is kept for the caption)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    lo_x, hi_x, lo_y, hi_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(hi_x - lo_x, 1e-6), max(hi_y - lo_y, 1e-6)
    scale = max(1e-6, min((width - 2 * side) / span_x, (height - top - bottom) / span_y))
    cx, cy = (lo_x + hi_x) / 2.0, (lo_y + hi_y) / 2.0
    mid_y = top + (height - top - bottom) / 2.0

    def to_screen(v):
        return (width / 2.0 + (v[0] - cx) * scale, mid_y - (v[1] - cy) * scale)
    return to_screen, scale


def build_frame(pkg: IngestedPackage, *, width: int, height: int, camera: Camera | None = None,
                mode: str = "render", show_sockets: bool = False) -> Frame:
    if mode not in MODES:
        raise ValueError(f"unknown display mode {mode!r}; modes: {MODES}")
    camera = camera or Camera()
    world_meshes = [(mesh, [mesh.world.apply(p) for p in mesh.positions]) for mesh in pkg.meshes]
    hull_world = [pkg.collision.world.apply(p) for p in pkg.collision.positions]
    view_meshes = [(mesh, [camera.to_view(p) for p in pts]) for mesh, pts in world_meshes]
    hull_view = [camera.to_view(p) for p in hull_world]
    # one fit for every mode, so toggling overlays never rescales the picture
    to_screen, scale = _fit([v for _, pts in view_meshes for v in pts] + hull_view, width, height)
    ccw = pkg.coordinates["front_face_winding"] == "counter_clockwise"

    def front_facing(a, b, c) -> bool:
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return area > 0.0 if ccw else area < 0.0

    items, stats = [], {"render_triangles": 0, "render_culled": 0, "collision_edges": 0,
                        "collision_faces": 0, "sockets": 0}
    if mode in ("render", "render+collision"):
        polys = []
        for mesh, vpts in view_meshes:
            material = pkg.materials[mesh.material_index]
            nview = [camera.to_view(rotate(mesh.world.rotation, n)) for n in mesh.normals]
            idx = mesh.indices
            for t in range(0, len(idx), 3):
                a, b, c = vpts[idx[t]], vpts[idx[t + 1]], vpts[idx[t + 2]]
                if not front_facing(a, b, c):
                    stats["render_culled"] += 1
                    continue
                na, nb, nc = nview[idx[t]], nview[idx[t + 1]], nview[idx[t + 2]]
                color = _hex(shade(material, (na[0] + nb[0] + nc[0], na[1] + nb[1] + nc[1], na[2] + nb[2] + nc[2])))
                polys.append(Polygon(points=(to_screen(a), to_screen(b), to_screen(c)), fill=color, outline=color,
                                     depth=(a[2] + b[2] + c[2]) / 3.0, layer="render", source=mesh.node))
        polys.sort(key=lambda p: p.depth)
        stats["render_triangles"] = len(polys)
        items += polys

    if mode in ("render+collision", "collision"):
        h = pkg.collision.indices
        front_faces = set()
        faces = []
        for t in range(0, len(h), 3):
            a, b, c = hull_view[h[t]], hull_view[h[t + 1]], hull_view[h[t + 2]]
            if front_facing(a, b, c):
                front_faces.add(t // 3)
                faces.append(Polygon(points=(to_screen(a), to_screen(b), to_screen(c)), fill="#20475e",
                                     outline="#20475e", depth=(a[2] + b[2] + c[2]) / 3.0, layer="collision",
                                     source=pkg.collision.node))
        if mode == "collision":
            faces.sort(key=lambda p: p.depth)
            items += faces
            stats["collision_faces"] = len(faces)
        edge_faces: dict = {}
        for t in range(0, len(h), 3):
            for e in ((h[t], h[t + 1]), (h[t + 1], h[t + 2]), (h[t + 2], h[t])):
                edge_faces.setdefault(tuple(sorted(e)), []).append(t // 3)
        back, front = [], []
        for (i, j), owners in sorted(edge_faces.items()):
            seen = any(f in front_faces for f in owners)
            line = Line(a=to_screen(hull_view[i]), b=to_screen(hull_view[j]),
                        fill="#58d0ff" if seen else "#2f6f8a", width=1.4 if seen else 1.0,
                        dash=() if seen else (3, 3), layer="collision")
            (front if seen else back).append(line)
        items += back + front
        stats["collision_edges"] = len(back) + len(front)

    if show_sockets:
        for s in pkg.sockets:
            origin_view = camera.to_view(s.world.translation)
            centre = to_screen(origin_view)
            for axis, color in (((1.0, 0.0, 0.0), "#ff5a5a"), ((0.0, 1.0, 0.0), "#5aff7a"), ((0.0, 0.0, 1.0), "#5a9bff")):
                d = rotate(s.world.rotation, axis)
                tip = tuple(s.world.translation[k] + SOCKET_AXIS_LENGTH_M * d[k] for k in range(3))
                items.append(Line(a=centre, b=to_screen(camera.to_view(tip)), fill=color, width=2.0, dash=(),
                                  layer="socket"))
            t = s.world.translation
            items.append(Marker(center=centre, radius=5.0, fill="#ffcc33",
                                label=f"{s.name}  ({t[0]:.4g}, {t[1]:.4g}, {t[2]:.4g}) m"))
            stats["sockets"] += 1

    # canonical axes gizmo, bottom-left: shows how +X/+Y/+Z land on screen for this camera
    origin = (44.0, height - 44.0)
    for label, axis, color in (("X", (1.0, 0.0, 0.0), "#ff5a5a"), ("Y", (0.0, 1.0, 0.0), "#5aff7a"),
                               ("Z", (0.0, 0.0, 1.0), "#5a9bff")):
        v = camera.to_view(axis)
        tip = (origin[0] + 26.0 * v[0], origin[1] - 26.0 * v[1])
        items.append(Line(a=origin, b=tip, fill=color, width=2.0, dash=(), layer="gizmo"))
        if abs(v[0]) + abs(v[1]) > 0.2:          # an axis pointing at the camera has no visible length
            items.append(Text(position=(origin[0] + 34.0 * v[0], origin[1] - 34.0 * v[1]), text=label, fill=color))
    stats["scale_px_per_m"] = scale
    return Frame(width=width, height=height, camera=camera, mode=mode, show_sockets=show_sockets,
                 background=_BACKGROUND, items=tuple(items), stats=stats)
