#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const baseUrl = process.env.MENTAT_BASE_URL || 'http://127.0.0.1:8888';
const debugPort = Number(process.env.MENTAT_BROWSER_DEBUG_PORT || 9223);
const repoRoot = resolve(new URL('..', import.meta.url).pathname.replace(/^\/(.:\/)/, '$1'));
const runtimeDir = resolve(repoRoot, 'data/runtime/browser-smoke-profile');
const chromeCandidates = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].filter(Boolean);
const chromePath = chromeCandidates.find((candidate) => existsSync(candidate));

if (!chromePath) {
  throw new Error(`No Chrome/Edge executable found. Set CHROME_PATH. Checked: ${chromeCandidates.join(', ')}`);
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

async function waitFor(fn, label, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (err) {
      lastError = err;
    }
    await sleep(150);
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ''}`);
}

function backupFile(relativePath) {
  const path = resolve(repoRoot, relativePath);
  return { path, existed: existsSync(path), content: existsSync(path) ? readFileSync(path, 'utf8') : '' };
}

function restoreFile(backup) {
  if (backup.existed) {
    mkdirSync(dirname(backup.path), { recursive: true });
    writeFileSync(backup.path, backup.content, 'utf8');
  } else if (existsSync(backup.path)) {
    rmSync(backup.path);
  }
}

class CdpClient {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve: ok, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message || JSON.stringify(message.error)));
        else ok(message.result || {});
      }
    };
  }

  call(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolveCall, rejectCall) => this.pending.set(id, { resolve: resolveCall, reject: rejectCall }));
  }

  async eval(expression) {
    const result = await this.call('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || 'Runtime evaluation failed');
    }
    return result.result?.value;
  }
}

async function main() {
  const backups = [backupFile('data/agents.json'), backupFile('data/agent_messages.json')];
  let chrome;
  let client;
  try {
    mkdirSync(runtimeDir, { recursive: true });
    chrome = spawn(chromePath, [
      '--headless=new',
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${runtimeDir}`,
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      baseUrl,
    ], { stdio: 'ignore' });

    const page = await waitFor(async () => {
      const pages = await jsonFetch(`http://127.0.0.1:${debugPort}/json/list`);
      return pages.find((item) => item.type === 'page' && item.webSocketDebuggerUrl);
    }, 'Chrome debug page');

    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolveOpen, rejectOpen) => {
      ws.onopen = resolveOpen;
      ws.onerror = () => rejectOpen(new Error('WebSocket connection to Chrome failed'));
    });
    client = new CdpClient(ws);
    await client.call('Runtime.enable');
    await client.call('Page.enable');
    await client.call('Page.navigate', { url: baseUrl });
    await waitFor(() => client.eval('document.readyState === "complete"'), 'page load');
    await waitFor(() => client.eval('document.querySelector("#view-today.active") !== null'), 'Today View default');

    const todayOk = await client.eval(`(() => { const stop = document.querySelector('#agent-console-stop'); const model = document.querySelector('#agent-console-model-select'); return Boolean(document.querySelector('#overview-cards .metric-card') && document.querySelector('#focus-task-list') && document.querySelector('#agent-console-panel') && document.querySelector('#agent-console-form') && model?.tagName === 'SELECT' && model.options.length > 0 && document.querySelector('#agent-console-apply-model') && stop?.hidden && getComputedStyle(stop).display === 'none'); })()`);
    if (!todayOk) throw new Error('Today render smoke failed');
    await client.eval(`(() => { const prompt = document.querySelector('#agent-console-prompt'); prompt.value = '/'; prompt.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    await waitFor(() => client.eval(`(() => { const menu = document.querySelector('#agent-console-command-menu'); return Boolean(menu && !menu.hidden && menu.textContent.includes('/model')); })()`), 'agent console command completion');
    await client.eval(`(() => { const prompt = document.querySelector('#agent-console-prompt'); prompt.value = ''; prompt.dispatchEvent(new Event('input', { bubbles: true })); })()`);

    await client.eval(`document.querySelector('[data-view="projects"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-projects.active") !== null'), 'Projects view');
    const projectsControls = await client.eval(`Boolean(document.querySelector('#create-task-button') && document.querySelector('#create-project-button') && document.querySelector('#edit-project-button') && document.querySelector('#task-status-filter'))`);
    if (!projectsControls) throw new Error('Projects controls smoke failed');
    await client.eval(`(() => { const select = document.querySelector('#task-status-filter'); select.value = 'open'; select.dispatchEvent(new Event('change', { bubbles: true })); return select.value; })()`);
    await client.eval(`document.querySelector('#create-task-button').click()`);
    await waitFor(() => client.eval('document.querySelector("#task-editor-form") !== null'), 'task editor form');
    await client.eval(`document.querySelector('[data-task-editor-cancel]').click()`);

    await client.eval(`document.querySelector('[data-view="agents"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-agents.active") !== null'), 'Agents view');
    await waitFor(() => client.eval('document.querySelector("#agent-message-form") !== null'), 'agent message compose');
    const agentsWorkspaceVisible = await client.eval(`Boolean(document.querySelector('#conversation-library-panel') && document.querySelector('#agent-message-panel'))`);
    if (!agentsWorkspaceVisible) throw new Error('Agents workspace/message panel smoke failed');

    const heartbeatStatus = await client.eval(`fetch('/api/agents/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent_id: 'browser_smoke_agent', name: 'Browser Smoke Agent', status: 'running', project: 'Mentat', current_task: 'Browser smoke live state' }) }).then((response) => response.status)`);
    if (![200, 201].includes(heartbeatStatus)) throw new Error(`Heartbeat smoke returned HTTP ${heartbeatStatus}`);

    const messageText = `Browser smoke queued message ${Date.now()}`;
    await client.eval(`(() => { const form = document.querySelector('#agent-message-form'); form.querySelector('textarea[name="message"]').value = ${JSON.stringify(messageText)}; form.querySelector('textarea[name="message"]').dispatchEvent(new Event('input', { bubbles: true })); form.requestSubmit(); })()`);
    await waitFor(() => client.eval(`document.body.textContent.includes(${JSON.stringify(messageText)})`), 'queued agent message appears');

    console.log(JSON.stringify({ ok: true, baseUrl, checks: ['today render', 'agent console controls', 'nav', 'task controls', 'task status filter', 'agent message compose'] }, null, 2));
    await client.ws.close?.();
  } finally {
    if (chrome && !chrome.killed) chrome.kill();
    await sleep(300);
    backups.forEach(restoreFile);
  }
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
