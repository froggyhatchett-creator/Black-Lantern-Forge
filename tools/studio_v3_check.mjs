// Generator v3 Phase 1 verification in the real Character Studio (Playwright + Chromium/SwiftShader WebGL2).
// Boots the studio on generator v3, measures every control at both ends, captures before/after control views,
// a blink sequence, multi-angle views, posed and animated frames, and exports a GLB + DNA from the browser.
// usage: node tools/studio_v3_check.mjs <base-url> <outdir>
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const base = process.argv[2] || "http://127.0.0.1:8799/";
const out = process.argv[3] || "studio_v3_check";
fs.mkdirSync(path.join(out, "shots"), { recursive: true });
const checks = [];
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${name} ${detail}`); };

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const t0 = Date.now();
await page.goto(base + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 180000 });
ok("v3 studio boots", (await page.evaluate(() => document.body.dataset.ready)) === "1", `${((Date.now() - t0) / 1000).toFixed(1)} s`);
const gen = await page.evaluate(() => window.studio.man.generator);
ok("generator v3 loaded", gen && gen.version === 3, JSON.stringify(gen));
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const tick = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(tick)); tick(); }), n);
const view = async (name) => { await settle(); await page.locator("#view").screenshot({ path: path.join(out, "shots", name) }); };
const still = () => page.evaluate(() => { const s = window.studio; s.state.clip = "none"; s.playing = false; s.clipT = 0; s.spin.yaw = 0; s.spin.vel = 0;
  s.state.pose = "A-pose (rest)"; document.getElementById("turntable").checked = false; s.dirtyGeo = true; });
const cam = (focus, yawDeg, pitch = 0.05) => page.evaluate(([f, y, p]) => { const s = window.studio; s.focus(f); s.cam.yaw = y * Math.PI / 180; s.cam.pitch = p; }, [focus, yawDeg, pitch]);
await still();

// ---------------------------------------------------------------- every control, both ends (geometry, no render)
const ctl = await page.evaluate(() => {
  const s = window.studio, res = {};
  s.applyPreset("neutral", false); s.evaluate();
  const ref = Float32Array.from(s.parts.body.cur), hRef = s.heightNow;
  for (const [k, pe] of Object.entries(s.man.params)) {
    const r = { quality: pe.quality };
    for (const [end, val] of [["min", pe.min], ["max", pe.max]]) {
      s.state.params[k] = val; s.evaluate();
      const c = s.parts.body.cur; let moved = 0, maxd = 0;
      for (let i = 0; i < c.length; i += 3) { const d = Math.hypot(c[i] - ref[i], c[i + 1] - ref[i + 1], c[i + 2] - ref[i + 2]); if (d > 1e-4) moved++; maxd = Math.max(maxd, d); }
      r[end] = { value: val, moved_vertices: moved, max_displacement_mm: +(maxd * 1000).toFixed(2), height_m: +s.heightNow.toFixed(4) };
      s.state.params[k] = pe.default;
    }
    r.at_default = pe.default; res[k] = r;
  }
  s.evaluate();
  return { neutral_height: hRef, controls: res };
});
const inert = Object.entries(ctl.controls).filter(([k, r]) => r.min.moved_vertices === 0 && r.max.moved_vertices === 0 ||
  (r.at_default !== r.min.value && r.min.moved_vertices === 0) || (r.at_default !== r.max.value && r.max.moved_vertices === 0)).map(([k]) => k);
ok("all 53 controls move the body at each used end", Object.keys(ctl.controls).length === 53 && !inert.length, inert.length ? `inert: ${inert}` : "53/53");
const hc = ctl.controls["body.height_m"];
ok("height control is exact", Math.abs(hc.min.height_m - hc.min.value) < 1e-3 && Math.abs(hc.max.height_m - hc.max.value) < 1e-3, `${hc.min.height_m} / ${hc.max.height_m} m`);

// ---------------------------------------------------------------- before/after control views
const SHOWN = [["body.femininity", "body", 25], ["body.muscle", "body", 25], ["body.body_fat", "body", 25], ["body.shoulder_width", "body", 0],
  ["face.jaw_width", "face", 0], ["face.nose_width", "face", 0], ["face.eye_size", "face", 0], ["face.lip_upper", "face", 25],
  ["face.chin_projection", "face", 90], ["face.cheekbone_width", "face", 0]];
await page.evaluate(() => window.studio.applyPreset("neutral", false));
for (const [k, focus, yaw] of SHOWN) {
  for (const end of ["min", "max"]) {
    await page.evaluate(([k, end]) => { const s = window.studio, pe = s.man.params[k]; s.state.params[k] = end === "min" ? pe.min : pe.max; s.dirtyGeo = true; }, [k, end]);
    await cam(focus, yaw); await view(`control_${k.replace(".", "_")}_${end}.png`);
  }
  await page.evaluate((k) => { const s = window.studio; s.state.params[k] = s.man.params[k].default; s.dirtyGeo = true; }, k);
}

// ---------------------------------------------------------------- the character: female preset, multi-angle
await page.click("[data-preset=female]"); await still();
for (const y of [0, 45, 90, 180]) { await cam("body", y); await view(`female_body_${y}.png`); }
for (const y of [0, 35, 90]) { await cam("face", y); await view(`female_face_${y}.png`); }
await page.click("[data-preset=male]"); await still();
for (const y of [0, 35]) { await cam("body", y); await view(`male_body_${y}.png`); }
await cam("face", 25); await view("male_face_25.png");
await page.click("[data-preset=female]"); await still();

// ---------------------------------------------------------------- blink
for (const w of [0, 0.5, 1]) {
  await page.evaluate((w) => { const s = window.studio; s.state.expr.blink_l = w; s.state.expr.blink_r = w; s.dirtyGeo = true; }, w);
  for (const y of [0, 35]) {  // framed on the eyes (midpoint of the two eyeball centres)
    await cam("face", y);
    await page.evaluate(() => { const s = window.studio; s.evaluate(); const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC; s.cam.target = a.map((v, k) => (v + b[k]) / 2); s.cam.dist = 0.3; });
    await view(`blink_${w}_${y}.png`);
  }
}
await page.evaluate(() => { const s = window.studio; s.state.expr = {}; s.dirtyGeo = true; });

// ---------------------------------------------------------------- rig: poses and an animation frame
for (const p of ["Relaxed", "Arms raised", "Lunge"]) {
  await page.evaluate((p) => { window.studio.state.pose = p; window.studio._resetPhys = true; }, p); await cam("body", 30); await view(`pose_${p.replace(" ", "_")}.png`);
}
await page.evaluate(() => { const s = window.studio; s.state.pose = "A-pose (rest)"; s.state.clip = "walk"; s.clipT = 8 / 30; s.playing = false; });
await cam("body", 60); await view("walk_frame8.png");
await still();

// ---------------------------------------------------------------- coverage
await page.click("#t-outfit").catch(() => {});
const covered = await page.evaluate(() => { const s = window.studio; s.state.outfit = []; s.enforceCoverage(); return s.state.outfit; });
ok("public coverage re-adds v3 garments", covered.includes("basic_top") && covered.includes("basic_shorts"), `${covered}`);

// ---------------------------------------------------------------- export
const glbB64 = await page.evaluate(() => { const b = window.studio.exportBytes(); let s = ""; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768)); return btoa(s); });
fs.writeFileSync(path.join(out, "v3_studio_export.glb"), Buffer.from(glbB64, "base64"));
ok("GLB exported from the v3 studio", glbB64.length > 1e5, `${(glbB64.length * 0.75 / 1e6).toFixed(2)} MB`);
const dna = await page.evaluate(() => window.studio.toDNA());
fs.writeFileSync(path.join(out, "v3_studio_export.dna.json"), JSON.stringify(dna, null, 1));
ok("DNA records generator v3", dna.identity.generator && dna.identity.generator.version === 3, JSON.stringify(dna.identity.generator));
ok("no page errors", !errors.length, errors.slice(0, 3).join(" | "));
fs.writeFileSync(path.join(out, "v3_check.json"), JSON.stringify({ checks, errors, controls: ctl }, null, 1));
await browser.close();
process.exit(checks.every((c) => c.pass) ? 0 : 1);
