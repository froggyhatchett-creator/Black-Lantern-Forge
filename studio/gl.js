// Character Studio renderer: dependency-free WebGL2, GPU linear-blend skinning, character-specific shading.
"use strict";

const VS = `#version 300 es
precision highp float;
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNrm;
layout(location=2) in vec3 aCol;
layout(location=3) in vec2 aUV;
layout(location=4) in vec4 aJnt;
layout(location=5) in vec4 aWgt;
uniform mat4 uJ[80];
uniform mat4 uVP;
out vec3 vPos; out vec3 vNrm; out vec3 vCol; out vec2 vUV; out vec3 vObj;
void main() {
  vec4 w = aWgt / max(aWgt.x + aWgt.y + aWgt.z + aWgt.w, 1e-6);
  mat4 m = uJ[int(aJnt.x)] * w.x + uJ[int(aJnt.y)] * w.y + uJ[int(aJnt.z)] * w.z + uJ[int(aJnt.w)] * w.w;
  vec4 p = m * vec4(aPos, 1.0);
  vPos = p.xyz; vNrm = mat3(m) * aNrm; vCol = aCol; vUV = aUV; vObj = aPos;
  gl_Position = uVP * p;
}`;

const FS = `#version 300 es
precision highp float;
in vec3 vPos; in vec3 vNrm; in vec3 vCol; in vec2 vUV; in vec3 vObj;
uniform vec3 uEye; uniform vec3 uBase; uniform float uRough; uniform float uSpec; uniform float uSSS;
uniform int uKind;   // 0 skin 1 cloth 2 hair 3 eye 4 cornea 5 card 6 teeth 7 ground
uniform float uAlpha; uniform vec3 uIris; uniform float uDetail; uniform vec3 uEyeC;
out vec4 o;
float h3(vec3 p){ p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float noise(vec3 x){ vec3 i = floor(x), f = fract(x); f = f*f*(3.0-2.0*f);
  return mix(mix(mix(h3(i), h3(i+vec3(1,0,0)), f.x), mix(h3(i+vec3(0,1,0)), h3(i+vec3(1,1,0)), f.x), f.y),
             mix(mix(h3(i+vec3(0,0,1)), h3(i+vec3(1,0,1)), f.x), mix(h3(i+vec3(0,1,1)), h3(i+vec3(1,1,1)), f.x), f.y), f.z); }
vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14), 0.0, 1.0); }
void main() {
  vec3 n = normalize(vNrm);
  vec3 v = normalize(uEye - vPos);
  if (!gl_FrontFacing) n = -n;
  vec3 base = uBase;
  float rough = uRough, spec = uSpec, sss = uSSS, alpha = uAlpha;
  if (uKind == 7) {  // ground disc with soft contact shadow
    float r = length(vPos.xz);
    float sh = smoothstep(0.05, 0.55, length(vPos.xz * vec2(1.0, 1.6)));
    float edge = 1.0 - smoothstep(0.6, 1.4, r);
    o = vec4(base * (0.55 + 0.45 * sh), edge * 0.9); return;
  }
  if (uKind == 0 || uKind == 6) base *= vCol;
  if (uKind == 0 && uDetail > 0.0) {  // procedural skin micro-relief (object space, so it sticks to the skin)
    float e = 0.0006;
    vec3 q = vObj * 900.0;
    float c = noise(q), gx = noise(q + vec3(1.3,0,0)) - c, gy = noise(q + vec3(0,1.3,0)) - c, gz = noise(q + vec3(0,0,1.3)) - c;
    n = normalize(n - uDetail * 0.12 * vec3(gx, gy, gz));
    rough *= 0.9 + 0.2 * noise(vObj * 180.0);
    base *= 0.97 + 0.06 * noise(vObj * 40.0);
  }
  float eyeAO = 1.0;
  if (uKind == 3) {  // eyeball: exact per-pixel angle from the optical axis (rest +z) instead of the faceted UV disk
    vec3 d = normalize(vObj - uEyeC);
    float s = acos(clamp(d.z, -1.0, 1.0)) / 0.5432;          // 1.0 at the iris edge (asin(6.2 mm / 12 mm))
    float ang = atan(d.y, d.x);
    float pr = 0.36;                                          // pupil radius as a fraction of the iris
    float fib = noise(vec3(ang * 38.0, s * 4.0, 1.7)) * 0.6 + noise(vec3(ang * 90.0, s * 9.0, 4.1)) * 0.4;
    vec3 iris = uIris * (0.62 + 0.75 * fib);
    iris *= mix(1.35, 0.7, smoothstep(pr, 0.95, s));          // lighter around the pupil, darker toward the rim
    iris += uIris * 0.55 * exp(-pow((s - 0.56) / 0.07, 2.0)) * (0.6 + 0.4 * fib);   // collarette
    iris *= 1.0 - 0.6 * smoothstep(0.80, 0.97, s);            // limbal ring
    float pupil = smoothstep(pr + 0.035, pr - 0.015, s);
    iris = mix(iris, vec3(0.012, 0.010, 0.010), pupil);
    vec3 sclera = mix(vec3(0.80, 0.77, 0.73), vec3(0.70, 0.58, 0.54), smoothstep(1.4, 3.0, s));
    sclera *= 0.97 + 0.06 * noise(vObj * 900.0);
    base = mix(iris, sclera, smoothstep(0.97, 1.10, s));
    // occlusion: corners sit deep under the lids; the upper lid shades the top of the eye
    eyeAO = mix(1.0, 0.42, smoothstep(1.5, 2.9, s)) * mix(1.0, 0.45, smoothstep(0.0, 0.45, n.y));
    rough = mix(0.35, 0.22, step(1.0, s)); spec = 0.25;
  }
  if (uKind == 5) {  // brow / lash cards: soft slanted strands with varied density, blended (not cut out)
    float along = vUV.x * 150.0 + vUV.y * 2.5;
    float f = fract(along), rnd = fract(sin(floor(along) * 12.9898) * 43758.5453);
    float strand = smoothstep(0.5, 0.05, abs(f - 0.5)) * (0.45 + 0.55 * rnd);
    float edge = smoothstep(0.0, 0.3, vUV.y) * smoothstep(1.0, 0.65, vUV.y);
    float ends = smoothstep(0.0, 0.06, vUV.x) * smoothstep(1.0, 0.8, vUV.x);
    alpha = clamp(strand * edge * ends * 1.3, 0.0, 0.95);
    if (alpha < 0.03) discard;
  }
  if (uKind == 2) {  // highlight streaks: broad per-vertex panels broken into fine strands
    float fine = noise(vec3(vObj.x * 900.0, vObj.y * 30.0, vObj.z * 900.0));
    base = mix(base, uIris, clamp(vCol.r, 0.0, 1.0) * uDetail * (0.35 + 0.65 * fine));
  }
  if (uKind == 2) base *= 0.82 + 0.3 * noise(vec3(vObj.x * 420.0, vObj.y * 18.0, vObj.z * 420.0));  // object-space strands: no UV seams
  vec3 L[3]; vec3 C[3];
  L[0] = normalize(vec3(0.55, 0.65, 0.75)); C[0] = vec3(1.0, 0.95, 0.88) * 2.4;
  L[1] = normalize(vec3(-0.7, 0.25, 0.45)); C[1] = vec3(0.70, 0.80, 1.0) * 0.8;
  L[2] = normalize(vec3(-0.2, 0.5, -0.9));  C[2] = vec3(1.0) * 1.4;
  vec3 col = vec3(0.0);
  float shin = 2.0 / max(pow(rough, 4.0), 1e-3) - 2.0;
  for (int i = 0; i < 3; i++) {
    float ndl = dot(n, L[i]);
    float wrap = sss * 0.5;
    float diff = clamp((ndl + wrap) / (1.0 + wrap), 0.0, 1.0);
    vec3 tint = mix(vec3(1.0), vec3(1.0, 0.6, 0.5), sss * clamp(wrap - ndl, 0.0, 1.0));
    col += base * diff * C[i] * tint * 0.32 * eyeAO;
    vec3 h = normalize(L[i] + v);
    float sp;
    if (uKind == 2) {  // Kajiya-Kay style highlight along the hair flow (roughly vertical)
      vec3 t = vec3(0.0, 1.0, 0.0) - n * n.y; t = length(t) < 0.2 ? normalize(vec3(0.0, 0.0, 1.0) - n * n.z) : normalize(t);
      float th = dot(t, h);
      sp = pow(sqrt(max(1.0 - th * th, 0.0)), 60.0) * 0.6 + pow(sqrt(max(1.0 - th * th, 0.0)), 12.0) * 0.15;
    } else {
      sp = pow(max(dot(n, h), 0.0), min(shin, 2000.0)) * (shin + 8.0) / 60.0;
    }
    col += C[i] * spec * sp * step(0.0, ndl) * 0.25;
  }
  float hemi = 0.5 + 0.5 * n.y;
  col += base * (vec3(0.32, 0.34, 0.40) * hemi + vec3(0.16, 0.13, 0.11) * (1.0 - hemi)) * 0.85 * eyeAO;
  float fres = pow(1.0 - clamp(dot(n, v), 0.0, 1.0), 4.0);
  if (uKind == 0) col += base * vec3(0.9, 0.35, 0.25) * sss * pow(1.0 - clamp(dot(n, v), 0.0, 1.0), 3.0) * 0.25;
  if (uKind == 1) col += base * fres * 0.35;  // cloth sheen
  if (uKind == 4) {  // clear cornea: faint sky reflection, no white rim; sharp key + fill catchlights
    float f5 = pow(1.0 - clamp(dot(n, v), 0.0, 1.0), 5.0);
    float rim = 1.0 - smoothstep(1.0, 1.28, acos(clamp(normalize(vObj - uEyeC).z, -1.0, 1.0)) / 0.5432);  // no seam at the cap edge
    col = vec3(0.55, 0.62, 0.72) * (0.03 + 0.5 * f5); alpha = (0.04 + 0.25 * f5) * rim;
    vec3 h = normalize(L[0] + v); col += C[0] * pow(max(dot(n, h), 0.0), 1400.0) * 1.4;
    vec3 h2 = normalize(L[2] + v); col += C[2] * pow(max(dot(n, h2), 0.0), 900.0) * 0.45;
    alpha = max(alpha, min(1.0, max(col.r, col.b))); }
  col = aces(col * 1.05);
  o = vec4(pow(col, vec3(1.0 / 2.2)), alpha);
}`;

