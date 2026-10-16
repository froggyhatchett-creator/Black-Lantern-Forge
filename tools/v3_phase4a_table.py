"""Before/after table of the Phase 4A stress matrix (matrix_before.json vs matrix_after.json) -> markdown on stdout."""
import json
import sys
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "examples/character_forge_aaa/humanity/v3_phase4a"
b, a = (json.loads((D / f"matrix_{t}.json").read_text()) for t in ("before", "after"))
rows = ["| Case | Folded lid triangles, closed (visible + hidden lining) | Visible folds, worst weight (per eye) | "
        "Eyeball exposure closed | Lid inside eye, worst mid-blink (mm) | Lash strands through skin, worst weight | "
        "Smoothness p99 | L/R exposure diff |", "|" + "---|" * 8]
tot = [0, 0, 0, 0]
for n in b:
    x, y = b[n]["summary"], a[n]["summary"]
    tot = [tot[0] + x["folds_total_closed"], tot[1] + y["folds_total_closed"], tot[2] + x["folds_visible_closed"], tot[3] + y["folds_visible_closed"]]
    rows.append(f"| {n} | {x['folds_visible_closed']} + {x['folds_hidden_closed']} → **{y['folds_visible_closed']} + {y['folds_hidden_closed']}** | "
                f"{x['folds_visible_max']} → **{y['folds_visible_max']}** | {x['exposure_closed_max']:.4f} → {y['exposure_closed_max']:.4f} | "
                f"{x['lid_in_eye_max_mm']:.2f} → **{y['lid_in_eye_max_mm']:.2f}** | {x['lash_penetrating_max']} → **{y['lash_penetrating_max']}** | "
                f"{x['smooth_p99_ratio_max']:.2f} → {y['smooth_p99_ratio_max']:.2f} | {x['symmetry_exposure_diff_max']:.4f} → {y['symmetry_exposure_diff_max']:.4f} |")
rows.append(f"| **All 18 cases** | **{tot[0]} → {tot[1]}** (visible {tot[2]} → {tot[3]}) | | | | | | |")
print("\n".join(rows))
