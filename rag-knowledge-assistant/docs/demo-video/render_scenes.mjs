// Renders each explainer scene frame-by-frame (deterministic) and encodes it with ffmpeg.
// Usage: node render_scenes.mjs [sceneId ...]   (default: all)   |   --preview sceneId t1 t2 ...
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright'); // resolves the preinstalled Playwright via NODE_PATH
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const here = path.dirname(new URL(import.meta.url).pathname);
const OUT = path.join(here, 'build'); fs.mkdirSync(OUT, { recursive: true });
const FPS = 30;
const url = id => 'file://' + path.join(here, 'scenes.html') + '?scene=' + id;

async function open(browser, id) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(url(id)); await page.evaluate(() => document.fonts.ready);
  return page;
}

async function renderScene(browser, id) {
  const page = await open(browser, id);
  const dur = await page.evaluate(() => window.__duration);
  const cdp = await page.context().newCDPSession(page);
  const out = path.join(OUT, `scene_${id}.mp4`);
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(FPS), '-movflags', '+faststart', out]);
  const n = Math.round(dur * FPS);
  for (let i = 0; i < n; i++) {
    await page.evaluate(t => window.__render(t), i / FPS);
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 93 });
    if (!ff.stdin.write(Buffer.from(data, 'base64'))) await new Promise(r => ff.stdin.once('drain', r));
  }
  ff.stdin.end(); await new Promise(r => ff.on('close', r));
  await page.close(); console.log(`scene ${id}: ${n} frames → ${path.basename(out)}`);
}

const args = process.argv.slice(2);
const browser = await chromium.launch();
if (args[0] === '--preview') {
  const [, id, ...ts] = args; const page = await open(browser, id);
  for (const t of ts) { await page.evaluate(t => window.__render(+t), t); await page.screenshot({ path: path.join(OUT, `preview_${id}_${t}.png`) }); }
} else {
  const ids = args.length ? args : await (async () => { const p = await open(browser, 'title'); const r = await p.evaluate(() => SCENES.map(s => s.id)); await p.close(); return r; })();
  const queue = [...ids]; const workers = Array.from({ length: 2 }, async () => { while (queue.length) await renderScene(browser, queue.shift()); });
  await Promise.all(workers);
}
await browser.close();