export class Renderer {
  constructor(canvas) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: true });
    if (!gl) throw new Error("WebGL2 is not available in this browser.");
    this.gl = gl; this.canvas = canvas;
    this.prog = this._program(VS, FS);
    this.u = {};
    for (const n of ["uJ", "uVP", "uEye", "uBase", "uRough", "uSpec", "uSSS", "uKind", "uAlpha", "uIris", "uDetail", "uEyeC"])
      this.u[n] = gl.getUniformLocation(this.prog, n);
    this.meshes = [];
    this.ground = this._groundMesh();
  }
  _program(vs, fs) {
    const gl = this.gl;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }
  // mesh: {pos Float32Array, nrm Float32Array, col Float32Array|null, uv Float32Array|null, idx Uint32Array, jnt Uint8Array, wgt Uint8Array}
  addMesh(m) {
    const gl = this.gl;
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    const n = m.pos.length / 3;
    const buf = (loc, data, size, type = gl.FLOAT, norm = false, usage = gl.STATIC_DRAW) => {
      const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage);
      gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, type, norm, 0, 0); return b;
    };
    const g = { vao, count: m.idx.length, n };
    g.pos = buf(0, m.pos, 3, gl.FLOAT, false, gl.DYNAMIC_DRAW);
    g.nrm = buf(1, m.nrm, 3, gl.FLOAT, false, gl.DYNAMIC_DRAW);
    g.col = buf(2, m.col || new Float32Array(n * 3).fill(1), 3, gl.FLOAT, false, gl.DYNAMIC_DRAW);
    buf(3, m.uv || new Float32Array(n * 2), 2);
    buf(4, m.jnt, 4, gl.UNSIGNED_BYTE, false);
    buf(5, m.wgt, 4, gl.UNSIGNED_BYTE, true);
    const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.idx, gl.STATIC_DRAW);
    gl.bindVertexArray(null);
    Object.assign(g, { kind: 0, base: [1, 1, 1], rough: 0.5, spec: 0.25, sss: 0, alpha: 1, visible: true, double: false, blend: false });
    this.meshes.push(g);
    return g;
  }
  update(g, attr, data) { const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, g[attr]); gl.bufferSubData(gl.ARRAY_BUFFER, 0, data); }
  _groundMesh() {
    const seg = 64, pos = [0, 0, 0], idx = [];
    for (let i = 0; i < seg; i++) { const a = i / seg * Math.PI * 2; pos.push(Math.cos(a) * 1.4, 0, Math.sin(a) * 1.4); }
    for (let i = 0; i < seg; i++) idx.push(0, 1 + ((i + 1) % seg), 1 + i);
    const n = pos.length / 3;
    const g = this.addMesh({ pos: new Float32Array(pos), nrm: new Float32Array(n * 3).map((_, i) => (i % 3 === 1 ? 1 : 0)),
      idx: new Uint32Array(idx), jnt: new Uint8Array(n * 4), wgt: new Uint8Array(n * 4).map((_, i) => (i % 4 === 0 ? 255 : 0)) });
    Object.assign(g, { kind: 7, base: [0.55, 0.58, 0.62], blend: true });
    this.meshes.pop();
    return g;
  }
  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr)), h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
  }
  draw(cam, jointMats, groundOn = true) {
    const gl = this.gl;
    this.resize();
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.prog);
    const vp = cam.viewProj(this.canvas.width / this.canvas.height);
    gl.uniformMatrix4fv(this.u.uVP, false, vp);
    gl.uniform3fv(this.u.uEye, cam.eye());
    const ident = new Float32Array(16 * 80); for (let i = 0; i < 80; i++) ident[i * 16] = ident[i * 16 + 5] = ident[i * 16 + 10] = ident[i * 16 + 15] = 1;
    gl.enable(gl.DEPTH_TEST);
    const drawMesh = (g) => {
      gl.uniform3fv(this.u.uBase, g.base); gl.uniform1f(this.u.uRough, g.rough); gl.uniform1f(this.u.uSpec, g.spec);
      gl.uniform1f(this.u.uSSS, g.sss); gl.uniform1i(this.u.uKind, g.kind); gl.uniform1f(this.u.uAlpha, g.alpha);
      gl.uniform3fv(this.u.uIris, g.iris || [0.2, 0.1, 0.05]); gl.uniform1f(this.u.uDetail, g.detail || 0);
      gl.uniform3fv(this.u.uEyeC, g.eyeC || [0, 0, 0]);
      if (g.double) gl.disable(gl.CULL_FACE); else { gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK); }
      gl.bindVertexArray(g.vao);
      gl.drawElements(gl.TRIANGLES, g.count, gl.UNSIGNED_INT, 0);
    };
    if (groundOn) {
      gl.uniformMatrix4fv(this.u.uJ, false, ident);
      gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
      drawMesh(this.ground); gl.depthMask(true); gl.disable(gl.BLEND);
    }
    gl.uniformMatrix4fv(this.u.uJ, false, jointMats);
    for (const g of this.meshes) if (g.visible && !g.blend) drawMesh(g);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
    for (const g of this.meshes) if (g.visible && g.blend) drawMesh(g);
    gl.depthMask(true); gl.disable(gl.BLEND);
    gl.bindVertexArray(null);
  }
}

