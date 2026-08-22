#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const baseUrl = new URL(process.env.MENTAT_WEB_BASE_URL || "http://127.0.0.1:8890");
const debugPort = Number(process.env.MENTAT_WEB_BROWSER_DEBUG_PORT || 9336);
const browserRuntimeRoot = resolve(
  process.env.MENTAT_WEB_BROWSER_RUNTIME_DIR
    || resolve(repoRoot, "data/runtime/web-foundation-smoke-runtime"),
);
const screenshotDirectory = process.env.MENTAT_WEB_SCREENSHOT_DIR
  ? resolve(process.env.MENTAT_WEB_SCREENSHOT_DIR)
  : "";
const normalizedBaseHostname = baseUrl.hostname.toLowerCase().replace(/^\[|\]$/gu, "");

if (
  baseUrl.protocol !== "http:"
  || !new Set(["127.0.0.1", "::1", "localhost"]).has(normalizedBaseHostname)
  || !baseUrl.port
  || baseUrl.pathname !== "/"
  || baseUrl.search
  || baseUrl.hash
) {
  throw new Error("MENTAT_WEB_BASE_URL must be an explicit loopback HTTP origin");
}
if (!Number.isSafeInteger(debugPort) || debugPort < 1024 || debugPort > 65535) {
  throw new Error("MENTAT_WEB_BROWSER_DEBUG_PORT must be between 1024 and 65535");
}
if (basename(browserRuntimeRoot) !== "web-foundation-smoke-runtime") {
  throw new Error("MENTAT_WEB_BROWSER_RUNTIME_DIR must end in web-foundation-smoke-runtime");
}

const ownedRuntimeDirectory = resolve(browserRuntimeRoot, `run-${process.pid}`);
const profileDirectory = resolve(ownedRuntimeDirectory, "profile");
const chromeCandidates = [
  process.env.CHROME_PATH,
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
].filter(Boolean);
const chromePath = chromeCandidates.find((candidate) => existsSync(candidate));
if (!chromePath) {
  throw new Error(`No Chrome/Chromium executable found. Checked: ${chromeCandidates.join(", ")}`);
}

function sleep(milliseconds) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds));
}

