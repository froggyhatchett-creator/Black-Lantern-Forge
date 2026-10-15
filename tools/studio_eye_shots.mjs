// Matched eye-region captures in the real studio (Project Humanity P1 eye experiment).
// Usage: node tools/studio_eye_shots.mjs <url> <outdir> [dna.json]
// Every capture uses the same DNA (default: the female preset), camera, lighting, expression and render size; the
// HUD/status overlays are hidden and secondary motion is frozen so before/after images differ only by the change.
// Also checks blink (expression morphs), gaze (eye joints drive the eyeballs) and writes eye_checks.json.
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";
import fs from "node:fs";
import path from "node:path";

const [url, out, dnaPath] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto(url);
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 180000 });
const dna = dnaPath ? JSON.parse(fs.readFileSync(dnaPath, "utf8")) : null;
await page.evaluate((dna) => {
  const st = window.studio;
  if (dna) st.fromDNA(dna); else st.applyPreset("female", false);
  st.state.hair_style = "bun";              // keep hair off the eyes so only the eye region is compared
  st.state.clip = "none"; st.state.pose = "A-pose (rest)"; st.playing = false; st.clipT = 0;
  st.phys.on = false; st.spin.yaw = 0; st.spin.vel = 0;
  for (const k in st.state.expr) st.state.expr[k] = 0;
  st.dirtyGeo = true;
  document.querySelector("#turntable").checked = false;
  for (const el of document.querySelectorAll(".stage > :not(canvas)")) el.style.visibility = "hidden";
}, dna);
const frames = async (n = 3) => { const f = await page.evaluate(() => window.studio.frames);
  await page.waitForFunction((f) => window.studio.frames >= f, f + n, { timeout: 120000 }); };
const view = (yaw, dist, dy = 0) => page.evaluate(([yaw, dist, dy]) => {
  const st = window.studio, n = st.skel.names, r = st.rest, e = n.indexOf("eye_l") * 3, f = n.indexOf("eye_r") * 3;
  st.cam.target = [(r[e] + r[f]) / 2, (r[e + 1] + r[f + 1]) / 2 + dy, (r[e + 2] + r[f + 2]) / 2];
  st.cam.yaw = yaw; st.cam.pitch = 0.0; st.cam.dist = dist;
}, [yaw, dist, dy]);
const shot = async (name) => { await frames(); await page.locator("canvas").screenshot({ path: path.join(out, name) }); };
const checks = {};

await view(0.0, 0.62, -0.03); await shot("face_front.png");
await view(0.62, 0.62, -0.03); await shot("face_3q.png");
await view(0.0, 0.22); await shot("eyes_front.png");
await view(0.62, 0.22); await shot("eyes_3q.png");

// blink: both lids closed through the expression morphs (offset measured against the open-eyed state)
await page.evaluate(() => { window._open = Float32Array.from(window.studio.parts.body.cur); });
await page.evaluate(() => { const st = window.studio; st.state.expr.blink_l = 1; st.state.expr.blink_r = 1; st.dirtyGeo = true; });
await view(0.0, 0.22); await shot("blink_front.png");
checks.blink = await page.evaluate(() => { const b = window.studio.parts.body.cur, o = window._open; let m = 0, moved = 0;
  for (let i = 0; i < b.length; i += 3) { const d = Math.hypot(b[i] - o[i], b[i + 1] - o[i + 1], b[i + 2] - o[i + 2]); m = Math.max(m, d); if (d > 5e-4) moved++; }
  return { max_lid_offset_mm: +(m * 1000).toFixed(2), vertices_moved: moved }; });
await page.evaluate(() => { const st = window.studio; st.state.expr.blink_l = 0; st.state.expr.blink_r = 0; st.dirtyGeo = true; });

// gaze: rotate both eye joints 25 degrees to the character's left (test hook only; the studio has no gaze control)
await page.evaluate(() => {
  const st = window.studio, n = st.skel.names, orig = st.poseRotations.bind(st), a = 25 * Math.PI / 180;
  st.poseRotations = (t) => { const r = orig(t); for (const e of ["eye_l", "eye_r"]) r.rot[n.indexOf(e)] = [0, Math.sin(a / 2), 0, Math.cos(a / 2)]; return r; };
});
await view(0.0, 0.22); await shot("gaze_left_front.png");
await page.evaluate(() => { delete window.studio.poseRotations; });

checks.errors = errors;
fs.writeFileSync(path.join(out, "eye_checks.json"), JSON.stringify(checks, null, 1));
await browser.close();
console.log(JSON.stringify(checks));
