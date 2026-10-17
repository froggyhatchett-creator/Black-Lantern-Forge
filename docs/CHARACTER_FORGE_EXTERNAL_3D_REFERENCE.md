# Project Humanity: external 3D character reference experiment (stopped for review)

**Subject.** The original Static Lullaby character (not Mercy):
- the project owner's artwork;
- a Rodin-generated `base.glb`, the authoritative model (the OBJ export was too large to supply and is not needed).

**Isolation.** Experiment: `experiments/rodin_reference/` (README there). Nothing in Forge, Character Forge, Mercy,
the presets, v1/v2 or any DNA was changed.

**Source files.** The GLB and the artwork are kept read-only and git-ignored, identified by sha256. The GLB
checksum is asserted on every run.

**Short answer.** The Rodin model is a good **3D reference** and a good source of **rigid props**. It is a poor
source of **facial identity**, and unusable as an **animatable character** or as **garments** without a large
pipeline. Forge should use it to remove ambiguity from images, not as geometry to import into characters.

## 1. Technical inspection (`results/inspection.json`)

| Item | Finding |
|---|---|
| File | 22.2 MB, glTF 2.0 written by Blender's glTF exporter 4.3.47, Forge validator: 0 errors, 0 warnings, no Forge profile |
| Objects | **1 node, 1 mesh, 1 primitive.** Body, hair, clothing, boots, gloves, belts, pouches, vials and the board are **one fused surface** |
| Size | 504,919 vertices (249,818 after welding UV seams), **exactly 500,000 triangles** (a generator face budget) |
| Attributes | POSITION, NORMAL, TEXCOORD_0. No colours, no tangents |
| Material, textures | One plain material: grey 0.5, metallic 0.05, roughness 0.4, double-sided. **No images or textures**, although UVs exist (0-1 atlas). Appearance (gold eyes, dark-to-teal hair, brass) is absent from this export |
| Rig and motion | **No skin, no skeleton, no morph targets, no animations** |
| Topology | **Watertight**: 0 boundary edges, 0 non-manifold edges, 0 inconsistently wound edges, 0 degenerate triangles, normals agree with winding |
| Shape of the shell | 1 connected component; Euler characteristic -182, so **genus 92**: tunnels wherever parts touch or loop (arms and hands fused to the board, D-rings, straps, belt loops) |
| Resolution | Near-uniform remesh: edge length median 5.7 mm (1st percentile 1.5, 99th 16.6). Facial features are a handful of edges wide |
| Scale, orientation | Y up, +Z forward, feet on y = 0, 1.898 m tall including hair and platform boots. Scale is **arbitrary** (see section 3) |

**Not checked:** self-intersections inside the fused shell (expected where parts merge).

## 2. Visual comparison with the artwork

Renders were made with Forge's own renderer. Sheets in `results/`:
- `artwork_vs_rodin.jpg`
- `artwork_vs_rodin_head.jpg`
- `rodin_four_views.jpg` (front, three-quarter, profile, rear)
- `lineup_true_scale.jpg`

| Transferred well | Lost or wrong |
|---|---|
| Overall pose and silhouette, weight shift, crossed stance | **Face expression**: eyes sculpted **shut**; mouth closed and neutral (artwork: open gold eyes, grin, tongue out, tongue piercing) |
| Cropped jacket with shoulder plate and sleeve vials, bra top with belt, harness straps | Forehead glyph simplified to a diamond relief, baked into the skull |
| Belts, thigh pouches, D-rings, baggy cargo pants, fingerless gloves | Glowing choker became a high collar |
| Platform buckle boots with gear details | Fringe strands invented across the face (they hide the face in profile) |
| The hover board: two turbine housings, compass emblem, vials, frame | **All colour**: hair gradient, gold eyes, skin tone, brass, glow |
| Long wavy hair mass to the waist | Rear (hair, back pouch) is **invented**: the artwork shows no back |

**Likeness verdict, from the renders:**
- Costume and props: clearly recognisable.
- Face: not recognisable as the artwork's character. The expression and eyes, which carry her identity, are gone.

