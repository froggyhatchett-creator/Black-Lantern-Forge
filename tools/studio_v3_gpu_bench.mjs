// Character Studio (generator v3) responsiveness benchmark: run it on a machine with a real GPU.
// It reports the WebGL renderer string first: "SwiftShader" / "llvmpipe" / "Software" means software rendering and
// the numbers are not a hardware result.
//
// usage: node tools/studio_v3_gpu_bench.mjs <studio-url> <outdir> [--headed] [--channel chrome|msedge] [--swiftshader]
//   (start the studio first: python3 -m forge_character_forge studio --port 8799)
// Measures: initial load (page open -> studio ready), orbit-camera frame times, identity-slider latency (value change
// -> next drawn frame), blink playback frame times (first blink after a shape change separately: it builds the lash
// contact), shoulder-hair frame times, and browser GLB export time and size. Writes <outdir>/gpu_bench.json.
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const [url, out] = args;
const flag = (n) => args.includes(n);
const opt = (n) => (args.indexOf(n) >= 0 ? args[args.indexOf(n) + 1] : undefined);
let chromium;
try { ({ chromium } = await import("playwright")); }
catch { ({ chromium } = await import("/opt/node-tools/node_modules/playwright/index.mjs")); }  // this repo's CI container
fs.mkdirSync(out, { recursive: true });
const launch = { headless: !flag("--headed"), channel: opt("--channel"),
  args: flag("--swiftshader") ? ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] : ["--ignore-gpu-blocklist", "--enable-gpu-rasterization"] };
const browser = await chromium.launch(launch);
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.setDefaultTimeout(900000);
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const t0 = Date.now();
await page.goto(url.replace(/\/?$/, "/") + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 600000 });
const r = { load_s: (Date.now() - t0) / 1000 };
r.renderer = await page.evaluate(() => { const g = document.getElementById("view").getContext("webgl2"); const e = g.getExtension("WEBGL_debug_renderer_info");
  return { vendor: e ? g.getParameter(e.UNMASKED_VENDOR_WEBGL) : g.getParameter(g.VENDOR), renderer: e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : g.getParameter(g.RENDERER) }; });
r.software = /swiftshader|llvmpipe|software|basic render/i.test(`${r.renderer.vendor} ${r.renderer.renderer}`);
console.log("renderer", JSON.stringify(r.renderer), r.software ? "(SOFTWARE: not a hardware result)" : "(hardware)");
// frame times of n frames while f(i) runs before each one
const frames = (n, f) => page.evaluate(async ({ n, src }) => { const fn = new Function("i", "s", src); const s = window.studio, dts = [];
  for (let i = 0; i < n; i++) { const a = performance.now(); fn(i, s); await new Promise((res) => { const f0 = s.frames; const t = () => (s.frames > f0 ? res() : requestAnimationFrame(t)); t(); });
    dts.push(performance.now() - a); }
  dts.sort((x, y) => x - y); return { frames: n, median_ms: +dts[n >> 1].toFixed(1), p95_ms: +dts[Math.floor(n * 0.95)].toFixed(1), max_ms: +dts[n - 1].toFixed(1) }; }, { n, src: f });
await page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.applyIdentityPreset("ID-A", false); s.state.clip = "none"; s.playing = false; s.dirtyGeo = true; });
await frames(5, "");
r.orbit = await frames(90, "s.cam.yaw = i * 0.07;");
r.identity_slider = await frames(20, "s.setIdentity('nose_length', (i % 2 ? 0.6 : -0.6), { record: false });");
r.blink_first_after_shape_change = await frames(1, "s.state.expr = { blink_l: 0.5, blink_r: 0.5 }; s.dirtyGeo = true;");
r.blink_playback = await frames(40, "const w = 0.5 - 0.5 * Math.cos(i / 40 * 2 * Math.PI); s.state.expr = { blink_l: w, blink_r: w }; s.dirtyGeo = true;");
r.walk_with_blink = await frames(60, "if (!i) { s.state.clip = 'walk'; s.playing = true; } const w = 0.5 - 0.5 * Math.cos(i / 30 * 2 * Math.PI); s.state.expr = { blink_l: w, blink_r: w }; s.dirtyGeo = true;");
await page.evaluate(() => { const s = window.studio; s.state.clip = "none"; s.playing = false; s.state.expr = {}; s.state.hair_style = "shoulder"; s.dirtyGeo = true; });
r.hair_shoulder_orbit = await frames(60, "s.cam.yaw = i * 0.1;");
r.export = await page.evaluate(() => { const a = performance.now(); const b = window.studio.exportBytes(); return { seconds: +((performance.now() - a) / 1000).toFixed(2), bytes: b.length }; });
await page.locator("#view").screenshot({ path: path.join(out, "gpu_bench_final.png") });
r.errors = errors;
fs.writeFileSync(path.join(out, "gpu_bench.json"), JSON.stringify(r, null, 1));
console.log(JSON.stringify(r, null, 1));
await browser.close();
