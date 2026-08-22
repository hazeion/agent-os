#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const baseUrl = new URL(process.env.MENTAT_WEB_BASE_URL || "http://127.0.0.1:8890");
const debugPort = Number(process.env.MENTAT_WEB_BROWSER_DEBUG_PORT || 9336);
const clientNavigationMode = process.env.MENTAT_WEB_CLIENT_NAVIGATION === "1";
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

const routes = [
  { path: "/", heading: "Home", title: "Mentat" },
  { path: "/agents", heading: "Agents", title: "Agents · Mentat" },
  { path: "/tasks", heading: "Tasks", title: "Tasks · Mentat" },
  { path: "/runs", heading: "Runs", title: "Runs · Mentat" },
];
const viewports = [
  { name: "wide", width: 1680, height: 1050, mobile: false, mode: "desktop" },
  { name: "desktop", width: 1440, height: 900, mobile: false, mode: "desktop" },
  { name: "compact", width: 1024, height: 768, mobile: false, mode: "compact" },
  { name: "mobile-boundary", width: 900, height: 900, mobile: false, mode: "drawer" },
  { name: "tablet", width: 768, height: 1024, mobile: true, mode: "drawer" },
  { name: "phone", width: 390, height: 844, mobile: true, mode: "drawer" },
];

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

async function navigate(client, path, label) {
  await client.call("Page.navigate", { url: new URL(path, baseUrl).href });
  await waitFor(
    () => client.eval("document.readyState === 'complete' && document.querySelector('.app-shell') !== null"),
    `${label} shell load`,
  );
}

