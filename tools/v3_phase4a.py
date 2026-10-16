"""Phase 4A blink stress matrix: identities x body presets, eye-size extremes and identity/control combinations.

Measures the studio blink (the pack's linear model: neutral blink + summed correctives + preset residual, as
v3/evaluate.py reproduces it) with v3/blink_quality.py at weights 0-1, per eye.
usage: python3 tools/v3_phase4a.py <tag> [--model 1]   -> examples/character_forge_aaa/humanity/v3_phase4a/matrix_<tag>.json
(--model 1 reproduces the Phase 1-3 blink, the "before" of Phase 4A)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forge_character_forge.params import preset  # noqa: E402
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, identity_dna as I  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a"


def body_preset(name):
    b, f, _ = preset(name)
    return {k: float(getattr(b if k.startswith("body.") else f, k.split(".")[1])) for k in E.control_defaults()}


def cases():
    P = I.presets()
    out = {}
    for body in ("female", "male", "neutral"):
        for idn in ("neutral", "ID-A", "ID-B", "MERCY-INSPIRED"):
            out[f"{idn} / {body} body"] = (body_preset(body), P[idn]["values"])
    fem = body_preset("female")
    for idn in ("ID-A", "MERCY-INSPIRED"):
        for es in (0.8, 1.25):  # face.eye_size slider ends
            out[f"{idn} / female body / eye size {es}"] = ({**fem, "face.eye_size": es}, P[idn]["values"])
    out["ID-A / male, head 1.15, jaw 1.3"] = ({**body_preset("female"), "body.femininity": 0.0, "body.head_size": 1.15, "face.jaw_width": 1.3}, P["ID-A"]["values"])
    out["Mercy / small head 0.9, face length 1.2"] = ({**fem, "body.head_size": 0.9, "face.face_length": 1.2}, P["MERCY-INSPIRED"]["values"])
    return out


def main(tag):
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    for name, (ctl, iv) in cases().items():
        t0 = time.time()
        v = E.shape(ctl, iv)
        m = Q.measure(v, E.blink(ctl, iv), lash_contact=E.BLINK_MODEL != 1)  # Phase 1-3 lashes had no contact
        res[name] = {"summary": Q.summary(m), "detail": m}
        print(f"{name:48s} {json.dumps(res[name]['summary'])} {time.time() - t0:.0f}s", flush=True)
    (OUT / f"matrix_{tag}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    if "--model" in sys.argv:
        E.BLINK_MODEL = int(sys.argv[sys.argv.index("--model") + 1])
    main(sys.argv[1])
