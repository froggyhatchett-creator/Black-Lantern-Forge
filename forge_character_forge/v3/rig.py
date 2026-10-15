"""Generator v3 compatibility skeleton: 163 MakeHuman bones -> 62 Forge joints.

Limits: the studio renderer skins with 80 joint matrices, the export contract allows 64 joints. v3 uses the Forge joint
names (so clips, poses, physics and humanoid tags work by name) without the six ``cloth_*`` joints (v2 garments are
not used on v3) plus four eyelid joints: 62 joints.

Every MakeHuman bone maps to exactly one Forge joint (``BONE_MAP``, resolved by the explicit rules below; tests check
that all 163 resolve and that no rule is ambiguous). Bones merged into a joint give it their skin weights, so poses that
only drive Forge joints deform exactly as MakeHuman's skinning would; what is lost is independent motion of the merged
bones (twist bones, metacarpals, toes, face muscles, tongue), reported in ``merge_report()``. Nothing is truncated:
per-vertex influences are the merged weights' top four, renormalised, with the dropped mass reported.

Joint positions: the head of the primary bone (pelvis: the pelvis.L head, centred; spine_01: spine04, so the pelvis
pivots at the hips, not behind the sacrum where MakeHuman's root sits); ball = mean of the five toe heads; breast = 6 cm
behind the breast bone's tip (MakeHuman's breast bones start at the spine). Joint rest orientations are identity (axis-aligned, like v1/v2), so the existing clips apply unchanged.
"""

from __future__ import annotations

import re

import numpy as np

from forge_character_forge.v3 import mh

# Forge joint -> (parent, primary MakeHuman bone whose head is the joint position, or a special rule)
JOINTS: list[tuple[str, str | None, str]] = [
    ("root", None, "@origin"), ("pelvis", "root", "pelvis.L"), ("spine_01", "pelvis", "spine04"),
    ("spine_02", "spine_01", "spine03"), ("spine_03", "spine_02", "spine02"), ("neck_01", "spine_03", "neck01"),
    ("head", "neck_01", "head"), ("jaw", "head", "jaw"), ("eye_l", "head", "eye.L"), ("eye_r", "head", "eye.R"),
    ("lid_upper_l", "head", "orbicularis03.L"), ("lid_lower_l", "head", "orbicularis04.L"),
    ("lid_upper_r", "head", "orbicularis03.R"), ("lid_lower_r", "head", "orbicularis04.R"),
]
_FINGERS = {"thumb": 1, "index": 2, "middle": 3, "ring": 4, "pinky": 5}
for _s, _S in (("l", "L"), ("r", "R")):
    JOINTS += [(f"clavicle_{_s}", "spine_03", f"clavicle.{_S}"), (f"upperarm_{_s}", f"clavicle_{_s}", f"upperarm01.{_S}"),
               (f"lowerarm_{_s}", f"upperarm_{_s}", f"lowerarm01.{_S}"), (f"hand_{_s}", f"lowerarm_{_s}", f"wrist.{_S}")]
    for _f, _k in _FINGERS.items():
        for _i in (1, 2, 3):
            JOINTS.append((f"{_f}_0{_i}_{_s}", f"hand_{_s}" if _i == 1 else f"{_f}_0{_i - 1}_{_s}", f"finger{_k}-{_i}.{_S}"))
    JOINTS += [(f"thigh_{_s}", "pelvis", f"upperleg01.{_S}"), (f"calf_{_s}", f"thigh_{_s}", f"lowerleg01.{_S}"),
               (f"foot_{_s}", f"calf_{_s}", f"foot.{_S}"), (f"ball_{_s}", f"foot_{_s}", f"@toes.{_S}"),
               (f"breast_{_s}", "spine_03", f"@breast.{_S}")]
NAMES = [j[0] for j in JOINTS]
PARENTS = [NAMES.index(p) if p else -1 for _, p, _ in JOINTS]

# explicit rules, first match wins; tests assert each bone matches exactly one rule
RULES: list[tuple[str, str]] = [
    (r"root|pelvis\.(L|R)", "pelvis"), (r"spine0[45]", "spine_01"), (r"spine03", "spine_02"), (r"spine0[12]", "spine_03"),
    (r"neck0[123]", "neck_01"), (r"head", "head"), (r"eye\.(L|R)", "eye_{s}"),
    (r"orbicularis03\.(L|R)", "lid_upper_{s}"), (r"orbicularis04\.(L|R)", "lid_lower_{s}"),
    (r"(clavicle|shoulder01)\.(L|R)", "clavicle_{s}"), (r"upperarm0[12]\.(L|R)", "upperarm_{s}"),
    (r"lowerarm0[12]\.(L|R)", "lowerarm_{s}"), (r"(wrist|metacarpal[1-4])\.(L|R)", "hand_{s}"),
    (r"finger1-([123])\.(L|R)", "thumb_0{i}_{s}"), (r"finger2-([123])\.(L|R)", "index_0{i}_{s}"),
    (r"finger3-([123])\.(L|R)", "middle_0{i}_{s}"), (r"finger4-([123])\.(L|R)", "ring_0{i}_{s}"),
    (r"finger5-([123])\.(L|R)", "pinky_0{i}_{s}"), (r"upperleg0[12]\.(L|R)", "thigh_{s}"),
    (r"lowerleg0[12]\.(L|R)", "calf_{s}"), (r"foot\.(L|R)", "foot_{s}"), (r"toe[1-5]-[123]\.(L|R)", "ball_{s}"),
    (r"breast\.(L|R)", "breast_{s}"),
    (r"@jaw-descendant", "jaw"),  # jaw, lower lip, tongue and chin bones: every bone whose ancestry reaches "jaw"
    (r"@head-descendant", "head"),  # remaining face muscles (brows, upper lip, cheeks, nose, lids' helpers)
]


