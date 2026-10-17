# Project Humanity: Mercy face reference refinement (stopped for review)

The new Mercy image was used as a **face identity and styling reference only**. It was not used for body proportions,
and nothing was reconstructed from it. The result is a new identity preset, **MERCY-REFINED** ("Mercy-inspired
(refined)"), built from the existing 36-parameter identity basis. The Phase 3C preset **MERCY-INSPIRED is unchanged**:
same values, same controls, same blink, and a byte-identical pack geometry blob. That keeps the comparison reviewable.
The reference image itself is not committed (third-party art).

Evidence: `examples/character_forge_aaa/humanity/v3_mercy_refined/`.
- Committed: JPEG sheets, `mercy_refined_report.json`, `studio_checks.json`, DNA files, and a sha256 manifest of the GLBs.
- Git-ignored: GLBs, dumps and per-shot PNGs.

## What changed

**Preset.** `identity.STYLIZED["MERCY-REFINED"]` takes the Phase 3C values and overrides 23 of them.
- Controls (`STYLIZED_CONTROLS`): `body.femininity = 1` and `face.eye_size = 1.25`.
- `face.eye_size` is the Studio slider's maximum. It is only safe because eyelid fit 2 (Phase 4A.1) keeps the lids on
  the eyeball.

| Priority | Target in the image | Change (Phase 3C -> refined) |
|---|---|---|
| 1 eyes | very large, almond, lifted outer corner | eye_size 0.8 -> 1.0, eye-size control 1.06 -> 1.25, eye_aperture 0.6 -> 0.8, eye_length 0.7 -> 0.8, eye_tilt 0.35 -> 0.45, brow_ridge -0.9 -> -0.7; eye_outer_corner 1.0 -> 0.8 (see the regression below) |
| 2 lower face | shorter, softer | face_length -0.3 -> -0.7, chin_height -0.6 -> -0.8, jaw_taper 0.8 -> 0.4, jaw_width -0.7 -> -0.45 |
| 3 mouth | compact, soft full lips, not pushed forward | mouth_width -0.3 -> -0.75, upper_lip -0.25 -> 0.1, lower_lip -0.1 -> 0.15, lip_projection -0.8 -> -1.0, mouth_height 0.35 -> 0.25 |
| 4 jaw/chin | rounder chin, no jaw-angle kink | chin_width -0.7 -> -0.4, chin_projection 0.15 -> 0.7 |
| 5 silhouette | compact, cute but adult | cheek_fullness -0.35 -> 0.4, cheekbone_height 0.6 -> 0.35, midface_projection 0.15 -> 0; nose_length -0.6 -> -0.8, nose_bridge -0.3 -> -0.5, nose_tip_angle 0.45 -> 0.6 |

**No new operators.** The basis covered all five priorities, so nothing was added.

**Blink residual is deliberately not baked for the new preset.**
- Preset blink residuals blend by distance. The two Mercy presets are close: at MERCY-INSPIRED, a refined residual
  would carry weight 0.54.
- Adding one would therefore silently change the blink of the existing Mercy character and of anything near it.
- `identity_dna.RESIDUAL_PRESETS` freezes the residual set at ID-A, ID-B and MERCY-INSPIRED. The refined face gets
  0.51 of the Phase 3C residual plus the summed correctives.
- Cost: the lid is 1.32 mm from its exact refit at worst, against 1.06 mm with a residual of its own. It still closes
  fully (table below).

**Pack.**
- Rebaked; the only content change is the added preset entry (+205 bytes).
- Geometry blob: byte-identical to the previous pack.

## Verification

Everything below is on the female body preset plus each preset's own controls, as the Studio applies them.

| | Phase 3C | Refined |
|---|---|---|
| Flipped head triangles, eyelid fit 1 / fit 2 | 0 / **2** | 0 / 0 |
| Degenerate triangles (< 2°), 1st-percentile min angle | 0, 6.6° | 0, 6.67° |
| Open eye exposure (px, same camera) | 1488 | 1798 (+21 %) |
| Eye to chin (mm) | 91.2 | 87.8 (-3.4) |
| Lips ahead of chin in profile (mm) | 11.6 | 8.8 (-2.8) |
| Blink closed: exposure, lid in eye | 0.0, 0.0 mm | 0.0, 0.0 mm |
| Folded lid triangles closed (all visible), worst frame | 10, 5 | 12, 6 |
| Half blink exposure (l, r) | 0.44, 0.44 | 0.45, 0.45 |
| Lash strands penetrating (worst weight); upright closed | 2; 91 | 3; 95 |
| Studio vs Python reference (blink 0 / 0.35 / 1) | 0.12 / 0.12 / 0.13 mm | 0.12 / 0.12 / 0.14 mm |
| Browser GLB export | validates, public, 10 meshes, 62 joints, 8 morphs, 7 clips | same |

**Tests**
- `tests/test_character_forge_v3_mercy_refined.py` (new) checks:
  - the old values (hash) are unchanged;
  - no residual is baked and none leaks into the existing presets;
  - 0 flips in both fits;
  - the blink closes.
- That file, plus the identity, identity DNA, blink and eyelid-fit suites: 42 tests, OK.
- `tools/studio_v3_identity.mjs` now expects five presets.

**Review sheets**

| File | What it shows | Rendered with |
|---|---|---|
| `bald_current_vs_refined.jpg` | front / three-quarter / profile, aligned on the eyes | CPU |
| `eyes_blink_current_vs_refined.jpg` | open / half-lidded 0.35 / closed | CPU |
| `studio_bald.jpg` | front / three-quarter / profile | real Studio |
| `studio_eyes.jpg` | open / 0.35 / closed, with lashes and brows | real Studio |
| `studio_hair.jpg` | shoulder hair, silver with a purple highlight (existing styling) | real Studio |

## Did likeness improve?

**Yes, modestly, and in the right direction.**
- The eyes read clearly larger and more almond.
- The lower face is shorter and rounder, the mouth smaller and less pushed forward, the chin softer and more present.
- The head reads more compact and younger-looking, while staying an adult skull on an adult body.
- Half-lidded (blink 0.35) gives the confident, heavy-lidded look without a new operator.

**It is not a close match, and geometry is no longer the main gap.** Side by side with the image, most of what makes
it "her" is surface and styling, not shape.

## What still blocks a closer match

Ordered by likeness gained per unit of work:

1. **Makeup and lashes (materials and grooming).**
   - Heavy black liner, dark dense upper lashes and purple shadow are most of the eye's identity in the image.
   - The skin has no makeup layer.
   - Lash and brow colour follow the hair colour. Silver hair therefore gives white lashes and brows (see
     `studio_hair.jpg`), which works directly against the look.
   - Needed: separate brow/lash colour, and a lash density/length styling option.
2. **Iris colour.** The image is violet. The eye material has fixed presets; a custom iris colour is a small
   appearance option.
3. **Hairstyle.**
   - The image has a short, tousled, layered bob with a purple front panel.
   - v3 has only bald and shoulder-length. The Studio already labels a "Layered bob" for v2, but v3 has no bob mesh.
   - The highlight control blends per strand, so purple does not read at all on silver. It cannot place a front streak.
   - Needed: a v3 short-bob style plus a placed (zone) colour streak.
4. **Accessories**: gauges, piercings (including the tongue stud), studded choker. These are an accessory system,
   out of scope.
5. **Fine lip forms**: a sharper cupid's bow and philtrum. The linear basis scales lips; it does not sculpt their
   outline. This is the one place a small new operator would help, but the gain is small next to items 1-3.
6. **Stylisation ceiling.**
   - The image's eyes are about 1.5-2x a realistic aperture, with a chibi head-to-face ratio.
   - Going further would break realistic adult anatomy. The refined preset stops there on purpose.
   - Eye control 1.25 is the slider limit.

## Is the new image a better long-term benchmark than REF-001?

**Better for styling, worse for geometry.** Use both, for different jobs.

- **Use the new image** as the benchmark for the *look*: eye shape, makeup, hair, colour blocking, accessories. It
  pins down the character's styling far better than REF-001 and gives Phases 4B+ concrete targets: brow/lash colour,
  iris colour, bob, streak, accessories.
- **Do not use it for measurements.** It is a stylised illustration with a strong head turn and tilt, painted
  proportions and occluding hair. Nothing in it can be measured reliably.
- **Keep REF-001 (or any near-frontal, less-stylised reference)** for the geometric identity checks.

## Regression found in passing (not fixed here)

Under eyelid fit 2, the **Phase 3C Mercy preset has 2 flipped triangles** in the open pose, one at each outer canthus.
- The cause is `eye_outer_corner = 1.0` combined with the fit-2 lid correction.
- Fit 1 has none. The Phase 4A.1 report does not list it.
- The refined preset avoids it with 0.8.
- Changing the old preset would change a historical character, so it is left as is.
- Recommended for Phase 4A.2: limit the fit-2 correction at the outer canthus, or cap `eye_outer_corner` × fit 2.

## Reproduce

```
python3 -c "from forge_character_forge.v3.bake import bake; bake('examples/character_forge_aaa/studio/studio_pack_v3.bin')"
python3 -m forge_character_forge studio --port 8799
node tools/studio_v3_mercy_refined.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_mercy_refined
python3 tools/v3_mercy_refined.py examples/character_forge_aaa/humanity/v3_mercy_refined examples/character_forge_aaa/humanity/v3_mercy_refined
python3 -m unittest tests.test_character_forge_v3_mercy_refined
```
