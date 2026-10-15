"""Character Forge generator v3 (Phase 1): realistic adult human on the MakeHuman hm08 CC0 foundation.

Independent of generators v1/v2 (their code, studio pack, garments and DNA are unchanged). The v3 model is the studio
pack written by ``v3.bake``; see docs/CHARACTER_FORGE_V3_PLAN.md and docs/CHARACTER_FORGE_V3_PHASE1.md.

Identity extension point: ``IDENTITY_LAYERS`` is where Forge-owned identity morphs (per-character shape layers on
this topology) and alternative body templates will register. Phase 1 registers none and applies none.
"""

GENERATOR_ID = "forge.character-forge"
GENERATOR_VERSION = 3
TEMPLATE_VERTICES = 13380  # hm08 body vertices (UV-seam copies are GPU-only; tests check this count)
GENERATOR = {"id": GENERATOR_ID, "version": GENERATOR_VERSION, "template_vertices": TEMPLATE_VERTICES,
             "foundation": "makehuman-hm08-cc0", "template": "human-adult"}
IDENTITY_LAYERS: dict = {}
