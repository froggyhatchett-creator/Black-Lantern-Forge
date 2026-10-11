# Determinism

Determinism is Forge's first-class contract.

## The contract

For a given `(seed, generator_version)`:

| Output | Guarantee | Enforced by |
|---|---|---|
| Parameters | Identical, bit-exact floats | `test_1_*`, golden params hash |
| Vertex positions | Bit-identical binary64 values | `test_2_*`, golden vertex hash |
| Faces | Identical index tuples | `test_3_*` |
| OBJ export | Byte-identical file | `test_4_*`, golden OBJ hash, CLI test |

Supported environment: CPython ≥ 3.10 with IEEE-754 binary64 floats and
`sys.float_repr_style == "short"`. That covers every mainstream CPython build
(x86-64, ARM64; Linux, macOS, Windows). `forge.determinism` checks this before
every generation and raises `EnvironmentNotSupportedError` if it doesn't hold.

Verified in this repository: identical output (OBJ bytes, parameter values, and
every vertex bit across 202 seeds) on CPython 3.10, 3.11, 3.12 and 3.13, and across
fresh interpreters with different `PYTHONHASHSEED` values.
**Not verified:** other CPU architectures or operating systems in practice (the
argument below says they match; no test has been run there yet), and non-CPython
interpreters.

## Why the output is stable

1. **One randomness source.** Every procedural choice draws from an explicit
   `PCG32` instance. Nothing reads Python's `random`, `hash()`, the clock, the
   PID, `os.urandom`, or the network. A static AST test enforces this, and a
   runtime test patches those functions to explode if they're called.
2. **Integer-only PRNG core.** PCG32 is pure 64-bit integer arithmetic.
   Floats come from `u32 / 2**32`, which is exact in binary64.
3. **Only correctly rounded float operations.** Geometry uses `+ − × ÷ √`
   only. IEEE 754 requires all five to be correctly rounded, so every conforming
   platform produces the same bits. Trig and other libm functions (whose last
   bit can differ between platforms) are banned in generation code by test.
   Circle profiles come from exact `sqrt` identities (e.g. cos 22.5° =
   √(2+√2)/2), built with exact quadrant symmetry.
4. **No order-sensitive float reductions.** No `sum()` over floats (its
   algorithm changed in Python 3.12); reductions use explicit sequential loops.
5. **Deterministic formatting.** OBJ coordinates use fixed 6-decimal formatting,
   which CPython rounds correctly and identically on all platforms. `-0.000000`
   is normalized to `0.000000`. Output is ASCII, `\n` line endings, written as
   bytes (no newline translation), with no timestamps, paths, or hostnames.

## PRNG: PCG32

PCG-XSH-RR with 64-bit state and 32-bit output, matching the reference C
implementation (`pcg32_srandom_r`, `pcg32_random_r`, `pcg32_boundedrand_r`)
bit-for-bit. Known-answer tests reproduce the reference `pcg32-demo` output for
`seed=42, stream=54`.

| Operation | Definition |
|---|---|
| `next_u32()` | Reference PCG32 output |
| `next_bounded(n)` | Unbiased integer in `[0, n)`, reference rejection sampling |
| `next_float()` | `next_u32() / 2**32`, in `[0, 1)` |
| `uniform(lo, hi)` | `lo + (hi − lo) × next_float()`, one draw |
| `choice(seq)` | `seq[next_bounded(len(seq))]` |

Chosen because it's small, integer-only, fully specified, has independent
streams, and has published reference vectors.

## Seeds and streams

- Seed: plain `int` in `[0, 2**64−1]`, validated in exactly one place
  (`forge/seed.py`). Invalid input always raises `InvalidSeedError`.
- Each component gets its own stream:
  `PCG32(initstate=seed, initseq=FNV1a64(label))` with labels
  `forge.sword.blade`, `forge.sword.guard`, `forge.sword.grip`,
  `forge.sword.pommel`. FNV-1a is used instead of `hash()` because `hash()` of a
  string is salted per process.
- Effect: a future generator version can change how the guard is drawn without
  shifting the random values the blade receives.
- Draw order inside each stream is fixed and documented in `forge/sword/v1.py`.
  Conditional parameters (e.g. guard `end_scale`) are always drawn, even when a
  shape doesn't use them, so the stream never depends on earlier choices.

## Generator versions

- `generate_sword(seed, generator_version)` requires the version. There is no
  implicit "latest" in the API, so a version bump never silently changes an
  existing caller's sword. (The CLI defaults to latest and records it.)
- Released versions are frozen. `v1.py` must keep producing the same output
  forever. Any change that would alter output (bounds, draw order, constants,
  vertex order, topology) goes into a new module registered under a new number.
- Golden hashes in `tests/test_determinism.py` lock v1. If one fails, v1
  changed: restore it. Don't update the hash.
- The OBJ header records `obj_format`. Formatting changes bump it.

## Boundaries

- Byte stability is a property of **(seed, generator_version, obj_format)**,
  not of the Forge package version.
- Changing `COORD_DECIMALS`, the header, or record order changes OBJ bytes, so it
  requires an `obj_format` bump.
- If you consume the in-memory geometry yourself, you get full binary64
  precision. Downstream tools that re-serialize it are outside this contract.

## Step 2 additions

Step 2 extends the contract without changing anything above:

- Normals, UVs, and materials are pure functions of `(frozen asset, presentation
  versions)`. They use the same rules: correctly rounded IEEE ops only, no libm
  transcendentals, no `sum()` over floats, no `**`. Static tests enforce this
  for every Step 2 numeric module.
- Material randomness comes from separate PCG32 streams labelled
  `forge.presentation.material.v1.<component>`. They're disjoint from the geometry
  streams, so presentation can't shift geometry randomness.
- Preview pixels follow the same argument. PNG *file* bytes depend on the zlib
  build, so previews are compared by `pixels_sha256`.
- Verified bit-identical on CPython 3.10–3.13: normals, UVs, materials, and
  enriched OBJ/MTL bytes for 122 seeds; record content hash; preview pixels in
  all three views.

Hash definitions and record versioning: [PERSISTENCE.md](PERSISTENCE.md).
Renderer boundary: [PREVIEW.md](PREVIEW.md).
