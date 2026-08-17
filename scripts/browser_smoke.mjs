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

async function verifyAppearanceContinuity(client) {
  await client.eval(`document.querySelector('[data-view="settings"]').click()`);
  await waitFor(() => client.eval('document.querySelector("#view-settings.active") !== null'), 'Settings view');
  await setViewport(client, 1440, 1000);
  const appearance = await client.eval(`(() => {
    const cards = [...document.querySelectorAll('#theme-preview-grid .theme-swatch')];
    const rectangles = cards.map((card) => card.getBoundingClientRect());
    const accentProbe = document.createElement('span');
    accentProbe.style.color = 'var(--accent)';
    document.body.append(accentProbe);
    const accent = getComputedStyle(accentProbe).color;
    accentProbe.remove();
    const focusStyles = ['theme-select', 'contrast-select'].map((id) => {
      const control = document.getElementById(id);
      control.focus();
      const style = getComputedStyle(control);
      return {
        id,
        border: style.borderTopColor,
        outline: style.outlineStyle,
        shadow: style.boxShadow,
      };
    });
    return {
      cardCount: cards.length,
      cardSizes: [...new Set(rectangles.map((rect) => rect.width + 'x' + rect.height))],
      accent,
      focusStyles,
    };
  })()`);
  if (
    appearance.cardCount !== 16
    || appearance.cardSizes.length !== 1
    || appearance.cardSizes[0] !== '160x88'
    || appearance.focusStyles.some((style) => (
      style.border !== appearance.accent
      || style.outline !== 'none'
      || style.shadow !== 'none'
    ))
  ) {
    throw new Error(`Appearance continuity smoke failed: ${JSON.stringify(appearance)}`);
  }
  await setViewport(client, 390, 844);
  const phoneThemeGridHidden = await client.eval(`getComputedStyle(document.querySelector('#theme-preview-grid')).display === 'none'`);
  if (!phoneThemeGridHidden) throw new Error('Phone theme preview grid remained visible');
  await setViewport(client, 1440, 1000);
  return appearance;
}

