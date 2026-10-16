// Independent GLB playback (Node.js, no dependencies, separate from the studio's exporter and renderer).
//
// Parses the GLB, samples an animation clip at given frames (LINEAR / slerp between keys), applies morph targets
// (sparse or dense, e.g. the blink) with given weights, then linear blend skinning, and writes the posed positions
// of selected meshes as float32 files plus a JSON index. Python renders and measures them (tools/v3_phase3d.py).
//
// usage: node glb_playback.mjs file.glb outdir --anim walk --frames 0,8,16 --morph blink_l=1,blink_r=1 [--meshes body,eye_l]
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const [file, outdir] = args;
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const buf = fs.readFileSync(file);
if (buf.readUInt32LE(0) !== 0x46546c67 || buf.readUInt32LE(4) !== 2 || buf.readUInt32LE(8) !== buf.length) throw new Error("not a GLB 2.0 file");
const jlen = buf.readUInt32LE(12), gltf = JSON.parse(buf.subarray(20, 20 + jlen).toString("utf8"));
const bin = buf.subarray(20 + jlen + 8, 20 + jlen + 8 + buf.readUInt32LE(20 + jlen));
const NC = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 }, SZ = { 5126: 4, 5125: 4, 5123: 2, 5121: 1 };
const typed = (ct, ab) => (ct === 5126 ? new Float32Array(ab) : ct === 5125 ? new Uint32Array(ab) : ct === 5123 ? new Uint16Array(ab) : new Uint8Array(ab));
const view = (bv, ct, count) => { const v = gltf.bufferViews[bv], o = bin.byteOffset + (v.byteOffset || 0); return typed(ct, bin.buffer.slice(o, o + count * SZ[ct])); };
function acc(i) {  // dense values of an accessor, sparse accessors expanded
  const a = gltf.accessors[i], n = NC[a.type];
  let arr = a.bufferView !== undefined ? Float32Array.from(view(a.bufferView, a.componentType, a.count * n)) : new Float32Array(a.count * n);
  if (a.componentType !== 5126 && a.bufferView !== undefined) arr = view(a.bufferView, a.componentType, a.count * n);
  if (a.sparse) {
    const idx = view(a.sparse.indices.bufferView, a.sparse.indices.componentType, a.sparse.count), val = view(a.sparse.values.bufferView, 5126, a.sparse.count * n);
    for (let k = 0; k < idx.length; k++) for (let c = 0; c < n; c++) arr[idx[k] * n + c] = val[k * n + c];
  }
  return { arr, n, count: a.count };
}
const mul = (a, b) => { const o = new Array(16).fill(0); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; };
const trs = (t = [0, 0, 0], q = [0, 0, 0, 1], s = [1, 1, 1]) => { const [x, y, z, w] = q;
  return [(1 - 2 * (y * y + z * z)) * s[0], (2 * (x * y + z * w)) * s[0], (2 * (x * z - y * w)) * s[0], 0, (2 * (x * y - z * w)) * s[1], (1 - 2 * (x * x + z * z)) * s[1],
    (2 * (y * z + x * w)) * s[1], 0, (2 * (x * z + y * w)) * s[2], (2 * (y * z - x * w)) * s[2], (1 - 2 * (x * x + y * y)) * s[2], 0, t[0], t[1], t[2], 1]; };
function slerp(a, b, t) { let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]; if (d < 0) { b = b.map((v) => -v); d = -d; }
  if (d > 0.9995) { const r = a.map((v, i) => v + (b[i] - v) * t), l = Math.hypot(...r); return r.map((v) => v / l); }
  const th = Math.acos(d), s = Math.sin(th); return a.map((v, i) => (Math.sin((1 - t) * th) * v + Math.sin(t * th) * b[i]) / s); }

