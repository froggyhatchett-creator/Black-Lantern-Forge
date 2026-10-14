# Character Forge: Step 6C Design — Fixed-Topology Rigged Humanoid

**Status:** approved design direction, spec under review
**Branch:** `feature/character-studio-step6c` (branched from `feature/character-studio-step6b`, commit `a5b3b4f`)
**Repository:** `C:\Users\mcfly\Projects\BlackLantern\Forge` (migrated with full history from the Codex working copy; `step6b-source-recovery` remote preserves the origin as a recovery reference)

## 1. Background

Black Lantern Forge is a deterministic, registry-driven procedural asset generator. Through Step 5B it ships nine rigid weapon families with zero third-party dependencies, an explicit versioned-registry architecture, and a Forge → Engine Asset Contract (v1) that is independently validated and byte-stable. That contract explicitly excludes animation, rigging, skinning and morph targets — it was never meant to cover organic, deformable characters.

Step 6A and Step 6B, built on the same baseline in an earlier session, added a separate `forge_character_studio` package: a deterministic neutral-humanoid body generator using a compact-support anatomical scalar field, extracted with marching tetrahedra, with a 21-joint landmark skeleton (explicitly documented as placement data, not a rig) and static deformation-readiness diagnostics. It is honestly self-documented as a non-production prototype: no face, no fingers/toes, no skin weights, no real rig, no blend shapes.

Independent verification in this session confirmed:
- The Character Studio test suite passes 30/30.
- The full baseline + character suite passes 649/656 (99%); the 7 failures trace to two pre-existing, narrow, Windows-only environment issues (see §7), not to geometry or determinism regressions.
- The implicit-surface approach has a structural limitation for this phase's goal: marching tetrahedra produces a **different vertex graph for every parameter/seed combination**, which rules out stable skin weights, bind poses, or corrective blend shapes — all of which require one fixed topology shared across every generated shape.

## 2. Goal of Step 6C

Deliver one genuinely skinned and poseable, fixed-topology neutral humanoid:

- a production-sourced base mesh with proper quad topology,
- deformed into Forge's parametric anatomy via a deterministic Blender-driven pipeline,
- a real bone hierarchy with normalized skin weights (not landmarks),
- a small set of corrective blend shapes at the four canonical joints Step 6B already identifies (shoulder, elbow, hip, knee),
- independently validated, deterministic glTF export.

Explicitly **out of scope** for Step 6C: production facial topology, separated fingers/toes, clothing, hair, secondary (soft-body) physics, reference-image reconstruction implementation, multiple body plans. These are architected for (contract boundaries exist) but not built.

## 3. Architecture decision: hybrid, not a replacement

Two approaches were compared:

- **A — keep extending the implicit-surface body.** Stays fully procedural with no external assets, but marching tetrahedra cannot give a fixed, weight-paintable topology without becoming a from-scratch procedural sculptor — a multi-month R&D bet with no proof it reaches anatomical credibility, since no production pipeline builds characters this way.
- **B — license a fixed-topology base mesh, deform it in Blender.** How the industry actually does this (parametric blend shapes over one authored topology). Requires sourcing and documenting a correctly licensed asset and re-proving determinism for a Blender-driven step.

**Decision: hybrid.** Keep Step 6B's deterministic parameter model and anatomical field as the shape driver. Replace only the mesh-*extraction* stage: a licensed fixed-topology base mesh is deterministically deformed to match the Forge-computed field and skeleton landmarks inside Blender, run headless and invoked by a controlled wrapper. Rig and skin weights are authored once against that fixed topology and reused for every seed/parameter combination.

This keeps Step 6B's genuinely good work (parameter model, PRNG stream usage, independent-validator discipline, provider Protocol boundaries) and replaces only the piece that structurally cannot reach the goal.

## 4. Base mesh sourcing

**Preferred candidate: Blender Studio "Human Base Meshes" v1.4.1**, an official first-party CC0 bundle from the Blender Foundation (17 meshes, closed-volume clean quad topology, UV-mapped, distributed as `.blend`, exportable to glTF/FBX/OBJ; requires Blender 4.2 LTS+). CC0 means no redistribution restriction, which matters because Forge needs to own and ship the topology as part of its own pipeline — ruling out alternatives like Mixamo, which explicitly prohibits standalone redistribution of character files.

