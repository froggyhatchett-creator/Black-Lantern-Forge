"""Optional foot locks for the v3 walk and run clips (Operation Stolen Fire E2).

The Python reference of ``studio/footlock.js`` (the studio applies it at export when "Foot locks" is ticked; off by
default, and then nothing changes). Both run the same arithmetic in the same order; ``tools/footlock_parity.mjs``
checks they agree.

Forge's walk and run are in-place loops: the hips stay over the origin and each foot swings forward and back under
them. A foot lock is therefore made in a ground frame that moves backwards at the clip's own stride speed (the
"treadmill belt"), so a game that moves the character forward at ``ground_speed_m_s`` sees the planted foot still:

1. FK of the clip on the character's own rest skeleton (its proportions, its height-scaled hip motion).
2. Stance per foot: the longest cyclic run of frames where the ankle is in the lowest quarter of its height range
   and travels backwards.
3. Belt speed v: the mean over both feet of the ankle's travel across its stance divided by the stance time.
4. Locked span: the middle ``CORE`` of the stance. Plant per foot (Effigy's rule: the source pose at the middle
   of the stance): the ankle's x and z and the foot's world rotation at the mid-stance frame m; the plant point then
   moves back at v (z(k) = z(m) - v (k - m) / fps). Its height is as low as the leg allows: the lower of the sole's
   two support points (heel, toe tip: ``HEEL``, ``TOE``) on the floor, unless that is out of reach somewhere in the
   locked span with the knee bent at least ``MIN_FLEX_DEG``; then the lowest height reachable over the whole span.
   The clips hold the hips too high for full contact in most stances (the source stance foot floats 3-4 cm; a
   rest-height flat foot was tried first and is out of reach everywhere); lowering the hips would change the root
   channel and is outside this experiment.
5. The ankle position blends in and out over ``BLEND`` frames on each side of the locked span (smoothstep), the
   foot's rotation over ``ROT_BLEND`` (the planted foot differs most from the clip in its turn, up to ~45 degrees).
6. Each frame in the window: two-bone IK of thigh > calf puts the ankle at source + (plant - source) * w, the knee
   turning in the source pose's own bend plane (so it keeps its bending direction) and never straighter than
   ``MIN_FLEX_DEG`` (a target further away is pulled in along the hip-ankle line); the foot's world rotation
   blends from the clip's towards the planted one by its own weight (held fixed while locked: no roll).

Derived from Effigy (https://github.com/SifuInTheShell/Effigy, MIT, (c) 2026 SifuInTheShell, read at c62db21):
``steps/_anim.py`` ``_two_bone`` (the knee-angle and swing solve), ``_lock`` (target = source + (target - source) *
w with a smoothstep blend), ``_s``, ``slerp``, ``_between``, ``_turn``; the contact rule follows the shape of
``ui/src/anim/clip.ts`` ``contacts`` (a low, contiguous span of at least three frames), but Effigy's stillness test
(< 15 % of the body height per second) finds no contact in an in-place clip, so stance here is "low and moving
backwards". Effigy's licence text: ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import math

import numpy as np

VERSION = 1
CLIPS = ("walk", "run")
LEGS = (("thigh_l", "calf_l", "foot_l"), ("thigh_r", "calf_r", "foot_r"))
BLEND = 3            # frames of smoothstep blend of the ankle position on each side of a locked span (Effigy's default)
ROT_BLEND = 6        # frames of smoothstep blend of the foot's rotation (longer: the planted foot differs most in turn)
LOW = 0.25           # stance: the ankle in the lowest quarter of its height range
MIN_FLEX_DEG = 5.0   # the knee is never straighter than this (the plant height is chosen reachable with it)
MIN_SPAN = 3         # frames; shorter stances or locked spans are not locked
CORE = 0.6           # the locked span: the middle 60 % of the stance (at least MIN_SPAN frames)
# the sole's support points from the skeleton alone: the heel this far behind the ankle and the toe tip this far beyond
# the ball, in units of the ankle-to-ball distance, on the floor in the rest pose (measured on the v3 neutral body
# mesh: heel 0.39, toe tip 0.44)
HEEL, TOE = 0.40, 0.45
_ID = np.array([0.0, 0.0, 0.0, 1.0])
_EX = np.array([1.0, 0.0, 0.0])


# --- quaternions (x, y, z, w), after Effigy steps/_anim.py ------------------------------------------------------

def _s(t: float) -> float:  # smoothstep
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _unit(v):
    return v / math.sqrt(float(v @ v))


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])


def qinv(q):
    return np.array([-q[0], -q[1], -q[2], q[3]])


def qrot(q, v):
    u = q[:3]
    t = 2 * np.cross(u, v)
    return v + q[3] * t + np.cross(u, t)


def _turn(axis, ang):
    s = math.sin(ang / 2)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, math.cos(ang / 2)])


def _between(u, v):
    """The shortest turn taking unit u to unit v."""
    d = float(u @ v)
    if 1 + d < 1e-8:  # opposite: a half turn about an axis normal to u
        a = np.cross(u, _EX)
        a = a if a @ a > 1e-12 else np.cross(u, np.array([0.0, 1.0, 0.0]))
        return _turn(_unit(a), math.pi)
    c = np.cross(u, v)
    return _unit(np.array([c[0], c[1], c[2], 1 + d]))


def slerp(a, b, t):
    """Shortest-path slerp, normalised; nlerp when the angle is tiny."""
    d = float(a @ b)
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        return _unit(a * (1 - t) + b * t)
    th = math.acos(min(d, 1.0))
    sn = math.sin(th)
    return _unit(a * (math.sin((1 - t) * th) / sn) + b * (math.sin(t * th) / sn))


def two_bone(pw, WU, WL, WB, a, b, c, P, max_reach=None):
    """New local turns of U (thigh), L (calf) and B (foot) putting B's origin at P with B's world turn WB.

    pw: U's parent world turn; WU, WL: the source world turns; a, b, c: the source hip, knee and ankle. The knee
    turns about the source pose's bend axis (u x v), so its bending direction is kept; a straight source knee falls
    back to the thigh's own X axis (Forge's knee hinge). max_reach: the longest hip-ankle distance allowed (default
    Effigy's, just short of straight). Effigy ``_two_bone``. None: nothing to solve."""
    l1, l2 = float(np.linalg.norm(b - a)), float(np.linalg.norm(c - b))
    dist = float(np.linalg.norm(P - a))
    if l1 * l2 < 1e-12 or dist < 1e-12:
        return None
    d = min(max(dist, abs(l1 - l2) + 1e-6), l1 + l2 - 1e-6 if max_reach is None else min(max_reach, l1 + l2 - 1e-6))
    u, v = a - b, c - b
    k = np.cross(u, v)
    if k @ k < 1e-16:
        k = qrot(WU, _EX)
    k = _unit(k)
    th = math.acos(min(max(float(u @ v) / (l1 * l2), -1.0), 1.0))
    th2 = math.acos(min(max((l1 * l1 + l2 * l2 - d * d) / (2 * l1 * l2), -1.0), 1.0))
    K = _turn(k, th2 - th)
    H = _between(_unit(qrot(K, v) + b - a), _unit(P - a))
    nU = qmul(H, WU)
    nL = qmul(H, qmul(K, WL))
    return _unit(qmul(qinv(pw), nU)), _unit(qmul(qinv(nU), nL)), _unit(qmul(qinv(nL), WB))


# --- the clip -------------------------------------------------------------------------------------------------

def fk(parents, rest, rot_f, root_off, pelvis):
    """World turns (J, 4) and positions (J, 3) of one frame. rest: (J, 3) world rest positions; rot_f: {joint index:
    local turn}; root_off: the clip's (height-scaled) pelvis offset. Parents come before children (the studio's
    order)."""
    J = len(parents)
    W, P = np.zeros((J, 4)), np.zeros((J, 3))
    for j in range(J):
        p = parents[j]
        off = rest[j] - (rest[p] if p >= 0 else 0.0)
        if j == pelvis:
            off = off + root_off
        q = rot_f.get(j, _ID)
        if p < 0:
            W[j], P[j] = q, off
        else:
            W[j], P[j] = qmul(W[p], q), P[p] + qrot(W[p], off)
    return W, P


def _longest_cyclic_run(mask):
    """(start, length) of the longest run of True in a cyclic mask (ties: the earliest start); None: no True."""
    F = len(mask)
    if not mask.any():
        return None
    if mask.all():
        return 0, F
    best, s0 = None, int(np.argmin(mask))  # start scanning just after a False so no run is split by the wrap
    run_start, run = None, 0
    for i in range(1, F + 1):
        f = (s0 + i) % F
        if mask[f]:
            if run == 0:
                run_start = f
            run += 1
            if best is None or run > best[1] or (run == best[1] and run_start < best[0]):
                best = (run_start, run)
        else:
            run = 0
    return best


def lock_clip(names, parents, rest, rot, root, fps):
    """Foot-lock one in-place loop. names, parents: the skeleton; rest: (J, 3) world rest positions; rot: {joint
    name: (F, 4) local turns}; root: (F, 3) pelvis offsets as exported (already height-scaled); fps.

    Returns (rot', report): rot' is ``rot`` with the six leg channels replaced (the other channels the same arrays);
    report holds the ground speed, the stance and locked spans and per-frame lock weights, or why nothing was locked.
    """
    rest = np.asarray(rest, float).reshape(-1, 3)
    root = np.asarray(root, float).reshape(-1, 3)
    idx = {n: i for i, n in enumerate(names)}
    F = len(root)
    assert all(parents[j] < j for j in range(len(parents))), "parents must come before children"
    rot_i = {idx[n]: np.asarray(q, float).reshape(F, 4) for n, q in rot.items() if n in idx}
    frames = [fk(parents, rest, {j: q[f] for j, q in rot_i.items()}, root[f], idx["pelvis"]) for f in range(F)]
    report = {"version": VERSION, "fps": fps, "frames": F, "blend": BLEND, "rotation_blend": ROT_BLEND, "feet": {}}
    stances = {}
    for U, L, B in LEGS:
        if not all(n in idx and n in rot for n in (U, L, B)):
            report["feet"][B] = {"locked": None, "reason": "no thigh, calf and foot channels"}
            continue
        A = np.array([P[idx[B]] for _, P in frames])
        h = A[:, 1]
        lo, hi = float(h.min()), float(h.max())
        dz = np.array([A[(f + 1) % F, 2] - A[(f - 1) % F, 2] for f in range(F)])
        st = _longest_cyclic_run((h <= lo + LOW * (hi - lo)) & (dz < 0))
        if st is None or st[1] < MIN_SPAN:
            report["feet"][B] = {"locked": None, "reason": "no stance"}
            continue
        stances[B] = (st, A)
    if not stances:
        return rot, {**report, "ground_speed_m_s": None}
    v = float(np.mean([(A[s % F, 2] - A[(s + n - 1) % F, 2]) / ((n - 1) / fps) for (s, n), A in stances.values()]))
    report["ground_speed_m_s"] = v
    out = {n: np.asarray(q, float).reshape(F, 4).copy() for n, q in rot.items()}
    for U, L, B in LEGS:
        if B not in stances:
            continue
        (s, n), A = stances[B]
        m = s + n // 2
        x0, y0, zm = (float(x) for x in A[m % F])
        Q = frames[m % F][0][idx[B]]
        ball = "ball" + B[4:]
        y_contact = None
        if ball in idx:  # the sole on the floor: the lower support point at y = 0
            ra, fwd = rest[idx[B]], rest[idx[ball]] - rest[idx[B]]
            fwd = np.array([fwd[0], 0.0, fwd[2]])
            pts = (np.array([ra[0], 0.0, ra[2]]) - HEEL * fwd, rest[idx[ball]] * [1, 0, 1] + TOE * fwd)
            y_contact = -min(float(qrot(Q, q - ra)[1]) for q in pts)
        nc = min(n, max(MIN_SPAN, int(round(CORE * n))))
        ls = int(s + (n - nc) // 2)
        le = ls + nc - 1  # unwrapped frame numbers
        l1 = float(np.linalg.norm(rest[idx[L]] - rest[idx[U]]))
        l2 = float(np.linalg.norm(rest[idx[B]] - rest[idx[L]]))
        dmax = math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * math.cos(math.radians(MIN_FLEX_DEG)))
        y_reach = -math.inf
        for k in range(ls, le + 1):
            H = frames[k % F][1][idx[U]]
            dh = math.hypot(x0 - H[0], zm - v * (k - m) / fps - H[2])
            if dh >= dmax:
                y_reach = math.inf
                break
            y_reach = max(y_reach, H[1] - math.sqrt(dmax * dmax - dh * dh) + 1e-6)
        if y_reach == math.inf:
            report["feet"][B] = {"stance": [int(s), int(n)], "locked": None, "reason": "plant out of reach"}
            continue
        y0 = max(y_contact, y_reach) if y_contact is not None else max(y0, y_reach)
        plant = lambda k: np.array([x0, y0, zm - v * (k - m) / fps])  # noqa: E731
        if (le - ls + 1) + 2 * ROT_BLEND > F:
            report["feet"][B] = {"stance": [int(s), int(n)], "locked": None, "reason": "lock window longer than the clip"}
            continue
        weights = {}
        for k in range(ls - ROT_BLEND, le + ROT_BLEND + 1):
            w, wr = _weight(k, ls, le, BLEND), _weight(k, ls, le, ROT_BLEND)
            if w <= 0 and wr <= 0:
                continue
            f = k % F
            W, P = frames[f]
            pw = W[parents[idx[U]]]
            c = P[idx[B]]
            r = two_bone(pw, W[idx[U]], W[idx[L]], slerp(W[idx[B]], Q, wr), P[idx[U]], P[idx[L]], c, c + (plant(k) - c) * w, dmax)
            if r is None:
                continue
            out[U][f], out[L][f], out[B][f] = r
            weights[f] = [w, wr]
        report["feet"][B] = {"stance": [int(s % F), int(n)], "locked": [ls % F, le - ls + 1], "locked_unwrapped_start": ls,
                             "plant": {"frame": int(m % F), "unwrapped_frame": int(m), "x": x0, "y": y0, "z": zm, "rotation": [float(x) for x in Q],
                                       "sole_contact_y": y_contact, "sole_above_floor_m": (y0 - y_contact) if y_contact is not None else None},
                             "weights": {int(f): [float(x) for x in w] for f, w in sorted(weights.items())}}
    return {n: (out[n] if n in out else q) for n, q in rot.items()}, report


def _weight(k, ls, le, blend):
    """1 inside the locked span [ls, le], a smoothstep over ``blend`` frames on each side, 0 beyond."""
    if ls <= k <= le:
        return 1.0
    return _s(1 - (ls - k) / blend) if k < ls else _s(1 - (k - le) / blend)


def summary(reports: dict) -> dict:
    """The record written to ``asset.extras.forge.animation_corrections`` (the same keys as the studio's)."""
    return {"foot_lock": {"version": VERSION, "method": "two-bone IK to a plant point moving at the stride speed; foot held at its mid-stance rotation while locked",
                          "derived_from": "Effigy steps/_anim.py (MIT, c62db21)", "blend_frames": BLEND, "rotation_blend_frames": ROT_BLEND,
                          "clips": {c: {"ground_speed_m_s": r.get("ground_speed_m_s"),
                                        "locked": {f: (d.get("locked")) for f, d in r["feet"].items()}}
                                    for c, r in reports.items()}}}
