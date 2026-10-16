"""Phase 3B close-ups: larger front and three-quarter faces and eye close-ups (open / closed) per identity."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.render import Camera, label, rasterize, save, sheet  # noqa: E402
from forge_character_forge.v3 import identity, model  # noqa: E402
from identity_proof import OUT, head_items  # noqa: E402

E = identity.frame()
faces = {"neutral (v3 default)": model.neutral(), **{k: identity.identity_mesh(v) for k, v in identity.IDENTITIES.items()}}
tiles, eyes = [], []
for name, v in faces.items():
    t = tuple(E + np.array([0, -0.04, 0]))
    for yaw in (0, 35):
        tiles.append(label(rasterize(head_items(v), Camera(yaw_deg=yaw, pitch_deg=2, target=t, distance=0.48, fov_deg=26), W=520, H=600,
                                     background=(0.78, 0.8, 0.83), ground_y=None), f"{name}  yaw {yaw}", size=15))
    d, _ = model.fit_blink(v)
    for w, tag in ((0, "open"), (0.5, "half"), (1, "closed")):
        eyes.append(label(rasterize(head_items(v + w * d), Camera(yaw_deg=15, pitch_deg=3, target=tuple(E + [0, 0.004, 0]), distance=0.2, fov_deg=26),
                                    W=420, H=260, background=(0.78, 0.8, 0.83), ground_y=None), f"{name} {tag}", size=13))
save(sheet(tiles, 2), OUT / "identity_closeups.png")
save(sheet(eyes, 3), OUT / "identity_eyes_blink.png")
