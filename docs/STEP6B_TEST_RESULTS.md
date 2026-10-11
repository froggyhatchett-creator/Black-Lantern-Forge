# Step 6B Verification Record

## Frozen ancestry

- Step 5B baseline: commit `2b259be`, tag `forge-v0.6.0-step5b-frozen`.
- Step 6A milestone: commit `bfe1e7d`, tag `forge-character-studio-step6a-frozen`.
- Step 6B development branch: `feature/character-studio-step6b`.

The Step 6B diff is checked against Step 6A and contains Character Studio additions/changes only. A separate
comparison against Step 5B verifies that none of its 217 tracked paths changed.

## Automated and artifact checks

- Character Studio suites: **30/30 passed in 76.97 seconds**, covering v1 compatibility, v2 determinism, morphology, contracts,
  watertightness, genus, normals/winding, skeleton completeness, joint-region density, subdivision, asymmetry,
  GLB validation and four canonical deformation diagnostics.
- Frozen Forge deterministic selection: **158/158 passed in 55.70 seconds**, using the same selection as Step 6A.
- Reference GLB: independently validated after clean release extraction.
- V1 recipe: regenerated to the exact frozen Step 6A mesh hash.
- V2 recipe: regenerated to the exact Step 6B mesh hash.

The two randomized temporary-directory OBJ tests excluded in Step 6A remain excluded because the Windows app
sandbox denies their writes. An attempted broader run also encountered the expected GUI/temp-directory sandbox
limits; it was stopped and is not reported as a product test result.
