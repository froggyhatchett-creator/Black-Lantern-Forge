// Optional foot locks for the v3 walk and run clips (Operation Stolen Fire E2): the browser twin of
// forge_character_forge/v3/footlock.py (same steps, same order; tools/footlock_parity.mjs checks they agree).
// Derived from Effigy steps/_anim.py (MIT, (c) 2026 SifuInTheShell, c62db21): the two-bone solve, the smoothstep
// blend towards a lock target, slerp, shortest turn. The method and its reasons are in footlock.py and
// docs/STOLEN_FIRE_E2.md. No DOM, no three.js: pure functions over the studio's skeleton and clip arrays.

export const VERSION = 1;
export const CLIPS = ["walk", "run"];
export const LEGS = [["thigh_l", "calf_l", "foot_l"], ["thigh_r", "calf_r", "foot_r"]];
export const BLEND = 3, ROT_BLEND = 6, LOW = 0.25, MIN_FLEX_DEG = 5.0, MIN_SPAN = 3, CORE = 0.6;
export const HEEL = 0.40, TOE = 0.45;  // sole support points in ankle-to-ball lengths (footlock.py)
const ID = [0, 0, 0, 1], EX = [1, 0, 0];

const s3 = (t) => { t = Math.min(Math.max(t, 0), 1); return t * t * (3 - 2 * t); };  // smoothstep
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const dot4 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const add = (a, b) => a.map((x, i) => x + b[i]);
const sub = (a, b) => a.map((x, i) => x - b[i]);
const scale = (a, k) => a.map((x) => x * k);
const norm = (a) => Math.sqrt(a.reduce((s, x) => s + x * x, 0));
const unit = (a) => { const n = Math.sqrt(a.reduce((s, x) => s + x * x, 0)); return a.map((x) => x / n); };

export function qmul(a, b) {
  const [ax, ay, az, aw] = a, [bx, by, bz, bw] = b;
  return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz];
}
const qinv = (q) => [-q[0], -q[1], -q[2], q[3]];
export function qrot(q, v) {
  const u = [q[0], q[1], q[2]], t = scale(cross(u, v), 2);
  return add(add(v, scale(t, q[3])), cross(u, t));
}
const turn = (axis, ang) => { const s = Math.sin(ang / 2); return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(ang / 2)]; };
function between(u, v) {
  const d = dot3(u, v);
  if (1 + d < 1e-8) { let a = cross(u, EX); if (dot3(a, a) <= 1e-12) a = cross(u, [0, 1, 0]); return turn(unit(a), Math.PI); }
  const c = cross(u, v);
  return unit([c[0], c[1], c[2], 1 + d]);
}
export function slerp(a, b, t) {
  let d = dot4(a, b);
  if (d < 0) { b = b.map((x) => -x); d = -d; }
  if (d > 0.9995) return unit(a.map((x, i) => x * (1 - t) + b[i] * t));
  const th = Math.acos(Math.min(d, 1)), sn = Math.sin(th), wa = Math.sin((1 - t) * th) / sn, wb = Math.sin(t * th) / sn;
  return unit(a.map((x, i) => x * wa + b[i] * wb));
}

// New local turns of the thigh, calf and foot putting the ankle at P with the foot's world turn WB (Effigy _two_bone;
// the knee turns about the source pose's own bend axis; maxReach: the longest hip-ankle distance allowed). null: nothing to solve.
export function twoBone(pw, WU, WL, WB, a, b, c, P, maxReach = null) {
  const l1 = norm(sub(b, a)), l2 = norm(sub(c, b)), dist = norm(sub(P, a));
  if (l1 * l2 < 1e-12 || dist < 1e-12) return null;
  const d = Math.min(Math.max(dist, Math.abs(l1 - l2) + 1e-6), maxReach === null ? l1 + l2 - 1e-6 : Math.min(maxReach, l1 + l2 - 1e-6));
  const u = sub(a, b), v = sub(c, b);
  let k = cross(u, v);
  if (dot3(k, k) < 1e-16) k = qrot(WU, EX);
  k = unit(k);
  const th = Math.acos(Math.min(Math.max(dot3(u, v) / (l1 * l2), -1), 1));
  const th2 = Math.acos(Math.min(Math.max((l1 * l1 + l2 * l2 - d * d) / (2 * l1 * l2), -1), 1));
  const K = turn(k, th2 - th);
  const H = between(unit(sub(add(qrot(K, v), b), a)), unit(sub(P, a)));
  const nU = qmul(H, WU), nL = qmul(H, qmul(K, WL));
  return [unit(qmul(qinv(pw), nU)), unit(qmul(qinv(nU), nL)), unit(qmul(qinv(nL), WB))];
}

