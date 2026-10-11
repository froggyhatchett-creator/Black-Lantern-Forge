"""The haft, its grip wrap and its butt cap, shared by every hafted family (Step 5B).

Layout along +Y (meters):
  * The grip zone [-G/2, +G/2] is centered on the origin, the grip-centered origin of the frozen
    convention, and the wrap covers it.
  * The haft runs from y_bottom = -G/2 - butt_margin up to y_top = y_bottom + length.
  * The head is seated over the haft's upper end, in the "seat" interval the family gives.
  * The haft is oval: half-width `radius` along X (the head's long axis), `radius * flatten` along Z.
  * Through the seat it is (1 + taper) times wider. A knob flares the butt of an axe haft; a butt
    cap closes the butt of a mace or hammer haft.

Draw helpers read one PCG32 stream each, in a fixed order, drawing every value unconditionally.
"""

from __future__ import annotations

from forge.errors import GeometryError
from forge.hafted.model import ButtCapGeom, GripGeom, HaftGeom
from forge.hafted.shapes import BUTT_CAP_SHAPES, butt_cap, grip_wrap, haft
from forge.mesh import Mesh
from forge.primitives import Station

Range = tuple[float, float]
WRAP_BEVEL = 0.04


def layout(h: HaftGeom, g: GripGeom) -> tuple[float, float, float, float]:
    """(y_bottom, y_top, grip_lo, grip_hi) for a haft and grip."""
    grip_hi = g.length * 0.5
    grip_lo = 0.0 - grip_hi
    y_bottom = grip_lo - h.butt_margin
    return y_bottom, y_bottom + h.length, grip_lo, grip_hi


def bore_volume(rx: float, rz: float, length: float) -> float:
    """Volume of haft (12-sided oval, area 3 * rx * rz) over `length`."""
    return 3.0 * rx * rz * length


def top_radii(h: HaftGeom) -> tuple[float, float]:
    rx = h.radius * (1.0 + h.taper)
    return rx, rx * h.flatten


def build_haft(h: HaftGeom, g: GripGeom, seat_lo: float, seat_hi: float, extra: tuple[float, ...] = ()) -> Mesh:
    """Haft mesh. Stations sit where the tests need vertices:
      * inside the grip zone (+-G/4)
      * at 15% and 85% of the seat
      * at any `extra` heights (for example inside a collar)
    The top 1.5 mm is chamfered by 4%."""
    y_bottom, y_top, grip_lo, grip_hi = layout(h, g)
    r, f = h.radius, h.flatten
    rt, rzt = top_radii(h)
    seat_a = seat_lo + (seat_hi - seat_lo) * 0.15
    seat_b = seat_lo + (seat_hi - seat_lo) * 0.85
    ys: dict[float, tuple[float, float]] = {}

    def at(y: float, rx: float) -> None:
        ys[y] = (rx, rx * f)

    if h.knob > 0.0:
        k = r * (1.0 + h.knob)
        at(y_bottom, k * 0.92)
        at(y_bottom + h.butt_margin * 0.35, k)
        at(y_bottom + h.butt_margin * 0.80, r * (1.0 + h.knob * 0.3))
    else:
        at(y_bottom, r)
    at(grip_lo, r)
    at(grip_lo * 0.5, r)
    at(grip_hi * 0.5, r)
    at(grip_hi, r)
    neck = grip_hi + (seat_lo - grip_hi) * 0.5
    at(neck, r + (rt - r) * 0.5)
    for y in extra:
        frac = (y - grip_hi) / (seat_lo - grip_hi) if y < seat_lo else 1.0
        at(y, r + (rt - r) * frac)
    at(seat_a, rt)
    at(seat_b, rt)
    chamfer_y = y_top - 0.0015
    if chamfer_y > seat_b:
        at(chamfer_y, rt)
    at(y_top, rt * 0.96)
    keys = sorted(ys)
    for a, b in zip(keys, keys[1:]):
        if not b - a > 1e-4:
            raise GeometryError(f"haft stations collide at y = {a!r}, {b!r}")
    if not (keys[0] == y_bottom and keys[-1] == y_top):
        raise GeometryError("haft stations must span the haft")
    stations = [Station(y, ys[y][0], ys[y][1]) for y in keys]
    return haft(stations, y_bottom, y_top)


def build_grip(h: HaftGeom, g: GripGeom) -> Mesh:
    return grip_wrap(g.length, h.radius + g.wrap, h.radius * h.flatten + g.wrap, WRAP_BEVEL)


def build_butt_cap(h: HaftGeom, g: GripGeom, c: ButtCapGeom) -> Mesh:
    y_bottom = layout(h, g)[0]
    return butt_cap(c.shape, y_bottom, h.radius, h.radius * h.flatten, c.radius, c.height)


# ------------------------------------------------------------------ draws (fixed order, every value drawn)

def draw_haft(r, *, length: Range, radius: Range, flatten: Range, taper: Range, knob: Range,
              butt_margin: Range, protrusion: Range) -> HaftGeom:
    return HaftGeom(length=r.uniform(*length), radius=r.uniform(*radius), flatten=r.uniform(*flatten),
                    taper=r.uniform(*taper), knob=r.uniform(*knob), butt_margin=r.uniform(*butt_margin),
                    protrusion=r.uniform(*protrusion))


def draw_grip(r, *, length: Range, wrap: Range) -> GripGeom:
    return GripGeom(length=r.uniform(*length), wrap=r.uniform(*wrap))


def draw_butt_cap(r, *, haft_radius: float, shapes: tuple[str, ...], radius_ratio: Range,
                  height: Range) -> ButtCapGeom:
    shape = r.choice(shapes)
    radius = haft_radius * r.uniform(*radius_ratio)
    if shape not in BUTT_CAP_SHAPES:
        raise GeometryError(f"unknown butt cap shape {shape!r}")
    return ButtCapGeom(shape=shape, radius=radius, height=r.uniform(*height))
