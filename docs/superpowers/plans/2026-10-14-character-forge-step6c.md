# Character Forge Step 6C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Black Lantern Forge one genuinely skinned, poseable, fixed-topology neutral humanoid — built by deterministically deforming a licensed production-quality base mesh inside Blender, driven by Step 6B's existing parametric anatomy, with real bone-weighted rigging, a small corrective-blend-shape set, and independent glTF validation.

**Architecture:** Hybrid. Keep Step 6B's `CharacterParameters`, PRNG stream usage and anatomical field as the deterministic shape driver; replace only the implicit-surface mesh-extraction stage with a Blender-driven deformation of a fixed-topology CC0 base mesh. New, additive contracts (`forge.character-recipe` v3, `forge.character-mesh` v3, `forge.character-skeleton-rig` v1, `forge.character-blendshapes` v1, `forge.character-secondary-physics` v1 stub) sit alongside the untouched v1/v2 contracts.

**Tech Stack:** Python 3.10+ stdlib only for all Forge-side code (matches `pyproject.toml`'s `dependencies = []`); Blender (pinned exact build, installed and invoked only in Phase 4) as an external controlled tool via `--background --python`, never a Python import dependency.

**Spec:** `docs/superpowers/specs/2026-10-14-character-forge-step6c-design.md`

## Global Constraints

- Zero third-party Python dependencies; Blender is an external invoked tool, never imported.
- No existing contract is modified: `forge.engine-contract` v1, `forge.character-recipe` v1/v2, `forge.character-mesh` v1/v2, `forge.character-skeleton-landmarks` v1 stay byte-identical. New contracts are additive only.
- All 656 existing tests must pass, unmodified in meaning, after Phase 0 and through every later task.
- Determinism target: byte-identical output within one pinned Blender build + OS; structural/semantic equivalence required across supported environments (spec §6).
- Skin weights: at most 4 joint influences per vertex, weights sum to 1.0 within 1e-6, no negative weights (spec §6).
- Volume change under each of the 4 canonical poses: within ±5%, an initial target to refine with real data (spec §6).
- Self-intersection: zero tolerated in the bind-pose mesh; posed near-contact allowance only in documented anatomical contact regions (spec §6).
- No AAA-quality claims; claims are limited to what the acceptance criteria in the spec (§11) actually demonstrate (spec §9).
- Base mesh must be CC0-licensed, with license text confirmed firsthand and archive SHA-256 recorded before use (spec §4). Step 6C code refuses any other license id.
- A Blender version mismatch against the pinned build must fail closed, never silently proceed (spec §5).

## Review Focus

- A `forge.character-recipe` v1 or v2 file loaded through code touched by this plan must still load exactly as before — v3 is additive, not a replacement path (spec §5). Covered by: Task 3.
- Skin weights that don't sum to 1.0, go negative, or exceed 4 influences must be refused by validation, never silently renormalized (spec §6). Covered by: Task 4.
- A Blender executable at the wrong version must be refused with a clear error, not accepted as "close enough" (spec §5). Covered by: Task 8.
- Self-intersection appearing outside the documented near-contact allowlist during any of the 4 canonical poses must fail the deformation test, not just get logged (spec §6). Covered by: Task 15.
- A base-mesh license that isn't exactly `CC0-1.0` must block provenance recording rather than be accepted provisionally (spec §4). Covered by: Task 2.

---

## Phase 0 — Windows compatibility prerequisite (independent of everything else; no Blender needed)

### Task 1: Fix the two Windows-only test failures found during the Step 6C read-only assessment

**Files:**
- Create: `.gitattributes`
- Modify: `forge_desktop/session.py:386-390`
- Test: no new test files — the existing suite already regresses on both bugs

**Interfaces:**
- Consumes: nothing new
- Produces: nothing new; this task only restores the existing 656-test suite to green on Windows

- [ ] **Step 1: Confirm the two failures still reproduce**

Run: `python -m unittest discover -s tests -p "test_viewer_cli.py"` and `python -m unittest discover -s tests -p "test_engine_integration.py"` from the repo root with `PYTHONPATH` including the repo root and `tests/`.
Expected: `test_viewer_cli` fails two tests with `bad_manifest`; `test_engine_integration` fails `test_50b_session_exports_an_engine_package` with a backslash-vs-forward-slash string mismatch.

- [ ] **Step 2: Add `.gitattributes`**

```gitattributes
* text=auto eol=lf
*.json text eol=lf
*.glb binary
*.png binary
```

- [ ] **Step 3: Renormalize the working tree and verify the golden fixtures are LF again**

Run: `git add --renormalize .` then inspect `examples/curved_sword_seed1337_v1.forgepkg/manifest.json` for the absence of `\r\n` (e.g. `od -c | grep -m1 '\\r'` finds nothing).

- [ ] **Step 4: Fix the path separator in `forge_desktop/session.py`**

In the `shown()` closure (currently at lines 386-390), change the return statement from `str(p.relative_to(base))` to `p.relative_to(base).as_posix()`. The `except ValueError: return p.name` branch is unchanged (no separator present).

- [ ] **Step 5: Run the full suite and verify 656/656 pass**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 656 tests ... OK`

- [ ] **Step 6: Commit**

```bash
git add .gitattributes forge_desktop/session.py
git commit -m "fix: Windows-only CRLF golden-fixture and path-separator test failures"
```

---

## Phase 1 — Character DNA schema foundations (pure Python, no Blender)

### Task 2: Base-mesh provenance record

**Files:**
- Create: `forge_character_studio/provenance.py`
- Test: `tests/test_character_provenance.py`

**Interfaces:**
- Consumes: nothing
- Produces: `BaseMeshProvenance` dataclass, `save_provenance(record, path) -> Path`, `load_provenance(path) -> BaseMeshProvenance`, `ALLOWED_LICENSE_IDS` (initially `("CC0-1.0",)`)

- [ ] **Step 1: Write the failing tests**

```python
def test_provenance_round_trips():
    record = BaseMeshProvenance(
        source_name="Blender Studio Human Base Meshes",
        source_url="https://www.blender.org/download/demo/",
        version="1.4.1",
        license_id="CC0-1.0",
        archive_sha256="0" * 64,
        retrieved_date="2026-10-14",
    )
    path = save_provenance(record, tmp_path / "provenance.json")
    assert load_provenance(path) == record

def test_provenance_rejects_non_cc0_license():
    with pytest.raises(ValueError):
        BaseMeshProvenance(source_name="x", source_url="https://example.com", version="1",
                            license_id="CC-BY-4.0", archive_sha256="0" * 64, retrieved_date="2026-10-14")

def test_provenance_rejects_malformed_sha256():
    with pytest.raises(ValueError):
        BaseMeshProvenance(source_name="x", source_url="https://example.com", version="1",
                            license_id="CC0-1.0", archive_sha256="not-a-hash", retrieved_date="2026-10-14")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_provenance -v` (or `pytest tests/test_character_provenance.py -v`)
Expected: FAIL with `ModuleNotFoundError` / `NameError`

- [ ] **Step 3: Implement `BaseMeshProvenance`, `save_provenance`, `load_provenance` in `forge_character_studio/provenance.py`**

`__post_init__` validates: `license_id in ALLOWED_LICENSE_IDS`; `archive_sha256` is exactly 64 lowercase hex characters; `source_name`, `source_url`, `version`, `retrieved_date` are non-empty strings. Use `canonical_json` from `forge.hashing` for `save_provenance`, matching the pattern already used in `forge_character_studio/recipe.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_character_provenance -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/provenance.py tests/test_character_provenance.py
git commit -m "feat: add base-mesh provenance record (CC0-only, Step 6C)"
```

### Task 3: `forge.character-recipe` v3 — additive pipeline metadata

**Files:**
- Modify: `forge_character_studio/recipe.py` (add new functions; `recipe_data`, `save_recipe`, `load_recipe` stay byte-for-byte unchanged)
- Test: `tests/test_character_recipe_v3.py`

**Interfaces:**
- Consumes: `CharacterAsset`, `CharacterParameters` from `forge_character_studio/model.py` (existing); `BaseMeshProvenance` from Task 2
- Produces: `RECIPE_CONTRACT_VERSION_V3 = 3`; `recipe_data_v3(asset: CharacterAsset, base_mesh: BaseMeshProvenance, blender_build: str) -> dict`; `save_recipe_v3(asset, base_mesh, blender_build, path) -> Path`; `load_recipe_v3(path) -> tuple[CharacterAsset, BaseMeshProvenance, str]`

- [ ] **Step 1: Write the failing tests**

```python
def test_recipe_v3_round_trips(demo_asset, demo_provenance):
    path = save_recipe_v3(demo_asset, demo_provenance, "4.2.3", tmp_path / "r.json")
    asset, provenance, blender_build = load_recipe_v3(path)
    assert asset == demo_asset
    assert provenance == demo_provenance
    assert blender_build == "4.2.3"

def test_recipe_v2_still_loads_unchanged(existing_v2_fixture_path):
    # existing load_recipe() path must be untouched by this task
    asset = load_recipe(existing_v2_fixture_path)
    assert asset.generator_version == 2

def test_recipe_v3_rejects_missing_pipeline_section(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"contract": {"id": "forge.character-recipe", "version": 3}}')
    with pytest.raises(ValueError):
        load_recipe_v3(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_recipe_v3 -v`
Expected: FAIL (functions don't exist yet)

- [ ] **Step 3: Implement the v3 functions in `forge_character_studio/recipe.py`**

`recipe_data_v3` reuses `recipe_data(asset)` for the existing sections and adds a `"pipeline"` section: `{"base_mesh": {"source_name", "version", "archive_sha256"}, "blender_build": blender_build}`. Its `contract.version` is `RECIPE_CONTRACT_VERSION_V3` (decoupled from `generator_version`, unlike v1/v2 — document this decoupling in a one-line comment since it's a deliberate change from the existing `"version": asset.generator_version` pattern). `load_recipe_v3` parses the same way `load_recipe` does but additionally requires and validates the `pipeline` section, reconstructing a `BaseMeshProvenance` from it (without the fields `save_provenance` writes that don't apply here, i.e. no `retrieved_date`/`source_url`/`license_id` round-trip is needed inside the recipe — only `source_name`, `version`, `archive_sha256`; keep the recipe's `pipeline.base_mesh` schema minimal and distinct from the full `BaseMeshProvenance` record).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_character_recipe_v3 -v`
Expected: all pass

- [ ] **Step 5: Run the full existing suite to confirm no v1/v2 regression**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 656 tests ... OK`

- [ ] **Step 6: Commit**

```bash
git add forge_character_studio/recipe.py tests/test_character_recipe_v3.py
git commit -m "feat: add forge.character-recipe v3 pipeline metadata (additive)"
```

---

## Phase 2 — New contract data models (pure Python, no Blender)

### Task 4: `forge.character-skeleton-rig` v1

**Files:**
- Create: `forge_character_studio/skeleton_rig.py`
- Test: `tests/test_character_skeleton_rig.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `BoneJoint` (`name: str`, `parent: str | None`, `bind_matrix: tuple[float, ...]` — 16 floats, row-major 4x4), `VertexWeights` (`joints: tuple[int, int, int, int]`, `weights: tuple[float, float, float, float]`), `SkeletonRig` (`contract_id="forge.character-skeleton-rig"`, `contract_version=1`, `bones: tuple[BoneJoint, ...]`, `vertex_weights: tuple[VertexWeights, ...]`)

- [ ] **Step 1: Write the failing tests**

```python
def test_valid_rig_constructs():
    root = BoneJoint("root", None, IDENTITY_4X4)
    child = BoneJoint("spine", "root", IDENTITY_4X4)
    weights = VertexWeights((0, 1, 0, 0), (0.7, 0.3, 0.0, 0.0))
    rig = SkeletonRig("forge.character-skeleton-rig", 1, (root, child), (weights,))
    assert rig.bones[1].parent == "root"

def test_rejects_weights_not_summing_to_one():
    with pytest.raises(ValueError):
        VertexWeights((0, 1, 0, 0), (0.5, 0.2, 0.0, 0.0))

def test_rejects_negative_weight():
    with pytest.raises(ValueError):
        VertexWeights((0, 1, 0, 0), (1.2, -0.2, 0.0, 0.0))

def test_rejects_unknown_parent_reference():
    with pytest.raises(ValueError):
        SkeletonRig("forge.character-skeleton-rig", 1,
                    (BoneJoint("a", "nonexistent", IDENTITY_4X4),), ())

def test_rejects_cyclic_parent_chain():
    with pytest.raises(ValueError):
        SkeletonRig("forge.character-skeleton-rig", 1,
                    (BoneJoint("a", "b", IDENTITY_4X4), BoneJoint("b", "a", IDENTITY_4X4)), ())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_skeleton_rig -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `BoneJoint`, `VertexWeights`, `SkeletonRig` in `forge_character_studio/skeleton_rig.py`**

`VertexWeights.__post_init__` validates `sum(weights)` is within 1e-6 of 1.0 and every weight is `>= 0.0`. `SkeletonRig.__post_init__` validates every `parent` name (when not `None`) exists among `bones`, and that walking each bone's parent chain terminates (no cycle) — use the standard visited-set walk.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_character_skeleton_rig -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/skeleton_rig.py tests/test_character_skeleton_rig.py
git commit -m "feat: add forge.character-skeleton-rig v1 contract"
```

### Task 5: `forge.character-blendshapes` v1

**Files:**
- Create: `forge_character_studio/blendshapes.py`
- Test: `tests/test_character_blendshapes.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `BlendShape` (`name: str`, `driven_by: str`, `min_angle_degrees: float`, `max_angle_degrees: float`, `vertex_deltas: tuple[tuple[float, float, float], ...]`), `build_blend_shape_set(base_vertex_count: int, shapes: tuple[BlendShape, ...]) -> BlendShapeSet`, `BlendShapeSet` (`contract_id="forge.character-blendshapes"`, `contract_version=1`, `shapes: tuple[BlendShape, ...]`)

- [ ] **Step 1: Write the failing tests**

```python
def test_valid_set_builds():
    shape = BlendShape("left_elbow_bend", "left_elbow", 0.0, 95.0, ((0.0, 0.0, 0.0),) * 10)
    bss = build_blend_shape_set(10, (shape,))
    assert bss.shapes[0].name == "left_elbow_bend"

def test_rejects_mismatched_vertex_delta_count():
    shape = BlendShape("x", "left_elbow", 0.0, 95.0, ((0.0, 0.0, 0.0),) * 5)
    with pytest.raises(ValueError):
        build_blend_shape_set(10, (shape,))

def test_rejects_min_not_less_than_max():
    with pytest.raises(ValueError):
        BlendShape("x", "left_elbow", 95.0, 0.0, ((0.0, 0.0, 0.0),))

def test_rejects_non_finite_delta():
    with pytest.raises(ValueError):
        BlendShape("x", "left_elbow", 0.0, 95.0, ((float("nan"), 0.0, 0.0),))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_blendshapes -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `BlendShape`, `BlendShapeSet`, `build_blend_shape_set` in `forge_character_studio/blendshapes.py`**

`BlendShape.__post_init__` validates `driven_by` is non-empty, `min_angle_degrees < max_angle_degrees`, and every delta component is finite (`math.isfinite`). `build_blend_shape_set` validates every shape's `len(vertex_deltas) == base_vertex_count` before constructing the frozen `BlendShapeSet`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_character_blendshapes -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/blendshapes.py tests/test_character_blendshapes.py
git commit -m "feat: add forge.character-blendshapes v1 contract"
```

### Task 6: `forge.character-secondary-physics` v1 (contract stub, no simulation)

**Files:**
- Create: `forge_character_studio/secondary_physics.py`
- Test: `tests/test_character_secondary_physics_contract.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `PhysicsRegion` (`name: str`, `attachment_vertex_indices: tuple[int, ...]`, `region_kind: str`), `REGION_KINDS = ("soft_body", "collision_volume")`, `SecondaryPhysicsContract` (`contract_id="forge.character-secondary-physics"`, `contract_version=1`, `regions: tuple[PhysicsRegion, ...]`)

- [ ] **Step 1: Write the failing tests**

```python
def test_valid_contract_builds():
    region = PhysicsRegion("chest_soft", (10, 11, 12), "soft_body")
    contract = SecondaryPhysicsContract("forge.character-secondary-physics", 1, (region,))
    assert contract.regions[0].region_kind == "soft_body"

def test_rejects_unknown_region_kind():
    with pytest.raises(ValueError):
        PhysicsRegion("x", (1,), "rigid_body")

def test_rejects_duplicate_region_names():
    region = PhysicsRegion("chest_soft", (1,), "soft_body")
    with pytest.raises(ValueError):
        SecondaryPhysicsContract("forge.character-secondary-physics", 1, (region, region))

def test_rejects_empty_attachment_indices():
    with pytest.raises(ValueError):
        PhysicsRegion("x", (), "soft_body")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_secondary_physics_contract -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `PhysicsRegion`, `SecondaryPhysicsContract` in `forge_character_studio/secondary_physics.py`**

This module defines schema only — no simulation code, no physics runtime, matching spec §5/§8. `PhysicsRegion.__post_init__` validates `region_kind in REGION_KINDS` and `attachment_vertex_indices` non-empty. `SecondaryPhysicsContract.__post_init__` validates region names are unique.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_character_secondary_physics_contract -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/secondary_physics.py tests/test_character_secondary_physics_contract.py
git commit -m "feat: add forge.character-secondary-physics v1 contract stub (no simulation)"
```

### Task 7: Promote the reconstruction-provider boundary to a first-class contract

**Files:**
- Modify: `forge_character_studio/integrations.py`
- Test: `tests/test_character_reconstruction_contract.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `CharacterDNA` (`contract_id="forge.character-recipe"`, `contract_version=3`, `recipe_path: Path`); `ReconstructionProvider.reconstruct(...) -> CharacterDNA` (changed return type, was `Path`)

- [ ] **Step 1: Write the failing tests**

```python
def test_character_dna_wraps_a_recipe_path(tmp_path):
    dna = CharacterDNA("forge.character-recipe", 3, tmp_path / "r.json")
    assert dna.contract_version == 3

def test_reconstruction_provider_protocol_still_a_protocol_boundary():
    # architecture guard: no concrete implementation ships in this module
    import inspect
    assert inspect.isabstract(ReconstructionProvider) or hasattr(ReconstructionProvider, "_is_protocol")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_reconstruction_contract -v`
Expected: FAIL (`CharacterDNA` doesn't exist)

- [ ] **Step 3: Add `CharacterDNA` and update `ReconstructionProvider.reconstruct`'s return type in `forge_character_studio/integrations.py`**

`CharacterDNA` is a frozen dataclass, no validation beyond type (keep it a thin reference wrapper around a `forge.character-recipe` v3 file path — the recipe itself, loaded via `load_recipe_v3` from Task 3, is the actual Character DNA content). Update the `ReconstructionProvider` Protocol's `reconstruct` signature to return `CharacterDNA` instead of `Path`.

- [ ] **Step 4: Run tests to verify they pass, then run the existing architecture test**

Run: `python -m unittest tests.test_character_reconstruction_contract -v`
Expected: pass
Run: `python -m unittest tests.test_character_architecture -v`
Expected: `test_future_integrations_are_protocol_boundaries` still passes (confirms the signature change didn't break the existing architecture guard)

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/integrations.py tests/test_character_reconstruction_contract.py
git commit -m "feat: promote ReconstructionProvider to return Character DNA (forge.character-recipe v3)"
```

---

## Phase 3 — Blender bridge infrastructure (pure Python; unit-testable with a fake executable, no real Blender required)

### Task 8: Blender discovery, version pinning, fail-closed refusal

**Files:**
- Create: `forge_character_studio/blender_bridge/__init__.py`, `forge_character_studio/blender_bridge/version_pin.py`
- Test: `tests/test_blender_bridge_version_pin.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `PINNED_BLENDER_VERSION: str` (placeholder value until Phase 4 fixes the real installed version), `BlenderVersionError(ValueError)`, `check_blender_version(executable: Path) -> str`, `require_pinned_blender(executable: Path) -> Path`

- [ ] **Step 1: Write the failing tests**

```python
def test_require_pinned_blender_accepts_matching_version(fake_blender_script):
    # fake_blender_script is a fixture writing a tiny script that prints
    # f"Blender {PINNED_BLENDER_VERSION}" when called with --version
    path = require_pinned_blender(fake_blender_script(PINNED_BLENDER_VERSION))
    assert path == fake_blender_script(PINNED_BLENDER_VERSION)

def test_require_pinned_blender_refuses_mismatched_version(fake_blender_script):
    with pytest.raises(BlenderVersionError):
        require_pinned_blender(fake_blender_script("3.6.0"))

def test_require_pinned_blender_refuses_missing_executable(tmp_path):
    with pytest.raises(BlenderVersionError):
        require_pinned_blender(tmp_path / "does-not-exist")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_blender_bridge_version_pin -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `check_blender_version`, `require_pinned_blender` in `forge_character_studio/blender_bridge/version_pin.py`**

`check_blender_version` runs `[str(executable), "--version"]` via `subprocess.run(capture_output=True, text=True, timeout=30)` and parses the version token from stdout. `require_pinned_blender` calls it and raises `BlenderVersionError` on a missing executable, a nonzero return code, or a parsed version that doesn't exactly equal `PINNED_BLENDER_VERSION`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_blender_bridge_version_pin -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/blender_bridge/ tests/test_blender_bridge_version_pin.py
git commit -m "feat: add fail-closed Blender version pinning for the character bridge"
```

### Task 9: Deterministic Blender deformation script generator

**Files:**
- Create: `forge_character_studio/blender_bridge/script_gen.py`
- Test: `tests/test_blender_bridge_script_gen.py`

**Interfaces:**
- Consumes: `CharacterAsset` from `forge_character_studio/model.py`
- Produces: `generate_deform_script(asset: CharacterAsset, base_mesh_path: Path, output_glb_path: Path) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_script_is_deterministic_for_same_inputs(demo_asset, tmp_path):
    a = generate_deform_script(demo_asset, tmp_path / "base.blend", tmp_path / "out.glb")
    b = generate_deform_script(demo_asset, tmp_path / "base.blend", tmp_path / "out.glb")
    assert a == b

def test_script_differs_for_different_seed(demo_asset, tmp_path):
    other = replace(demo_asset, seed=demo_asset.seed + 1)
    a = generate_deform_script(demo_asset, tmp_path / "base.blend", tmp_path / "out.glb")
    b = generate_deform_script(other, tmp_path / "base.blend", tmp_path / "out.glb")
    assert a != b

def test_script_embeds_the_paths_as_posix(demo_asset, tmp_path):
    script = generate_deform_script(demo_asset, tmp_path / "base.blend", tmp_path / "out.glb")
    assert "\\\\" not in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_blender_bridge_script_gen -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `generate_deform_script` in `forge_character_studio/blender_bridge/script_gen.py`**

Pure string templating: embed `asset.seed`, `asset.parameters.to_dict()`, and the two paths (rendered with `.as_posix()` to keep the generated script portable and the output deterministic across platforms) into a Python source string that a pinned Blender will later execute in `--background --python` mode. This task only generates text — it does not invoke Blender and has no Blender dependency.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_blender_bridge_script_gen -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/blender_bridge/script_gen.py tests/test_blender_bridge_script_gen.py
git commit -m "feat: add deterministic Blender deformation script generator"
```

---

## Phase 4 — Blender-dependent execution

**⚠ Every task in this phase requires a real, pinned Blender installation and the downloaded, license-verified base mesh. Per your instruction, none of these tasks start until you separately approve installing Blender and downloading the base mesh — this plan only sequences and specifies them.**

Exact `bpy` API call bodies cannot be written or verified without a live Blender to run against, so these tasks are specified at the interface/contract level; the implementer fills in the Blender-side script body against the actual pinned version once it's installed, and that body becomes part of `script_gen.py`'s template from Task 9.

### Task 10: Base-mesh deformation invocation

**Files:**
- Create: `forge_character_studio/blender_bridge/deform.py`
- Test: `tests/test_blender_bridge_deform.py` (integration-level; requires Blender + base mesh present)

**Interfaces:**
- Consumes: `require_pinned_blender` (Task 8), `generate_deform_script` (Task 9)
- Produces: `deform_base_mesh(asset: CharacterAsset, base_mesh_path: Path, blender_executable: Path, output_glb_path: Path) -> Path` — the GLB this writes is Blender's **raw** export: valid glTF 2.0 with skinning data, but with none of Forge's `forge.character-mesh` v3 identity metadata yet. Task 13 adds that in a separate, pure-Python, Blender-independent step.

- [ ] **Step 1: Write the integration test** — generate a character, run `deform_base_mesh`, assert the output GLB exists, is valid glTF 2.0, and has the same vertex count as the base mesh (fixed topology, per spec §6).
- [ ] **Step 2: Run it against the real pinned Blender and base mesh; confirm it fails without Blender installed** (documents the prerequisite rather than silently skipping).
- [ ] **Step 3: Implement `deform_base_mesh`**: call `require_pinned_blender`, write the Task 9 script to a temp `.py` file, run `[blender_executable, "--background", "--python", script_path]` via `subprocess.run`, check return code 0, return `output_glb_path`.
- [ ] **Step 4: Run the integration test and confirm it passes.**
- [ ] **Step 5: Commit.**

### Task 11: Rig and skin-weight extraction

**Files:**
- Create: `forge_character_studio/blender_bridge/rig_extract.py`
- Test: `tests/test_blender_bridge_rig_extract.py` (requires Task 10's output)

**Interfaces:**
- Consumes: output of `deform_base_mesh` (Task 10); `SkeletonRig`, `BoneJoint`, `VertexWeights` (Task 4)
- Produces: `extract_rig(deformed_glb_path: Path) -> SkeletonRig`

- [ ] **Step 1: Write the integration test** — run against a Task 10 output, assert the extracted `SkeletonRig` validates (reuses Task 4's `__post_init__` checks) and every base-mesh vertex has a `VertexWeights` entry.
- [ ] **Step 2: Implement `extract_rig`** reading the armature/weight data Blender wrote into the GLB's skinning accessors.
- [ ] **Step 3: Run the test and confirm it passes.**
- [ ] **Step 4: Commit.**

### Task 12: Corrective blend-shape baking

**Files:**
- Create: `forge_character_studio/blender_bridge/blendshape_bake.py`
- Test: `tests/test_blender_bridge_blendshape_bake.py` (requires Tasks 10-11 output)

**Interfaces:**
- Consumes: output of `deform_base_mesh` (Task 10), `SkeletonRig` (Task 11); `BlendShape`, `build_blend_shape_set` (Task 5)
- Produces: `bake_corrective_shapes(base_mesh_path: Path, rig: SkeletonRig, joint_names: tuple[str, ...], blender_executable: Path) -> BlendShapeSet`

- [ ] **Step 1: Write the integration test** — bake shapes for the four canonical joints (`left_shoulder`, `left_elbow`, `left_hip`, `left_knee`, matching Step 6B's existing diagnostic set), assert the result validates under Task 5's checks.
- [ ] **Step 2: Implement `bake_corrective_shapes`**, posing the rig at each joint's documented angle range and capturing the resulting vertex deltas.
- [ ] **Step 3: Run the test and confirm it passes.**
- [ ] **Step 4: Commit.**

---

## Phase 5 — Validation and acceptance

### Task 13: Stamp Forge v3 identity metadata onto the deformed GLB (pure Python, no Blender needed to test)

**Files:**
- Create: `forge_character_studio/mesh_v3.py`
- Test: `tests/test_character_mesh_v3.py`

**Interfaces:**
- Consumes: `CharacterAsset` (existing, `model.py`); `SkeletonRig` (Task 4); `BlendShapeSet` (Task 5); `BaseMeshProvenance` (Task 2); a raw GLB's bytes (synthetic in this task's own tests; Task 10's real output once Phase 4 runs)
- Produces: `MESH_V3_CONTRACT_ID = "forge.character-mesh"`, `MESH_V3_CONTRACT_VERSION = 3`, `stamp_character_v3_identity(raw_glb_bytes: bytes, asset: CharacterAsset, rig: SkeletonRig, shapes: BlendShapeSet, base_mesh: BaseMeshProvenance) -> bytes`

- [ ] **Step 1: Write the failing tests**

```python
def test_stamped_glb_carries_v3_identity_extras(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance):
    stamped = stamp_character_v3_identity(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance)
    doc = parse_gltf_json_chunk(stamped)  # local test helper, mirrors validate_glb.py's own chunk parsing
    extras = doc["asset"]["extras"]
    assert extras["contract"] == {"id": "forge.character-mesh", "version": 3}
    assert extras["base_mesh"]["source_name"] == demo_provenance.source_name

def test_stamping_does_not_alter_vertex_or_index_data(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance):
    stamped = stamp_character_v3_identity(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance)
    assert extract_accessor_bytes(stamped, "POSITION") == extract_accessor_bytes(synthetic_raw_glb, "POSITION")

def test_stamping_is_deterministic(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance):
    a = stamp_character_v3_identity(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance)
    b = stamp_character_v3_identity(synthetic_raw_glb, demo_asset, demo_rig, demo_shapes, demo_provenance)
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_character_mesh_v3 -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `stamp_character_v3_identity` in `forge_character_studio/mesh_v3.py`**

Parse the raw GLB's JSON chunk (reuse `forge.engine.glb`'s existing chunk-level helpers where they fit, matching the pattern `forge_character_studio/glb.py` already uses for `pack_glb`), rewrite only `asset.extras` to add `{"contract": {"id": MESH_V3_CONTRACT_ID, "version": MESH_V3_CONTRACT_VERSION}, "generator": {"id": GENERATOR_ID, "version": asset.generator_version}, "seed": str(asset.seed), "body_plan_id": asset.body_plan_id, "base_mesh": {"source_name": base_mesh.source_name, "version": base_mesh.version, "archive_sha256": base_mesh.archive_sha256}, "skeleton_rig": {"contract": {"id": rig.contract_id, "version": rig.contract_version}}, "blend_shapes": {"contract": {"id": shapes.contract_id, "version": shapes.contract_version}, "names": [s.name for s in shapes.shapes]}}`, re-pack the GLB with the BIN chunk byte-for-byte untouched, and repad the JSON chunk per the existing contract's 4-byte alignment rule.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_character_mesh_v3 -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add forge_character_studio/mesh_v3.py tests/test_character_mesh_v3.py
git commit -m "feat: add forge.character-mesh v3 identity stamping (pure Python)"
```

### Task 14: Independent validator for the v3 contracts

**Files:**
- Create: `forge_character_studio/validate_character_v3.py`
- Test: `tests/test_character_v3_validator.py`

**Interfaces:**
- Consumes: nothing from the bridge or generator modules, and nothing from `mesh_v3.py`'s stamping code either (architecture requirement, mirrors `validate_glb.py` importing none of the writer) — only raw bytes/data plus the Task 4/5 contract dataclasses for schema shape reference in tests. It validates Task 13's *output* (stamped GLB bytes) without ever importing Task 13's module.
- Produces: `CharacterV3Error(ValueError)`, `validate_character_v3_bytes(glb_data: bytes, rig: SkeletonRig, shapes: BlendShapeSet) -> dict`

- [ ] **Step 1: Write the failing tests** — a Task-13-stamped synthetic GLB + matching rig + shapes passes, including an assertion that `asset.extras.contract == {"id": "forge.character-mesh", "version": 3}`; corrupt GLB header refused; a rig with an out-of-range joint index in `VertexWeights` refused; a `BlendShapeSet` whose `driven_by` name isn't among the rig's bone names refused.
- [ ] **Step 2: Run tests to verify they fail.**
- [ ] **Step 3: Implement `validate_character_v3_bytes`**, structured like `validate_glb.py`'s check order: container → accessors → skinning → blend-shape cross-references. Add a static check (grep-based test is acceptable) confirming this module has no `import` of `blender_bridge`, `generate`, or `implicit`.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit.**

### Task 15: Real deformation/tolerance test tier (spec §6)

**Files:**
- Create: `tests/test_character_deformation_tolerances.py`
- Test: (this task *is* the test)

**Interfaces:**
- Consumes: output of Tasks 10-12 (a deformed, rigged, blend-shaped character)
- Produces: nothing new — a test-only module

- [ ] **Step 1: Write the test** posing the rig at all 4 canonical joints (left_shoulder, left_elbow, left_hip, left_knee) and asserting, against the actually-deformed mesh (not an estimate): zero self-intersecting triangles outside the documented near-contact allowlist regions named in the spec (§6); total mesh volume within ±5% of rest pose; every vertex position finite; skin weights still sum to 1.0 within 1e-6 after pose (weights don't change with pose, but this guards against a posing bug that corrupts them).
- [ ] **Step 2: Run it against real Phase 4 output and confirm it passes** (or tighten/loosen the ±5% and near-contact tolerances with a one-line documented rationale if real data shows the initial target was wrong — per spec §6 these are initial targets, not fixed law).
- [ ] **Step 3: Commit.**

### Task 16: Documentation

**Files:**
- Create: `docs/CHARACTER_STUDIO_STEP6C.md`, `docs/BASE_MESH_PROVENANCE.md`
- Modify: `README.md` (add Step 6C to the status table, matching the existing row format for Steps 1 through 5B)

**Interfaces:**
- Consumes: nothing new
- Produces: nothing new — documentation only

- [ ] **Step 1: Write `docs/CHARACTER_STUDIO_STEP6C.md`** following the existing `CHARACTER_STUDIO_STEP6A.md`/`STEP6B.md` format: status, what works, contracts, known limitations, explicit non-claims (spec §9), run instructions.
- [ ] **Step 2: Write `docs/BASE_MESH_PROVENANCE.md`** recording the actual downloaded archive's SHA-256, confirmed license text, and version, following `docs/PROVENANCE.md`'s existing pattern.
- [ ] **Step 3: Update `README.md`'s status table** with a Step 6C row.
- [ ] **Step 4: Commit.**

```bash
git add docs/CHARACTER_STUDIO_STEP6C.md docs/BASE_MESH_PROVENANCE.md README.md
git commit -m "docs: document Step 6C (fixed-topology rigged humanoid)"
```
