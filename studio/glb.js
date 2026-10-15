// In-browser GLB export of the current studio character (contract forge.character-forge.glb v1, public profile).
// Geometry is the studio's linear-basis evaluation; asset extras say so ("exact": false). Exact geometry comes
// from the Python engine (`python3 -m forge_character_forge export`).
"use strict";

const FLOAT = 5126, USHORT = 5123, UINT = 5125;

class Bin {
  constructor() { this.chunks = []; this.len = 0; this.views = []; this.accessors = []; }
  view(bytes, target) {
    const pad = (4 - (this.len % 4)) % 4; if (pad) { this.chunks.push(new Uint8Array(pad)); this.len += pad; }
    const v = { buffer: 0, byteOffset: this.len, byteLength: bytes.byteLength }; if (target) v.target = target;
    this.chunks.push(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)); this.len += bytes.byteLength;
    this.views.push(v); return this.views.length - 1;
  }
  acc(arr, type, comp, n, { target = 34962, minmax = false, normalized = false } = {}) {
    const a = { bufferView: this.view(arr, target), componentType: comp, count: arr.length / n, type };
    if (minmax) { const mn = Array(n).fill(Infinity), mx = Array(n).fill(-Infinity);
      for (let i = 0; i < arr.length; i++) { const k = i % n; const v = Math.fround(arr[i]); if (v < mn[k]) mn[k] = v; if (v > mx[k]) mx[k] = v; }
      a.min = mn; a.max = mx; }
    if (normalized) a.normalized = true;
    this.accessors.push(a); return this.accessors.length - 1;
  }
  sparse(count, idx, val) {  // idx Uint32Array (ascending), val Float32Array (n*3)
    const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < val.length; i++) { const k = i % 3, v = Math.fround(val[i]); if (v < mn[k]) mn[k] = v; if (v > mx[k]) mx[k] = v; }
    if (idx.length < count) for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], 0); mx[k] = Math.max(mx[k], 0); }
    this.accessors.push({ componentType: FLOAT, count, type: "VEC3", min: mn, max: mx,
      sparse: { count: idx.length, indices: { bufferView: this.view(idx), componentType: UINT }, values: { bufferView: this.view(val) } } });
    return this.accessors.length - 1;
  }
  bytes() { const out = new Uint8Array(this.len + ((4 - (this.len % 4)) % 4)); let o = 0; for (const c of this.chunks) { out.set(c, o); o += c.length; } return out; }
}