**Before use (not yet done):** fetch the bundle, read its bundled license file directly (not just secondary sources), and record the exact archive SHA-256 and version in a provenance document, following the same pattern as `docs/PROVENANCE.md`. If the license text doesn't match CC0 exactly as currently believed, treat base-mesh sourcing as blocked and re-open this section before proceeding.

MakeHuman (CC0 per project FAQ since 2020, but historically confused licensing and lower mesh quality) and MB-Lab (archived, licensing unclear) were considered and set aside as fallbacks only if the Blender Studio bundle's license doesn't check out as expected.

## 5. Contracts

All additive. No existing contract (`forge.engine-contract` v1, `forge.character-recipe` v1/v2, `forge.character-mesh` v1/v2, `forge.character-skeleton-landmarks` v1) is modified or reinterpreted.

| Contract | Version | Status | Purpose |
|---|---|---|---|
| `forge.character-recipe` | v3 (new) | new | Adds base-mesh identity/provenance reference, pinned Blender build identity, retopology/fit parameters. This recipe is the character's **Character DNA**: the editable, versioned source-of-truth parameter set, independent of whether it was hand-dialed or produced by a future reconstruction provider. |
| `forge.character-mesh` | v3 (new) | new | Fixed vertex count/topology (from the sourced base mesh), real `JOINTS_0`/`WEIGHTS_0` skin attributes, bind pose. References the two contracts below. |
| `forge.character-skeleton-rig` | v1 (new) | new | Real bone hierarchy, bind matrices, skin weights. Distinct from and additional to `forge.character-skeleton-landmarks` v1, which is kept unchanged as placement/diagnostic data feeding the rig's authoring, not replaced by it. |
| `forge.character-blendshapes` | v1 (new) | new | Named corrective shape keys with an explicit parameter/joint-angle → weight mapping and documented ranges. |
| `forge.character-secondary-physics` | v1 (new, contract-only) | stub | Names soft-body/cloth-collision attachment regions (chest, groin, garment-collision volumes) so a future physics provider has a stable target. **No simulation is implemented in Step 6C.** |
| `forge.character-reconstruction-provider` | — (new, contract-only) | stub | Promotes the existing `ReconstructionProvider` Protocol in `integrations.py` from an informal interface to a documented first-class contract boundary that accepts and edits Character DNA. No concrete provider is implemented in Step 6C. |

## 6. Determinism and tolerances

**Refinement from the original "byte-identical everywhere" framing:** byte-identical output is the determinism target **within one pinned toolchain and environment** (exact Blender build, exact base-mesh version, exact OS) — this mirrors how Forge already pins generator/presentation versions. Across different supported environments, the requirement is **structural and semantic equivalence**, not byte equivalence: same vertex count and topology, same joint hierarchy, same weight distribution, dimensions within tolerance. This is checked with a semantic hash, the same pattern as the existing weapon contract's `semantic_sha256`, extended to cover skin weights and blend-shape ranges.

**Initial measurable tolerances** (targets to validate and tighten empirically once real data exists — not yet backed by evidence, per §9):

- **Self-intersection:** zero tolerated self-intersecting triangles in the unposed bind-pose mesh. For the four canonical posed tests, a documented near-contact allowance only in anatomically expected contact regions (e.g., underarm, inner thigh), measured as maximum penetration depth; flagged and logged, not an automatic failure, everywhere else zero tolerance.
- **Vertex integrity:** vertex count and triangle adjacency identical to the base topology for every generated character (the whole point of fixing topology); every position finite and non-NaN; no duplicate or zero-area triangles, reusing and extending Forge's existing `check_closed_oriented` validation.
- **Skin-weight normalization:** at most 4 joint influences per vertex (glTF `JOINTS_0`/`WEIGHTS_0` limit), each vertex's weights sum to 1.0 within 1e-6, no negative weights.
- **Volume change under pose:** total mesh volume within ±5% across each of the four canonical pose tests; per-joint-region local volume tracked as a refinement of Step 6B's existing stretch-estimate diagnostic, now measured on the actually-deformed mesh instead of estimated statically.

## 7. Windows compatibility findings (documented now, fixed separately)

