"""Bake the Character Studio pack (exact Python builds -> morph basis) into examples/character_forge_aaa/studio/."""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from forge_character_forge.studio_bake import bake, compact_pack

out = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/character_forge_aaa/studio/studio_pack.bin")
man = bake(out, workers=int(sys.argv[2]) if len(sys.argv) > 2 else 4)
print("compacted:", compact_pack(out))
print("params:", len(man["params"]), "parts:", len(man["parts"]), "unstable:", man["unstable_topology"])
