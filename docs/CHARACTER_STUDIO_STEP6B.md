# Character Studio Step 6B: Organic Anatomy

## Status

Step 6B is a deterministic deformation-ready procedural prototype. It is visibly smoother and more
anatomically articulated than Step 6A, but it is not a production sculpt, final retopology, or AAA claim.
The frozen weapon system and all 217 Step 5B baseline paths remain unchanged.

## Architecture and geometry

`humanoid.neutral.v2` builds a single compact-support anatomical field. Separate authored regions describe
the cranium, jaw, neck, clavicle shelf, rib cage, abdomen, pelvic bowl, upper/lower limbs, hands, ankles and
feet. Joint support volumes are deliberately smaller than muscle segments so elbows, knees, shoulders and
hips remain continuous without the large spherical joints visible in the first prototype.

Marching tetrahedra produces one indexed watertight surface. A deterministic tangential relaxation pass is
then projected back onto the anatomy field. This is constrained anatomical refinement, not indiscriminate
smoothing: field projection retains the requested morphology and anatomical silhouette. Adjacency propagation
enforces consistent winding, and the frozen Forge mesh validator checks every edge and outward volume.

The `subdivision` control selects three deterministic sampling densities. Joint-centered support bands are
measured by `diagnostics.py`; these provide dense deformation regions for future skin weighting. They are not
claimed to be artist-authored quad edge loops. A dedicated quad-retopology stage remains future work.

## Morphology

Step 6A controls remain supported. V2 adds head, neck, hand, foot, shoulder and pelvis controls; independent
left/right arm and leg controls; a symmetry blend; configurable subdivision; and shoulder/hip corrective
strength. Controls describe geometry rather than sex, gender, species, or named characters. Other body plans
remain separate versioned implementations.

## Neutral skeleton landmark contract

`forge.character-skeleton-landmarks` version 1 contains a parented landmark hierarchy, not an animation rig.
It includes root, lower spine, chest spine, neck, head, bilateral shoulders, elbows, wrists, hands, hips,
knees, ankles and feet. Positions and joint support radii are saved in the GLB asset metadata and emitted as
`character.skeleton.json`. This contract is the handoff point for a future rigging provider and Motion Studio;
Step 6B does not implement or modify Motion Studio.

## Contracts and compatibility

- `forge.character-recipe` v2 records every v2 parameter and the regenerated mesh hash.
- `forge.character-mesh` v2 embeds the landmark contract while retaining one indexed GLB triangle primitive.
- The exact Step 6A v1 generator is retained in `legacy_v1.py`; original v1 recipes regenerate to their stored
  mesh hash. The independent GLB validator accepts both v1 and v2.

## Validation

`diagnostics.py` reports Euler characteristic, triangle-area range, joint-region density, radial support bands,
and estimated support/stretch for arm raising, elbow bending, knee bending and hip rotation. These are static
deformation-readiness diagnostics, not proof of animation quality and not an animation engine.

## Run

```powershell
python -m forge_character_studio generate --seed 2606 --height 1.82 `
  --chest-scale 1.06 --waist-scale 0.94 --shoulder-width-scale 1.04 `
  --subdivision 1 --out output/step6b-character
python -m forge_character_studio validate-glb output/step6b-character/character.glb
```

The command writes the GLB, canonical recipe, skeleton and diagnostic JSON, plus front, side, back and
three-quarter PNG previews.

## Remaining anatomical limitations

- Facial landmarks are silhouette-level; there are no eyes, eyelids, lips, ears, teeth or production face loops.
- Hands are mitten-like volumes without fingers; feet have no separated toes or plantar detail.
- Muscle groups are broad procedural masses, without tendon, scapular or detailed clavicle deformation.
- The extracted surface is triangular and field-derived. It has dense joint support bands, not final quad loops.
- No skin weights, bind matrices, corrective blend shapes, rig, animation, clothing, hair or soft-body data.
- Self-intersection is structurally avoided for the generated closed iso-surface, but extreme future modular body
  combinations will require a dedicated broad-phase intersection validator.
- UVs and neutral material remain provisional; the preview is a deterministic renderer, not an editor viewport.

## Proposed Step 6C

1. Deterministic region-aware quad retopology with authored face, shoulder, elbow, hip and knee loop targets.
2. Fingers, toes, ears, orbital cavities and controllable facial planes.
3. Skin-weight contract and a neutral bind-pose export, kept separate from animation execution.
4. Corrective blend-shape contract driven by measured joint poses.
5. Material-region and non-overlapping UV atlas generation.
6. Reference-image ingestion experiments through the existing provider boundary with explicit provenance.
7. Additional body-plan graphs for digitigrade and anthropomorphic prototypes.
