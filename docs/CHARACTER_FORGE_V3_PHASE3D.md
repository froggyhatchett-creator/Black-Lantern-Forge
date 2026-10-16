# Generator v3, Phase 3D/3E: identities in Character DNA and the real Character Studio (milestone)

Status: **working milestone; stopped for review.** In the real Character Studio (`?gen=3`) you can pick one of four
faces (Neutral, ID-A, ID-B, Mercy-inspired), edit all 36 identity sliders together with the 53 body/face controls,
save the character as Character DNA, reload it on a fresh page, animate it, and export it as an animated GLB that
keeps its identity. Generators v1/v2, their DNA and earlier v3 DNA are unchanged in meaning and appearance.

Evidence: `examples/character_forge_aaa/humanity/v3_phase3d/` (studio screenshots, three GLBs, checks, report).

## 1. Mercy-inspired lip projection and jaw contour
- **Lips:** one new operator, `lip_projection` (parameter 36): both lips move forward/back as a unit (4 mm at
  s = 1), no change to lip height or mouth shape. Mercy-inspired: `lip_projection -0.8`, `upper_lip -0.25`,
  `lower_lip -0.1` (were +0.15 / +0.1). The profile pout is gone.
- **Jaw:** the kink came from `face_length -0.6`: the chin border moved up about 7 mm while the gonion, at the edge of
  the face region, barely moved, leaving a step at the jaw angle. Fixed by retuning existing parameters:
  `face_length -0.3`, `chin_height -0.6` (shortening through the chin instead), `jaw_angle 0`.
  A dedicated `jaw_contour` operator was tried in two forms (a mandible-line width and a jaw-border lift); both kept or
  moved the kink, so it was **not** added. Parameters 1-35 are unchanged; ID-A and ID-B are unchanged.
- Evidence: `mercy_lip_jaw_before_after.png` (same renderer and cameras, Phase 3C values vs these). Health: 0 flipped
  head triangles, max area change 2.49 (3C: 3.85), eye joint to eyeball centre 0.34 mm.

So the identity layer has **36** parameters, not 35: the 35 earlier ones plus `lip_projection`.

## 2-3. Identity as a versioned DNA group; deterministic save/load
`v3/identity_dna.py`. An optional top-level DNA key; the trait schema (`forge.character-dna` v1) is untouched:

```json
"face_identity": {"schema": "forge.v3-face-identity", "version": 1,
                  "generator": {"id": "forge.character-forge", "version": 3},
                  "preset": "ID-B", "values": {"nose_length": 0.35, "...": 0.0}, "locked": ["nose_length"]}
```
- **Absent = neutral identity.** Existing DNA (v1/v2 and pre-identity v3) validates, hashes and looks exactly as
  before (`dna_hash`/`anatomy_hash` include the group only when present).
- **No silent reinterpretation:** an unknown schema or version, an unknown or misspelt key, a non-number or a value
  outside [-1, 1] is an error in Python (`validate_dna`) and in the studio (the load is refused and nothing changes).
- **The meaning of version 1 is frozen:** `v3/identity_basis_v1.json` records every parameter's geometry (sha256
  and moments); a test fails if any parameter's geometry changes. Changing an operator requires version 2.
- Identity holds face shape only; body controls (including `body.femininity`) stay in the DNA traits. The
  Mercy-inspired preset also sets `body.femininity = 1` and says so in the studio.
- Save/load is deterministic: the saved file reloads and re-saves to identical DNA bytes (Python test) and identical
  `face_identity`/traits (studio test).

## 4-6. The real v3 Studio
- **Pack** (`v3/bake.py`, 7.03 MB, was 6.79): per identity parameter its delta at s = +1 for every part (body, eyes,
  corneas, garments; s < 0 uses the negative: identity is exactly linear), the joint delta (the rig follows the
  face), and blink correctives at both ends. Grooming carries no identity data: brows, lashes and hair are anchored to
  the skin and follow it.
- **Identity tab:** four preset buttons and 36 sliders in seven groups (skull & forehead, brow & eyes, nose, cheeks,
  mouth & lips, jaw & chin, overall), each with a lock (presets keep locked values) and double-click reset to 0.
  Presets only set starting values: every slider stays editable, and undo/redo cover identity edits.
- **Save/Load:** File tab, as before; the DNA now carries `face_identity`. Exact build: the Python exact build is
  the v2 engine, so for v3 the button is hidden and the server refuses v3 or identity DNA, instead of silently
  returning v2 geometry. v3 characters export with Export GLB.

