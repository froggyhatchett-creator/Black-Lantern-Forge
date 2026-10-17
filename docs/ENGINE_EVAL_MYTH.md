# Engine evaluation: Myth (panxinmiao/myth) for Black Lantern Forge

Status: **assessment only; stopped for approval.** Nothing was integrated. No Forge, Character Forge or Black Lantern OS
code was changed. Myth was read from source (shallow clone of `main` at b168cab, 2026-09-30, outside the Forge
repo); no dependency was fetched or built, nothing was run on a GPU.

**Recommendation: CONDITIONAL GO, for a narrow role.** Use Myth as an *optional, out-of-process rendering backend*
(an independent GLB viewer / headless renderer driven through its prebuilt Python wheel), proven by one isolated
proof of concept on your tower. **NO-GO, for now, as the basis of the native Forge editor** or as a replacement for
Character Studio. Revisit the editor question after the PoC and after Myth has a second maintainer or a 1.0.

Legend: **[verified]** = read in Myth's source, manifests, CI or package registries; **[claimed]** = stated in Myth's
docs, not checked in code; **[not verified]** = could not be checked here (no GPU, no build). Nothing about
Myth's *rendering* is verified by running it: this container has no GPU and no Vulkan driver, and building Myth
would mean fetching wgpu and its dependency tree, which was out of scope.

## 1. What Myth is

