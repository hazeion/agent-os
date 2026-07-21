#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';

const baseUrl = process.env.MENTAT_BASE_URL || 'http://127.0.0.1:8888';
const debugPort = Number(process.env.MENTAT_BROWSER_DEBUG_PORT || 9223);
const repoRoot = resolve(new URL('..', import.meta.url).pathname.replace(/^\/(.:\/)/, '$1'));
const browserRuntimeRoot = resolve(
  process.env.MENTAT_BROWSER_RUNTIME_DIR || resolve(repoRoot, 'data/runtime/browser-smoke-runtime'),
);
if (basename(browserRuntimeRoot) !== 'browser-smoke-runtime') {
  throw new Error('MENTAT_BROWSER_RUNTIME_DIR must end in browser-smoke-runtime');
}
const ownedRuntimeDir = resolve(browserRuntimeRoot, `run-${process.pid}`);
const runtimeDir = resolve(ownedRuntimeDir, 'profile');
const calendarScreenshotPath = resolve(ownedRuntimeDir, 'calendar-week-smoke.png');
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
  const backups = [backupFile('data/agents.json')];
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
    await client.call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    await client.call('Page.navigate', { url: baseUrl });
    await waitFor(() => client.eval('document.readyState === "complete"'), 'page load');
    await waitFor(() => client.eval('document.querySelector("#view-today.active") !== null'), 'Today View default');

    await waitFor(() => client.eval(`(() => { const stop = document.querySelector('#agent-console-stop'); const model = document.querySelector('#agent-console-model-select'); return Boolean(document.querySelector('#overview-cards .metric-card') && document.querySelector('#focus-task-list') && document.querySelector('#agent-console-panel') && document.querySelector('#agent-console-form') && model?.tagName === 'SELECT' && model.options.length > 0 && document.querySelector('#agent-console-apply-model') && stop?.hidden && getComputedStyle(stop).display === 'none'); })()`), 'Today render', 30000);
    const structuredEventRendered = await client.eval(`(() => { renderAgentConsole({ agents: [{ id: 'event-smoke', name: 'Event Smoke', available: true, model: 'test/model' }], model_catalog: { profile_id: 'event-smoke', models: ['test/model'], current_model: 'test/model' }, runs: [{ id: 'run_event_smoke', agent_id: 'event-smoke', agent_name: 'Event Smoke', status: 'completed', prompt: 'Check events', response: 'Done', created_at: new Date().toISOString(), event_cursor: 1, events: [{ schema_version: 1, run_id: 'run_event_smoke', sequence: 1, cursor: 1, type: 'complete', kind: 'complete', timestamp: new Date().toISOString(), data: {}, display_text: 'Structured event rendered' }] }] }); return document.querySelector('#agent-console-chat')?.textContent.includes('Structured event rendered'); })()`);
    if (!structuredEventRendered) throw new Error('Structured Agent Console event render smoke failed');
    await client.eval(`(() => { const prompt = document.querySelector('#agent-console-prompt'); prompt.value = '/'; prompt.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    await waitFor(() => client.eval(`(() => { const menu = document.querySelector('#agent-console-command-menu'); return Boolean(menu && !menu.hidden && menu.textContent.includes('/model')); })()`), 'agent console command completion');
    const commandManifestOk = await client.eval(`fetch('/api/agent-console/commands').then((response) => response.json()).then((payload) => payload.schema_version === 1 && payload.source === 'mentat' && payload.capabilities?.['commands.hermes_cli_passthrough'] === false && payload.commands?.map((item) => item.command).join(',') === '/model,/new,/help')`);
    if (!commandManifestOk) throw new Error('Mentat command manifest contract smoke failed');
    await client.eval(`(() => { const prompt = document.querySelector('#agent-console-prompt'); prompt.value = '/help'; prompt.form.requestSubmit(); })()`);
    await waitFor(() => client.eval(`document.querySelector('#agent-console-form-status')?.textContent.includes('/model — Refresh current provider models')`), 'manifest-driven agent console help');
    await client.eval(`(() => { const prompt = document.querySelector('#agent-console-prompt'); prompt.value = ''; prompt.dispatchEvent(new Event('input', { bubbles: true })); })()`);

    await client.eval(`document.querySelector('[data-view="projects"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-projects.active") !== null'), 'Projects view');
    const projectsControls = await client.eval(`Boolean(document.querySelector('#create-task-button') && document.querySelector('#create-project-button') && document.querySelector('#edit-project-button') && document.querySelector('#task-status-filter'))`);
    if (!projectsControls) throw new Error('Projects controls smoke failed');
    await client.eval(`(() => { const select = document.querySelector('#task-status-filter'); select.value = 'open'; select.dispatchEvent(new Event('change', { bubbles: true })); return select.value; })()`);
    await client.eval(`document.querySelector('#create-task-button').click()`);
    await waitFor(() => client.eval('document.querySelector("#task-editor-form") !== null'), 'task editor form');
    await client.eval(`document.querySelector('[data-task-editor-cancel]').click()`);

    await client.eval(`document.querySelector('[data-view="calendar"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-calendar.active") !== null'), 'Calendar view');
    await waitFor(() => client.eval(`document.querySelectorAll('#calendar-week-days .calendar-week-day-header').length === 7 && document.querySelector('#calendar-week')?.getAttribute('aria-busy') === 'false'`), 'Operator Week render');
    const currentWeekLabel = await client.eval(`document.querySelector('#calendar-week-range')?.textContent || ''`);
    await client.eval(`document.querySelector('[data-calendar-week-nav="next"]').click()`);
    await waitFor(() => client.eval(`document.querySelector('#calendar-week')?.getAttribute('aria-busy') === 'false' && (document.querySelector('#calendar-week-range')?.textContent || '') !== ${JSON.stringify(currentWeekLabel)}`), 'next calendar week');
    await client.eval(`document.querySelector('[data-calendar-week-nav="today"]').click()`);
    await waitFor(() => client.eval(`document.querySelector('#calendar-week')?.getAttribute('aria-busy') === 'false' && (document.querySelector('#calendar-week-range')?.textContent || '') === ${JSON.stringify(currentWeekLabel)}`), 'current calendar week');
    await client.eval(`renderCalendar({ source: 'local', auth: 'not_connected', read_only: true, items: [], summary: {}, range_days: 7 }, { view: 'calendar' })`);
    await waitFor(() => client.eval(`document.querySelectorAll('[data-calendar-source="preview"]').length === 3`), 'disconnected calendar preview');
    await client.eval(`document.querySelector('[data-calendar-source="preview"]')?.click()`);
    await waitFor(() => client.eval(`Boolean(document.querySelector('#calendar-event-inspector:not([hidden])'))`), 'calendar event inspector');
    const previewMutationSafe = await client.eval(`!document.querySelector('#calendar-event-inspector [data-calendar-create-task], #calendar-event-inspector [data-calendar-link-task]')`);
    if (!previewMutationSafe) throw new Error('Preview calendar event exposed task mutation actions');
    const calendarScreenshot = await client.call('Page.captureScreenshot', { format: 'png', fromSurface: true });
    mkdirSync(dirname(calendarScreenshotPath), { recursive: true });
    writeFileSync(calendarScreenshotPath, calendarScreenshot.data, 'base64');

    await client.eval(`document.querySelector('[data-view="agents"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-agents.active") !== null'), 'Agents view');
    await waitFor(() => client.eval(`Boolean(document.querySelector('#managed-agent-list .managed-agent-card, #managed-agent-list .empty'))`), 'managed agents inventory');
    const agentsWorkspaceVisible = await client.eval(`Boolean(document.querySelector('#managed-agents-panel') && document.querySelector('#conversation-library-panel') && !document.querySelector('#agent-message-panel'))`);
    if (!agentsWorkspaceVisible) throw new Error('Agents workspace smoke failed');
    const agentDeletionContract = await client.eval(`(() => { const dialog = document.querySelector('#agent-delete-dialog'); const defaultCard = document.querySelector('[data-hermes-profile-id="default"]'); return Boolean(dialog && (!defaultCard || !defaultCard.querySelector('[data-delete-hermes-profile]'))); })()`);
    if (!agentDeletionContract) throw new Error('Managed Agent deletion safety contract smoke failed');

    const routedProfileId = await client.eval(`(() => { const button = document.querySelector('[data-use-hermes-profile]'); const profileId = button?.dataset.useHermesProfile || ''; button?.click(); return profileId; })()`);
    if (routedProfileId) {
      await waitFor(() => client.eval('document.querySelector("#view-today.active") !== null'), 'profile-aware Console route');
      await waitFor(() => client.eval(`document.querySelector('#agent-console-agent')?.value === ${JSON.stringify(routedProfileId)}`), 'selected Console profile');
      await client.eval(`document.querySelector('[data-view="agents"]').click()`);
      await waitFor(() => client.eval('document.querySelector("#view-agents.active") !== null'), 'Agents view after Console routing');
    }

    await client.eval(`document.querySelector('#create-agent-button').click()`);
    await waitFor(() => client.eval(`Boolean(document.querySelector('#agent-creator-dialog')?.open)`), 'agent creator dialog');
    await client.eval(`document.querySelector('[data-agent-creator-close]').click()`);

    const heartbeatStatus = await client.eval(`fetch('/api/agents/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent_id: 'browser_smoke_agent', name: 'Browser Smoke Agent', status: 'running', project: 'Mentat', current_task: 'Browser smoke live state' }) }).then((response) => response.status)`);
    if (![200, 201].includes(heartbeatStatus)) throw new Error(`Heartbeat smoke returned HTTP ${heartbeatStatus}`);

    await client.eval(`document.querySelector('[data-view="notes"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-notes.active") !== null'), 'Notes view');
    const contextPacksVisible = await client.eval(`Boolean(document.querySelector('#context-pack-list') && document.querySelector('#create-context-pack') && document.querySelector('#context-pack-dialog'))`);
    if (!contextPacksVisible) throw new Error('Context Packs workspace smoke failed');

    console.log(JSON.stringify({ ok: true, baseUrl, checks: ['today render', 'agent console controls', 'structured event render', 'Mentat command manifest', 'nav', 'task controls', 'task status filter', 'Operator Week render', 'calendar week navigation', 'calendar preview safety', 'calendar event inspector', 'managed agents inventory', 'agent deletion safeguards', 'Agent Creator dialog', 'Context Packs workspace'] }, null, 2));
    await client.ws.close?.();
  } finally {
    if (chrome && !chrome.killed) chrome.kill();
    await sleep(300);
    backups.forEach(restoreFile);
    rmSync(ownedRuntimeDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
