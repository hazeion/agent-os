#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { cpus, platform, release, totalmem } from "node:os";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const standaloneEntry = resolve(projectRoot, ".next", "standalone", "server.js");
const sampleCount = Number(process.env.MENTAT_AGENT_CONSOLE_PERF_SAMPLES || 7);
const serverPort = Number(process.env.MENTAT_AGENT_CONSOLE_PERF_PORT || 8892);
const debugPort = Number(process.env.MENTAT_AGENT_CONSOLE_PERF_DEBUG_PORT || 9337);
const externalBaseUrl = process.env.MENTAT_WEB_BASE_URL;
const baseUrl = new URL(externalBaseUrl || `http://127.0.0.1:${serverPort}`);
const runtimeRoot = resolve(
  process.env.MENTAT_AGENT_CONSOLE_PERF_RUNTIME_DIR
    || resolve(projectRoot, "..", "data", "runtime", "agent-console-performance-runtime"),
);
const ownedRuntimeDirectory = resolve(runtimeRoot, `run-${process.pid}`);
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

if (!Number.isSafeInteger(sampleCount) || sampleCount < 5 || sampleCount > 21) {
  throw new Error("MENTAT_AGENT_CONSOLE_PERF_SAMPLES must be between 5 and 21");
}
for (const [name, port] of [["server", serverPort], ["debug", debugPort]]) {
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65535) {
    throw new Error(`${name} port must be between 1024 and 65535`);
  }
}
if (
  baseUrl.protocol !== "http:"
  || baseUrl.hostname !== "127.0.0.1"
  || !baseUrl.port
  || baseUrl.pathname !== "/"
  || baseUrl.search
  || baseUrl.hash
) {
  throw new Error("MENTAT_WEB_BASE_URL must be an explicit 127.0.0.1 HTTP origin");
}
if (basename(runtimeRoot) !== "agent-console-performance-runtime") {
  throw new Error(
    "MENTAT_AGENT_CONSOLE_PERF_RUNTIME_DIR must end in agent-console-performance-runtime",
  );
}
if (!chromePath) {
  throw new Error(`No Chrome/Chromium executable found. Checked: ${chromeCandidates.join(", ")}`);
}
if (!externalBaseUrl && !existsSync(standaloneEntry)) {
  throw new Error("Run npm run build before the Agent Console production performance gate");
}

const thresholds = Object.freeze({
  acceptedDispatchMilliseconds: 1_000,
  loadedTabMilliseconds: 50,
  optimisticPaintMilliseconds: 1000 / 60,
  streamPaintMilliseconds: 250,
});

function sleep(milliseconds) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds));
}

async function waitFor(operation, label, timeoutMilliseconds = 15_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const result = await operation();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await sleep(25);
  }
  throw new Error(
    `Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`,
  );
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise((resolveExit) => child.once("exit", resolveExit));
  child.kill("SIGTERM");
  await Promise.race([exited, sleep(5_000)]);
  if (child.exitCode === null) {
    child.kill("SIGKILL");
    await Promise.race([
      new Promise((resolveExit) => child.once("exit", resolveExit)),
      sleep(1_000),
    ]);
  }
}

function median(values) {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

function rounded(values) {
  return values.map((value) => Number(value.toFixed(3)));
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
      if (message.error) pending.reject(new Error(message.error.message || "CDP call failed"));
      else pending.resolve(message.result || {});
    };
  }

  call(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    this.webSocket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolveCall, rejectCall) => {
      this.pending.set(id, { reject: rejectCall, resolve: resolveCall });
    });
  }

  async evaluate(expression) {
    const result = await this.call("Runtime.evaluate", {
      awaitPromise: true,
      expression,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(
        result.exceptionDetails.exception?.description
        || result.exceptionDetails.text
        || "Runtime evaluation failed",
      );
    }
    return result.result?.value;
  }
}

