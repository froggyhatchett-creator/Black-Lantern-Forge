# Character Studio Step 6A

## Status

Step 6A is a functional foundation, not a production character generator and not an AAA-quality claim.
It adds a separate `forge_character_studio` package beside the frozen Step 5B weapon system. No
frozen weapon source is edited.

## What works

- A deterministic, neutral humanoid base generator with explicit seed and generator version.
- Height, torso, chest, waist, hip, arm and leg morphology controls.
- One connected, closed, outward-wound triangle surface. The exported body is not a collection of
  visibly intersecting primitive meshes.
- Canonical `forge.character-recipe` v1 JSON recipes with mesh-integrity hashes.
- Deterministic glTF 2.0 binary export under `forge.character-mesh` v1.
- An independent GLB validator that imports no generator or character model code.
- Deterministic software-rendered PNG previews using Forge's existing engine-independent renderer.
- Provider-neutral protocol boundaries for reconstruction, rigging, clothing and Motion Studio.

## Geometry approach

The prototype constructs a compact-support anatomical scalar field from overlapping volumes, then
extracts one indexed surface with marching tetrahedra. Adjacency propagation establishes consistent
winding and the existing Forge mesh validator proves that every edge has exactly two incident faces
and the signed volume is positive.

This is materially better than exporting separate spheres or capsules: the shoulders, torso, hips,
arms and legs share one continuous surface. It remains a coarse procedural base. It has no production
facial topology, hands, toes, edge-loop art direction, retopology or sculpt-quality anatomical landmarks.

## Contracts

### `forge.character-recipe` version 1

Stores generator identity/version, body-plan identity, unsigned 64-bit seed, explicit parameters and
the regenerated mesh hash. Loading regenerates the geometry and refuses a mismatched integrity hash.

### `forge.character-mesh` version 1

A single-node GLB with one triangle primitive containing `POSITION`, `NORMAL` and `TEXCOORD_0`.
Coordinates are right-handed glTF, +Y up, meters. Asset extras carry contract, generator, body-plan,
seed and coordinate metadata. This contract intentionally does not inherit weapon-only socket rules.

## Run the demonstration

```powershell
python -m forge_character_studio generate --seed 1337 --height 1.82 `
  --torso-scale 1.05 --chest-scale 1.10 --waist-scale 0.92 `
  --hip-scale 1.04 --arm-scale 1.02 --leg-scale 1.06 `
  --out output/character-demo

python -m forge_character_studio validate-glb output/character-demo/character.glb
python -m forge_character_studio load output/character-demo/character.recipe.json `
  --out output/character-reloaded
```

The command writes `character.glb`, `character.recipe.json`, and `character.preview.png`.

## Architectural boundaries

`integrations.py` defines contracts only:

- `ReconstructionProvider` accepts one or more complete or incomplete image references.
- `RiggingProvider` accepts a Character Mesh artifact without prescribing a skeleton.
- `ClothingProvider` keeps garment generation separate from body generation.
- `MotionStudioBridge` is an eventual handoff boundary. Step 6A contains no Motion Studio code.

Body plans are identified by versioned strings. `humanoid.neutral.v1` is the first implementation,
not a universal skeleton or a male/female template. Digitigrade bipeds, quadrupeds, centaurs, wings,
tails and arbitrary additional structures require new body-plan implementations and topology contracts.

## Known limitations

- The surface is a faceted medium-resolution prototype and lacks animation-friendly production loops.
- No skeleton, skin weights, blend shapes, animation, clothing, hair, eyes, teeth or soft-body data.
- UVs are provisional box projections; no texture images are baked.
- The preview is a deterministic software render, not an interactive editor viewport.
- Only the neutral humanoid body plan is implemented.
- Image reconstruction and third-party models are interfaces only.

## Proposed Step 6B

1. Introduce a body-plan graph contract describing anatomical regions, joints and optional structures.
2. Replace field-only topology with a deterministic retopology/template stage providing deformation loops.
3. Add hands, feet, facial landmarks and controllable head morphology.
4. Add skeleton and skin-weight contracts without assuming one humanoid rig.
5. Add a lightweight interactive Character Studio editor over the same headless API.
6. Add material regions and texture-atlas contracts.
7. Prototype reference-image ingestion through `ReconstructionProvider`, retaining provenance and refusal
   behavior for insufficient references.
8. Define the handoff contract with Motion Studio without importing or modifying its implementation.
