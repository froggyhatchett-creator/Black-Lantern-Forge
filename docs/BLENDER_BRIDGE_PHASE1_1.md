# Blender Bridge Phase 1.1: animation contract and seam-safe rigging (stopped for review)

## Result: all six success criteria met on the native v3 ID-A character

| # | Criterion | Result |
|---|---|---|
| 1 | Existing animations survive unchanged | 7/7 clips with identical channel sets, key counts and key times (max difference 0.0 s); values within 0.00003°; same clip order after the post-export step; walk / run / wave playback within 0.001 mm |
| 2 | Forge metadata restored accurately | `forge_restamp.py` verifies 9 claims against the processed file before restoring; Forge's validator then passes in **public** profile; the metadata is identical to the source plus one `post_processing` record; the embedded DNA is byte-identical; all 27 joint metadata entries identical |
| 3 | A weight edit without cracks or shading change | Left-knee edit: **0 of 1,122 seams open** over every walk and run frame (Phase 1: 1.63 mm); normals, UVs, positions, triangles and vertex order **bit-identical** to the unedited round trip; only body weights change (696 vertices, max 0.073) |
| 4 | Clothing and facial morphs still work | Shorts and top penetration into the body: **identical** to the source in all 52 walk and run frames. Blink deltas within 0.00012 mm; blink playback within 0.001 mm |
| 5 | Edited character passes independent playback | `tools/glb_playback.mjs` and `tools/glb_independent_check.mjs` (public profile, original clip order) |
| 6 | Original character reproducible | Source GLB sha256 unchanged (`c257a6b1…`), git-clean. The edited file states `dna_reproduces_file: false`, so nothing claims the DNA regenerates it |

**No major architectural change was needed:**
- one Blender export contract (`RIG_EXPORT`), plus automatic fps;
- one Forge-side post-export step;
- one seam-safe weight operation;
- all inside `experiments/blender_bridge/`.

## Priority 1: animation preservation

**Automatic frame rate**
- `job_blender.py` reads the source GLB's key times *before* Blender imports it, and picks the smallest common rate
  (24/25/30/48/50/60/120) that puts every key on a whole frame. For ID-A that is 30 fps (75 distinct key times).
- It sets the scene to that rate before import.
- It **refuses** a job whose explicit `scene_fps` contradicts the keys, or whose keys fit no rate.

**Constant channels:** measured four exporter configurations, then adopted one as the default (`RIG_EXPORT`).

| Exporter options | Channels per clip | Keys | Key times | Joint metadata | File |
|---|---|---|---|---|---|
| Blender defaults (sampling on) | **186** (constant 2-key STEP on every joint) | 2 or N | equal where kept | dropped | 12.08 MB |
| No forced sampling | 6 / 10 / 14 = source | = source | **identical** | dropped | 11.88 MB |
| Sampling on, no "keep animated armature" | 6 / 10 / 14 | some compressed to 2 keys | **changed** (rejected) | dropped | 11.87 MB |
| **No forced sampling + no keep-armature + extras (adopted)** | **= source** | **= source** | **identical** | **all 27 kept** | 11.88 MB |

**Why reject sampling:** the padded clips play back correctly on their own, but they drive every joint, which would
override other layers in a layered animation system.

**Limitation:** unsampled export writes the actions' keys as they are. Clips that depend on constraints or drivers
would need baking first; Forge's clips have none.

**Clip identity**
- Blender still writes clips alphabetically. The post-export step restores the source order *by name* (the clip set
  must be identical), so consumers that index clips also work.
- Every check in this phase addresses clips by name.

**Blink morphs**
- Deltas match within 0.00012 mm, and default weights `[0, 0]` are kept on the four blink meshes.
- None of the seven clips animates the blink (the Studio drives it at runtime), so there is no blink key timing to
  preserve.

## Priority 2: Forge metadata (`forge_restamp.py`, Forge-side, stdlib + numpy)

**Checks before anything is written** (any failure means nothing is written):

| Claim | Check |
|---|---|
| Units and axes | body bounds within 1 mm of the source; face toward +Z |
| `joint_rest_orientation: identity` | every joint's local rotation is identity |
| `fixed_topology_vertices` 14,517 | body vertex count |
| `template_vertices` 13,380 | welded body count |
| Coverage and outfit | meshes present and skinned |
| `dev_only_parts` | absent |
| Joints, clips | identical joint and clip names |

**Restores**
- `asset.extras.forge` verbatim, plus a `post_processing` record: tool, processor, source and processed checksums,
  changes, job parameters, Blender version, verified claims, and **`dna_reproduces_file`**. That flag is true only if
  positions, weights and morphs still match the source.
- Per-joint metadata.
- Clip order.

Only the JSON chunk is rewritten; the binary data is copied unchanged.

**Bug found and fixed while verifying**
- Forge characters have a joint and a mesh node that share a name (`eye_l`, `eye_r`).
- My first version matched joint metadata by name and wrote the humanoid "LeftEye" tag onto the **eye mesh**.
- It now addresses joints only through the skin's joint list, and `rig_compare` compares joint and non-joint
  metadata separately and type-strictly.

**Tests** (`test_bridge.py`, now 9, all passing)
- Refuses a rotated joint, a renamed clip and unskinned shorts.
- Restores metadata, joint extras and clip order.
- Never tags a mesh node.

**Phase 1 omission, corrected:** Phase 1 never checked node extras, and they were being dropped. They are now
preserved by Blender (`export_extras`) and re-checked by the restamp.

## Priority 3: seam-safe skin-weight editing (`weights_edit_seam_safe`)

