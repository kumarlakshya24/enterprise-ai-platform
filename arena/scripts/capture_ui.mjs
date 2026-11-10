#!/usr/bin/env node
// Headless screenshots of the demo UI, plus a silent mp4 and gif.
// Requires google-chrome and ffmpeg. Reuses the API if :8097 is already up.

import { spawn } from "node:child_process";
import { copyFileSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const assets = resolve(root, "docs/assets");
const port = process.env.ARENA_PORT || "8097";
const base = `http://127.0.0.1:${port}`;
const shots = [
  ["weekly", "weekly.png"],
  ["compare", "compare.png"],
  ["lora", "lora.png"],
  ["distilled", "distilled.png"],
  ["low", "low-volume.png"],
  ["memo", "memo.png"],
  ["pipeline", "pipeline.png"],
];
const film = ["weekly.png", "compare.png", "lora.png", "distilled.png", "low-volume.png", "memo.png"];

mkdirSync(assets, { recursive: true });

function wait(ms) {
  return new Promise((resolveWait) => setTimeout(resolveWait, ms));
}

async function portOpen() {
  try {
    const response = await fetch(`${base}/healthz`);
    return response.ok;
  } catch {
    return false;
  }
}

async function waitFor(fn, label, tries = 50) {
  for (let i = 0; i < tries; i += 1) {
    if (await fn()) return;
    await wait(200);
  }
  throw new Error(`timed out waiting for ${label}`);
}

function startApi() {
  const python = resolve(root, ".venv/bin/python");
  return spawn(python, ["-m", "arena"], {
    cwd: root,
    env: { ...process.env, ARENA_PORT: port, ARENA_HOST: "127.0.0.1" },
    stdio: "ignore",
  });
}

function startChrome(debugPort) {
  return spawn(
    "google-chrome",
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--hide-scrollbars",
      "--user-data-dir=/tmp/arena-chrome",
      "--window-size=1440,1000",
      `--remote-debugging-port=${debugPort}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
}

async function cdpSend(ws, method, params = {}) {
  const id = cdpSend.next++;
  const payload = JSON.stringify({ id, method, params });
  const reply = new Promise((resolveReply, rejectReply) => {
    const onMessage = (raw) => {
      const message = JSON.parse(raw.data);
      if (message.id !== id) return;
      ws.removeEventListener("message", onMessage);
      if (message.error) rejectReply(new Error(JSON.stringify(message.error)));
      else resolveReply(message.result || {});
    };
    ws.addEventListener("message", onMessage);
  });
  ws.send(payload);
  return reply;
}
cdpSend.next = 1;

async function shoot(debugPort, query, filename) {
  const created = await fetch(`http://127.0.0.1:${debugPort}/json/new?${base}/?shot=${query}`, {
    method: "PUT",
  });
  if (!created.ok) throw new Error(`json/new failed: ${created.status}`);
  const target = await created.json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolveOpen, rejectOpen) => {
    ws.addEventListener("open", resolveOpen);
    ws.addEventListener("error", () => rejectOpen(new Error("devtools websocket failed")));
  });
  await cdpSend(ws, "Runtime.enable");
  await cdpSend(ws, "Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await waitFor(async () => {
    const result = await cdpSend(ws, "Runtime.evaluate", {
      expression: "document.body && document.body.dataset.ready === 'true'",
      returnByValue: true,
    });
    return Boolean(result.result && result.result.value);
  }, query);
  const shot = await cdpSend(ws, "Page.captureScreenshot", { format: "png" });
  writeFileSync(resolve(assets, filename), Buffer.from(shot.data, "base64"));
  ws.close();
  await fetch(`http://127.0.0.1:${debugPort}/json/close/${target.id}`);
  console.log("wrote", filename);
}

function ffmpeg(args) {
  return new Promise((resolveDone, rejectDone) => {
    const child = spawn("ffmpeg", args, { stdio: "inherit" });
    child.on("exit", (code) => (code === 0 ? resolveDone() : rejectDone(new Error(`ffmpeg ${code}`))));
  });
}

const frameScale = "scale=trunc(iw/2)*2:trunc(ih/2)*2";

async function encode(frameDir) {
  const input = resolve(frameDir, "frame-%02d.png");
  await ffmpeg([
    "-y",
    "-framerate",
    "1/2",
    "-i",
    input,
    "-vf",
    frameScale,
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    resolve(assets, "arena-demo.mp4"),
  ]);
  const palette = resolve(frameDir, "palette.png");
  await ffmpeg([
    "-y",
    "-framerate",
    "1/2",
    "-i",
    input,
    "-vf",
    `${frameScale},palettegen=stats_mode=full:max_colors=256`,
    palette,
  ]);
  await ffmpeg([
    "-y",
    "-framerate",
    "1/2",
    "-i",
    input,
    "-i",
    palette,
    "-lavfi",
    `${frameScale}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle`,
    "-gifflags",
    "+offsetting+transdiff",
    "-loop",
    "0",
    resolve(assets, "arena-demo.gif"),
  ]);
}

const debugPort = 9333;
let api = null;
let chrome = null;
try {
  if (!(await portOpen())) {
    api = startApi();
    await waitFor(portOpen, "api");
  }
  chrome = startChrome(debugPort);
  await waitFor(async () => {
    try {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/version`);
      return response.ok;
    } catch {
      return false;
    }
  }, "chrome");
  for (const [query, filename] of shots) {
    await shoot(debugPort, query, filename);
  }
  const frameDir = "/tmp/arena-frames";
  rmSync(frameDir, { recursive: true, force: true });
  mkdirSync(frameDir, { recursive: true });
  film.forEach((filename, index) => {
    const frame = `frame-${String(index + 1).padStart(2, "0")}.png`;
    copyFileSync(resolve(assets, filename), resolve(frameDir, frame));
  });
  await encode(frameDir);
  console.log("wrote arena-demo.mp4");
  console.log("wrote arena-demo.gif");
} finally {
  if (chrome) chrome.kill();
  if (api) api.kill();
}
