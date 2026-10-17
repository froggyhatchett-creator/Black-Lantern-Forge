# Myth v0.3.0 proof of concept: results

Status: **prepared and statically validated; the rendering half is blocked here and waits on your tower.**
Run date: 2026-10-17. Input: `examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb`
(committed, unchanged).

## What actually ran

| Step | Result |
|---|---|
| Isolated environment | `experiments/myth_poc/.venv` (git-ignored). `pip install myth-py==0.3.0`: one wheel, **no Python dependencies**, venv 33 MB. Forge's environment and `pyproject.toml` are untouched. |
| `import myth` | OK (Linux x86-64, CPython 3.13, abi3 wheel). |
| `Renderer.init_headless(640, 480)` | **FAILED: no GPU adapter.** Exact error: "No compatible GPU adapter found ... vulkan drivers/libraries could not be loaded ... gl drivers/libraries could not be loaded". The container has no Vulkan or OpenGL driver. Per your instruction, no system driver was installed. |
| Load the GLB without a GPU | **Not possible.** `create_scene()` and `load_gltf()` both refuse before GPU initialisation ("Renderer not initialized"). Myth cannot even parse a file headlessly without an adapter, so no Myth-side loading was verified here. |
| `myth_poc.py` | Runs up to GPU initialisation, records the error in `myth_out/myth_metrics.json` and exits with code 2. |
| Reference (our independent player) | Done: 9 frames, masks and metrics in `reference/` (below). About 5 minutes on CPU. |
| `compare.py` | Tested here. Reference vs itself: all pass. Sabotaged copy: exactly the four planted defects fail. |
| `run_on_windows.ps1` | Written; **not executed** (no PowerShell or Windows here). |

## Reference numbers (our player; what Myth must reproduce)

| Frame | Silhouette px | Visible eyeball px | Garment px |
|---|---|---|---|
| full body, front, rest | 23,513 | 25 | 12,995 |
| full body, 3/4, rest | 23,229 | 22 | 12,192 |
| full body, 3/4, walk frame 10 | 20,554 | 21 | 11,399 |
| face, front, blink 0 / 0.5 / 1 | 146,919 | 2,502 / 1,246 / 12 | 0 |
| face, 3/4, blink 0 / 0.5 / 1 | ~169,900 | 1,834 / 929 / 4 | 0 |

Blink is linear and closes, as in the studio: 0.50 at half blink, 0.002-0.005 when closed.

## Static compatibility of this GLB with Myth's loader (source read, not run)

| GLB feature | Myth v0.3.0 | Evidence |
|---|---|---|
| Sparse morph targets, no bufferView (zero base), u32 indices | **supported** | `myth-gltf` 1.4.2 `SparseIter`: zeros for `accessor.count` and values at the indices. It needs strictly increasing indices; **ours are** (checked, all 8 accessors). Myth decodes them through `gltf::accessor::Iter` (`load_morph_targets`). |
| Morph target names (`mesh.extras.targetNames`) | **not read** | Weights are set by index: 0 = blink_l, 1 = blink_r, on all four morphed meshes (checked). |
| 62-joint skin, u16 JOINTS_0, f32 WEIGHTS_0 | supported | joint matrices in a storage buffer (no cap); `read_joints(0).into_u16()`, `read_weights(0)` |
| Float VEC3 COLOR_0 (hair) | supported | `read_colors(0).into_rgba_f32()` |
| u32 indices, single-primitive meshes | supported | the mesh stays on the named node (`find_node_by_name("body").mesh`) |
| LINEAR rotation/translation clips | supported | translation/rotation/scale/morph-weight channels |
| Metallic-roughness, PNG textures, MASK, BLEND, doubleSided | claimed supported | not rendered here |
| Skinning visually correct, walk pose, clothing, blink closure | **unverified** | needs the tower run (`compare.py` criteria) |

## Dependencies (as installed)

- `myth-py` 0.3.0, about 8 MB per platform wheel: Windows x64/ARM64, Linux x86-64/aarch64, macOS. No Python dependencies.
- **Bundled Rust code:** 308 crates per the wheel's own CycloneDX SBOM (`myth_py-0.3.0.dist-info/sboms/`). These include wgpu 29.0.4, winit 0.30.13, pyo3 0.28.3, image 0.25.10 and Myth's own glTF fork myth-gltf 1.4.2; no egui (the egui UI is not in the Python wheel). They also include **an HTTP/TLS client** (`ehttp`, `ureq`, `rustls`, `webpki-roots`): Myth's default `http` feature can load assets from URLs. The PoC passes only a local file path; nothing here makes network requests.

## Licensing (from the SBOM; reviewed, not legal advice)

- **No copyleft** among the 308 bundled crates. The licenses are MIT OR Apache-2.0, MIT, Apache-2.0, BSD-2/3-Clause, ISC, Zlib, Unicode-3.0, Unlicense, BSL-1.0 and CC0-1.0.
- One data license: `webpki-roots` (the bundled TLS root certificates) is **CDLA-Permissive-2.0**.
- **Concern: the wheel ships no license or notice files at all.** Its metadata says only "MIT", although the engine is MIT OR Apache-2.0 and its dependencies need their notices reproduced when redistributed. Using the wheel locally, as here, carries no obligation. If Forge ever **redistributes** Myth (a bundled installer, say), we must assemble an attribution file ourselves, from this SBOM plus each crate's license text.

## Compatibility blockers and limitations found

1. **No GPU, no Myth.** Myth needs a wgpu adapter for everything, including loading a file. A headless CI check without a GPU would need a software Vulkan driver (Mesa, as Myth's own CI uses), which is an environment change you have not approved.
2. **Morph names are not read.** Blink must be driven by index; acceptable because we own the exporter.
3. **The Python API cannot seek an animation.** The mixer only has play/stop, so a given frame is reached by stepping `update(dt)` from the start. Deterministic, but scrubbing a timeline (an editor need) is not available from Python.
4. **No skin or joint introspection in Python.** The 62-joint skin can only be checked through the rendered result, which is what the silhouette test does.
5. **Shading cannot match the Studio.** The GLB carries plain PBR; the Studio's skin SSS, eye and strand shading would have to be re-made as Myth custom materials. The comparison therefore measures geometry, not looks.
6. **Performance is unknown.** Nothing rendered. `myth_poc.py` will record headless init, GLB load and median/max render+readback time on the tower. Its own pixel bookkeeping costs about 0.03 s per frame.
7. **Tk embedding is untested.** The interactive check uses Myth's own window (`--window`), not Forge's Tk shell.

## Next (needs your run)

Run `run_on_windows.ps1` on the tower and send back `myth_poc_results.zip`. If every check passes, the assessment's
CONDITIONAL GO is confirmed for the viewer role. If a check fails, the side-by-side images and the JSON say which
one: sparse morphs, skinning, clothing or the walk.
