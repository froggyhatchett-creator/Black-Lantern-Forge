// Independent GLB loader + skinning evaluator (Node.js, no dependencies).
//
// Written separately from the Python exporter: it parses the GLB container,
// decodes accessors, walks the glTF node hierarchy (TRS), samples an animation
// at a keyframe, builds joint matrices (global * inverseBind), applies linear
// blend skinning to every skinned mesh, and reports structural facts plus the
// deformation it computed.  With --expect <json> it compares body vertices
// against positions produced by the Python pipeline for the same frame.
//
// usage: node glb_independent_check.mjs file.glb [--anim walk --frame 8] [--expect check.json]
import fs from "node:fs";

const args = process.argv.slice(2);
const file = args[0];
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const buf = fs.readFileSync(file);
const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m })); process.exit(1); };
if (buf.readUInt32LE(0) !== 0x46546c67) fail("bad magic");
if (buf.readUInt32LE(4) !== 2) fail("bad version");
if (buf.readUInt32LE(8) !== buf.length) fail("length mismatch");
const jlen = buf.readUInt32LE(12);
if (buf.readUInt32LE(16) !== 0x4e4f534a) fail("missing JSON chunk");
const gltf = JSON.parse(buf.subarray(20, 20 + jlen).toString("utf8"));
const binStart = 20 + jlen + 8;
if (buf.readUInt32LE(20 + jlen + 4) !== 0x004e4942) fail("missing BIN chunk");
const bin = buf.subarray(binStart, binStart + buf.readUInt32LE(20 + jlen));

const NC = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };
function acc(i) {
  const a = gltf.accessors[i], v = gltf.bufferViews[a.bufferView];
  const n = NC[a.type], off = (v.byteOffset || 0) + (a.byteOffset || 0), cnt = a.count * n;
  const ab = bin.buffer.slice(bin.byteOffset + off, bin.byteOffset + off + cnt * ({ 5126: 4, 5125: 4, 5123: 2, 5121: 1 }[a.componentType]));
  const arr = a.componentType === 5126 ? new Float32Array(ab) : a.componentType === 5125 ? new Uint32Array(ab)
    : a.componentType === 5123 ? new Uint16Array(ab) : new Uint8Array(ab);
  return { arr, n, count: a.count };
}

// 4x4 column-major helpers
const ident = () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
function mul(a, b) { const o = new Array(16).fill(0); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; }
function trs(t = [0, 0, 0], q = [0, 0, 0, 1], s = [1, 1, 1]) {
  const [x, y, z, w] = q;
  return [(1 - 2 * (y * y + z * z)) * s[0], (2 * (x * y + z * w)) * s[0], (2 * (x * z - y * w)) * s[0], 0,
    (2 * (x * y - z * w)) * s[1], (1 - 2 * (x * x + z * z)) * s[1], (2 * (y * z + x * w)) * s[1], 0,
    (2 * (x * z + y * w)) * s[2], (2 * (y * z - x * w)) * s[2], (1 - 2 * (x * x + y * y)) * s[2], 0,
    t[0], t[1], t[2], 1];
}

// animation sampling (LINEAR; slerp for rotations)
const animName = opt("--anim", null), frame = parseInt(opt("--frame", "0"), 10);
const overrides = {};
let animTime = null;
if (animName) {
  const an = (gltf.animations || []).find((a) => a.name === animName);
  if (!an) fail(`animation ${animName} not found`);
  for (const ch of an.channels) {
    const s = an.samplers[ch.sampler];
    const tin = acc(s.input).arr, out = acc(s.output);
    const k = Math.min(frame, tin.length - 1);
    animTime = tin[k];
    const val = Array.from(out.arr.slice(k * out.n, k * out.n + out.n));
    (overrides[ch.target.node] ||= {})[ch.target.path] = val;
  }
}
const parent = {};
gltf.nodes.forEach((n, i) => (n.children || []).forEach((c) => (parent[c] = i)));
const world = [];
function W(i) {
  if (world[i]) return world[i];
  const n = gltf.nodes[i], o = overrides[i] || {};
  const L = n.matrix ? n.matrix : trs(o.translation || n.translation, o.rotation || n.rotation, o.scale || n.scale);
  return (world[i] = parent[i] === undefined ? L : mul(W(parent[i]), L));
}
const skin = gltf.skins[0];
const ibm = acc(skin.inverseBindMatrices).arr;
const jointMats = skin.joints.map((j, k) => mul(W(j), Array.from(ibm.slice(k * 16, k * 16 + 16))));

