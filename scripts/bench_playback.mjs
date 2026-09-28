// Phase 12B playback benchmark: headless Chrome over the DevTools protocol.
//
//   start the dev API (:8010) and Vite (:5180), then from the repo root:
//   node scripts/bench_playback.mjs            (CHROME_PATH=... to override the browser)
//
// Plays the real Dutch GP command center at 16x, switches to 64x, 1x and 4x,
// pauses and steps back, and prints JSON: animation-frame intervals, long
// tasks, spatial requests, and whether the map ever showed a state after the
// cursor or went back in time. Nothing is installed: Node's built-in fetch and
// WebSocket drive a throwaway Chrome profile that is deleted afterwards.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9333;
const URL = process.env.LFI_URL ?? "http://localhost:5180/?session=openf1%3A11353&lap=40";
const profile = mkdtempSync(join(tmpdir(), "lfi-cdp-"));
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--window-size=1440,900", "--no-first-run", "--no-default-browser-check", "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 50; i += 1) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent("about:blank")}`, { method: "PUT" });
      if (r.ok) return r.json();
    } catch { /* not up yet */ }
    await sleep(200);
  }
  throw new Error("chrome did not start");
}

const MEASURE = String.raw`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s) => document.querySelector(s);
  const meta = () => q('#cc-map .cc-panel-meta')?.textContent ?? '';
  const readout = () => q('.cc-replay-time')?.textContent ?? '';
  const secs = (txt) => { const m = /(\d\d):(\d\d):(\d\d\.\d)/.exec(txt); return m ? (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) : null; };
  const markers = () => document.querySelectorAll('#cc-map g.sm-marker').length;
  const alert = () => !!q('#cc-map [role=alert]');
  const rateBtn = (r) => [...document.querySelectorAll('.cc-replay-speed button')].find((b) => b.textContent.trim() === r + '\u00d7');
  const longs = [];
  new PerformanceObserver((l) => l.getEntries().forEach((e) => longs.push(e.duration))).observe({ type: 'longtask' });
  for (let i = 0; i < 40 && markers() === 0; i += 1) await sleep(250);
  const startState = { readout: readout(), meta: meta(), markers: markers() };

  async function run(rate, ms) {
    rateBtn(rate).click();
    performance.clearResourceTimings(); longs.length = 0;
    const frames = []; let last = performance.now(); const start = last; let going = true;
    const loop = (now) => { frames.push(now - last); last = now; if (going) requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    const t0 = secs(readout()); const samples = [];
    while (performance.now() - start < ms) {
      await sleep(100);
      samples.push([secs(readout()), secs(meta()), meta().includes('lag'), markers(), alert()]);
    }
    going = false;
    const f = frames.slice(2).sort((a, b) => a - b);
    const pct = (p) => (f.length ? +f[Math.min(f.length - 1, Math.floor(p * f.length))].toFixed(1) : null);
    const res = performance.getEntriesByType('resource').filter((e) => e.name.includes('/spatial'));
    const shown = samples.map((s) => s[1]).filter((x) => x != null);
    const paired = samples.filter((s) => s[0] != null && s[1] != null);
    return {
      rate, wallMs: ms, raceSeconds: +(secs(readout()) - t0).toFixed(1),
      frames: f.length, fps: +(f.length / (ms / 1000)).toFixed(1), p50: pct(0.5), p95: pct(0.95), p99: pct(0.99),
      max: f.length ? +f[f.length - 1].toFixed(1) : null, over33: f.filter((x) => x > 33.4).length,
      over50: f.filter((x) => x > 50).length,
      longTasks: longs.length, longMax: longs.length ? Math.round(Math.max(...longs)) : 0,
      windowRequests: res.filter((e) => e.name.includes('/window')).map((e) => [decodeURIComponent(e.name).replace(/^.*step=/, 'step='), Math.round(e.duration), e.transferSize]),
      atRequests: res.filter((e) => !e.name.includes('/window')).length,
      // Phase 12C: car telemetry windows while a driver is selected (LFI_URL with &driver=)
      telemetryRequests: performance.getEntriesByType('resource')
        .filter((e) => e.name.includes('/api/v1/') && e.name.includes('/telemetry/'))
        .map((e) => [Math.round(e.duration), e.transferSize]),
      shownNeverAfterCursor: paired.every((s) => s[1] <= s[0] + 0.05),
      shownNeverBack: shown.every((x, i) => i === 0 || x >= shown[i - 1]),
      maxLagS: paired.length ? Math.max(...paired.map((s) => +(s[0] - s[1]).toFixed(1))) : null,
      lagSamples: samples.filter((s) => s[2]).length, samples: samples.length,
      minMarkers: Math.min(...samples.map((s) => s[3])), errorSamples: samples.filter((s) => s[4]).length,
    };
  }

  rateBtn(16).click();
  q('button[aria-label="Play replay"]').click();
  const r16 = await run(16, 3750);
  const r64 = await run(64, 2500);
  const r1 = await run(1, 2500);
  const r4 = await run(4, 2500);
  q('button[aria-label="Pause replay"]')?.click();
  await sleep(800);
  const paused = { readout: readout(), meta: meta(), markers: markers(), error: alert(),
                   exact: secs(meta()) === secs(readout()) };
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
  await sleep(30);
  const afterSeekBack = { readout: readout(), meta: meta(), markers: markers(),
                          shownAfterCursor: secs(meta()) != null && secs(meta()) > secs(readout()) + 0.05 };
  await sleep(800);
  const settled = { readout: readout(), meta: meta(), markers: markers(), error: alert(),
                    exact: secs(meta()) === secs(readout()) };
  return { startState, r16, r64, r1, r4, paused, afterSeekBack, settled,
           visibility: document.visibilityState, ua: navigator.userAgent.replace(/.*(HeadlessChrome\/[\d.]+).*/, '$1') };
})()`;

try {
  const t = await target();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0; const waiting = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); } };
  const send = (method, params = {}) => new Promise((r) => { id += 1; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: URL });
  await sleep(6000);
  const out = await send("Runtime.evaluate", { expression: MEASURE, awaitPromise: true, returnByValue: true, timeout: 120000 });
  console.log(JSON.stringify(out.result?.result?.value ?? out, null, 1));
  ws.close();
} finally {
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* chrome may still hold files */ }
}