async function dispatchKey(client, key, { shift = false } = {}) {
  const keyCode = key === "Tab" ? 9 : key === "Escape" ? 27 : 0;
  const code = key === "Tab" ? "Tab" : key === "Escape" ? "Escape" : key;
  const modifiers = shift ? 8 : 0;
  await client.call("Input.dispatchKeyEvent", {
    type: "keyDown",
    key,
    code,
    modifiers,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
  await client.call("Input.dispatchKeyEvent", {
    type: "keyUp",
    key,
    code,
    modifiers,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
}

async function dispatchPointerClick(client, point) {
  await client.call("Input.dispatchMouseEvent", {
    type: "mousePressed",
    button: "left",
    buttons: 1,
    clickCount: 1,
    x: point.x,
    y: point.y,
  });
  await client.call("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    button: "left",
    buttons: 0,
    clickCount: 1,
    x: point.x,
    y: point.y,
  });
}

async function inspectRoutes(client) {
  await setViewport(client, viewports[1]);
  const results = [];
  for (const route of routes) {
    await navigate(client, route.path, `${route.heading} route`);
    const result = await client.eval(`(() => ({
      title: document.title,
      heading: document.querySelector('h1')?.textContent?.trim() || '',
      headingCount: document.querySelectorAll('h1').length,
      mainCount: document.querySelectorAll('main').length,
      current: document.querySelector('[aria-current="page"] .nav-copy strong')?.textContent?.trim() || '',
      currentCount: document.querySelectorAll('[aria-current="page"]').length,
      scriptPaths: [...document.scripts].map((script) => new URL(script.src, location.href).pathname),
      hasFlightPayload: document.documentElement.innerHTML.includes('self.__next_f'),
      hasLogo: document.querySelector('.brand-mark')?.getAttribute('src') === '/mentat-mark-emerald.png',
      overflow: document.documentElement.scrollWidth - innerWidth,
    }))()`);
    if (
      result.title !== route.title
      || result.heading !== route.heading
      || result.current !== route.heading
      || result.headingCount !== 1
      || result.mainCount !== 1
      || result.currentCount !== 1
      || JSON.stringify(result.scriptPaths) !== JSON.stringify(["/preference-preload.js", "/shell-runtime.js"])
      || result.hasFlightPayload
      || !result.hasLogo
      || result.overflow > 1
    ) {
      throw new Error(`${route.heading} route contract failed: ${JSON.stringify(result)}`);
    }
    results.push({ route, result });
  }
  return results;
}

async function inspectPreEnhancementMobileNavigation(client) {
  await setViewport(client, viewports.at(-1));
  let runtimeRequestId = "";
  const removePausedHandler = client.on("Fetch.requestPaused", ({ requestId, request }) => {
    if (new URL(request.url).pathname === "/shell-runtime.js") runtimeRequestId = requestId;
  });
  await client.call("Fetch.enable", {
    patterns: [{ urlPattern: `${baseUrl.origin}/shell-runtime.js*`, requestStage: "Request" }],
  });

  try {
    await client.call("Page.navigate", { url: baseUrl.href });
    await waitFor(
      () => client.eval("document.readyState !== 'loading' && document.querySelector('.app-shell') !== null"),
      "pre-enhancement mobile shell",
    );
    await waitFor(() => runtimeRequestId, "held shell runtime request");
    await client.eval("document.activeElement?.blur()");
    await dispatchKey(client, "Tab");
    const firstFocus = await client.eval("document.activeElement?.classList.contains('skip-link')");
    await dispatchKey(client, "Tab");
    const result = await client.eval(`(() => ({
      sidebarVisibility: getComputedStyle(document.querySelector('.sidebar')).visibility,
      activeLabel: document.activeElement?.getAttribute('aria-label') || '',
      activeInsideSidebar: document.querySelector('.sidebar')?.contains(document.activeElement),
      drawerOpen: document.documentElement.dataset.navOpen === 'true',
    }))()`);
    if (
      !firstFocus
      || result.sidebarVisibility !== "hidden"
      || result.activeLabel !== "Open navigation"
      || result.activeInsideSidebar
      || result.drawerOpen
    ) {
      throw new Error(`pre-enhancement mobile navigation contract failed: ${JSON.stringify({ firstFocus, result })}`);
    }

    await client.call("Fetch.continueRequest", { requestId: runtimeRequestId });
    runtimeRequestId = "";
    await client.call("Fetch.disable");
    await waitFor(
      () => client.eval("document.readyState === 'complete' && document.querySelector('[data-bridge-status]')?.dataset.state === 'ready'"),
      "enhanced mobile shell",
    );
    return { firstFocus, ...result };
  } finally {
    if (runtimeRequestId) {
      await Promise.allSettled([client.call("Fetch.continueRequest", { requestId: runtimeRequestId })]);
    }
    removePausedHandler();
    await Promise.allSettled([client.call("Fetch.disable")]);
  }
}

async function captureGeometry(client) {
  return client.eval(`(() => {
    const rect = (element) => {
      const value = element.getBoundingClientRect();
      return { left: value.left, right: value.right, top: value.top, width: value.width, height: value.height };
    };
    return {
      bridge: rect(document.querySelector('.bridge-status')),
      panels: [...document.querySelectorAll('.panel')].map(rect),
      sidebar: rect(document.querySelector('.sidebar')),
      workspace: rect(document.querySelector('.workspace')),
      navOpenDisplay: getComputedStyle(document.querySelector('[data-nav-open]')).display,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  })()`);
}

async function inspectViewport(client, viewport) {
  await setViewport(client, viewport);
  let healthRequestId = "";
  const removePausedHandler = client.on("Fetch.requestPaused", ({ requestId }) => {
    healthRequestId = requestId;
  });
  await client.call("Fetch.enable", {
    patterns: [{ urlPattern: `${baseUrl.origin}/api/bridge/health*`, requestStage: "Request" }],
  });

  try {
    await navigate(client, "/", `${viewport.name} viewport`);
    await waitFor(
      () => client.eval("document.querySelector('[data-bridge-status-text]')?.textContent === 'Checking Python'"),
      `${viewport.name} checking state`,
    );
    await waitFor(() => healthRequestId, `${viewport.name} held bridge request`);
    const checking = await captureGeometry(client);

    await client.call("Fetch.continueRequest", { requestId: healthRequestId });
    healthRequestId = "";
    await waitFor(
      () => client.eval("document.querySelector('[data-bridge-status]')?.dataset.state === 'ready'"),
      `${viewport.name} ready state`,
    );
    const ready = await captureGeometry(client);
    const details = await client.eval(`(() => ({
      bridgeLive: document.querySelector('[data-bridge-status]')?.getAttribute('aria-live'),
      bridgeAtomic: document.querySelector('[data-bridge-status]')?.getAttribute('aria-atomic'),
      bridgeText: document.querySelector('[data-bridge-status-text]')?.textContent,
      bridgeCompact: document.querySelector('[data-bridge-status-compact]')?.textContent,
      contrast: document.documentElement.dataset.contrast,
      heading: document.querySelector('h1')?.textContent?.trim(),
      active: document.querySelector('[aria-current="page"] .nav-copy strong')?.textContent?.trim(),
      sidebarHidden: document.querySelector('.sidebar')?.getAttribute('aria-hidden'),
    }))()`);

    const geometryShift = Math.max(
      Math.abs(ready.bridge.width - checking.bridge.width),
      Math.abs(ready.bridge.height - checking.bridge.height),
      ...ready.panels.flatMap((panel, index) => [
        Math.abs(panel.left - checking.panels[index].left),
        Math.abs(panel.top - checking.panels[index].top),
        Math.abs(panel.width - checking.panels[index].width),
        Math.abs(panel.height - checking.panels[index].height),
      ]),
    );
    const panelsStack = viewport.width <= 900
      ? ready.panels[1].top > ready.panels[0].top
      : Math.abs(ready.panels[1].top - ready.panels[0].top) < 1;
    const modeValid = viewport.mode === "desktop"
      ? Math.abs(ready.sidebar.width - 216) < 1 && Math.abs(ready.workspace.left - 216) < 1 && ready.navOpenDisplay === "none"
      : viewport.mode === "compact"
        ? Math.abs(ready.sidebar.width - 76) < 1 && Math.abs(ready.workspace.left - 76) < 1 && ready.navOpenDisplay === "none"
        : ready.sidebar.right <= 1 && Math.abs(ready.workspace.left) < 1 && ready.navOpenDisplay !== "none" && details.sidebarHidden === "true";

    if (
      ready.overflow > 1
      || checking.overflow > 1
      || geometryShift > 0.5
      || !panelsStack
      || !modeValid
      || details.bridgeLive !== "polite"
      || details.bridgeAtomic !== "true"
      || details.bridgeText !== "Python ready"
      || details.bridgeCompact !== "Ready"
      || details.contrast !== "standard"
      || details.heading !== "Home"
      || details.active !== "Home"
    ) {
      throw new Error(`${viewport.name} responsive contract failed: ${JSON.stringify({ checking, ready, details, geometryShift, panelsStack, modeValid })}`);
    }

    if (screenshotDirectory) {
      mkdirSync(screenshotDirectory, { recursive: true });
      const screenshot = await client.call("Page.captureScreenshot", { format: "png", fromSurface: true });
      writeFileSync(resolve(screenshotDirectory, `node-shell-${viewport.name}.png`), Buffer.from(screenshot.data, "base64"));
    }
    return { viewport, checking, ready, details, geometryShift };
  } finally {
    if (healthRequestId) {
      await Promise.allSettled([client.call("Fetch.continueRequest", { requestId: healthRequestId })]);
    }
    removePausedHandler();
    await client.call("Fetch.disable");
  }
}

async function inspectKeyboardDrawerAndContrast(client) {
  const phone = viewports.at(-1);
  await setViewport(client, phone);
  await navigate(client, "/", "phone interaction");

  await client.eval("document.activeElement?.blur()");
  await dispatchKey(client, "Tab");
  const skipFocus = await client.eval(`(() => {
    const active = document.activeElement;
    const style = getComputedStyle(active);
    return { className: active?.className || '', outlineWidth: Number.parseFloat(style.outlineWidth) };
  })()`);

  await client.eval("document.querySelector('[data-nav-open]').click()");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === 'true'"), "drawer open");
  await waitFor(
    () => client.eval("Math.abs(document.querySelector('.sidebar').getBoundingClientRect().left) < 1"),
    "drawer transition",
  );
  const opened = await client.eval(`(() => ({
    expanded: document.querySelector('[data-nav-open][aria-controls]').getAttribute('aria-expanded'),
    backdropHidden: document.querySelector('[data-nav-backdrop]').hidden,
    sidebarLeft: document.querySelector('.sidebar').getBoundingClientRect().left,
    workspaceInert: document.querySelector('[data-workspace]').inert,
    activeLabel: document.activeElement?.getAttribute('aria-label') || '',
  }))()`);

  await client.eval("document.querySelector('.brand').focus()");
  await dispatchKey(client, "Tab", { shift: true });
  const trapped = await client.eval("document.activeElement?.querySelector('.nav-copy strong')?.textContent || ''");
  await dispatchKey(client, "Escape");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === undefined"), "drawer close");
  const closed = await client.eval(`(() => ({
    expanded: document.querySelector('[data-nav-open][aria-controls]').getAttribute('aria-expanded'),
    backdropHidden: document.querySelector('[data-nav-backdrop]').hidden,
    sidebarHidden: document.querySelector('.sidebar').getAttribute('aria-hidden'),
    workspaceInert: document.querySelector('[data-workspace]').inert,
    focusReturned: document.activeElement === document.querySelector('[data-nav-open]'),
  }))()`);

  await client.eval("document.querySelector('[data-nav-open][aria-controls]').click()");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === 'true'"), "drawer backdrop open");
  await client.eval("document.querySelector('[data-nav-backdrop]').click()");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === undefined"), "drawer backdrop close");
  const backdropClosed = await client.eval(`(() => ({
    hidden: document.querySelector('[data-nav-backdrop]').hidden,
    focusReturned: document.activeElement === document.querySelector('[data-nav-open][aria-controls]'),
  }))()`);

  await client.eval("document.querySelector('[data-nav-open][aria-controls]').click()");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === 'true'"), "drawer resize open");
  await setViewport(client, viewports[2]);
  await waitFor(
    () => client.eval("document.activeElement === document.querySelector('[data-nav-link][aria-current=\"page\"]')"),
    "desktop breakpoint focus",
  );
  const desktopBreakpointFocus = await client.eval(`(() => ({
    drawerOpen: document.documentElement.dataset.navOpen === 'true',
    sidebarHidden: document.querySelector('.sidebar').getAttribute('aria-hidden'),
    active: document.activeElement?.querySelector('.nav-copy strong')?.textContent || '',
  }))()`);
  await setViewport(client, phone);
  await waitFor(
    () => client.eval("document.activeElement === document.querySelector('[data-nav-open][aria-controls]')"),
    "mobile breakpoint focus",
  );
  const mobileBreakpointFocus = await client.eval(`(() => ({
    sidebarHidden: document.querySelector('.sidebar').getAttribute('aria-hidden'),
    focusReturned: document.activeElement === document.querySelector('[data-nav-open][aria-controls]'),
  }))()`);

  await client.eval(`(() => {
    const select = document.querySelector('[data-contrast-select]');
    select.value = 'high';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await client.call("Page.reload", { ignoreCache: true });
  await waitFor(
    () => client.eval("document.readyState === 'complete' && document.documentElement.dataset.shellRuntime === 'ready' && document.documentElement.dataset.contrast === 'high'"),
    "persisted high contrast",
  );
  const contrast = await client.eval(`(() => ({
    mode: document.documentElement.dataset.contrast,
    preference: document.documentElement.dataset.contrastPreference,
    selected: document.querySelector('[data-contrast-select]').value,
    accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
  }))()`);
  await client.eval("localStorage.removeItem('mentat-contrast-v1')");

  if (
    !String(skipFocus.className).includes("skip-link")
    || skipFocus.outlineWidth < 2
    || opened.expanded !== "true"
    || opened.backdropHidden
    || Math.abs(opened.sidebarLeft) > 1
    || !opened.workspaceInert
    || opened.activeLabel !== "Close navigation"
    || trapped !== "Runs"
    || closed.expanded !== "false"
    || !closed.backdropHidden
    || closed.sidebarHidden !== "true"
    || closed.workspaceInert
    || !closed.focusReturned
    || !backdropClosed.hidden
    || !backdropClosed.focusReturned
    || desktopBreakpointFocus.drawerOpen
    || desktopBreakpointFocus.sidebarHidden !== "false"
    || desktopBreakpointFocus.active !== "Home"
    || mobileBreakpointFocus.sidebarHidden !== "true"
    || !mobileBreakpointFocus.focusReturned
    || contrast.mode !== "high"
    || contrast.preference !== "high"
    || contrast.selected !== "high"
    || contrast.accent.toLowerCase() !== "#bdf7b9"
  ) {
    throw new Error(`phone interaction contract failed: ${JSON.stringify({ skipFocus, opened, trapped, closed, backdropClosed, desktopBreakpointFocus, mobileBreakpointFocus, contrast })}`);
  }

  return { skipFocus, opened, trapped, closed, backdropClosed, desktopBreakpointFocus, mobileBreakpointFocus, contrast };
}

async function inspectUnavailableBridge(client) {
  const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", {
    source: `(() => {
      const nativeFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        return url.pathname === '/api/bridge/health'
          ? Promise.reject(new TypeError('bridge_unavailable'))
          : nativeFetch(input, init);
      };
    })();`,
  });
  try {
    const results = [];
    for (const probe of [
      { name: "desktop", viewport: viewports[1], width: 156, height: 38, compact: false },
      { name: "phone", viewport: viewports.at(-1), width: 78, height: 44, compact: true },
    ]) {
      await setViewport(client, probe.viewport);
      await navigate(client, "/", `${probe.name} unavailable bridge`);
      await waitFor(
        () => client.eval("document.querySelector('[data-bridge-status]')?.dataset.state === 'unavailable'"),
        `${probe.name} unavailable bridge state`,
      );
      const result = await client.eval(`(() => {
        const status = document.querySelector('.bridge-status');
        const rect = status.getBoundingClientRect();
        const compact = document.querySelector('[data-bridge-status-compact]');
        return {
          text: document.querySelector('[data-bridge-status-text]')?.textContent,
          compactText: compact?.textContent,
          compactVisible: getComputedStyle(compact).display !== 'none',
          width: rect.width,
          height: rect.height,
          overflow: document.documentElement.scrollWidth - innerWidth,
        };
      })()`);
      if (
        result.text !== "Python unavailable"
        || result.compactText !== "Offline"
        || result.compactVisible !== probe.compact
        || result.width !== probe.width
        || result.height !== probe.height
        || result.overflow > 1
      ) {
        throw new Error(`${probe.name} unavailable bridge contract failed: ${JSON.stringify(result)}`);
      }
      results.push({ probe: probe.name, result });
    }
    return results;
  } finally {
    await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier });
  }
}

async function inspectAgentsWorkspace(client) {
  await setViewport(client, viewports[1]);
  let agentsRequestId = "";
  const removePausedHandler = client.on("Fetch.requestPaused", ({ requestId }) => {
    agentsRequestId = requestId;
  });
  await client.call("Fetch.enable", {
    patterns: [{ urlPattern: `${baseUrl.origin}/api/agents*`, requestStage: "Request" }],
  });
  try {
    await navigate(client, "/agents", "Agents workspace");
    await waitFor(
      () => client.eval("document.querySelector('[data-agents-root]')?.dataset.agentsState === 'loading'"),
      "Agents loading state",
    );
    await waitFor(() => agentsRequestId, "held Agents request");
    const loading = await client.eval(`(() => ({
      summary: document.querySelector('[data-agents-summary]')?.textContent,
      busy: document.querySelector('[data-agents-root]')?.getAttribute('aria-busy'),
      refreshDisabled: document.querySelector('[data-agents-refresh]')?.disabled,
      cards: document.querySelectorAll('.agent-card').length,
    }))()`);
    await client.call("Fetch.continueRequest", { requestId: agentsRequestId });
    agentsRequestId = "";
    await client.call("Fetch.disable");
    await waitFor(
      () => client.eval("document.querySelector('[data-agents-root]')?.dataset.agentsState !== 'loading'"),
      "Agents ready state",
    );
    const loaded = await client.eval(`(() => ({
      state: document.querySelector('[data-agents-root]')?.dataset.agentsState,
      summary: document.querySelector('[data-agents-summary]')?.textContent,
      busy: document.querySelector('[data-agents-root]')?.getAttribute('aria-busy'),
      refreshDisabled: document.querySelector('[data-agents-refresh]')?.disabled,
      cards: [...document.querySelectorAll('.agent-card')].map((card) => ({
        name: card.querySelector('h3')?.textContent,
        fields: [...card.querySelectorAll('.agent-field dd')].map((value) => value.textContent),
        capabilities: [...card.querySelectorAll('.agent-capabilities li')].map((value) => value.textContent),
      })),
      overflow: document.documentElement.scrollWidth - innerWidth,
    }))()`);
    if (
      loading.summary !== "Loading canonical Agents…"
      || loading.busy !== "true"
      || !loading.refreshDisabled
      || loading.cards !== 0
      || !new Set(["ready", "empty"]).has(loaded.state)
      || loaded.busy !== "false"
      || loaded.refreshDisabled
      || loaded.overflow > 1
      || (loaded.state === "empty" && (loaded.summary !== "No canonical Agents yet." || loaded.cards.length !== 0))
      || (loaded.state === "ready" && loaded.cards.some((card) => (
        !card.name || card.fields.length !== 3 || card.capabilities.length === 0
      )))
    ) {
      throw new Error(`Agents workspace contract failed: ${JSON.stringify({ loading, loaded })}`);
    }

    const requestsBeforeRefresh = await client.eval(
      "performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/agents').length",
    );
    await client.eval("document.querySelector('[data-agents-refresh]').click()");
    await waitFor(
      () => client.eval(`performance.getEntriesByType('resource')
        .filter((entry) => new URL(entry.name).pathname === '/api/agents').length > ${requestsBeforeRefresh}`),
      "Agents refresh request",
    );
    await waitFor(
      () => client.eval("document.querySelector('[data-agents-root]')?.dataset.agentsState !== 'loading'"),
      "Agents refresh completion",
    );
    return { loading, loaded };
  } finally {
    if (agentsRequestId) {
      await Promise.allSettled([client.call("Fetch.continueRequest", { requestId: agentsRequestId })]);
    }
    removePausedHandler();
    await Promise.allSettled([client.call("Fetch.disable")]);
  }
}

async function inspectAgentFailureStates(client) {
  const states = [
    { name: "unsupported", status: 501, detail: "This Python bridge does not support Agent data yet." },
    { name: "unavailable", status: 503, detail: "Agent data is temporarily unavailable. Check the Python connection and retry." },
    { name: "error", status: 502, detail: "Mentat could not safely read Agent data. Try again." },
  ];
  const results = [];
  for (const state of states) {
    const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", {
      source: `(() => {
        const nativeFetch = window.fetch.bind(window);
        window.fetch = (input, init) => {
          const url = new URL(typeof input === 'string' ? input : input.url, location.href);
          if (url.pathname !== '/api/agents') return nativeFetch(input, init);
          return Promise.resolve(new Response(JSON.stringify({ schema_version: 1, status: '${state.name}' }), {
            status: ${state.status},
            headers: { 'Content-Type': 'application/json' },
          }));
        };
      })();`,
    });
    try {
      await navigate(client, "/agents", `Agents ${state.name}`);
      await waitFor(
        () => client.eval(`document.querySelector('[data-agents-root]')?.dataset.agentsState === '${state.name}'`),
        `Agents ${state.name} state`,
      );
      const result = await client.eval(`(() => ({
        summary: document.querySelector('[data-agents-summary]')?.textContent,
        busy: document.querySelector('[data-agents-root]')?.getAttribute('aria-busy'),
        cards: document.querySelectorAll('.agent-card').length,
        refreshDisabled: document.querySelector('[data-agents-refresh]')?.disabled,
      }))()`);
      if (result.summary !== state.detail || result.busy !== "false" || result.cards !== 0 || result.refreshDisabled) {
        throw new Error(`Agents ${state.name} contract failed: ${JSON.stringify(result)}`);
      }
      results.push({ name: state.name, result });
    } finally {
      await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier });
    }
  }
  return results;
}

async function inspectAgentProjection(client) {
  const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", {
    source: `(() => {
      const nativeFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        if (url.pathname !== '/api/agents') return nativeFetch(input, init);
        return Promise.resolve(new Response(JSON.stringify({
          schema_version: 1,
          status: 'ready',
          count: 1,
          agents: [{
            id: 'agent_researcher',
            name: 'Researcher',
            runtime_type: 'hermes',
            runtime_config_id: 'runtime_config_researcher',
            capabilities: ['browser-use', 'research.web'],
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
      };
    })();`,
  });
  try {
    await navigate(client, "/agents", "Agents projection");
    await waitFor(
      () => client.eval("document.querySelector('[data-agents-root]')?.dataset.agentsState === 'ready'"),
      "Agents projection state",
    );
    const result = await client.eval(`(() => ({
      summary: document.querySelector('[data-agents-summary]')?.textContent,
      cardCount: document.querySelectorAll('.agent-card').length,
      name: document.querySelector('.agent-card h3')?.textContent,
      fields: [...document.querySelectorAll('.agent-field dd')].map((value) => value.textContent),
      capabilities: [...document.querySelectorAll('.agent-capabilities li')].map((value) => value.textContent),
      rendered: document.querySelector('[data-agents-list]')?.textContent,
    }))()`);
    if (
      result.summary !== "1 canonical Agent."
      || result.cardCount !== 1
      || result.name !== "Researcher"
      || JSON.stringify(result.fields) !== JSON.stringify(["agent_researcher", "hermes", "runtime_config_researcher"])
      || JSON.stringify(result.capabilities) !== JSON.stringify(["browser-use", "research.web"])
      || result.rendered.includes("runtime_agent_ref")
      || result.rendered.includes("private")
    ) {
      throw new Error(`Agents projection contract failed: ${JSON.stringify(result)}`);
    }
    return result;
  } finally {
    await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier });
  }
}

async function inspectTasksWorkspace(client) {
  await setViewport(client, viewports[1]);
  await navigate(client, "/tasks", "Tasks workspace");
  await waitFor(() => client.eval("document.querySelector('[data-tasks-root]')?.dataset.tasksState !== 'loading'"), "Tasks ready state");
  const result = await client.eval(`(() => ({
    state: document.querySelector('[data-tasks-root]')?.dataset.tasksState,
    summary: document.querySelector('[data-tasks-summary]')?.textContent,
    cards: document.querySelectorAll('.task-card').length,
    rendered: document.querySelector('[data-tasks-list]')?.textContent,
    overflow: document.documentElement.scrollWidth - innerWidth,
  }))()`);
  if (!new Set(["ready", "empty"]).has(result.state) || result.overflow > 1 || (result.state === "empty" && (result.summary !== "No current Tasks yet." || result.cards !== 0)) || (result.state === "ready" && result.cards === 0) || result.rendered.includes("description") || result.rendered.includes("delegation")) throw new Error(`Tasks workspace contract failed: ${JSON.stringify({ state: result.state, summary: result.summary, cards: result.cards, overflow: result.overflow })}`);
  const before = await client.eval("performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/tasks').length");
  await client.eval("document.querySelector('[data-tasks-refresh]').click()");
  await waitFor(() => client.eval(`performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/tasks').length > ${before}`), "Tasks refresh request");
  return { state: result.state, summary: result.summary, cards: result.cards, overflow: result.overflow };
}

async function inspectTaskFailureStates(client) {
  const states = [
    { name: "unsupported", status: 501, detail: "This Python bridge does not support Task data yet." },
    { name: "unavailable", status: 503, detail: "Task data is temporarily unavailable. Check the Python connection and retry." },
    { name: "error", status: 502, detail: "Mentat could not safely read Task data. Try again." },
  ]; const results = [];
  for (const state of states) {
    const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const nativeFetch = window.fetch.bind(window); window.fetch = (input, init) => { const url = new URL(typeof input === 'string' ? input : input.url, location.href); return url.pathname === '/api/tasks' ? Promise.resolve(new Response(JSON.stringify({ schema_version: 1, status: '${state.name}' }), { status: ${state.status}, headers: { 'Content-Type': 'application/json' } })) : nativeFetch(input, init); }; })();` });
    try { await navigate(client, "/tasks", `Tasks ${state.name}`); await waitFor(() => client.eval(`document.querySelector('[data-tasks-root]')?.dataset.tasksState === '${state.name}'`), `Tasks ${state.name} state`); const result = await client.eval(`({ summary: document.querySelector('[data-tasks-summary]')?.textContent, cards: document.querySelectorAll('.task-card').length })`); if (result.summary !== state.detail || result.cards !== 0) throw new Error(`Tasks ${state.name} contract failed: ${JSON.stringify(result)}`); results.push({ name: state.name, result }); } finally { await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier }); }
  } return results;
}

async function inspectRunsWorkspace(client) {
  await setViewport(client, viewports[1]);
  await navigate(client, "/runs", "Runs workspace");
  await waitFor(() => client.eval("document.querySelector('[data-runs-root]')?.dataset.runsState !== 'loading'"), "Runs ready state");
  const result = await client.eval(`(() => ({
    state: document.querySelector('[data-runs-root]')?.dataset.runsState,
    summary: document.querySelector('[data-runs-summary]')?.textContent,
    cards: document.querySelectorAll('.run-card').length,
    rendered: document.querySelector('[data-runs-list]')?.textContent,
    overflow: document.documentElement.scrollWidth - innerWidth,
  }))()`);
  if (!new Set(["ready", "empty"]).has(result.state) || result.overflow > 1 || (result.state === "empty" && (result.summary !== "No current Runs yet." || result.cards !== 0)) || (result.state === "ready" && result.cards === 0) || result.rendered.includes("runtime_run_ref") || result.rendered.includes("state_revision") || result.rendered.includes("events")) throw new Error(`Runs workspace contract failed: ${JSON.stringify({ state: result.state, summary: result.summary, cards: result.cards, overflow: result.overflow })}`);
  const before = await client.eval("performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/runs').length");
  await client.eval("document.querySelector('[data-runs-refresh]').click()");
  await waitFor(() => client.eval(`performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/runs').length > ${before}`), "Runs refresh request");
  return { state: result.state, summary: result.summary, cards: result.cards, overflow: result.overflow };
}

async function inspectRunFailureStates(client) {
  const states = [
    { name: "unsupported", status: 501, detail: "This Python bridge does not support Run data yet." },
    { name: "unavailable", status: 503, detail: "Run data is temporarily unavailable. Check the Python connection and retry." },
    { name: "error", status: 502, detail: "Mentat could not safely read Run data. Try again." },
  ]; const results = [];
  for (const state of states) {
    const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const nativeFetch = window.fetch.bind(window); window.fetch = (input, init) => { const url = new URL(typeof input === 'string' ? input : input.url, location.href); return url.pathname === '/api/runs' ? Promise.resolve(new Response(JSON.stringify({ schema_version: 1, status: '${state.name}' }), { status: ${state.status}, headers: { 'Content-Type': 'application/json' } })) : nativeFetch(input, init); }; })();` });
    try { await navigate(client, "/runs", `Runs ${state.name}`); await waitFor(() => client.eval(`document.querySelector('[data-runs-root]')?.dataset.runsState === '${state.name}'`), `Runs ${state.name} state`); const result = await client.eval(`({ summary: document.querySelector('[data-runs-summary]')?.textContent, cards: document.querySelectorAll('.run-card').length })`); if (result.summary !== state.detail || result.cards !== 0) throw new Error(`Runs ${state.name} contract failed: ${JSON.stringify(result)}`); results.push({ name: state.name, result }); } finally { await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier }); }
  } return results;
}

async function inspectRunProjection(client) {
  await setViewport(client, viewports.at(-1));
  const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const nativeFetch = window.fetch.bind(window); window.fetch = (input, init) => { const url = new URL(typeof input === 'string' ? input : input.url, location.href); if (url.pathname !== '/api/runs') return nativeFetch(input, init); return Promise.resolve(new Response(JSON.stringify({ schema_version: 1, service: 'mentat-local-bridge', runtime: 'python', status: 'ready', count: 1, runs: [{ id: 'run_' + 'x'.repeat(124), source: 'task_dispatch', task_id: 'task_1', agent_id: 'agent_researcher', runtime_type: 'hermes', status: 'waiting_for_approval', dispatch_state: 'accepted', partial: false, timeline_truncated: false, created_at: '2026-08-22T00:00:00Z', updated_at: '2026-08-22T00:01:00Z', started_at: '2026-08-22T00:00:01Z', completed_at: null }] }), { status: 200, headers: { 'Content-Type': 'application/json' } })); }; })();` });
  try {
    await navigate(client, "/runs", "Runs projection");
    await waitFor(() => client.eval("document.querySelector('[data-runs-root]')?.dataset.runsState === 'ready'"), "Runs projection state");
    const result = await client.eval(`(() => ({ summary: document.querySelector('[data-runs-summary]')?.textContent, cards: document.querySelectorAll('.run-card').length, rendered: document.querySelector('[data-runs-list]')?.textContent, overflow: document.documentElement.scrollWidth - innerWidth }))()`);
    if (result.summary !== "1 current Run." || result.cards !== 1 || result.overflow > 1 || !["task_dispatch", "task_1", "agent_researcher", "hermes", "Waiting For Approval", "accepted", "2026-08-22T00:00:00Z", "2026-08-22T00:01:00Z", "2026-08-22T00:00:01Z", "Not completed"].every((value) => result.rendered.includes(value)) || result.rendered.includes("runtime_run_ref") || result.rendered.includes("state_revision")) throw new Error(`Runs projection contract failed: ${JSON.stringify({ summary: result.summary, cards: result.cards, overflow: result.overflow })}`);
    return { summary: result.summary, cards: result.cards, overflow: result.overflow };
  } finally { await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier }); }
}

async function inspectRunMalformedPayload(client) {
  const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const nativeFetch = window.fetch.bind(window); window.fetch = (input, init) => { const url = new URL(typeof input === 'string' ? input : input.url, location.href); return url.pathname === '/api/runs' ? Promise.resolve(new Response(JSON.stringify({ schema_version: 1, service: 'mentat-local-bridge', runtime: 'python', status: 'ready', runs: [], count: 0, unexpected: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })) : nativeFetch(input, init); }; })();` });
  try {
    await navigate(client, "/runs", "Runs malformed payload");
    await waitFor(() => client.eval("document.querySelector('[data-runs-root]')?.dataset.runsState === 'error'"), "Runs malformed payload state");
    const result = await client.eval(`({ summary: document.querySelector('[data-runs-summary]')?.textContent, cards: document.querySelectorAll('.run-card').length })`);
    if (result.summary !== "Mentat could not safely read Run data. Try again." || result.cards !== 0) throw new Error(`Runs malformed payload contract failed: ${JSON.stringify(result)}`);
    return result;
  } finally { await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier }); }
}

async function inspectRunRejectedFetch(client) {
  const injection = await client.call("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const nativeFetch = window.fetch.bind(window); window.fetch = (input, init) => { const url = new URL(typeof input === 'string' ? input : input.url, location.href); return url.pathname === '/api/runs' ? Promise.reject(new TypeError('runs_unavailable')) : nativeFetch(input, init); }; })();` });
  try {
    await navigate(client, "/runs", "Runs rejected fetch");
    await waitFor(() => client.eval("document.querySelector('[data-runs-root]')?.dataset.runsState === 'error'"), "Runs rejected fetch state");
    const result = await client.eval(`({ summary: document.querySelector('[data-runs-summary]')?.textContent, cards: document.querySelectorAll('.run-card').length })`);
    if (result.summary !== "Mentat could not safely read Run data. Try again." || result.cards !== 0) throw new Error(`Runs rejected fetch contract failed: ${JSON.stringify(result)}`);
    return result;
  } finally { await client.call("Page.removeScriptToEvaluateOnNewDocument", { identifier: injection.identifier }); }
}

