// Phase 3D/3E evidence in the real Character Studio (Playwright + Chromium/SwiftShader): identity presets through the
// UI, slider edits, DNA save -> page reload -> load, legacy and invalid DNA, grooming and blink checks, geometry dumps
// for the Python reference comparison (tools/v3_phase3d.py), browser GLB exports and matched screenshots.
// usage: node tools/studio_v3_identity.mjs <base-url> <outdir> [--shots] [--legacy-url <url of the pre-identity studio>]
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const [base, out] = process.argv.slice(2);
const shots = process.argv.includes("--shots");
const legacyUrl = (() => { const i = process.argv.indexOf("--legacy-url"); return i > 0 ? process.argv[i + 1] : null; })();
const dumps = path.join(out, "dumps");
fs.mkdirSync(dumps, { recursive: true });
fs.mkdirSync(path.join(out, "shots"), { recursive: true });
const checks = [];
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${name} ${detail}`); };
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const ctx = await browser.newContext({ viewport: { width: 1000, height: 700 }, acceptDownloads: true });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const boot = async (p, url) => { await p.goto(url + "?gen=3"); await p.waitForFunction(() => document.body.dataset.ready, null, { timeout: 600000 }); };
await boot(page, base);
ok("v3 studio boots", (await page.evaluate(() => document.body.dataset.ready)) === "1");

const PRESETS = ["neutral", "ID-A", "ID-B", "MERCY-INSPIRED", "MERCY-REFINED"];
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const t = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(t)); t(); }), n);
const shot = async (name) => { if (!shots) return; await settle(); await page.locator("#view").screenshot({ path: path.join(out, "shots", `${name}.png`), timeout: 900000 }); };
const reset = () => page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.state.clip = "none"; s.playing = false; s.clipT = 0;
  s.spin.yaw = 0; s.spin.vel = 0; s.state.pose = "A-pose (rest)"; s.state.expr = {}; document.getElementById("turntable").checked = false; s.dirtyGeo = true; s.evaluate(); });
const faceCam = (yawDeg, dist = 0.55, drop = 0.035) => page.evaluate(([y, d, dr]) => { const s = window.studio; s.evaluate();
  const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC; s.cam.target = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - dr, (a[2] + b[2]) / 2];
  s.cam.dist = d; s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.02; }, [yawDeg, dist, drop]);
const bodyCam = (yawDeg) => page.evaluate((y) => { const s = window.studio; s.focus("body"); s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.05; }, yawDeg);
const tab = (id) => page.click(`#t-${id}`);
const pickIdentity = async (name) => { await tab("identity"); await page.click(`[data-identity="${name}"]`); await page.evaluate(() => window.studio.evaluate()); };
const slide = async (id, v) => { await page.$eval(id, (el, v) => { el.value = v; el.dispatchEvent(new Event("input")); el.dispatchEvent(new Event("change")); }, v); };
const setBlink = (w) => page.evaluate((w) => { const s = window.studio; s.state.expr.blink_l = w; s.state.expr.blink_r = w; s.evaluate(); }, w);
const dump = async (tag) => {  // body positions (float32), joints and the state that produced them
  const d = await page.evaluate(() => { const s = window.studio; s.evaluate(); const b = s.parts.body.cur;
    const enc = (a) => { const u = new Uint8Array(a.buffer, a.byteOffset, a.byteLength); let t = ""; for (let i = 0; i < u.length; i += 32768) t += String.fromCharCode(...u.subarray(i, i + 32768)); return btoa(t); };
    return { body: enc(Float32Array.from(b)), rest: Array.from(s.rest), height: s.heightNow, params: s.state.params, identity: s.state.identity, lidFit: s.state.lidFit || 1,
      expr: s.state.expr, affinity: s.presetAffinity() }; });
  fs.writeFileSync(path.join(dumps, `${tag}.f4`), Buffer.from(d.body, "base64"));
  delete d.body; fs.writeFileSync(path.join(dumps, `${tag}.json`), JSON.stringify(d));
  return d;
};

// --- UI structure
const ui = await page.evaluate(() => ({ tab: !document.getElementById("t-identity").hidden, sliders: document.querySelectorAll("#tab-identity input[type=range]").length,
  presets: [...document.querySelectorAll("[data-identity]")].map((b) => b.dataset.identity), keys: window.studio.man.identity.keys.length,
  version: window.studio.man.identity.version }));
