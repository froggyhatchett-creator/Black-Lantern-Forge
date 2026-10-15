// Phase 2 demonstrations driven in headless Chromium against the studio (local engine server).
// Usage: node tools/studio_demos.mjs <url> <outdir>
// Writes PNG frames per demo plus demos.json (physics traces, measurements, server export result).
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";
import fs from "node:fs";
import path from "node:path";

const [url, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto(url);
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 180000 });
const result = { errors };

const frames = async (n = 2) => { const f = await page.evaluate(() => window.studio.frames);
  await page.waitForFunction((f) => window.studio.frames >= f, f + n, { timeout: 120000 }); };
const shot = async (name) => { await frames(); await page.locator("canvas").screenshot({ path: path.join(out, name) }); };
const set = (fn, arg) => page.evaluate(fn, arg);
const reset = () => set(() => { const st = window.studio; st.applyPreset("female", false); st.state.clip = "none"; st.state.pose = "A-pose (rest)";
  st.playing = false; st.clipT = 0; st.spin.yaw = 0; st.spin.vel = 0; for (const k in st.state.expr) st.state.expr[k] = 0; st.syncUI(); st.dirtyGeo = true; });
const view = (where, yaw = 0.35) => set(([w, y]) => { const st = window.studio; st.focus(w); st.cam.yaw = y; st.cam.pitch = 0.05; }, [where, yaw]);

// ---- B: body and face customization
await reset(); await view("body");
for (const p of ["female", "male", "neutral"]) { await set((p) => window.studio.applyPreset(p, false), p); await shot(`B_preset_${p}.png`); }
const sliders = [["body.height_m", 1.5, 2.05], ["body.body_fat", 0, 1], ["body.muscle", 0, 1], ["body.shoulder_width", 0.8, 1.25], ["body.hip_width", 0.8, 1.3]];
result.body = [];
for (const [k, lo, hi] of sliders) {
  await set(() => window.studio.applyPreset("neutral", false));
  for (const [tag, v] of [["lo", lo], ["hi", hi]]) {
    await set(([k, v]) => { window.studio.setParam(k, v, { record: false }); }, [k, v]);
    await shot(`B_${k.replace(".", "_")}_${tag}.png`);
    result.body.push({ param: k, value: v, height_m: await page.evaluate(() => window.studio.heightNow) });
  }
}
await set(() => window.studio.applyPreset("female", false)); await view("face", 0.45);
for (const [k, lo, hi] of [["face.jaw_width", 0.75, 1.3], ["face.nose_length", 0.75, 1.3], ["face.eye_size", 0.8, 1.25], ["face.cheekbone_width", 0.75, 1.3]]) {
  for (const [tag, v] of [["lo", lo], ["hi", hi]]) {
    await set(([k, v]) => window.studio.setParam(k, v, { record: false }), [k, v]); await shot(`B_${k.replace(".", "_")}_${tag}.png`);
  }
  await set(([k]) => { const pe = window.studio.man.params[k]; window.studio.setParam(k, pe.default, { record: false }); }, [k]);
}
for (const e of ["smile", "frown", "brow_raise", "jaw_open", "blink_l"]) {
  const ok = await set((e) => { const st = window.studio; if (!st.man.expressions.some((x) => x.name === e)) return false;
    for (const k in st.state.expr) st.state.expr[k] = 0; st.state.expr[e] = 1; st.dirtyGeo = true; return true; }, e);
  if (ok) await shot(`B_expr_${e}.png`);
}
result.expressions = await page.evaluate(() => window.studio.man.expressions.map((e) => e.name));

// ---- C: animation previews (frames sampled through each clip)
await reset(); await view("body", 0.9);
result.clips = {};
for (const c of ["idle", "walk", "run", "jump", "turn", "sudden_stop"]) {
  const info = await set((c) => { const st = window.studio; st.state.clip = c; st.playing = false; const cl = st.clips[c];
    return { frames: cl.frames, fps: cl.fps, loop: cl.loop }; }, c);
  result.clips[c] = info;
  const dur = info.frames / info.fps;
  for (const [i, f] of [0.0, 0.25, 0.5, 0.75].entries()) {
    await set(([t]) => { const st = window.studio; st.clipT = t; st._resetPhys = true; }, [f * dur]);
    await shot(`C_${c}_${i}.png`);
  }
}