const report = { ok: true, file, meshes: {}, joints: skin.joints.length, animations: (gltf.animations || []).map((a) => a.name),
  profile: gltf.asset?.extras?.forge?.profile, anim: animName, frame, time: animTime };
let posedBody = null;
let maxWeightErr = 0;
for (const node of gltf.nodes) {
  if (node.mesh === undefined) continue;
  const mesh = gltf.meshes[node.mesh];
  for (const p of mesh.primitives) {
    const pos = acc(p.attributes.POSITION), J = acc(p.attributes.JOINTS_0), Wt = acc(p.attributes.WEIGHTS_0), idx = acc(p.indices);
    const out = new Float64Array(pos.count * 3);
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9], moved = 0;
    for (let v = 0; v < pos.count; v++) {
      let m = new Array(16).fill(0), ws = 0;
      for (let k = 0; k < 4; k++) {
        const w = Wt.arr[v * 4 + k]; ws += w;
        if (!w) continue;
        const jm = jointMats[J.arr[v * 4 + k]];
        for (let e = 0; e < 16; e++) m[e] += w * jm[e];
      }
      maxWeightErr = Math.max(maxWeightErr, Math.abs(ws - 1));
      const x = pos.arr[v * 3], y = pos.arr[v * 3 + 1], z = pos.arr[v * 3 + 2];
      const X = m[0] * x + m[4] * y + m[8] * z + m[12], Y = m[1] * x + m[5] * y + m[9] * z + m[13], Z = m[2] * x + m[6] * y + m[10] * z + m[14];
      out[v * 3] = X; out[v * 3 + 1] = Y; out[v * 3 + 2] = Z;
      const d = Math.hypot(X - x, Y - y, Z - z); if (d > 1e-4) moved++;
      lo = [Math.min(lo[0], X), Math.min(lo[1], Y), Math.min(lo[2], Z)]; hi = [Math.max(hi[0], X), Math.max(hi[1], Y), Math.max(hi[2], Z)];
    }
    let maxIndex = 0; for (const i of idx.arr) maxIndex = Math.max(maxIndex, i);
    report.meshes[mesh.name] = { vertices: pos.count, triangles: idx.count / 3, indexInRange: maxIndex < pos.count,
      morphTargets: (p.targets || []).length, posedBBoxMin: lo.map((v) => +v.toFixed(4)), posedBBoxMax: hi.map((v) => +v.toFixed(4)),
      verticesMovedBySkinning: moved };
    if (mesh.name === "body") posedBody = out;
  }
}
report.maxWeightSumError = maxWeightErr;
const expect = opt("--expect", null);
if (expect) {
  const e = JSON.parse(fs.readFileSync(expect, "utf8"));
  let maxErr = 0;
  e.indices.forEach((vi, k) => {
    const d = Math.hypot(posedBody[vi * 3] - e.positions[k][0], posedBody[vi * 3 + 1] - e.positions[k][1], posedBody[vi * 3 + 2] - e.positions[k][2]);
    maxErr = Math.max(maxErr, d);
  });
  report.comparedVertices = e.indices.length;
  report.maxPositionErrorVsPython_m = maxErr;
  if (maxErr > 1e-4) { report.ok = false; report.error = "independent skinning disagrees with Python pipeline"; }
}
for (const m of Object.values(report.meshes)) if (!m.indexInRange) { report.ok = false; report.error = "index out of range"; }
if (maxWeightErr > 1e-4) { report.ok = false; report.error = "weights do not sum to 1"; }
console.log(JSON.stringify(report, null, 1));
process.exit(report.ok ? 0 : 1);
