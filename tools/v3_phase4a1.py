"""Phase 4A.1 stress matrix: the Phase 4A cases (identities x body presets, eye size at the slider ends 0.8 and 1.25,
identity/control combinations) measured with the Phase 4A.1 metrics, before (Phase 4A: eyelid fit 1, no corner
limits, Phase 4A lashes) and after (eyelid fit 2, corner limits, smoothed and limited lash turn).

usage: python3 tools/v3_phase4a1.py before|after   -> examples/character_forge_aaa/humanity/v3_phase4a1/matrix_<tag>.json
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, lash_contact as LC, model  # noqa: E402
from v3_phase4a import cases, phase_4a  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a1"


def main(tag):
    if tag == "before":
        phase_4a()
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"settings": {"eyelid_fit": E.EYELID_FIT, "no_overtake": model.NO_OVERTAKE, "angle_untangle": model.ANGLE_UNTANGLE,
                        "lash_turn_sigma": LC.TURN_SIGMA}, "cases": {}}
    for name, (ctl, iv) in cases().items():
        t0 = time.time()
        v = E.shape(ctl, iv)
        m = Q.measure(v, E.blink(ctl, iv))
        res["cases"][name] = {"summary": Q.summary(m), "detail": m}
        print(f"{name:48s} {json.dumps(Q.summary(m))} {time.time() - t0:.0f}s", flush=True)
    (OUT / f"matrix_{tag}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