async function waitFor(operation, label, timeoutMilliseconds = 15000) {
  const deadline = Date.now() + timeoutMilliseconds;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const result = await operation();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`);
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise((resolveExit) => child.once("exit", resolveExit));
  child.kill("SIGTERM");
  await Promise.race([exited, sleep(5000)]);
  if (child.exitCode === null) {
    child.kill("SIGKILL");
    await Promise.race([new Promise((resolveExit) => child.once("exit", resolveExit)), sleep(1000)]);
  }
}

class CdpClient {
  constructor(webSocket) {
    this.ws = webSocket;
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
    this.eventErrors = [];
    webSocket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const pending = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message || JSON.stringify(message.error)));
        else pending.resolve(message.result || {});
        return;
      }
      if (!message.method) return;
      for (const handler of this.handlers.get(message.method) || []) {
        Promise.resolve(handler(message.params || {})).catch((error) => this.eventErrors.push(error));
      }
    };
  }

  on(method, handler) {
    const handlers = this.handlers.get(method) || new Set();
    handlers.add(handler);
    this.handlers.set(method, handlers);
    return () => handlers.delete(handler);
  }

  call(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolveCall, rejectCall) => {
      this.pending.set(id, { resolve: resolveCall, reject: rejectCall });
    });
  }

  async eval(expression) {
    const result = await this.call("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "Runtime evaluation failed");
    }
    return result.result?.value;
  }
}

async function setViewport(client, viewport) {
  await client.call("Emulation.setDeviceMetricsOverride", {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  });
}

async function inspectViewport(client, viewport) {
  await setViewport(client, viewport);
  let healthRequestId = "";
  const removePausedHandler = client.on("Fetch.requestPaused", ({ requestId, request }) => {
    if (new URL(request.url).pathname === "/api/bridge/health") {
      healthRequestId = requestId;
      return;
    }
    void client.call("Fetch.continueRequest", { requestId });
  });
  await client.call("Fetch.enable", {
    patterns: [{ urlPattern: `${baseUrl.origin}/api/bridge/health*`, requestStage: "Request" }],
  });

  try {
    await client.call("Page.navigate", { url: baseUrl.href });
    await waitFor(() => client.eval("document.readyState === 'complete'"), `${viewport.name} page load`);
    await waitFor(
      () => client.eval("document.querySelector('[aria-live]')?.textContent.includes('Checking private bridge')"),
      `${viewport.name} checking state`,
    );
    await waitFor(() => healthRequestId, `${viewport.name} held bridge request`);
    const checking = await client.eval(`(() => {
      const cards = [...document.querySelectorAll('.runtime-card')].map((element) => {
        const rect = element.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      });
      const status = document.querySelector('[aria-live]').getBoundingClientRect();
      return {
        cards,
        status: { width: status.width, height: status.height },
        overflow: document.documentElement.scrollWidth - innerWidth,
      };
    })()`);

    await client.call("Fetch.continueRequest", { requestId: healthRequestId });
    healthRequestId = "";
    await waitFor(
      () => client.eval("document.querySelector('[aria-live]')?.textContent.includes('Connected · Mentat')"),
      `${viewport.name} ready state`,
    );
    const ready = await client.eval(`(() => {
      const cards = [...document.querySelectorAll('.runtime-card')].map((element) => {
        const rect = element.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      });
      const statusElement = document.querySelector('[aria-live]');
      const status = statusElement.getBoundingClientRect();
      const brand = document.querySelector('.brand');
      return {
        cards,
        status: { width: status.width, height: status.height },
        title: document.title,
        heading: document.querySelector('h1')?.textContent?.trim() || '',
        headingCount: document.querySelectorAll('h1').length,
        mainCount: document.querySelectorAll('main').length,
        runtimeRegion: document.querySelector('[aria-label="Runtime readiness"]') !== null,
        bridgeLive: statusElement?.getAttribute('aria-live'),
        bridgeAtomic: statusElement?.getAttribute('aria-atomic'),
        statusText: statusElement?.textContent?.trim() || '',
        overflow: document.documentElement.scrollWidth - innerWidth,
        brandLabel: brand?.getAttribute('aria-label') || '',
        scriptPaths: [...document.scripts].map((script) => new URL(script.src, location.href).pathname),
        hasFlightPayload: document.documentElement.innerHTML.includes('self.__next_f'),
      };
    })()`);

    await client.call("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Tab",
      code: "Tab",
      windowsVirtualKeyCode: 9,
      nativeVirtualKeyCode: 9,
    });
    await client.call("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Tab",
      code: "Tab",
      windowsVirtualKeyCode: 9,
      nativeVirtualKeyCode: 9,
    });
    const keyboard = await client.eval(`(() => {
      const active = document.activeElement;
      const style = getComputedStyle(active);
      return {
        className: active?.className || '',
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
      };
    })()`);

    const geometryShift = ready.cards.reduce((maximum, card, index) => Math.max(
      maximum,
      Math.abs(card.width - checking.cards[index].width),
      Math.abs(card.height - checking.cards[index].height),
      Math.abs(card.left - checking.cards[index].left),
      Math.abs(card.top - checking.cards[index].top),
    ), 0);
    const expectedStacking = viewport.mobile
      ? ready.cards[1].top > ready.cards[0].top
      : Math.abs(ready.cards[1].top - ready.cards[0].top) < 1;
    if (
      ready.title !== "Mentat Runtime Foundation"
      || ready.heading !== "The new Mentat shell is running on Node."
      || ready.headingCount !== 1
      || ready.mainCount !== 1
      || !ready.runtimeRegion
      || ready.bridgeLive !== "polite"
      || ready.bridgeAtomic !== "true"
      || !ready.statusText.startsWith("Connected · Mentat")
      || ready.overflow > 1
      || checking.overflow > 1
      || geometryShift > 0.5
      || !expectedStacking
      || ready.brandLabel !== "Mentat runtime foundation home"
      || JSON.stringify(ready.scriptPaths) !== JSON.stringify(["/foundation-status.js"])
      || ready.hasFlightPayload
      || !String(keyboard.className).includes("brand")
      || keyboard.outlineStyle === "none"
      || Number.parseFloat(keyboard.outlineWidth) < 2
    ) {
      throw new Error(`${viewport.name} foundation contract failed: ${JSON.stringify({ checking, ready, keyboard, geometryShift, expectedStacking })}`);
    }

    if (screenshotDirectory) {
      mkdirSync(screenshotDirectory, { recursive: true });
      const screenshot = await client.call("Page.captureScreenshot", { format: "png", fromSurface: true });
      writeFileSync(resolve(screenshotDirectory, `node-foundation-${viewport.name}.png`), Buffer.from(screenshot.data, "base64"));
    }
    return { viewport, checking, ready, keyboard, geometryShift };
  } finally {
    if (healthRequestId) {
      await Promise.allSettled([client.call("Fetch.continueRequest", { requestId: healthRequestId })]);
    }
    removePausedHandler();
    await client.call("Fetch.disable");
  }
}

async function main() {
  let chrome;
  let client;
  const consoleErrors = [];
  try {
    mkdirSync(profileDirectory, { recursive: true });
    chrome = spawn(chromePath, [
      "--headless=new",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profileDirectory}`,
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--no-first-run",
      "--no-default-browser-check",
      "about:blank",
    ], { stdio: "ignore" });

    const page = await waitFor(async () => {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
      if (!response.ok) return null;
      const pages = await response.json();
      return pages.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
    }, "Chrome debug page", 30000);
    const webSocket = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolveOpen, rejectOpen) => {
      webSocket.onopen = resolveOpen;
      webSocket.onerror = () => rejectOpen(new Error("WebSocket connection to Chrome failed"));
    });
    client = new CdpClient(webSocket);
    client.on("Runtime.exceptionThrown", ({ exceptionDetails }) => {
      consoleErrors.push(exceptionDetails?.text || "uncaught runtime exception");
    });
    client.on("Runtime.consoleAPICalled", ({ type, args }) => {
      if (type === "error" || type === "assert") {
        consoleErrors.push(args?.map((argument) => argument.value || argument.description || "").join(" ") || type);
      }
    });
    client.on("Log.entryAdded", ({ entry }) => {
      if (entry?.level === "error") consoleErrors.push(entry.text || "browser log error");
    });
    await client.call("Runtime.enable");
    await client.call("Page.enable");
    await client.call("Log.enable");

    const results = [];
    for (const viewport of [
      { name: "desktop", width: 1440, height: 1000, mobile: false },
      { name: "phone", width: 390, height: 844, mobile: true },
    ]) {
      results.push(await inspectViewport(client, viewport));
    }
    if (client.eventErrors.length || consoleErrors.length) {
      throw new Error(`Browser console/event errors: ${JSON.stringify({ consoleErrors, eventErrors: client.eventErrors.map(String) })}`);
    }
    console.log(JSON.stringify({ ok: true, baseUrl: baseUrl.origin, results }, null, 2));
    client.ws.close();
  } finally {
    await stopChild(chrome);
    rmSync(ownedRuntimeDirectory, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 200,
    });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
