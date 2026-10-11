"""Example: generate a handful of short swords through the Python API.

Run from anywhere:
    python examples/generate_short_swords.py
Writes OBJ files into <repo>/output/.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from forge import generate_sword, write_obj  # noqa: E402

GENERATOR_VERSION = 1  # pin it: same seed + same version = same sword, forever

for seed in (1, 2, 3, 1337):
    sword = generate_sword(seed, GENERATOR_VERSION)
    path = write_obj(sword, REPO_ROOT / "output" / f"short_sword_seed{seed}_v{GENERATOR_VERSION}.obj")
    b, g, m = sword.params.blade, sword.params.guard, sword.params.pommel
    print(f"seed {seed:>5}: {b.length:.3f} m {b.point_shape} blade, {g.shape} guard, "
          f"{m.shape} pommel, {sword.triangle_count} tris -> {path.relative_to(REPO_ROOT)}")
