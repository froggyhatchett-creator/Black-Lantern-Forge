# Blender Bridge Phase 1: rigged character round trip (stopped for review)

## Recommendation: CONDITIONAL GO for Blender-assisted rigging workflows

**Round trip of a native v3 character through Blender 5.2.2: exact, under one condition.** The scene frame rate
must match the file (30 fps). With that:
- the skeleton, skin weights, blink morphs, all 7 clips, materials and textures come back numerically identical;
- independent playback of walk, run, wave and blink matches the original to **0.0012 mm**.

**With Blender's default 24 fps:** every clip is silently resampled and shortened, and the walk is off by up to
**74 mm**. This is the specific incompatibility you asked me to identify (below).

**Editing weights is NO-GO until one tool exists.** The first rigging operation (smoothing one bone's weights on a
copy) worked as intended on the knee, but it exposed a real incompatibility. Blender's weight tools treat glTF
UV-seam copies as separate vertices, so the posed mesh **cracks open along seams (1.6 mm)**. Welding first closes
the cracks but **loses the split (hard-edge) normals on 1,062 seam vertices**. A seam-aware weld that keeps per-corner normals
is needed before any weight edit is trustworthy.

**Conditions**
1. **Pin the scene fps** to the source's rate in every job. The bridge job records it.
2. **Add a Forge-side post-export adapter.** Blender drops Forge's contract metadata, adds constant channels and
   reorders clips (below). The adapter restores the contract metadata and handles the constant channels.
3. **Weight edits** only after a seam-aware weld that preserves split normals.
4. **Verify every output** independently (`rig_compare.py` + playback), never by Blender's own report. Every defect
   in this phase was found that way.

Experiment: `experiments/blender_bridge/`.
- Rig jobs: `rig_roundtrip`, `weights_smooth_copy` (`job_blender.py`).
- Comparison: `rig_compare.py`.
- Renders: `render_rig.py`, `render_weights.py`.
- Job records: `results/jobs/phase1_*`.

The 12 MB output GLBs are not committed; their sha256 values are in the job records.

## Asset

`examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb` (committed and validated; ID-A on
the female body preset). sha256 `c257a6b1…cdafbd3`; **unchanged after every job**.

| Item | Source |
|---|---|
| Meshes | 10 (body, eyes, corneas, top, shorts, brows, lashes, shoulder hair), one primitive each |
| Size | 124,127 vertices, 130,124 triangles |
| Skin | one skin, 62 joints, root `root` |
| Morph targets | `blink_l`, `blink_r` on body, brows, lashes and hair (sparse accessors) |
| Animations | idle, walk, run, jump, turn, sudden_stop, wave: LINEAR, keyed at 30 fps |
| Materials | 8: OPAQUE, MASK for strands, BLEND for corneas |
| Images | 5 PNG: skin albedo 2048², skin normal, eye, two strand masks |
| Metadata | `asset.extras.forge` contract, public profile |

## What Blender sees (inspect; `rig_roundtrip` report)

- **Armature** `id_a`: 62 bones, root `root`.
- **Clips:** 7 actions, each stashed as an NLA track, all LINEAR keys.
- **Meshes:** every mesh parented to the armature with an Armature modifier and 62 vertex groups. At most 4
  influences (brows 2, hair 3, eyes 1). Weight sums exactly 1.0.
- **Shape keys** `blink_l` and `blink_r` on body (387/387 vertices moved), brows, lashes and hair.
- **Hair** keeps its colour attribute. UV maps, materials and the 5 images are all present.
- **Import helper:** the importer adds an `Icosphere` bone-display mesh. My first export picked it up; it is now
  excluded explicitly (`excluded_import_helpers` in the report).

## Round trip: numbers (`rig_compare.py`: Forge reader and validator, numpy, independent player)

| | Default (24 fps scene) | **30 fps scene** |
|---|---|---|
| Forge validator | 0 errors | 0 errors |
| Counts (meshes, vertices, triangles, joints, morphs, clips, materials, images) | identical | identical |
| Joint names / hierarchy / order | same / same / reordered | same / same / reordered |
| Inverse bind matrices | max diff 2e-7 | 2e-7 |
| Rest joint transforms | 0.0002 mm, 0.0° | 0.0002 mm, 0.0° |
| Vertex positions (all meshes) | ≤ 0.00001 mm (brows 0.001 mm) | same |
| Skin weights per joint name | **identical** (0.0) | identical |
| Blink deltas | ≤ 0.00012 mm | ≤ 0.00012 mm |
| UVs | identical except 2 toe-tip vertices (6 triangles; below) | same |
| Normals | ≤ 0.3°, brows ≤ 5.2° (338 of 8,320 vertices > 1°) | same |
| Hair vertex colour | ≤ 0.0039 (8-bit quantisation) | same |
| Materials | factors, alpha mode, cutoff, double-sided identical (float32 rounding) | same |
| Textures | **pixel-identical**, samplers identical | same |
| Clip durations | **all shortened** (walk 1.0333 -> 1.0000 s) | identical |
| Keys per clip | **resampled** (walk 32 -> 25) | identical (walk 32) |
| Values at the source key times | **up to 6.4°, 7.8 mm** | ≤ 0.00003°, ≤ 0.0005 mm |
| Playback: walk / run / wave + blink / blink 0.5 / blink 1 | **74 / 42 / 7.6** / 0.001 / 0.001 mm | **0.001 / 0.001 / 0.0012 / 0.001 / 0.001 mm** |

### Differences that remain at 30 fps (documented, none repaired)

