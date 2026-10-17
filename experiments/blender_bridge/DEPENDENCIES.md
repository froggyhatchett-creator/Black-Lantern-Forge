# Dependencies of the Blender bridge experiment (isolated; not Forge dependencies)

Installed 2026-10-17, with approval, into `experiments/blender_bridge/.bpy-venv` only. The venv and the cached
wheel (`.wheels/`) are git-ignored. Forge's `pyproject.toml` (`dependencies = []`) and the system Python are
unchanged; the system Python still cannot import `bpy`. Delete the two directories to remove everything.

## The package

| Item | Value |
|---|---|
| Package | `bpy` 5.2.2 (Blender 5.2.2 LTS as a Python module) |
| Publisher | Blender Foundation (PyPI metadata; homepage https://www.blender.org) |
| File | `bpy-5.2.2-cp313-cp313-manylinux_2_28_x86_64.whl`, released 2026-09-15 |
| Size | 401,697,653 bytes; matches PyPI exactly |
| sha256 | `3dfd1a9e7a5aec0f0fe95a1b01d10cd66e212b16ea38b77d132159dc9a666d45`; matches PyPI's published digest |
| Install method | Downloaded with `--no-deps`, hash and size checked, then installed from that file |
| Python | 3.13 only (venv created from the system 3.13.16) |
| Disk | venv 1.0 GB, cached wheel 384 MB |

## Installed packages (licences from each package's own metadata)

| Package | Version | Licence |
|---|---|---|
| bpy | 5.2.2 | **GPL-3.0** |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib (+ bundled) |
| Cython | 3.3.0 | Apache-2.0 |
| requests | 2.34.2 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| certifi | 2026.7.22 | **MPL-2.0** |
| charset-normalizer | 3.5.2 | MIT |
| idna | 3.20 | BSD-3-Clause |
| attrs | 26.1.0 | MIT |
| cattrs | 26.2.1 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| zstandard | 0.25.0 | BSD-3-Clause |

## Licensing concerns (not legal advice)

**1. `bpy` is GPL-3.0.**
- Forge never imports it. Jobs run it as a separate process that exchanges files.
- Output files (GLBs) are not GPL.
- **Never redistribute** Blender or `bpy` with Forge. Users install Blender themselves.

**2. `job_blender.py` and `probe_blender_selection.py` import `bpy`.**
- The Blender Foundation regards distributed scripts like these as GPL-covered.
- They are kept as a separate component.
- Licensing them (GPL-3.0-or-later) is the owner's decision if they are ever shipped.

**3. certifi (MPL-2.0)** is file-level copyleft. It is irrelevant while nothing is redistributed.

**4. The `bpy` wheel bundles 44 native libraries** in `bpy/lib`, for example OpenEXR, OpenImageIO, OpenColorIO,
OpenVDB, USD, Embree, oneTBB, MaterialX, Draco, meshoptimizer, OpenImageDenoise, Vulkan and SYCL loaders.
- The wheel carries **no top-level licence or third-party notice file**. Only the Cycles add-on and some data files
  (assets, studio lights) include their own licence texts.
- The same rule applies: do not redistribute it.
- If that ever changes, the notices would have to be assembled from upstream.
