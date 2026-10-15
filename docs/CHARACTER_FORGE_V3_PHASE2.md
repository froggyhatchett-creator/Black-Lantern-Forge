# Generator v3, Phase 2: visual quality (milestone report)

Status: **milestone reached; stopped for visual review.** The v3 adult in the real Character Studio now has skin
maps, textured eyes, eyebrows, eyelashes and one strand hairstyle. Generators v1/v2 are unchanged. This is a clear
step from "bald mannequin" toward a believable person; it is **not photorealistic** (see the end of this report).

Open it: `python3 -m forge_character_forge studio`, then `?gen=3` (or Generator: v3). Evidence:
`examples/character_forge_aaa/humanity/v3_phase2/`.

## What was added, and where each asset comes from
| Layer | Source and licence | How it works |
|---|---|---|
| Skin albedo (2048 px, RGBA) | **Forge-generated** (`v3/textures.py`, deterministic, seed 3) | Baked in hm08's own UV layout: a multiplier on the skin-tone control (so tone still works) with regional colour (lips, cheeks, nose, ears, eyelids, under-eye), low-frequency mottling, sparse moles and nose/cheek freckles. Regions come from MakeHuman's CC0 targets (lip, nose, cheek, ear vertex sets) and the lid-bone weights, not hand-placed. Alpha = scalp mask: the scalp under the hair takes the hair colour. |
| Skin normal map (1024 px) | **Forge-generated** | Tangent-space (glTF convention) from a height field: soft undulation, coarse pores on nose and cheeks, vertical lip lines, smooth eyelids. Pores finer than a texel stay procedural in the shader. |
| Eye texture (1024 px) | **MakeHuman CC0** `eyes/materials/brown_eye.png` (official repo; sha256 in `v3/assets/PROVENANCE.json`) | Photographic iris and sclera detail. The iris keeps its fibres but takes the chosen eye colour (recoloured by luminance in the shader and, for the GLB, in the exported texture). The iris/sclera split is found from the texture itself (edge at about 0.40 rad from the optical axis). The cornea keeps its clear cap and sharp key and fill catchlights. |
| Eyebrows | **Forge-generated** (`v3/grooming.py`) | 1,040 individual hairs, root on the brow ridge (projected onto the skin), growth upward at the head of the brow and along/downward toward the tail, lying at a shallow angle. |
| Eyelashes | **Forge-generated** | 262 lashes rooted on the lid margin (found where the lid skin crosses the cornea sphere: hm08's skin is closed behind the lids), upper lashes curling up, short lower lashes. |
| Hair: shoulder-length layers, side part | **Forge-generated** | 3,392 strand ribbons (several hairs each, alpha from a Forge strand profile), rooted on the scalp (a hairline from forehead over temples and ears to the nape; mouth and throat interior excluded), combed from the part, collision with head, neck and shoulders, gathered in 240 locks with a gentle wave, the face kept clear. Not a solid shell. |

**Why not MakeHuman's own skins, brows, lashes and hair:** those live in the separate `makehuman-assets` repository
(Git LFS). From this environment it is unreachable (no GitHub access to it; github.com pages are blocked by the proxy),
so nothing from it was used or claimed. Only the eye texture and its material file are in the main repository and
were downloaded (0.6 MB).

## Attachment: stable under controls, blink and motion
Every strand is anchored to a body triangle (barycentric root). The studio re-evaluates all strands from the live body
after every edit (after the exact-height scaling), so they follow every control, the blink and skinning without any
per-control morph data:
- brows and lashes use the root triangle's frame (they turn with the skin: lashes close with the lid);
- scalp hair is cage-bound: every strand point follows a weighted blend of nearby skin vertices' displacements, with
  roots bound exactly to their triangle, so the hair widens with the head, jaw, neck and shoulders and does not swing
  (a first version translated strands rigidly; the face then cut through the hair at the largest head and on the male
  preset, which the variation test exposed).

The GLB export carries the lashes' own blink morph targets (computed from the body's blink, including the per-control
blink correctives), so the exported character blinks with its lashes.

## Renderer changes (studio)
Texture support (sRGB colour maps, mipmaps, anisotropic filtering); a normal map with a derivative-based tangent frame
(no stored tangents); textured eyes; a strand shader (Kajiya-Kay highlight along the hair, alpha-to-coverage for soft,
order-independent strand edges); scalp tint under hair. v2 paths are unchanged (no textures, so the new branches are
off): the v2 studio smoke test still passes 23/23.

## Evidence (all from the real studio, identical cameras before and after)
"Before" is the Phase 1 build (commit 4932d59) served side by side; "after" is this build.
- `sheet_before_after_face.png`: front, three-quarter, profile (female preset, neutral studio lighting).
- `sheet_before_after_body.png`, `sheet_blink.png` (open, half, closed: lashes fold down with the lid).
- `sheet_variations.png`: masculine build, largest eyes, widest jaw, largest head, widest nose, highest body fat,
  tallest; male preset.
