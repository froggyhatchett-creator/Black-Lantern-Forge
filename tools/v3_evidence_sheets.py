"""Compose the generator v3 Phase 1 evidence sheets from tools/studio_v3_check.mjs screenshots (no rendering)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

D = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/character_forge_aaa/humanity/v3_phase1")
S = D / "shots"


def tile(name, label, w=420):
    im = Image.open(S / name).convert("RGB")
    im = im.resize((w, int(im.height * w / im.width)))
    ImageDraw.Draw(im).rectangle((0, 0, w, 22), fill=(20, 20, 24))
    ImageDraw.Draw(im).text((6, 5), label, fill=(240, 220, 160))
    return im


def sheet(tiles, cols, out):
    w, h = tiles[0].width, max(t.height for t in tiles)
    rows = -(-len(tiles) // cols)
    im = Image.new("RGB", (cols * (w + 4), rows * (h + 4)), (14, 14, 16))
    for k, t in enumerate(tiles):
        im.paste(t, ((k % cols) * (w + 4), (k // cols) * (h + 4)))
    im.save(D / out)


ctl = sorted({p.name.rsplit("_", 1)[0] for p in S.glob("control_*_min.png")})
sheet([tile(f"{c}_{e}.png", f"{c[8:].replace('_', '.', 1)} = {e}", 300) for c in ctl for e in ("min", "max")], 4, "sheet_controls.png")
sheet([tile(f"female_body_{y}.png", f"female preset, body, yaw {y}", 300) for y in (0, 45, 90, 180)]
      + [tile(f"male_body_{y}.png", f"male preset, body, yaw {y}", 300) for y in (0, 35)], 3, "sheet_angles_body.png")
sheet([tile(f"female_face_{y}.png", f"female preset, face, yaw {y}") for y in (0, 35, 90)] + [tile("male_face_25.png", "male preset, face, yaw 25")], 2, "sheet_angles_face.png")
sheet([tile(f"blink_{w}_{y}.png", f"blink {w}, yaw {y}") for w in (0, 0.5, 1) for y in (0, 35)], 2, "sheet_blink.png")
sheet([tile(f"pose_{p}.png", p.replace("_", " "), 300) for p in ("Relaxed", "Arms_raised", "Lunge")] + [tile("walk_frame8.png", "walk clip, frame 8", 300)], 4, "sheet_rig.png")
print("sheets written to", D)