Independently reproduced and root-caused in this session, not yet fixed:

- **CRLF checkout mangling.** `core.autocrlf=true` rewrites golden `manifest.json` fixtures from LF to CRLF on checkout. Forge's contract requires byte-exact LF-only canonical JSON, so `test_viewer_cli` refuses the mangled fixtures (`bad_manifest`). This cascades into every "re-run the Step 4 suite" check (`test_66_step_4_suite_passes` in `test_arsenal_frozen`, `test_67_step_4_suite_passes` in `test_hafted_frozen`).
- **Native path separator in a status string.** `test_50b_session_exports_an_engine_package` fails because a desktop/session status message embeds a Windows-native backslash path where the test expects a portable forward-slash form. The exported package itself is unaffected — this is a presentation-string bug, not a data bug. Cascades into every "re-run the Step 3 suite" check (`test_67_step_3_suite_passes` in `test_arsenal_frozen`, `test_68_step_3_suite_passes` in `test_hafted_frozen`, `test_64_step_3_suite_passes` in `test_viewer_independence`).

Both pre-date this initiative. Per your instruction, these are fixed in **one narrowly scoped prerequisite commit** (a `.gitattributes` forcing LF on canonical JSON/golden-fixture paths, and a one-line portable-path fix to the status-message code), executed and verified *before* any Step 6C feature work, and kept separate from it in history. This commit is sequenced as Phase 0 in §10 and is not executed until you approve the implementation plan.

## 8. Preserved future architecture (not implemented in Step 6C)

- **Image-to-character reconstruction** stays a first-class creation pathway: the `ReconstructionProvider` Protocol is promoted to a documented contract (§5) that accepts one or more image references and produces editable Character DNA (a `forge.character-recipe` v3 document) — not a conversation feature, a data contract a future provider implements against.
- **Anatomically responsive secondary physics** (breast and male genital simulation, collision volumes, garment interaction) is preserved as a named contract boundary (`forge.character-secondary-physics` v1, §5) defining attachment regions only. No simulation code, no physics runtime, ships in Step 6C.
- **Engine-agnostic, multi-genre architecture** is preserved by construction: Step 6C's export target is plain glTF 2.0 through the same independent-validator discipline as the weapon contract, with no engine-specific assumptions baked in anywhere in the pipeline.

## 9. Explicit non-claims

No claim of AAA-quality realism, production-ready animation, or shipping-quality deformation is made for Step 6C's output. Claims are limited to what §11's acceptance criteria actually demonstrate: one fixed-topology mesh, bone-weighted and posed without structural failure within the tolerances in §6, independently validated. Visual quality, animation quality, and performance claims wait for dedicated evidence (rendered comparisons, profiling, in-engine testing) in a later step.

## 10. Test strategy

- Existing Character Studio suite (30 tests) stays green and its meaning untouched.
- New suite for the Blender bridge: determinism within a pinned toolchain (§6), fail-closed refusal on a wrong/unpinned Blender version (mirrors existing generator-version pinning behavior), independent validator for the new v3/v1 contracts that imports zero bridge or generator code (mirrors `validate_glb.py`'s existing discipline).
- A real deformation test tier: pose the rig at the four canonical joints and check the tolerances in §6 against the actually-deformed mesh — replacing Step 6B's static density/stretch *estimate* with a real measurement.
- `.gitattributes` enforcing LF on every canonical-JSON/golden-fixture path (Phase 0, §7), verified by re-running the full existing suite and confirming all 656 tests pass before any Step 6C feature code is added.

## 11. Measurable acceptance criteria

Step 6C is done when:

1. One seed reproducibly generates a fixed-topology mesh + real bone-weighted rig + at least one working corrective blend shape, byte-identical across repeated runs on the same pinned toolchain, and structurally/semantically equivalent (§6) across every supported environment tested.
2. The rig poses at all four canonical joints within the tolerances in §6, verified by a script with zero shared code with the generator.
3. Exported GLB/contract validates under an independent validator with zero shared code with the writer.
4. Base-mesh provenance is documented: license text confirmed firsthand, exact version, exact SHA-256.
5. All 656 existing Step 5B/6A/6B tests still pass unmodified, after the Phase 0 Windows-compatibility commit and with no other baseline file touched.
