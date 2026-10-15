"""Secondary motion: bone-driven spring-damper particles with constraints, colliders and garment containment.

Model (per physics bone, chains processed root to tip every substep):
  * a particle sits at the bone's tip; its animated target is where the tip
    would be with no secondary rotation;
  * acceleration  a = w^2 (target - p) - 2 zeta w (v - v_target)   (gravity is
    pre-loaded into the rest shape, so only body accelerations excite motion);
  * the tip is kept at bone length (optional stretch), inside a cone of
    ``max_angle`` around the target direction, outside capsule colliders built
    from the animated skeleton (thighs, pelvis, torso), and inside garment
    containment ellipsoids (briefs/bra support) when a garment is worn;
  * the result is converted to a local joint rotation and can be baked into
    glTF animation channels.

This is a real, executed simulation over the character's animated skeleton.
It is not a soft-body/FEM tissue model: the mesh deforms only through the
physics bones' skin weights.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from forge_character_forge.animation import FPS, Clip
from forge_character_forge.rig import forward_kinematics, mat_to_quat, quat_to_mat


@dataclass(frozen=True)
class SpringParams:
    frequency_hz: float = 2.2      # natural frequency (stiffness = (2 pi f)^2)
    damping_ratio: float = 0.25
    max_angle_deg: float = 25.0
    radius: float = 0.03           # particle collision radius (m)

    def __post_init__(self):
        if not (0.2 <= self.frequency_hz <= 30.0 and 0.0 <= self.damping_ratio <= 3.0
                and 0.0 < self.max_angle_deg <= 120.0 and 0.0 <= self.radius <= 0.2):
            raise ValueError(f"SpringParams out of stable range: {self}")


DEFAULTS = {
    "breast": SpringParams(2.4, 0.22, 22.0, 0.035),
    "penis": SpringParams(3.2, 0.30, 40.0, 0.015),
    "testicle": SpringParams(2.6, 0.18, 35.0, 0.018),
    "cloth": SpringParams(1.6, 0.35, 70.0, 0.02),
}


@dataclass
class Chain:
    kind: str
    bones: list
    params: SpringParams
    tips: dict = field(default_factory=dict)  # bone -> rest tip position (world)


@dataclass
class Collider:
    name: str
    a_joint: str
    b_joint: str
    radius: float
    a_off: np.ndarray | None = None
    b_off: np.ndarray | None = None


@dataclass
class Containment:
    """Ellipsoid in a joint's frame that a chain's particles must stay inside (garment support)."""
    name: str
    joint: str
    center: np.ndarray
    radii: np.ndarray
    kinds: tuple
    bones: tuple = ()   # restrict to these bones (empty = every bone of the kinds)
    stiffness_scale: float = 1.0   # garment support raises the effective natural frequency ...
    damping_scale: float = 1.0     # ... and damping (fabric friction / compression)
    angle_scale: float = 1.0       # ... and tightens the motion limit


def default_chains(skel, params: dict | None = None, include_dev: bool = True) -> list[Chain]:
    params = {**DEFAULTS, **(params or {})}
    names = skel.names
    chains = []
    m = skel.marks
    u = m["height"] / 1.75
    for lab in ("l", "r"):
        b = f"breast_{lab}"
        if b in names:
            tip = np.asarray(m.get(f"nipple_{lab}", skel[b] + np.array([0, 0, 0.06 * u])))
            if np.linalg.norm(tip - skel[b]) < 0.02 * u:
                tip = skel[b] + np.array([0, -0.01, 0.06]) * u
            chains.append(Chain("breast", [b], params["breast"], {b: tip}))
    if include_dev and "penis_01" in names:
        tips = {"penis_01": skel["penis_02"], "penis_02": skel["penis_03"], "penis_03": np.asarray(m["penis_tip"])}
        chains.append(Chain("penis", ["penis_01", "penis_02", "penis_03"], params["penis"], tips))
        for lab in ("l", "r"):
            t = f"testicle_{lab}"
            chains.append(Chain("testicle", [t], params["testicle"], {t: skel[t] + np.array([0, -0.022 * u, 0.002 * u])}))
    for side in ("front", "back"):
        bones = [f"cloth_{side}_0{i}" for i in (1, 2, 3)]
        if all(b in names for b in bones):
            tips = {bones[0]: skel[bones[1]], bones[1]: skel[bones[2]],
                    bones[2]: skel[bones[2]] + (skel[bones[2]] - skel[bones[1]]) * 0.6}
            chains.append(Chain("cloth", bones, params["cloth"], tips))
    return chains


def default_colliders(skel) -> list[Collider]:
    u = skel.marks["height"] / 1.75
    out = []
    for lab in ("l", "r"):
        out.append(Collider(f"thigh_{lab}", f"thigh_{lab}", f"calf_{lab}", 0.072 * u))
        out.append(Collider(f"calf_{lab}", f"calf_{lab}", f"foot_{lab}", 0.048 * u))
    out.append(Collider("lower_torso", "pelvis", "spine_02", 0.10 * u, a_off=np.array([0, 0.05, -0.02]) * u,
                        b_off=np.array([0, 0.0, -0.02]) * u))
    return out


SUPPORT = {  # garment -> (kinds, stiffness, damping, angle, allowance m)
    "bra": (("breast",), 1.9, 2.2, 0.45, 0.010),
    "tshirt": (("breast",), 1.15, 1.35, 0.85, 0.025),
    "robe": (("breast",), 1.1, 1.3, 0.9, 0.03),
    "briefs": (("penis", "testicle"), 1.7, 2.0, 0.45, 0.008),
    "shorts": (("penis", "testicle"), 1.3, 1.5, 0.7, 0.015),
    "pants": (("penis", "testicle"), 1.3, 1.5, 0.7, 0.015),
}


def garment_containment(skel, outfit, chains: list | None = None) -> list[Containment]:
    """Support volumes for worn garments, centered on the supported chains' rest tips."""
    chains = default_chains(skel) if chains is None else chains
    u = skel.marks["height"] / 1.75
    best = {}
    for g in outfit:
        if g not in SUPPORT:
            continue
        kinds, ks, kd, ka, allow = SUPPORT[g]
        for kind in kinds:  # the most supportive garment wins per kind
            if kind not in best or ks > best[kind][1]:
                best[kind] = (g, ks, kd, ka, allow)
    out = []
    for ch in chains:
        if ch.kind not in best:
            continue
        g, ks, kd, ka, allow = best[ch.kind]
        for bone in ch.bones:
            joint = "spine_03" if ch.kind == "breast" else "pelvis"
            tip = np.asarray(ch.tips[bone])
            r = np.array([1.0, 1.0, 0.8]) * (allow * u + 0.004 * u)
            out.append(Containment(f"{g}_support_{bone}", joint, tip - skel[joint], r, (ch.kind,), (bone,), ks, kd, ka))
    return out