**The design (smallest that works)**
1. Copy the mesh.
2. Make a **temporary welded proxy**: one vertex per position, 14,517 → 13,380, which is exactly the template count.
3. Run Blender's tools on the proxy: Smooth `calf_l` 0.5 ×2, Normalize All, Limit Total 4, Normalize All.
4. **Write the proxy's weights back to every vertex of the unwelded copy at the same position.**
5. Delete the proxy. The original object is renamed, unchanged, and not exported.

The exported mesh's geometry, UVs, per-corner normals, topology, triangles, vertex order and material boundaries are
never touched. Only weights change. Each seam copy receives identical weights, so the posed surface cannot split.

| | Phase 1: edited as imported | Phase 1: welded first | **Phase 1.1: seam-safe** |
|---|---|---|---|
| Seams with different weights (of 1,122) | 68 | 0 | **0** |
| Widest posed seam opening | **1.63 mm** (run t = 10/30 s) | 0 | **0.000 mm over all 52 walk and run frames** |
| Vertices whose normal changed > 1° | 0 | **2,248** (max 134°) | **0** |
| Normals / UVs / triangles vs unedited round trip | identical | changed | **bit-identical** |
| Weight change | 749 vertices, max 0.073 | 801, max 0.073 | 696 exported vertices, max 0.073 |
| Posed change (walk / run) | 2.2 / 3.9 mm | 2.0 / 3.6 mm | 2.0 / 3.6 mm, left knee only |

(Counts differ slightly by definition: Blender counts per internal vertex, the comparison per exported vertex at
> 1e-6.)

**Clothing**
- For every frame of walk and run, shorts and top vertices inside the body by more than 1 mm were counted (signed
  distance to the nearest body vertex along its posed normal).
- **Identical before and after the edit:** shorts 328 vertex-frames, deepest 11.5 mm; top 930, deepest 8.3 mm.
- These source values are pre-existing and partly the metric's approximation at hems and folds. The edit changes
  none of them.

**Pre-existing Forge detail (unchanged):** one vertex per knee carries 0.0039 of the opposite leg's calf bone.

## Validation (all on the restamped files, against the source)

`rig_compare.py`, `seam_check.py` and the independent players.

| | Round trip, restamped | Seam-safe knee edit, restamped |
|---|---|---|
| Forge validator | public, 0 errors | public, 0 errors |
| Skeleton: names, hierarchy, inverse binds, rest | identical (2e-7; 0.0002 mm; 0°) | identical |
| Positions / topology | ≤ 0.00001 mm (brows 0.001), same counts | same |
| Skin weights | identical | body only: 696 vertices, max 0.073 |
| UVs, normals | as Phase 1: 2 toe-tip seam vertices, brow normals ≤ 5.2° | identical to the round trip |
| Materials, textures | identical, pixel-identical | identical |
| Animations: channels, keys, times, order | identical, 0.0 s, source order | identical |
| Morphs | ≤ 0.00012 mm; default weights kept | same |
| Playback walk / run / wave + blink / blink 0.5 / blink 1 | 0.001 / 0.001 / 0.0009 / 0.001 / 0.001 mm | 2.0 / 3.6 / 0.0009 / 0.001 / 0.001 mm (the intended knee change) |
| Metadata, DNA | restored; `dna_reproduces_file: true` | restored; **`dna_reproduces_file: false`** with the change recorded |

**Renders** (`experiments/blender_bridge/results/`): rows are source / 1.1 round trip / 1.1 seam-safe edit.

| File | Content |
|---|---|
| `p11_rest.jpg` | rest pose |
| `p11_walk.jpg` | walk at t = 0, 8, 16, 24 (/30 s) |
| `p11_run.jpg` | run at t = 0, 5, 10, 15 (/30 s) |
| `p11_blink.jpg` | blink 0 / 0.5 / 1 |
| `p11_diff.jpg` | ×10 pixel differences: the round trip shows edge flicker only; the edit shows changes only at the left knee in motion |
| `p11_seams.jpg` | the three weight-edit variants at the widest Phase 1 seam: the 1.63 mm crack (white line) in row 1 only |

## Known limitations

1. **Phase 1 round-trip residues remain**, all measured and unchanged by this phase:
   - 6 toe-tip triangles take the other UV copy;
   - brow strand normals ≤ 5.2°;
   - hair colour quantised to 8 bits.
2. **Weight edits require write-back by position.** Two genuinely distinct vertices at the same position would
   receive the same weights. There are none on this character: the weld count equals the template count. Different
   meshes with deliberately coincident but separately weighted vertices would need a smarter key.
3. **Garment weights are not edited.** Forge garments carry their own weights. An edit that moves the body under a
   garment would need the same edit transferred to the garment. This knee edit did not affect the shorts, but a
   thigh or hip edit could.
4. **Unsampled export:** constraint- or driver-based clips would need baking first.
5. **The `post_processing` record** is new metadata inside `asset.extras.forge`. Forge's validator ignores unknown
   keys today; a contract revision should define it formally.
6. **Not tested:** the Blender application launcher, Windows, other Blender versions.
7. **By design, Phase 1's 24 fps failure can no longer be reproduced.** The job now detects 30 fps, and
   `"scene_fps": 24` is refused as contradicting the keys. Phase 1's records stay in `results/jobs/phase1_*`.
   `weights_smooth_copy` is kept only as the Phase 1 counter-example.

## Next step (recommendation)

1. **Promote the three pieces into a reviewed, still-optional tool**, with the fps rule, `RIG_EXPORT`, restamp
   verification and seam-safe write-back as its contract. Gate every output through `rig_compare` + `seam_check`.
2. **Add garment-aware weight transfer** before any edit near clothing.
3. **Only then** consider rigging an external character (Rodin), which first needs topology work this pipeline does
   not do.

## Commits

See the final report message (this phase's commit on `claude/gifted-galileo-pwlplk`).
