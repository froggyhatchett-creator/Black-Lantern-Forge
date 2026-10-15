// Black Lantern Character Studio: real-time editing over the baked fixed-topology morph basis.
import { Renderer, OrbitCamera, M4, norm, sub, cross, dot, len } from "./gl.js";
import { exportGLB, zipFiles } from "./glb.js";

const $ = (s) => document.querySelector(s);
const statusEl = $("#status");
let statusTimer = 0;
const setStatus = (t, ms = 6000) => { statusEl.textContent = t; statusEl.classList.remove("faded"); clearTimeout(statusTimer);
  if (ms) statusTimer = setTimeout(() => statusEl.classList.add("faded"), ms); };

// ---------------------------------------------------------------- pack loading
async function packBytes(url) {
  const res = await fetch(url).catch(() => null);
  if (res && res.ok) return res.body;
  // static hosts that serve only text: base64 chunks listed in studio_pack.parts.json
  const idx = await fetch("studio_pack.parts.json");
  if (!idx.ok) throw new Error(`could not load ${url} (${res ? res.status : "network error"})`);
  const { bytes, parts } = await idx.json(), out = new Uint8Array(bytes);
  let o = 0;
  for (const name of parts) {
    const txt = await (await fetch(name)).text(), bin = atob(txt.trim());
    for (let i = 0; i < bin.length; i++) out[o + i] = bin.charCodeAt(i);
    o += bin.length;
  }
  if (o !== bytes) throw new Error("studio pack chunks are incomplete");
  return new Blob([out]).stream();
}
async function loadPack(url) {
  const body = await packBytes(url);
  const raw = await new Response(body.pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
  const head = new TextDecoder().decode(new Uint8Array(raw, 0, 8));
  if (head !== "FORGEPK1") throw new Error("not a Character Forge studio pack");
  const n = new DataView(raw).getUint32(8, true);
  const man = JSON.parse(new TextDecoder().decode(new Uint8Array(raw, 12, n)));
  const blob = raw.slice(12 + n);
  const T = { f4: Float32Array, u4: Uint32Array, i2: Int16Array, u1: Uint8Array };
  const cache = new Map();
  const arr = (e) => {
    const n = e.s.reduce((a, b) => a * b, 1);
    if (!e.enc) return new T[e.t](blob, e.o, n);
    if (cache.has(e.o)) return cache.get(e.o);
    // "d1p": byte planes of first differences along the leading axis (exactly reversible)
    const size = T[e.t].BYTES_PER_ELEMENT, planes = new Uint8Array(blob, e.o, n * size), bytes = new Uint8Array(n * size);
    for (let b = 0; b < size; b++) { const base = b * n; for (let i = 0; i < n; i++) bytes[i * size + b] = planes[base + i]; }
    const a = new T[e.t](bytes.buffer), step = e.s.length > 1 ? e.s[1] : 1;
    for (let i = step; i < n; i++) a[i] = a[i] + a[i - step];  // typed-array store wraps like the encoder
    cache.set(e.o, a); return a;
  };
  return { man, arr };
}

const SKIN = (meta) => meta.skin_srgb.map((c) => c.map(srgb2lin));
function srgb2lin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
function hex2lin(h) { h = h.replace("#", ""); return [0, 2, 4].map((i) => srgb2lin(parseInt(h.slice(i, i + 2), 16) / 255)); }
function lin2hex(c) { return "#" + c.map((v) => { v = Math.max(0, Math.min(1, v)); v = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  return Math.round(v * 255).toString(16).padStart(2, "0"); }).join(""); }
function skinColor(meta, tone, under) {
  const pal = SKIN(meta), x = tone * (pal.length - 1), i = Math.min(Math.floor(x), pal.length - 2), t = x - i;
  const c = pal[i].map((v, k) => v * (1 - t) + pal[i + 1][k] * t);
  const warm = under > 0 ? [1, 1, 0.86] : [1, 0.94, 0.97];
  return c.map((v, k) => v * (1 + (warm[k] - 1) * Math.abs(under)));
}

// quaternion helpers (x, y, z, w)
const qmul = (a, b) => [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
  a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
const qeuler = (rx, ry, rz) => { const d = Math.PI / 180, h = (a) => [Math.sin(a * d / 2), Math.cos(a * d / 2)];
  const [sx, cx] = h(rx), [sy, cy] = h(ry), [sz, cz] = h(rz);
  return qmul([0, 0, sz, cz], qmul([0, sy, 0, cy], [sx, 0, 0, cx])); };
function slerp(a, b, t) { let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]; if (d < 0) { b = b.map((v) => -v); d = -d; }
  if (d > 0.9995) { const r = a.map((v, i) => v + (b[i] - v) * t); const l = Math.hypot(...r); return r.map((v) => v / l); }
  const th = Math.acos(d), s = Math.sin(th); return a.map((v, i) => (Math.sin((1 - t) * th) * v + Math.sin(t * th) * b[i]) / s); }
function mat3FromQ(q) { const [x, y, z, w] = q; return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]; }
function qFromMat3(m) { const t = m[0][0] + m[1][1] + m[2][2]; let q;
  if (t > 0) { const s = Math.sqrt(t + 1) * 2; q = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]; }
  else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) { const s = Math.sqrt(1 + m[0][0] - m[1][1] - m[2][2]) * 2; q = [0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s]; }
  else if (m[1][1] > m[2][2]) { const s = Math.sqrt(1 + m[1][1] - m[0][0] - m[2][2]) * 2; q = [(m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s]; }
  else { const s = Math.sqrt(1 + m[2][2] - m[0][0] - m[1][1]) * 2; q = [(m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s]; }
  const l = Math.hypot(...q); return q.map((v) => v / l); }
function rotBetween(a, b) {  // quaternion rotating unit a onto unit b
  const c = dot(a, b); if (c < -0.9999) return [1, 0, 0, 0];
  const v = cross(a, b), q = [v[0], v[1], v[2], 1 + c], l = Math.hypot(...q); return q.map((x) => x / l); }
const qrot = (q, v) => { const m = mat3FromQ(q); return [m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2], m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2], m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]]; };
const qconj = (q) => [-q[0], -q[1], -q[2], q[3]];
function scaleRot(q, k) {  // scale a rotation's angle by k (k may exceed 1)
  const w = Math.max(-1, Math.min(1, q[3])), ang = 2 * Math.acos(w), sn = Math.sqrt(Math.max(1 - w * w, 0));
  if (sn < 1e-6) return [0, 0, 0, 1];
  const a2 = ang * k / 2, s2 = Math.sin(a2) / sn; return [q[0] * s2, q[1] * s2, q[2] * s2, Math.cos(a2)];
}