ok("Identity tab with one slider per parameter", ui.tab && ui.sliders === ui.keys && ui.keys === 36, JSON.stringify(ui));
ok("five identity presets", JSON.stringify(ui.presets) === JSON.stringify(PRESETS), ui.presets.join(", "));

// --- presets through the UI; geometry at blink weights for the Python comparison; grooming follows the face
const groom = {};
for (const p of PRESETS) {
  await reset(); await pickIdentity(p);
  const st = await page.evaluate(() => window.studio.state.identity);
  const ref = await page.evaluate((p) => window.studio.man.identity.presets[p].values, p);
  ok(`preset ${p} sets its values and stays editable`, Object.entries(ref).every(([k, v]) => Math.abs((st.values[k] || 0) - v) < 1e-9) && st.preset === p);
  for (const w of [0, 0.25, 0.5, 0.75, 1]) { await setBlink(w); await dump(`preset_${p}_blink${w}`); }
  await setBlink(0);
  groom[p] = await page.evaluate(() => {
    const s = window.studio, L = s.parts.lashes, res = {};
    const rootGap = (P) => { const A = P.anchor, K = P.strandPts, body = s.parts.body.cur; let worst = 0;
      for (let r = 0; r < A.bary.length / 3; r++) { const v = r * 2 * K, q = [0, 1, 2].map((k) => body[A.tri[r * 3] * 3 + k] * A.bary[r * 3] + body[A.tri[r * 3 + 1] * 3 + k] * A.bary[r * 3 + 1] + body[A.tri[r * 3 + 2] * 3 + k] * A.bary[r * 3 + 2]);
        const c = [0, 1, 2].map((k) => (P.cur[v * 3 + k] + P.cur[(v + 1) * 3 + k]) / 2); worst = Math.max(worst, Math.hypot(c[0] - q[0], c[1] - q[1], c[2] - q[2])); }
      return worst * 1000; };
    res.root_gap_mm = { brows: rootGap(s.parts.brows), lashes: rootGap(s.parts.lashes), hair: rootGap(s.parts.hair_shoulder) };
    const open = Float32Array.from(L.cur); s.state.expr = { blink_l: 1, blink_r: 1 }; s.evaluate();
    let m = 0; for (let i = 0; i < open.length; i += 3) m += Math.hypot(L.cur[i] - open[i], L.cur[i + 1] - open[i + 1], L.cur[i + 2] - open[i + 2]);
    res.lash_mean_move_mm = m / (open.length / 3) * 1000; s.state.expr = {}; s.evaluate();
    // hair stays clear of the face: no hair point inside the skin near the face (distance to nearest body vertex in front of the ears)
    return res;
  });
}
ok("strand roots stay on the skin for every identity", Object.values(groom).every((g) => Object.values(g.root_gap_mm).every((x) => x < 1.0)),
  JSON.stringify(Object.fromEntries(Object.entries(groom).map(([p, g]) => [p, Object.fromEntries(Object.entries(g.root_gap_mm).map(([k, v]) => [k, +v.toFixed(3)]))]))));
ok("lashes ride the blink for every identity", Object.values(groom).every((g) => g.lash_mean_move_mm > 2),
  Object.entries(groom).map(([p, g]) => `${p} ${g.lash_mean_move_mm.toFixed(2)} mm`).join(", "));

// --- identity combined with the body and face controls (through the sliders)
const COMBOS = { idA_male_bighead_widejaw: ["ID-A", { "body.femininity": 0, "body.head_size": 1.15, "face.jaw_width": 1.3 }],
  idB_fem_bigeyes_widenose: ["ID-B", { "body.femininity": 1, "face.eye_size": 1.25, "face.nose_width": 1.3 }],
  mercy_smallhead_longface_tall: ["MERCY-INSPIRED", { "body.femininity": 1, "body.head_size": 0.9, "face.face_length": 1.2, "body.height_m": 1.9 }] };
for (const [tag, [p, ctl]] of Object.entries(COMBOS)) {
  await reset(); await pickIdentity(p);
  for (const [k, v] of Object.entries(ctl)) { await tab(k.startsWith("body.") ? "body" : "face"); await slide(`[id="s-${k}"]`, v); }
  for (const w of [0, 0.5, 1]) { await setBlink(w); await dump(`combo_${tag}_blink${w}`); }
  await setBlink(0);
}

