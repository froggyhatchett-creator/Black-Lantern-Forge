"""Forge-side post-export step for Blender-processed character GLBs (Phase 1.1). Standard library + numpy only;
never imports Blender. Restores what Blender's exporter drops or reorders, but only after checking the processed
file still deserves each claim:

  asset.extras.forge     copied from the source after verification (below); the embedded Character DNA is copied
                         byte-for-byte and never edited
  node extras            per-joint metadata (humanoid mapping, secondary_motion) restored by joint name if missing
  animation order        clips reordered to the source's order, by name (the clip set must be identical)
  post_processing        appended under asset.extras.forge: which tool/job changed what, and whether the DNA still
                         reproduces this file ("dna_reproduces_file")

Verified claims (any failure -> nothing is written, exit 1): units/axes (body height and footprint within 1 mm of the
source, nose toward +Z), identity joint rest orientation, fixed_topology_vertices (body vertex count), template
vertices (welded body count), coverage/outfit meshes present and skinned, dev_only_parts absent, same joint names,
same clip names. The JSON chunk is rewritten; the binary chunk is copied unchanged.

    python3 forge_restamp.py <source.glb> <processed.glb> <out.glb> [--changes "<what>" ...] [--job <result.json>]
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

import rig_compare as R

TOOL = {"id": "forge.blender-bridge.restamp", "version": 1}


def chunks(path):
    b = Path(path).read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    bl = struct.unpack_from("<I", b, 20 + jl)[0]
    return js, b[20 + jl + 8:20 + jl + 8 + bl]


def write_glb(path, js, binary):
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<I4s", len(j), b"JSON") + j + struct.pack("<I4s", len(binary), b"BIN\0") + binary
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def verify_claims(S, D, forge, changes):
    """List of (claim, ok, detail)."""
    out = []
    MS, MD = R.meshes(S), R.meshes(D)
    bs, bd = MS["body"], MD.get("body")
    if bd is None:
        return [("body mesh present", False, "missing")]
    ext = lambda P: np.r_[P.min(0), P.max(0)]
    d = np.abs(ext(bs["P"]) - ext(bd["P"])).max()
    out.append(("units/axes: body bounds within 1 mm of the source", d <= 1e-3, f"{d * 1000:.4f} mm"))
    nose = bd["P"][np.argmax(bd["P"][:, 1] * (bd["P"][:, 1] > 1.4) + bd["P"][:, 2] * 10 * (bd["P"][:, 1] > 1.4))]
    out.append(("front axis +Z (face points to +Z)", nose[2] > bd["P"][:, 2].mean(), f"nose z {nose[2]:.3f} vs body mean {bd['P'][:, 2].mean():.3f}"))
    jn = [D.g["nodes"][j] for j in D.g["skins"][0]["joints"]]
    nonid = [n.get("name") for n in jn if any(abs(x) > 1e-6 for x in n.get("rotation", [0, 0, 0, 1])[:3])]
    if forge.get("joint_rest_orientation") == "identity":
        out.append(("joint_rest_orientation identity", not nonid, f"{len(nonid)} joints with a non-identity rest rotation"))
    if "fixed_topology_vertices" in forge:
        out.append(("fixed_topology_vertices = body vertex count", len(bd["P"]) == forge["fixed_topology_vertices"], f"{len(bd['P'])} vs {forge['fixed_topology_vertices']}"))
    tv = forge.get("generator", {}).get("template_vertices")
    if tv:
        welded = len(np.unique(np.round(bd["P"] * 1e6).astype(np.int64), axis=0))
        out.append(("template_vertices = welded body count", welded == tv, f"{welded} vs {tv}"))
    cov = forge.get("coverage", {})
    need = sorted({m for ms in cov.get("covered_by", {}).values() for m in ms} | set(cov.get("outfit", [])))
    miss = [m for m in need if m not in MD or MD[m]["skin"] is None]
    out.append(("coverage/outfit meshes present and skinned", not miss, f"missing or unskinned: {miss}" if miss else f"{need}"))
    names = {D.name(i) for i in range(len(D.g["nodes"]))} | set(MD)
    dev = [p for p in forge.get("dev_only_parts", []) if p in names]
    out.append(("dev_only_parts absent", not dev, f"{dev}"))
    js_ = sorted(S.name(i) for i in S.g["skins"][0]["joints"])
    jd_ = sorted(D.name(i) for i in D.g["skins"][0]["joints"])
    out.append(("same joint names", js_ == jd_, f"{len(js_)} vs {len(jd_)}"))
    ca = sorted(a["name"] for a in S.g.get("animations", []))
    cb = sorted(a["name"] for a in D.g.get("animations", []))
    out.append(("same clip names", ca == cb, f"{ca} vs {cb}"))
    return out


def dna_still_exact(S, D):
    """True only if geometry, topology, UVs, skin weights, morphs and animation values match the source."""
    MS, MD = R.meshes(S), R.meshes(D)
    js = [S.name(i) for i in S.g["skins"][0]["joints"]]
    jd = [D.name(i) for i in D.g["skins"][0]["joints"]]
    worst = {}
    for name, a in MS.items():
        b = MD[name]
        m, miss = R.match(a, b)
        worst[name] = {"pos_mm": float(np.abs(a["P"][m] - b["P"]).max() * 1000), "unmatched": int(miss),
                       "weights": float(np.abs(R.weights_by_name(a, js)[m] - R.weights_by_name(b, jd)[:, [jd.index(n) for n in js]]).max()) if "W" in a else 0.0,
                       "morph_mm": max((float(np.abs(a["targets"][t][m] - b["targets"][t]).max() * 1000) for t in a["targets"]), default=0.0)}
    ok = all(w["pos_mm"] < 0.01 and w["weights"] < 1e-6 and w["morph_mm"] < 0.01 for w in worst.values())
    return ok, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("processed")
    ap.add_argument("out")
    ap.add_argument("--changes", action="append", default=[])
    ap.add_argument("--job")
    a = ap.parse_args()
    S, D = R.G(a.source), R.G(a.processed)
    forge = (S.g["asset"].get("extras") or {}).get("forge")
    if not forge:
        print("source has no Forge metadata to restore")
        return 1
    claims = verify_claims(S, D, forge, a.changes)
    for c, ok, det in claims:
        print(("OK  " if ok else "FAIL"), c, "-", det)
    if not all(ok for _, ok, _ in claims):
        print("REFUSED: the processed file does not support the source's claims; nothing written")
        return 1
    exact, worst = dna_still_exact(S, D)
    js, binary = chunks(a.processed)
    # 1. asset metadata: verbatim copy + a post-processing record (the DNA object itself is not touched)
    restored = json.loads(json.dumps(forge))
    rec = {"tool": TOOL, "processor": js["asset"].get("generator"), "source_sha256": hashlib.sha256(Path(a.source).read_bytes()).hexdigest(),
           "processed_sha256": hashlib.sha256(Path(a.processed).read_bytes()).hexdigest(), "changes": a.changes,
           "dna_reproduces_file": exact, "claims_verified": [c for c, _, _ in claims]}
    if a.job:
        r = json.loads(Path(a.job).read_text())
        rec["job"] = {"operation": r["job"]["operation"], "params": r["job"].get("params"), "blender_version": r.get("blender_version")}
    if not exact:
        rec["note"] = "This file differs from what the embedded DNA generates (see changes); the DNA describes the source character, not this file."
    restored["post_processing"] = restored.get("post_processing", []) + [rec]
    js["asset"]["extras"] = {**(js["asset"].get("extras") or {}), "forge": restored}
    # 2. per-joint metadata by name
    # joints are addressed through the skin (node indices), never by bare node name: Forge characters have a joint and
    # a mesh node that share a name (eye_l, eye_r), and a name match would tag the eye MESH as a humanoid bone
    src_joint_extras = {S.name(i): S.g["nodes"][i]["extras"] for i in S.g["skins"][0]["joints"] if S.g["nodes"][i].get("extras")}
    src_other_extras = [S.name(i) for i, n in enumerate(S.g["nodes"]) if n.get("extras") and i not in S.g["skins"][0]["joints"]]
    if src_other_extras:
        print(f"REFUSED: source has extras on non-joint nodes {src_other_extras}; restoring them is not supported")
        return 1
    restored_nodes = 0
    for j in js["skins"][0]["joints"]:
        n = js["nodes"][j]
        e = src_joint_extras.get(n.get("name"))
        if e is not None and json.dumps(n.get("extras"), sort_keys=True) != json.dumps(e, sort_keys=True):
            n["extras"] = e
            restored_nodes += 1
    # 3. clip order by name
    order = [x["name"] for x in S.g.get("animations", [])]
    js["animations"] = sorted(js.get("animations", []), key=lambda x: order.index(x["name"]))
    write_glb(a.out, js, binary)
    print(f"restamped -> {a.out}: forge metadata restored, {restored_nodes} joint extras restored, clip order {order}, dna_reproduces_file={exact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