export function exportGLB(st) {
  const b = new Bin(), skel = st.skel, J = st.J, rest = st.rest, names = skel.names;
  const nodes = [];
  for (let j = 0; j < J; j++) {
    const p = skel.parents[j];
    const t = p < 0 ? [rest[j * 3], rest[j * 3 + 1], rest[j * 3 + 2]] : [0, 1, 2].map((k) => rest[j * 3 + k] - rest[p * 3 + k]);
    const node = { name: names[j], translation: t.map(Math.fround) };
    const kids = []; for (let i = 0; i < J; i++) if (skel.parents[i] === j) kids.push(i);
    if (kids.length) node.children = kids;
    const ex = {}; if (skel.humanoid[names[j]]) ex.humanoid = skel.humanoid[names[j]]; if (skel.physics.includes(names[j])) ex.secondary_motion = true;
    if (Object.keys(ex).length) node.extras = ex;
    nodes.push(node);
  }
  const ibm = new Float32Array(J * 16);
  for (let j = 0; j < J; j++) { const o = j * 16; ibm[o] = ibm[o + 5] = ibm[o + 10] = ibm[o + 15] = 1; ibm[o + 12] = -rest[j * 3]; ibm[o + 13] = -rest[j * 3 + 1]; ibm[o + 14] = -rest[j * 3 + 2]; }
  const skin = { name: "forge_skin", joints: [...Array(J).keys()], inverseBindMatrices: b.acc(ibm, "MAT4", FLOAT, 16, { target: 0 }), skeleton: 0 };
  delete b.views[b.accessors[skin.inverseBindMatrices].bufferView].target;
  const materials = [], matIndex = new Map(), meshes = [], meshNodes = [];
  const material = (key, def) => { if (!matIndex.has(key)) { materials.push(def); matIndex.set(key, materials.length - 1); } return matIndex.get(key); };
  for (const [name, P] of Object.entries(st.parts)) {
    if (!P.g.visible) continue;
    const n = P.cur.length / 3;
    const attrs = { POSITION: b.acc(P.cur, "VEC3", FLOAT, 3, { minmax: true }), NORMAL: b.acc(P.nrm, "VEC3", FLOAT, 3) };
    if (P.material === "skin" || P.material === "teeth") {
      const col = new Float32Array(n * 3), base = P.g.base;
      for (let i = 0; i < n * 3; i++) col[i] = Math.min(1, Math.max(0, (P.tint ? P.tint[i] : 1) * base[i % 3]));
      attrs.COLOR_0 = b.acc(col, "VEC3", FLOAT, 3);
    }
    const streaks = P.material === "hair" && P.hl && P.g.detail > 0;  // highlights: hair color + streaks per vertex
    if (streaks) {
      const col = new Float32Array(n * 3), a = P.g.base, h = P.g.iris;
      for (let v = 0; v < n; v++) { const m = (P.hl[v] / 255) * P.g.detail; for (let c = 0; c < 3; c++) col[v * 3 + c] = a[c] * (1 - m) + h[c] * m; }
      attrs.COLOR_0 = b.acc(col, "VEC3", FLOAT, 3);
    }
    const jj = new Uint16Array(P.jnt.length); for (let i = 0; i < jj.length; i++) jj[i] = P.jnt[i];
    const ww = new Float32Array(P.wgt.length);
    for (let v = 0; v < n; v++) { let s = 0; for (let k = 0; k < 4; k++) s += P.wgt[v * 4 + k]; for (let k = 0; k < 4; k++) ww[v * 4 + k] = P.wgt[v * 4 + k] / s; }
    attrs.JOINTS_0 = b.acc(jj, "VEC4", USHORT, 4); attrs.WEIGHTS_0 = b.acc(ww, "VEC4", FLOAT, 4);
    const isTex = P.material === "skin" || P.material === "teeth" || streaks;
    // brow/lash strands are procedural in the studio; the browser GLB carries them as soft translucent cards
    const alpha = P.g.kind === 4 ? 0.08 : P.g.kind === 5 ? 0.6 : 1;
    const m = material(streaks ? "hair_highlights" : P.material, { name: streaks ? "hair_highlights" : P.material, doubleSided: !!P.g.double,
      ...(P.g.blend ? { alphaMode: "BLEND" } : {}),
      pbrMetallicRoughness: { baseColorFactor: isTex ? [1, 1, 1, 1] : [...P.g.base, alpha], metallicFactor: 0, roughnessFactor: P.g.rough } });
    const prim = { attributes: attrs, indices: b.acc(P.idx, "SCALAR", UINT, 1, { target: 34963 }), material: m, mode: 4 };
    const mesh = { name, primitives: [prim] };
    if (name === "body" && st.expressions.length) {
      prim.targets = []; const tn = [];
      for (const e of st.expressions) { const { idx, val } = st.decodeSparse(e.body, n); prim.targets.push({ POSITION: b.sparse(n, idx, val) }); tn.push(e.name); }
      mesh.weights = tn.map(() => 0); mesh.extras = { targetNames: tn };
    }
    meshes.push(mesh);
    nodes.push({ name, mesh: meshes.length - 1, skin: 0 }); meshNodes.push(nodes.length - 1);
  }
  nodes.push({ name: st.name, children: [0, ...meshNodes] });
  const animations = [];
  for (const c of st.clips) {
    const times = new Float32Array(c.frames); for (let i = 0; i < c.frames; i++) times[i] = i / c.fps;
    const ti = b.acc(times, "SCALAR", FLOAT, 1, { target: 0, minmax: true }); delete b.views[b.accessors[ti].bufferView].target;
    const samplers = [], channels = [];
    for (const [jn, q] of Object.entries(c.rot)) {
      const j = names.indexOf(jn); if (j < 0) continue;
      const out = Float32Array.from(q);
      for (let i = 1; i < c.frames; i++) { let d = 0; for (let k = 0; k < 4; k++) d += out[i * 4 + k] * out[(i - 1) * 4 + k]; if (d < 0) for (let k = 0; k < 4; k++) out[i * 4 + k] *= -1; }
      const oi = b.acc(out, "VEC4", FLOAT, 4, { target: 0 }); delete b.views[b.accessors[oi].bufferView].target;
      samplers.push({ input: ti, output: oi, interpolation: "LINEAR" }); channels.push({ sampler: samplers.length - 1, target: { node: j, path: "rotation" } });
    }
    if (c.root) {
      const pel = names.indexOf("pelvis"), par = skel.parents[pel];
      const tr = new Float32Array(c.frames * 3);
      for (let i = 0; i < c.frames; i++) for (let k = 0; k < 3; k++) tr[i * 3 + k] = rest[pel * 3 + k] - rest[par * 3 + k] + c.root[i * 3 + k] * st.u;
      const oi = b.acc(tr, "VEC3", FLOAT, 3, { target: 0 }); delete b.views[b.accessors[oi].bufferView].target;
      samplers.push({ input: ti, output: oi, interpolation: "LINEAR" }); channels.push({ sampler: samplers.length - 1, target: { node: pel, path: "translation" } });
    }
    animations.push({ name: c.name, samplers, channels });
  }
  const gltf = {
    asset: { version: "2.0", generator: "Black Lantern Character Studio (browser export)", extras: { forge: {
      contract: { id: "forge.character-forge.glb", version: 1 }, profile: "public", units: "meters", up_axis: "+Y", front_axis: "+Z",
      handedness: "right", joint_rest_orientation: "identity", dev_only_parts: [], coverage: st.coverage, exact: false,
      geometry_source: "Character Studio linear morph basis over exact Python builds; regenerate exact geometry from the DNA",
      dna: st.dna } } },
    scene: 0, scenes: [{ name: "character", nodes: [nodes.length - 1] }], nodes, meshes, skins: [skin], materials, animations,
    accessors: b.accessors, bufferViews: b.views, buffers: [{ byteLength: 0 }],
  };
  const bin = b.bytes(); gltf.buffers[0].byteLength = bin.length;
  let json = new TextEncoder().encode(JSON.stringify(gltf));
  const jpad = (4 - (json.length % 4)) % 4; if (jpad) { const j2 = new Uint8Array(json.length + jpad).fill(0x20); j2.set(json); json = j2; }
  const total = 12 + 8 + json.length + 8 + bin.length, out = new Uint8Array(total), dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546c67, true); dv.setUint32(4, 2, true); dv.setUint32(8, total, true);
  dv.setUint32(12, json.length, true); dv.setUint32(16, 0x4e4f534a, true); out.set(json, 20);
  dv.setUint32(20 + json.length, bin.length, true); dv.setUint32(24 + json.length, 0x004e4942, true); out.set(bin, 28 + json.length);
  return out;
}