| | |
|---|---|
| What | A Rust 3D **rendering engine** on wgpu (Vulkan / DX12 / Metal / WebGPU) [verified: Cargo.toml]. Not a full game engine: "physics, audio, and networking are left to your choice" [claimed, docs]. |
| Size | ~173,000 lines of Rust, 68 WGSL shader files/templates, 10 crates (core, scene, resources, assets, animation, render, app, egui, macros, dev utils) [verified] |
| Version | 0.3.0 (2026-07-31); crates.io `myth-engine` 0.3.0, created 2026-02-07, **522 downloads total** [verified]. PyPI `myth-py` 0.3.0 [verified] |
| History | First commit 2026-01-04. **All 755 commits on `main` by one author** (Pan Xinmiao) [verified, git log]. 104 commits since July: very active. GitHub: 221 stars, 18 forks, 5 open issues, 6 open PRs [verified, repo page] |
| License | **MIT OR Apache-2.0** (dual, licensee's choice) for the engine; the Python package metadata says MIT [verified] |
| Toolchain | Rust 1.92+, edition 2024, wgpu 29, winit 0.30, egui 0.34, glam 0.32; uses a **fork of the `gltf` crate** (`myth-gltf`) [verified] |
| Stability | Pre-1.0 with breaking API changes listed in the 0.3.0 changelog (frame composition, camera extraction, screen-space settings, image API, render-graph handles) [verified]. Expect churn. |
| CI | lint; tests on ubuntu, windows and macos (Linux headless via Mesa software Vulkan + Xvfb); WASM check; Python wheel publishing [verified: .github/workflows] |

## 2. Capabilities that matter to Forge

| Capability | Status | Notes |
|---|---|---|
| PBR materials | [claimed] + code present | Metallic-roughness plus clearcoat, iridescence, transmission, sheen, anisotropy; Phong, unlit, custom-material macro. Example `pbr_materials.rs`. |
| GPU rendering pipeline | [verified, source] | SSA render graph, clustered forward lighting, cascaded and spot shadows, IBL, SSAO/SSR/SSGI/SSSS, TAA/FXAA/MSAA, bloom. Two paths: HighFidelity and BasicForward. |
| Skeletal animation | [verified, source] | GPU skinning with joint matrices in a **storage buffer** (no fixed joint cap; our studio's WebGL2 path caps at 80). Shadow-skinning example. |
| Animation clips / blending | [verified, source] | `AnimationMixer` / `AnimationAction` (three.js-style): play, blend, events; glTF translation, rotation, scale and **morph-weight** channels. |
| Morph targets | [verified, source] | Up to 128 active targets per mesh; positions, normals and tangents in storage buffers; weights settable per mesh from Rust and Python (`set_morph_target_influences`). |
| Facial animation | **absent** | Nothing beyond morph weights: no facial rig, FACS layer, lip-sync or expression system. Forge would still own all facial logic. |
| glTF 2.0 import | [verified, source] | Async loader; skins, clips, morph targets; KHR_materials_*, KHR_texture_transform, meshopt, quantization. **Does not read `mesh.extras.targetNames`** (morphs addressed by index). **Sparse accessors** (our morph targets use them) depend on the forked `gltf` crate: **[not verified]**. |
| Scene management | [verified, source] | Scene graph, nodes, cameras, lights, prefabs, multiple scenes. |
| Object picking | **absent** | No raycast or picking API; only an unjittered projection "for UI / raycasting" in the camera. An editor would build picking itself. |
| Editor interfaces | partial [verified, source] | `myth_egui` (egui inside Myth's render graph); the 3,000-line glTF viewer demo has a scene inspector (node tree, materials, textures) and animation controls. **No gizmos, undo, selection, asset browser or serialization of edited scenes.** |
| Headless / offscreen | [verified, source] | `init_headless` + non-blocking GPU→CPU readback, in Rust and Python; used in its CI tests. |
| Python bindings | [verified, registry] | PyO3; **prebuilt wheels**: Windows x64/ARM64, Linux x86-64/aarch64 (manylinux2014), macOS x86/ARM, CPython 3.10+ (abi3), 7-9 MB each. Supports glTF loading, animation play, morph weights, headless render and readback. |
| Embedding in a host window | [claimed, source table] | `init_with_handle(native handle)`: PySide6 `winId()`, wxPython, SDL2, glfw, **Tk `winfo_id()`**; Win32, AppKit, X11 (no Wayland path in the bindings). Tk embedding untested. |
| Platforms | Windows / macOS / Linux [verified, CI]; WebGPU/WASM [verified, CI build check]; iOS/Android [**claimed only**: no native Android build configuration in the repo] | |

## 3. What Forge has today (from a read-only survey of this repo)

- **Character Studio** (`studio/studio.js`, `studio/gl.js`, ~1,500 lines): dependency-free WebGL2 in a browser.
  - Skinning is GPU linear-blend skinning, capped at 80 joints.
  - Morphs run on the CPU. That covers the 53 controls, the 36 identity parameters and the eyelid fit, plus blink correctives, lash turn/contact and hair cages.
  - Shading is custom per material (skin with SSS, eye/cornea, strands, cloth), not glTF PBR. There are no shadow maps.
  - It is the only real-time 3D in Forge.
- **Desktop shell** (`forge_desktop/`): Tkinter, stdlib only, Windows `.pyw` launcher. It has **no real-time 3D**: it shows software-rendered preview images on a canvas (weapons).
- **Engine viewer** (`forge_engine_viewer/`): independent Tk viewer for weapon contract packages. It uses a painter's algorithm and is explicitly not PBR; it refuses skins and animations.
- **Software rasterizers**: `forge_character_forge/render.py` (numpy) and `forge/render/raster.py`. They are deterministic, and used for evidence and preview sheets.
- **GLB pipeline**: Python and browser exporters, validators and two independent Node loaders.
  - The exported GLBs use **plain core glTF 2.0, no extensions**: one 62-joint skin, sparse POSITION morph targets named in `mesh.extras.targetNames`, metallic-roughness materials with embedded PNGs, LINEAR rotation and translation clips.
- No Rust anywhere. The Python package declares no dependencies (numpy and Pillow are used in practice).

## 4. Fit with Forge's architecture

**Good fit**
- **The GLB contract is the seam.** Forge already treats the GLB as the hand-off to "any game engine" (`FORGE_ENGINE_CONTRACT_V1`). A Myth viewer that only *consumes* our GLBs needs no change to generators, DNA or exports.
- **The Python wheel avoids a Rust toolchain in Forge.** A Python tool can drive Myth like any optional dependency, and import it only when present.
- **License** permits use, modification, vendoring and forking.
- **Headless readback** would give Forge real GPU renders of exported characters for evidence and CI. The caveat is that GPU output is not bit-deterministic across drivers, which our software rasterizer is.

**Poor fit**
- **Language and stack.** Forge is Python stdlib-first with a WebGL2 studio. Myth is a 173k-line Rust/wgpu engine on Rust 1.92 and edition 2024. Any deep integration means adopting Rust and its build chain, or living behind the Python bindings' API surface.
- **Character Studio's real work is not rendering.** Its value is the CPU-side morph basis, identity, eyelid fit, lash contact and hair cages, plus character-specific shading. Myth would replace roughly `gl.js` (draw calls, skinning, lighting). All the Studio logic would have to be re-hosted, and the custom skin/eye/strand look would have to be re-made as Myth custom materials: our GLBs carry only plain PBR.
- **Editor essentials are missing:** no picking, gizmos, undo, selection model or scene serialization. Myth gives a renderer plus egui, not an editor.
- **Maintenance risk.** One maintainer, nine months of history, pre-1.0 churn, and a forked glTF crate. Basing Forge's native editor on it now would put Forge's core on a single person's pace and priorities.

## 5. Role options, compared with keeping what we have

| Option | Gains | Costs / risks | Verdict |
|---|---|---|---|
| **Keep current systems only** | No new dependency; full control; deterministic evidence; Character Studio already works and exports | No real-time 3D on the desktop; no PBR/shadows/IBL viewer for exported GLBs; editor renderer would be built from scratch later | Baseline |
| **Myth as an optional rendering backend / viewer** (out of process, via `myth-py`) | Real-time PBR, shadows, IBL, skinning, morphs and animation on exported GLBs with no Forge code changes; headless GPU renders; Windows wheels today | Optional Python dependency; GLB-only (no live Studio logic); untested Tk embedding; sparse-accessor support to be proven | **CONDITIONAL GO** (this assessment) |
| **Myth as the basis of the native Forge editor** | Saves writing a modern renderer (render graph, lighting, post, glTF, egui) | Rust adoption; editor features still to build; bus factor 1; API churn; Studio logic re-host; lock-in to a young project | **NO-GO for now** |
| **Selective reuse of components** (study or vendor parts under MIT/Apache) | Ideas and code for a render graph, clustered lighting, sparse morph storage, readback | Only useful once Forge has its own Rust/wgpu renderer; vendored code becomes ours to maintain | Later, if we go native Rust |

**What it could realistically replace or improve:**
- `forge_engine_viewer`, for character GLBs: it cannot show skins or animation today.
- A real-time 3D panel in the Tk desktop shell, if Tk embedding works.
- An optional GPU path next to the software rasterizers for "beauty" previews. The rasterizers would stay for deterministic tests.

It would **not** replace Character Studio's WebGL2 renderer without re-hosting the Studio, and that is not justified now.

**Development time:** for viewing exported characters with PBR, shadows and animation, Myth plausibly saves weeks. For a native editor, the renderer is the smaller part. Picking, gizmos, undo, serialization and the Forge-specific deformation logic dominate, and Myth supplies none of them. Independence is preserved only if Myth stays behind the GLB contract and is optional: Forge must keep running without it.

## 6. Licensing, platforms and long-term maintenance

**Licensing**
- MIT or Apache-2.0, at our choice. Obligations when distributing Myth (source or binaries): keep its copyright notice and the license text. Under Apache-2.0, also keep its NOTICE (none present) and state changes to modified files. Apache-2.0 includes a patent grant; MIT does not.
- Nothing is copyleft at the top level.
- **The transitive Rust dependency licenses were not audited** (no `cargo deny` run without fetching). wgpu, winit and egui are MIT/Apache; zstd is BSD; the rest are unknown. An audit is a condition before any distribution.

**Windows**
- Verified in CI (windows-latest tests) and by published win_amd64 and win_arm64 wheels. Backends DX12 and Vulkan.
- **Not verified on your tower or on any GPU by me.**

**Linux**
- Verified in CI with Mesa software Vulkan. Native window embedding through the Python bindings is X11 only (no Wayland).

**Android**
- Claimed in the docs only. There is no native Android build configuration, NDK or APK tooling in the repository. The "mobile" support visible in code is the WebGPU build in a mobile browser.
- If Android matters, it is unproven.

**Maintenance risks, and mitigations**
- **Bus factor 1:** pin an exact version, and keep Forge fully functional without Myth.
- **API churn before 1.0:** use one thin adapter script; never let Forge data models depend on Myth types.
- **Forked glTF crate:** our GLBs use core glTF only; the PoC tests our exact files.
- **Upstream abandonment:** the license allows a fork, but a fork of 173k lines of Rust is not something Forge can realistically maintain today. Treat it as a replaceable viewer, not a foundation.

## 7. Proposed proof of concept (not started; needs your approval)

**Goal:** prove that Myth renders an existing Character Forge v3 GLB unchanged, with the walk clip and the blink morphs, on Windows, without touching Forge.

**Isolation**
- A new folder `experiments/myth_poc/`, or a separate scratch repo if you prefer zero footprint in Forge.
- It contains one Python script plus a README, run in its own virtual environment.
- No import of Forge packages, and no change to generators, DNA, Studio, exports or Black Lantern OS.
- Myth is not added to `pyproject.toml`.

**Inputs (read-only)**
- `examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb`: committed; 62-joint skin, 7 clips; blink is morph index 0 (left) and 1 (right) on the body, brows, lashes and hair.
- Its DNA stays inside the GLB untouched.

**Dependencies**
- `pip install myth-py==0.3.0` in a venv: one prebuilt wheel, about 8 MB, no Rust build, free.
- On your tower: your GPU driver.
- In this container: only if you also approve Mesa's software Vulkan driver (`mesa-vulkan-drivers`, a system package of a few tens of MB), the same setup Myth's own CI uses.

**Script**
1. Headless init at 1280×720.
2. Load the GLB.
3. List animations; expect idle, walk, run, jump, turn, sudden_stop, wave.
4. Play `walk`, stepping a fixed dt.
5. Set blink weights 0 / 0.5 / 1 by index on the four morphed meshes.
6. Render fixed frames (walk frame 10 at blink 0, 0.5 and 1, plus a rest pose), read them back and save PNGs.
7. Do the same through a window, for the interactive check.

**Acceptance**
- The GLB loads with no error. Sparse morph targets are applied: blink 1 visibly closes both eyes.
- All 62 joints skin correctly, with no exploded vertices or misplaced garments, matching the silhouette of our independent loader (`tools/glb_playback.mjs` + `render.py`) at the same frame.
- The walk plays and loops. Clothing (public profile) is present.
- It runs on Windows with your GPU, and you send back the PNGs and timings.
- Optional: Tk embedding via `winfo_id()` in a 20-line test window.

**Effort:** about half a day to write, plus one run on your tower. Nothing in Forge changes, so removing it is deleting the folder.

**Decision after the PoC**
- If it passes: an optional "View in Myth" tool next to the existing viewers, still outside the core.
- If sparse morphs or skinning fail: report upstream; our pipeline stays as is.
- The native-editor question stays separate. Re-evaluate it when Forge has an editor plan and Myth has more than one maintainer or a 1.0.

## 8. Verified vs assumed: summary

- **Verified (source, CI, registries):**
  - license; version and history; one maintainer
  - the wgpu stack and crate layout
  - GPU skinning via storage buffer; morph targets (128, positions/normals/tangents); animation mixer and glTF channels including morph weights
  - headless readback; egui integration; inspector demo
  - Python wheels for Windows, Linux and macOS; CI on three OSes
  - absence of picking, gizmos and a facial layer; `targetNames` not read
- **Claimed, not checked:** visual quality and performance; PBR extensions behaving correctly; iOS/Android; Tk embedding; sparse-accessor loading in the forked glTF crate.
- **Not verified at all:** anything at runtime, any GPU, your Windows tower, transitive licenses.