async function inspectCompactPointerAndTooltip(client) {
  await setViewport(client, viewports[2]);
  await navigate(client, "/", "compact navigation");
  await client.eval("document.activeElement?.blur()");
  for (let index = 0; index < 4; index += 1) await dispatchKey(client, "Tab");
  await waitFor(
    () => client.eval("document.activeElement?.getAttribute('href') === '/agents'"),
    "compact keyboard navigation",
  );
  const point = await client.eval(`(() => {
    const link = document.activeElement;
    const rect = link.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  await waitFor(
    () => client.eval("document.querySelector('[data-nav-tooltip]')?.hidden === false"),
    "compact keyboard tooltip",
  );
  const tooltip = await client.eval(`(() => {
    const value = document.querySelector('[data-nav-tooltip]');
    const tooltipRect = value.getBoundingClientRect();
    const sidebarRect = document.querySelector('.sidebar').getBoundingClientRect();
    return {
      hidden: value.hidden,
      text: value.textContent,
      left: tooltipRect.left,
      right: tooltipRect.right,
      top: tooltipRect.top,
      bottom: tooltipRect.bottom,
      sidebarRight: sidebarRect.right,
      viewportWidth: innerWidth,
      viewportHeight: innerHeight,
    };
  })()`);
  await dispatchPointerClick(client, point);
  await waitFor(
    () => client.eval("location.pathname === '/agents' && document.querySelector('h1')?.textContent === 'Agents'"),
    "compact pointer navigation",
  );
  const result = await client.eval(`(() => ({
    path: location.pathname,
    active: document.querySelector('[aria-current="page"] .nav-copy strong')?.textContent,
    overflow: document.documentElement.scrollWidth - innerWidth,
  }))()`);
  if (
    tooltip.hidden
    || tooltip.text !== "Agents"
    || tooltip.left < tooltip.sidebarRight
    || tooltip.right > tooltip.viewportWidth
    || tooltip.top < 0
    || tooltip.bottom > tooltip.viewportHeight
    || result.path !== "/agents"
    || result.active !== "Agents"
    || result.overflow > 1
  ) {
    throw new Error(`compact pointer and tooltip contract failed: ${JSON.stringify({ tooltip, result })}`);
  }
  return { tooltip, result };
}

async function inspectCompactShortHeight(client) {
  await setViewport(client, { width: 1024, height: 320, mobile: false });
  await navigate(client, "/", "short compact navigation");
  await waitFor(
    () => client.eval("document.documentElement.dataset.shellRuntime === 'ready'"),
    "short compact shell runtime",
  );
  await client.eval("document.activeElement?.blur()");
  for (let index = 0; index < 6; index += 1) await dispatchKey(client, "Tab");
  await waitFor(
    () => client.eval("document.activeElement?.getAttribute('href') === '/runs'"),
    "short compact keyboard navigation",
  );
  await waitFor(
    () => client.eval("document.querySelector('[data-nav-tooltip]')?.hidden === false"),
    "short compact Runs tooltip",
  );
  const result = await client.eval(`(() => {
    const sidebar = document.querySelector('.sidebar');
    const primaryNav = document.querySelector('.primary-nav');
    const runs = document.activeElement;
    const tooltip = document.querySelector('[data-nav-tooltip]');
    const navRect = primaryNav.getBoundingClientRect();
    const runsRect = runs.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const sidebarRect = sidebar.getBoundingClientRect();
    return {
      active: runs?.getAttribute('href') || '',
      sidebarOverflow: getComputedStyle(sidebar).overflowY,
      navOverflow: getComputedStyle(primaryNav).overflowY,
      navScrollHeight: primaryNav.scrollHeight,
      navClientHeight: primaryNav.clientHeight,
      navScrollTop: primaryNav.scrollTop,
      runsVisible: runsRect.top >= navRect.top && runsRect.bottom <= navRect.bottom,
      tooltipHidden: tooltip.hidden,
      tooltipText: tooltip.textContent,
      tooltipLeft: tooltipRect.left,
      tooltipRight: tooltipRect.right,
      tooltipTop: tooltipRect.top,
      tooltipBottom: tooltipRect.bottom,
      sidebarRight: sidebarRect.right,
      viewportWidth: innerWidth,
      viewportHeight: innerHeight,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  })()`);
  if (
    result.active !== "/runs"
    || !new Set(["auto", "scroll"]).has(result.sidebarOverflow)
    || !new Set(["auto", "scroll"]).has(result.navOverflow)
    || result.navScrollHeight <= result.navClientHeight
    || result.navScrollTop <= 0
    || !result.runsVisible
    || result.tooltipHidden
    || result.tooltipText !== "Runs"
    || result.tooltipLeft < result.sidebarRight
    || result.tooltipRight > result.viewportWidth
    || result.tooltipTop < 0
    || result.tooltipBottom > result.viewportHeight
    || result.overflow > 1
  ) {
    throw new Error(`short compact navigation contract failed: ${JSON.stringify(result)}`);
  }
  return result;
}

async function inspectSystemContrastAndReducedMotion(client) {
  await setViewport(client, viewports.at(-1));
  await client.call("Emulation.setEmulatedMedia", {
    features: [
      { name: "prefers-contrast", value: "more" },
      { name: "prefers-reduced-motion", value: "reduce" },
    ],
  });
  try {
    await navigate(client, "/", "system contrast and reduced motion");
    await waitFor(
      () => client.eval("document.documentElement.dataset.contrast === 'high'"),
      "system high contrast",
    );
    await client.eval("document.activeElement?.blur()");
    for (let index = 0; index < 3; index += 1) await dispatchKey(client, "Tab");
    await waitFor(
      () => client.eval("document.activeElement === document.querySelector('[data-contrast-select]')"),
      "contrast keyboard focus",
    );
    const result = await client.eval(`(() => {
      const select = document.querySelector('[data-contrast-select]');
      const selectStyle = getComputedStyle(select);
      const drawerStyle = getComputedStyle(document.querySelector('.sidebar'));
      const duration = drawerStyle.transitionDuration.split(',')[0].trim();
      const transitionMilliseconds = duration.endsWith('ms')
        ? Number.parseFloat(duration)
        : Number.parseFloat(duration) * 1000;
      return {
        contrast: document.documentElement.dataset.contrast,
        preference: document.documentElement.dataset.contrastPreference,
        selected: select.value,
        outlineStyle: selectStyle.outlineStyle,
        outlineWidth: Number.parseFloat(selectStyle.outlineWidth),
        transitionMilliseconds,
      };
    })()`);
    if (
      result.contrast !== "high"
      || result.preference !== "system"
      || result.selected !== "system"
      || result.outlineStyle === "none"
      || result.outlineWidth < 2
      || result.transitionMilliseconds > 0.02
    ) {
      throw new Error(`system contrast and reduced motion contract failed: ${JSON.stringify(result)}`);
    }
    return result;
  } finally {
    await client.call("Emulation.setEmulatedMedia", { features: [] });
  }
}

async function inspectTwoHundredPercentReflow(client) {
  // A 720 x 360 CSS viewport represents a 1440 x 720 window at 200% browser zoom.
  await setViewport(client, { width: 720, height: 360, mobile: false });
  await navigate(client, "/", "200 percent reflow");
  await client.eval("document.querySelector('[data-nav-open][aria-controls]').click()");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === 'true'"), "zoom drawer open");
  const result = await client.eval(`(() => {
    const sidebar = document.querySelector('.sidebar');
    const primaryNav = document.querySelector('.primary-nav');
    const runs = [...document.querySelectorAll('[data-nav-link]')]
      .find((candidate) => candidate.getAttribute('href') === '/runs');
    runs.scrollIntoView({ block: 'nearest' });
    runs.focus();
    const runsRect = runs.getBoundingClientRect();
    const visibleTargets = [
      ...document.querySelectorAll('.brand, [data-nav-link], .icon-button, [data-contrast-select]'),
    ].filter((target) => {
      const style = getComputedStyle(target);
      return !target.hidden && style.display !== 'none' && target.getBoundingClientRect().width > 0;
    });
    return {
      cssWidth: innerWidth,
      cssHeight: innerHeight,
      overflow: document.documentElement.scrollWidth - innerWidth,
      workspaceWidth: document.querySelector('.workspace').getBoundingClientRect().width,
      sidebarHidden: document.querySelector('.sidebar').getAttribute('aria-hidden'),
      sidebarOverflow: getComputedStyle(sidebar).overflowY,
      sidebarScrollHeight: sidebar.scrollHeight,
      sidebarClientHeight: sidebar.clientHeight,
      navOverflow: getComputedStyle(primaryNav).overflowY,
      navScrollHeight: primaryNav.scrollHeight,
      navClientHeight: primaryNav.clientHeight,
      runsVisible: runsRect.top >= 0 && runsRect.bottom <= innerHeight,
      smallestTarget: Math.min(...visibleTargets.map((target) => {
        const rect = target.getBoundingClientRect();
        return Math.min(rect.width, rect.height);
      })),
    };
  })()`);
  await dispatchKey(client, "Escape");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === undefined"), "zoom drawer close");
  const focusReturned = await client.eval("document.activeElement === document.querySelector('[data-nav-open][aria-controls]')");
  if (
    result.cssWidth !== 720
    || result.cssHeight !== 360
    || result.overflow > 1
    || Math.abs(result.workspaceWidth - 720) > 1
    || result.sidebarHidden !== "false"
    || !new Set(["auto", "scroll"]).has(result.sidebarOverflow)
    || !new Set(["auto", "scroll"]).has(result.navOverflow)
    || result.navScrollHeight <= result.navClientHeight
    || !result.runsVisible
    || result.smallestTarget < 44
    || !focusReturned
  ) {
    throw new Error(`200 percent reflow contract failed: ${JSON.stringify({ result, focusReturned })}`);
  }
  return { ...result, focusReturned };
}

async function inspectPreHydrationCompactNavigation(client) {
  await setViewport(client, viewports[2]);
  const pausedRequestIds = new Set();
  const removePausedHandler = client.on("Fetch.requestPaused", ({ requestId }) => {
    pausedRequestIds.add(requestId);
  });
  await client.call("Fetch.enable", {
    patterns: [{ urlPattern: `${baseUrl.origin}/_next/static/*.js*`, requestStage: "Request" }],
  });

  try {
    await client.call("Page.navigate", { url: baseUrl.href });
    await waitFor(
      () => client.eval(`document.querySelector('.app-shell') !== null
        && performance.getEntriesByType('resource').some((entry) => new URL(entry.name).pathname === '/shell-runtime.js')`),
      "development shell before hydration",
    );
    await waitFor(() => pausedRequestIds.size > 0, "paused Next framework request");
    await client.eval("document.activeElement?.blur()");
    for (let index = 0; index < 4; index += 1) await dispatchKey(client, "Tab");
    await waitFor(
      () => client.eval("document.activeElement?.getAttribute('href') === '/agents'"),
      "pre-hydration compact keyboard navigation",
    );
    const point = await client.eval(`(() => {
      const rect = document.activeElement.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()`);
    await client.call("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: point.x,
      y: point.y,
    });
    const beforeHydration = await client.eval(`(() => {
      const tooltip = document.querySelector('[data-nav-tooltip]');
      return {
        active: document.activeElement?.getAttribute('href') || '',
        hydrated: document.documentElement.dataset.shellHydrated === 'true',
        tooltipHidden: tooltip.hidden,
        tooltipText: tooltip.textContent,
        tooltipLeft: tooltip.style.left,
        tooltipTop: tooltip.style.top,
      };
    })()`);
    if (
      beforeHydration.active !== "/agents"
      || beforeHydration.hydrated
      || !beforeHydration.tooltipHidden
      || beforeHydration.tooltipText
      || beforeHydration.tooltipLeft
      || beforeHydration.tooltipTop
    ) {
      throw new Error(`pre-hydration compact navigation contract failed: ${JSON.stringify(beforeHydration)}`);
    }

    await Promise.all(
      [...pausedRequestIds].map((requestId) => client.call("Fetch.continueRequest", { requestId })),
    );
    pausedRequestIds.clear();
    await client.call("Fetch.disable");
    await waitFor(
      () => client.eval("document.documentElement.dataset.shellHydrated === 'true'"),
      "development hydration signal",
    );
    return {
      ...beforeHydration,
      hydratedAfterRelease: true,
    };
  } finally {
    await Promise.allSettled(
      [...pausedRequestIds].map((requestId) => client.call("Fetch.continueRequest", { requestId })),
    );
    removePausedHandler();
    await Promise.allSettled([client.call("Fetch.disable")]);
  }
}

async function inspectClientNavigationPersistence(client, consoleErrors) {
  await setViewport(client, viewports.at(-1));
  await navigate(client, "/", "development client navigation");
  await sleep(1000);
  await waitFor(
    () => client.eval("document.querySelector('[data-bridge-status]')?.dataset.state === 'ready'"),
    "initial development bridge health",
  );

  await client.eval(`(() => {
    window.__mentatClientNavigationMarker = 'persistent-document';
    const select = document.querySelector('[data-contrast-select]');
    select.value = 'high';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    document.querySelector('[data-nav-open]').click();
  })()`);
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === 'true'"), "development drawer open");
  await waitFor(
    () => client.eval("Math.abs(document.querySelector('.sidebar').getBoundingClientRect().left) < 1"),
    "development drawer transition",
  );
  const taskPoint = await client.eval(`(() => {
    const rect = document.querySelector('[data-nav-link][href="/tasks"]').getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  await dispatchPointerClick(client, taskPoint);
  await waitFor(
    () => client.eval("location.pathname === '/tasks' && document.querySelector('h1')?.textContent === 'Tasks'"),
    "Next Link client transition",
  );
  await waitFor(
    () => client.eval("document.querySelector('[data-bridge-status]')?.dataset.state === 'ready'"),
    "post-transition bridge health",
  );

  const afterTransition = await client.eval(`(() => ({
    marker: window.__mentatClientNavigationMarker ?? null,
    active: document.querySelector('[aria-current="page"] .nav-copy strong')?.textContent,
    bridge: document.querySelector('[data-bridge-status-text]')?.textContent,
    contrast: document.documentElement.dataset.contrast,
    selected: document.querySelector('[data-contrast-select]')?.value,
    drawerOpen: document.documentElement.dataset.navOpen === 'true',
    sidebarHidden: document.querySelector('.sidebar')?.getAttribute('aria-hidden'),
    workspaceInert: document.querySelector('[data-workspace]')?.inert,
    runtimeScripts: document.querySelectorAll('[data-mentat-shell-runtime]').length,
  }))()`);

  await client.eval("document.querySelector('[data-nav-open]').click()");
  await waitFor(
    () => client.eval("document.documentElement.dataset.navOpen === 'true' && document.activeElement === document.querySelector('[data-nav-close]')"),
    "post-transition drawer enhancement",
  );
  await dispatchKey(client, "Escape");
  await waitFor(
    () => client.eval("document.documentElement.dataset.navOpen === undefined && document.activeElement === document.querySelector('[data-nav-open]')"),
    "post-transition Escape focus return",
  );

  await client.eval("document.querySelector('[data-nav-open]').click()");
  await waitFor(() => client.eval("document.documentElement.dataset.navOpen === 'true'"), "Home Link drawer open");
  await waitFor(
    () => client.eval("Math.abs(document.querySelector('.sidebar').getBoundingClientRect().left) < 1"),
    "Home Link drawer transition",
  );
  const homePoint = await client.eval(`(() => {
    const rect = document.querySelector('.brand[data-nav-link][href="/"]').getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  await dispatchPointerClick(client, homePoint);
  await waitFor(
    () => client.eval("location.pathname === '/' && document.querySelector('h1')?.textContent === 'Home'"),
    "Mentat Home Link client transition",
  );
  await waitFor(
    () => client.eval("document.querySelector('[data-bridge-status]')?.dataset.state === 'ready'"),
    "Home Link bridge health",
  );
  const homeTransition = await client.eval(`(() => ({
    marker: window.__mentatClientNavigationMarker ?? null,
    active: document.querySelector('[aria-current="page"] .nav-copy strong')?.textContent,
    bridge: document.querySelector('[data-bridge-status-text]')?.textContent,
    contrast: document.documentElement.dataset.contrast,
    drawerOpen: document.documentElement.dataset.navOpen === 'true',
    sidebarHidden: document.querySelector('.sidebar')?.getAttribute('aria-hidden'),
    workspaceInert: document.querySelector('[data-workspace]')?.inert,
    runtimeScripts: document.querySelectorAll('[data-mentat-shell-runtime]').length,
  }))()`);
  await client.eval("localStorage.removeItem('mentat-contrast-v1')");

  if (
    afterTransition.marker !== "persistent-document"
    || afterTransition.active !== "Tasks"
    || afterTransition.bridge !== "Python ready"
    || afterTransition.contrast !== "high"
    || afterTransition.selected !== "high"
    || afterTransition.drawerOpen
    || afterTransition.sidebarHidden !== "true"
    || afterTransition.workspaceInert
    || afterTransition.runtimeScripts !== 1
    || homeTransition.marker !== "persistent-document"
    || homeTransition.active !== "Home"
    || homeTransition.bridge !== "Python ready"
    || homeTransition.contrast !== "high"
    || homeTransition.drawerOpen
    || homeTransition.sidebarHidden !== "true"
    || homeTransition.workspaceInert
    || homeTransition.runtimeScripts !== 1
  ) {
    throw new Error(`development Link transition contract failed: ${JSON.stringify({ afterTransition, homeTransition, consoleErrors })}`);
  }
  return { tasks: afterTransition, home: homeTransition };
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
      consoleErrors.push(
        exceptionDetails?.exception?.description
        || exceptionDetails?.text
        || "uncaught runtime exception",
      );
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

    if (clientNavigationMode) {
      const preHydration = await inspectPreHydrationCompactNavigation(client);
      const clientNavigation = await inspectClientNavigationPersistence(client, consoleErrors);
      if (client.eventErrors.length || consoleErrors.length) {
        throw new Error(`Browser console/event errors: ${JSON.stringify({ consoleErrors, eventErrors: client.eventErrors.map(String) })}`);
      }
      console.log(JSON.stringify({
        ok: true,
        baseUrl: baseUrl.origin,
        preHydration,
        clientNavigation,
      }, null, 2));
      client.ws.close();
      return;
    }

    const preEnhancementResult = await inspectPreEnhancementMobileNavigation(client);
    const routeResults = await inspectRoutes(client);
    const viewportResults = [];
    for (const viewport of viewports) {
      viewportResults.push(await inspectViewport(client, viewport));
    }
    const interactionResult = await inspectKeyboardDrawerAndContrast(client);
    const agentsResult = await inspectAgentsWorkspace(client);
    const agentProjectionResult = await inspectAgentProjection(client);
    const agentFailureResult = await inspectAgentFailureStates(client);
    const tasksResult = await inspectTasksWorkspace(client);
    const taskFailureResult = await inspectTaskFailureStates(client);
    const runsResult = await inspectRunsWorkspace(client);
    const runProjectionResult = await inspectRunProjection(client);
    const runMalformedResult = await inspectRunMalformedPayload(client);
    const runRejectedResult = await inspectRunRejectedFetch(client);
    const runFailureResult = await inspectRunFailureStates(client);
    const unavailableResult = await inspectUnavailableBridge(client);
    const compactResult = await inspectCompactPointerAndTooltip(client);
    const compactHeightResult = await inspectCompactShortHeight(client);
    const systemPreferenceResult = await inspectSystemContrastAndReducedMotion(client);
    const reflowResult = await inspectTwoHundredPercentReflow(client);
    if (client.eventErrors.length || consoleErrors.length) {
      throw new Error(`Browser console/event errors: ${JSON.stringify({ consoleErrors, eventErrors: client.eventErrors.map(String) })}`);
    }
    console.log(JSON.stringify({
      ok: true,
      baseUrl: baseUrl.origin,
      preEnhancement: preEnhancementResult,
      routes: routeResults,
      viewports: viewportResults,
      interactions: interactionResult,
      agents: agentsResult,
      agentProjection: agentProjectionResult,
      agentFailures: agentFailureResult,
      tasks: tasksResult,
      taskFailures: taskFailureResult,
      runs: runsResult,
      runProjection: runProjectionResult,
      runMalformed: runMalformedResult,
      runRejected: runRejectedResult,
      runFailures: runFailureResult,
      unavailable: unavailableResult,
      compact: compactResult,
      compactHeight: compactHeightResult,
      systemPreferences: systemPreferenceResult,
      reflow: reflowResult,
    }, null, 2));
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
