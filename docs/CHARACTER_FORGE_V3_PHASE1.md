# Generator v3, Phase 1: realistic human foundation (milestone report)

Status: **Phase 1 milestone reached; stopped for review.** One realistic adult human (MakeHuman hm08 CC0 base) runs in
the real Character Studio behind a generator selector, with all 53 controls, a 62-joint rig, a corrected blink,
v3-fitted basic garments, poses and clips, and a validated browser GLB export. Generators v1/v2 are unchanged.

Open it: `python3 -m forge_character_forge studio`, then `http://127.0.0.1:8765/?gen=3` (or pick "v3" in the
Generator menu; static hosting uses `#v3`). Evidence: `examples/character_forge_aaa/humanity/v3_phase1/`.

## What was built
| Piece | Where | Notes |
|---|---|---|
| CC0 assets, provenance | `forge_character_forge/v3/assets/` | 169 files (8.5 MB): base mesh, eyes, skeleton, weights, face pose units, 162 targets. Each target's CC0 header is checked; sha256 and source URL per file in `PROVENANCE.json` (test re-hashes). No MakeHuman/MPFB code. `tools/v3_fetch_assets.py` rebuilds the set. |
| Readers | `v3/mh.py` | OBJ with UVs, targets, mhclo eye fitting, skeleton, weights, BVH pose units. |
| Neutral and controls | `v3/model.py`, `v3/controls.py` | Neutral = hm08 + 0.5 female + 0.5 male macro, scaled to 1.75 m, soles at y = 0. Each control end is a sum of targets (linear), soles kept on the floor. |
| Rig | `v3/rig.py` | 163 bones -> 62 joints (below). |
| Blink | `v3/model.py` (`blink_delta`, `fit_blink`) | Corrected lid closure, fitted per eye shape (below). |
| Garments | `v3/garments.py` | `basic_top`, `basic_shorts`: the v3 body clipped by planes through the rig's joints, offset 6/8 mm, skinned with interpolated body weights. |
| Pack | `v3/bake.py` -> `examples/.../studio/studio_pack_v3.bin` (1.33 MB), `studio/studio_meta_v3.json` | Same FORGEPK1 container as v2. Bake: about 2 min (blink fitting); no SDF bake. Reproducible byte for byte (test). |
| Studio | `studio/studio.js`, `gl.js`, `glb.js`, `index.html` | Generator selector; UV-seam-welded normals; eye centre by sphere fit; iris angle per part; exact height; meta-driven coverage, styling and breast support; DNA `identity.generator`; mismatch note when loading DNA from another generator; "approx."/"derived" badges on sliders; hair panel hidden on v3; blink correctives in preview and export. v2 behaviour unchanged (23/23 v2 smoke checks pass). |

## The 53 controls (requirement 4)
36 direct, 16 approximate, 1 derived; none dropped or silently substituted. Each approximate/derived control says what
it does instead (meta `controls`, slider badge tooltip, `v3/controls.py`):

- **Approximate (16):** body_fat (MakeHuman weight = fat + mass), shoulder_width (V-shape), chest_width/depth (whole
  torso), waist_width (half torso width: no waist target), belly (pregnancy shape), breast_projection (nipple point),
  face_width (whole head), face_length (chin + half head height), jaw_width (chin bones), jaw_angle (square/oval
  head), nose_bridge (Greek bridge), nose_tip (tip width), brow_prominence (moves the brow, no ridge), eye_tilt (one
  corner), ear_protrusion (ear wing).
- **Derived (1), the remaining control:** asymmetry. MakeHuman has no asymmetry target; v3 builds it from unequal
  left/right targets (cheekbone, eye corner, ear), one side only.
- **Height** is exact: the studio scales the evaluated character to the requested height (measured 1.45 and 2.10 m at
  the slider ends). Femininity moves between the pure female and male macros.
- Measured in the studio: every control moves the body at each used end (53/53), table in `v3_check.json`
  (moved vertices and maximum displacement per end).

## Skeleton: 163 bones, 80-joint renderer, 64-joint export (requirement 5)
- v3 exports 62 joints: the v1/v2 Forge names minus the six `cloth_*` joints (no v2 garments on v3) plus
  `lid_upper_l/r`, `lid_lower_l/r`. Under both limits, with no truncation.
- Every MakeHuman bone maps to exactly one joint by explicit rules (tested: all 163 resolve; no two explicit rules
  overlap). Merged bones give their weights to the joint: twist bones (upper/lower arm, leg), metacarpals into the
  hand, toes into the ball, neck01-03, spine pairs, 34 face-muscle bones into head, jaw/lower lip/tongue (19) into jaw.
  What is lost is independent motion of merged bones; poses that drive Forge joints deform exactly as MakeHuman's own
  skinning. Per-vertex influences: top four of the merged weights, renormalised (mean dropped weight 0.1%, maximum
  34% at one vertex). Every skin vertex is weighted.
- Joint rest orientations are identity, as in v1/v2, so the existing poses and seven clips apply by name. Verified:
  Relaxed, Arms raised, Lunge, walk frame 8 (`sheet_rig.png`); the independent GLB loader skins every vertex for walk
  frame 8.