const animName = opt("--anim", null), frames = opt("--frames", "0").split(",").map(Number);
const morph = Object.fromEntries((opt("--morph", "") || "").split(",").filter(Boolean).map((kv) => { const [k, v] = kv.split("="); return [k, +v]; }));
const want = opt("--meshes", "body,eye_l,eye_r,cornea_l,cornea_r,lashes,brows").split(",");
const an = animName ? (gltf.animations || []).find((a) => a.name === animName) : null;
if (animName && !an) throw new Error(`animation ${animName} not found`);
const fps = 30;  // the studio exports keyframes at i / 30 s; frames here are sampled by time
const parent = {}; gltf.nodes.forEach((n, i) => (n.children || []).forEach((c) => (parent[c] = i)));
const skin = gltf.skins[0], ibm = acc(skin.inverseBindMatrices).arr;
fs.mkdirSync(outdir, { recursive: true });
const index = { file: path.basename(file), anim: animName, morph, frames: [], meshes: {} };
const meshData = {};
for (const node of gltf.nodes) {
  if (node.mesh === undefined) continue;
  const mesh = gltf.meshes[node.mesh], p = mesh.primitives[0];
  if (!want.includes(mesh.name)) continue;
  const pos = acc(p.attributes.POSITION).arr, base = Float32Array.from(pos);
  const names = (mesh.extras && mesh.extras.targetNames) || [];
  const applied = {};
  (p.targets || []).forEach((t, k) => { const w = morph[names[k]] || 0; if (!w) return; const d = acc(t.POSITION).arr; for (let i = 0; i < base.length; i++) base[i] += w * d[i]; applied[names[k]] = w; });
  meshData[mesh.name] = { base, J: acc(p.attributes.JOINTS_0).arr, W: acc(p.attributes.WEIGHTS_0).arr, idx: acc(p.indices).arr };
  index.meshes[mesh.name] = { vertices: base.length / 3, triangles: meshData[mesh.name].idx.length / 3, morphs_applied: applied, targets: names };
  fs.writeFileSync(path.join(outdir, `${mesh.name}_idx.u4`), Buffer.from(Uint32Array.from(meshData[mesh.name].idx).buffer));
}
for (const f of frames) {
  const ov = {};
  let tsec = 0;
  if (an) {
    tsec = f / fps;
    for (const ch of an.channels) {
      const s = an.samplers[ch.sampler], tin = acc(s.input).arr, out = acc(s.output);
      let i = 0; while (i < tin.length - 2 && tin[i + 1] <= tsec) i++;
      const a = Math.min(1, Math.max(0, (tsec - tin[i]) / (tin[i + 1] - tin[i] || 1)));
      const va = Array.from(out.arr.slice(i * out.n, i * out.n + out.n)), vb = Array.from(out.arr.slice((i + 1) * out.n, (i + 1) * out.n + out.n));
      (ov[ch.target.node] ||= {})[ch.target.path] = ch.target.path === "rotation" ? slerp(va, vb, a) : va.map((v, k) => v + (vb[k] - v) * a);
    }
  }
  const world = [];
  const Wm = (i) => { if (world[i]) return world[i]; const n = gltf.nodes[i], o = ov[i] || {};
    const L = trs(o.translation || n.translation, o.rotation || n.rotation, o.scale || n.scale);
    return (world[i] = parent[i] === undefined ? L : mul(Wm(parent[i]), L)); };
  const JM = skin.joints.map((j, k) => mul(Wm(j), Array.from(ibm.slice(k * 16, k * 16 + 16))));
  for (const [name, m] of Object.entries(meshData)) {
    const n = m.base.length / 3, out = new Float32Array(n * 3);
    for (let v = 0; v < n; v++) {
      const M = new Array(16).fill(0);
      for (let k = 0; k < 4; k++) { const w = m.W[v * 4 + k]; if (!w) continue; const jm = JM[m.J[v * 4 + k]]; for (let e = 0; e < 16; e++) M[e] += w * jm[e]; }
      const x = m.base[v * 3], y = m.base[v * 3 + 1], z = m.base[v * 3 + 2];
      out[v * 3] = M[0] * x + M[4] * y + M[8] * z + M[12]; out[v * 3 + 1] = M[1] * x + M[5] * y + M[9] * z + M[13]; out[v * 3 + 2] = M[2] * x + M[6] * y + M[10] * z + M[14];
    }
    fs.writeFileSync(path.join(outdir, `${name}_f${f}.f4`), Buffer.from(out.buffer));
  }
  const head = skin.joints.findIndex((j) => gltf.nodes[j].name === "head");
  index.frames.push({ frame: f, time: tsec, head_world: [12, 13, 14].map((k) => Wm(skin.joints[head])[k]) });
}
fs.writeFileSync(path.join(outdir, "index.json"), JSON.stringify(index, null, 1));
console.log(JSON.stringify({ ok: true, ...index }));
