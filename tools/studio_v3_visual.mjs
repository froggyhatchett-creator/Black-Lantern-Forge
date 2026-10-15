// Generator v3 Phase 2 (visual quality) evidence in the real Character Studio (Playwright + Chromium/SwiftShader).
// Captures matched views with identical cameras, so the same script run against the Phase 1 build gives the
// "before" images. With --full it also captures control variations, head movement, numeric grooming checks and
// a browser GLB export.  usage: node tools/studio_v3_visual.mjs <base-url> <outdir> <prefix> [--full]
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const [base, out, prefix] = process.argv.slice(2);
const full = process.argv.includes("--full");
fs.mkdirSync(out, { recursive: true });
const checks = [];
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${name} ${detail}`); };
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto(base + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 300000 });
ok("v3 studio boots", (await page.evaluate(() => document.body.dataset.ready)) === "1");
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const t = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(t)); t(); }), n);
const shot = async (name) => { await settle(); await page.locator("#view").screenshot({ path: path.join(out, `${prefix}_${name}.png`), timeout: 600000 }); };
const reset = () => page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.state.clip = "none"; s.playing = false; s.clipT = 0;
  s.spin.yaw = 0; s.spin.vel = 0; s.state.pose = "A-pose (rest)"; s.state.expr = {}; document.getElementById("turntable").checked = false; s.dirtyGeo = true; s.evaluate(); });
// cameras: framed on the eyes (face) or the whole body; identical for every build
const faceCam = (yawDeg, dist = 0.55, drop = 0.035) => page.evaluate(([y, d, dr]) => { const s = window.studio; s.evaluate();
  const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC; s.cam.target = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - dr, (a[2] + b[2]) / 2];
  s.cam.dist = d; s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.02; }, [yawDeg, dist, drop]);
const bodyCam = (yawDeg) => page.evaluate((y) => { const s = window.studio; s.focus("body"); s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.05; }, yawDeg);

await reset();
for (const y of [0, 35, 90]) { await faceCam(y); await shot(`face_${y}`); }
for (const y of [0, 35]) { await bodyCam(y); await shot(`body_${y}`); }
for (const w of [0, 0.5, 1]) {
  await page.evaluate((w) => { const s = window.studio; s.state.expr.blink_l = w; s.state.expr.blink_r = w; s.dirtyGeo = true; }, w);
  await faceCam(20, 0.2, 0); await shot(`blink_${w}`);
}
await reset();

if (full) {
  // grooming follows the face: lashes ride the blink, brows and hair keep their roots on the skin
  const g = await page.evaluate(() => {
    const s = window.studio, L = s.parts.lashes, H = s.parts.hair_shoulder, res = {};
    res.textures = Object.keys(s.texBitmaps || {});
    const open = Float32Array.from(L.cur);
    s.state.expr.blink_l = 1; s.state.expr.blink_r = 1; s.evaluate();
    let m = 0; for (let i = 0; i < open.length; i += 3) m += Math.hypot(L.cur[i] - open[i], L.cur[i + 1] - open[i + 1], L.cur[i + 2] - open[i + 2]);
    res.lash_mean_move_mm = m / (open.length / 3) * 1000;
    s.state.expr = {}; s.evaluate();
    // roots: strand vertex 0/1 must sit on their anchored body point (re-evaluated after an extreme face edit)
    s.state.params["face.eye_size"] = s.man.params["face.eye_size"].max; s.state.params["body.head_size"] = s.man.params["body.head_size"].max; s.evaluate();
    const rootGap = (P) => { const A = P.anchor, K = P.strandPts, body = s.parts.body.cur; let worst = 0;
      for (let r = 0; r < A.bary.length / 3; r++) { const v = r * 2 * K, p = [0, 1, 2].map((k) => body[A.tri[r * 3] * 3 + k] * A.bary[r * 3] + body[A.tri[r * 3 + 1] * 3 + k] * A.bary[r * 3 + 1] + body[A.tri[r * 3 + 2] * 3 + k] * A.bary[r * 3 + 2]);
        const c = [0, 1, 2].map((k) => (P.cur[v * 3 + k] + P.cur[(v + 1) * 3 + k]) / 2); worst = Math.max(worst, Math.hypot(c[0] - p[0], c[1] - p[1], c[2] - p[2])); }
      return worst * 1000; };
    res.root_gap_mm = { brows: rootGap(s.parts.brows), lashes: rootGap(s.parts.lashes), hair: rootGap(H) };
    return res;
  });
  ok("skin, eye and strand textures loaded", ["skin_albedo", "skin_normal", "eye", "strand_hair", "strand_single"].every((k) => g.textures.includes(k)), g.textures.join(","));
  ok("lashes ride the blink", g.lash_mean_move_mm > 2, `${g.lash_mean_move_mm.toFixed(2)} mm mean lash displacement`);
  ok("strand roots stay on the skin after extreme edits", Object.values(g.root_gap_mm).every((x) => x < 1.0), JSON.stringify(Object.fromEntries(Object.entries(g.root_gap_mm).map(([k, v]) => [k, +v.toFixed(3)]))));
  await reset();
  // control variations with the new surface layers
  const VAR = [["body.femininity", "min", "face", 35], ["face.eye_size", "max", "face", 0], ["face.jaw_width", "max", "face", 0],
    ["body.head_size", "max", "face", 35], ["face.nose_width", "max", "face", 0], ["body.body_fat", "max", "body", 35], ["body.height_m", "max", "body", 35]];
  for (const [k, end, cam, y] of VAR) {
    await page.evaluate(([k, end]) => { const s = window.studio, pe = s.man.params[k]; s.state.params[k] = end === "min" ? pe.min : pe.max; s.dirtyGeo = true; }, [k, end]);
    if (cam === "face") await faceCam(y); else await bodyCam(y);
    await shot(`var_${k.replace(".", "_")}_${end}`);
    await reset();
  }
  await page.click("[data-preset=male]"); await page.evaluate(() => { window.studio.state.clip = "none"; window.studio.dirtyGeo = true; });
  await faceCam(35); await shot("var_male_preset");
  await reset();
  // head movement: a posed head and an animation frame keep hair, brows and lashes attached
  await page.evaluate(() => { const s = window.studio; s.state.pose = "Contrapposto"; s._resetPhys = true; });
  await faceCam(30, 0.9, 0.05); await shot("motion_pose");
  await page.evaluate(() => { const s = window.studio; s.state.pose = "A-pose (rest)"; s.state.clip = "walk"; s.clipT = 8 / 30; s.playing = false; });
  await bodyCam(60); await shot("motion_walk8");
  await reset();
  // export
  const glb = await page.evaluate(() => { const b = window.studio.exportBytes(); let s = ""; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768)); return btoa(s); });
  fs.writeFileSync(path.join(out, "v3_phase2_export.glb"), Buffer.from(glb, "base64"));
  ok("GLB exported", glb.length > 1e6, `${(glb.length * 0.75 / 1e6).toFixed(1)} MB`);
  fs.writeFileSync(path.join(out, "v3_phase2_export.dna.json"), JSON.stringify(await page.evaluate(() => window.studio.toDNA()), null, 1));
}
ok("no page errors", !errors.length, errors.slice(0, 3).join(" | "));
fs.writeFileSync(path.join(out, `${prefix}_checks.json`), JSON.stringify({ checks, errors }, null, 1));
await browser.close();
process.exit(checks.every((c) => c.pass) ? 0 : 1);