def _rot_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -0.999999:
        axis = np.cross(a, [1, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def _closest_on_segment(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
    return a + t * ab


@dataclass
class SimResult:
    rotations: dict                  # bone -> (T, 4) local quaternions (secondary only)
    tip_offsets: dict                # bone -> (T,) distance of simulated tip from animated target (m)
    angles_deg: dict                 # bone -> (T,) angular deviation
    max_penetration: float           # deepest collider penetration after constraints (m)
    raw_max_penetration: float       # deepest penetration before collision resolution (m)
    containment_violations: int
    stable: bool
    params: dict


def simulate(skel, c: Clip, chains: list[Chain], colliders: list[Collider] | None = None,
             containment: list[Containment] | None = None, substeps: int = 8, collide: bool = True,
             warmup_frames: int = 30, gravity_kick: float = 0.0) -> SimResult:
    colliders = default_colliders(skel) if colliders is None else colliders
    containment = containment or []
    T = len(c.times)
    dt = 1.0 / FPS / substeps
    names = skel.names
    rest = skel.rest

    def anim_frame(f):
        f = min(max(f, 0), T - 1)
        pose = {j: q[f] for j, q in c.rotations.items()}
        return forward_kinematics(skel, pose, local_trans={"pelvis": c.root_translation[f]})

    frames = [anim_frame(f) for f in range(T)]

    def lerp_G(fr: float):
        i = int(math.floor(fr))
        t = fr - i
        A = frames[min(max(i, 0), T - 1)]
        B = frames[min(max(i + 1, 0), T - 1)]
        return A * (1 - t) + B * t  # matrices blended (fine for small dt; only used for targets)

    state = {}
    for ch in chains:
        for b in ch.bones:
            tip = ch.tips[b]
            G = frames[0]
            j = names.index(b)
            p = G[j, :3, :3] @ (tip - rest[j]) + G[j, :3, 3]
            state[b] = [p.copy(), np.zeros(3)]
    out_rot = {b: np.zeros((T, 4)) for ch in chains for b in ch.bones}
    off = {b: np.zeros(T) for b in out_rot}
    angs = {b: np.zeros(T) for b in out_rot}
    max_pen = 0.0
    raw_pen = 0.0
    viol = 0
    prev_target = {}
    stable = True
    total_steps = (T + warmup_frames) * substeps
    for step in range(total_steps):
        fr = max(0.0, (step - warmup_frames * substeps) / substeps)
        G = lerp_G(fr)
        local_override = {}
        for ch in chains:
            Gc = G.copy()
            for b in ch.bones:
                sup = [c for c in containment if ch.kind in c.kinds and (not c.bones or b in c.bones)]
                w = 2 * math.pi * ch.params.frequency_hz * math.prod(c.stiffness_scale for c in sup)
                z = ch.params.damping_ratio * math.prod(c.damping_scale for c in sup)
                max_ang = math.radians(ch.params.max_angle_deg * math.prod(c.angle_scale for c in sup))
                j = names.index(b)
                pj = skel.parents[j]
                # world transform of this bone with secondary rotations of earlier chain bones applied
                Gp = Gc[pj]
                Lj = np.eye(4)
                Lj[:3, 3] = rest[j] - rest[pj]
                Gj = Gp @ Lj
                joint = Gj[:3, 3]
                tip_local = ch.tips[b] - rest[j]
                target = Gj[:3, :3] @ tip_local + joint
                key = (b,)
                vt = (target - prev_target.get(key, target)) / dt
                prev_target[key] = target
                p_old, v = state[b]
                p = p_old
                if gravity_kick and step == 0:
                    v = v + np.array([0, -gravity_kick, 0])
                acc = w * w * (target - p) - 2 * z * w * (v - vt)
                v = v + acc * dt
                p = p_old + v * dt
                L = np.linalg.norm(tip_local)
                d = p - joint
                dn = np.linalg.norm(d)
                d = d / max(dn, 1e-12)
                tdir = (target - joint) / L
                p_new = joint + d * L
                for _it in range(3):
                    d = (p_new - joint) / np.linalg.norm(p_new - joint)
                    ang = math.acos(float(np.clip(np.dot(d, tdir), -1, 1)))
                    if ang > max_ang:  # cone limit: rotate back toward the target direction
                        axis = np.cross(tdir, d)
                        an = np.linalg.norm(axis)
                        if an > 1e-9:
                            axis /= an
                            d = _axis_angle(axis, max_ang) @ tdir
                    p_new = joint + d * L
                    if not collide:
                        break
                    hit = False
                    for col in colliders:
                        if ch.kind == "breast" and col.name == "lower_torso":
                            continue
                        a, bb = _collider_points(col, G, names)
                        q = _closest_on_segment(p_new, a, bb)
                        dd = p_new - q
                        dist = np.linalg.norm(dd)
                        need = col.radius + ch.params.radius
                        if dist < need:
                            hit = True
                            raw_pen = max(raw_pen, need - dist)
                            n = dd / dist if dist > 1e-9 else np.array([0, 0, 1.0])
                            p_new = q + n * need
                            dnew = p_new - joint
                            p_new = joint + dnew / np.linalg.norm(dnew) * L
                    if not hit:
                        break
                contained = False
                for box in containment:
                    if ch.kind not in box.kinds or (box.bones and b not in box.bones):
                        continue
                    Gb = G[names.index(box.joint)]
                    cw = Gb[:3, :3] @ box.center + Gb[:3, 3]
                    loc = Gb[:3, :3].T @ (p_new - cw)
                    s = np.linalg.norm(loc / box.radii)
                    if s > 1.0:
                        viol += 1
                        loc /= s
                        p_new = Gb[:3, :3] @ loc + cw
                        dnew = p_new - joint
                        p_new = joint + dnew / np.linalg.norm(dnew) * L
                        contained = True
                v = (p_new - p_old) / dt
                if contained:
                    v = v * 0.5
                if not np.all(np.isfinite(p_new)) or np.linalg.norm(v) > 50:
                    stable = False
                state[b] = [p_new, v]
                # local rotation that turns the target direction into the simulated direction
                Rw = _rot_between(target - joint, p_new - joint)
                Rp = Gj[:3, :3]
                Rl = Rp.T @ Rw @ Rp
                Lrot = np.eye(4)
                Lrot[:3, :3] = Rl
                Gc[j] = Gj @ Lrot
                if step >= warmup_frames * substeps and (step - warmup_frames * substeps) % substeps == substeps - 1:
                    f = (step - warmup_frames * substeps) // substeps
                    out_rot[b][f] = mat_to_quat(Rl)
                    off[b][f] = np.linalg.norm(p_new - target)
                    angs[b][f] = math.degrees(math.acos(float(np.clip(np.dot(
                        (p_new - joint) / L, (target - joint) / L), -1, 1))))
            # penetration audit after resolution
            if collide:
                for b in ch.bones:
                    p = state[b][0]
                    for col in colliders:
                        if ch.kind == "breast" and col.name == "lower_torso":
                            continue
                        a, bb = _collider_points(col, G, names)
                        q = _closest_on_segment(p, a, bb)
                        max_pen = max(max_pen, col.radius + ch.params.radius - np.linalg.norm(p - q))
    params = {ch.kind: asdict(ch.params) for ch in chains}
    return SimResult(out_rot, off, angs, max(0.0, max_pen), raw_pen, viol, stable, params)


def _collider_points(col, G, names):
    ia, ib = names.index(col.a_joint), names.index(col.b_joint)
    a, b = G[ia, :3, 3], G[ib, :3, 3]
    if col.a_off is not None:
        a = a + G[ia, :3, :3] @ col.a_off
    if col.b_off is not None:
        b = b + G[ib, :3, :3] @ col.b_off
    return a, b


def amplitude(sim: "SimResult", bone: str) -> float:
    """Dynamic amplitude: peak-to-peak of the tip's deviation from its animated target (m)."""
    o = sim.tip_offsets[bone]
    return float(o.max() - o.min())


def _axis_angle(axis, ang):
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def bake(c: Clip, sim: SimResult, name: str | None = None) -> Clip:
    """Return a copy of the clip with simulated secondary rotations added as channels."""
    rot = dict(c.rotations)
    for b, q in sim.rotations.items():
        rot[b] = q
    return Clip(name or f"{c.name}_secondary", c.times, rot, c.root_translation, c.loop)
