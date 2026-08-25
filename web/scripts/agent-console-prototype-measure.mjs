#!/usr/bin/env node

// THROWAWAY PROTOTYPE #132: repeatable browser evidence, not a production test.

import { existsSync } from "node:fs";
import { isAbsolute } from "node:path";

import { launch as launchChrome } from "chrome-launcher";

const baseUrl = new URL(
  process.env.MENTAT_PROTOTYPE_URL
    || "http://127.0.0.1:8893/prototype/agent-console-state",
);
const normalizedHost = baseUrl.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
if (
  baseUrl.protocol !== "http:"
  || !new Set(["127.0.0.1", "::1", "localhost"]).has(normalizedHost)
  || !baseUrl.port
) {
  throw new Error("MENTAT_PROTOTYPE_URL must be an explicit loopback HTTP URL");
}

const chromePath = process.env.CHROME_PATH?.trim() || "";
if (!chromePath || !isAbsolute(chromePath) || !existsSync(chromePath)) {
  throw new Error("CHROME_PATH must be an absolute local Chromium/Chrome executable");
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function jsonFetch(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

async function waitFor(check, label, timeoutMs = 30_000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const result = await check();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`);
}

function median(values) {
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

class CdpClient {
  constructor(webSocket) {
    this.webSocket = webSocket;
    this.nextId = 1;
    this.pending = new Map();
    webSocket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message || JSON.stringify(message.error)));
      else pending.resolve(message.result || {});
    };
  }

  call(method, params = {}) {
    const id = this.nextId++;
    this.webSocket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  async eval(expression) {
    const result = await this.call("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
      throw new Error(detail || "Browser evaluation failed");
    }
    return result.result?.value;
  }
}

function validatePass(result, reducedMotion) {
  const inputMedian = median(result.input_latency_ms);
  const switchMedian = median(result.switch_latency_ms);
  const streamMedian = median(result.stream_paint_ms);
  const failures = [];
  if (result.fixture_messages !== 2_000) failures.push("fixture size");
  if (result.paged_dom_messages > 200) failures.push("paged DOM bound");
  if (result.all_dom_messages < 2_000) failures.push("all-message comparison");
  // One 60 Hz frame plus scheduler/clock tolerance on the local reference run.
  if (inputMedian > 20) failures.push(`input median ${inputMedian}ms`);
  if (switchMedian > 50) failures.push(`switch median ${switchMedian}ms`);
  if (streamMedian > 250) failures.push(`stream median ${streamMedian}ms`);
  if (!result.stale_event_ignored || result.crossed_event_visible) failures.push("stream isolation");
  if (!result.draft_isolation) failures.push("draft isolation");
  if (!result.queue_cap_holds) failures.push("queue cap");
  if (!result.focus_retained) failures.push("focus retention");
  if (result.scroll_anchor_delta_px > 2) failures.push(`scroll anchoring ${result.scroll_anchor_delta_px}px`);
  if (!result.transcript_dom_order) failures.push("transcript DOM order");
  if (result.reduced_motion !== reducedMotion) failures.push("motion emulation");
  if (failures.length) throw new Error(`Prototype evidence failed: ${failures.join(", ")}`);
  return {
    ...result,
    medians: {
      input_latency_ms: inputMedian,
      switch_latency_ms: switchMedian,
      stream_paint_ms: streamMedian,
    },
  };
}

async function runPass(client, run, reducedMotion) {
  await client.call("Emulation.setEmulatedMedia", {
    media: "screen",
    features: [{ name: "prefers-reduced-motion", value: reducedMotion ? "reduce" : "no-preference" }],
  });
  await client.call("Page.navigate", { url: `${baseUrl.href}?run=${run}&motion=${reducedMotion ? "reduce" : "standard"}` });
  await waitFor(() => client.eval("document.readyState === 'complete'"), "page load");
  await waitFor(() => client.eval("document.documentElement.dataset.prototypeReady === 'true'"), "prototype readiness");
  const result = await client.eval("window.__MENTAT_PROTOTYPE__.benchmark()");
  return validatePass(result, reducedMotion);
}

async function main() {
  const chrome = await launchChrome({
    chromePath,
    chromeFlags: [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--no-first-run",
      "--no-default-browser-check",
    ],
    handleSIGINT: false,
    logLevel: "silent",
  });
  let webSocket;
  try {
    const page = await waitFor(async () => {
      const pages = await jsonFetch(`http://127.0.0.1:${chrome.port}/json/list`);
      return pages.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
    }, "Chrome page");
    webSocket = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      webSocket.onopen = resolve;
      webSocket.onerror = () => reject(new Error("Could not connect to Chrome DevTools"));
    });
    const client = new CdpClient(webSocket);
    await client.call("Runtime.enable");
    await client.call("Page.enable");
    await client.call("Emulation.setDeviceMetricsOverride", {
      width: 1512,
      height: 982,
      deviceScaleFactor: 1,
      mobile: false,
    });

    const standard = [];
    for (let run = 1; run <= 3; run += 1) standard.push(await runPass(client, run, false));
    const reduced = await runPass(client, 1, true);
    const summary = {
      artifact_schema: 1,
      ok: true,
      url: baseUrl.href,
      browser: await client.eval("navigator.userAgent"),
      viewport: await client.eval("({ width: innerWidth, height: innerHeight, devicePixelRatio })"),
      fixture_messages: 2_000,
      standard_runs: standard,
      reduced_motion_run: reduced,
      aggregate_medians: {
        paged_render_ms: median(standard.map((result) => result.paged_render_ms)),
        all_render_ms: median(standard.map((result) => result.all_render_ms)),
        input_latency_ms: median(standard.map((result) => result.medians.input_latency_ms)),
        switch_latency_ms: median(standard.map((result) => result.medians.switch_latency_ms)),
        stream_paint_ms: median(standard.map((result) => result.medians.stream_paint_ms)),
        profiler_commit_ms: median(standard.map((result) => result.profiler_commit_ms.median)),
      },
    };
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    webSocket?.close();
    chrome.kill();
  }
}

try {
  await main();
} catch (error) {
  console.error(error?.stack || error);
  process.exitCode = 1;
}
