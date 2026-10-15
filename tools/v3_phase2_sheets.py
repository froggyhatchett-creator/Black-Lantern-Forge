"""Compose generator v3 Phase 2 evidence sheets from tools/studio_v3_visual.mjs screenshots (no rendering).

before_* come from the Phase 1 build (commit 4932d59) and after_* from this build, with identical cameras.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

D = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/character_forge_aaa/humanity/v3_phase2")
S = D / "shots"


def tile(name, label, w=480):
    im = Image.open(S / name).convert("RGB")
    im = im.crop((0, 0, im.width, im.height - 70))  # drop the studio's bottom toolbar
    im = im.resize((w, int(im.height * w / im.width)))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w, 22), fill=(20, 20, 24))
    d.text((6, 5), label, fill=(240, 220, 160))
    return im


def sheet(rows, out):
    tiles = [t for r in rows for t in r]
    w, h = tiles[0].width, max(t.height for t in tiles)
    cols = max(len(r) for r in rows)
    im = Image.new("RGB", (cols * (w + 4), len(rows) * (h + 4)), (14, 14, 16))
    for i, r in enumerate(rows):
        for j, t in enumerate(r):
            im.paste(t, (j * (w + 4), i * (h + 4)))
    im.save(D / out)


views = [("face_0", "front"), ("face_35", "three-quarter"), ("face_90", "profile")]
sheet([[tile(f"before_{v}.png", f"BEFORE (Phase 1) {l}") for v, l in views],
       [tile(f"after_{v}.png", f"AFTER (Phase 2) {l}") for v, l in views]], "sheet_before_after_face.png")
sheet([[tile(f"before_body_{y}.png", f"BEFORE body {y}") for y in (0, 35)] + [tile(f"after_body_{y}.png", f"AFTER body {y}") for y in (0, 35)]],
      "sheet_before_after_body.png")
sheet([[tile(f"before_blink_{w}.png", f"BEFORE blink {w}") for w in (0, 0.5, 1)],
       [tile(f"after_blink_{w}.png", f"AFTER blink {w}") for w in (0, 0.5, 1)]], "sheet_blink.png")
var = sorted(p.name for p in S.glob("after_var_*.png"))
rows = [[tile(n, n[10:-4].replace("_", " ")) for n in var[i:i + 4]] for i in range(0, len(var), 4)]
sheet(rows, "sheet_variations.png")
sheet([[tile("after_motion_pose.png", "Contrapposto pose (head turned)"), tile("after_motion_walk8.png", "walk clip, frame 8")]], "sheet_motion.png")
print("sheets written to", D)