const POSES = {
  "A-pose (rest)": {},
  "Relaxed": { upperarm_l: [0, 0, -38], upperarm_r: [0, 0, 38], lowerarm_l: [-12, 0, -4], lowerarm_r: [-12, 0, 4] },
  "Contrapposto": { pelvis: [0, 6, 4], spine_02: [0, -4, -3], neck_01: [4, -6, 0], head: [-4, 8, 2], thigh_l: [-6, 0, 2], calf_l: [14, 0, 0],
    foot_l: [-6, 0, 0], thigh_r: [2, 0, -3], upperarm_l: [-10, 0, -40], lowerarm_l: [-35, 0, 0], upperarm_r: [8, 0, 36], lowerarm_r: [-15, 0, 0] },
  "Hands on hips": { upperarm_l: [0, -20, -55], upperarm_r: [0, 20, 55], lowerarm_l: [-10, 70, 0], lowerarm_r: [-10, -70, 0], spine_02: [-4, 0, 0] },
  "Lunge": { pelvis: [0, 10, 0], thigh_l: [-55, 0, 0], calf_l: [60, 0, 0], foot_l: [-8, 0, 0], thigh_r: [25, 0, 0], calf_r: [35, 0, 0],
    spine_01: [8, 0, 0], spine_02: [6, -8, 0], upperarm_l: [30, 0, -30], upperarm_r: [-50, 0, 30], lowerarm_r: [-60, 0, 0], head: [-8, 10, 0] },
  "Arms raised": { upperarm_l: [0, 0, 95], upperarm_r: [0, 0, -95], lowerarm_l: [0, 0, 15], lowerarm_r: [0, 0, -15], head: [-8, 0, 0] },
};

const LABELS = {
  height_m: "Height (m)", femininity: "Masculine ↔ feminine build", body_fat: "Body fat", muscle: "Muscle", shoulder_width: "Shoulder width",
  chest_width: "Chest width", chest_depth: "Chest depth", waist_width: "Waist", hip_width: "Hips", glute_size: "Glutes", belly: "Belly",
  torso_length: "Torso length", neck_length: "Neck length", neck_thickness: "Neck thickness", arm_length: "Arm length", arm_thickness: "Arm girth",
  leg_length: "Leg length", thigh_thickness: "Thigh girth", calf_thickness: "Calf girth", hand_size: "Hand size", foot_size: "Foot size",
  head_size: "Head size", breast_size: "Breast size", breast_spacing: "Breast spacing", breast_height: "Breast height",
  breast_projection: "Breast projection", breast_sag: "Breast sag", face_width: "Face width", face_length: "Face length", jaw_width: "Jaw width",
  jaw_angle: "Jaw squareness", chin_width: "Chin width", chin_length: "Chin length", chin_projection: "Chin projection",
  cheekbone_width: "Cheekbone width", cheekbone_height: "Cheekbone height", cheek_fullness: "Cheek fullness", nose_length: "Nose length",
  nose_width: "Nose width", nose_bridge: "Nose bridge", nose_tip: "Nose tip", nose_upturn: "Nose upturn", brow_height: "Brow height",
  brow_prominence: "Brow ridge", eye_size: "Eye size", eye_spacing: "Eye spacing", eye_tilt: "Eye tilt", lip_upper: "Upper lip",
  lip_lower: "Lower lip", mouth_width: "Mouth width", ear_size: "Ear size", ear_protrusion: "Ear protrusion", asymmetry: "Asymmetry",
};
const GROUPS = {
  body: [["Overall", ["height_m", "femininity", "body_fat", "muscle", "head_size"]],
    ["Torso", ["shoulder_width", "chest_width", "chest_depth", "waist_width", "hip_width", "glute_size", "belly", "torso_length"]],
    ["Chest", ["breast_size", "breast_spacing", "breast_height", "breast_projection", "breast_sag"]],
    ["Neck & limbs", ["neck_length", "neck_thickness", "arm_length", "arm_thickness", "leg_length", "thigh_thickness", "calf_thickness", "hand_size", "foot_size"]]],
  face: [["Face shape", ["face_width", "face_length", "jaw_width", "jaw_angle", "chin_width", "chin_length", "chin_projection", "cheekbone_width", "cheekbone_height", "cheek_fullness", "asymmetry"]],
    ["Nose", ["nose_length", "nose_width", "nose_bridge", "nose_tip", "nose_upturn"]],
    ["Eyes & brows", ["eye_size", "eye_spacing", "eye_tilt", "brow_height", "brow_prominence"]],
    ["Mouth & ears", ["lip_upper", "lip_lower", "mouth_width", "ear_size", "ear_protrusion"]]],
};
const HAIR_LABELS = { bald: "Bald", buzz: "Buzz cut", short: "Short (close crop)", pixie: "Pixie / shag", bob: "Layered bob",
  bangs: "Bob with asymmetric bangs", long: "Long layered", bun: "Bun" };
const HAIR_SWAY = { hair_long: [1.0, 0.15, 0.5], hair_bob: [0.45, 0.16, 0.15], hair_bangs: [0.45, 0.16, 0.15], hair_pixie: [0.12, 0.2, 0.1] };  // amount, unit top, unit length
const MATERIAL = {
  skin: { kind: 0, rough: 0.5, spec: 0.28, sss: 1, detail: 1 }, eye: { kind: 3, rough: 0.15, spec: 0.6 },
  cornea: { kind: 4, blend: true, rough: 0.03, spec: 1 }, teeth: { kind: 6, rough: 0.3, spec: 0.4 },
  brow: { kind: 5, double: true, blend: true, rough: 0.7, spec: 0.1 }, lash: { kind: 5, double: true, blend: true, rough: 0.6, spec: 0.1 },
  hair: { kind: 2, double: true, rough: 0.5, spec: 0.3 },
};