## 3. Geometry and anatomical quality

| | |
|---|---|
| Scale | Exported at 1.90 m. Landmark-fitted head scale is 1.114 x a native v3 head. Normalising the head gives a ~1.70 m total, ~1.6 m body without hair and platform soles. Absolute size is a choice, not a measurement |
| Head | Pitched ~13.5° down (measured by the fit). Stylised anime face: wide-set eyes, small nose, V-chin. Eye to chin ~13 cm at export scale (v3: ~12 cm) |
| Body | Curvy and stylised like the artwork (large bust, narrow waist). Only the midriff, upper chest, face and fingers are skin. **Everything else is clothing surface: there is no body underneath.** Hips, legs, arms and shoulders cannot be measured anatomically |
| Hands | Formed, but fused to the board and the thigh. No separable fingers |
| Pose | Posed (walking stance, arms bent around the board), not a bind pose. Joint positions are not recoverable reliably |
| Animation readiness | **None.** Fused, posed, unrigged, no interior. Loading it proves nothing about animation; it stays unrigged here |

## 4. Forge compatibility

| Capability | Status | Evidence |
|---|---|---|
| Read the GLB, preserve geometry, normals, UVs, material | **Works** | `forge_character_forge.validate.read_glb` / `validate_glb`; inspection and renders use the file unchanged |
| Display it, alone or alongside a native v3 character | **Works (offline renderer)** | `views.py`: Forge's CPU rasterizer, Rodin beside v3 ID-A at true scale. 500k triangles render in 2-5 s per view |
| Independent playback tool (`tools/glb_playback.mjs`) | **Needs an adapter** | Fails: it assumes Forge's own contract (a skin). A static-mesh path is a few lines |
| Character Studio | **New development** | The Studio exports GLB but has no import path or reference-model slot. It would need a static GLB reader (it has only an exporter) and a non-character draw path; 500k triangles likely needs decimation for the web |
| Editable scene asset with transforms | **Not available** | Forge has no scene or asset editor. The Myth evaluation covers a viewer, not editing |
| Body-proportion reference | **Partial; manual landmarks needed** | Usable only where skin is visible. Clothing hides the rest |
| Facial identity reference | **Works mechanically; low value here** | See the probe below |
| Reusable hair, clothing, equipment | **Props yes (with work); garments and hair no** | See section 5 |
| Retopology or fitting onto Forge topology | **New development** | Not attempted. Fused, posed, genus-92 shell |
| Preserve DNA, skinning, animations | **Yes, by construction** | Nothing touched them. A reference must never enter DNA silently; it needs its own provenance record |

### Face fitting probe (`facefit_probe.py`; probe only, nothing saved)

The probe aligns a native v3 face (female body preset, identity 0, lids excluded) to the Rodin head. It then solves
the 36 linear identity parameters by least squares, alternating with rigid ICP for 4 rounds.

**Without landmarks** (`free`):
- Converges to a **false** alignment: the v3 face matched a sub-region of the larger Rodin face (scale 0.90).
- Its error looks *better* (3.0 -> 2.7 mm), and the render shows it is wrong.
- Lesson: unanchored geometric fitting on this mesh is unsafe, and the error number alone hides it.

**With three landmarks** read off the mesh (nasal bridge, nose tip, chin):
- A sane alignment: scale 1.114, pitch 13.5°.
- The identity fit reduces the trimmed error only from 3.69 to 3.16 mm (-14 %). The fitted face barely changes.
- The fit **shrinks the eyes** (eye_size -0.20, eye_depth -0.26) because Rodin sculpted them shut. That is the
  opposite of the artwork.
- Fitting reproduces the generator's errors faithfully. The remaining difference is stylisation outside the basis
  plus the ~6 mm resolution.

## 5. Reusable vs unusable components

