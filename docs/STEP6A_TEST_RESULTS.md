# Step 6A Test Record

This file records the final verification run for the packaged Step 6A milestone.

The frozen baseline is Git commit `2b259be`, tagged `forge-v0.6.0-step5b-frozen`. Development occurs
on `feature/character-studio-step6a`.

## Results

- Character Studio suites: **20 passed** in 11.08 seconds.
- Frozen deterministic geometry and presentation selection: **158 passed** in 40.03 seconds.
- Demo Character Mesh Contract validation: **passed**, 6,366 vertices and 12,728 triangles.
- Demo recipe regeneration and mesh hash: **passed**.
- Baseline path comparison against `forge-v0.6.0-step5b-frozen`: **no baseline files changed**.

The broader 160-test frozen selection initially reported ten errors belonging to two tests that write
OBJ files inside randomized `tempfile` directories. All ten were Windows app-sandbox permission
errors. The same selection excluding those two write-dependent tests ran 158/158 successfully. This is
an execution-environment limitation, not recorded as a source failure. The complete frozen release
suite remains declared as 626 tests by Step 5B; it was not falsely reported as fully executed here.