function installPerformanceFixture() {
  const timestamp = "2026-08-27T12:00:00Z";
  const serviceFields = {
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
  const agent = {
    capabilities: ["run.message", "run.start"],
    id: "agent_perf",
    name: "Performance Agent",
    runtime_type: "codex",
    system_role: "direct",
  };
  const firstConversation = {
    agent_id: agent.id,
    archived_at: null,
    created_at: timestamp,
    id: "conv_perf_a",
    revision: 1,
    state: "active",
    title: "Performance A",
    title_source: "first_prompt",
    updated_at: timestamp,
  };
  const secondConversation = {
    ...firstConversation,
    id: "conv_perf_b",
    title: "Performance B",
  };
  const run = {
    id: "run_perf_a",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const makeMessage = (sequence, targetConversation, text, role = "assistant", runId = null) => ({
    content: { parts: [{ text, type: "text" }], schema_version: 1 },
    conversation_id: targetConversation.id,
    created_at: timestamp,
    id: `msg_perf_${targetConversation.id}_${sequence}`,
    revision: 1,
    role,
    run_id: runId,
    sequence,
    state: "accepted",
    updated_at: timestamp,
  });
  const olderMessages = Array.from({ length: 100 }, (_, index) => makeMessage(
    index + 1,
    firstConversation,
    `Performance transcript ${index + 1}`,
    index % 2 === 0 ? "user" : "assistant",
  ));
  const recentMessages = Array.from({ length: 100 }, (_, index) => makeMessage(
    index + 101,
    firstConversation,
    `Performance transcript ${index + 101}`,
    index % 2 === 0 ? "user" : "assistant",
  ));
  const secondMessage = makeMessage(1, secondConversation, "Cached second transcript");
  const dispatchMessage = makeMessage(
    201,
    firstConversation,
    "Measured dispatch",
    "user",
    run.id,
  );
  dispatchMessage.id = "msg_perf_dispatch";
  const state = {
    accepted: false,
    dispatchMessage: null,
    eventSources: [],
    networkRequests: 0,
    resolveTurn: null,
  };
  window.__mentatPerf = state;

  const response = (payload, status = 200) => new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
  const detail = (targetConversation, currentRun, messages, nextMessageCursor = null) => ({
    ...serviceFields,
    agent,
    conversation: targetConversation,
    current_run: currentRun,
    messages,
    next_message_cursor: nextMessageCursor,
    queued_turns: [],
  });
  const acceptedConversation = {
    ...firstConversation,
    revision: 2,
    updated_at: "2026-08-27T12:00:01Z",
  };
  window.fetch = (input, init = {}) => {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, location.href);
    const method = init.method || (input instanceof Request ? input.method : "GET");
    state.networkRequests += 1;
    if (url.pathname === "/api/bridge/health" && method === "GET") {
      return Promise.resolve(response({ mentat_version: "performance-fixture", status: "ready" }));
    }
    if (url.pathname === "/api/conversations" && method === "GET") {
      return Promise.resolve(response({
        ...serviceFields,
        agents: [agent],
        conversations: [state.accepted ? acceptedConversation : firstConversation, secondConversation],
        count: 2,
        direct_agent_id: agent.id,
        next_cursor: null,
      }));
    }
    if (url.pathname === "/api/agent-activity" && method === "GET") {
      return Promise.resolve(response({
        ...serviceFields,
        activity: [],
        direct_agent_id: agent.id,
      }));
    }
    if (url.pathname === "/api/codex-readiness" && method === "GET") {
      return Promise.resolve(response({
        ...serviceFields,
        setup_command: null,
        state: "ready",
      }));
    }
    if (url.pathname === `/api/conversations/${firstConversation.id}` && method === "GET") {
      if (url.searchParams.get("before") === "101") {
        return Promise.resolve(response(detail(firstConversation, null, olderMessages)));
      }
      return Promise.resolve(response(detail(
        state.accepted ? acceptedConversation : firstConversation,
        state.accepted ? run : null,
        state.accepted ? [...recentMessages.slice(1), state.dispatchMessage] : recentMessages,
        "101",
      )));
    }
    if (url.pathname === `/api/conversations/${secondConversation.id}` && method === "GET") {
      return Promise.resolve(response(detail(secondConversation, null, [secondMessage])));
    }
    if (
      url.pathname === `/api/conversations/${firstConversation.id}/turns`
      && method === "POST"
    ) {
      const request = JSON.parse(String(init.body || "{}"));
      const exactMessage = {
        ...dispatchMessage,
        content: {
          parts: [{ text: request.text, type: "text" }],
          schema_version: 1,
        },
      };
      const submission = {
        ...serviceFields,
        conversation: acceptedConversation,
        disposition: "accepted",
        duplicate: false,
        message: exactMessage,
        run: { ...run, status: "starting" },
        turn: {
          attempt_count: 1,
          blocked_reason: null,
          conversation_id: firstConversation.id,
          created_at: timestamp,
          id: "turn_perf_dispatch",
          latest_run_id: run.id,
          queue_ordinal: 1,
          revision: 3,
          state: "consumed",
          updated_at: timestamp,
          user_message_id: exactMessage.id,
        },
      };
      return new Promise((resolveTurn) => {
        state.resolveTurn = () => {
          state.accepted = true;
          state.dispatchMessage = exactMessage;
          state.resolveTurn = null;
          resolveTurn(response(submission, 202));
        };
      });
    }
    return Promise.resolve(response({ schema_version: 1, status: "not_found" }, 404));
  };

  class PerformanceEventSource {
    constructor(url) {
      this.closed = false;
      this.listeners = new Map();
      this.onerror = null;
      this.url = String(url);
      state.eventSources.push(this);
    }

    addEventListener(type, listener) {
      const listeners = this.listeners.get(type) || new Set();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    }

    removeEventListener(type, listener) {
      this.listeners.get(type)?.delete(listener);
    }

    close() {
      this.closed = true;
    }

    emit(type, data) {
      if (this.closed) return;
      const event = new MessageEvent(type, { data });
      for (const listener of this.listeners.get(type) || []) {
        if (typeof listener === "function") listener(event);
        else listener.handleEvent(event);
      }
    }
  }
  window.EventSource = PerformanceEventSource;
}

function textInputExpression(text) {
  return `(() => {
    const prompt = document.getElementById("console-prompt");
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(prompt, ${JSON.stringify(text)});
    prompt.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      data: ${JSON.stringify(text)},
      inputType: "insertText",
    }));
  })()`;
}

function mutationMeasurementExpression({ action, predicate, startExpression = "performance.now()" }) {
  return `new Promise((resolve, reject) => {
    const startedAt = ${startExpression};
    const finish = () => {
      if (!(${predicate})) return false;
      observer.disconnect();
      clearTimeout(timeout);
      resolve(performance.now() - startedAt);
      return true;
    };
    const observer = new MutationObserver(finish);
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
    const timeout = setTimeout(() => {
      observer.disconnect();
      reject(new Error("performance fixture mutation timed out: " + JSON.stringify({
        progress: document.querySelector('.selected-run-progress')?.textContent || null,
        sources: window.__mentatPerf?.eventSources?.map((source) => ({
          closed: source.closed,
          listeners: [...source.listeners.keys()],
          url: source.url,
        })) || [],
        status: document.querySelector('.console-notice')?.textContent || null,
      })));
    }, 2000);
    ${action};
    queueMicrotask(finish);
  })`;
}

async function navigate(client) {
  await client.call("Page.navigate", { url: baseUrl.href });
  await waitFor(
    () => client.evaluate(
      "document.readyState === 'complete' && document.getElementById('console-prompt') !== null",
    ),
    "hydrated Agent Console",
  );
  await waitFor(
    () => client.evaluate("document.querySelectorAll('.message-row').length === 100"),
    "100-message production fixture",
  );
}

async function measureSample(client, index) {
  await navigate(client);
  await client.evaluate("document.querySelector('.load-older')?.click()");
  await waitFor(
    () => client.evaluate("document.querySelectorAll('.message-row').length === 200"),
    "200-message bounded transcript",
  );
  await client.evaluate(
    "[...document.querySelectorAll('button')].find((button) => button.textContent === 'Check readiness')?.click()",
  );
  await waitFor(
    () => client.evaluate("document.querySelector('.console-notice')?.textContent === 'Codex is signed in and ready.'"),
    "Codex-ready fixture state",
  );

  const networkBeforeTyping = await client.evaluate("window.__mentatPerf.networkRequests");
  await client.evaluate(textInputExpression(`Measured dispatch ${index + 1}`));
  await client.evaluate("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  const networkAfterTyping = await client.evaluate("window.__mentatPerf.networkRequests");
  await waitFor(
    () => client.evaluate("document.querySelector('.composer-send')?.disabled === false"),
    "enabled production composer",
  );

  const optimistic = await client.evaluate(mutationMeasurementExpression({
    action: `window.__mentatPerf.dispatchStartedAt = startedAt;
      document.querySelector(".composer-send").click()`,
    predicate: "document.querySelector('[aria-label=\"Sending message\"]') !== null",
  }));
  const accepted = await client.evaluate(mutationMeasurementExpression({
    action: `if (typeof window.__mentatPerf.resolveTurn !== "function") {
        reject(new Error("held Turn response was unavailable"));
      } else {
        window.__mentatPerf.resolveTurn();
      }`,
    predicate: "document.querySelector('.console-notice')?.textContent === 'Turn accepted. The Run is now visible in this Conversation.'",
    startExpression: "window.__mentatPerf.dispatchStartedAt",
  }));
  await waitFor(
    () => client.evaluate("window.__mentatPerf.eventSources.some((source) => !source.closed)"),
    "selected Run production stream",
  );

  const streamLabel = `Measured live update ${index + 1}`;
  const stream = await client.evaluate(mutationMeasurementExpression({
    action: `window.__mentatPerf.eventSources.findLast((source) => !source.closed).emit(
        "timeline",
        JSON.stringify({ event: { run_id: "run_perf_a", summary: ${JSON.stringify(streamLabel)} } }),
      )`,
    predicate: `document.querySelector('.selected-run-progress')?.textContent.includes(${JSON.stringify(streamLabel)})`,
  }));
  const retainedRows = await client.evaluate("document.querySelectorAll('.message-row').length");

  await client.evaluate("document.getElementById('conversation-tab-conv_perf_b').click()");
  await waitFor(
    () => client.evaluate("document.querySelector('.conversation-transcript')?.textContent.includes('Cached second transcript')"),
    "second Conversation warm cache",
  );
  await client.evaluate("document.getElementById('conversation-tab-conv_perf_a').click()");
  await waitFor(
    () => client.evaluate("document.querySelector('.conversation-transcript')?.textContent.includes('Measured dispatch')"),
    "first Conversation warm cache",
  );
  const loadedTab = await client.evaluate(mutationMeasurementExpression({
    action: "document.getElementById('conversation-tab-conv_perf_b').click()",
    predicate: "document.querySelector('.conversation-transcript')?.textContent.includes('Cached second transcript')",
  }));

  return {
    accepted,
    loadedTab,
    optimistic,
    retainedRows,
    stream,
    typingNetworkDelta: networkAfterTyping - networkBeforeTyping,
  };
}

async function main() {
  let server;
  let chrome;
  let client;
  try {
    mkdirSync(profileDirectory, { recursive: true });
    if (!externalBaseUrl) {
      server = spawn(process.execPath, [standaloneEntry], {
        cwd: resolve(projectRoot, ".next", "standalone"),
        env: {
          ...process.env,
          HOSTNAME: "127.0.0.1",
          NODE_ENV: "production",
          PORT: String(serverPort),
        },
        stdio: "ignore",
      });
    }
    await waitFor(async () => {
      if (server?.exitCode !== null && server?.exitCode !== undefined) {
        throw new Error(`standalone server exited with ${server.exitCode}`);
      }
      const response = await fetch(baseUrl);
      return response.ok;
    }, "standalone production server", 30_000);

    chrome = spawn(chromePath, [
      "--headless=new",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profileDirectory}`,
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--no-default-browser-check",
      "--no-first-run",
      "about:blank",
    ], { stdio: "ignore" });
    const page = await waitFor(async () => {
      if (chrome.exitCode !== null) throw new Error(`Chrome exited with ${chrome.exitCode}`);
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
      if (!response.ok) return null;
      const pages = await response.json();
      return pages.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
    }, "Chrome debug page", 30_000);
    const webSocket = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolveOpen, rejectOpen) => {
      webSocket.onopen = resolveOpen;
      webSocket.onerror = () => rejectOpen(new Error("Chrome WebSocket failed"));
    });
    client = new CdpClient(webSocket);
    await client.call("Runtime.enable");
    await client.call("Page.enable");
    await client.call("Emulation.setDeviceMetricsOverride", {
      deviceScaleFactor: 1,
      height: 900,
      mobile: false,
      width: 1440,
    });
    await client.call("Page.addScriptToEvaluateOnNewDocument", {
      source: `(${installPerformanceFixture.toString()})();`,
    });

    const samples = [];
    for (let index = 0; index < sampleCount; index += 1) {
      samples.push(await measureSample(client, index));
    }
    const metrics = {
      acceptedDispatchMilliseconds: samples.map((sample) => sample.accepted),
      loadedTabMilliseconds: samples.map((sample) => sample.loadedTab),
      optimisticPaintMilliseconds: samples.map((sample) => sample.optimistic),
      streamPaintMilliseconds: samples.map((sample) => sample.stream),
    };
    const failures = [];
    for (const [metric, values] of Object.entries(metrics)) {
      const threshold = thresholds[metric];
      if (values.some((value) => value >= threshold)) {
        failures.push(`${metric} exceeded ${threshold}ms: ${rounded(values).join(", ")}`);
      }
    }
    if (samples.some((sample) => sample.typingNetworkDelta !== 0)) {
      failures.push("typing initiated network work");
    }
    if (samples.some((sample) => sample.retainedRows !== 200)) {
      failures.push("the production transcript did not retain exactly 200 bounded rows");
    }

    const chromeVersion = spawnSync(chromePath, ["--version"], { encoding: "utf8" });
    const report = {
      environment: {
        browser: chromeVersion.stdout.trim() || basename(chromePath),
        cpu: cpus()[0]?.model || "unknown",
        memory_bytes: totalmem(),
        mode: "Next.js standalone production + headless Chrome",
        node: process.version,
        platform: `${platform()} ${release()}`,
        viewport: "1440x900@1x",
      },
      fixtures: {
        conversations: 2,
        initial_messages: 100,
        paginated_retained_messages: 200,
        samples: sampleCount,
      },
      medians_ms: Object.fromEntries(
        Object.entries(metrics).map(([name, values]) => [name, Number(median(values).toFixed(3))]),
      ),
      ok: failures.length === 0,
      samples: Object.fromEntries(
        Object.entries(metrics).map(([name, values]) => [name, rounded(values)]),
      ),
      thresholds_ms: thresholds,
      typing_network_deltas: samples.map((sample) => sample.typingNetworkDelta),
    };
    console.log(JSON.stringify(report, null, 2));
    if (failures.length) throw new Error(failures.join("; "));
    client.webSocket.close();
  } finally {
    await stopChild(chrome);
    await stopChild(server);
    rmSync(ownedRuntimeDirectory, {
      force: true,
      maxRetries: 5,
      recursive: true,
      retryDelay: 200,
    });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