// Minimal store-only zip (so the artifact download allowlist, which has .zip but not .glb, can carry the GLB).
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(d) { let c = 0xffffffff; for (let i = 0; i < d.length; i++) c = CRC[(c ^ d[i]) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
export function zipFiles(files) {  // [{name, data: Uint8Array}]
  const enc = new TextEncoder(), parts = [], central = []; let off = 0;
  for (const f of files) {
    const nm = enc.encode(f.name), crc = crc32(f.data), h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint32(14, crc, true); h.setUint32(18, f.data.length, true);
    h.setUint32(22, f.data.length, true); h.setUint16(26, nm.length, true);
    parts.push(new Uint8Array(h.buffer), nm, f.data);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint32(16, crc, true);
    c.setUint32(20, f.data.length, true); c.setUint32(24, f.data.length, true); c.setUint16(28, nm.length, true); c.setUint32(42, off, true);
    central.push(new Uint8Array(c.buffer), nm);
    off += 30 + nm.length + f.data.length;
  }
  const csize = central.reduce((a, c) => a + c.length, 0), e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, csize, true); e.setUint32(16, off, true);
  const all = [...parts, ...central, new Uint8Array(e.buffer)], out = new Uint8Array(all.reduce((a, c) => a + c.length, 0));
  let o = 0; for (const c of all) { out.set(c, o); o += c.length; } return out;
}
