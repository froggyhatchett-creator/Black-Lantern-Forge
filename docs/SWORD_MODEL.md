# Short Sword Model (generator v1)

Source of truth: `forge/sword/params.py`. All bounds are inclusive.
Lengths are meters.

## Parameters

### Blade (diamond cross-section)

| Parameter | Bounds | Meaning |
|---|---|---|
| `point_shape` | `spear` · `acute` · `ogive` | Point profile |
| `length` | 0.42 – 0.60 | Blade base (guard top) to tip, along +Y |
| `base_width` | 0.040 – 0.058 | Edge to edge at the base, along X |
| `thickness` | 0.0050 – 0.0085 | Spine thickness at the base, along Z |
| `taper` | 0.0 – 0.35 | Fraction of width lost by the point shoulder |
| `distal_taper` | 0.20 – 0.60 | Fraction of thickness lost by the point shoulder |
| `point_length_ratio` | spear 0.08–0.14 · acute 0.16–0.26 · ogive 0.10–0.18 | Point length ÷ blade length |

Point shapes: `spear` and `acute` run straight to the tip (short and long
point). `ogive` follows an elliptical edge, `w(s) = w_shoulder·√(1−s²)`, through
three extra cross-sections.

### Guard

| Parameter | Bounds | Meaning |
|---|---|---|
| `shape` | `bar` · `tapered` · `oval` | Box, box narrowing toward the ends, or elliptical plate |
| `width` | 0.090 – 0.150 | Span along X |
| `thickness` | 0.010 – 0.020 | Extent along Y (sword axis) |
| `depth` | 0.024 – 0.036 | Extent along Z |
| `end_scale` | 0.50 – 0.80 | `tapered` only: end cross-section scale. Always drawn so the random stream stays stable. |

### Grip (octagonal cross-section)

| Parameter | Bounds | Meaning |
|---|---|---|
| `length` | 0.085 – 0.110 | Along Y, centered on the origin |
| `radius` | 0.011 – 0.015 | Circumradius at the ends |
| `swell` | 0.0 – 0.12 | Extra radius fraction at mid-grip: `r(s) = r·(1 + swell·4s(1−s))` |
| `segments` | 2 – 5 (int) | Lengthwise loft segments |

### Pommel

| Parameter | Bounds | Meaning |
|---|---|---|
| `shape` | `disc` · `orb` · `faceted` | Beveled 16-gon disc · squashed sphere cut flat at 45° latitude · octagonal double frustum |
| `radius` | 0.018 – 0.028 | Max radius in XZ |
| `height` | 0.016 – 0.030 | Extent along Y |

Derived total length: 0.531 – 0.760 m.

## Draw order (part of the v1 contract)

Each component has its own PCG32 stream (see DETERMINISM.md). Within each stream:

1. **blade**: point_shape, length, base_width, thickness, taper, distal_taper, point_length_ratio
2. **guard**: shape, width, thickness, depth, end_scale
3. **grip**: length, radius, swell, segments
4. **pommel**: shape, radius, height

## Geometry

Every component is built by one primitive, `loft`: a convex cross-section
profile swept along +Y through a list of stations `(y, rx, rz)`, with each end
closed by a fan around a center vertex. A center vertex on the end plane gives
a flat cap; one beyond it gives a point, like the blade tip. The bar and
tapered guards are lofted along their span and rotated onto X with an exact
90° rotation.

Every mesh is validated on construction (finite floats, in-range indices, no
repeated indices, no faces under 1 µm², no unreferenced vertices). The
generator also checks that every component is a closed, consistently oriented,
outward-facing shell. Any violation raises an error. Nothing is repaired.

Vertex and triangle counts vary with the parameters: ogive points add rings,
grip segments vary, and guard and pommel shapes have different topology.