// World turns and positions of one frame. rest: world rest positions (J*3); rotF: Map joint -> local turn.
export function fk(parents, rest, rotF, rootOff, pelvis) {
  const J = parents.length, W = new Array(J), P = new Array(J);
  for (let j = 0; j < J; j++) {
    const p = parents[j];
    let off = p < 0 ? [rest[j * 3], rest[j * 3 + 1], rest[j * 3 + 2]] : [rest[j * 3] - rest[p * 3], rest[j * 3 + 1] - rest[p * 3 + 1], rest[j * 3 + 2] - rest[p * 3 + 2]];
    if (j === pelvis) off = add(off, rootOff);
    const q = rotF.get(j) || ID;
    if (p < 0) { W[j] = q; P[j] = off; } else { W[j] = qmul(W[p], q); P[j] = add(P[p], qrot(W[p], off)); }
  }
  return [W, P];
}

function longestCyclicRun(mask) {  // [start, length] of the longest cyclic run of true (ties: earliest start); null: none
  const F = mask.length;
  if (!mask.some(Boolean)) return null;
  if (mask.every(Boolean)) return [0, F];
  let best = null, runStart = 0, run = 0;
  const s0 = mask.indexOf(false);
  for (let i = 1; i <= F; i++) {
    const f = (s0 + i) % F;
    if (mask[f]) {
      if (run === 0) runStart = f;
      run++;
      if (!best || run > best[1] || (run === best[1] && runStart < best[0])) best = [runStart, run];
    } else run = 0;
  }
  return best;
}
const weight = (k, ls, le, blend) => (ls <= k && k <= le ? 1 : k < ls ? s3(1 - (ls - k) / blend) : s3(1 - (k - le) / blend));
// Foot-lock one in-place loop. rot: {joint: Float32Array(F*4)} local turns; root: (F*3) pelvis offsets as exported
// (height-scaled). Returns {rot, report}: rot shares every untouched array, the six leg channels are new.
export function lockClip(names, parents, rest, rot, root, fps, F) {
  const idx = new Map(names.map((n, i) => [n, i])), pelvis = idx.get("pelvis");
  const R = (i) => [rest[i * 3], rest[i * 3 + 1], rest[i * 3 + 2]];  // a rest position as float64
  const rotI = new Map(); for (const [n, q] of Object.entries(rot)) if (idx.has(n)) rotI.set(idx.get(n), q);
  const frames = [];
  for (let f = 0; f < F; f++) {
    const rf = new Map(); for (const [j, q] of rotI) rf.set(j, [q[f * 4], q[f * 4 + 1], q[f * 4 + 2], q[f * 4 + 3]]);
    frames.push(fk(parents, rest, rf, [root[f * 3], root[f * 3 + 1], root[f * 3 + 2]], pelvis));
  }
  const report = { version: VERSION, fps, frames: F, blend: BLEND, rotation_blend: ROT_BLEND, feet: {} }, stances = {};
  for (const [U, L, B] of LEGS) {
    if (![U, L, B].every((n) => idx.has(n) && rot[n])) { report.feet[B] = { locked: null, reason: "no thigh, calf and foot channels" }; continue; }
    const A = frames.map(([, P]) => P[idx.get(B)]), h = A.map((p) => p[1]);
    const lo = Math.min(...h), hi = Math.max(...h);
    const mask = A.map((_, f) => h[f] <= lo + LOW * (hi - lo) && A[(f + 1) % F][2] - A[(f - 1 + F) % F][2] < 0);
    const st = longestCyclicRun(mask);
    if (!st || st[1] < MIN_SPAN) { report.feet[B] = { locked: null, reason: "no stance" }; continue; }
    stances[B] = [st, A];
  }
  const keys = Object.keys(stances);
  if (!keys.length) { report.ground_speed_m_s = null; return { rot, report }; }
  let v = 0; for (const B of keys) { const [[s, n], A] = stances[B]; v += (A[s % F][2] - A[(s + n - 1) % F][2]) / ((n - 1) / fps); }
  v /= keys.length;
  report.ground_speed_m_s = v;
  const out = {}; for (const [n, q] of Object.entries(rot)) out[n] = q;
  for (const [U, L, B] of LEGS) {
    if (!stances[B]) continue;
    const [[s, n], A] = stances[B], iU = idx.get(U), iL = idx.get(L), iB = idx.get(B);
    const m = s + Math.floor(n / 2), [x0, ya, zm] = A[m % F], Q = frames[m % F][0][iB];
    let yContact = null;
    const ib = idx.get("ball" + B.slice(4));
    if (ib !== undefined) {  // the sole on the floor: the lower support point at y = 0
      const ra = R(iB), rb = R(ib), fwd = [rb[0] - ra[0], 0, rb[2] - ra[2]];
      const pts = [sub([ra[0], 0, ra[2]], scale(fwd, HEEL)), add([rb[0], 0, rb[2]], scale(fwd, TOE))];
      yContact = -Math.min(...pts.map((q) => qrot(Q, sub(q, ra))[1]));
    }
    const nc = Math.min(n, Math.max(MIN_SPAN, Math.round(CORE * n)));
    const ls = s + Math.floor((n - nc) / 2), le = ls + nc - 1;
    const l1 = norm(sub(R(iL), R(iU))), l2 = norm(sub(R(iB), R(iL)));
    const dmax = Math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * Math.cos(MIN_FLEX_DEG * Math.PI / 180));
    let yReach = -Infinity;
    for (let k = ls; k <= le; k++) {
      const H = frames[k % F][1][iU], dh = Math.hypot(x0 - H[0], zm - v * (k - m) / fps - H[2]);
      if (dh >= dmax) { yReach = Infinity; break; }
      yReach = Math.max(yReach, H[1] - Math.sqrt(dmax * dmax - dh * dh) + 1e-6);
    }
    if (yReach === Infinity) { report.feet[B] = { stance: [s, n], locked: null, reason: "plant out of reach" }; continue; }
    const y0 = yContact !== null ? Math.max(yContact, yReach) : Math.max(ya, yReach);
    const plant = (k) => [x0, y0, zm - v * (k - m) / fps];
    if (le - ls + 1 + 2 * ROT_BLEND > F) { report.feet[B] = { stance: [s, n], locked: null, reason: "lock window longer than the clip" }; continue; }
    const qU = Float32Array.from(rot[U]), qL = Float32Array.from(rot[L]), qB = Float32Array.from(rot[B]), weights = {};
    for (let k = ls - ROT_BLEND; k <= le + ROT_BLEND; k++) {
      const w = weight(k, ls, le, BLEND), wr = weight(k, ls, le, ROT_BLEND);
      if (w <= 0 && wr <= 0) continue;
      const f = ((k % F) + F) % F, [W, P] = frames[f], c = P[iB];
      const r = twoBone(W[parents[iU]], W[iU], W[iL], slerp(W[iB], Q, wr), P[iU], P[iL], c, add(c, scale(sub(plant(k), c), w)), dmax);
      if (!r) continue;
      for (const [arr, q] of [[qU, r[0]], [qL, r[1]], [qB, r[2]]]) for (let i = 0; i < 4; i++) arr[f * 4 + i] = q[i];
      weights[f] = [w, wr];
    }
    out[U] = qU; out[L] = qL; out[B] = qB;
    report.feet[B] = { stance: [s % F, n], locked: [ls % F, le - ls + 1], locked_unwrapped_start: ls,
      plant: { frame: m % F, unwrapped_frame: m, x: x0, y: y0, z: zm, rotation: Q, sole_contact_y: yContact,
        sole_above_floor_m: yContact !== null ? y0 - yContact : null }, weights };
  }
  return { rot: out, report };
}

