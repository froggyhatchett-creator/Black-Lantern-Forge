# Character Forge as an asset kit

Character Forge is built from parts that do not know they are making a person. This note lists which parts
are reusable for other asset types (weapons, armor, props, creatures, buildings), what has been shown to work,
and what each new asset type would still need. Nothing here needs Blender, Unreal or any other external editor
at runtime. Python 3 + numpy + Pillow build the assets; Node or a browser validates and views them.

## Reusable modules

| Module | What it does | Asset-agnostic? | Shown on non-character assets |
|---|---|---|---|
| `sdf.py` (`Field`, `Ellipsoid`, `RoundCone`, `RoundBox`, clip planes) | Smooth CSG solid modelling | yes | lantern, pauldron (`kit.py`) |
| `mesher.py` (`mesh_box`, surface nets) | Watertight meshing of any SDF | yes | lantern, pauldron, hairstyles |
| `lod.py` (`decimate`, `cached_decimate`) | Quadric LODs on existing vertices, so every per-vertex attribute carries over by index | yes | lantern frame LOD chain; character LOD1/LOD2 |
| `hair.py` pattern (unit-space volume + distance grid + frame placement) | Rigid-in-frame attachments that fit a parametric host without per-parameter data | pattern | hair (4 styles); helmets and masks would reuse it unchanged |
| `parts.Part` + `kit.attach` | Rigid binding of any mesh to a joint; exported and skinned like a garment | yes | lantern on `hand_r`, pauldron on `upperarm_l` (validated GLB, Node skinning check) |
| `gltf.py` / `validate.py` / `tools/glb_independent_check.mjs` | GLB writing and two independent validators | mostly (the contract metadata is character-specific) | the equipped-character GLB |
| `rig.py`, `animation.py`, `physics.py` | FK, linear blend skinning, clips, spring-damper secondary motion | skeleton-generic | — (creatures would reuse them with a new skeleton) |
| `studio_bake.py` pack + `studio/gl.js` | Piecewise-linear morph basis for live editing; WebGL2 skinned renderer | yes for any fixed-topology parametric asset | — |
| `dna.py` provenance/locks/layers | Versioned, provenance-tracked parameters | the trait model is generic | — |

## What a new asset type needs

- **Weapons and props.** An SDF recipe and a parameter set. Use `kit.mesh_field`, then `kit.lod_chain`, then
  `kit.attach` to a hand or back joint. This is demonstrated.
- **Armor.** Rigid plates work today (the pauldron). Plates that deform need weights copied from the nearest
  body vertices, the way garments get them in `clothing.py`. That path exists for garments but is not wrapped
  for armor yet.
- **Creatures.** A new skeleton definition (`skeleton.py` is humanoid-specific), anatomy SDF recipes and a
  template. The mesher, template machinery, rig, physics, DNA and studio basis are reused. Not attempted.
- **Buildings and modular sets.** The SDF, mesher and LOD modules apply as they are. There is no
  grid/socket system for modular kits, no UV unwrapping for tiling materials, and no collision-mesh export.
  Not attempted.

## Limits (honest)

- Surface nets meshes are smooth by nature. Hard-surface assets with crisp bevels need finer grids or a
  feature-preserving mesher, which is not implemented.
- No texture baking. Materials are flat PBR factors plus the procedural textures the character uses.
