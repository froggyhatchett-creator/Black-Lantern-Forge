"""Generate authorized reference images for the image-to-3D tests and demos.

All images are produced here, either by rendering characters with known
parameters (ground truth recorded next to them) or by drawing a stylized
figure procedurally.  No third-party or downloaded imagery is used.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, ".")
from forge_character_forge.appearance import AppearanceParams
from forge_character_forge.animation import POSES
from forge_character_forge.character import CharacterSpec, build_character
from forge_character_forge.dna import spec_to_dict
from forge_character_forge.params import preset
from forge_character_forge.preview import draw_items, posed_parts
from forge_character_forge.render import Camera, rasterize


def render_ref(ch, pose=None, yaw=0.0, W=600, H=1000, bg=(0.93, 0.93, 0.92), crop=None):
    posed, _ = posed_parts(ch, pose or {})
    h = ch.skeleton.marks["height"]
    cam = Camera(yaw_deg=yaw, pitch_deg=0.0, target=(0, h * 0.5, 0), distance=6.0, ortho_height=h * 1.12)
    img = rasterize(draw_items(ch, posed), cam, W=W, H=H, background=bg, ssaa=2)
    if crop:
        img = img[crop[0]:crop[1], crop[2]:crop[3]]
    return img


def stylized_drawing(path):
    """A flat-colored stylized character sheet figure (large head, ~5.5 heads tall), drawn with primitives."""
    W, H = 500, 900
    im = Image.new("RGB", (W, H), (250, 248, 240))
    d = ImageDraw.Draw(im)
    skin, hair, shirt, skirt = (242, 205, 180), (120, 60, 140), (60, 120, 200), (40, 40, 60)
    cx, top = 250, 60
    head = 145
    d.ellipse([cx - 62, top, cx + 62, top + head], fill=skin)                  # head
    d.pieslice([cx - 70, top - 8, cx + 70, top + 120], 180, 360, fill=hair)   # hair cap
    d.rectangle([cx - 70, top + 50, cx - 55, top + 230], fill=hair)            # long side hair
    d.rectangle([cx + 55, top + 50, cx + 70, top + 230], fill=hair)
    d.ellipse([cx - 32, top + 70, cx - 12, top + 92], fill=(30, 30, 30))
    d.ellipse([cx + 12, top + 70, cx + 32, top + 92], fill=(30, 30, 30))
    d.rectangle([cx - 17, top + head - 5, cx + 17, top + head + 25], fill=skin)  # neck
    y0 = top + head + 20
    d.polygon([(cx - 85, y0), (cx + 85, y0), (cx + 60, y0 + 190), (cx - 60, y0 + 190)], fill=shirt)  # torso
    d.polygon([(cx - 85, y0 + 5), (cx - 130, y0 + 200), (cx - 112, y0 + 208), (cx - 70, y0 + 40)], fill=skin)  # arms
    d.polygon([(cx + 85, y0 + 5), (cx + 130, y0 + 200), (cx + 112, y0 + 208), (cx + 70, y0 + 40)], fill=skin)
    y1 = y0 + 185
    d.polygon([(cx - 62, y1), (cx + 62, y1), (cx + 95, y1 + 130), (cx - 95, y1 + 130)], fill=skirt)  # skirt
    for s in (-1, 1):
        d.polygon([(cx + s * 22, y1 + 125), (cx + s * 55, y1 + 125), (cx + s * 45, y1 + 330), (cx + s * 25, y1 + 330)], fill=skin)
        x0, x1 = sorted((cx + s * 18, cx + s * 52))
        d.ellipse([x0 - 18, y1 + 318, x1 + 18, y1 + 345], fill=(90, 50, 40))
    im.save(path)


def main(out="examples/character_forge_aaa/references"):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    truth = {}
    b, f, g = preset("female")
    b = b.with_(hip_width=1.08, waist_width=0.9, shoulder_width=0.92, leg_length=1.04, body_fat=0.3)
    f = f.with_(face_width=0.95)
    app = AppearanceParams(skin_tone=0.45, undertone=0.3, hair_style="long", hair_color="#5a2e16", eye_color="hazel")
    spec = CharacterSpec(b, f, g, app, ("tshirt", "shorts"), 29.0, "ref_ada", (("tshirt", "#c23b2e"), ("shorts", "#24324f")))
    ch = build_character(spec, "public")
    full = render_ref(ch)
    Image.fromarray(full).save(out / "ref_full_front.png")
    truth["ref_full_front.png"] = spec_to_dict(spec)
    Image.fromarray(full[:430]).save(out / "ref_waist_up.png")
    truth["ref_waist_up.png"] = spec_to_dict(spec)
    Image.fromarray(full[40:260, 170:430]).convert("RGB").save(out / "ref_portrait.jpg", quality=92)
    truth["ref_portrait.jpg"] = spec_to_dict(spec)
    Image.fromarray(full).save(out / "ref_full_front.webp", lossless=True)
    side = render_ref(ch, yaw=90.0)
    Image.fromarray(side).save(out / "ref_side.png")
    bm, fm, gm = preset("male")
    bm = bm.with_(shoulder_width=1.12, body_fat=0.3)
    spec2 = CharacterSpec(bm, fm, gm, AppearanceParams(skin_tone=0.7, hair_style="short", hair_color="#141010"),
                          ("tshirt", "pants"), 41.0, "ref_bram", (("tshirt", "#2f7a3a"), ("pants", "#3a3026")))
    ch2 = build_character(spec2, "public")
    seated = render_ref(ch2, pose=POSES["seated"])
    Image.fromarray(seated).save(out / "ref_seated.png")
    truth["ref_seated.png"] = spec_to_dict(spec2)
    stylized_drawing(out / "ref_stylized_drawing.png")
    truth["ref_stylized_drawing.png"] = {"note": "procedurally drawn stylized figure; no parametric ground truth"}
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=1, sort_keys=True))
    (out / "PROVENANCE.md").write_text(
        "# Reference image provenance\n\nEvery image here was generated by `tools/make_references.py` in this repository: "
        "renders of Character Forge characters with the parameters in `ground_truth.json`, crops of those renders, "
        "and one procedurally drawn stylized figure. No photographs, third-party artwork or downloaded assets.\n")
    print("wrote", sorted(p.name for p in out.iterdir()))


def phase2(out="examples/character_forge_aaa/references"):
    """Extra references for hairstyle and skirt detection (adds files; never rewrites the phase 1 references)."""
    out = Path(out)
    truth = json.loads((out / "ground_truth.json").read_text())
    b, f, g = preset("female")
    b = b.with_(hip_width=1.04, body_fat=0.35)
    app = AppearanceParams(skin_tone=0.25, hair_style="bob", hair_color="#2a1a12", eye_color="green")
    spec = CharacterSpec(b, f, g, app, ("tshirt", "skirt"), 34.0, "ref_cleo", (("tshirt", "#e0c040"), ("skirt", "#3b4f8a")))
    full = render_ref(build_character(spec, "public"))
    Image.fromarray(full).save(out / "ref_bob_skirt.png")
    truth["ref_bob_skirt.png"] = spec_to_dict(spec)
    app2 = AppearanceParams(skin_tone=0.6, hair_style="bangs", hair_color="#16100c", eye_color="dark_brown")
    spec2 = CharacterSpec(b.with_(hip_width=1.0), f.with_(jaw_width=0.95), g, app2, ("tshirt", "pants"), 27.0, "ref_dara",
                          (("tshirt", "#f0f0f0"), ("pants", "#20242a")))
    full2 = render_ref(build_character(spec2, "public"))
    Image.fromarray(full2[30:300, 150:450]).save(out / "ref_bangs_portrait.png")
    truth["ref_bangs_portrait.png"] = spec_to_dict(spec2)
    bm, fm, gm = preset("male")
    app3 = AppearanceParams(skin_tone=0.15, hair_style="long", hair_color="#8a6a3a")
    spec3 = CharacterSpec(bm, fm, gm, app3, ("tshirt", "pants"), 45.0, "ref_ewan", (("tshirt", "#6a2030"), ("pants", "#2f3a2c")))
    full3 = render_ref(build_character(spec3, "public"))
    Image.fromarray(full3).save(out / "ref_long_male.png")
    truth["ref_long_male.png"] = spec_to_dict(spec3)
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=1, sort_keys=True))
    print("wrote phase 2 references")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--phase2"]:
        phase2(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
