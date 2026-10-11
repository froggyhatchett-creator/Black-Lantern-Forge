# Presentation Layer (Step 2)

`derive_presentation(asset, versions) -> PresentedSword` turns a frozen
`SwordAsset` into something you can shade, texture, and export. It's a pure
function of `(asset, versions)`. It reads geometry and never writes it.

## Data model

Normals and UVs are **face-varying attribute streams**, the same model OBJ uses
with `f v/vt/vn`. Per component:

| Field | Meaning |
|---|---|
| `normals` | unique unit normals |
| `normal_indices` | one `(i, j, k)` per frozen triangle, indexing `normals` |
| `uvs` | unique `(u, v)` pairs |
| `uv_indices` | one `(i, j, k)` per frozen triangle, indexing `uvs` |
| `material` | the component's `Material` |

Frozen positions and position indices are never copied, split, or reordered.
That's how "normals/UVs must not alter positions or face indices" is
guaranteed by construction, and the tests check it bit for bit.
`PresentedSword` validates itself on construction: finite values, unit normals,
one triple per triangle, in-range indices, no unreferenced entries.

## Versions

All four are explicit. There's no implicit "latest". `PRESENTATION_V1` is a
named, frozen bundle.

| Field | v1 meaning |
|---|---|
| `presentation_version` | composition: face-varying streams bound to frozen geometry; one material per component, by name |
| `normals_version` | crease-angle normals below |
| `uv_version` | box / cylindrical mapping below |
| `material_version` | palettes, draw order, and procedural pattern formulas below |

A released version is never edited. New behavior gets a new number, and the old
one stays registered so existing records keep reproducing.

## Normals (normals_version 1)

For triangle `f`: raw normal `n_f = (p1 − p0) × (p2 − p0)` (length = 2 × area),
unit normal `u_f = n_f / |n_f|`.

| Component | Mode | Why |
|---|---|---|
| blade | faceted: every corner gets `u_f` | keeps ridge, cutting edges, and point crisp |
| guard | crease 30° | box edges (90°) hard; oval 16-gon sides (22.5°) smooth |
| grip | crease 60° | octagon sides (45°) smooth (wrapped look); end caps hard |
| pommel | crease 30° | disc/orb 16-gon smooth; faceted 8-gon (45°) and disc bevel hard |

**Crease(θ):** the corner of `f` at vertex `v` gets
`normalize(Σ n_g)` over triangles `g` touching `v` with `u_g · u_f ≥ cos θ`,
summed in ascending triangle order. It's area-weighted (angle weighting would
need `acos`). `cos 30° = √3/2` and `cos 60° = 0.5` are exact constants.

**Why the blade is faceted:** measured over 3000 seeds, the blade's true ridge
dihedral (7.7°–22.9° on the body, 1.8°–20° in the point) overlaps the loft's
triangulation twist (0°–6.5°). No single crease angle separates them across the
v1 parameter range. Faceted is the honest, predictable choice. The cost is a faint
seam on some blade flats.

Unique normals are deduplicated by exact value, in first-seen (triangle, corner) order.

## UVs (uv_version 1)

Each component has its own `[0, 1]²` UV space, one material per component.
Every value is guaranteed inside `[0, 1]`. Bounds `B` = the component's
axis-aligned box. `N(axis, x) = (x − min) / (max − min)`.
The dominant axis of a face is the largest `|component|` of its raw normal,
with ties going Y, then Z, then X.

**Box mapping (blade, guard)**

| Dominant axis | UV |
|---|---|
| Z (flats) | `(N(x), N(y))`. Front and back share a mirrored layout. |
| X | `(N(z), N(y))` |
| Y (caps / ends) | `(N(x), N(z))` |

**Cylindrical mapping (grip, pommel)**

- Faces that are Y-dominant, or that touch the Y axis, are planar: `(N(x), N(z))`.
- Every other face gets `u = diamond_angle(x, z) / 4` and `v = N(y)`.
  `diamond_angle` is a trig-free, monotonic stand-in for the polar angle: 0 at
  +X, 1 at +Z, 2 at −X, 3 at −Z.
- **Seam:** if a triangle's corners span more than 0.5 in u, it crosses the
  +X seam, and corners below 0.5 get +1. Every ring has a vertex exactly on +X,
  so the seam lands on u = 1.0 exactly.

There's no packing and no texel-density balancing. These UVs exist for stable
procedural texturing, the preview, and later export.

## Materials (material_version 1)

| Field | Range |
|---|---|
| `preset` | name from the palette |
| `base_color` | RGB, each in [0, 1] |
| `metallic` | 0.0 or 1.0 |
| `roughness` | [0.05, 1.0] |
| `pattern` | procedural surface detail (below) |

| Component | Presets | Pattern |
|---|---|---|
| blade | bright_steel, blued_steel, dark_iron, bronze | brushed |
| guard | brass, bronze, steel, blackened_steel | patina |
| grip | brown_leather, black_leather, oxblood_leather, cord_wrap | wrap |
| pommel | same metals as guard. Matches the guard's preset 3 times in 4. | patina |

`base_color = preset_color × (1 + tint)` with tint in [−0.06, 0.06].
`roughness = preset + jitter` with jitter in [−0.05, 0.05].

**Randomness isolation:** each component draws from
`PCG32(seed, FNV1a64("forge.presentation.material.v1.<component>"))`. These
labels never collide with the geometry labels (`forge.sword.<component>`), and
the generator never sees them. Materials depend on the seed alone, not on
generated geometry, and presentation can't shift geometry randomness. Tests
prove all three.

**Draw order** (part of the contract):

- blade / guard: preset, tint, roughness_jitter, pattern.seed, pattern.strength
- grip: preset, tint, roughness_jitter, pattern.seed, bands, contrast, twist
- pommel: match_guard, preset (always drawn), tint, roughness_jitter,
  pattern.seed, pattern.strength

**Procedural patterns** are evaluated at (u, v) and multiply the base color.
They use integer hashing plus `+ − × ÷ floor` only.

| Pattern | Factor |
|---|---|
| brushed (strength 0.04–0.10) | `1 + s·(2·noise(16u, 2v) − 1)`. Fine lengthwise streaks. |
| patina (strength 0.10–0.25) | `1 − s·(2·noise(5u,5v) + noise(11u,11v))/3`. Blotchy darkening. |
| wrap (bands 7–14, contrast 0.25–0.50, twist 0/1) | `t = bands·v + twist·u`, `f = frac(t)`: `(1 − c + c·4f(1−f)) × (1 + 0.06·(2·noise − 1))`. Leather or cord bands. A twist of 1 is a seamless one-band-per-turn spiral. |

`noise` is smooth value noise: a murmur3-style integer hash on the lattice,
blended with smoothstep bilinear interpolation.