// ---------------------------------------------------------------- application
class Studio {
  constructor(meta, pack, clips) {
    this.meta = meta; this.man = pack.man; this.arr = pack.arr;
    this.clips = {};
    for (const [n, c] of Object.entries(clips || {})) this.clips[n] = { ...c, name: n, rot: Object.fromEntries(Object.entries(c.rot).map(([k, v]) => [k, Float32Array.from(v)])), root: Float32Array.from(c.root) };
    if (!clips) for (const [n, c] of Object.entries(this.man.clips)) this.clips[n] = { ...c, name: n, rot: Object.fromEntries(Object.entries(c.rot).map(([k, e]) => [k, this.arr(e)])), root: this.arr(c.root) };
    this.spin = { yaw: 0, vel: 0, mode: "camera" };
    this.renderer = new Renderer($("#view"));
    this.cam = new OrbitCamera();
    this.cam.attach($("#view"), () => this.dirtyFrame = true, (dx) => {
      if (this.spin.mode !== "character") return false;
      this.spin.vel = 0.7 * this.spin.vel + 0.3 * (dx * 0.012) / Math.max(this._dt || 1 / 60, 1 / 240); this.spin.yaw += dx * 0.012;
      this._lastSpin = performance.now(); return true; });
    this.skel = this.man.skeleton;
    this.J = this.skel.names.length;
    this.restBase = this.arr(this.skel.rest);
    this.state = this.defaultState();
    this.history = []; this.future = [];
    this.parts = {};
    for (const [name, p] of Object.entries(this.man.parts)) this.buildPart(name, p);
    this.decodeCache = new Map();
    this.clipT = 0; this.playing = true;
    this.phys = { on: true, state: new Map(), freq: 2.4, damp: 0.22, support: 1, intensity: 1, hair: null };
    this.dirtyGeo = true;
    this.buildUI();
    $("#body-verts").textContent = this.man.parts.body.n.toLocaleString("en-US");
    this.applyPreset("female", false);
    this.focus("body");
    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
  }
  defaultState() {
    const params = {};
    for (const [k, pe] of Object.entries(this.man.params)) params[k] = pe.default;
    return { params, locks: {}, preset: "neutral", name: "studio_character", age: 30,
      skin_tone: 0.3, undertone: 0.0, eye: "brown", hair_style: "long", hair_color: "#3b2416", hl_color: "#a47b52", hl_amount: 0,
      outfit: ["tshirt", "shorts"], colors: {}, expr: {}, pose: "A-pose (rest)", clip: "idle" };
  }
  buildPart(name, p) {
    const pos = this.arr(p.pos), idx = this.arr(p.idx);
    const hl = p.highlight ? this.arr(p.highlight) : null;  // hair: highlight streak mask in COLOR_0.r
    const col = p.color ? Float32Array.from(this.arr(p.color), (v) => v / 255 * 2) : hl ? Float32Array.from({ length: hl.length * 3 }, (_, i) => hl[(i / 3) | 0] / 255) : null;
    const uv = p.uv ? this.arr(p.uv) : null;
    const g = this.renderer.addMesh({ pos: Float32Array.from(pos), nrm: new Float32Array(pos.length), col, uv, idx,
      jnt: this.arr(p.joints), wgt: this.arr(p.weights) });
    const mat = p.material.startsWith("cloth_") ? { kind: 1, double: true, rough: 0.85, spec: 0.08 } : (MATERIAL[p.material] || {});
    Object.assign(g, mat);
    this.parts[name] = { g, base: pos, idx, tint: col, cur: new Float32Array(pos.length), nrm: new Float32Array(pos.length), material: p.material,
      jnt: this.arr(p.joints), wgt: this.arr(p.weights), sway: null, headSpace: p.frame === "head", hl };
  }
  // -------------------------------------------------------------- geometry evaluation
  addDelta(target, enc, w) {
    if (!enc || !w) return;
    const s = enc.scale * w;
    if (enc.dense) { const d = this.arr(enc.dense); for (let i = 0; i < d.length; i++) target[i] += d[i] * s; return; }
    const idx = this.arr(enc.idx), val = this.arr(enc.val);
    for (let i = 0; i < idx.length; i++) { const o = idx[i] * 3, k = i * 3; target[o] += val[k] * s; target[o + 1] += val[k + 1] * s; target[o + 2] += val[k + 2] * s; }
  }
  weights() {  // piecewise-linear weights per (param, side)
    const out = [];
    for (const [k, pe] of Object.entries(this.man.params)) {
      const dv = this.state.params[k] - pe.default; if (Math.abs(dv) < 1e-9) continue;
      const side = dv > 0 ? "hi" : "lo", se = pe.sides[side]; if (!se) continue;
      out.push([se, dv / (se.at - pe.default)]);
    }
    return out;
  }
  headFrame(rest) {  // the engine's head_frame recovered from the head and jaw joints (exact, see skeleton.py)
    const n = this.skel.names, h = n.indexOf("head") * 3, j = n.indexOf("jaw") * 3;
    const hh = (rest[j + 1] - rest[h + 1]) / 0.1;
    return { O: [0, rest[h + 1] - 0.2 * hh, rest[h + 2]], k: hh / 0.23 };
  }
  evaluate() {
    this.updateVisibility();
    const ws = this.weights();
    const pre = this.man.presets[this.state.preset];
    const rest = Float32Array.from(this.restBase);
    for (const [se, w] of ws) { const d = this.arr(se.joints); for (let i = 0; i < d.length; i++) rest[i] += d[i] * w; }
    if (pre && pre.joints) { const d = this.arr(pre.joints); for (let i = 0; i < d.length; i++) rest[i] += d[i]; }
    this.rest = rest;
    const { O, k } = this.headFrame(rest);
    for (const [name, P] of Object.entries(this.parts)) {
      const cur = P.cur;
      if (P.headSpace) {  // rigid in head space: world = O + unit * k
        if (!P.g.visible) continue;
        for (let i = 0; i < cur.length; i += 3) { cur[i] = O[0] + P.base[i] * k; cur[i + 1] = O[1] + P.base[i + 1] * k; cur[i + 2] = O[2] + P.base[i + 2] * k; }
        this.normals(cur, P.idx, P.nrm); this.renderer.update(P.g, "pos", cur); this.renderer.update(P.g, "nrm", P.nrm); continue;
      }
      cur.set(P.base);
      for (const [se, w] of ws) this.addDelta(cur, se.parts[name], w);
      if (pre && pre.parts) this.addDelta(cur, pre.parts[name], 1);
      if (name === "body") for (const e of this.man.expressions) this.addDelta(cur, e.body, this.state.expr[e.name] || 0);
      this.normals(cur, P.idx, P.nrm);
      this.renderer.update(P.g, "pos", cur); this.renderer.update(P.g, "nrm", P.nrm);
      if (P.material === "eye") {  // rest-pose eyeball center for the per-pixel eye shading
        const c = [0, 0, 0]; for (let i = 0; i < cur.length; i += 3) { c[0] += cur[i]; c[1] += cur[i + 1]; c[2] += cur[i + 2]; }
        P.g.eyeC = c.map((x) => x / (cur.length / 3));
      }
      if (P.material === "cornea") P.g.eyeC = this.parts[`eye_${name.slice(-1)}`].g.eyeC;  // eyes evaluate first
    }
    this.heightNow = this.measureHeight();
    this.updateColors();
    $("#height-readout").textContent = `${this.heightNow.toFixed(2)} m`;
  }
  measureHeight() { const b = this.parts.body.cur; let lo = 1e9, hi = -1e9; for (let i = 1; i < b.length; i += 3) { lo = Math.min(lo, b[i]); hi = Math.max(hi, b[i]); } return hi - lo; }
  normals(pos, idx, out) {
    out.fill(0);
    for (let t = 0; t < idx.length; t += 3) {
      const a = idx[t] * 3, b = idx[t + 1] * 3, c = idx[t + 2] * 3;
      const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
      const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      for (const o of [a, b, c]) { out[o] += nx; out[o + 1] += ny; out[o + 2] += nz; }
    }
    for (let i = 0; i < out.length; i += 3) { const l = Math.hypot(out[i], out[i + 1], out[i + 2]) || 1; out[i] /= l; out[i + 1] /= l; out[i + 2] /= l; }
  }
  updateColors() {
    const s = this.state, skin = skinColor(this.meta, s.skin_tone, s.undertone);
    const hair = hex2lin(s.hair_color);
    for (const [name, P] of Object.entries(this.parts)) {
      const g = P.g;
      if (P.material === "skin") g.base = skin;
      else if (P.material === "hair") { g.base = hair; g.iris = hex2lin(s.hl_color); g.detail = s.hl_amount; }  // highlight color/amount
      else if (P.material === "brow") g.base = hair.map((v) => v * 0.8);
      else if (P.material === "lash") g.base = [0.02, 0.015, 0.012];
      else if (P.material === "eye") { g.base = [1, 1, 1]; g.iris = this.meta.eye_colors[s.eye] || [0.2, 0.09, 0.03]; }
      else if (P.material === "cornea") g.base = [1, 1, 1];
      else if (P.material === "teeth") g.base = [1, 1, 1];
      else if (P.material.startsWith("cloth_")) { const gname = P.material.slice(6);
        g.base = s.colors[gname] ? hex2lin(s.colors[gname]) : this.meta.garment_colors[gname]; }
    }
  }
  updateVisibility() {
    const s = this.state, hs = s.hair_style, out = new Set(s.outfit);
    for (const [name, P] of Object.entries(this.parts)) {
      let vis = true;
      if (name === "hair_cap") vis = ["short", "bun"].includes(hs);
      else if (name === "hair_bun") vis = hs === "bun";
      else if (name.startsWith("hair_")) vis = name === `hair_${hs}`;
      else if (P.material.startsWith("cloth_")) {
        const gname = P.material.slice(6);
        vis = out.has(gname);
      }
      P.g.visible = vis && !(this.hidden && this.hidden.has(name));
    }
  }
  // -------------------------------------------------------------- coverage (public profile stays clothed)
  required() {
    const p = this.state.params;
    const r = ["pelvis"];
    if (p["body.femininity"] > 0.5 || p["body.breast_size"] > 0.15) r.push("chest");
    return r;
  }
  enforceCoverage() {
    const covers = this.meta.covers, out = new Set(this.state.outfit), added = [];
    for (const reg of this.required()) {
      if (![...out].some((g) => covers[reg].includes(g))) { const g = reg === "pelvis" ? "shorts" : "tshirt"; out.add(g); added.push(g); }
    }
    this.state.outfit = [...out];
    const note = $("#coverage-note");
    note.textContent = added.length ? `Public characters stay clothed: added ${added.join(", ")}.` : "";
    return added;
  }
  // -------------------------------------------------------------- skeleton / animation / physics
  fk(localRot, rootOffset) {
    const J = this.J, par = this.skel.parents, rest = this.rest, G = new Array(J);
    for (let j = 0; j < J; j++) {
      const p = par[j];
      const off = p < 0 ? [rest[j * 3], rest[j * 3 + 1], rest[j * 3 + 2]] : [rest[j * 3] - rest[p * 3], rest[j * 3 + 1] - rest[p * 3 + 1], rest[j * 3 + 2] - rest[p * 3 + 2]];
      if (rootOffset && this.skel.names[j] === "pelvis") { off[0] += rootOffset[0]; off[1] += rootOffset[1]; off[2] += rootOffset[2]; }
      const L = M4.fromQT(localRot[j] || [0, 0, 0, 1], off);
      G[j] = p < 0 ? L : M4.mul(G[p], L);
    }
    return G;
  }
  poseRotations(t) {
    const names = this.skel.names, rot = new Array(this.J).fill(null);
    const pose = POSES[this.state.pose] || {};
    for (const [n, e] of Object.entries(pose)) { const j = names.indexOf(n); if (j >= 0) rot[j] = qeuler(...e); }
    let root = null;
    const c = this.state.clip !== "none" && this.clips[this.state.clip];
    if (c) {
      const f = (t * c.fps) % (c.frames - 1), i = Math.floor(f), a = f - i;
      if (this._lastF !== undefined && f < this._lastF && !c.loop) this._resetPhys = true;  // non-looping clip restarted
      this._lastF = f;
      for (const [n, q] of Object.entries(c.rot)) {
        const j = names.indexOf(n); if (j < 0) continue;
        const qa = [...q.slice(i * 4, i * 4 + 4)], qb = [...q.slice((i + 1) * 4, (i + 1) * 4 + 4)];
        const qc = slerp(qa, qb, a); rot[j] = rot[j] ? qmul(rot[j], qc) : qc;
      }
      const r = c.root, u = this.heightNow / 1.75;
      root = [0, 1, 2].map((k) => (r[i * 3 + k] * (1 - a) + r[(i + 1) * 3 + k] * a) * u);
    }
    const ri = names.indexOf("root");  // character spin (inertial, felt by the physics) — camera orbit is not
    const qy = [0, Math.sin(this.spin.yaw / 2), 0, Math.cos(this.spin.yaw / 2)];
    rot[ri] = rot[ri] ? qmul(qy, rot[ri]) : qy;
    return { rot, root };
  }
  physicsChains() {
    const n = this.skel.names, m = this.skel.marks, rest = this.rest, base = this.restBase, ch = [];
    const tipOf = (b, tipBase) => { const j = n.indexOf(b); return [0, 1, 2].map((k) => tipBase[k] - base[j * 3 + k] + rest[j * 3 + k]); };
    for (const lab of ["l", "r"]) {
      const b = `breast_${lab}`, j = n.indexOf(b); if (j < 0 || !m[`nipple_${lab}`]) continue;
      const bs = this.state.params["body.breast_size"];
      ch.push({ kind: "breast", bones: [b], tips: { [b]: tipOf(b, m[`nipple_${lab}`]) }, freq: this.phys.freq, damp: this.phys.damp,
        maxAng: 22 * Math.PI / 180, gain: Math.min(1, bs / 0.4) });
    }
    for (const side of ["front", "back"]) {
      const bones = [1, 2, 3].map((i) => `cloth_${side}_0${i}`);
      if (!bones.every((b) => n.includes(b))) continue;
      const P = (b) => { const j = n.indexOf(b); return [rest[j * 3], rest[j * 3 + 1], rest[j * 3 + 2]]; };
      const p3 = P(bones[2]), p2 = P(bones[1]);
      ch.push({ kind: "cloth", bones, tips: { [bones[0]]: P(bones[1]), [bones[1]]: p3, [bones[2]]: p3.map((v, k) => v + (v - p2[k]) * 0.6) },
        freq: 1.6, damp: 0.35, maxAng: 70 * Math.PI / 180, gain: 1 });
    }
    return ch;
  }
  simulate(rot, root, dt) {
    if (!this.phys.on) return rot;
    const names = this.skel.names, par = this.skel.parents, rest = this.rest;
    const support = { 0: 1, 1: 1.15, 2: 1.9 }[this.phys.support] || 1;
    const outfit = new Set(this.state.outfit);
    const breastSupport = outfit.has("bra") ? 1.9 : (outfit.has("tshirt") || outfit.has("robe") ? 1.15 : 1);
    const sub_ = 4, h = Math.min(dt, 1 / 20) / sub_;
    for (let s = 0; s < sub_; s++) {
      for (const ch of this.physicsChains()) {
        const sup = ch.kind === "breast" ? breastSupport * support : 1;
        const w = 2 * Math.PI * ch.freq * sup, z = ch.damp * (ch.kind === "breast" ? sup * 1.15 : 1);
        for (const b of ch.bones) {
          const j = names.indexOf(b), p = par[j];
          const G = this.fk(rot, root);
          const Gp = G[p];
          const off = [rest[j * 3] - rest[p * 3], rest[j * 3 + 1] - rest[p * 3 + 1], rest[j * 3 + 2] - rest[p * 3 + 2]];
          const Rp = [[Gp[0], Gp[4], Gp[8]], [Gp[1], Gp[5], Gp[9]], [Gp[2], Gp[6], Gp[10]]];
          const mv = (M, v) => [M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2], M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2], M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2]];
          const joint = mv(Rp, off).map((v, k) => v + Gp[12 + k]);
          const tipL = ch.tips[b].map((v, k) => v - rest[j * 3 + k]);
          const target = mv(Rp, tipL).map((v, k) => v + joint[k]);
          const L = len(tipL) || 1e-6;
          let st = this.phys.state.get(b);
          if (!st || this._resetPhys) { st = { p: target.slice(), v: [0, 0, 0], pf: target.slice() }; this.phys.state.set(b, st); }
          // the driving motion happens once per frame: spread it evenly over the sub-steps
          const frac = (s + 1) / sub_, tg = st.pf.map((v, k) => v + (target[k] - v) * frac);
          const vt = target.map((v, k) => (v - st.pf[k]) / (h * sub_));
          if (s === sub_ - 1) st.pf = target.slice();
          const acc = [0, 1, 2].map((k) => w * w * (tg[k] - st.p[k]) - 2 * z * w * (st.v[k] - vt[k]) + (this.kick ? this.kick[k] : 0));
          st.v = st.v.map((v, k) => v + acc[k] * h);
          let pn = st.p.map((v, k) => v + st.v[k] * h);
          let d = norm(sub(pn, joint)); const td = norm(sub(tg, joint));
          const ang = Math.acos(Math.max(-1, Math.min(1, dot(d, td)))), maxA = ch.maxAng / (ch.kind === "breast" ? Math.sqrt(sup) : 1);
          if (ang > maxA) { const t = maxA / ang; d = norm(td.map((v, k) => v * (1 - t) + d[k] * t)); }
          pn = joint.map((v, k) => v + d[k] * L);
          st.v = pn.map((v, k) => (v - st.p[k]) / h); st.p = pn;
          // local rotation turning the target direction into the simulated one (scaled by gain)
          let q = rotBetween(td, d);
          const gain = ch.gain * this.phys.intensity;
          if (gain !== 1) q = scaleRot(q, gain);
          const qp = qFromMat3(Rp);
          rot[j] = qmul(qconj(qp), qmul(q, qp));
        }
      }
      this.kick = null;
    }
    this._resetPhys = false;
    return rot;
  }
  hairSway(G, dt) {
    // Long hair has no bones: a spring-lagged offset driven by the head's world motion, stronger toward the ends.
    const name = Object.keys(HAIR_SWAY).find((n) => this.parts[n] && this.parts[n].g.visible); if (!name) return;
    const P = this.parts[name], [amt, top, len] = HAIR_SWAY[name];
    const h = G[this.skel.names.indexOf("head")], head = [h[12], h[13], h[14]];
    if (!P.sway) {  // per-vertex sway weight from the head-space height: roots stay, ends follow the spring
      const f = new Float32Array(P.base.length / 3);
      for (let i = 0; i < f.length; i++) { const t = Math.max(0, Math.min(1, (top - P.base[i * 3 + 1]) / len)); f[i] = t * t * amt; }
      P.sway = { f, p: head.slice(), v: [0, 0, 0], prev: head.slice() };
    }
    const S = P.sway, w = 2 * Math.PI * 1.3 * Math.sqrt(this.phys.freq / 2.4), z = 0.18, n = 4, hh = Math.min(dt, 0.05) / n;
    if (this._resetPhys || !this.phys.on) { S.p = head.slice(); S.v = [0, 0, 0]; S.prev = head.slice(); }
    for (let k = 0; k < n; k++) {
      const tgt = head.map((v, i) => S.prev[i] + (v - S.prev[i]) * (k + 1) / n);
      const vt = head.map((v, i) => (v - S.prev[i]) / Math.max(dt, 1e-4));
      for (let i = 0; i < 3; i++) { const a = w * w * (tgt[i] - S.p[i]) - 2 * z * w * (S.v[i] - vt[i]); S.v[i] += a * hh; S.p[i] += S.v[i] * hh; }
    }
    S.prev = head.slice();
    let off = S.p.map((v, i) => (v - head[i]) * this.phys.intensity);
    const L = Math.hypot(...off), maxL = 0.12; if (L > maxL) off = off.map((v) => v * maxL / L);
    const yaw = -this.spin.yaw, c = Math.cos(yaw), sn = Math.sin(yaw);  // world -> character rest frame
    const ox = off[0] * c + off[2] * sn, oz = -off[0] * sn + off[2] * c, oy = Math.min(off[1], 0.02);
    const out = P.sway.buf || (P.sway.buf = new Float32Array(P.cur.length));
    for (let i = 0; i < P.cur.length; i += 3) {
      const f = S.f[i / 3];
      out[i] = P.cur[i] + ox * f; out[i + 1] = P.cur[i + 1] + oy * f * 0.3; out[i + 2] = P.cur[i + 2] + oz * f;
    }
    this.renderer.update(P.g, "pos", out);
  }
  exportState() {
    return { skel: this.skel, J: this.J, rest: this.rest, parts: this.parts, u: this.heightNow / 1.75, name: this.state.name,
      generator: this.man.generator || null,
      expressions: this.man.expressions, clips: Object.values(this.clips),
      coverage: { required: this.required(), covered_by: Object.fromEntries(this.required().map((r) => [r, this.state.outfit.filter((g) => this.meta.covers[r].includes(g))])), outfit: this.state.outfit },
      dna: this.toDNA(), decodeSparse: (enc, n) => this.decodeSparse(enc, n) };
  }
  decodeSparse(enc, n) {
    if (enc.dense) { const d = this.arr(enc.dense), idx = []; for (let v = 0; v < n; v++) if (d[v * 3] || d[v * 3 + 1] || d[v * 3 + 2]) idx.push(v);
      const val = new Float32Array(idx.length * 3); idx.forEach((v, k) => { for (let c = 0; c < 3; c++) val[k * 3 + c] = d[v * 3 + c] * enc.scale; });
      return { idx: Uint32Array.from(idx), val }; }
    const idx = Uint32Array.from(this.arr(enc.idx)), q = this.arr(enc.val), val = new Float32Array(q.length);
    for (let i = 0; i < q.length; i++) val[i] = q[i] * enc.scale; return { idx, val };
  }
  exportBytes() { this.evaluate(); return exportGLB(this.exportState()); }
  async offerFile(filename, data, zipName) {
    const dl = window.claude ? await window.claude.use("downloads").catch(() => null) : null;
    if (dl) {
      let name = filename, payload = data;
      if (zipName) { payload = zipFiles([{ name: filename, data: typeof data === "string" ? new TextEncoder().encode(data) : data }]); name = zipName; }
      try { await dl.save({ filename: name, data: new Blob([payload]) }); setStatus(`Offered ${name} for saving.`); }
      catch (e) { setStatus(e.code === "declined" ? "Save cancelled." : `Save unavailable here (${e.code || e.message}). Use Copy DNA.`); }
      return;
    }
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([data])); a.download = filename;
    document.body.append(a); a.click(); a.remove(); setStatus(`Saved ${filename}.`);
  }
  // -------------------------------------------------------------- frame loop
  step(dt, now = performance.now()) {  // advance animation, spin inertia and secondary motion by dt seconds
    if (this.dirtyGeo) { this.evaluate(); this.dirtyGeo = false; }
    if (this.playing) this.clipT += dt;
    this._dt = dt;
    if (!(this._lastSpin && now - this._lastSpin < 60)) { this.spin.yaw += this.spin.vel * dt; this.spin.vel *= Math.exp(-2.2 * dt); }
    let { rot, root } = this.poseRotations(this.clipT);
    rot = this.simulate(rot, root, dt);
    const G = this.fk(rot, root);
    this.hairSway(G, dt);
    return { G, root };
  }
  loop(now) {
    const dt = this.lastT ? Math.min((now - this.lastT) / 1000, 0.1) : 1 / 60; this.lastT = now;
    if ($("#turntable").checked) this.cam.yaw += dt * 0.35;
    const { G, root } = this.step(dt, now);
    if (root && this.followTarget !== false) {  // keep travelling clips in frame
      const pel = G[this.skel.names.indexOf("pelvis")];
      this.cam.target[0] += (pel[12] - this.cam.target[0]) * Math.min(1, dt * 4);
      this.cam.target[2] += (pel[14] - this.cam.target[2]) * Math.min(1, dt * 4);
    }
    const mats = new Float32Array(80 * 16);
    for (let j = 0; j < this.J; j++) {
      const inv = M4.ident(); inv[12] = -this.rest[j * 3]; inv[13] = -this.rest[j * 3 + 1]; inv[14] = -this.rest[j * 3 + 2];
      mats.set(M4.mul(G[j], inv), j * 16);
    }
    for (let j = this.J; j < 80; j++) { mats[j * 16] = mats[j * 16 + 5] = mats[j * 16 + 10] = mats[j * 16 + 15] = 1; }
    this.renderer.draw(this.cam, mats, $("#ground").checked);
    this.frames = (this.frames || 0) + 1;
    requestAnimationFrame(this.loop);
  }
  // -------------------------------------------------------------- state changes
  snapshot() { return JSON.stringify(this.state); }
  commit() { this.history.push(this._before || this.snapshot()); this.future = []; this._before = null; if (this.history.length > 100) this.history.shift(); }
  undo() { if (!this.history.length) return; this.future.push(this.snapshot()); this.state = JSON.parse(this.history.pop()); this.syncUI(); this.dirtyGeo = true; }
  redo() { if (!this.future.length) return; this.history.push(this.snapshot()); this.state = JSON.parse(this.future.pop()); this.syncUI(); this.dirtyGeo = true; }
  setParam(k, v, { record = true } = {}) {
    if (record && !this._before) this._before = this.snapshot();
    const pe = this.man.params[k]; this.state.params[k] = Math.max(pe.min, Math.min(pe.max, v));
    if (k === "body.femininity" || k === "body.breast_size") this.enforceCoverage();
    this.dirtyGeo = true;
  }
  applyPreset(name, record = true) {
    if (record) this._before = this.snapshot();
    const vals = this.man.presets[name].values;
    for (const [k, v] of Object.entries(vals)) if (!this.state.locks[k]) this.state.params[k] = v;
    this.state.preset = name;
    // presets set a starting look; styling and wardrobe are separate from anatomy and stay editable
    if (name === "male") Object.assign(this.state, { hair_style: "short", hair_color: "#1f1712", hl_amount: 0, outfit: ["tshirt", "pants"], skin_tone: 0.45 });
    if (name === "female") Object.assign(this.state, { hair_style: "long", hair_color: "#3b2416", hl_amount: 0.25, outfit: ["tshirt", "shorts"], skin_tone: 0.3 });
    this.enforceCoverage();
    if (record) this.commit();
    this._resetPhys = true;
    this.syncUI(); this.dirtyGeo = true;
  }
  randomize() {
    this._before = this.snapshot();
    const seed = Math.floor(Math.random() * 1e6); let x = seed;
    const rnd = () => { x = (x * 1103515245 + 12345) % 2147483648; return x / 2147483648; };
    for (const [k, pe] of Object.entries(this.man.params)) {
      if (this.state.locks[k] || k === "body.femininity" || k === "body.height_m") continue;
      const span = (pe.max - pe.min) * 0.35, c = this.state.params[k];
      this.state.params[k] = Math.max(pe.min, Math.min(pe.max, c + (rnd() - 0.5) * span));
    }
    this.commit(); this.syncUI(); this.dirtyGeo = true;
    setStatus(`Randomized unlocked traits (seed ${seed}). Locked traits were kept.`);
  }
  focus(where) {
    const m = this.skel.marks, s = (this.heightNow || 1.75) / 1.75;
    const spots = { body: [[0, 0.88 * s, 0], 5.4 * s], face: [[0, (m.y_chin + 0.12) * s, 0.05], 0.75], torso: [[0, m.y_hip * 1.25 * s, 0.05], 1.6 * s],
      hands: [this.jointPos("hand_l") || [0.4 * s, 0.85 * s, 0], 0.55], feet: [[0, 0.1, 0.1], 1.2] };
    const [t, d] = spots[where]; this.cam.target = t; this.cam.dist = d;
  }
  jointPos(name) {  // current rest position of a joint (A-pose); null before the first evaluation
    const j = this.skel.names.indexOf(name); if (j < 0 || !this.rest) return null;
    return [this.rest[j * 3], this.rest[j * 3 + 1], this.rest[j * 3 + 2]];
  }
  // -------------------------------------------------------------- DNA
  toDNA() {
    const s = this.state, d = this.meta.defaults, traits = {};
    const tr = (v, dv, k) => ({ value: v, provenance: JSON.stringify(v) === JSON.stringify(dv) ? "default" : "user", confidence: 1,
      sources: [], locked: !!s.locks[k], note: "Character Studio" });
    for (const g of ["body", "face"]) for (const [k, dv] of Object.entries(d[g])) {
      const key = `${g}.${k}`; const v = key in s.params ? +s.params[key].toFixed(4) : dv; traits[key] = tr(v, dv, key); }
    traits["body.nipple_size"] = tr(d.body.nipple_size, d.body.nipple_size, "");
    traits["body.areola_size"] = tr(d.body.areola_size, d.body.areola_size, "");
    for (const [k, dv] of Object.entries(d.genital)) traits[`genital.${k}`] = tr(dv, dv, "");
    const app = { ...d.appearance, skin_tone: +s.skin_tone.toFixed(3), undertone: +s.undertone.toFixed(3), eye_color: s.eye,
      hair_style: s.hair_style, hair_color: s.hair_color, hair_highlight_color: s.hl_color, hair_highlight_amount: +(+s.hl_amount).toFixed(3) };
    for (const [k, dv] of Object.entries(d.appearance)) traits[`appearance.${k}`] = tr(app[k], dv, `appearance.${k}`);
    traits["wardrobe.outfit"] = tr([...s.outfit], [], "wardrobe.outfit");
    traits["wardrobe.colors"] = tr({ ...s.colors }, {}, "wardrobe.colors");
    return { schema: this.meta.dna.schema, version: this.meta.dna.version,
      identity: { name: s.name || "studio_character", age_years: Math.max(18, +s.age || 30), preset: s.preset },
      traits, sources: [], regions: {}, reconstruction: null,
      history: [{ op: "character_studio_export", note: "values edited interactively; regenerate exact geometry with the Python engine" }] };
  }
  fromDNA(dna) {
    if (dna.schema !== this.meta.dna.schema) throw new Error("This file is not Character DNA (forge.character-dna).");
    if (!(dna.identity && dna.identity.age_years >= 18)) throw new Error("Character DNA must describe an adult (age 18 or older).");
    this._before = this.snapshot();
    const t = dna.traits, s = this.state, clamped = [];
    for (const k of Object.keys(this.man.params)) if (t[k]) {
      const pe = this.man.params[k], v = t[k].value;
      if (v < pe.min || v > pe.max) clamped.push(k);
      s.params[k] = Math.max(pe.min, Math.min(pe.max, v)); s.locks[k] = !!t[k].locked;
    }
    const a = (k, d) => (t[`appearance.${k}`] ? t[`appearance.${k}`].value : d);
    s.skin_tone = a("skin_tone", s.skin_tone); s.undertone = a("undertone", s.undertone); s.eye = a("eye_color", s.eye);
    s.hair_style = this.meta.hair_styles.includes(a("hair_style", s.hair_style)) ? a("hair_style", s.hair_style) : "short";
    s.hair_color = a("hair_color", s.hair_color);
    s.hl_color = a("hair_highlight_color", s.hl_color); s.hl_amount = a("hair_highlight_amount", 0);
    if (t["wardrobe.outfit"]) s.outfit = t["wardrobe.outfit"].value.filter((g) => this.meta.garments.includes(g));
    if (t["wardrobe.colors"]) s.colors = { ...t["wardrobe.colors"].value };
    s.name = dna.identity.name; s.age = dna.identity.age_years;
    s.preset = this.man.presets[dna.identity.preset] ? dna.identity.preset : "neutral";
    this.enforceCoverage(); this.commit(); this.syncUI(); this.dirtyGeo = true; this._resetPhys = true;
    const prov = {}; for (const v of Object.values(t)) prov[v.provenance] = (prov[v.provenance] || 0) + 1;
    setStatus(`Loaded ${s.name}: ${Object.entries(prov).map(([k, v]) => `${v} ${k}`).join(", ")}` +
      (clamped.length ? `. ${clamped.length} value(s) were outside the studio range and were clamped.` : "."));
  }
  // -------------------------------------------------------------- UI
  buildUI() {
    for (const tab of ["body", "face"]) {
      const host = $(`#tab-${tab}`);
      for (const [title, keys] of GROUPS[tab]) {
        const fs = document.createElement("fieldset"); fs.innerHTML = `<legend>${title}</legend>`;
        for (const n of keys) {
          const k = `${tab}.${n}`, pe = this.man.params[k]; if (!pe) continue;
          const row = document.createElement("div"); row.className = "slider";
          const step = (pe.max - pe.min) / 200;
          row.innerHTML = `<label for="s-${k}">${LABELS[n] || n}</label><output id="o-${k}"></output>
            <button type="button" class="lock" id="l-${k}" aria-pressed="false" title="Lock: randomize and DNA regeneration keep this value">lock</button>
            <input type="range" id="s-${k}" min="${pe.min}" max="${pe.max}" step="${step}">`;
          fs.append(row);
          const inp = row.querySelector("input");
          inp.addEventListener("input", () => { this.setParam(k, +inp.value); row.querySelector("output").textContent = this.fmt(k, +inp.value); });
          inp.addEventListener("change", () => this.commit());
          inp.addEventListener("dblclick", () => { this.setParam(k, pe.default); this.commit(); this.syncUI(); });
          row.querySelector(".lock").addEventListener("click", (e) => {
            this.state.locks[k] = !this.state.locks[k]; e.target.setAttribute("aria-pressed", this.state.locks[k]); });
        }
        host.append(fs);
      }
    }
    // presets & actions
    document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => this.applyPreset(b.dataset.preset)));
    $("#randomize").addEventListener("click", () => this.randomize());
    $("#undo").addEventListener("click", () => this.undo()); $("#redo").addEventListener("click", () => this.redo());
    document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); } });
    document.querySelectorAll("[data-focus]").forEach((b) => b.addEventListener("click", () => this.focus(b.dataset.focus)));
    // tabs
    document.querySelectorAll("[role=tab]").forEach((t) => t.addEventListener("click", () => {
      document.querySelectorAll("[role=tab]").forEach((x) => x.setAttribute("aria-selected", x === t));
      document.querySelectorAll("[role=tabpanel]").forEach((p) => (p.hidden = p.id !== t.getAttribute("aria-controls")));
    }));
    // look
    const bind = (id, key, conv = (v) => v, evt = "input") => $(id).addEventListener(evt, (e) => { this._before ||= this.snapshot();
      this.state[key] = conv(e.target.value); this.dirtyGeo = true; if (evt === "change") this.commit(); });
    bind("#skin", "skin_tone", Number); bind("#under", "undertone", Number);
    for (const id of ["#skin", "#under"]) $(id).addEventListener("input", (e) => { e.target.parentElement.querySelector("output").textContent = (+e.target.value).toFixed(2); });
    $("#skin").addEventListener("change", () => this.commit()); $("#under").addEventListener("change", () => this.commit());
    const eye = $("#eye"); for (const k of Object.keys(this.meta.eye_colors)) eye.append(new Option(k.replace("_", " "), k));
    bind("#eye", "eye", String, "change");
    const hs = $("#hairstyle"); for (const k of this.meta.hair_styles) hs.append(new Option(HAIR_LABELS[k] || k, k));
    bind("#hairstyle", "hair_style", String, "change"); bind("#haircolor", "hair_color", String, "change");
    bind("#hlcolor", "hl_color", String, "change"); bind("#hlamount", "hl_amount", Number);
    $("#hlamount").addEventListener("input", (e) => { $("#hlamount-o").textContent = (+e.target.value).toFixed(2); });
    $("#hlamount").addEventListener("change", () => this.commit());
    // outfit
    const oh = $("#outfit");
    for (const g of this.meta.garments) {
      const row = document.createElement("div"); row.className = "garment";
      row.innerHTML = `<label><input type="checkbox" id="g-${g}"> ${g}</label><input type="color" id="c-${g}" aria-label="${g} color">`;
      oh.append(row);
      row.querySelector("input[type=checkbox]").addEventListener("change", (e) => {
        this._before = this.snapshot();
        const set = new Set(this.state.outfit); e.target.checked ? set.add(g) : set.delete(g); this.state.outfit = [...set];
        this.enforceCoverage(); this.commit(); this.syncUI(); this.dirtyGeo = true; });
      row.querySelector("input[type=color]").addEventListener("change", (e) => { this._before = this.snapshot();
        this.state.colors[g] = e.target.value; this.commit(); this.dirtyGeo = true; });
    }
    // expressions
    const eh = $("#expressions");
    for (const e of this.man.expressions) {
      const row = document.createElement("div"); row.className = "slider";
      row.innerHTML = `<label for="e-${e.name}">${e.name.replace("_", " ")}</label><output id="eo-${e.name}">0.00</output><span></span>
        <input type="range" id="e-${e.name}" min="0" max="1" step="0.01" value="0">`;
      eh.append(row);
      row.querySelector("input").addEventListener("input", (ev) => { this.state.expr[e.name] = +ev.target.value;
        row.querySelector("output").textContent = (+ev.target.value).toFixed(2); this.dirtyGeo = true; });
    }
    // pose & animation
    const ps = $("#pose"); for (const k of Object.keys(POSES)) ps.append(new Option(k, k));
    ps.addEventListener("change", (e) => { this.state.pose = e.target.value; this._resetPhys = true; });
    const cs = $("#clip"); cs.append(new Option("none", "none")); for (const k of Object.keys(this.clips)) cs.append(new Option(k.replace("_", " "), k));
    cs.addEventListener("change", (e) => { this.state.clip = e.target.value; this.clipT = 0; this._resetPhys = true; });
    $("#play").addEventListener("click", (e) => { this.playing = !this.playing; e.target.textContent = this.playing ? "Pause" : "Play";
      e.target.setAttribute("aria-pressed", this.playing); });
    $("#physics").addEventListener("change", (e) => { this.phys.on = e.target.checked; this._resetPhys = true; });
    $("#freq").addEventListener("input", (e) => { this.phys.freq = +e.target.value; $("#freq-o").textContent = `${(+e.target.value).toFixed(1)} Hz`; });
    $("#damp").addEventListener("input", (e) => { this.phys.damp = +e.target.value; $("#damp-o").textContent = (+e.target.value).toFixed(2); });
    $("#bounce").addEventListener("click", () => { this.kick = [0, 60, 0]; });
    // file
    $("#name").addEventListener("change", (e) => { this.state.name = e.target.value.replace(/[^\w.-]+/g, "_") || "studio_character"; });
    $("#age").addEventListener("change", (e) => { const a = Math.max(18, +e.target.value || 30); this.state.age = a; e.target.value = a; });
    $("#dna-copy").addEventListener("click", async () => {
      const txt = JSON.stringify(this.toDNA(), null, 1);
      try { await navigator.clipboard.writeText(txt); setStatus("Character DNA copied. Save it as a .dna.json file and run: python3 -m forge_character_forge export <file> --out character.glb"); }
      catch { $("#dna-text").value = txt; $("#dna-text").hidden = false; $("#dna-text").select(); setStatus("Clipboard unavailable: the DNA is shown below, selected for copying."); }
    });
    $("#dna-save").addEventListener("click", () => this.offerFile(`${this.state.name}.dna.json`, JSON.stringify(this.toDNA(), null, 1)));
    $("#glb-export").addEventListener("click", () => { const bytes = this.exportBytes();
      setStatus(`Built ${(bytes.length / 1e6).toFixed(1)} MB GLB in the browser.`);
      this.offerFile(`${this.state.name}.glb`, bytes, `${this.state.name}_glb.zip`); });
    document.querySelectorAll("[data-drag]").forEach((b) => b.addEventListener("click", () => {
      this.spin.mode = b.dataset.drag; document.querySelectorAll("[data-drag]").forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
    $("#intensity").addEventListener("input", (e) => { this.phys.intensity = +e.target.value; $("#intensity-o").textContent = `${(+e.target.value).toFixed(2)}×`; });
    $("#dna-load").addEventListener("change", async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try { this.fromDNA(JSON.parse(await f.text())); } catch (err) { setStatus(`Could not load DNA: ${err.message}`); }
      e.target.value = "";
    });
    $("#exact").addEventListener("click", () => this.exactBuild());
    this.syncUI();
    this.probeServer();
  }
  fmt(k, v) { return k === "body.height_m" ? `${v.toFixed(2)} m` : v.toFixed(2); }
  syncUI() {
    for (const k of Object.keys(this.man.params)) {
      const inp = document.getElementById(`s-${k}`); if (!inp) continue;
      inp.value = this.state.params[k]; document.getElementById(`o-${k}`).textContent = this.fmt(k, this.state.params[k]);
      document.getElementById(`l-${k}`).setAttribute("aria-pressed", !!this.state.locks[k]);
    }
    $("#skin").value = this.state.skin_tone; $("#under").value = this.state.undertone; $("#eye").value = this.state.eye;
    for (const id of ["#skin", "#under"]) $(id).parentElement.querySelector("output").textContent = (+$(id).value).toFixed(2);
    $("#hairstyle").value = this.state.hair_style; $("#haircolor").value = this.state.hair_color;
    $("#hlcolor").value = this.state.hl_color; $("#hlamount").value = this.state.hl_amount; $("#hlamount-o").textContent = (+this.state.hl_amount).toFixed(2);
    for (const g of this.meta.garments) {
      document.getElementById(`g-${g}`).checked = this.state.outfit.includes(g);
      const c = this.state.colors[g] || lin2hex(this.meta.garment_colors[g]); document.getElementById(`c-${g}`).value = c;
    }
    document.querySelectorAll("[data-preset]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.preset === this.state.preset));
    $("#name").value = this.state.name; $("#age").value = this.state.age;
    $("#pose").value = this.state.pose; $("#clip").value = this.state.clip;
  }
  saveFile(name, text, type) {
    try {
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name;
      document.body.append(a); a.click(); a.remove();
      setStatus(`Saved ${name} (if your browser blocked the download, use Copy DNA instead).`);
    } catch { setStatus("Download unavailable here: use Copy DNA."); }
  }
  async probeServer() {
    try { const r = await fetch("api/health", { cache: "no-store" }); if (r.ok) { this.server = true; $("#exact").hidden = false; $("#server-note").textContent = "Engine server connected: exact build and GLB export available."; } }
    catch { /* static hosting: no engine server */ }
  }
  async exactBuild() {
    setStatus("Building exact geometry with the Python engine (about 40 s)...");
    try {
      const r = await fetch("api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(this.toDNA()) });
      const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText);
      setStatus(`Exported ${j.path} (${(j.bytes / 1e6).toFixed(1)} MB), validation ${j.validation.ok ? "passed" : "FAILED"}.`);
      if (j.download) { const a = document.createElement("a"); a.href = j.download; a.download = j.path.split("/").pop(); a.click(); }
    } catch (err) { setStatus(`Exact build failed: ${err.message}`); }
  }
}

// ---------------------------------------------------------------- boot
(async () => {
  try {
    setStatus("Loading character data...");
    const meta = await (await fetch("studio_meta.json")).json();
    const pack = await loadPack("studio_pack.bin");
    let clips = null; try { const r = await fetch("studio_clips.json"); if (r.ok) clips = await r.json(); } catch { /* use the pack's clips */ }
    window.studio = new Studio(meta, pack, clips);
    setStatus("Drag to rotate · scroll or pinch to zoom · right-drag or shift-drag to pan · double-click a slider to reset it");
    document.body.dataset.ready = "1";
  } catch (err) {
    setStatus(`Character Studio could not start: ${err.message}`);
    document.body.dataset.ready = "error";
    console.error(err);
  }
})();
