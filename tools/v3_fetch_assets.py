"""Assemble the generator v3 CC0 asset set: copy from the approved experiment, fetch the missing MakeHuman targets.

Only CC0 data files from the official makehumancommunity/makehuman repository; no MakeHuman/MPFB code.
Every target must carry the CC0 header; sha256 and source URL are recorded in v3/assets/PROVENANCE.json.
Usage: python3 tools/v3_fetch_assets.py [--offline]
"""
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.v3.controls import required_targets  # noqa: E402

SRC = "https://raw.githubusercontent.com/makehumancommunity/makehuman/master/makehuman/data/"
EXP = ROOT / "experiments/makehuman_visual_proof"
DST = ROOT / "forge_character_forge/v3/assets"
FILES = ["3dobjs/base.obj", "eyes/high-poly/high-poly.obj", "eyes/high-poly/high-poly.mhclo", "rigs/default.mhskel",
         "rigs/default_weights.mhw", "poseunits/face-poseunits.bvh", "poseunits/face-poseunits.json"]


def main():
    rels = FILES + [f"targets/{t}" for t in required_targets()]
    prov = []
    for rel in rels:
        dst = DST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        exp = EXP / "assets/data" / rel
        origin = "copied from experiments/makehuman_visual_proof (same source URL)"
        if not dst.exists():
            if exp.exists():
                shutil.copyfile(exp, dst)
            elif "--offline" in sys.argv:
                raise SystemExit(f"missing {rel}")
            else:
                for k in range(4):
                    try:
                        dst.write_bytes(urllib.request.urlopen(SRC + rel, timeout=60).read())
                        break
                    except Exception as e:  # network retry with backoff
                        if k == 3:
                            raise SystemExit(f"download failed {rel}: {e}")
                        time.sleep(2 ** (k + 1))
                origin = "downloaded"
        data = dst.read_bytes()
        if rel.startswith("targets/") and b"CC0" not in data[:600]:
            raise SystemExit(f"{rel}: no CC0 header, refusing")
        prov.append({"file": rel, "source_url": SRC + rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                     "origin": origin if exp.exists() else "downloaded"})
    for lic in ("makehuman_LICENSE.md", "makehuman_LICENSE.ASSETS.md"):
        shutil.copyfile(EXP / lic, DST / lic)
    (DST / "PROVENANCE.json").write_text(json.dumps({
        "generator": "forge.character-forge v3 (Phase 1)",
        "source": "official repository makehumancommunity/makehuman, branch master (raw.githubusercontent.com)",
        "license": "CC0 1.0 (makehuman_LICENSE.ASSETS.md section C); each target file carries the CC0 header (checked)",
        "code": "no MakeHuman (AGPL-3.0) or MPFB2 (GPL-3.0) code is used; all parsers are Forge code",
        "files": prov}, indent=1))
    print(f"{len(prov)} files, {sum(p['bytes'] for p in prov) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