| Component | Verdict | Why / what it would take |
|---|---|---|
| **Hover board** | **Reusable as a rigid prop** | Rigid, mostly self-contained. Cut at the hand contacts, cap the holes, decimate, re-texture, attach to a hand joint. A few days, semi-manual |
| Boots | Possibly, as rigid foot accessories | Fused to the pants. Separation at the shaft plus ankle-deformation limits |
| Small hardware (pouches, vials, buckles, plate) | Possibly, as a kit-bash library | Small rigid pieces, but fused; each needs cutting and capping |
| Jacket, top, pants | **Unusable as garments** | Posed, fused to the body, no inner surface or thickness, no separation from skin. Needs retopology, re-posing and cloth fitting to v3: a garment-authoring pipeline (weeks) |
| Hair | **Unusable as Forge hair**; useful as a target | A solid sculpt fused to head and back. Forge hair is strand cards. Its volume could guide a new card hairstyle |
| Body and face | Reference only | No body under clothes. Face lost its expression and eyes |
| Textures | Not present | A textured Rodin export would be needed to evaluate appearance transfer |

## 6. Recommended strategy

**C-lite: a reference model plus harvested rigid props, on a native v3 character.** Not A, and not full B.

- **A (direct import as a scene asset).** A posed, unrigged statue. Forge has no scene editor, and the result could
  never be edited, animated or kept consistent with DNA. Fine for a turntable; a dead end for Forge's goal.
- **B (reference fitting).** Sound in principle, because v3 is linear in identity and body controls. The probe shows
  it works only with landmarks, and that the clothed, stylised, eyes-closed mesh carries little anatomical
  information beyond what the artwork already gives. Body fitting would also need pose estimation. Worth it later
  for **proportions**, not identity.
- **C (hybrid).** Its practical part today: keep the anatomy native (MakeHuman v3, DNA, rig and animations
  untouched), harvest **rigid** props (the board), and use the external mesh as a **measurable 3D reference**:
  multi-view, scale, silhouette, the rear the artwork never shows. The face, garments and hair stay native and are
  styled to the reference.

The real gain over images alone is **consistency across views**: profile, rear and volume are no longer guessed.
That gain is about the costume and props, not the face.

## 7. Effort and risks

| Work | Estimate |
|---|---|
| Studio reference overlay (static GLB reader, ghost/side-by-side display, manual scale and offset, standard views) | 2-3 days |
| Landmark sidecar (manual clicks, provenance) + landmark-anchored proportion fit of the native character | 1-2 weeks, outcome uncertain |
| Prop harvest (board): cut, cap, decimate, UV/texture, hand attachment, export | 3-5 days, semi-manual |
| Garment or hair conversion | weeks each; not recommended now |

**Risks**
- **Hallucinated geometry**: the rear and the hidden parts are invented, and the eyes are wrong.
- **Arbitrary scale.**
- **Stylised anatomy** beyond realistic MakeHuman ranges (bust, waist).
- **Fused and posed geometry**, and heavy meshes (500k triangles) for the web.
- **Missing textures.**
- **Provenance and terms** of generator outputs.
- **Pressure to make Forge depend on an external generator.**

**Mitigations**
- Treat the reference as read-only input with a checksum and an owner.
- Never let it into DNA silently.
- Keep Forge working without it.

## 8. Smallest practical next milestone

**"Reference model overlay" in the Character Studio:**
- Load a static GLB as a read-only reference: not exported, not in DNA, with a provenance sidecar holding the
  checksum and source.
- Show it beside or ghosted over the native character, with manual scale and offset, at front, three-quarter,
  profile and rear.
- Optionally click and store a few landmarks.

It serves all three strategies, needs no retopology or rig transfer, and immediately lets a native v3 Static
Lullaby character be shaped and styled against a consistent 3D target.

**Needed from the project owner:**
- whether a *textured* Rodin export exists (for appearance);
- whether the board should be the first harvested prop.

## Reproduce

```
cp <your base.glb> experiments/rodin_reference/source/base.glb
cp <artwork> experiments/rodin_reference/source/artwork.webp
python3 experiments/rodin_reference/inspect_glb.py
python3 experiments/rodin_reference/views.py
python3 experiments/rodin_reference/facefit_probe.py landmarks
python3 experiments/rodin_reference/facefit_probe.py free
```
