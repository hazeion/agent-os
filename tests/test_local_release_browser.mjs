import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { CHECKS, DIAGNOSTICS, configuration, expression, observe, validChecks } from '../scripts/mentat_acceptance_browser.mjs';
const config = { origin: 'http://127.0.0.1:54321', debug_port: 54322, project_id: 'project_exact', task_id: 'task_exact', elapsed_offset_ms: 0, remaining_ms: 30 };
test('configuration refuses arbitrary origins, ids, fields and extended wall budgets', () => {
  for (const change of [{ origin: 'https://example.invalid' }, { origin: 'http://127.0.0.1:54321/tasks' }, { project_id: '";execute()' }, { task_id: '../outside' }, { expression: 'arbitrary' }, { elapsed_offset_ms: 39999, remaining_ms: 2 }]) assert.throws(() => configuration({ ...config, ...change }));
});
function snapshot(changes = {}) {
  const root = { dataset: { shellHydrated: 'true', shellRuntime: 'ready' } };
  const parent = { hidden: false, getAttribute: () => null, parentElement: null };
  const strong = text => ({ textContent: text, parentElement: parent, getAttribute: () => null, getBoundingClientRect: () => ({ width: 100, height: 20, left: 1, top: 1, right: 101, bottom: 21 }) });
  const projectText = strong('Disposable acceptance Project'), taskText = strong('Disposable acceptance Task');
  const project = { dataset: { projectId: 'project_exact' }, querySelector: () => projectText, getAttribute: () => 'true' };
  const task = { dataset: { planningTaskId: 'task_exact' }, querySelector: () => taskText };
  if (changes.hidden) parent.hidden = true;
  if (changes.offscreen) taskText.getBoundingClientRect = () => ({ width: 100, height: 20, left: 1, top: 1200, right: 101, bottom: 1220 });
  if (changes.wrongTask) task.dataset.planningTaskId = 'task_other';
  if (changes.unselected) project.getAttribute = () => 'false';
  if (changes.notHydrated) root.dataset.shellHydrated = 'false';
  const context = { document: { readyState: 'complete', documentElement: root,
    querySelectorAll: selector => selector.includes('button') ? [project] : [task],
    querySelector: selector => selector === '#main-content h1' ? { textContent: changes.wrongHeading ? 'Other page' : 'Projects & Tasks' } : selector.includes('bridge') ? { dataset: { state: changes.bridgeChecking ? 'checking' : 'ready' } } : {} },
    location: { origin: config.origin, pathname: '/tasks' }, innerWidth: changes.wrongViewport ? 800 : 1440, innerHeight: 1000,
    getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }) };
  return JSON.parse(JSON.stringify(vm.runInNewContext(expression(config), context)));
}
test('fixed DOM predicate binds actual identities, visible rows and selected Project', () => {
  assert.ok(Object.values(snapshot()).every(Boolean));
  assert.equal(snapshot({ wrongTask: true }).task_visible, false);
  assert.equal(snapshot({ hidden: true }).project_visible, false);
  assert.equal(snapshot({ hidden: true }).task_visible, false);
  assert.equal(snapshot({ unselected: true }).project_selected, false);
  assert.equal(snapshot({ notHydrated: true }).shell_hydrated, false);
  assert.equal(snapshot({ bridgeChecking: true }).bridge_ready, false);
  assert.equal(snapshot({ wrongViewport: true }).viewport_correct, false);
  assert.equal(snapshot({ wrongHeading: true }).heading_correct, false);
  assert.equal(snapshot({ offscreen: true }).task_visible, false);
  assert.equal(snapshot({ offscreen: true }).diagnostics.task_renderable, true);
  assert.equal(snapshot({ offscreen: true }).diagnostics.task_intersects_viewport, false);
  assert.equal(snapshot({ hidden: true }).diagnostics.task_renderable, false);
  assert.equal(snapshot({ wrongTask: true }).diagnostics.task_exists, false);
});
test('readiness evidence requires exact boolean closure, not strings or extra payload', () => {
  const ready = Object.fromEntries(CHECKS.map(key => [key, true]));
  assert.equal(validChecks(ready), true);
  assert.equal(validChecks({ ...ready, task_visible: 'true' }), false);
  assert.equal(validChecks({ ...ready, raw_dom: 'private' }), false);
});
test('a connecting websocket timeout closes the owned transport and refuses readiness', async () => {
  let closed = false;
  class Socket { constructor() { this.readyState = 0; } close() { closed = true; this.readyState = 3; } }
  const result = await observe({ ...config, remaining_ms: 10 }, { WebSocket: Socket, now: () => 0,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, false); assert.equal(closed, true);
  assert.equal(Object.values(result.checks).some(Boolean), false);
});
test('fixed protocol reaches readiness and closes without navigating or closing Chrome', async () => {
  const messages = []; let closed = false;
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); messages.push(message);
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) }));
    }
    close() { closed = true; this.readyState = 3; }
  }
  const result = await observe(config, { now: () => 0, WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, true); assert.equal(closed, true);
  assert.deepEqual(messages.map(item => item.method), ['Runtime.enable','Emulation.setDeviceMetricsOverride','Runtime.evaluate']);
  assert.deepEqual(messages[1].params, { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  assert.ok(CHECKS.every(key => result.checks[key] === true));
});
test('a foreign debugger endpoint is never connected', async () => {
  let clock = 0, connected = false;
  class Socket { constructor() { connected = true; } }
  const result = await observe({ ...config, remaining_ms: 10 }, { now: () => clock, WebSocket: Socket,
    fetch: async () => { clock = 10; return { ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: 'ws://example.invalid/devtools/page/outside' }]))] }; } });
  assert.equal(result.ready, false); assert.equal(connected, false);
});

test('progress is initial and changed-only bounded evidence with reserved final capacity', async () => {
  const progress = []; let clock = 0, evaluations = 0;
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); let value;
      if (message.method === 'Runtime.evaluate') {
        evaluations++; clock += 150;
        value = snapshot({ notHydrated: evaluations % 2 === 0, offscreen: true });
      }
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: value ? { result: { value } } : {} }) }));
    }
    close() { this.readyState = 3; }
  }
  const result = await observe({ ...config, remaining_ms: 4000 }, { now: () => clock, WebSocket: Socket,
    onProgress: value => progress.push(value),
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, false);
  assert.ok(evaluations > 16); assert.ok(progress.length <= 16);
  assert.ok(Buffer.byteLength(progress.map(value => JSON.stringify(value) + '\n').join('')) <= 12288);
  assert.ok(Buffer.byteLength(JSON.stringify(result) + '\n') <= 4096);
  assert.equal(progress[0].event, 'progress');
  assert.ok(Object.values(progress[0].checks).every(value => value === false));
  assert.deepEqual(Object.keys(progress.at(-1).diagnostics).sort(), [...DIAGNOSTICS].sort());
  assert.equal(progress.at(-1).diagnostics.task_renderable, true);
  assert.equal(progress.at(-1).checks.task_visible, false);
});