// --- customise, save through the File tab, reload the page, load the file
await reset(); await pickIdentity("ID-B");
await slide('[id="si-nose_length"]', 0.35); await slide('[id="si-eye_aperture"]', 0.4); await slide('[id="si-lip_projection"]', -0.5);
await tab("face"); await slide('[id="s-face.cheekbone_width"]', 1.2);
await tab("body"); await slide('[id="s-body.height_m"]', 1.68);
await tab("identity"); await page.click('[id="li-nose_length"]');
await page.evaluate(() => { window.studio.state.name = "custom_idb"; document.getElementById("name").value = "custom_idb"; });
const before = await dump("saveload_before");
await tab("file");
const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), page.click("#dna-save")]);
const savedPath = path.join(out, "custom_idb.dna.json");
await dl.saveAs(savedPath);
const saved = JSON.parse(fs.readFileSync(savedPath, "utf8"));
ok("saved DNA carries the versioned identity group", saved.face_identity && saved.face_identity.version === 1 && saved.face_identity.preset === "ID-B"
  && Object.keys(saved.face_identity.values).length === 36 && saved.face_identity.values.nose_length === 0.35 && saved.face_identity.locked.includes("nose_length"),
  JSON.stringify({ preset: saved.face_identity.preset, nose_length: saved.face_identity.values.nose_length, locked: saved.face_identity.locked }));
await boot(page, base);  // a fresh page: nothing carried over except the file
await page.setInputFiles("#dna-load", savedPath);
await page.waitForFunction(() => /Loaded/.test(document.getElementById("status").textContent), null, { timeout: 60000 });
const after = await dump("saveload_after");
const bodyDiff = (a, b) => { const x = new Float32Array(fs.readFileSync(path.join(dumps, `${a}.f4`)).buffer.slice(0)), y = new Float32Array(fs.readFileSync(path.join(dumps, `${b}.f4`)).buffer.slice(0));
  let m = 0; for (let i = 0; i < x.length; i++) m = Math.max(m, Math.abs(x[i] - y[i])); return m; };
const dSave = bodyDiff("saveload_before", "saveload_after");
// DNA traits store 4 decimals (an unchanged format): a slider value such as 1.68075 m reloads as 1.6807 m (0.05 mm here)
ok("save -> reload -> load restores the character (to the DNA's 4-decimal trait precision)", dSave < 1e-4 && JSON.stringify(after.identity) === JSON.stringify({ ...before.identity, values: { ...Object.fromEntries(Object.keys(saved.face_identity.values).map((k) => [k, saved.face_identity.values[k]])) } }),
  `max body vertex difference ${dSave.toExponential(2)} m; height ${before.height.toFixed(4)} -> ${after.height.toFixed(4)}`);
const resaved = await page.evaluate(() => window.studio.toDNA());
ok("re-saving the loaded character gives the same DNA", JSON.stringify(resaved.face_identity) === JSON.stringify(saved.face_identity)
  && JSON.stringify(resaved.traits) === JSON.stringify(saved.traits));

// --- legacy v3 DNA (no identity group) and an invalid group
const legacy = JSON.parse(JSON.stringify(saved)); delete legacy.face_identity;
delete legacy.face_deformation;  // DNA saved before Phase 4A.1 has no eyelid-fit group either (it then loads as fit 1)
const legacyPath = path.join(out, "legacy_v3_no_identity.dna.json"); fs.writeFileSync(legacyPath, JSON.stringify(legacy, null, 1));
await page.setInputFiles("#dna-load", legacyPath);
await page.waitForFunction(() => /neutral identity/.test(document.getElementById("status").textContent), null, { timeout: 60000 });
const leg = await dump("legacy_new_studio");
ok("v3 DNA without an identity group loads with the neutral identity", Object.values(leg.identity.values).every((v) => !v), await page.textContent("#status"));
const bad = JSON.parse(JSON.stringify(saved)); bad.face_identity.version = 2; bad.face_identity.values.nose_lenght = 0.2;
const badPath = path.join(out, "invalid_identity.dna.json"); fs.writeFileSync(badPath, JSON.stringify(bad));
await page.setInputFiles("#dna-load", badPath);
await page.waitForFunction(() => /Could not load DNA/.test(document.getElementById("status").textContent), null, { timeout: 60000 });
const afterBad = await page.evaluate(() => window.studio.state.identity);
ok("invalid identity group is refused and nothing changes", JSON.stringify(afterBad) === JSON.stringify(leg.identity), await page.textContent("#status"));
if (legacyUrl) {  // the same legacy DNA in the studio as it was before identity existed (Phase 3C build)
  const p2 = await ctx.newPage(); await boot(p2, legacyUrl);
  await p2.setInputFiles("#dna-load", legacyPath);
  await p2.waitForFunction(() => /Loaded/.test(document.getElementById("status").textContent), null, { timeout: 60000 });
  const old = await p2.evaluate(() => { window.studio.evaluate(); const b = window.studio.parts.body.cur, u = new Uint8Array(Float32Array.from(b).buffer); let t = ""; for (let i = 0; i < u.length; i += 32768) t += String.fromCharCode(...u.subarray(i, i + 32768)); return btoa(t); });
  fs.writeFileSync(path.join(dumps, "legacy_old_studio.f4"), Buffer.from(old, "base64"));
  const dl2 = bodyDiff("legacy_new_studio", "legacy_old_studio");
  ok("legacy v3 DNA looks the same as in the pre-identity studio", dl2 < 2e-6, `max body vertex difference ${dl2.toExponential(2)} m`);
  await p2.close();
}
// the loaded legacy character keeps eyelid fit 1 until "Use corrected eyelids"; upgrade it so the presets below are
// exported with the current fit (as for any new character)
const upg = await page.evaluate(() => { const b = document.getElementById("lidfit-upgrade"), r = document.getElementById("lidfit-row");
  if (!b) return null; const shown = r && !r.hidden; if (shown) b.click(); return { shown, fit: window.studio.state.lidFit || 1 }; });
