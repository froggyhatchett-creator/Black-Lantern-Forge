// Phase 4A.1 evidence in the real Character Studio: identical cameras and states, run against the Phase 4A build
// ("before") and this build ("after"). Hair style bald (styling only). Eye close-ups open, at half and at full blink
// for Neutral, ID-A, ID-B and Mercy-inspired on the female body preset, the two named defects (ID-A and
// Mercy-inspired at eye size 0.8, the slider minimum), one identity/body stress combination, and a walk frame while
// blinking. With --dump: body and lash geometry for the Python comparison, and the historical-DNA checks (a Phase 4A
// DNA loads unchanged as eyelid fit 1; "Use corrected eyelids" switches it to fit 2; save -> reload keeps the fit).
// usage: node tools/studio_v3_eyelid.mjs <base-url> <outdir> <prefix> [--dump] [--legacy-dna <file>] [--legacy-only]
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const [base, out, prefix] = process.argv.slice(2);
const dumpOn = process.argv.includes("--dump"), legacyOnly = process.argv.includes("--legacy-only");
const li = process.argv.indexOf("--legacy-dna"), legacyDna = li > 0 ? process.argv[li + 1] : null;
fs.mkdirSync(path.join(out, "shots"), { recursive: true });
fs.mkdirSync(path.join(out, "dumps"), { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
page.setDefaultTimeout(900000);
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const t0 = Date.now();
await page.goto(base + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 600000 });
const bootS = (Date.now() - t0) / 1000;
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const t = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(t)); t(); }), n);
const shot = async (name) => { await settle(); await page.locator("#view").screenshot({ path: path.join(out, "shots", `${prefix}_${name}.png`) }); console.log("shot", name); };
const setup = async (idn, ctl = {}) => {
  await page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.state.clip = "none"; s.playing = false; s.clipT = 0; s.spin.yaw = 0;
    s.state.pose = "A-pose (rest)"; s.state.expr = {}; document.getElementById("turntable").checked = false; });
  await page.click("#t-identity"); await page.click(`[data-identity="${idn}"]`);
  await page.evaluate((ctl) => { const s = window.studio; for (const [k, v] of Object.entries(ctl)) s.setParam(k, v, { record: false }); s.state.hair_style = "bald"; s.evaluate(); }, ctl);
};
const blink = (w) => page.evaluate((w) => { const s = window.studio; s.state.expr = { blink_l: w, blink_r: w }; s.evaluate(); }, w);
const eyeCam = (yaw) => page.evaluate((y) => { const s = window.studio; s.evaluate(); const a = s.parts.eye_l.g.eyeC;
  s.cam.target = [a[0] - 0.012, a[1] - 0.002, a[2]]; s.cam.dist = 0.16; s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.05; }, yaw);
const grab = () => page.evaluate(() => { const s = window.studio; s.evaluate(); const enc = (f) => { const u = new Uint8Array(f.buffer); let t = "";
    for (let i = 0; i < u.length; i += 32768) t += String.fromCharCode(...u.subarray(i, i + 32768)); return btoa(t); };
  return { body: enc(Float32Array.from(s.parts.body.cur)), lashes: enc(Float32Array.from(s.parts.lashes.cur)), params: s.state.params,
    identity: s.state.identity, expr: s.state.expr, lidFit: s.state.lidFit || 1, height: s.heightNow }; });
const dump = async (tag) => {
  const d = await grab();
  fs.writeFileSync(path.join(out, "dumps", `${tag}.f4`), Buffer.from(d.body, "base64"));
  fs.writeFileSync(path.join(out, "dumps", `${tag}_lashes.f4`), Buffer.from(d.lashes, "base64"));
  delete d.body; delete d.lashes; fs.writeFileSync(path.join(out, "dumps", `${tag}.json`), JSON.stringify(d));
};
const CASES = [["neutral", {}], ["ID-A", {}], ["ID-B", {}], ["MERCY-INSPIRED", {}], ["ID-A", { "face.eye_size": 0.8 }],
  ["MERCY-INSPIRED", { "face.eye_size": 0.8 }], ["ID-A", { "body.femininity": 0.0, "body.head_size": 1.15, "face.jaw_width": 1.3 }]];