## 7-9. Verification in the studio (tools/studio_v3_identity.mjs, all through the UI)
| Check | Result |
|---|---|
| Identity tab, 36 sliders, presets Neutral / ID-A / ID-B / Mercy-inspired | pass |
| Every preset sets its values and stays editable | pass |
| Strand roots on the skin, every identity | brows 0.25 mm, lashes 0.3 mm (deliberate lifts), hair 0.002 mm |
| Lashes ride the blink, every identity | 4.6-5.3 mm mean lash travel |
| Customise ID-B (3 identity sliders, a face and a body control, a lock), **Save** (real download), fresh page, **Load** | restored to 0.05 mm: the DNA stores body traits to 4 decimals (the height slider's 1.68075 m reloads as 1.6807 m); identity values exact; re-saving gives the same DNA |
| v3 DNA without identity group | loads with the neutral identity and says so; **identical (0.0 m) to the same DNA in the pre-identity studio** (Phase 3C build served side by side) |
| Invalid identity group (version 2, misspelt key) | refused, state unchanged |
| No page errors | pass |

**Studio geometry vs an independent Python evaluation** (`v3/evaluate.py`, same model, no quantisation): max vertex
error 0.07-0.32 mm for every preset and combination at every blink weight. The difference is the pack's sparse
encoding (per-term deltas under 0.05 mm are dropped, an unchanged v3 convention) summed over the female preset's ~30
active controls.

**Identity combined with the controls** (identity preset plus slider ends together, female body preset as base):
| Combination | Head triangles flipped | Max area change | Studio vs reference |
|---|---|---|---|
| ID-A + femininity 0, head size 1.15, jaw width 1.3 | 0 | 6.37 | 0.32 mm |
| ID-B + femininity 1, eye size 1.25 (max), nose width 1.3 (max) | 0 | 2.26 | 0.29 mm |
| Mercy-inspired + head size 0.9, face length 1.2, height 1.90 m | 0 | 3.37 | 0.26 mm |

Python tests repeat this without the browser (identity adds exactly to the controls; health; blink).

**Blink per identity, from the studio's own geometry** (eyeball exposure, front view, 1 = open; folded lid triangles):
| | 0.25 | 0.5 | 0.75 | 1 (closed) |
|---|---|---|---|---|
| Neutral | 0.74 / 0 | 0.46 / 0 | 0.17 / 0 | 0.000 / 15 |
| ID-A | 0.71 / 0 | 0.41 / 8 | 0.11 / 36 | 0.001 / 77 |
| ID-B | 0.74 / 0 | 0.45 / 0 | 0.17 / 0 | 0.000 / 11 |
| Mercy-inspired | 0.74 / 0 | 0.43 / 6 | 0.16 / 9 | 0.000 / 55 |
| ID-A + male, big head, wide jaw | | 0.45 / 6 | | 0.000 / 41 |
| ID-B + big eyes, wide nose | | 0.45 / 0 | | 0.000 / 10 |
| Mercy + small head, long face, tall | | 0.43 / 6 | | 0.003 / 52 |

How the blink is corrected: each identity parameter carries the blink refitted at s = +1 and at s = -1 (minus the
neutral blink), scaled by |s|; summing those alone closes every eye but folds the lids 2-5x more than an exact refit.
So each preset also carries a **residual** (exact blink refit at the preset minus the summed correctives), faded in
by closeness to the preset (1 at the preset, 0 at a distance equal to the preset's own size). Edited presets keep
most of the benefit (an 80 % Mercy with large eyes: 34 folds vs 70 without the residual).

## 10-11. Three animated GLB exports, validated independently
`v3_identity_id_a.glb`, `v3_identity_id_b.glb`, `v3_identity_mercy_inspired.glb` (12.2 MB each, exported by the
studio's Export GLB code path, with their DNA beside them).

| Check | ID-A | ID-B | Mercy-inspired |
|---|---|---|---|
| `validate_glb` (public profile) | pass | pass | pass |
| Contents | 10 meshes, 130,124 triangles, 62 joints, 8 morph targets (blink L/R on body, brows, lashes, hair), 7 clips | same | same |
| Independent skinning check, walk frame 8 | pass (weights sum to 1 within 5e-8) | pass | pass |
| GLB rest geometry vs studio preview | 0.0001 mm | 0.0001 mm | 0.0001 mm |
| GLB vs Python reference (open / 0.5 / closed) | 0.09 / 0.19 / 0.31 mm | 0.12 / 0.13 / 0.26 mm | 0.08 / 0.14 / 0.22 mm |
| Blink from the GLB's own morph targets: exposure at 0.5 / 1 | 0.40 / 0.000 | 0.45 / 0.000 | 0.42 / 0.000 |

**Playback, not just validation:** `tools/glb_playback.mjs` (independent of the exporter and renderer) samples the
walk clip from each file, applies the blink morph and skins every mesh; `glb_playback_sheet.png` renders walk frames
0, 10 (blinking) and 20 from the exported files only (clothed, as exported). In the studio, the walk clip plays (clip
time advances) for each identity and `studio_walk_blink_sheet.png` shows it walking mid-blink.

## 12. Studio screenshots (identical cameras)
- `studio_faces_sheet.png`: Neutral, ID-A, ID-B, Mercy-inspired: front, three-quarter, profile (female body preset,
  shoulder-length hair, same materials);
- `studio_blink_sheet.png`: blink 0 / 0.5 / 1 for the three identities;
- `studio_faces_bald_sheet.png`: the same four faces with hair style bald (styling only), because the
  shoulder-length hair hides most of the face in profile;
- `studio_walk_blink_sheet.png`; `shots/ui_identity_tab.png` (the Identity tab; captured before the generator menu
  label was shortened to fit phone width).

## Visual assessment (from the studio screenshots)
- **Three distinct faces, plus the neutral:** yes, at a glance and in every view. ID-A is long and narrow with a high
  forehead, deep-set close eyes and a long, high-bridged nose; ID-B is short and broad with wide-set large eyes, a
  short upturned nose and full lips; Mercy-inspired has almond, outer-lifted eyes, a small upturned nose, high
  cheekbones and a narrow V jaw. Measured: every pair differs by 6.5-14.4 mm mean surface distance (MakeHuman's own
  variants differ by 0-2.8 mm).
- **The same materials, hair and grooming fit every face:** skin maps, eyes, brows, lashes and the shoulder-length
  hair follow each identity with roots on the skin.
- **Blink:** every face closes to a clean lid line (`studio_blink_sheet.png`); the half-closed state is coherent.
- **Animation:** walking and blinking at the same time in the studio and in the GLB playback frames.
- **Not photorealistic, and not a Mercy likeness.** The Mercy-inspired face is a stylised adult *inspired by* the
  reference's structure; without the reference's hair, liner, lashes, iris colour and expression it is not
  recognisable as that character, and nothing here claims it is.

## Remaining defects (honest)
1. **Closed-lid folds rise with combined correctives.** The eye always closes (exposure at most 0.003), but at full
   blink ID-A has 77 and Mercy-inspired 55 folded lid triangles on the female body preset (neutral 15, ID-B 11;
   an exact refit of the identity alone: ID-A 22, Mercy 40). The preset residual is fitted with body controls at
   their defaults, and the control and identity correctives are summed. In the screenshots the closed lid line
   looks clean; the folds are sub-millimetre creases, but they are real geometry defects. Fix: fit the residuals on
   the body presets as well, or refit the blink in the browser for the current character.
2. **Mid-blink lash poke-through on ID-A** (a few upper lashes show above the closing lid at 0.5), inherited from
   Phase 2 lash anchoring.
3. **Hair edges on wide or narrow faces.** The cage-bound hair follows the head, but its hard Phase 2 edge where it
   frames the cheeks is more visible on ID-B's broad face and next to ID-A's narrow temples.
4. **Mercy-inspired lips on the female preset.** The identity's lip fix holds in profile; from the front the female
   body preset's own lip controls (`face.lip_upper` and `face.lip_lower` = 1.12) add back some fullness. That is the
   body preset, not the identity, but the default pairing shows it.
5. **ID-B can read young.** Round, short face, large eyes and full cheeks on the female body read youthful at a glance.
   The body and DNA are adult (age 30); the design passed the 3B gate, but it is worth a look.
6. **Studio preview vs exact model: up to 0.32 mm.** The pack drops per-term deltas under 0.05 mm (an existing v3
   convention); summed over many active controls this reaches 0.3 mm. Invisible, but it means the studio and GLB are
   a close approximation of the Python reference, not identical to it.
7. **Identity changes overall scale slightly.** The height control is exact, so a taller head (forehead height,
   skull) shrinks the body very slightly to keep the requested height, as every v3 control does.
8. **No exact (Python) GLB build for v3.** The browser export is the v3 export path; the server's exact build stays
   v2-only and now refuses v3 rather than dropping the identity.
9. **Software rendering.** All screenshots come from Chromium with SwiftShader (about 3 minutes per hair close-up);
   performance on a GPU was not measured here.

## Tests
| Suite | Result |
|---|---|
| `tests.test_character_forge_v3_identity` (Phase 3A-3C, unchanged) | 9 pass |
| `tests.test_character_forge_v3_identity_dna` (new: versioning, frozen basis, legacy hash, save/load, invalid groups, affinity, exact build refusal, identity + controls health and blink) | 10 pass |
| `tests.test_character_forge_v3` (pack, assets, grooming) | 24 pass |
| `tests.test_character_forge_dna_physics`, `tests.test_character_forge_studio` (v1/v2 DNA and studio) | 26 pass |
| `tools/studio_v3_identity.mjs` (real studio, through the UI) | 22 checks pass, no page errors |
| `tools/studio_smoke.mjs` (v2 studio) | 23/23 (run with a 10-minute screenshot timeout: SwiftShader takes over 30 s for the v2 face close-up) |

## Reproduce
```
python3 -c "from forge_character_forge.v3.bake import bake; bake('examples/character_forge_aaa/studio/studio_pack_v3.bin')"
python3 -m unittest tests.test_character_forge_v3_identity tests.test_character_forge_v3_identity_dna
python3 -m forge_character_forge studio --port 8799 &        # and the Phase 3C build on 8798 for the legacy check
node tools/studio_v3_identity.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase3d --legacy-url http://127.0.0.1:8798/ --shots
python3 tools/v3_phase3d.py
```
