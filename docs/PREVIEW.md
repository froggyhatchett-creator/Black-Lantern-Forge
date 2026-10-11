# Preview Renderer (Step 2)

A small software rasterizer in pure Python with no dependencies. No GPU, no
OpenGL, no GUI. It produces a PNG of the full sword with fixed framing.

## Why a software renderer

Forge's priorities are determinism, inspectability, and zero dependencies. A
GPU or OpenGL path would add a large native dependency and make pixels depend
on drivers. The cost of pure Python is speed: about 2–3 s at the default size.
That's fine for a preview.

## Settings (`PreviewSettings`, preview_version 1)

| Field | Default | Range |
|---|---|---|
| `preview_version` | 1 | supported: [1] |
| `view` | `three_quarter` | `three_quarter`, `front`, `side` |
| `width` × `height` | 480 × 960 | 16–4096 each |
| `ssaa` | 2 | 1–4 (samples per pixel = ssaa²) |

## Camera (fixed, documented)

Orthographic, so there's no perspective divide and attribute interpolation is
exactly affine.

**Framing is fixed in world space** and doesn't depend on the asset. Every v1
sword appears at the same scale and position, so previews line up for
comparison.

| Constant | Value |
|---|---|
| target | (0, 0.295, 0) m: midpoint of the v1 Y range [−0.085, 0.675] |
| frame height | 0.84 m; frame width = 0.84 × W/H |
| screen up | world +Y (the coordinate system is preserved; tip points up) |

| View | Direction toward camera | Notes |
|---|---|---|
| `three_quarter` | (1, 0.5, 2) | default; about 26.6° yaw, 12.6° elevation |
| `front` | (0, 0, 1) | blade flat; +X = screen right |
| `side` | (1, 0, 0) | blade edge; −Z = screen right |

Basis: `d = normalize(direction)`, `right = normalize(Y × d)`, `up = d × right`.
A test projects every vertex of 66 seeds in all three views and checks that it
lands inside the frame.

## Pipeline

1. **Project and cull.** Project triangles in fixed order (component order,
   then face order). Cull back faces by screen-space signed area.
2. **Rasterize.** Write a z-buffer at (W·ssaa) × (H·ssaa) samples. Each sample
   center is tested with inclusive edge functions (no cracks); depth ties keep
   the first-drawn triangle. Each sample stores a triangle id and barycentrics,
   and shading is deferred.
3. **Shade each visible sample once.**
   - Interpolate the normal and normalize it. Interpolate the UV.
   - `material.sample(u, v)` returns the procedural texture color.
   - Blinn-Phong with two camera-relative lights (key upper-left, fill right)
     plus ambient. The exponent is `int(2/r² − 2)`, computed by integer
     squaring.
   - Metals take their color from a camera-space studio environment: a vertical
     sky/floor gradient, left/right falloff, a softbox at camera-left, and a
     softbox behind the camera. It's blurred by roughness.
4. **Encode.** The display value is `sqrt(color)`, a gamma-2 approximation;
   `sqrt` is exact. Background: a vertical gray gradient. Each pixel is the mean
   of its ssaa² samples, quantized as `int(255·x + 0.5)`.

**Not physically based.** The goal is readable surfaces, not realism.

## PNG output

8-bit RGB, non-interlaced, filter 0, zlib level 9. Two `tEXt` chunks:
`Software` and `forge.preview`. The latter is canonical JSON holding the seed,
all versions, preview settings, camera basis, `pixels_sha256`, and, when
rendered from or with a record, `record_content_sha256`. No timestamps.

## Determinism boundary (what's actually verified)

| Claim | Status |
|---|---|
| Same presented sword + same settings → identical pixel buffer (`pixels_sha256`) | **Verified**: CPython 3.10, 3.11, 3.12, 3.13 on x86-64 Linux. Golden hashes in tests. |
| Identical pixels on other OSes and CPUs (macOS, Windows, ARM64) | **Argued, not tested.** The renderer uses only `+ − × ÷ √`, comparisons, and integer ops, all exactly specified by IEEE 754, with no libm transcendentals. A static test enforces this. |
| Identical PNG file bytes | **Only for the same zlib build.** zlib and zlib-ng can produce different, equally valid compressed streams. Compare `pixels_sha256`, not file hashes. |

`python -m forge preview record.json` re-renders and, when the record stores a
pixel hash and the settings aren't overridden, verifies it. A mismatch exits
with code 3.

## Step 5A: `forge.preview.fit` v1 (geometry-bound framing)

The fixed camera above is preview `forge.preview` v1. It frames 0.84 m, sized for the short
sword, and it stays the short sword's renderer, so the short sword's pixels can't change.

The blade families register a second renderer, `forge.preview.fit` v1 (`forge/render/fit.py`).
It reuses the same settings, view bases, rasterizer, shading, PNG and metadata. Only the
framing differs:

- **Extents.** Every vertex of every component is projected onto the view's right and up axes.
- **Target.** The center of those projected extents, at zero depth along the view direction.
- **Frame.** `half_height = max(span_up / 2, span_right / 2 · H / W) · 1.06`, and
  `half_width = half_height · W / H`.

It uses only `+ − × ÷` and comparisons, so the framing is as deterministic as the geometry. The
fitted camera is written into the PNG's `forge.preview` metadata, like the fixed camera. Which
renderer an asset uses comes from its registry descriptor (`preview_id`). `PreviewSettings` still
accepts only `preview_version` 1. A new renderer *id* fits that frozen schema, where a v2 of
`forge.preview` would not. See [ARSENAL_BLADES.md](ARSENAL_BLADES.md#9-preview-forgepreviewfit-v1).

## Step 5B: hafted families use `forge.preview.fit` v1 unchanged

The four hafted families (`one_hand_axe`, `two_hand_axe`, `mace`, `war_hammer`) register the
same `forge.preview.fit` v1 renderer. Nothing about the renderer changed: an axe or a hammer is
framed from its own vertices exactly as a blade is, so a wide head and a long haft both fit. Each
family's seed-1337 pixel hash is pinned in `examples/hafted_seed1337.golden.json`. See
[HAFTED_WEAPONS.md](HAFTED_WEAPONS.md).