1. **Forge contract metadata dropped.**
   - `asset.extras.forge` (contract id and version, public profile, coverage, generator) is gone.
   - The validator therefore sees no Forge profile and cannot apply the public-profile rules.
   - Needs a Forge-side re-stamp after export.
2. **Constant channels added.**
   - Every clip grows from 6-14 channels to 186: 62 joints × translation, rotation and scale. The added channels
     are constant 2-key STEP values (all verified constant).
   - Playback is unchanged, but in an engine that layers clips, a clip now drives every joint and can override
     other layers.
   - File cost is small: 12.08 MB against 12.19 MB.
3. **Clip and texture order changes.**
   - Clips come out alphabetical, so anything addressing clips by index breaks.
   - Tools that count keyframes also break. `tools/glb_independent_check.mjs` picks a frame by key index of the
     first channel; on the round-trip file, "frame 8" resolved to 1.033 s.
   - Texture entries are reordered, and the shared strand mask gets a duplicate texture entry: the exporter's "more
     than one image node" warning. All material-to-image bindings are verified correct.
4. **Toe-tip UV seam.**
   - At one vertex per foot, the source has two copies with the same position, normal and weights but different
     UVs.
   - After the round trip, 6 of 26,756 body triangles (3 per foot) take the other copy's UV, a 0.118 jump.
   - A tiny texture defect at the toe tips; reproducible.
5. **Brow strand normals:** up to 5.2° different on 338 vertices. Positions are exact.
6. **Hair colour** is 8-bit quantised (≤ 0.4 %).
7. **Draco and meshoptimizer compression** are unavailable in the `bpy` wheel (missing libraries, logged). Not used
   here.

### The default-24 fps incompatibility, specifically

- Forge clips are keyed at k/30 s. With Blender's default scene rate of 24 fps, the importer places them on
  fractional frames (walk ends at frame 24.8).
- The exporter then samples whole frames and drops the fractional tail.
- Every clip loses its last 1/30 s or so and is resampled at 24 fps. Peak rotation error at the original keys is
  6.4° (jump).
- **Fix: set the scene to the file's rate before import** (`"scene_fps": 30` in the job). Verified exact.
- This is the one Blender setting a Forge job must never leave at its default.

## Visual comparisons (Forge renderer; colours from each file's own textures)

| File | Content |
|---|---|
| `results/phase1_rest.jpg` | rest pose, front and three-quarter: source / 30 fps / default 24 fps. Identical |
| `results/phase1_walk.jpg` | walk at t = 0, 8, 16, 24 (/30 s), three rows in the same order. The 24 fps row visibly differs in limb phase |
| `results/phase1_blink.jpg` | blink 0 / 0.5 / 1. Identical in all three |
| `results/phase1_diff.jpg` | per-pixel difference ×10 against the source. 30 fps: a few edge pixels (max 33/255 at blink 0.5, at most 6 pixels > 16). 24 fps: whole-body outlines at walk frames 8, 16, 24 |

## Rigging-related operation: smoothing a copied weight set (`weights_smooth_copy`)

**The operation** (`calf_l`, the left knee):
1. Duplicate the body inside Blender; the original object is renamed, verified unchanged, and left out of the
   export.
2. On the copy only: Smooth (factor 0.5, ×2), Normalize All, Limit Total 4, Normalize All.
3. Export with the copy in place of the body.

| | As imported | Welded first (mitigation variant) |
|---|---|---|
| Changed vertices / max change | 749 / 0.073 | 801 / 0.073 |
| Max influences, weight sums | 4, 1.0 | 4, 1.0 |
| Other meshes, rest pose, blink, clips | unchanged | unchanged |
| Posed change (walk / run) | 2.2 / 3.9 mm, left knee only | 2.0 / 3.6 mm |
| **Seam cracks** (1,122 seam vertex groups) | **68 seams get different weights; opening up to 1.63 mm at run t = 10/30 s** | **0 (closed)** |
| **Hard-edge normals** | kept | **lost on 1,062 seam vertices** (by height: 354 at the feet, 469 at hand height, 202 in the face around the eyes; up to 134°) |
| Vertices after weld | — | 13,380: exactly the v3 template count in the source metadata |

**Evidence**
- `results/phase1_weights_calf_l.jpg`: the crack is the light line on the inner thigh at run t = 10/30 s.
- `results/phase1_weights_calf_l_welded.jpg`: the line is gone.

Each sheet shows the weight heat map before and after, the weight change, and the posed knee in the run clip with
its difference.

**Findings**
- **Headless gotcha:** Blender's vertex-group tools refuse Object mode when headless; the job enters Weight Paint
  mode.
- **A pre-existing Forge weight detail:** one vertex at each knee carries 0.0039 of the *opposite* leg's calf bone.
  The smoothing spread it to a few neighbours (≤ 0.002). It is a Forge source issue, not Blender's. Noted, not
  changed.
- **Garments:** the shorts' weights were not edited to match the body. Editing body weights alone risks garment
  clipping; a real workflow must edit them together.

## Effort and next step (if approved)

| Work | Estimate |
|---|---|
| Post-export adapter (re-stamp the Forge contract, strip constant channels, clip order by name) + `rig_compare` as a gate | 2-3 days |
| Seam-aware weld that preserves per-corner custom normals, re-verified with the crack and normal checks above | 2-4 days |
| Only then: rigging the Rodin model, which has no clean topology and needs operator work first | not started, per instruction |

## Not done, as instructed

No change to the original character, its DNA, any generator, the Studio or Forge's dependencies. No Rodin rigging.
No large GLBs committed.
