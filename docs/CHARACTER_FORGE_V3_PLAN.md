# Generator v3 (MakeHuman CC0 foundation), Phase 1 plan

Goal: one realistic adult v3 human in the real Character Studio with working controls, rig, blink, preview and a
validated GLB export, without touching generators v1/v2, their assets or their DNA.

## Isolation
- New package `forge_character_forge/v3/`. v1/v2 code paths, studio pack, garments and DNA are unchanged.
- Assets under `forge_character_forge/v3/assets/` (CC0, with `PROVENANCE.json`); no MakeHuman/MPFB code.
- Studio: v2 stays the default. v3 loads its own pack (`studio_pack_v3.bin`) and meta (`studio_meta_v3.json`) through a
  generator selector. DNA written from v3 carries `identity.generator = {"id": "forge.character-forge", "version": 3}`.

## Skeleton compatibility (163 MakeHuman bones -> renderer and export limits)
- The v3 export skeleton uses the existing Forge joint names (so clips, poses and physics work by name), minus the six
  `cloth_*` joints (no v2 garments on v3), plus `lid_upper_l/r` and `lid_lower_l/r`: 62 joints, under the renderer's 80.
- Every MakeHuman bone is mapped explicitly (table in `v3/rig.py`); merged bones (twist, metacarpal, face-muscle,
  toe and tongue bones) give their weights to the mapped joint. This is exact for any animation that does not drive a
  merged bone; nothing is truncated silently. Tests check that every bone is mapped and that weights sum to 1.

## Controls
- Each of the 53 studio controls maps to MakeHuman targets (high and low side) or to an exact transform (height in
  metres via uniform scale). Each is labelled direct / approximate / derived in `v3/controls.py`; none is dropped.
- The pack stores per-control vertex deltas (no SDF bake): the targets are already linear deltas.

## Face
- Blink is a morph built from the lid bones, plus a corrective pass: lid vertices are kept on the eyeball surface and the
  displacement is relaxed to remove crumpling. Measured: eyeball exposure, flipped triangles, area change.
- Other expressions (smile, frown, ...) are out of Phase 1 and reported as missing.

## Coverage and garments
- Public v3 characters stay clothed with **v3-fitted** basic garments (offset shells of the v3 body regions, same skin
  weights). v2 garments are not used or claimed on v3.

## Out of scope (Phase 1)
Hair on v3, identity morphs (extension point only), Mercy, alternative body templates, v2 garment fitting, the Python
exact-export path for v3 (the studio pack is the v3 model; the browser export is validated).
