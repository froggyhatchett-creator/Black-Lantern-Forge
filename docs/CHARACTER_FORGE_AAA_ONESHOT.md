# Black Lantern Character Forge — one-shot experiment

Status: **experimental vertical slice**. Isolated package `forge_character_forge/`, branch
`experiment/character-forge-aaa-oneshot`, started from `5329fb3` (latest committed Step 6C work).
Nothing in `forge/`, `forge_character_studio/`, `forge_desktop/` or `forge_engine_viewer/` was modified;
the only change to an existing file is one `.gitignore` line (`.forge_cache/`). Deleting the package,
`tools/` additions, `tests/test_character_forge_*.py`, `examples/character_forge_aaa/` and this file removes
the experiment completely.

Measured results, tables and file lists for this run are in
[`examples/character_forge_aaa/REPORT.md`](../examples/character_forge_aaa/REPORT.md).

## What it is

A procedural, engine-agnostic human character generator that produces rigged, skinned, morphable,
textured GLB files from a versioned **Character DNA**, plus an image-to-character path that fills a DNA
from reference images and completes unseen anatomy from presets with explicit provenance.

Dependencies: Python 3.13 standard library, **numpy** and **Pillow** (both already installed in this
environment; nothing was installed or downloaded). Node.js (already installed) runs an independent GLB
check. No Blender (not installed), no pretrained models, no third-party meshes or images.

## Architecture (data flow)

```
Character DNA (traits: value, provenance, confidence, locked, sources)
   │ to_spec()
   ▼
CharacterSpec ── params.py (Body/Face/Genital) · appearance.py · outfit
   │
   ├─ skeleton.py      humanoid joints (A-pose, identity rest orientations), physics + dev chains
   ├─ anatomy.py       smooth-CSG signed-distance field in reference meters (body/head/hands/feet)
   ├─ template.py      ONE fixed-topology mesh: per-region surface nets (body 9.5 mm, head 3 mm,
   │                   hands 3 mm), caps removed, loops snapped and zipper-stitched, relaxed
   ├─ body.py          template → per-bone affine proportion warp → Newton projection onto the
   │                   character's own field → tangential relax (topology never changes)
   ├─ rig.py           field-derived skin weights (primitive ownership, soft-min, diffusion, 4
   │                   influences), FK, LBS
   ├─ expressions.py   blink/smile/brow/frown/pucker/lips_part morph targets (vertex deltas)
   ├─ accessories.py   eyes (+cornea), SDF-meshed teeth/gums/tongue, brow & lash cards, hair
   ├─ clothing.py      shrink-wrapped garment shells, parametric skirt/robe, loincloth flaps
   ├─ dev_anatomy.py   developer-only male genital mesh on its own bone chain
   ├─ physics.py       spring-damper secondary motion, colliders, garment support, baking
   ├─ gltf.py          GLB writer (skin, sparse morphs, PBR textures, animations, metadata)
   ├─ validate.py      structural GLB validator + profile rules
   ├─ reconstruct.py   image ingest → segmentation → measurement → regions → fit → DNA
   └─ render.py/preview.py  vectorized software rasterizer used for every image in examples/
```

## Key engineering decisions

* **No licensed base mesh was available**, so geometry is procedural. Instead of a primitive mannequin,
  anatomy is a smooth union of ~170 tagged primitives with dimensions taken from adult anthropometric
  averages (bideltoid/hip breadth, head length/breadth, interpupillary distance, nose/mouth widths).
  It reads as a human figure but is not production sculpt quality.
* **Fixed topology from an implicit field.** The field is meshed once (neutral body) into a closed,
  oriented 2-manifold template (~62k vertices, ~125k triangles). Every character re-uses its vertex
  order and triangles and only moves vertices, so skin weights, UVs, morph targets and garment cut
  regions are computed once and stay valid for every edit.
* **Multi-resolution without cracks**: body, head and hands are meshed on separate grids, each region
  is capped against a bounded cut volume, the caps are deleted, both sides' boundary loops are snapped
  to their cut planes and the skin contour, and a zipper strip joins them.
* **Skin weights come from the same field** that shapes the surface (each primitive belongs to a bone).
* **Rest pose is A-pose with identity joint orientations**, so the glTF skin is simple and
  retarget-friendly (joint nodes carry a `humanoid` name map in `extras`).
* **Profiles are an export-time contract**: `public` rebuilds the body without nipple detail, never
  builds developer parts or joints, auto-adds garments for required coverage and is checked by the
  validator; `developer` must be written to `*.dev.glb` and flags every dev node.
* **Adult-only gate**: `CharacterSpec`/DNA reject `age_years < 18`.
* **Physics is bone-driven** so its output is ordinary joint animation that any glTF runtime plays.

## Image-to-3D: method statement

Hybrid **classic computer vision + procedural fitting**. No pretrained network, landmark model or
generative model is used, because none is available here. Stages: validated ingest (PNG/JPEG/WebP by
content sniffing, size limits, explicit authorization flag, SHA-256), segmentation (alpha channel or
border-color background model + Otsu + morphology + largest component + small-hole fill), hair-aware
silhouette measurement in head-height units, region visibility / posture / stylization detection,
analysis-by-synthesis fitting of visible-region parameters against the SDF body's own silhouette,
color sampling for skin/hair/garments, and DNA output with per-trait provenance.

Full-body completion: every region not visible in the reference is generated from the preset prior and
marked `invented` (or `estimated` when derived from an observed cue). Absolute height is never treated
as observed. Facial detail, eye color and the back of the body are never treated as observed.

## Classification (WORKING / PARTIAL / STUB / BLOCKED / NOT ATTEMPTED)

See the table in `examples/character_forge_aaa/REPORT.md` — it is generated alongside the measured
results so the classifications sit next to their evidence.