- `sheet_motion.png`: Contrapposto pose (head turned) and walk frame 8.
- `after_checks.json`: textures loaded; lash displacement during blink; strand roots on the skin after extreme edits.
- `v3_phase2_export.glb` + `glb_validation.json` + `glb_independent_check.json`.

## Results
| Check | Result |
|---|---|
| v3 studio boots, all five maps loaded (skin albedo and normal, eye, two strand profiles), no page errors | pass |
| Lashes ride the blink (mean lash displacement, open to closed) | 5.3 mm |
| Strand roots on the skin after extreme edits (largest eyes and head) | brows 0.25 mm, lashes 0.3 mm (both deliberate lifts off the skin), hair 0.002 mm |
| Blink side effects on other grooming | 450 of 1,040 brow hairs move by up to 7.8 mm (MakeHuman's upper-lid weights reach the lower brow); 117 of 47,488 hair points by at most 0.3 mm |
| Browser GLB (female preset) | 12.2 MB; `validate_glb` passes with the public profile: 10 meshes, 130,124 triangles, 62 joints, 8 morph targets, 7 animations, 5 embedded PNG images, no errors or warnings. The independent Node loader poses walk frame 8 and skins every vertex of every mesh. |
| Unit tests (`tests/test_character_forge_v3.py`) | 24 pass: anchors rebuild their rest positions exactly, every strand starts on its anchor, hair cage weights sum to 1, the face and eyes stay clear of hair, every lash grows from the lid, maps are deterministic, the eye texture matches its recorded sha256, pack contents |
| v1/v2 | no Python change to v1/v2; v2 studio smoke 23/23 |

Visual result (`sheet_before_after_face.png`): the bald mannequin is now a person with skin colour variation, readable
lips, detailed irises with corneal highlights, eyebrows, eyelashes and a shoulder-length layered hairstyle; blinking
closes over the eye with the lashes folding down (`sheet_blink.png`); all of it holds under the control variations and
in pose and animation.

## Remaining deficiencies (honest)
**Not photorealistic.** The renders support "visibly improved, believable at a glance in a stylised-realistic way",
not photorealism.

1. **Facial geometry is now the main limit on the face.** With surface, eyes and grooming in place, the MakeHuman
   average face shows its simplicity: soft, youthful, low-detail forms (shallow eyelid crease, little
   nasolabial/philtrum/chin definition, a flat cheek-jaw transition). The normal map cannot create these; they need
   sculpted, Forge-owned detail shapes (the identity layer) or higher-detail targets.
2. **Surface detail is procedural, not scanned.** The skin reads clean and slightly plastic up close: no
   photographic pore and colour detail, no subsurface scattering beyond the wrap term, no specular or roughness map.
   Scanned CC0 skin (for example MakeHuman's own skins, unreachable here) would raise this considerably.
3. **Hair is good at a distance, synthetic up close.** Visible ribbon banding in profile, tips that turn grey and
   translucent (alpha-to-coverage against the background), a hard edge where the hair frames the cheeks, a sparse
   hairline at the part. There is no hair physics on v3 (the v2 sway applies to v2 styles only), and the hair does
   not collide with the body in poses: it is skinned to the head and deforms with the body shape, not with the motion.
4. **Brows and lashes.** Brows read slightly grey and pencil-like at mid distance; mid-blink, a few upper lashes
   dip into the closing lid; the blink moves the lower brow hairs (up to 7.8 mm), inherited from MakeHuman's lid
   weights.
5. **Eyes.** The sclera is a little grey-blue under the studio's cool fill light. The iris colour control recolours
   the MakeHuman texture by luminance, so very light colours (ice blue) keep a brown texture structure. The GLB
   carries a recoloured copy of the eye texture.
6. **Performance (software rendering).** Under SwiftShader, close-ups take 2-3 minutes per frame with the hair; on a
   GPU this is a normal load (about 95,000 hair vertices). The GLB grew from 1.7 to 12.2 MB (textures and hair).
7. **No expression system** (as instructed); only the blink exists on v3.

**Which is the limiting factor now?** For the face up close: **facial geometry** first (the forms are simple and
generic), then surface detail. For the full figure at normal viewing distance: the hair and the skin shading. The
next most valuable step is the Forge identity layer (coherent, sculpted facial forms on this topology), then scanned
CC0 skin.

## Reproduce
```
python3 tools/v3_fetch_assets.py --offline     # verify assets (adds the eye texture if missing, with provenance)
python3 -c "from forge_character_forge.v3.bake import bake; bake('examples/character_forge_aaa/studio/studio_pack_v3.bin')"
python3 -m unittest tests.test_character_forge_v3          # 24 tests, about 5 min
python3 -m forge_character_forge studio --port 8799 &
node tools/studio_v3_visual.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase2/shots after --full
# "before": the same script against a checkout of commit 4932d59 served on another port, prefix "before"
python3 tools/v3_phase2_sheets.py
```