// ---- math helpers (column-major 4x4) ----
export const M4 = {
  ident() { const m = new Float32Array(16); m[0] = m[5] = m[10] = m[15] = 1; return m; },
  mul(a, b) { const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; }
    return o; },
  fromQT(q, t) { const [x, y, z, w] = q; return new Float32Array([
    1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
    2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
    2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0, t[0], t[1], t[2], 1]); },
  persp(fovy, asp, n, f) { const t = 1 / Math.tan(fovy / 2), m = new Float32Array(16);
    m[0] = t / asp; m[5] = t; m[10] = (f + n) / (n - f); m[11] = -1; m[14] = 2 * f * n / (n - f); return m; },
  lookAt(e, c, up) { const z = norm(sub(e, c)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, e), -dot(y, e), -dot(z, e), 1]); },
};
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const scl = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const len = (a) => Math.hypot(a[0], a[1], a[2]);
export const norm = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

export class OrbitCamera {
  constructor() { this.yaw = 0.35; this.pitch = 0.08; this.dist = 4.6; this.target = [0, 0.9, 0]; this.fov = 0.42; }
  eye() { const cp = Math.cos(this.pitch);
    return [this.target[0] + Math.sin(this.yaw) * cp * this.dist, this.target[1] + Math.sin(this.pitch) * this.dist,
            this.target[2] + Math.cos(this.yaw) * cp * this.dist]; }
  viewProj(asp) { return M4.mul(M4.persp(this.fov, asp, 0.02, 60), M4.lookAt(this.eye(), this.target, [0, 1, 0])); }
  attach(el, onChange, onDrag) {
    let drag = null; const pts = new Map();
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
      drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey }; });
    el.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 2) {  // pinch zoom
        const [a, b] = [...pts.values()]; const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (this._pinch) this.zoom(this._pinch / d); this._pinch = d; onChange(); return;
      }
      const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
      if (drag && !drag.pan && onDrag && onDrag(dx, dy)) { onChange(); return; }
      if (drag && drag.pan) {
        const s = this.dist * 0.0015, eye = this.eye();
        const f = norm(sub(this.target, eye)), r = norm(cross(f, [0, 1, 0])), u = cross(r, f);
        this.target = add(this.target, add(scl(r, -dx * s), scl(u, dy * s)));
      } else { this.yaw -= dx * 0.008; this.pitch = Math.max(-1.3, Math.min(1.3, this.pitch + dy * 0.006)); }
      onChange();
    });
    const up = (e) => { pts.delete(e.pointerId); this._pinch = null; if (!pts.size) drag = null; };
    el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("wheel", (e) => { e.preventDefault(); this.zoom(Math.exp(e.deltaY * 0.0012)); onChange(); }, { passive: false });
  }
  zoom(f) { this.dist = Math.max(0.18, Math.min(9, this.dist * f)); }
}