const tagOf = (idn, ctl) => idn + (ctl["face.eye_size"] ? `_eye${ctl["face.eye_size"]}` : "") + (ctl["body.head_size"] ? "_stress" : "");
const timing = {};
for (const [idn, ctl] of legacyOnly ? [] : CASES) {
  const tag = tagOf(idn, ctl);
  await setup(idn, ctl);
  for (const w of [0, 0.25, 0.5, 0.75, 1]) {
    const tb = Date.now(); await blink(w); if (w === 0.5) timing[tag] = (Date.now() - tb) / 1000;
    if (dumpOn) await dump(`blink_${tag}_${w}`);
    if ([0, 0.5, 1].includes(w)) for (const y of [10, 50]) { await eyeCam(y); await shot(`${tag}_w${w}_y${y}`); }
  }
}
// walking while blinking (studio playback state at walk frame 10)
await setup("ID-A");
if (legacyOnly) { const tb = Date.now(); await blink(0.5); timing["ID-A"] = (Date.now() - tb) / 1000; } else {
await page.evaluate(() => { const s = window.studio; s.state.clip = "walk"; s.playing = true; });
await settle(6);
await page.evaluate(() => { const s = window.studio; s.playing = false; s.clipT = 10 / 30; s.state.expr = { blink_l: 0.5, blink_r: 0.5 }; s.dirtyGeo = true;
  s.evaluate(); const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC; s.cam.target = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2]; s.cam.dist = 0.5; s.cam.yaw = 0.5; s.cam.pitch = 0.05; });
await shot("walk10_blink0.5");
}
// return to neutral: blink 1 then 0 restores the open geometry exactly
const ret = await page.evaluate(() => { const s = window.studio; s.state.clip = "none"; s.state.expr = {}; s.evaluate(); const a = Float32Array.from(s.parts.body.cur), l = Float32Array.from(s.parts.lashes.cur);
  s.state.expr = { blink_l: 1, blink_r: 1 }; s.evaluate(); s.state.expr = { blink_l: 0, blink_r: 0 }; s.evaluate();
  let m = 0, ml = 0; for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i] - s.parts.body.cur[i])); for (let i = 0; i < l.length; i++) ml = Math.max(ml, Math.abs(l[i] - s.parts.lashes.cur[i]));
  return { body_m: m, lashes_m: ml }; });
// historical DNA: load a Phase 4A DNA, dump it; (after only) upgrade, save, reload
const legacy = {};
if (legacyDna) {
  const dna = JSON.parse(fs.readFileSync(legacyDna, "utf8"));
  legacy.status = await page.evaluate((d) => { const s = window.studio; s.state.expr = {}; s.fromDNA(d); s.state.hair_style = "bald"; s.evaluate();
    return document.getElementById("status").textContent; }, dna);
  await dump("legacy_dna_loaded");
  legacy.fit_after_load = await page.evaluate(() => window.studio.state.lidFit || 1);
  legacy.upgrade_visible = await page.evaluate(() => { const r = document.getElementById("lidfit-row"); return r ? !r.hidden : null; });
  if (legacy.upgrade_visible) {
    await page.evaluate(() => document.getElementById("lidfit-upgrade").click());  // the DNA panel's tab may not be shown
    await dump("legacy_dna_upgraded");
    legacy.undo_restores_fit = await page.evaluate(() => { const s = window.studio; s.undo(); s.evaluate(); const f = s.state.lidFit || 1; s.redo(); s.evaluate(); return f; });
    legacy.redo_fit = await page.evaluate(() => window.studio.state.lidFit || 1);
    const saved = await page.evaluate(() => window.studio.toDNA());
    legacy.saved_group = saved.face_deformation || null;
    fs.writeFileSync(path.join(out, `${prefix}_upgraded.dna.json`), JSON.stringify(saved, null, 1));
    await page.evaluate((d) => { const s = window.studio; s.fromDNA(JSON.parse(JSON.stringify(d))); s.state.hair_style = "bald"; s.evaluate(); }, saved);
    await dump("legacy_dna_upgraded_reloaded");
    legacy.fit_after_reload = await page.evaluate(() => window.studio.state.lidFit || 1);
  }
}
const rep = { boot_s: bootS, blink_eval_s: timing, return_to_neutral: ret, legacy, errors };
console.log(JSON.stringify(rep));
fs.writeFileSync(path.join(out, `${prefix}_studio_eyelid${legacyOnly ? "_legacy" : ""}.json`), JSON.stringify(rep, null, 1));
await browser.close();
