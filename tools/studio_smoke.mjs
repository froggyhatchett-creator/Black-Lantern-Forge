// Headless end-to-end check of the Character Studio (Playwright + Chromium/SwiftShader WebGL2).
// usage: node tools/studio_smoke.mjs <url> <outdir>
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const url = process.argv[2] || "http://127.0.0.1:8799/";
const out = process.argv[3] || "studio_smoke";
fs.mkdirSync(out, { recursive: true });
const checks = [];
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${name} ${detail}`); };

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const t0 = Date.now();
await page.goto(url);
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 180000 });
const ready = await page.evaluate(() => document.body.dataset.ready);
ok("studio boots", ready === "1", `${((Date.now() - t0) / 1000).toFixed(1)} s`);
if (ready !== "1") { console.log(await page.textContent("#status")); await browser.close(); process.exit(1); }
const settle = (n = 6) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const tick = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(tick)); tick(); }), n);
const coverage = () => page.evaluate(() => { const c = document.getElementById("view"); const g = c.getContext("webgl2");
  const w = c.width, h = c.height, px = new Uint8Array(w * h * 4); g.readPixels(0, 0, w, h, g.RGBA, g.UNSIGNED_BYTE, px);
  let n = 0, top = h, sum = 0; for (let y = 0; y < h; y++) for (let x = 0; x < w; x += 2) { const i = (y * w + x) * 4; if (px[i + 3] > 200) { n++; sum += px[i]; top = Math.min(top, h - y); } }
  return { frac: n / (w * h / 2), sum, w, h }; });
const shot = (name) => page.screenshot({ path: path.join(out, name) });

await page.evaluate(() => window.studio.focus("body")); await settle();
const c0 = await coverage();
ok("character renders", c0.frac > 0.03, `covered fraction ${c0.frac.toFixed(3)}`);
await shot("01_default_female.png");

// presets change geometry
const h0 = await page.evaluate(() => window.studio.heightNow);
await page.click("[data-preset=male]"); await settle();
const h1 = await page.evaluate(() => window.studio.heightNow);
ok("male preset changes geometry", Math.abs(h1 - h0) > 0.05, `height ${h0.toFixed(3)} -> ${h1.toFixed(3)} m`);
await shot("02_male_preset.png");

// slider drives real vertices
const before = await page.evaluate(() => Array.from(window.studio.parts.body.cur.slice(0, 30000)));
await page.evaluate(() => { const s = document.getElementById("s-body.shoulder_width"); s.value = s.max; s.dispatchEvent(new Event("input", { bubbles: true })); s.dispatchEvent(new Event("change", { bubbles: true })); });
await settle();
const after = await page.evaluate(() => Array.from(window.studio.parts.body.cur.slice(0, 30000)));
let moved = 0; for (let i = 0; i < before.length; i++) if (Math.abs(before[i] - after[i]) > 1e-4) moved++;
ok("shoulder slider moves vertices", moved > 1000, `${moved} coordinates changed`);
await page.evaluate(() => { const s = document.getElementById("s-body.height_m"); s.value = "2.05"; s.dispatchEvent(new Event("input", { bubbles: true })); });
await settle();
const h2 = await page.evaluate(() => window.studio.heightNow);
ok("height slider reaches requested height", Math.abs(h2 - 2.05) < 0.08, `measured ${h2.toFixed(3)} m`);
await page.click("#undo"); await settle();
const h3 = await page.evaluate(() => window.studio.heightNow);
ok("undo restores the previous value", Math.abs(h3 - h1) < 0.02, `${h3.toFixed(3)} m`);

// orbit + zoom by real mouse input
const box = await page.locator("#view").boundingBox();
const yaw0 = await page.evaluate(() => window.studio.cam.yaw);
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
await page.mouse.move(box.x + box.width / 2 + 220, box.y + box.height / 2 + 30, { steps: 8 }); await page.mouse.up();
const yaw1 = await page.evaluate(() => window.studio.cam.yaw);
ok("mouse drag rotates", Math.abs(yaw1 - yaw0) > 0.5, `yaw ${yaw0.toFixed(2)} -> ${yaw1.toFixed(2)}`);
const d0 = await page.evaluate(() => window.studio.cam.dist);
await page.mouse.wheel(0, -600); await settle();
const d1 = await page.evaluate(() => window.studio.cam.dist);
ok("wheel zooms", d1 < d0 * 0.8, `distance ${d0.toFixed(2)} -> ${d1.toFixed(2)}`);
await shot("03_orbit_zoom.png");

// face editing + close-up
await page.click("[data-preset=female]"); await page.click("#t-face");
await page.evaluate(() => window.studio.focus("face")); await settle();
await shot("04_face_before.png");
const fb = await page.evaluate(() => Array.from(window.studio.parts.body.cur));
for (const [k, v] of [["face.jaw_width", 1.3], ["face.nose_length", 1.3], ["face.eye_size", 1.25], ["face.lip_upper", 1.3]])
  await page.evaluate(([k, v]) => { const s = document.getElementById(`s-${k}`); s.value = v; s.dispatchEvent(new Event("input", { bubbles: true })); }, [k, v]);
await settle();
const fa = await page.evaluate(() => Array.from(window.studio.parts.body.cur));
let fm = 0; for (let i = 0; i < fa.length; i += 3) if (Math.hypot(fa[i] - fb[i], fa[i + 1] - fb[i + 1], fa[i + 2] - fb[i + 2]) > 5e-4) fm++;
ok("face sliders reshape the face", fm > 500, `${fm} vertices moved > 0.5 mm`);
await shot("05_face_after.png");
await page.evaluate(() => { const s = document.getElementById("e-smile"); s.value = 1; s.dispatchEvent(new Event("input", { bubbles: true })); });
await settle(); await shot("06_face_smile.png");

// outfit coverage rule
await page.click("#t-outfit");
await page.evaluate(() => window.studio.focus("body"));
await page.click("#g-shorts"); await settle();
const outfit = await page.evaluate(() => window.studio.state.outfit);
const note = await page.textContent("#coverage-note");
ok("public coverage is enforced", outfit.includes("shorts") || outfit.some((g) => ["briefs", "pants", "skirt", "robe", "loincloth"].includes(g)), `outfit=${outfit} note="${note}"`);
await page.check("#g-skirt"); await page.click("#g-shorts"); await settle();
const outfit2 = await page.evaluate(() => window.studio.state.outfit);
ok("garments swap when coverage remains", outfit2.includes("skirt") && !outfit2.includes("shorts"), `${outfit2}`);
await shot("07_skirt.png");

// look
await page.click("#t-look");
await page.selectOption("#hairstyle", "bun"); await page.fill("#haircolor", "#a33a2a");
await page.evaluate(() => { const s = document.getElementById("skin"); s.value = 0.8; s.dispatchEvent(new Event("input", { bubbles: true })); });
await settle(); await shot("08_look.png");

// animation + physics
await page.click("#t-motion");
await page.selectOption("#clip", "jump");
const f0 = await page.evaluate(() => window.studio.clipT);
await page.waitForTimeout(3000);
const f1 = await page.evaluate(() => window.studio.clipT);
// dt is clamped to 0.1 s per frame, so under a ~2 fps software rasterizer clip time runs slower than wall time
ok("animation advances", f1 > f0 + 0.15, `clip time ${f0.toFixed(2)} -> ${f1.toFixed(2)} s`);
const phys = await page.evaluate(() => [...window.studio.phys.state.keys()]);
ok("live secondary physics runs", phys.includes("breast_l") && phys.includes("cloth_front_01"), phys.join(","));
await page.selectOption("#clip", "walk"); await page.waitForTimeout(600); await shot("09_walk.png");
await page.selectOption("#clip", "none"); await page.selectOption("#pose", "Contrapposto"); await settle(10); await shot("10_pose.png");

// character spin: inertia, physics response; camera orbit causes none
await page.selectOption("#clip", "none"); await page.selectOption("#pose", "A-pose (rest)");
await page.evaluate(() => window.studio.focus("torso")); await page.waitForTimeout(1500);
const tipDev = () => page.evaluate(() => { const s = window.studio.phys.state.get("breast_l"); return s ? Math.hypot(...s.v) : 0; });
await page.click("[data-drag=camera]");
await page.mouse.move(box.x + 300, box.y + 400); await page.mouse.down(); await page.mouse.move(box.x + 700, box.y + 400, { steps: 6 }); await page.mouse.up();
await page.waitForTimeout(100);
const vCam = await tipDev();
ok("camera orbit causes no secondary motion", vCam < 0.01, `breast particle speed ${vCam.toFixed(4)} m/s`);
await page.click("[data-drag=character]");
const yawA = await page.evaluate(() => window.studio.spin.yaw);
await page.mouse.move(box.x + 300, box.y + 400); await page.mouse.down(); await page.mouse.move(box.x + 760, box.y + 400, { steps: 5 }); await page.mouse.up();
await page.waitForTimeout(120);
const vSpin = await tipDev(), yawB = await page.evaluate(() => window.studio.spin.yaw);
{ const fr = await page.evaluate(() => window.studio.frames); await page.waitForFunction((f) => window.studio.frames >= f + 3, fr, { timeout: 20000 }); }
const yawC = await page.evaluate(() => window.studio.spin.yaw);
ok("spinning the character moves soft tissue", vSpin > 0.05, `breast particle speed ${vSpin.toFixed(3)} m/s`);
ok("spin has inertia after release", Math.abs(yawC - yawB) > 0.05, `yaw ${yawA.toFixed(2)} -> ${yawB.toFixed(2)} -> ${yawC.toFixed(2)}`);
await shot("12_spin_inertia.png");
await page.waitForTimeout(3500);
const vSettle = await tipDev();
ok("motion settles (damping)", vSettle < vSpin * 0.25, `${vSettle.toFixed(4)} m/s after 3.5 s`);
await page.click("[data-drag=camera]");

// in-browser GLB export
const glbB64 = await page.evaluate(() => { const b = window.studio.exportBytes(); let s = ""; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768)); return btoa(s); });
fs.writeFileSync(path.join(out, "studio_export.glb"), Buffer.from(glbB64, "base64"));
ok("GLB exported from the studio", glbB64.length > 1e6, `${(glbB64.length * 0.75 / 1e6).toFixed(1)} MB`);

// DNA export for Python validation
const dna = await page.evaluate(() => window.studio.toDNA());
fs.writeFileSync(path.join(out, "studio_export.dna.json"), JSON.stringify(dna, null, 1));
ok("DNA export produced", dna.schema === "forge.character-dna" && Object.keys(dna.traits).length > 60, `${Object.keys(dna.traits).length} traits`);
// reload: change things, then load the exported DNA back and compare
const pBefore = await page.evaluate(() => JSON.stringify(window.studio.state.params));
await page.click("[data-preset=male]"); await settle();
await page.evaluate((d) => window.studio.fromDNA(d), dna); await settle();
const pAfter = await page.evaluate(() => JSON.stringify(window.studio.state.params));
const a1 = JSON.parse(pBefore), a2 = JSON.parse(pAfter); let maxd = 0; for (const k of Object.keys(a1)) maxd = Math.max(maxd, Math.abs(a1[k] - a2[k]));
ok("DNA reload restores every parameter", maxd < 1e-3, `max difference ${maxd.toExponential(2)}`);
const fps = await page.evaluate(() => new Promise((r) => { const f0 = window.studio.frames, t0 = performance.now(); setTimeout(() => r((window.studio.frames - f0) / ((performance.now() - t0) / 1000)), 2000); }));
ok("frame rate measured (software GL, informational)", fps > 0, `${fps.toFixed(1)} fps under SwiftShader`);

// phone layout
await page.setViewportSize({ width: 400, height: 860 }); await settle(); await shot("11_phone.png");
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
ok("no horizontal scroll at phone width", !overflow);

ok("no console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
fs.writeFileSync(path.join(out, "smoke_report.json"), JSON.stringify({ checks, errors }, null, 1));
await browser.close();
process.exit(checks.every((c) => c.pass) ? 0 : 1);