// ---- D: secondary motion, stepped at a fixed 60 Hz (rendering is not involved, so software GL speed does not matter)
const trace = (opts) => page.evaluate((o) => {
  const st = window.studio;
  st.applyPreset("female", false); st.state.outfit = o.outfit; st.enforceCoverage(); st.dirtyGeo = true;
  st.state.clip = o.clip || "none"; st.state.pose = "A-pose (rest)"; st.playing = !!o.clip; st.clipT = 0;
  st.phys.on = true; st.phys.damp = o.damp ?? 0.22; st.phys.freq = o.freq ?? 2.4; st.phys.intensity = o.intensity ?? 1;
  st.spin.yaw = 0; st.spin.vel = 0; st._lastSpin = 0; st._resetPhys = true;
  const dt = 1 / 60, rows = [];
  st.step(dt, 1e9);
  for (let i = 0; i < Math.round((o.seconds || 4) / dt); i++) {
    const t = i * dt;
    if (o.spin && t < o.spin.until) { st.spin.vel = o.spin.vel; }
    if (o.orbit) st.cam.yaw += o.orbit * dt;   // camera only: never touches the simulation inputs
    st.step(dt, 1e9 + i * 1000);
    const dev = (b) => { const s = st.phys.state.get(b); return s ? Math.hypot(s.p[0] - s.pf[0], s.p[1] - s.pf[1], s.p[2] - s.pf[2]) : 0; };
    rows.push([+t.toFixed(4), +(dev("breast_l") * 1000).toFixed(3), +(dev("cloth_front_01") * 1000).toFixed(3), +st.spin.yaw.toFixed(4)]);
  }
  return rows;
}, opts);
const spin = { vel: 5.0, until: 0.35 };
result.physics = {
  columns: ["t_s", "breast_l_offset_mm", "cloth_front_01_offset_mm", "character_yaw_rad"],
  camera_orbit_only: await trace({ outfit: ["tshirt", "skirt"], orbit: 3.0, seconds: 2 }),
  spin_damping_0_10: await trace({ outfit: ["tshirt", "skirt"], spin, damp: 0.10 }),
  spin_damping_0_22: await trace({ outfit: ["tshirt", "skirt"], spin, damp: 0.22 }),
  spin_damping_0_50: await trace({ outfit: ["tshirt", "skirt"], spin, damp: 0.50 }),
  spin_with_bra: await trace({ outfit: ["bra", "tshirt", "skirt"], spin, damp: 0.22 }),
  spin_intensity_0_5: await trace({ outfit: ["tshirt", "skirt"], spin, damp: 0.22, intensity: 0.5 }),
  sudden_stop_clip: await trace({ outfit: ["tshirt", "skirt"], clip: "sudden_stop", seconds: 2.5 }),
  jump_clip: await trace({ outfit: ["tshirt", "skirt"], clip: "jump", seconds: 2.0 }),
};
await reset(); await view("torso", 0.7);
await set(() => { const st = window.studio; st.state.outfit = ["tshirt", "skirt"]; st.state.hair_style = "long"; st.dirtyGeo = true; st.spin.mode = "character"; st._resetPhys = true; st.step(1 / 60, 1e9); });
await shot("D_spin_0.png");
for (let i = 1; i <= 3; i++) {
  await set((i) => { const st = window.studio; for (let k = 0; k < 6; k++) { if (i === 1) st.spin.vel = 5; st.step(1 / 60, 2e9 + i * 1e5 + k * 1000); } }, i);
  await shot(`D_spin_${i}.png`);
}

// ---- E: hairstyles and appearance
await reset(); await view("face", 0.6);
for (const hs of await page.evaluate(() => window.studio.meta.hair_styles)) {
  await set((hs) => { const st = window.studio; st.state.hair_style = hs; st.state.hl_amount = 0; st.dirtyGeo = true; }, hs);
  await shot(`E_hair_${hs}.png`);
}
await set(() => { const st = window.studio; st.state.hair_style = "long"; st.state.hair_color = "#5a3a22"; st.state.hl_color = "#c9a06a"; st.state.hl_amount = 0.8; st.dirtyGeo = true; });
await shot("E_highlights_on.png");
await view("body", 0.4);
for (const [i, tone] of [0.05, 0.35, 0.65, 0.95].entries()) {
  await set((t) => { const st = window.studio; st.state.skin_tone = t; st.dirtyGeo = true; }, tone); await shot(`E_skin_${i}.png`);
}
await set(() => { const st = window.studio; st.state.outfit = ["robe"]; st.state.colors.robe = "#5b2a6e"; st.enforceCoverage(); st.dirtyGeo = true; });
await shot("E_outfit_robe.png");
await set(() => { const st = window.studio; st.state.outfit = ["bra", "pants"]; st.state.colors.pants = "#2d3e2a"; st.enforceCoverage(); st.dirtyGeo = true; });
await shot("E_outfit_bra_pants.png");

// ---- H: save -> reload -> exact export through the local engine server
await reset();
await set(() => { const st = window.studio; st.state.name = "demo_h"; st.setParam("body.height_m", 1.82, { record: false }); st.setParam("face.jaw_width", 1.1, { record: false });
  st.state.hair_style = "bangs"; st.state.hl_amount = 0.4; st.state.outfit = ["tshirt", "pants"]; st.dirtyGeo = true; });
const dna = await page.evaluate(() => window.studio.toDNA());
fs.writeFileSync(path.join(out, "H_demo.dna.json"), JSON.stringify(dna, null, 1));
await set(() => window.studio.applyPreset("male", false));
await set((d) => window.studio.fromDNA(d), dna);
result.reload = await page.evaluate((d) => { const st = window.studio; let m = 0;
  for (const k of Object.keys(st.man.params)) m = Math.max(m, Math.abs(st.state.params[k] - d.traits[k].value));
  return { max_param_diff: m, hair_style: st.state.hair_style, outfit: st.state.outfit }; }, dna);
const browserGlb = await page.evaluate(() => { const b = window.studio.exportBytes(); let s = ""; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768)); return btoa(s); });
fs.writeFileSync(path.join(out, "H_browser_export.glb"), Buffer.from(browserGlb, "base64"));
result.server_export = await page.evaluate(async (d) => {
  const t0 = performance.now(); const r = await fetch("api/export", { method: "POST", body: JSON.stringify(d) });
  const j = await r.json(); j.seconds = (performance.now() - t0) / 1000; j.status = r.status; return j; }, dna);
await view("body", 0.4); await shot("H_reloaded.png");
result.memory_mb = await page.evaluate(() => performance.memory ? performance.memory.usedJSHeapSize / 1e6 : null);
fs.writeFileSync(path.join(out, "demos.json"), JSON.stringify(result, null, 1));
await browser.close();
console.log(JSON.stringify({ errors, reload: result.reload, server: { status: result.server_export.status, path: result.server_export.path, ok: result.server_export.validation && result.server_export.validation.ok } }));