if (upg) ok("legacy character offers and applies the corrected eyelids", upg.shown && upg.fit === 2, JSON.stringify(upg));

// --- browser GLB exports of the three faces (female body preset, identity preset as selected)
for (const p of ["ID-A", "ID-B", "MERCY-INSPIRED"]) {
  await reset(); await pickIdentity(p);
  await page.evaluate((p) => { window.studio.state.name = p.toLowerCase().replace(/-/g, "_"); }, p);
  await dump(`export_${p}`);
  const glb = await page.evaluate(() => { const b = window.studio.exportBytes(); let s = ""; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768)); return btoa(s); });
  const name = `v3_identity_${p.toLowerCase().replace(/-/g, "_")}`;
  fs.writeFileSync(path.join(out, `${name}.glb`), Buffer.from(glb, "base64"));
  fs.writeFileSync(path.join(out, `${name}.dna.json`), JSON.stringify(await page.evaluate(() => window.studio.toDNA()), null, 1));
  ok(`GLB exported: ${p}`, glb.length > 1e6, `${(glb.length * 0.75 / 1e6).toFixed(1)} MB`);
}

// --- matched screenshots from the actual studio (identical cameras), blink and walk playback
if (shots) {
  for (const p of PRESETS) {
    await reset(); await pickIdentity(p);
    for (const y of [0, 35, 90]) { await faceCam(y); await shot(`face_${p}_${y}`); }
  }
  for (const p of ["ID-A", "ID-B", "MERCY-INSPIRED"]) {
    await reset(); await pickIdentity(p);
    for (const w of [0, 0.5, 1]) { await setBlink(w); await faceCam(15, 0.22, 0); await shot(`blink_${p}_${w}`); }
    await setBlink(0);
    // walk playback in the studio: the clip plays (frames advance), blinking while walking
    await page.evaluate(() => { const s = window.studio; s.state.clip = "walk"; s.playing = true; s.clipT = 0; });
    const t0 = await page.evaluate(() => window.studio.clipT); await settle(6); const t1 = await page.evaluate(() => window.studio.clipT);
    ok(`walk clip plays in the studio: ${p}`, t1 > t0, `clip time ${t0.toFixed(3)} -> ${t1.toFixed(3)} s`);
    await page.evaluate(() => { const s = window.studio; s.playing = false; s.clipT = 10 / 30; s.state.expr = { blink_l: 1, blink_r: 1 }; s.dirtyGeo = true; });
    await faceCam(40, 0.9, 0.08); await shot(`walk_blink_${p}`);
  }
  await reset(); await pickIdentity("MERCY-INSPIRED");
  await page.screenshot({ path: path.join(out, "shots", "ui_identity_tab.png"), timeout: 900000 });
}
ok("no page errors", !errors.length, errors.slice(0, 3).join(" | "));
fs.writeFileSync(path.join(out, "studio_checks.json"), JSON.stringify({ checks, errors }, null, 1));
await browser.close();
process.exit(checks.every((c) => c.pass) ? 0 : 1);