// The studio's clips with walk and run foot-locked for one character, and the record for asset.extras.forge.
// rest: world rest positions; u: the height scale the exporter applies to the clips' hip motion.
export function lockClips(names, parents, rest, clips, u) {
  const reports = {}, outClips = clips.map((c) => {
    if (!CLIPS.includes(c.name) || !c.loop) return c;
    const root = new Float64Array(c.frames * 3); for (let i = 0; i < root.length; i++) root[i] = c.root[i] * u;
    const r = lockClip(names, parents, rest, c.rot, root, c.fps, c.frames);
    reports[c.name] = r.report;
    return { ...c, rot: r.rot };
  });
  return { clips: outClips, record: summary(reports), reports };
}

export function summary(reports) {
  const clips = {};
  for (const [c, r] of Object.entries(reports)) {
    const locked = {}; for (const [f, d] of Object.entries(r.feet)) locked[f] = d.locked;
    clips[c] = { ground_speed_m_s: r.ground_speed_m_s, locked };
  }
  return { foot_lock: { version: VERSION, method: "two-bone IK to a plant point moving at the stride speed; foot held at its mid-stance rotation while locked",
    derived_from: "Effigy steps/_anim.py (MIT, c62db21)", blend_frames: BLEND, rotation_blend_frames: ROT_BLEND, clips } };
}
