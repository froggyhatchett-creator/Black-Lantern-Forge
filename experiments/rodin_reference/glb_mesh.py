"""Read the single-primitive Rodin GLB (positions, normals, UVs, triangles) with Forge's own GLB reader. Read-only."""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.validate import read_glb  # noqa: E402

SOURCE = HERE / "source" / "base.glb"
SHA256 = "2f359f0135f632e33ad8ba378e3e1ecebcffafc45f698ccc7f4bd629ccc6e41f"


def load(path=SOURCE):
    g, b = read_glb(path)
    prim = g["meshes"][0]["primitives"][0]

    def acc(i, dt, n):
        a = g["accessors"][i]
        bv = g["bufferViews"][a["bufferView"]]
        o = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        return np.frombuffer(b, dt, a["count"] * n, o).reshape(a["count"], n)

    at = prim["attributes"]
    return (acc(at["POSITION"], "<f4", 3).astype(float), acc(at["NORMAL"], "<f4", 3).astype(float),
            acc(at["TEXCOORD_0"], "<f4", 2).astype(float), acc(prim["indices"], "<u4", 1).reshape(-1, 3).astype(np.int64))
