"""Generator v3 blink measurements, as the studio composes the blink (pack morph + per-control correctives).

Cases: the neutral (with MakeHuman's bone-only lid skinning for comparison), every control end that carries a
corrective (from the bake's fits), and the female and male presets, where several controls combine (bilinear
composition, not a fit). Output: blink_report.json.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge_character_forge.params import preset  # noqa: E402
from forge_character_forge.studio_bake import pack_array, read_pack  # noqa: E402
from forge_character_forge.v3 import metrics, model  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/character_forge_aaa/humanity/v3_phase1")
man, blob = read_pack(Path(__file__).resolve().parents[1] / "examples/character_forge_aaa/studio/studio_pack_v3.bin")
v0 = model.neutral()
src = model.body_surface()[0]
region = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])


def scatter(enc):
    """Pack delta over body split vertices -> base vertex array."""
    d = np.zeros((src.size, 3))
    if "dense" in enc:
        d[:] = pack_array(enc["dense"], blob).reshape(-1, 3) * enc["scale"]
    else:
        d[pack_array(enc["idx"], blob)] = pack_array(enc["val"], blob).reshape(-1, 3) * enc["scale"]
    full = np.zeros_like(v0)
    full[src] = d
    return full


blink0 = sum(scatter(e["body"]) for e in man["expressions"])


def compose(values):
    geo, blink = np.zeros_like(v0), blink0.copy()
    for key, val in values.items():
        pe = man["params"][key]
        dv = val - pe["default"]
        side = "hi" if dv > 0 else "lo"
        if abs(dv) < 1e-9 or side not in pe["sides"] or pe.get("mode") == "uniform_scale":
            continue
        w = dv / (pe["sides"][side]["at"] - pe["default"])
        geo += model.control_delta(key, side)[0] * w
        for enc in pe["sides"][side].get("expr", {}).values():
            blink += scatter(enc) * w
    return geo, blink


def measure(v, b):
    o = metrics.eye_exposure_pixels(v)
    return {"closed_exposure": round(metrics.eye_exposure_pixels(v + b) / o, 4), "half_exposure": round(metrics.eye_exposure_pixels(v + 0.5 * b) / o, 3),
            **metrics.tri_quality(v, v + b, region)}


lbs = model.blink_delta(v0, "l", corrected=False) + model.blink_delta(v0, "r", corrected=False)
rep = {"neutral": {"v3_studio_blink": measure(v0, blink0), "makehuman_bone_skinning": measure(v0, lbs)},
       "control_ends_fitted_at_bake": man["blink_fits"], "presets": {}}
for name in ("female", "male"):
    pb, pf, _ = preset(name)
    vals = {k: float(getattr(pb if k.startswith("body.") else pf, k.split(".")[1])) for k in man["params"]}
    geo, b = compose(vals)
    _, b_nocorr = compose({})
    rep["presets"][name] = {"with_correctives": measure(v0 + geo, b), "without_correctives": measure(v0 + geo, blink0)}
print(json.dumps({k: rep[k] for k in ("neutral", "presets")}, indent=1))
(out / "blink_report.json").write_text(json.dumps(rep, indent=1))