## Blink (requirement 6)
MakeHuman's lid bones close the lid by linear blend skinning: partially weighted vertices travel along chords into
the eyeball and the lid crumples (46 folded triangles on the v3 neutral). The v3 corrective:
1. each lid vertex rotates by (its weight x the closing angle) about the lid pivot (no chord collapse);
2. the displacement is Laplacian-relaxed over the lid region (+2 rings);
3. lid vertices are kept off the cornea (at least their open distance from the eye centre);
4. any triangle still folded is untangled locally;
5. the closing angle and a lower-lid raise are **fitted per eye shape** (grid: close fully, then fewest folds);
6. every control end that reshapes the lids (37 ends) carries a blink corrective, applied in proportion to the
   control and the blink (bilinear), in the studio preview and in the exported morph target.

| Case (front view, eyeball exposure relative to open) | Closed | 50% | Folded lid triangles |
|---|---|---|---|
| Neutral, v3 corrective | 0.0% | 46.7% | 4 of 2,170 |
| Neutral, MakeHuman bone skinning | 0.0% | 35.7% | 46 |
| Female preset, with correctives | 0.0% | 45.4% | 15 |
| Female preset, without correctives (fixed morph) | 4.5% | 51% | 4 |
| Male preset, with correctives | 0.0% | 46.8% | 14 |
| Every fitted control end | at most 0.33% | | 2 to 32 |

`sheet_blink.png` (studio, female preset: open, half, closed; front and 3/4) shows a smooth closed lid line.
`blink_report.json` has all numbers.

## Export (requirement 7)
Browser GLB of the female preset (`v3_studio_export.glb`, 1.7 MB): `validate_glb` passes with the public profile
(7 meshes, 33,596 triangles, 62 joints, 2 morph targets, 7 animations, no errors or warnings); the independent Node
loader (`glb_independent_check.mjs`) parses, poses walk frame 8 and skins every vertex. The body carries MakeHuman's
UVs (TEXCOORD_0, split at seams: 14,517 GPU vertices for the 13,380-vertex template). DNA records
`identity.generator = {id: forge.character-forge, version: 3}`.

## Requirements checklist
1. v1/v2 preserved: no v1/v2 source, pack, garments or DNA changed; `GENERATOR_VERSION` stays 2; v2 pack still
   stamped v2 (test); v2 studio smoke 23/23; v2 GLB export path unchanged (UVs export only for welded v3 bodies).
2. Independent versioned foundation with documented CC0 assets: `forge_character_forge/v3/`, provenance tested.
3. Topology, UVs, anatomy preserved: the hm08 body is used as is (13,380 vertices, all quads, UVs exported).
4. Controls: 36 / 16 / 1 as above.
5. Joint limits: 62 joints, explicit total mapping, tested.
6. Blink: closes without exposed eyeball or visible crumpling at the neutral and presets (numbers and images above).
7. One realistic adult in the studio with controls, rig, preview and validated export: yes.
8. Old garments stay with v2: v3 shows only `basic_top`/`basic_shorts`; the v2 garment list is not offered on v3.
9. Identity separate: v3 changes only anatomy controls; styling, wardrobe and expression stay separate DNA layers.
10. Extension point: `v3.IDENTITY_LAYERS` (empty) and the generator/template fields in the pack stamp; no Mercy
    reconstruction, no centaur or alternative templates.

## Remaining limitations (honest list)
- **Realism is limited by materials and grooming, not geometry.** No hair, eyebrows or eyelashes on v3 (MakeHuman's
  CC0 proxies were not fetched in Phase 1), flat procedural skin (no texture maps), no teeth or tongue, the mouth
  never opens. The face reads as a bald mannequin of a real person, not a finished character.
- Only the blink expression exists on v3; smile, frown, brow raise, lips part and pucker are missing.
- Garments are skin-tight offset shells: they show the body's shape (nipples, buttocks); no drape, no cloth bones,
  so no cloth secondary motion on v3. v2 garments are not fitted to v3.
- Combinations are linear: each control is exact at its ends, but cross effects (for example femininity with muscle,
  height with any other control) are not modelled; height is applied as an exact post-scale.
- Blink at the smallest eye size closes but the lid line is slightly jagged (32 folded triangles); combined controls use
  the bilinear corrective, not a fit (female preset: 15 folds, visually clean).
- Clips and poses were authored for the v2 rest pose; MakeHuman's arms rest slightly forward, so arm poses land a few
  degrees differently. Merged bones (twist, fingers' metacarpals, toes, face muscles) cannot be animated separately.
- The Python engine cannot export v3 exactly (`api/export`, CLI `export`): the studio pack is the v3 model and the
  browser export is the validated v3 path.
- MakeHuman's targets vary around one average face: v3 characters still need the Forge identity layer (see
  `experiments/makehuman_visual_proof/IDENTITY_FINDINGS.md`) to look like different people.
- Evidence images are SwiftShader screenshots (software WebGL); colours and shading match what a GPU browser shows,
  frame rate does not.

## Reproduce
```
python3 tools/v3_fetch_assets.py --offline            # verify assets (network only for missing files)
python3 -c "from forge_character_forge.v3.bake import bake; bake('examples/character_forge_aaa/studio/studio_pack_v3.bin')"
python3 -c "import json; from forge_character_forge.v3.bake import studio_meta_v3; json.dump(studio_meta_v3(), open('studio/studio_meta_v3.json', 'w'), indent=1)"
python3 -m unittest tests.test_character_forge_v3      # 17 tests, about 2.5 min (includes a full re-bake)
python3 -m forge_character_forge studio --port 8799 &
node tools/studio_v3_check.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase1
python3 tools/v3_evidence_sheets.py && python3 tools/v3_blink_report.py
```