def _ancestors(bone: str, bones: dict) -> list[str]:
    out = []
    while bones[bone]["parent"]:
        bone = bones[bone]["parent"]
        out.append(bone)
    return out


def matching_rules(bone: str) -> list[str]:
    """All rules a bone matches (resolved joint names); the first is used."""
    bones, _ = mh.skeleton()
    hits = []
    for pat, joint in RULES:
        if pat.startswith("@"):
            anc = [bone] + _ancestors(bone, bones)
            if (pat == "@jaw-descendant" and "jaw" in anc) or (pat == "@head-descendant" and "head" in anc[1:]):
                hits.append(joint)
            continue
        m = re.fullmatch(pat, bone)
        if m:
            side = bone[-1].lower() if bone[-2:] in (".L", ".R") else ""
            num = next((g for g in m.groups() if g and g.isdigit()), "")
            hits.append(joint.format(s=side, i=num))
    return hits


def bone_map() -> dict[str, str]:
    bones, _ = mh.skeleton()
    out = {}
    for b in bones:
        hits = matching_rules(b)
        if not hits:
            raise ValueError(f"MakeHuman bone {b} has no Forge joint")
        out[b] = hits[0]
    return out


def joint_rest(verts: np.ndarray) -> np.ndarray:
    """(62,3) joint positions on a (morphed) base: the head of each joint's primary MakeHuman bone."""
    jp = mh.joint_positions(verts)
    out = np.zeros((len(JOINTS), 3))
    for k, (_, _, src) in enumerate(JOINTS):
        if src == "@origin":
            continue
        if src.startswith("@breast."):  # MakeHuman's breast bone starts at the spine: pivot 6 cm behind its tip
            bones, _ = mh.skeleton()
            tip, h = jp[bones[src[1:]]["tail"]], mh.bone_head(src[1:], jp)
            out[k] = tip + (h - tip) / np.linalg.norm(h - tip) * 0.06
        elif src.startswith("@toes."):
            out[k] = np.mean([mh.bone_head(f"toe{t}-1.{src[-1]}", jp) for t in range(1, 6)], 0)
        else:
            out[k] = mh.bone_head(src, jp)
    return out


def skin(n_verts: int):
    """Per-vertex top-4 Forge joints and weights for the base mesh (vertex ids of base.obj)."""
    bm = bone_map()
    W = np.zeros((n_verts, len(NAMES)))
    for bone, pairs in mh.skin_weights().items():
        p = np.asarray(pairs, float)
        np.add.at(W, (p[:, 0].astype(np.int64), NAMES.index(bm[bone])), p[:, 1])
    total = W.sum(1)
    order = np.argsort(-W, 1)[:, :4]
    w4 = np.take_along_axis(W, order, 1)
    kept = w4.sum(1)
    unweighted = total <= 1e-9
    w4[unweighted] = [1, 0, 0, 0]
    order[unweighted] = NAMES.index("pelvis")
    w4 /= w4.sum(1, keepdims=True)
    dropped = np.where(total > 1e-9, 1 - kept / np.maximum(total, 1e-9), 0)
    return order, w4, {"unweighted_vertices": int(unweighted.sum()), "max_dropped_weight": float(dropped.max()),
                       "mean_dropped_weight": float(dropped.mean()), "raw_weight_sum_range": [float(total[~unweighted].min()), float(total.max())]}


def merge_report() -> dict:
    bm = bone_map()
    weighted = set(mh.skin_weights())
    merged: dict[str, list[str]] = {}
    for b, j in bm.items():
        merged.setdefault(j, []).append(b)
    return {"makehuman_bones": len(bm), "forge_joints": len(NAMES), "bones_with_weights": len(weighted),
            "merged": {j: sorted(bs) for j, bs in merged.items() if len(bs) > 1},
            "joints_without_bone_weights": [j for j in NAMES if not any(b in weighted for b in merged.get(j, []))]}
