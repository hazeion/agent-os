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
const settingsScreenshotPath = resolve(ownedRuntimeDir, 'settings-diagnostics-smoke.png');
const homeScreenshotPath = process.env.MENTAT_HOME_SCREENSHOT_PATH
  ? resolve(process.env.MENTAT_HOME_SCREENSHOT_PATH)
  : '';
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

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise((resolveExit) => child.once('exit', resolveExit));
  child.kill();
  await Promise.race([exited, sleep(5000)]);
  if (child.exitCode === null) {
    child.kill('SIGKILL');
    await Promise.race([
      new Promise((resolveExit) => child.once('exit', resolveExit)),
      sleep(1000),
    ]);
  }
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

async function setViewport(client, width, height) {
  await client.call('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await sleep(100);
}

async function reloadPage(client) {
  await client.call('Page.reload', { ignoreCache: true });
  await waitFor(() => client.eval('document.readyState === "complete"'), 'page reload');
}

async function pointerClick(client, x, y) {
  const common = { x, y, button: 'left', clickCount: 1 };
  await client.call('Input.dispatchMouseEvent', { type: 'mousePressed', ...common });
  await client.call('Input.dispatchMouseEvent', { type: 'mouseReleased', ...common });
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
      '--disable-dev-shm-usage',
      '--no-first-run',
      '--no-default-browser-check',
      baseUrl,
    ], { stdio: 'ignore' });

    const page = await waitFor(async () => {
      const pages = await jsonFetch(`http://127.0.0.1:${debugPort}/json/list`);
      return pages.find((item) => item.type === 'page' && item.webSocketDebuggerUrl);
    }, 'Chrome debug page', 30000);

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

    const shellDefaults = await client.eval(`(() => {
      const ids = [...document.querySelectorAll('[id]')].map((item) => item.id);
      const rgb = (value) => (value.match(/[\\d.]+/g) || []).slice(0, 3).map(Number);
      const luminance = (value) => {
        const channels = rgb(value).map((item) => {
          const normalized = item / 255;
          return normalized <= 0.04045
            ? normalized / 12.92
            : ((normalized + 0.055) / 1.055) ** 2.4;
        });
        return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2]);
      };
      const ratio = (first, second) => {
        const a = luminance(first);
        const b = luminance(second);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      };
      const searchStyle = getComputedStyle(document.querySelector('.search-shell'));
      return {
        theme: document.documentElement.dataset.theme,
        shell: document.documentElement.dataset.uiShell,
        contrast: document.documentElement.dataset.contrast,
        duplicateIds: ids.filter((id, index) => ids.indexOf(id) !== index),
        title: document.title,
        brand: document.querySelector('#brand-name')?.textContent || '',
        greeting: document.querySelector('.hero-title')?.textContent || '',
        controlContrast: ratio(searchStyle.borderTopColor, searchStyle.backgroundColor),
      };
    })()`);
    if (
      shellDefaults.theme !== 'emerald'
      || shellDefaults.shell !== 'emerald'
      || !['standard', 'high'].includes(shellDefaults.contrast)
      || shellDefaults.duplicateIds.length
      || shellDefaults.title !== 'Mentat'
      || shellDefaults.brand !== 'Mentat'
      || !shellDefaults.greeting
      || shellDefaults.controlContrast < 3
    ) {
      throw new Error(`Emerald shell default contract failed: ${JSON.stringify(shellDefaults)}`);
    }

    await client.eval(`(() => {
      localStorage.setItem('mentat-theme', 'compact-dark');
      localStorage.setItem('mentat-ui-shell-v1', 'classic');
      localStorage.setItem('mentat-contrast-v1', 'high');
    })()`);
    await reloadPage(client);
    const savedShell = await client.eval(`(() => ({
      theme: document.documentElement.dataset.theme,
      shell: document.documentElement.dataset.uiShell,
      contrast: document.documentElement.dataset.contrast,
      bodyColor: getComputedStyle(document.body).color,
      searchBorder: getComputedStyle(document.querySelector('.search-shell')).borderTopColor,
    }))()`);
    if (
      savedShell.theme !== 'compact-dark'
      || savedShell.shell !== 'classic'
      || savedShell.contrast !== 'high'
      || savedShell.bodyColor !== 'rgb(255, 253, 245)'
      || savedShell.searchBorder !== 'rgb(128, 148, 150)'
    ) {
      throw new Error(`Saved shell preference contract failed: ${JSON.stringify(savedShell)}`);
    }
    await setViewport(client, 1200, 900);
    const classicHomeLayout = await client.eval(`(() => {
      const selectors = [
        '#today-active-work-panel',
        '#home-live-agents-panel',
        '#today-calendar-panel',
        '.home-context-stack',
        '#agent-console-panel',
      ];
      const rects = selectors.map((selector) => document.querySelector(selector)?.getBoundingClientRect());
      const overlap = (left, right) => (
        Math.min(left.right, right.right) - Math.max(left.left, right.left) > 2
        && Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top) > 2
      );
      return {
        visible: rects.every((rect) => rect && rect.width > 120 && rect.height > 40),
        focusAgentsAligned: Math.abs(rects[0].top - rects[1].top) <= 2,
        scheduleContextAligned: Math.abs(rects[2].top - rects[3].top) <= 2,
        consoleLast: rects[4].top >= Math.max(rects[2].bottom, rects[3].bottom) - 2,
        focusConsoleOverlap: overlap(rects[0], rects[4]),
        overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth,
      };
    })()`);
    if (
      !classicHomeLayout.visible
      || !classicHomeLayout.focusAgentsAligned
      || !classicHomeLayout.scheduleContextAligned
      || !classicHomeLayout.consoleLast
      || classicHomeLayout.focusConsoleOverlap
      || classicHomeLayout.overflow > 1
    ) {
      throw new Error(`Classic Home rollback layout failed: ${JSON.stringify(classicHomeLayout)}`);
    }

    await client.eval(`(() => {
      localStorage.setItem('mentat-theme', 'emerald');
      localStorage.setItem('mentat-ui-shell-v1', 'emerald');
      localStorage.removeItem('mentat-contrast-v1');
    })()`);
    await setViewport(client, 1440, 1000);
    await reloadPage(client);
    await waitFor(() => client.eval('document.querySelector("#view-today.active") !== null'), 'Emerald Today restore');

    await waitFor(() => client.eval(`(() => {
      const stop = document.querySelector('#agent-console-stop');
      const model = document.querySelector('#agent-console-model-select');
      const mounts = [
        '#today-active-work-panel',
        '#home-live-agents-panel',
        '#today-calendar-panel',
        '#home-projects-panel',
        '#home-crons-panel',
        '#agent-console-panel',
      ];
      return Boolean(
        mounts.every((selector) => document.querySelector(selector))
        && !document.querySelector('#overview-cards')
        && ![...document.querySelectorAll('.metric-card')].some((card) => card.getClientRects().length)
        && document.querySelector('#focus-task-list')
        && document.querySelector('#home-live-agent-list .home-live-agent-row, #home-live-agent-list .empty')
        && document.querySelector('#home-project-stats')
        && document.querySelector('#home-cron-list')
        && document.querySelector('#agent-console-form')
        && model?.tagName === 'SELECT'
        && model.options.length > 0
        && document.querySelector('#agent-console-apply-model')
        && stop?.hidden
        && getComputedStyle(stop).display === 'none'
      );
    })()`), 'reference-aligned Home render', 30000);
    await waitFor(
      () => client.eval(`state.agentConsoleCommandManifest?.commands?.length === 3`),
      'Mentat Agent Console command manifest bootstrap',
      30000,
    );
    const homeDesktopLayout = await client.eval(`(() => {
      const rect = (selector) => document.querySelector(selector)?.getBoundingClientRect();
      const focus = rect('#today-active-work-panel');
      const agents = rect('#home-live-agents-panel');
      const schedule = rect('#today-calendar-panel');
      const context = rect('.home-context-stack');
      const consoleDock = rect('#agent-console-panel');
      const grid = rect('#home-operations-dashboard');
      return {
        noMetrics: !document.querySelector('#overview-cards') && ![...document.querySelectorAll('.metric-card')].some((card) => card.getClientRects().length),
        firstRowAligned: Math.abs(focus.top - agents.top) <= 2,
        secondRowAligned: Math.abs(schedule.top - context.top) <= 2,
        columnRatio: focus.width / agents.width,
        consoleSpansGrid: Math.abs(consoleDock.left - grid.left) <= 2 && Math.abs(consoleDock.right - grid.right) <= 2,
        rowOrder: focus.top < schedule.top && agents.top < context.top && schedule.bottom <= consoleDock.top + 2,
        overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth,
        overflowSources: [...document.querySelectorAll('body *')]
          .map((element) => ({ element, rect: element.getBoundingClientRect() }))
          .filter(({ rect }) => rect.width > 0 && rect.right > innerWidth + 1)
          .slice(0, 8)
          .map(({ element, rect }) => ({
            tag: element.tagName,
            id: element.id,
            className: typeof element.className === 'string' ? element.className : '',
            right: Math.round(rect.right),
            width: Math.round(rect.width),
          })),
      };
    })()`);
    if (
      !homeDesktopLayout.noMetrics
      || !homeDesktopLayout.firstRowAligned
      || !homeDesktopLayout.secondRowAligned
      || homeDesktopLayout.columnRatio < 1.08
      || homeDesktopLayout.columnRatio > 1.28
      || !homeDesktopLayout.consoleSpansGrid
      || !homeDesktopLayout.rowOrder
      || homeDesktopLayout.overflow > 1
    ) {
      throw new Error(`Reference-aligned Home desktop layout failed: ${JSON.stringify(homeDesktopLayout)}`);
    }
    for (const viewport of [
      { width: 1680, height: 1050 },
      { width: 1440, height: 900 },
      { width: 1200, height: 900 },
      { width: 1024, height: 768 },
      { width: 900, height: 900 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await setViewport(client, viewport.width, viewport.height);
      const disclosureLayout = await client.eval(`(() => {
        const panel = document.querySelector('#today-active-work-panel');
        const panelRect = panel.getBoundingClientRect();
        const inspect = (detailsSelector, contentSelector, controlSelectors = []) => {
          const details = document.querySelector(detailsSelector);
          details.open = true;
          const content = document.querySelector(contentSelector);
          const contentRect = content.getBoundingClientRect();
          const controls = controlSelectors.map((selector) => document.querySelector(selector)?.getBoundingClientRect());
          const result = {
            contentVisible: contentRect.width > 0 && contentRect.height > 0,
            contentInside: contentRect.left >= panelRect.left - 1 && contentRect.right <= panelRect.right + 1,
            controlsInside: controls.every((rect) => (
              rect
              && rect.width > 0
              && rect.height > 0
              && rect.left >= panelRect.left - 1
              && rect.right <= panelRect.right + 1
            )),
          };
          details.open = false;
          return result;
        };
        return {
          quick: inspect(
            '.home-utility-disclosure:not(#today-completed-panel)',
            '.home-utility-popover',
            ['#quick-capture-title', '#quick-capture-project', '#quick-capture-form button'],
          ),
          completed: inspect('#today-completed-panel', '#completed-list'),
        };
      })()`);
      if (
        !disclosureLayout.quick.contentVisible
        || !disclosureLayout.quick.contentInside
        || !disclosureLayout.quick.controlsInside
        || !disclosureLayout.completed.contentVisible
        || !disclosureLayout.completed.contentInside
      ) {
        throw new Error(`Home disclosure clipping at ${viewport.width}px: ${JSON.stringify(disclosureLayout)}`);
      }
    }
    await setViewport(client, 1440, 1000);
    if (homeScreenshotPath) {
      await setViewport(client, 1672, 941);
      const homeScreenshot = await client.call('Page.captureScreenshot', { format: 'png', fromSurface: true });
      mkdirSync(dirname(homeScreenshotPath), { recursive: true });
      writeFileSync(homeScreenshotPath, homeScreenshot.data, 'base64');
      await setViewport(client, 1440, 1000);
    }
    const consoleDisclosure = await client.eval(`(() => {
      const details = document.querySelector('#agent-console-details');
      const summary = details?.querySelector('summary');
      summary?.click();
      const opened = Boolean(details?.open && document.querySelector('#agent-console-chat')?.getClientRects().length);
      summary?.click();
      return {
        opened,
        closed: !details?.open,
        composerVisible: Boolean(document.querySelector('#agent-console-prompt')?.getClientRects().length),
        stateVisible: Boolean(document.querySelector('#agent-console-state')?.getClientRects().length),
      };
    })()`);
    if (!consoleDisclosure.opened || !consoleDisclosure.closed || !consoleDisclosure.composerVisible || !consoleDisclosure.stateVisible) {
      throw new Error(`Compact Agent Console disclosure failed: ${JSON.stringify(consoleDisclosure)}`);
    }
    const homeRuntimeContracts = await client.eval(`(async () => {
      const originalTasks = state.tasks;
      const originalCalendar = state.homeCalendar;
      const originalAgents = state.agents;
      state.tasks = [];
      state.agents = [];
      const today = new Date();
      const tomorrow = new Date(today);
      tomorrow.setDate(tomorrow.getDate() + 1);
      tomorrow.setHours(9, 0, 0, 0);
      renderHomeSchedule({
        items: [{
          id: 'future-only',
          title: 'Tomorrow only',
          start: tomorrow.toISOString(),
          end: new Date(tomorrow.getTime() + 3600000).toISOString(),
        }],
        source: 'local',
        auth: 'not_connected',
        error: 'Calendar connection unavailable',
        summary: { stale: true },
      });
      const expectedToday = new Intl.DateTimeFormat(undefined, {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      }).format(today);
      const futureOnly = {
        labelsToday: document.querySelector('#home-schedule-date')?.textContent.startsWith(expectedToday),
        empty: document.querySelector('#calendar-list .home-schedule-empty')?.textContent.includes('No calendar events'),
        degraded: document.querySelector('#home-schedule-date')?.classList.contains('attention'),
        explainsFallback: document.querySelector('#home-schedule-date')?.textContent.includes('local fallback'),
      };

      const at = (hour, minute = 0) => {
        const value = new Date(today);
        value.setHours(hour, minute, 0, 0);
        return value.toISOString();
      };
      renderHomeSchedule({
        items: [
          { id: 'lane-a', title: 'Lane A', start: at(9), end: at(11) },
          { id: 'lane-b', title: 'Lane B', start: at(9, 15), end: at(10, 30) },
          { id: 'lane-c', title: 'Lane C', start: at(9, 30), end: at(12) },
          { id: 'late', title: 'Late event', start: at(23, 45), end: at(24) },
        ],
        source: 'google',
        auth: 'connected',
        summary: { stale: false },
      });
      const trackRect = document.querySelector('.home-schedule-track').getBoundingClientRect();
      const events = [...document.querySelectorAll('.home-schedule-event')].map((item) => ({
        title: item.textContent,
        rect: item.getBoundingClientRect(),
      }));
      const collides = (left, right) => (
        Math.min(left.right, right.right) - Math.max(left.left, right.left) > 1
        && Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top) > 1
      );
      const firstThree = events.slice(0, 3).map((entry) => entry.rect);
      const late = events.find((entry) => entry.title.includes('Late event'))?.rect;
      const schedule = {
        allRendered: events.length === 4,
        concurrentSeparated: firstThree.every((rect, index) => (
          firstThree.slice(index + 1).every((other) => !collides(rect, other))
        )),
        lateInside: Boolean(late && late.left >= trackRect.left - 1 && late.right <= trackRect.right + 1),
        lateReadable: Boolean(late && late.width >= 24),
        trackContainsLanes: trackRect.height >= 190,
      };

      const remoteBinding = 'b'.repeat(32);
      const runs = [
        {
          id: 'local-waiting',
          agent_id: 'default',
          agent_name: 'default',
          session_id: 'local-session',
          status: 'waiting_for_approval',
          transport_mode: 'local',
          connection_binding_id: 'local-default',
          prompt: 'Approve local action',
          created_at: new Date().toISOString(),
          action_required: { kind: 'approval', request_id: 'approval-1', preview: { title: 'Approval needed' } },
        },
        {
          id: 'remote-complete',
          agent_id: 'default',
          agent_name: 'default',
          session_id: 'remote-session',
          status: 'completed',
          transport_mode: 'remote',
          connection_binding_id: remoteBinding,
          prompt: 'Remote done',
          created_at: new Date(Date.now() - 60000).toISOString(),
        },
      ];
      const agent = { id: 'default', name: 'default', available: true, model: 'configured default' };
      const baseConsole = {
        agents: [agent],
        selected_agent_id: 'default',
        model_catalog: { profile_id: 'default', models: [], current_model: 'configured default' },
        provider_inventory: { profile_id: 'default', providers: [], capabilities: { 'providers.switch': false } },
        runs,
      };
      renderAgentConsole({
        ...baseConsole,
        transport: { mode: 'local', binding_id: 'local-default', console_available: true },
      });
      const localWaiting = {
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        stopVisible: !document.querySelector('#agent-console-stop')?.hidden,
        state: document.querySelector('#agent-console-state')?.textContent,
        homeStatus: document.querySelector('.home-agent-status')?.textContent,
        homeSessions: document.querySelector('.home-live-agent-runtime small')?.textContent,
      };
      const clarificationRuns = [
        {
          ...runs[0],
          id: 'local-clarification',
          session_id: 'local-clarification-session',
          status: 'waiting_for_clarification',
          prompt: 'Clarify local action',
          action_required: {
            kind: 'clarification',
            request_id: 'clarification-1',
            prompt: { question: 'Which option should Hermes use?', type: 'choice', choices: [{ id: 'a', label: 'Option A' }] },
          },
        },
        runs[1],
      ];
      renderAgentConsole({
        ...baseConsole,
        runs: clarificationRuns,
        transport: { mode: 'local', binding_id: 'local-default', console_available: true },
      });
      const localClarification = {
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        stopVisible: !document.querySelector('#agent-console-stop')?.hidden,
        state: document.querySelector('#agent-console-state')?.textContent,
        questionVisible: document.querySelector('#agent-console-chat')?.textContent.includes('Which option should Hermes use?'),
      };
      renderAgentConsole({
        ...baseConsole,
        transport: { mode: 'remote', binding_id: remoteBinding, console_available: true },
      });
      const remoteReady = {
        promptEnabled: !document.querySelector('#agent-console-prompt')?.disabled,
        stopHidden: document.querySelector('#agent-console-stop')?.hidden,
        homeStatus: document.querySelector('.home-agent-status')?.textContent,
        homeSessions: document.querySelector('.home-live-agent-runtime small')?.textContent,
      };
      state.agentConsoleAgents = [
        { id: 'offline-a', name: 'offline-a', available: false, model: 'configured default' },
        { id: 'offline-b', name: 'offline-b', available: false, model: 'configured default' },
        { id: 'offline-c', name: 'offline-c', available: false, model: 'configured default' },
        { id: 'working-agent', name: 'working-agent', available: true, model: 'configured default' },
      ];
      state.agentConsoleRuns = [{
        id: 'remote-working',
        agent_id: 'working-agent',
        session_id: 'working-session',
        status: 'running',
        transport_mode: 'remote',
        connection_binding_id: remoteBinding,
        created_at: new Date().toISOString(),
      }];
      renderHomeLiveAgents();
      const visibleAgentRows = [...document.querySelectorAll('.home-live-agent-row')];
      const prioritizedAgents = {
        names: visibleAgentRows.map((row) => row.querySelector('.home-live-agent-name')?.textContent),
        statuses: visibleAgentRows.map((row) => row.querySelector('.home-agent-status')?.textContent),
        workingAccessibleName: visibleAgentRows
          .find((row) => row.textContent.includes('working-agent'))
          ?.getAttribute('aria-label'),
      };

      state.tasks = originalTasks;
      state.homeCalendar = originalCalendar;
      state.agents = originalAgents;
      await refresh();
      return { futureOnly, schedule, localWaiting, localClarification, remoteReady, prioritizedAgents };
    })()`);
    if (
      !homeRuntimeContracts.futureOnly.labelsToday
      || !homeRuntimeContracts.futureOnly.empty
      || !homeRuntimeContracts.futureOnly.degraded
      || !homeRuntimeContracts.futureOnly.explainsFallback
      || !homeRuntimeContracts.schedule.allRendered
      || !homeRuntimeContracts.schedule.concurrentSeparated
      || !homeRuntimeContracts.schedule.lateInside
      || !homeRuntimeContracts.schedule.lateReadable
      || !homeRuntimeContracts.schedule.trackContainsLanes
      || !homeRuntimeContracts.localWaiting.promptDisabled
      || !homeRuntimeContracts.localWaiting.stopVisible
      || !homeRuntimeContracts.localWaiting.state?.includes('waiting for approval')
      || !homeRuntimeContracts.localWaiting.homeStatus?.includes('Needs attention')
      || !homeRuntimeContracts.localWaiting.homeSessions?.includes('1 session')
      || !homeRuntimeContracts.localClarification.promptDisabled
      || !homeRuntimeContracts.localClarification.stopVisible
      || !homeRuntimeContracts.localClarification.state?.includes('waiting for clarification')
      || !homeRuntimeContracts.localClarification.questionVisible
      || !homeRuntimeContracts.remoteReady.promptEnabled
      || !homeRuntimeContracts.remoteReady.stopHidden
      || !homeRuntimeContracts.remoteReady.homeStatus?.includes('Ready')
      || !homeRuntimeContracts.remoteReady.homeSessions?.includes('1 session')
      || !homeRuntimeContracts.prioritizedAgents.names?.includes('working-agent')
      || homeRuntimeContracts.prioritizedAgents.statuses?.filter((status) => status?.includes('Unavailable')).length !== 2
      || !homeRuntimeContracts.prioritizedAgents.workingAccessibleName?.includes('Runtime:')
      || !homeRuntimeContracts.prioritizedAgents.workingAccessibleName?.includes('Last activity:')
      || !homeRuntimeContracts.prioritizedAgents.workingAccessibleName?.includes('Health:')
    ) {
      throw new Error(`Home runtime contracts failed: ${JSON.stringify(homeRuntimeContracts)}`);
    }
    for (const viewport of [
      { width: 1680, height: 1050 },
      { width: 1440, height: 900 },
      { width: 1200, height: 900 },
      { width: 1024, height: 768 },
      { width: 900, height: 900 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await setViewport(client, viewport.width, viewport.height);
      const lateBoundary = await client.eval(`(() => {
        const originalTasks = state.tasks;
        const originalCalendar = state.homeCalendar;
        state.tasks = [];
        const earlierStart = new Date();
        earlierStart.setHours(22, 30, 0, 0);
        const earlierEnd = new Date(earlierStart);
        earlierEnd.setHours(23, 0, 0, 0);
        const lateStart = new Date();
        lateStart.setHours(23, 45, 0, 0);
        const lateEnd = new Date(lateStart);
        lateEnd.setDate(lateEnd.getDate() + 1);
        lateEnd.setHours(0, 0, 0, 0);
        renderHomeSchedule({
          items: [
            { id: 'late-earlier', title: 'Late earlier', start: earlierStart.toISOString(), end: earlierEnd.toISOString() },
            { id: 'late-boundary', title: 'Late boundary', start: lateStart.toISOString(), end: lateEnd.toISOString() },
          ],
          source: 'google',
          auth: 'connected',
          summary: { stale: false },
        });
        const track = document.querySelector('.home-schedule-track')?.getBoundingClientRect();
        const events = [...document.querySelectorAll('.home-schedule-event')];
        const earlierEvent = events
          .find((item) => item.textContent.includes('Late earlier'))
          ?.getBoundingClientRect();
        const lateEvent = events
          .find((item) => item.textContent.includes('Late boundary'))
          ?.getBoundingClientRect();
        const rectanglesOverlap = Boolean(
          earlierEvent
          && lateEvent
          && earlierEvent.left < lateEvent.right - 1
          && earlierEvent.right > lateEvent.left + 1
          && earlierEvent.top < lateEvent.bottom - 1
          && earlierEvent.bottom > lateEvent.top + 1
        );
        const minimumTargetWidth = innerWidth <= 640 ? 44 : 24;
        const result = {
          visible: Boolean(
            earlierEvent
            && lateEvent
            && earlierEvent.width >= minimumTargetWidth
            && earlierEvent.height >= 44
            && lateEvent.width >= minimumTargetWidth
            && lateEvent.height >= 44
          ),
          inside: Boolean(
            earlierEvent
            && lateEvent
            && track
            && earlierEvent.left >= track.left - 1
            && earlierEvent.right <= track.right + 1
            && lateEvent.left >= track.left - 1
            && lateEvent.right <= track.right + 1
          ),
          separate: !rectanglesOverlap,
        };
        state.tasks = originalTasks;
        state.homeCalendar = originalCalendar;
        renderHomeSchedule(originalCalendar);
        return result;
      })()`);
      if (!lateBoundary.visible || !lateBoundary.inside || !lateBoundary.separate) {
        throw new Error(`Late schedule target failed at ${viewport.width}px: ${JSON.stringify(lateBoundary)}`);
      }
    }
    await setViewport(client, 390, 844);
    const homeMobileLayout = await client.eval(`(() => {
      const selectors = [
        '#today-active-work-panel',
        '#home-live-agents-panel',
        '#today-calendar-panel',
        '.home-context-stack',
        '#agent-console-panel',
      ];
      const rects = selectors.map((selector) => document.querySelector(selector).getBoundingClientRect());
      const targetSizes = [...document.querySelectorAll('#view-today button, #view-today summary')]
        .filter((item) => item.getClientRects().length)
        .map((item) => item.getBoundingClientRect());
      return {
        ordered: rects.every((rect, index) => index === 0 || rect.top >= rects[index - 1].bottom - 1),
        overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth,
        undersizedTargets: targetSizes.filter((rect) => rect.width < 44 || rect.height < 44).length,
      };
    })()`);
    if (!homeMobileLayout.ordered || homeMobileLayout.overflow > 1 || homeMobileLayout.undersizedTargets) {
      throw new Error(`Reference-aligned Home mobile layout failed: ${JSON.stringify(homeMobileLayout)}`);
    }
    await setViewport(client, 1440, 1000);
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

    await client.eval(`document.querySelector('[data-view="settings"]').click()`);
    await waitFor(() => client.eval('document.querySelector("#view-settings.active") !== null'), 'Settings view');
    await waitFor(() => client.eval(`document.querySelector('#mentat-version')?.textContent.startsWith('v0.1.0')`), 'Mentat version display');
    const supportActionsVisible = await client.eval(`Boolean(document.querySelector('#download-diagnostics') && document.querySelector('a[href*="issues/new?template=bug_report.yml"]') && document.querySelector('a[href$="#quick-start"]'))`);
    if (!supportActionsVisible) throw new Error('Settings support actions smoke failed');
    const diagnosticsDownloadSafe = await client.eval(`fetch('/api/diagnostics/bundle', { method: 'POST', headers: { Accept: 'application/zip' } }).then(async (response) => { const bytes = new Uint8Array(await response.arrayBuffer()); return response.status === 200 && response.headers.get('content-type') === 'application/zip' && response.headers.get('content-disposition') === 'attachment; filename=mentat-diagnostics.zip' && bytes[0] === 80 && bytes[1] === 75; })`);
    if (!diagnosticsDownloadSafe) throw new Error('Redacted diagnostics download smoke failed');
    const settingsScreenshot = await client.call('Page.captureScreenshot', { format: 'png', fromSurface: true });
    writeFileSync(settingsScreenshotPath, settingsScreenshot.data, 'base64');

    const shellViews = ['today', 'agents', 'calendar', 'projects', 'notes', 'settings'];
    const shellViewports = [
      { width: 1680, height: 1050, mode: 'expanded' },
      { width: 1440, height: 900, mode: 'expanded' },
      { width: 1200, height: 900, mode: 'expanded' },
      { width: 1024, height: 768, mode: 'compact' },
      { width: 900, height: 900, mode: 'drawer' },
      { width: 768, height: 1024, mode: 'drawer' },
      { width: 390, height: 844, mode: 'drawer' },
    ];
    for (const view of shellViews) {
      await client.eval(`document.querySelector('[data-view="${view}"]').click()`);
      await waitFor(
        () => client.eval(`document.querySelector('[data-view-panel="${view}"].active') !== null`),
        `${view} responsive view`,
      );
      for (const viewport of shellViewports) {
        await setViewport(client, viewport.width, viewport.height);
        const layout = await client.eval(`(() => {
          const root = document.documentElement;
          const sidebar = document.querySelector('#mentat-sidebar');
          const toggle = document.querySelector('#navigation-toggle');
          const hero = document.querySelector('.hero-title');
          const main = document.querySelector('#main-content');
          const active = document.querySelector('.nav-item[aria-current="page"]');
          const navRects = [...document.querySelectorAll('.nav-item')]
            .map((item) => item.getBoundingClientRect());
          const sidebarStyle = getComputedStyle(sidebar);
          const toggleStyle = getComputedStyle(toggle);
          const heroRect = hero.getBoundingClientRect();
          const heroStyle = getComputedStyle(hero);
          const headerRect = document.querySelector('.command-header').getBoundingClientRect();
          const mainRect = main.getBoundingClientRect();
          const navText = document.querySelector('.nav-item > span:last-child');
          const close = document.querySelector('#mobile-nav-close');
          return {
            overflow: Math.max(root.scrollWidth, document.body.scrollWidth) - innerWidth,
            sidebarWidth: sidebar.getBoundingClientRect().width,
            sidebarTransform: sidebarStyle.transform,
            toggleDisplay: toggleStyle.display,
            heroVisible: heroRect.width > 0 && heroRect.height > 0,
            heroClipped: heroStyle.clipPath !== 'none' || heroStyle.clip !== 'auto',
            headerVisible: headerRect.width > 0 && headerRect.height > 0,
            mainLeft: mainRect.left,
            mainRight: mainRect.right,
            activeView: active?.dataset.view || '',
            navTextDisplay: getComputedStyle(navText).display,
            closeDisplay: getComputedStyle(close).display,
            navStacked: navRects.every((rect, index) => (
              Math.abs(rect.left - navRects[0].left) <= 1
              && (index === 0 || rect.top >= navRects[index - 1].bottom - 1)
            )),
          };
        })()`);
        const commonValid = (
          layout.overflow <= 1
          && layout.heroClipped
          && layout.headerVisible
          && layout.activeView === view
          && layout.mainLeft >= -1
          && layout.mainRight <= viewport.width + 1
        );
        const modeValid = (
          (viewport.mode === 'expanded' && Math.abs(layout.sidebarWidth - 216) <= 2 && layout.toggleDisplay === 'none')
          || (
            viewport.mode === 'compact'
            && Math.abs(layout.sidebarWidth - 76) <= 2
            && layout.toggleDisplay === 'none'
            && layout.navStacked
          )
          || (
            viewport.mode === 'drawer'
            && layout.sidebarWidth > 0
            && layout.toggleDisplay !== 'none'
            && layout.sidebarTransform !== 'none'
            && layout.navTextDisplay !== 'none'
            && layout.closeDisplay !== 'none'
          )
        );
        if (!commonValid || !modeValid) {
          throw new Error(`Responsive shell failed for ${view} at ${viewport.width}px: ${JSON.stringify(layout)}`);
        }
      }
    }

    await setViewport(client, 1024, 768);
    const compactStatus = await client.eval(`(() => {
      const footer = document.querySelector('.sidebar-footer');
      const health = document.querySelector('#health-label');
      const refresh = document.querySelector('#refresh-rate').parentElement;
      const updated = document.querySelector('#last-updated').parentElement;
      footer.focus();
      return {
        footerWidth: footer.getBoundingClientRect().width,
        healthWidth: health.getBoundingClientRect().width,
        refreshWidth: refresh.getBoundingClientRect().width,
        updatedWidth: updated.getBoundingClientRect().width,
        healthText: health.textContent.trim(),
        refreshText: refresh.textContent.trim(),
        updatedText: updated.textContent.trim(),
      };
    })()`);
    if (
      compactStatus.footerWidth < 240
      || compactStatus.healthWidth <= 1
      || compactStatus.refreshWidth <= 1
      || compactStatus.updatedWidth <= 1
      || !compactStatus.healthText
      || !compactStatus.refreshText
      || !compactStatus.updatedText
    ) {
      throw new Error(`Compact status disclosure failed: ${JSON.stringify(compactStatus)}`);
    }

    for (const viewport of [
      { width: 900, height: 900 },
      { width: 390, height: 844 },
    ]) {
      await setViewport(client, viewport.width, viewport.height);
      await client.eval(`window.scrollTo(0, Math.min(650, document.documentElement.scrollHeight - innerHeight))`);
      await sleep(100);
      const toggleTarget = await client.eval(`(() => {
        const toggle = document.querySelector('#navigation-toggle');
        const rect = toggle.getBoundingClientRect();
        const x = rect.left + (rect.width / 2);
        const y = rect.top + (rect.height / 2);
        const hit = document.elementFromPoint(x, y);
        toggle.focus();
        return {
          x,
          y,
          top: rect.top,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
          hitToggle: Boolean(hit?.closest('#navigation-toggle')),
        };
      })()`);
      if (
        !toggleTarget.hitToggle
        || toggleTarget.width < 44
        || toggleTarget.height < 44
        || toggleTarget.top < 0
        || toggleTarget.bottom > viewport.height
      ) {
        throw new Error(`Mobile navigation hit target failed at ${viewport.width}px: ${JSON.stringify(toggleTarget)}`);
      }
      await pointerClick(client, toggleTarget.x, toggleTarget.y);
      await waitFor(
        () => client.eval(`document.documentElement.dataset.navOpen === 'true'`),
        `mobile drawer open at ${viewport.width}px`,
      );
      await waitFor(
        () => client.eval(`document.querySelector('#mentat-sidebar')?.contains(document.activeElement)`),
        `mobile drawer focus entry at ${viewport.width}px`,
      );
      const openDrawer = await client.eval(`(() => ({
        expanded: document.querySelector('#navigation-toggle')?.getAttribute('aria-expanded'),
        sidebarHidden: document.querySelector('#mentat-sidebar')?.getAttribute('aria-hidden'),
        sidebarRole: document.querySelector('#mentat-sidebar')?.getAttribute('role'),
        ariaModal: document.querySelector('#mentat-sidebar')?.getAttribute('aria-modal'),
        mainInert: document.querySelector('#main-content')?.inert,
        closeVisible: getComputedStyle(document.querySelector('#mobile-nav-close')).display !== 'none',
        homeLabelVisible: getComputedStyle(document.querySelector('[data-view="today"] > span:last-child')).display !== 'none',
        focusInside: document.querySelector('#mentat-sidebar')?.contains(document.activeElement),
      }))()`);
      if (
        openDrawer.expanded !== 'true'
        || openDrawer.sidebarHidden !== null
        || openDrawer.sidebarRole !== 'dialog'
        || openDrawer.ariaModal !== 'true'
        || !openDrawer.mainInert
        || !openDrawer.closeVisible
        || !openDrawer.homeLabelVisible
        || !openDrawer.focusInside
      ) {
        throw new Error(`Mobile drawer accessibility state failed at ${viewport.width}px: ${JSON.stringify(openDrawer)}`);
      }
      const focusWrap = await client.eval(`(() => {
        const sidebar = document.querySelector('#mentat-sidebar');
        const controls = [...sidebar.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
          + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )].filter((element) => {
          const style = getComputedStyle(element);
          return !element.hidden
            && element.getAttribute('aria-hidden') !== 'true'
            && style.display !== 'none'
            && style.visibility !== 'hidden'
            && element.getClientRects().length > 0;
        });
        const first = controls[0];
        const last = controls[controls.length - 1];
        last.focus();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
        const forwardWrapped = document.activeElement === first;
        first.focus();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }));
        return {
          controlCount: controls.length,
          firstId: first?.id || '',
          forwardWrapped,
          reverseWrapped: document.activeElement === last,
          openerIncluded: controls.includes(document.querySelector('#navigation-toggle')),
        };
      })()`);
      if (
        focusWrap.controlCount < 7
        || focusWrap.firstId !== 'mobile-nav-close'
        || !focusWrap.forwardWrapped
        || !focusWrap.reverseWrapped
        || focusWrap.openerIncluded
      ) {
        throw new Error(`Mobile drawer focus trap failed at ${viewport.width}px: ${JSON.stringify(focusWrap)}`);
      }
      await client.eval(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`);
      await waitFor(
        () => client.eval(`document.documentElement.dataset.navOpen !== 'true'`),
        `mobile drawer Escape close at ${viewport.width}px`,
      );
      await waitFor(
        () => client.eval(`document.activeElement?.id === 'navigation-toggle'`),
        `mobile drawer focus return at ${viewport.width}px`,
      );
    }

    await client.eval(`(() => {
      window.scrollTo(0, 500);
      document.querySelector('.skip-link').focus();
    })()`);
    await client.call('Input.dispatchKeyEvent', {
      type: 'keyDown',
      key: 'Enter',
      code: 'Enter',
      windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13,
    });
    await client.call('Input.dispatchKeyEvent', {
      type: 'keyUp',
      key: 'Enter',
      code: 'Enter',
      windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13,
    });
    await waitFor(
      () => client.eval(`location.hash === '#main-content' && document.activeElement?.id === 'main-content'`),
      'skip-link activation',
    );
    await setViewport(client, 1440, 1000);

    console.log(JSON.stringify({ ok: true, baseUrl, checks: ['Emerald shell defaults', 'saved shell reload', 'theme and contrast reload', 'Classic Home rollback geometry', 'reference-aligned Home desktop layout', 'reference-aligned Home mobile layout', 'Home disclosures across seven widths', 'Today-only schedule and degradation state', 'concurrent schedule lanes', '23:45 schedule target across seven widths', 'connection-bound Live Agents', 'unavailable-agent ranking', 'approval and clarification Console states', 'Home operational accessible names', 'no Home metric cards', 'compact Agent Console disclosure', 'six-view responsive matrix', 'mobile drawer keyboard and focus', 'skip link', 'today render', 'agent console controls', 'structured event render', 'Mentat command manifest', 'nav', 'task controls', 'task status filter', 'Operator Week render', 'calendar week navigation', 'calendar preview safety', 'calendar event inspector', 'managed agents inventory', 'agent deletion safeguards', 'Agent Creator dialog', 'Context Packs workspace', 'Settings support actions', 'Mentat version display', 'redacted diagnostics download'] }, null, 2));
    await client.ws.close?.();
  } finally {
    await stopChild(chrome);
    backups.forEach(restoreFile);
    rmSync(ownedRuntimeDir, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 200,
    });
  }
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