async function verifyCompactNavigationTooltip(client) {
  await setViewport(client, 1024, 768);
  const compactItem = await client.eval(`Boolean(document.querySelector('.nav-item[data-view="agents"]'))`);
  if (!compactItem) throw new Error('Compact navigation item is missing');
  const idleHidden = await client.eval(`(() => { const tooltip = document.querySelector('#compact-nav-tooltip'); return tooltip.hidden && tooltip.getAttribute('aria-hidden') === 'true'; })()`);
  if (!idleHidden) throw new Error('Compact navigation tooltip is visible while idle');
  await client.eval(`document.querySelector('.nav-item[data-view="today"]').focus()`);
  await client.call('Input.dispatchKeyEvent', {
    type: 'keyDown',
    key: 'Tab',
    code: 'Tab',
    windowsVirtualKeyCode: 9,
    nativeVirtualKeyCode: 9,
  });
  await client.call('Input.dispatchKeyEvent', {
    type: 'keyUp',
    key: 'Tab',
    code: 'Tab',
    windowsVirtualKeyCode: 9,
    nativeVirtualKeyCode: 9,
  });
  await waitFor(
    () => client.eval(`document.activeElement?.dataset.view === 'agents'`),
    'keyboard focus on compact navigation item',
  );
  await sleep(180);
  const tooltip = await client.eval(`(() => {
    const item = document.querySelector('.nav-item[data-view="agents"]');
    const label = document.querySelector('#compact-nav-tooltip');
    const itemRect = item.getBoundingClientRect();
    const labelRect = label.getBoundingClientRect();
    const style = getComputedStyle(label);
    label.style.pointerEvents = 'auto';
    const hit = document.elementFromPoint(
      labelRect.left + (labelRect.width / 2),
      labelRect.top + (labelRect.height / 2),
    );
    label.style.removeProperty('pointer-events');
    return {
      text: label.textContent.trim(),
      hidden: label.hidden,
      ariaHidden: label.getAttribute('aria-hidden'),
      opacity: style.opacity,
      visibility: style.visibility,
      pointerEvents: style.pointerEvents,
      painted: hit === label,
      leftOfTooltip: labelRect.left,
      rightOfIcon: itemRect.right,
      tooltipRight: labelRect.right,
      viewportWidth: innerWidth,
    };
  })()`);
  if (
    tooltip.text !== 'Agents & Sessions'
    || tooltip.hidden
    || tooltip.ariaHidden !== 'true'
    || tooltip.opacity !== '1'
    || tooltip.visibility !== 'visible'
    || tooltip.pointerEvents !== 'none'
    || !tooltip.painted
    || tooltip.leftOfTooltip < tooltip.rightOfIcon
    || tooltip.tooltipRight > tooltip.viewportWidth
  ) {
    throw new Error(`Compact navigation tooltip failed: ${JSON.stringify(tooltip)}`);
  }

  const calendarTarget = await client.eval(`(() => { const rect = document.querySelector('.nav-item[data-view="calendar"]').getBoundingClientRect(); return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }; })()`);
  await client.call('Input.dispatchMouseEvent', { type: 'mouseMoved', ...calendarTarget });
  await waitFor(
    () => client.eval(`document.querySelector('#compact-nav-tooltip').textContent.trim() === 'Calendar'`),
    'pointer tooltip over a different keyboard-focused item',
  );
  await client.call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 320, y: 320 });
  await waitFor(
    () => client.eval(`(() => { const tooltip = document.querySelector('#compact-nav-tooltip'); return !tooltip.hidden && tooltip.textContent.trim() === 'Agents & Sessions'; })()`),
    'keyboard tooltip restoration after pointer leave',
  );

  const hiddenDuringScrollRefresh = await client.eval(`(() => {
    const navigation = document.querySelector('.nav-groups');
    navigation.dispatchEvent(new Event('scroll'));
    return document.querySelector('#compact-nav-tooltip').hidden;
  })()`);
  if (!hiddenDuringScrollRefresh) throw new Error('Compact navigation tooltip did not refresh on scroll');
  await waitFor(
    () => client.eval(`(() => { const tooltip = document.querySelector('#compact-nav-tooltip'); return !tooltip.hidden && tooltip.textContent.trim() === 'Agents & Sessions'; })()`),
    'keyboard tooltip restoration after scroll',
  );

  await client.call('Input.dispatchKeyEvent', {
    type: 'keyDown',
    key: 'Escape',
    code: 'Escape',
    windowsVirtualKeyCode: 27,
    nativeVirtualKeyCode: 27,
  });
  await client.call('Input.dispatchKeyEvent', {
    type: 'keyUp',
    key: 'Escape',
    code: 'Escape',
    windowsVirtualKeyCode: 27,
    nativeVirtualKeyCode: 27,
  });
  await waitFor(
    () => client.eval(`document.querySelector('#compact-nav-tooltip').hidden`),
    'compact navigation tooltip Escape dismissal',
  );

  const pointerTarget = await client.eval(`(() => { const rect = document.querySelector('.nav-item[data-view="agents"]').getBoundingClientRect(); return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }; })()`);
  await client.call('Input.dispatchMouseEvent', { type: 'mouseMoved', ...pointerTarget });
  await waitFor(
    () => client.eval(`!document.querySelector('#compact-nav-tooltip').hidden`),
    'pointer-opened compact navigation tooltip',
  );
  await client.call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 320, y: 320 });
  await waitFor(
    () => client.eval(`document.querySelector('#compact-nav-tooltip').hidden`),
    'pointer tooltip dismissal after leave',
  );
  await client.call('Input.dispatchMouseEvent', { type: 'mouseMoved', ...pointerTarget });
  await waitFor(
    () => client.eval(`!document.querySelector('#compact-nav-tooltip').hidden`),
    'pointer tooltip reopened before activation',
  );
  await pointerClick(client, pointerTarget.x, pointerTarget.y);
  await waitFor(
    () => client.eval(`document.querySelector('#compact-nav-tooltip').hidden`),
    'pointer tooltip dismissal after activation',
  );

  await setViewport(client, 390, 844);
  await client.eval(`document.querySelector('#navigation-toggle').click()`);
  await waitFor(
    () => client.eval(`document.documentElement.dataset.navOpen === 'true'`),
    'phone navigation drawer open',
  );
  const phoneLabel = await client.eval(`(() => {
    const label = document.querySelector('.nav-item[data-view="agents"] > span:last-child');
    const rect = label.getBoundingClientRect();
    return {
      text: label.textContent.trim(),
      display: getComputedStyle(label).display,
      width: rect.width,
    };
  })()`);
  if (
    phoneLabel.text !== 'Agents & Sessions'
    || phoneLabel.display === 'none'
    || phoneLabel.width <= 1
  ) {
    throw new Error(`Phone navigation label failed: ${JSON.stringify(phoneLabel)}`);
  }
  await client.eval(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`);
  await waitFor(
    () => client.eval(`document.documentElement.dataset.navOpen !== 'true'`),
    'phone navigation drawer close',
  );
  await setViewport(client, 1024, 768);
  return { tooltip, phoneLabel };
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
    const savedAppearance = await client.eval(`(() => ({
      theme: document.documentElement.dataset.theme,
      shell: document.documentElement.dataset.uiShell,
      contrast: document.documentElement.dataset.contrast,
      legacyShell: localStorage.getItem('mentat-ui-shell-v1'),
    }))()`);
    if (
      savedAppearance.theme !== 'compact-dark'
      || savedAppearance.shell !== 'emerald'
      || savedAppearance.contrast !== 'high'
      || savedAppearance.legacyShell !== null
    ) {
      throw new Error(`Saved appearance migration contract failed: ${JSON.stringify(savedAppearance)}`);
    }
    if (process.env.MENTAT_APPEARANCE_SMOKE === '1') {
      const appearance = await verifyAppearanceContinuity(client);
      console.log(JSON.stringify({ ok: true, baseUrl, appearance }, null, 2));
      await client.ws.close?.();
      return;
    }
    if (process.env.MENTAT_NAV_TOOLTIP_SMOKE === '1') {
      const navigation = await verifyCompactNavigationTooltip(client);
      console.log(JSON.stringify({ ok: true, baseUrl, navigation }, null, 2));
      await client.ws.close?.();
      return;
    }

    await client.eval(`(() => {
      localStorage.setItem('mentat-theme', 'emerald');
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
        && document.querySelector('#agent-console-provider-select')
        && document.querySelector('#agent-console-tool-toggle')
        && !document.querySelector('#agent-console-apply-model')
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
      const agentSelect = rect('#agent-console-agent');
      const providerSelect = rect('#agent-console-provider-select');
      const modelSelect = rect('#agent-console-model-select');
      const prompt = rect('#agent-console-prompt');
      return {
        noMetrics: !document.querySelector('#overview-cards') && ![...document.querySelectorAll('.metric-card')].some((card) => card.getClientRects().length),
        firstRowAligned: Math.abs(focus.top - agents.top) <= 2,
        secondRowAligned: Math.abs(schedule.top - context.top) <= 2,
        columnRatio: focus.width / agents.width,
        consoleSpansGrid: Math.abs(consoleDock.left - grid.left) <= 2 && Math.abs(consoleDock.right - grid.right) <= 2,
        runtimeControlsAligned: Math.max(agentSelect.top, providerSelect.top, modelSelect.top) - Math.min(agentSelect.top, providerSelect.top, modelSelect.top) <= 2,
        promptBelowRuntime: prompt.top >= Math.max(agentSelect.bottom, providerSelect.bottom, modelSelect.bottom) - 2,
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
      || !homeDesktopLayout.runtimeControlsAligned
      || !homeDesktopLayout.promptBelowRuntime
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
    const consoleLayout = await client.eval(`(() => {
      const selectors = document.querySelector('.agent-console-runtime-row')?.getBoundingClientRect();
      const transcript = document.querySelector('#agent-console-transcript')?.getBoundingClientRect();
      const composer = document.querySelector('#agent-console-form')?.getBoundingClientRect();
      return {
        ordered: Boolean(
          selectors
          && transcript
          && composer
          && selectors.bottom <= transcript.top + 1
          && transcript.bottom <= composer.top + 1
        ),
        transcriptVisible: Boolean(document.querySelector('#agent-console-chat')?.getClientRects().length),
        composerVisible: Boolean(document.querySelector('#agent-console-prompt')?.getClientRects().length),
        stateVisible: Boolean(document.querySelector('#agent-console-state')?.getClientRects().length),
        disclosureRemoved: !document.querySelector('#agent-console-details'),
        redundantBannerRemoved: !document.querySelector('#agent-console-runtime-banner'),
      };
    })()`);
    if (
      !consoleLayout.ordered
      || !consoleLayout.transcriptVisible
      || !consoleLayout.composerVisible
      || !consoleLayout.stateVisible
      || !consoleLayout.disclosureRemoved
      || !consoleLayout.redundantBannerRemoved
    ) {
      throw new Error(`Agent Console vertical layout failed: ${JSON.stringify(consoleLayout)}`);
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
      const originalHomeRefreshAgentConsoleModels = refreshAgentConsoleModels;
      refreshAgentConsoleModels = async (agentId) => ({
        model_catalog: {
          ...(baseConsole.model_catalog || {}),
          profile_id: agentId,
        },
        provider_inventory: {
          ...(baseConsole.provider_inventory || {}),
          profile_id: agentId,
        },
      });
      renderAgentConsole({
        ...baseConsole,
        transport: { mode: 'local', binding_id: 'local-default', console_available: true },
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
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
      await new Promise((resolve) => setTimeout(resolve, 0));
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
      await new Promise((resolve) => setTimeout(resolve, 0));
      refreshAgentConsoleModels = originalHomeRefreshAgentConsoleModels;
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
    const structuredEventRendered = await client.eval(`(() => { state.agentConsoleSelectedAgentId = 'event-smoke'; state.agentConsoleTransportBinding = 'local:local-default'; renderAgentConsole({ agents: [{ id: 'event-smoke', name: 'Event Smoke', available: true, model: 'test/model' }], selected_agent_id: 'event-smoke', model_catalog: { profile_id: 'event-smoke', models: ['test/model'], current_model: 'test/model' }, runs: [{ id: 'run_event_smoke', agent_id: 'event-smoke', agent_name: 'Event Smoke', status: 'completed', transport_mode: 'local', connection_binding_id: 'local-default', prompt: 'Check events', response: 'Done', created_at: new Date().toISOString(), event_cursor: 1, events: [{ schema_version: 1, run_id: 'run_event_smoke', sequence: 1, cursor: 1, type: 'complete', kind: 'complete', timestamp: new Date().toISOString(), data: {}, display_text: 'Structured event rendered' }] }] }); return document.querySelector('#agent-console-chat')?.textContent.includes('Structured event rendered'); })()`);
    if (!structuredEventRendered) throw new Error('Structured Agent Console event render smoke failed');
    const hiddenToolState = await client.eval(`(() => {
      state.agentConsoleShowActivity = false;
      renderAgentConsole({
        agents: [{ id: 'tool-smoke', name: 'Tool Smoke', available: true, provider: 'alpha', model: 'alpha-one' }],
        provider_inventory: {
          profile_id: 'tool-smoke',
          current_provider: 'alpha',
          current_model: 'alpha-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'alpha', name: 'Alpha', current: true, models: ['alpha-one'] }],
        },
        runs: [{
          id: 'run_tool_smoke',
          agent_id: 'tool-smoke',
          agent_name: 'Tool Smoke',
          status: 'running',
          prompt: 'Use a tool',
          created_at: new Date().toISOString(),
          events: [{ type: 'tool.started', kind: 'tool.started', display_text: 'Using browser.search', timestamp: new Date().toISOString() }],
        }],
      });
      const chat = document.querySelector('#agent-console-chat')?.textContent || '';
      return {
        detailsHidden: !chat.includes('Using browser.search'),
        transcriptVisible: document.querySelector('#agent-console-chat')?.getClientRects().length > 0,
        activityVisible: document.querySelector('#agent-console-tool-activity-banner')?.getClientRects().length > 0,
        activityText: document.querySelector('#agent-console-tool-activity-banner')?.textContent || '',
        toggleLabel: document.querySelector('#agent-console-tool-toggle')?.textContent,
        pressed: document.querySelector('#agent-console-tool-toggle')?.getAttribute('aria-pressed'),
        animated: getComputedStyle(document.querySelector('.agent-console-tool-dots'), '::after').animationName === 'agent-console-tool-dots',
        liveNodeCount: document.querySelectorAll('#agent-console-tool-live-status[role="status"]').length,
        liveText: document.querySelector('#agent-console-tool-live-status')?.textContent || '',
        transientStatusCount: document.querySelectorAll('.agent-console-tool-activity[role="status"]').length,
      };
    })()`);
    if (
      !hiddenToolState.detailsHidden
      || !hiddenToolState.transcriptVisible
      || !hiddenToolState.activityVisible
      || !hiddenToolState.activityText.includes('Tool Smoke is using tools')
      || hiddenToolState.toggleLabel !== 'Show activity'
      || hiddenToolState.pressed !== 'false'
      || !hiddenToolState.animated
      || hiddenToolState.liveNodeCount !== 1
      || !hiddenToolState.liveText.includes('is using tools')
      || hiddenToolState.transientStatusCount !== 0
    ) {
      throw new Error(`Default-hidden tool activity contract failed: ${JSON.stringify(hiddenToolState)}`);
    }
    const shownToolState = await client.eval(`(() => {
      document.querySelector('#agent-console-tool-toggle').click();
      const chat = document.querySelector('#agent-console-chat')?.textContent || '';
      return {
        detailsVisible: chat.includes('Using browser.search'),
        activityHidden: document.querySelector('#agent-console-tool-activity-banner')?.hidden,
        toggleLabel: document.querySelector('#agent-console-tool-toggle')?.textContent,
        pressed: document.querySelector('#agent-console-tool-toggle')?.getAttribute('aria-pressed'),
      };
    })()`);
    if (
      !shownToolState.detailsVisible
      || !shownToolState.activityHidden
      || shownToolState.toggleLabel !== 'Hide activity'
      || shownToolState.pressed !== 'true'
    ) {
      throw new Error(`Tool visibility toggle contract failed: ${JSON.stringify(shownToolState)}`);
    }
    const stableToolLiveState = await client.eval(`(() => {
      state.agentConsoleShowActivity = false;
      const live = document.querySelector('#agent-console-tool-live-status');
      const observer = new MutationObserver(() => {});
      observer.observe(live, { childList: true, characterData: true, subtree: true });
      renderAgentConsole({
        agents: [{ id: 'tool-smoke', name: 'Tool Smoke', available: true, provider: 'alpha', model: 'alpha-one' }],
        provider_inventory: {
          profile_id: 'tool-smoke',
          current_provider: 'alpha',
          current_model: 'alpha-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'alpha', name: 'Alpha', current: true, models: ['alpha-one'] }],
        },
        runs: [{
          id: 'run_tool_smoke',
          agent_id: 'tool-smoke',
          agent_name: 'Tool Smoke',
          status: 'running',
          prompt: 'Use concurrent tools',
          created_at: new Date().toISOString(),
          events: [
            { type: 'tool.started', kind: 'tool.started', display_text: 'First tool', timestamp: new Date().toISOString() },
            { type: 'tool.started', kind: 'tool.started', display_text: 'Second tool', timestamp: new Date().toISOString() },
          ],
        }],
      });
      const repeatedAnnouncementMutations = observer.takeRecords().length;
      observer.disconnect();
      state.agentConsoleSelectedAgentId = 'tool-second';
      renderAgentConsole({
        agents: [
          { id: 'tool-smoke', name: 'Tool Smoke', available: true, provider: 'alpha', model: 'alpha-one' },
          { id: 'tool-second', name: 'Tool Second', available: true, provider: 'alpha', model: 'alpha-one' },
        ],
        provider_inventory: {
          profile_id: 'tool-second',
          current_provider: 'alpha',
          current_model: 'alpha-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'alpha', name: 'Alpha', current: true, models: ['alpha-one'] }],
        },
        runs: [],
        selected_agent_id: 'tool-second',
      });
      return {
        repeatedAnnouncementMutations,
        switchedAgentLiveText: live.textContent,
      };
    })()`);
    if (
      stableToolLiveState.repeatedAnnouncementMutations !== 0
      || stableToolLiveState.switchedAgentLiveText !== ''
    ) {
      throw new Error(`Stable tool live-region contract failed: ${JSON.stringify(stableToolLiveState)}`);
    }
    await client.eval(`(() => {
      window.__originalPreviewAgentConsoleProvider = previewAgentConsoleProvider;
      window.__originalSwitchAgentConsoleProvider = switchAgentConsoleProvider;
      window.__originalRefreshAgentConsoleModels = refreshAgentConsoleModels;
      window.__originalStartAgentConsoleRun = startAgentConsoleRun;
      window.__originalStageContextPack = stageContextPack;
      window.__runtimeSwitchCalls = [];
      window.__runtimeRunCalls = [];
      window.__runtimeContextPackCalls = [];
      startAgentConsoleRun = async (...args) => {
        window.__runtimeRunCalls.push(args);
        throw new Error('Unexpected run during runtime smoke.');
      };
      stageContextPack = async (...args) => {
        window.__runtimeContextPackCalls.push(args);
        return { attachments: [], instructions: '' };
      };
      refreshAgentConsoleModels = async (agentId) => ({
        model_catalog: {
          profile_id: agentId,
          models: [...(state.agentConsoleModels || [])],
          current_model: state.agentConsoleProviderInventory.current_model || '',
        },
        provider_inventory: structuredClone(state.agentConsoleProviderInventory),
      });
      window.__runtimeDynamicRefreshAgentConsoleModels = refreshAgentConsoleModels;
      window.__holdRuntimePreview = true;
      window.__resolveRuntimePreview = null;
      previewAgentConsoleProvider = async (provider, model, agentId) => {
        window.__runtimeSwitchCalls.push(['preview', provider, model, agentId]);
        if (window.__holdRuntimePreview) {
          await new Promise((resolve) => {
            window.__resolveRuntimePreview = resolve;
          });
        }
        return {
          profile_id: agentId,
          confirmation_id: 'provider_switch_browser_smoke',
          target: { provider, model },
        };
      };
      switchAgentConsoleProvider = async (provider, model, agentId, confirmationId) => {
        window.__runtimeSwitchCalls.push(['switch', provider, model, agentId, confirmationId]);
        return {
          ok: true,
          agent_id: agentId,
          provider,
          model,
          message: 'Runtime updated and verified.',
          model_catalog: { profile_id: agentId, models: [model], current_model: model },
          provider_inventory: {
            profile_id: agentId,
            current_provider: provider,
            current_model: model,
            capabilities: { 'providers.switch': true },
            providers: [
              { id: 'alpha', name: 'Alpha', current: provider === 'alpha', models: ['alpha-one'] },
              { id: 'beta', name: 'Beta', current: provider === 'beta', models: ['beta-first', 'beta-second'] },
            ],
          },
        };
      };
      state.agentConsoleShowActivity = false;
      state.agentConsoleRuntimeNotices = [];
      state.agentConsoleSelectedProvider = '';
      state.agentConsoleSelectedModel = '';
      state.agentConsoleRuntimeUnresolved = false;
      state.agentConsoleRuntimeLoading = false;
      renderAgentConsole({
        agents: [{ id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'legacy', model: 'legacy-one' }],
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'legacy',
          current_model: 'legacy-one',
          capabilities: { 'providers.switch': true },
          providers: [
            { id: 'beta', name: 'Beta', current: false, models: ['beta-first', 'beta-second'] },
          ],
        },
        runs: [],
      });
    })()`);
    const confirmedOutsideInventory = await client.eval(`(() => {
      const provider = document.querySelector('#agent-console-provider-select');
      const model = document.querySelector('#agent-console-model-select');
      return {
        provider: provider?.value,
        providerDisabled: provider?.selectedOptions[0]?.disabled,
        model: model?.value,
        modelDisabled: model?.selectedOptions[0]?.disabled,
        state: document.querySelector('#agent-console-state')?.textContent || '',
      };
    })()`);
    if (
      confirmedOutsideInventory.provider !== 'legacy'
      || !confirmedOutsideInventory.providerDisabled
      || confirmedOutsideInventory.model !== 'legacy-one'
      || !confirmedOutsideInventory.modelDisabled
      || confirmedOutsideInventory.state !== 'Ready'
    ) {
      throw new Error(`Confirmed runtime outside selectable inventory failed: ${JSON.stringify(confirmedOutsideInventory)}`);
    }
    const failedTransportRefreshState = await client.eval(`(async () => {
      refreshAgentConsoleModels = async () => {
        throw new Error('Rejected transport refresh');
      };
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-rejected-refresh', console_available: true },
        agents: state.agentConsoleAgents,
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'legacy',
          current_model: 'legacy-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'legacy', name: 'Legacy', current: true, models: ['legacy-one'] }],
        },
        runs: [],
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
      const rejected = {
        unresolved: state.agentConsoleRuntimeUnresolved,
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        retryVisible: document.querySelector('#agent-console-runtime-refresh')?.getClientRects().length > 0,
      };
      refreshAgentConsoleModels = async (agentId) => ({
        model_catalog: { profile_id: agentId, models: [], current_model: '' },
        provider_inventory: {
          profile_id: agentId,
          current_provider: '',
          current_model: '',
          capabilities: { 'providers.switch': false },
          providers: [],
          error: 'Runtime unavailable.',
        },
      });
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-degraded-refresh', console_available: true },
        agents: state.agentConsoleAgents,
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'legacy',
          current_model: 'legacy-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'legacy', name: 'Legacy', current: true, models: ['legacy-one'] }],
        },
        runs: [],
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
      const degraded = {
        unresolved: state.agentConsoleRuntimeUnresolved,
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        retryVisible: document.querySelector('#agent-console-runtime-refresh')?.getClientRects().length > 0,
      };
      refreshAgentConsoleModels = window.__runtimeDynamicRefreshAgentConsoleModels;
      state.agentConsoleRuntimeUnresolved = false;
      state.agentConsoleRuntimeLoading = false;
      return { rejected, degraded };
    })()`);
    if (
      !failedTransportRefreshState.rejected.unresolved
      || !failedTransportRefreshState.rejected.promptDisabled
      || !failedTransportRefreshState.rejected.retryVisible
      || !failedTransportRefreshState.degraded.unresolved
      || !failedTransportRefreshState.degraded.promptDisabled
      || !failedTransportRefreshState.degraded.retryVisible
    ) {
      throw new Error(`Transport refresh failure did not fail closed: ${JSON.stringify(failedTransportRefreshState)}`);
    }
    await client.eval(`(() => {
      state.agentConsoleSelectedProvider = '';
      state.agentConsoleSelectedModel = '';
      renderAgentConsole({
        agents: [{ id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'alpha', model: 'alpha-one' }],
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'alpha',
          current_model: 'alpha-one',
          capabilities: { 'providers.switch': true },
          providers: [
            { id: 'alpha', name: 'Alpha', current: true, models: ['alpha-one'] },
            { id: 'beta', name: 'Beta', current: false, models: ['beta-first', 'beta-second'] },
          ],
        },
        runs: [{
          id: 'runtime-history-before-switch',
          agent_id: 'runtime-smoke',
          agent_name: 'Runtime Smoke',
          status: 'completed',
          prompt: 'Earlier retained run',
          response: 'Earlier response',
          created_at: '2026-01-01T00:00:00.000Z',
          events: [],
        }],
      });
      const provider = document.querySelector('#agent-console-provider-select');
      provider.value = 'beta';
      provider.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await waitFor(() => client.eval(`window.__runtimeSwitchCalls?.length === 1 && Boolean(window.__resolveRuntimePreview)`), 'runtime preview pending');
    const pendingRuntimeState = await client.eval(`(() => ({
      state: document.querySelector('#agent-console-state')?.textContent || '',
      providerDisabled: document.querySelector('#agent-console-provider-select')?.disabled,
      modelDisabled: document.querySelector('#agent-console-model-select')?.disabled,
      promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
      sendDisabled: document.querySelector('#agent-console-form .agent-console-send')?.disabled,
    }))()`);
    if (
      !pendingRuntimeState.state.includes('Switching runtime')
      || pendingRuntimeState.state.includes('Ready')
      || !pendingRuntimeState.providerDisabled
      || !pendingRuntimeState.modelDisabled
      || !pendingRuntimeState.promptDisabled
      || !pendingRuntimeState.sendDisabled
    ) {
      throw new Error(`Pending runtime projection failed: ${JSON.stringify(pendingRuntimeState)}`);
    }
    await client.eval(`(() => {
      window.__holdRuntimePreview = false;
      window.__resolveRuntimePreview();
    })()`);
    await waitFor(() => client.eval(`window.__runtimeSwitchCalls?.length === 2 && document.querySelector('#agent-console-chat')?.textContent.includes('Switched to beta · beta-first')`), 'immediate provider runtime switch');
    const providerSwitchState = await client.eval(`(() => ({
      calls: window.__runtimeSwitchCalls,
      provider: document.querySelector('#agent-console-provider-select')?.value,
      model: document.querySelector('#agent-console-model-select')?.value,
      mutationUnlocked: !state.agentConsoleRuntimeMutationInFlight,
      bannerCount: document.querySelectorAll('#agent-console-runtime-banner').length,
      noticeAfterRetainedRun: document.querySelector('#agent-console-chat')?.lastElementChild?.classList.contains('agent-console-runtime-notice'),
    }))()`);
    if (
      JSON.stringify(providerSwitchState.calls) !== JSON.stringify([
        ['preview', 'beta', 'beta-first', 'runtime-smoke'],
        ['switch', 'beta', 'beta-first', 'runtime-smoke', 'provider_switch_browser_smoke'],
      ])
      || providerSwitchState.provider !== 'beta'
      || providerSwitchState.model !== 'beta-first'
      || !providerSwitchState.mutationUnlocked
      || providerSwitchState.bannerCount !== 0
      || !providerSwitchState.noticeAfterRetainedRun
    ) {
      throw new Error(`Immediate provider switch contract failed: ${JSON.stringify(providerSwitchState)}`);
    }
    await client.eval(`(() => {
      const model = document.querySelector('#agent-console-model-select');
      model.value = 'beta-second';
      model.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await waitFor(() => client.eval(`window.__runtimeSwitchCalls?.length === 4 && document.querySelector('#agent-console-model-select')?.value === 'beta-second'`), 'immediate model runtime switch');
    const modelSwitchState = await client.eval(`(() => ({
      calls: window.__runtimeSwitchCalls.slice(2),
      notice: document.querySelector('#agent-console-chat')?.textContent || '',
    }))()`);
    if (
      JSON.stringify(modelSwitchState.calls) !== JSON.stringify([
        ['preview', 'beta', 'beta-second', 'runtime-smoke'],
        ['switch', 'beta', 'beta-second', 'runtime-smoke', 'provider_switch_browser_smoke'],
      ])
      || !modelSwitchState.notice.includes('Switched to beta · beta-second')
    ) {
      throw new Error(`Immediate model switch contract failed: ${JSON.stringify(modelSwitchState)}`);
    }
    await client.eval(`(() => {
      window.__oldRuntimeBinding = state.agentConsoleTransportBinding;
      state.agentConsoleRuntimeNotices = [];
      window.__resolveOldBindingSwitch = null;
      switchAgentConsoleProvider = async (provider, model, agentId, confirmationId) => {
        window.__runtimeSwitchCalls.push(['switch-old-binding', provider, model, agentId, confirmationId]);
        await new Promise((resolve) => {
          window.__resolveOldBindingSwitch = resolve;
        });
        window.__oldBindingSwitchReturned = true;
        return {
          ok: true,
          agent_id: agentId,
          provider,
          model,
          message: 'Old binding switch completed.',
          model_catalog: { profile_id: agentId, models: [model], current_model: model },
          provider_inventory: {
            profile_id: agentId,
            current_provider: provider,
            current_model: model,
            capabilities: { 'providers.switch': true },
            providers: [{ id: provider, name: provider, current: true, models: [model] }],
          },
        };
      };
      const model = document.querySelector('#agent-console-model-select');
      model.value = 'beta-first';
      model.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await waitFor(() => client.eval(`Boolean(window.__resolveOldBindingSwitch)`), 'deferred old-binding switch');
    await client.eval(`(() => {
      const separator = window.__oldRuntimeBinding.indexOf(':');
      const originalMode = window.__oldRuntimeBinding.slice(0, separator);
      const originalBindingId = window.__oldRuntimeBinding.slice(separator + 1);
      state.agentConsoleSelectedProvider = '';
      state.agentConsoleSelectedModel = '';
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-new-binding', console_available: true },
        agents: [{ id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'gamma', model: 'gamma-one' }],
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'gamma',
          current_model: 'gamma-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'gamma', name: 'Gamma', current: true, models: ['gamma-one'] }],
        },
        runs: [],
      });
      state.agentConsoleSelectedProvider = '';
      state.agentConsoleSelectedModel = '';
      renderAgentConsole({
        transport: { mode: originalMode, binding_id: originalBindingId, console_available: true },
        agents: [{ id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'gamma', model: 'gamma-one' }],
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'gamma',
          current_model: 'gamma-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'gamma', name: 'Gamma', current: true, models: ['gamma-one'] }],
        },
        runs: [],
      });
      window.__resolveOldBindingSwitch();
    })()`);
    await waitFor(() => client.eval(`window.__oldBindingSwitchReturned && !state.agentConsoleRuntimeMutationInFlight`), 'A-B-A old-binding result discarded');
    const transportRaceState = await client.eval(`(() => ({
      provider: document.querySelector('#agent-console-provider-select')?.value,
      model: document.querySelector('#agent-console-model-select')?.value,
      state: document.querySelector('#agent-console-state')?.textContent || '',
      bannerCount: document.querySelectorAll('#agent-console-runtime-banner').length,
      newBindingNotice: state.agentConsoleRuntimeNotices.some((notice) => (
        notice.transport_binding === state.agentConsoleTransportBinding
        && notice.provider === 'beta'
        && notice.model === 'beta-first'
      )),
    }))()`);
    if (
      transportRaceState.provider !== 'gamma'
      || transportRaceState.model !== 'gamma-one'
      || !transportRaceState.state.includes('Ready')
      || transportRaceState.bannerCount !== 0
      || transportRaceState.newBindingNotice
    ) {
      throw new Error(`A-B-A old transport runtime result was not discarded: ${JSON.stringify(transportRaceState)}`);
    }
    await client.eval(`(() => {
      state.agentConsoleSelectedProvider = '';
      state.agentConsoleSelectedModel = '';
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-new-binding', console_available: true },
        agents: [{ id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'beta', model: 'beta-second' }],
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'beta',
          current_model: 'beta-second',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'beta', name: 'Beta', current: true, models: ['beta-first', 'beta-second'] }],
        },
        runs: [],
      });
      switchAgentConsoleProvider = async (provider, model, agentId, confirmationId) => {
        window.__runtimeSwitchCalls.push(['switch-failed', provider, model, agentId, confirmationId]);
        throw new Error('Hermes rejected the browser smoke switch.');
      };
      refreshAgentConsoleModels = async (agentId) => ({
        model_catalog: { profile_id: agentId, models: ['beta-first', 'beta-second'], current_model: 'beta-second' },
        provider_inventory: {
          profile_id: agentId,
          current_provider: 'beta',
          current_model: 'beta-second',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'beta', name: 'Beta', current: true, models: ['beta-first', 'beta-second'] }],
        },
      });
      const model = document.querySelector('#agent-console-model-select');
      model.value = 'beta-first';
      model.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await waitFor(() => client.eval(`document.querySelector('#agent-console-form-status')?.textContent.includes('Hermes rejected the browser smoke switch.') && document.querySelector('#agent-console-model-select')?.value === 'beta-second' && !state.agentConsoleRuntimeMutationInFlight`), 'failed runtime switch reconciliation');
    await client.eval(`(() => {
      refreshAgentConsoleModels = async (agentId) => ({
        ok: true,
        agent_id: agentId,
        model_catalog: { profile_id: agentId, models: [], current_model: '' },
        provider_inventory: {
          profile_id: agentId,
          current_provider: '',
          current_model: '',
          capabilities: { 'providers.switch': false },
          providers: [],
          error: 'Current runtime identity is unavailable.',
        },
      });
      const model = document.querySelector('#agent-console-model-select');
      model.value = 'beta-first';
      model.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await waitFor(() => client.eval(`state.agentConsoleRuntimeUnresolved && !state.agentConsoleRuntimeMutationInFlight`), 'unverified runtime fail-closed state');
    const unresolvedRuntimeState = await client.eval(`(() => ({
      state: document.querySelector('#agent-console-state')?.textContent || '',
      status: document.querySelector('#agent-console-form-status')?.textContent || '',
      bannerCount: document.querySelectorAll('#agent-console-runtime-banner').length,
      promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
      sendDisabled: document.querySelector('#agent-console-form .agent-console-send')?.disabled,
      attachDisabled: document.querySelector('#agent-console-attach')?.disabled,
      providerDisabled: document.querySelector('#agent-console-provider-select')?.disabled,
      modelDisabled: document.querySelector('#agent-console-model-select')?.disabled,
      retryVisible: document.querySelector('#agent-console-runtime-refresh')?.getClientRects().length > 0,
      retryCompact: document.querySelector('#agent-console-runtime-refresh')?.getBoundingClientRect().width
        < document.querySelector('#agent-console-transcript')?.getBoundingClientRect().width / 2,
      switchCallCount: window.__runtimeSwitchCalls.length,
    }))()`);
    if (
      !unresolvedRuntimeState.state.includes('Runtime verification required')
      || !unresolvedRuntimeState.status.includes('Retry the runtime check')
      || unresolvedRuntimeState.bannerCount !== 0
      || !unresolvedRuntimeState.promptDisabled
      || !unresolvedRuntimeState.sendDisabled
      || !unresolvedRuntimeState.attachDisabled
      || !unresolvedRuntimeState.providerDisabled
      || !unresolvedRuntimeState.modelDisabled
      || !unresolvedRuntimeState.retryVisible
      || !unresolvedRuntimeState.retryCompact
    ) {
      throw new Error(`Unverified runtime did not fail closed: ${JSON.stringify(unresolvedRuntimeState)}`);
    }
    const unresolvedContextPackState = await client.eval(`(async () => {
      state.contextPacks = [{
        id: 'runtime-pack',
        name: 'Runtime pack',
        note_paths: [],
        workspace_files: [],
      }];
      renderContextPacks({ context_packs: state.contextPacks });
      renderAgentConsoleContextPackPicker();
      await applyContextPackToConsole('runtime-pack');
      return {
        stageCalls: window.__runtimeContextPackCalls.length,
        listDisabled: document.querySelector('[data-use-context-pack="runtime-pack"]')?.disabled,
        pickerDisabled: document.querySelector('[data-apply-context-pack="runtime-pack"]')?.disabled,
        status: document.querySelector('#agent-console-form-status')?.textContent || '',
      };
    })()`);
    if (
      unresolvedContextPackState.stageCalls !== 0
      || !unresolvedContextPackState.listDisabled
      || !unresolvedContextPackState.pickerDisabled
      || !unresolvedContextPackState.status.includes('Wait until Hermes confirms')
    ) {
      throw new Error(`Unresolved Context Pack staging was not blocked: ${JSON.stringify(unresolvedContextPackState)}`);
    }
    const retryRuntimeState = await client.eval(`(async () => {
      refreshAgentConsoleModels = async (agentId) => ({
        model_catalog: { profile_id: agentId, models: ['gamma-one'], current_model: 'gamma-one' },
        provider_inventory: {
          profile_id: agentId,
          current_provider: 'gamma',
          current_model: 'gamma-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'gamma', name: 'Gamma', current: true, models: ['gamma-one'] }],
        },
      });
      document.querySelector('#agent-console-runtime-refresh').click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      return {
        unresolved: state.agentConsoleRuntimeUnresolved,
        provider: document.querySelector('#agent-console-provider-select')?.value,
        model: document.querySelector('#agent-console-model-select')?.value,
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        retryHidden: document.querySelector('#agent-console-runtime-refresh')?.hidden,
        bannerCount: document.querySelectorAll('#agent-console-runtime-banner').length,
        switchCallCount: window.__runtimeSwitchCalls.length,
      };
    })()`);
    if (
      retryRuntimeState.unresolved
      || retryRuntimeState.provider !== 'gamma'
      || retryRuntimeState.model !== 'gamma-one'
      || retryRuntimeState.promptDisabled
      || !retryRuntimeState.retryHidden
      || retryRuntimeState.bannerCount !== 0
      || retryRuntimeState.switchCallCount !== unresolvedRuntimeState.switchCallCount
    ) {
      throw new Error(`Explicit runtime reconciliation failed: ${JSON.stringify(retryRuntimeState)}`);
    }
    const stagingSerializationState = await client.eval(`(async () => {
      window.__resolveContextPackStage = null;
      stageContextPack = async (...args) => {
        window.__runtimeContextPackCalls.push(args);
        await new Promise((resolve) => {
          window.__resolveContextPackStage = resolve;
        });
        return { attachments: [], instructions: '' };
      };
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-new-binding', console_available: true },
        agents: [{ id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'gamma', model: 'gamma-one' }],
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'gamma',
          current_model: 'gamma-one',
          capabilities: { 'providers.switch': true },
          providers: [
            { id: 'gamma', name: 'Gamma', current: true, models: ['gamma-one'] },
            { id: 'beta', name: 'Beta', current: false, models: ['beta-first'] },
          ],
        },
        runs: [],
      });
      const switchCallsBefore = window.__runtimeSwitchCalls.length;
      const staging = applyContextPackToConsole('runtime-pack');
      await new Promise((resolve) => setTimeout(resolve, 0));
      const provider = document.querySelector('#agent-console-provider-select');
      const locked = {
        agent: document.querySelector('#agent-console-agent')?.disabled,
        provider: provider?.disabled,
        model: document.querySelector('#agent-console-model-select')?.disabled,
      };
      provider.value = 'beta';
      provider.dispatchEvent(new Event('change', { bubbles: true }));
      const providerAfterBlockedChange = provider.value;
      window.__resolveContextPackStage();
      await staging;
      return {
        locked,
        providerAfterBlockedChange,
        switchCallsUnchanged: window.__runtimeSwitchCalls.length === switchCallsBefore,
        stagingFinished: !state.agentConsoleAttachmentsUploading,
      };
    })()`);
    if (
      !stagingSerializationState.locked.agent
      || !stagingSerializationState.locked.provider
      || !stagingSerializationState.locked.model
      || stagingSerializationState.providerAfterBlockedChange !== 'gamma'
      || !stagingSerializationState.switchCallsUnchanged
      || !stagingSerializationState.stagingFinished
    ) {
      throw new Error(`Context Pack/runtime serialization failed: ${JSON.stringify(stagingSerializationState)}`);
    }
    const agentRefreshState = await client.eval(`(async () => {
      window.__resolveAgentRuntimeRead = null;
      refreshAgentConsoleModels = async (agentId) => {
        await new Promise((resolve) => {
          window.__resolveAgentRuntimeRead = resolve;
        });
        return {
          model_catalog: { profile_id: agentId, models: ['gamma-one'], current_model: 'gamma-one' },
          provider_inventory: {
            profile_id: agentId,
            current_provider: 'gamma',
            current_model: 'gamma-one',
            capabilities: { 'providers.switch': true },
            providers: [{ id: 'gamma', name: 'Gamma', current: true, models: ['gamma-one'] }],
          },
        };
      };
      state.agentConsoleAgents = [
        { id: 'runtime-smoke', name: 'Runtime Smoke', available: true, provider: 'beta', model: 'beta-second' },
        { id: 'runtime-second', name: 'Runtime Second', available: true, provider: 'gamma', model: 'gamma-one' },
      ];
      renderAgentConsole({ agents: state.agentConsoleAgents, provider_inventory: state.agentConsoleProviderInventory, runs: [] });
      const before = window.__runtimeSwitchCalls.length;
      const agent = document.querySelector('#agent-console-agent');
      agent.value = 'runtime-second';
      agent.dispatchEvent(new Event('change', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      const pending = {
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        sendDisabled: document.querySelector('#agent-console-form .agent-console-send')?.disabled,
        attachDisabled: document.querySelector('#agent-console-attach')?.disabled,
        newSessionDisabled: document.querySelector('#agent-console-new-session')?.disabled,
        state: document.querySelector('#agent-console-state')?.textContent || '',
      };
      renderAgentConsole({
        agents: state.agentConsoleAgents,
        provider_inventory: {
          profile_id: 'runtime-second',
          current_provider: 'stale-same-profile',
          current_model: 'stale-same-profile-one',
          capabilities: { 'providers.switch': true },
          providers: [{
            id: 'stale-same-profile',
            name: 'Stale same profile',
            current: true,
            models: ['stale-same-profile-one'],
          }],
        },
        runs: [],
      });
      const incidentalSameProfile = {
        loading: state.agentConsoleRuntimeLoading,
        promptDisabled: document.querySelector('#agent-console-prompt')?.disabled,
        sendDisabled: document.querySelector('#agent-console-form .agent-console-send')?.disabled,
      };
      state.agentConsoleStartFresh = false;
      document.querySelector('#agent-console-new-session').click();
      const prompt = document.querySelector('#agent-console-prompt');
      prompt.value = 'Must not run before runtime confirmation';
      await submitAgentConsolePrompt();
      const blockedActions = {
        startFresh: state.agentConsoleStartFresh,
        runCalls: window.__runtimeRunCalls.length,
      };
      window.__resolveAgentRuntimeRead();
      await new Promise((resolve) => setTimeout(resolve, 0));
      return {
        switchCallsUnchanged: window.__runtimeSwitchCalls.length === before,
        provider: document.querySelector('#agent-console-provider-select')?.value,
        model: document.querySelector('#agent-console-model-select')?.value,
        status: document.querySelector('#agent-console-form-status')?.textContent || '',
        pending,
        incidentalSameProfile,
        blockedActions,
      };
    })()`);
    if (
      !agentRefreshState.switchCallsUnchanged
      || agentRefreshState.provider !== 'gamma'
      || agentRefreshState.model !== 'gamma-one'
      || !agentRefreshState.status.includes('confirmed by Hermes')
      || !agentRefreshState.pending.promptDisabled
      || !agentRefreshState.pending.sendDisabled
      || !agentRefreshState.pending.attachDisabled
      || !agentRefreshState.pending.newSessionDisabled
      || !agentRefreshState.pending.state.includes('Checking Hermes runtime')
      || !agentRefreshState.incidentalSameProfile.loading
      || !agentRefreshState.incidentalSameProfile.promptDisabled
      || !agentRefreshState.incidentalSameProfile.sendDisabled
      || agentRefreshState.blockedActions.startFresh
      || agentRefreshState.blockedActions.runCalls !== 0
    ) {
      throw new Error(`Agent runtime refresh contract failed: ${JSON.stringify(agentRefreshState)}`);
    }
    const staleAgentRefreshState = await client.eval(`(async () => {
      window.__resolveStaleAgentRuntimeRead = null;
      window.__staleAgentRuntimeReadCalls = 0;
      refreshAgentConsoleModels = async (agentId) => {
        window.__staleAgentRuntimeReadCalls += 1;
        if (window.__staleAgentRuntimeReadCalls === 1) {
          await new Promise((resolve) => {
            window.__resolveStaleAgentRuntimeRead = resolve;
          });
        } else {
          return {
            model_catalog: { profile_id: agentId, models: ['delta-one'], current_model: 'delta-one' },
            provider_inventory: {
              profile_id: agentId,
              current_provider: 'delta',
              current_model: 'delta-one',
              capabilities: { 'providers.switch': true },
              providers: [{ id: 'delta', name: 'Delta', current: true, models: ['delta-one'] }],
            },
          };
        }
        return {
          model_catalog: { profile_id: agentId, models: ['stale-one'], current_model: 'stale-one' },
          provider_inventory: {
            profile_id: agentId,
            current_provider: 'stale',
            current_model: 'stale-one',
            capabilities: { 'providers.switch': true },
            providers: [{ id: 'stale', name: 'Stale', current: true, models: ['stale-one'] }],
          },
        };
      };
      const agent = document.querySelector('#agent-console-agent');
      agent.value = 'runtime-smoke';
      agent.dispatchEvent(new Event('change', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-stale-agent-binding', console_available: true },
        agents: state.agentConsoleAgents,
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'delta',
          current_model: 'delta-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'delta', name: 'Delta', current: true, models: ['delta-one'] }],
        },
        runs: [],
      });
      for (let attempt = 0; attempt < 20 && state.agentConsoleProviderInventory.current_provider !== 'delta'; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5));
      }
      const confirmedBeforeOldAgentRead = state.agentConsoleProviderInventory.current_provider;
      window.__resolveStaleAgentRuntimeRead();
      await new Promise((resolve) => setTimeout(resolve, 0));
      return {
        provider: document.querySelector('#agent-console-provider-select')?.value,
        model: document.querySelector('#agent-console-model-select')?.value,
        unresolved: state.agentConsoleRuntimeUnresolved,
        state: document.querySelector('#agent-console-state')?.textContent || '',
        calls: window.__staleAgentRuntimeReadCalls,
        confirmedBeforeOldAgentRead,
      };
    })()`);
    if (
      staleAgentRefreshState.provider !== 'delta'
      || staleAgentRefreshState.model !== 'delta-one'
      || staleAgentRefreshState.unresolved
      || staleAgentRefreshState.state !== 'Ready'
    ) {
      throw new Error(`Stale agent runtime read overwrote the new binding: ${JSON.stringify(staleAgentRefreshState)}`);
    }
    const staleRetryRefreshState = await client.eval(`(async () => {
      state.agentConsoleRuntimeUnresolved = true;
      clearAgentConsoleRuntimeForInspection('runtime-smoke');
      renderAgentConsole({
        agents: state.agentConsoleAgents,
        provider_inventory: state.agentConsoleProviderInventory,
        runs: [],
      });
      window.__resolveStaleRetryRuntimeRead = null;
      window.__staleRetryRuntimeReadCalls = 0;
      refreshAgentConsoleModels = async (agentId) => {
        window.__staleRetryRuntimeReadCalls += 1;
        if (window.__staleRetryRuntimeReadCalls === 1) {
          await new Promise((resolve) => {
            window.__resolveStaleRetryRuntimeRead = resolve;
          });
        } else {
          return {
            model_catalog: { profile_id: agentId, models: ['epsilon-one'], current_model: 'epsilon-one' },
            provider_inventory: {
              profile_id: agentId,
              current_provider: 'epsilon',
              current_model: 'epsilon-one',
              capabilities: { 'providers.switch': true },
              providers: [{ id: 'epsilon', name: 'Epsilon', current: true, models: ['epsilon-one'] }],
            },
          };
        }
        return {
          model_catalog: { profile_id: agentId, models: ['stale-retry-one'], current_model: 'stale-retry-one' },
          provider_inventory: {
            profile_id: agentId,
            current_provider: 'stale-retry',
            current_model: 'stale-retry-one',
            capabilities: { 'providers.switch': true },
            providers: [{ id: 'stale-retry', name: 'Stale retry', current: true, models: ['stale-retry-one'] }],
          },
        };
      };
      document.querySelector('#agent-console-runtime-refresh').click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      renderAgentConsole({
        transport: { mode: 'remote', binding_id: 'browser-smoke-stale-retry-binding', console_available: true },
        agents: state.agentConsoleAgents,
        provider_inventory: {
          profile_id: 'runtime-smoke',
          current_provider: 'epsilon',
          current_model: 'epsilon-one',
          capabilities: { 'providers.switch': true },
          providers: [{ id: 'epsilon', name: 'Epsilon', current: true, models: ['epsilon-one'] }],
        },
        runs: [],
      });
      for (let attempt = 0; attempt < 20 && state.agentConsoleProviderInventory.current_provider !== 'epsilon'; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5));
      }
      const confirmedBeforeOldRetryRead = state.agentConsoleProviderInventory.current_provider;
      window.__resolveStaleRetryRuntimeRead();
      await new Promise((resolve) => setTimeout(resolve, 0));
      return {
        provider: document.querySelector('#agent-console-provider-select')?.value,
        model: document.querySelector('#agent-console-model-select')?.value,
        unresolved: state.agentConsoleRuntimeUnresolved,
        state: document.querySelector('#agent-console-state')?.textContent || '',
        calls: window.__staleRetryRuntimeReadCalls,
        confirmedBeforeOldRetryRead,
      };
    })()`);
    if (
      staleRetryRefreshState.provider !== 'epsilon'
      || staleRetryRefreshState.model !== 'epsilon-one'
      || staleRetryRefreshState.unresolved
      || staleRetryRefreshState.state !== 'Ready'
    ) {
      throw new Error(`Stale retry runtime read overwrote the new binding: ${JSON.stringify(staleRetryRefreshState)}`);
    }
    await client.eval(`(() => {
      previewAgentConsoleProvider = window.__originalPreviewAgentConsoleProvider;
      switchAgentConsoleProvider = window.__originalSwitchAgentConsoleProvider;
      refreshAgentConsoleModels = window.__originalRefreshAgentConsoleModels;
      startAgentConsoleRun = window.__originalStartAgentConsoleRun;
      stageContextPack = window.__originalStageContextPack;
      delete window.__originalPreviewAgentConsoleProvider;
      delete window.__originalSwitchAgentConsoleProvider;
      delete window.__originalRefreshAgentConsoleModels;
      delete window.__originalStartAgentConsoleRun;
      delete window.__originalStageContextPack;
      delete window.__runtimeDynamicRefreshAgentConsoleModels;
      delete window.__runtimeSwitchCalls;
      delete window.__runtimeRunCalls;
      delete window.__runtimeContextPackCalls;
    })()`);
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
    await waitFor(() => client.eval(`document.querySelectorAll('#calendar-week-days .calendar-week-day-header').length === 7 && document.querySelector('#calendar-week')?.getAttribute('aria-busy') === 'false'`), 'Operator Week render', 30000);
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
    await verifyAppearanceContinuity(client);
    await waitFor(() => client.eval(`document.querySelector('#mentat-version')?.textContent.startsWith('v0.1.0')`), 'Mentat version display');
    const supportActionsVisible = await client.eval(`Boolean(document.querySelector('#download-diagnostics') && document.querySelector('a[href*="issues/new?template=bug_report.yml"]') && document.querySelector('a[href$="#quick-start"]'))`);
    if (!supportActionsVisible) throw new Error('Settings support actions smoke failed');
    await waitFor(() => client.eval(`['off', 'ready', 'receiving', 'degraded'].includes(state.hermesWebhookHealth?.state)`), 'webhook health render');
    const webhookHealthContract = await client.eval(`(() => {
      const setup = document.querySelector('#webhook-setup-text')?.textContent || '';
      const summary = document.querySelector('#webhook-health-summary')?.textContent || '';
      return {
        setup,
        summary,
        copyEnabled: !document.querySelector('#copy-webhook-setup')?.disabled,
      };
    })()`);
    if (
      !webhookHealthContract.setup.startsWith('hooks:')
      || !webhookHealthContract.setup.includes('secret_env: <YOUR_PRIVATE_SECRET_ENV>')
      || webhookHealthContract.setup.includes('MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT')
      || !webhookHealthContract.summary.includes('Signed local receiver')
      || !webhookHealthContract.copyEnabled
    ) {
      throw new Error(`Webhook health contract smoke failed: ${JSON.stringify(webhookHealthContract)}`);
    }
    const webhookInteractions = await client.eval(`(async () => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: async (value) => { window.__webhookCopiedSetup = value; } },
      });
      document.querySelector('#copy-webhook-setup').click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      const copyStatus = document.querySelector('#webhook-health-status')?.textContent || '';
      renderWebhookHealth({
        state: 'ready', state_label: 'Ready',
        summary: 'The signed receiver is ready and waiting for its first verified event.',
        probe_available: true,
        target_path: '/api/integrations/hermes/webhooks/v1/local-default',
        events: ['on_session_end', 'on_session_start', 'subagent_start', 'subagent_stop'],
        ages_seconds: { last_event: null, last_refresh: null, last_reconciliation: 12 },
        counters: { accepted: 0, coalesced: 0, dropped: 0, refresh_successes: 0, refresh_failures: 0 },
      });
      verifyHermesWebhookProbe = async () => ({ ok: true, result: 'webhook_probe_accepted' });
      fetchHermesWebhookHealth = async () => ({
        state: 'receiving', state_label: 'Receiving',
        summary: 'The signed receiver has accepted verified Hermes events.',
        probe_available: true,
        target_path: '/api/integrations/hermes/webhooks/v1/local-default',
        events: ['on_session_end', 'on_session_start', 'subagent_start', 'subagent_stop'],
        ages_seconds: { last_event: 0, last_refresh: 0, last_reconciliation: 12 },
        counters: { accepted: 1, coalesced: 0, dropped: 0, refresh_successes: 1, refresh_failures: 0 },
      });
      document.querySelector('#verify-webhook-probe').click();
      for (let attempt = 0; attempt < 20 && !document.querySelector('#webhook-health-status')?.textContent.includes('Signed probe accepted'); attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5));
      }
      return {
        copied: window.__webhookCopiedSetup || '',
        copyStatus,
        probeStatus: document.querySelector('#webhook-health-status')?.textContent || '',
        state: state.hermesWebhookHealth?.state || '',
      };
    })()`);
    if (
      !webhookInteractions.copied.startsWith('hooks:')
      || !webhookInteractions.copyStatus.includes('Manual Hermes setup copied')
      || !webhookInteractions.probeStatus.includes('Signed probe accepted')
      || webhookInteractions.state !== 'receiving'
    ) {
      throw new Error(`Webhook interaction smoke failed: ${JSON.stringify(webhookInteractions)}`);
    }
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

    await verifyCompactNavigationTooltip(client);

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

    console.log(JSON.stringify({ ok: true, baseUrl, checks: ['Emerald shell defaults', 'legacy shell migration', 'theme and contrast reload', 'reference-aligned Home desktop layout', 'reference-aligned Home mobile layout', 'Home disclosures across seven widths', 'Today-only schedule and degradation state', 'concurrent schedule lanes', '23:45 schedule target across seven widths', 'connection-bound Live Agents', 'unavailable-agent ranking', 'approval and clarification Console states', 'Home operational accessible names', 'no Home metric cards', 'Agent Console vertical layout', 'six-view responsive matrix', 'compact navigation label tooltip', 'mobile drawer keyboard and focus', 'skip link', 'today render', 'agent console controls', 'structured event render', 'default-hidden tool activity', 'tool visibility toggle', 'immediate provider switch', 'immediate model switch', 'failed switch reconciliation', 'agent runtime refresh', 'Mentat command manifest', 'nav', 'task controls', 'task status filter', 'Operator Week render', 'calendar week navigation', 'calendar preview safety', 'calendar event inspector', 'managed agents inventory', 'agent deletion safeguards', 'Agent Creator dialog', 'Context Packs workspace', 'equal Theme Studio cards', 'border-only dropdown focus', 'phone theme grid hiding', 'Settings support actions', 'Mentat version display', 'redacted diagnostics download'] }, null, 2));
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
