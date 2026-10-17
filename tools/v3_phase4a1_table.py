"""Markdown before/after table of the Phase 4A.1 stress matrix (matrix_before.json = Phase 4A, matrix_after.json)."""
import json
import sys
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "examples/character_forge_aaa/humanity/v3_phase4a1"


def main():
    b = json.loads((D / "matrix_before.json").read_text())["cases"]
    a = json.loads((D / "matrix_after.json").read_text())["cases"]
    cols = ["Case", "Eyeball through open lid (vertices / deepest mm)", "Folded lid triangles closed (visible + hidden)",
            "Visible folds, worst weight (per eye)", "Exposure closed", "Lid inside eye mid-blink (mm)",
            "Lash strands through skin, worst weight", "Closed lash scatter p95 (deg)", "Upright closed upper lashes", "Smoothness p99"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    tot = {"bf": 0, "af": 0, "bv": 0, "av": 0, "bo": 0, "ao": 0}
    for name in b:
        x, y = b[name]["summary"], a[name]["summary"]
        tot["bf"] += x["folds_total_closed"]; tot["af"] += y["folds_total_closed"]
        tot["bv"] += x["folds_visible_closed"]; tot["av"] += y["folds_visible_closed"]
        tot["bo"] += x["open_skin_in_eye_vertices"]; tot["ao"] += y["open_skin_in_eye_vertices"]
        row = [name,
               f"{x['open_skin_in_eye_vertices']} / {x['open_skin_in_eye_max_mm']:.2f} → **{y['open_skin_in_eye_vertices']} / {y['open_skin_in_eye_max_mm']:.2f}**",
               f"{x['folds_visible_closed']} + {x['folds_hidden_closed']} → **{y['folds_visible_closed']} + {y['folds_hidden_closed']}**",
               f"{x['folds_visible_max']} → **{y['folds_visible_max']}**",
               f"{x['exposure_closed_max']:.4f} → {y['exposure_closed_max']:.4f}",
               f"{x['lid_in_eye_max_mm']:.2f} → **{y['lid_in_eye_max_mm']:.2f}**",
               f"{x['lash_penetrating_max']} → **{y['lash_penetrating_max']}**",
               f"{x['lash_scatter_p95_deg']:.1f} → **{y['lash_scatter_p95_deg']:.1f}**",
               f"{x['lash_upright_closed']} → {y['lash_upright_closed']}",
               f"{x['smooth_p99_ratio_max']:.2f} → {y['smooth_p99_ratio_max']:.2f}"]
        print("| " + " | ".join(row) + " |")
    print(f"| **All {len(b)} cases** | {tot['bo']} → **{tot['ao']}** vertices | {tot['bf']} → **{tot['af']}** (visible {tot['bv']} → {tot['av']}) |"
          + " |" * (len(cols) - 3))


if __name__ == "__main__":
    sys.exit(main())
