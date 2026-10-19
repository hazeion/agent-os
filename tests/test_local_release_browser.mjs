import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { CHECKS, DIAGNOSTICS, configuration, expression, observe, validChecks } from '../scripts/mentat_acceptance_browser.mjs';
const config = { origin: 'http://127.0.0.1:54321', debug_port: 54322, project_id: 'project_exact', task_id: 'task_exact', elapsed_offset_ms: 0, remaining_ms: 30 };
test('configuration refuses arbitrary origins, ids, fields and extended wall budgets', () => {
  for (const change of [{ origin: 'https://example.invalid' }, { origin: 'http://127.0.0.1:54321/tasks' }, { project_id: '";execute()' }, { task_id: '../outside' }, { expression: 'arbitrary' }, { elapsed_offset_ms: 39999, remaining_ms: 2 }]) assert.throws(() => configuration({ ...config, ...change }));
});
function snapshot(changes = {}) {
  const root = changes.missingDocumentRoot ? null : { dataset: { shellHydrated: 'true', shellRuntime: 'ready' } };
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
  const context = { document: { readyState: changes.missingDocumentRoot ? 'loading' : 'complete', documentElement: root,
    querySelectorAll: selector => changes.missingDocumentRoot ? [] : selector.includes('button') ? [project] : [task],
    querySelector: selector => changes.missingDocumentRoot ? null : selector === '#main-content h1' ? { textContent: changes.wrongHeading ? 'Other page' : 'Projects & Tasks' } : selector.includes('bridge') ? { dataset: { state: changes.bridgeChecking ? 'checking' : 'ready' } } : {} },
    location: changes.browserError ? { origin: 'null', pathname: '/chromewebdata/', href: 'chrome-error://chromewebdata/', protocol: 'chrome-error:' } : changes.foreign ? { origin: 'https://other.invalid', pathname: '/tasks', href: 'https://other.invalid/tasks', protocol: 'https:' } : changes.auth ? { origin: config.origin, pathname: '/sign-in', href: config.origin + '/sign-in?return=%2Ftasks', protocol: 'http:' } : changes.blank ? { origin: 'null', pathname: 'blank', href: 'about:blank', protocol: 'about:' } : { origin: config.origin, pathname: '/tasks' }, innerWidth: changes.wrongViewport ? 800 : 1440, innerHeight: 1000,
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
  assert.equal(snapshot().observation.ready_state, 'complete');
  assert.equal(snapshot().observation.location_category, 'tasks');
  assert.equal(snapshot({ blank: true }).observation.location_category, 'blank');
  assert.equal(snapshot({ blank: true }).document_complete, false);
  assert.equal(snapshot({ auth: true }).observation.location_category, 'auth');
  assert.equal(snapshot({ auth: true }).document_complete, false);
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
  assert.equal(result.code, 'browser_protocol_timeout'); assert.equal(result.stage, 'connect');
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
  assert.deepEqual(messages.map(item => item.method), ['Runtime.enable','Page.enable','Emulation.setFocusEmulationEnabled','Emulation.setDeviceMetricsOverride','Runtime.evaluate']);
  assert.deepEqual(messages[3].params, { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  assert.ok(CHECKS.every(key => result.checks[key] === true));
  assert.deepEqual(messages[2].params, { enabled: true });
  assert.equal(messages.filter(item => item.method === 'Page.navigate').length, 0);
  assert.equal(result.observation.location_category, 'tasks');
  assert.equal(result.observation.snapshots, 1);
  assert.equal(result.stage, 'ready');
  assert.equal(result.transport.sent_requests, 5);
  assert.equal(result.transport.matched_responses, 5);
  assert.equal(result.transport.pending_calls, 0);
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
        evaluations++; clock += 100;
        value = snapshot({ notHydrated: evaluations % 2 === 0, offscreen: true });
      }
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: value ? { result: { value } } : {} }) }));
    }
    close() { this.readyState = 3; }
  }
  const result = await observe({ ...config, remaining_ms: 1800 }, { now: () => clock, WebSocket: Socket,
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

test('ambiguous page inventories are refused before any websocket setup', async () => {
  const expected = config.origin + '/tasks';
  for (const urls of [[expected,expected], [expected,'about:blank'], [expected,'https://other.invalid'], ['about:blank','about:blank']]) {
    let connected = false;
    class Socket { constructor() { connected = true; } }
    const pages = urls.map((url,index) => ({ type: 'page', url, webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned-${index}` }));
    const result = await observe(config, { now: () => 0, WebSocket: Socket,
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify(pages))] }) });
    assert.equal(connected, false); assert.equal(result.ready, false);
    assert.equal(result.code, 'browser_target_ambiguous'); assert.equal(result.transport.sent_requests, 0);
  }
});

test('existing Runtime response timer is distinct from protocol rejection at the same fixed stage', async () => {
  for (const rejection of [false, true]) {
    const progress = [], methods = [];
    class Socket {
      constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
      send(raw) {
        const message = JSON.parse(raw); methods.push(message.method);
        if (message.method === 'Runtime.enable' && !rejection) return;
        queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, ...(message.method === 'Runtime.enable' ? { error: { message: 'private error and URL' } } : { result: {} }) }) }));
      }
      close() { this.readyState = 3; }
    }
    const result = await observe(config, { now: () => 0, WebSocket: Socket, onProgress: value => progress.push(value),
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
    assert.equal(result.ready, false);
    assert.equal(result.code, rejection ? 'browser_protocol_failed' : 'browser_protocol_timeout');
    assert.equal(result.stage, 'runtime');
    assert.equal(methods.filter(method => method === 'Runtime.enable').length, 1);
    assert.equal(methods.includes('Runtime.evaluate'), false);
    assert.equal(progress.at(-1).stage, 'runtime');
    assert.deepEqual(progress.map(value => value.stage).filter((value, index, values) => index === 0 || value !== values[index - 1]), ['discovery','connect','runtime']);
    assert.equal(JSON.stringify(result).includes('private'), false);
  }
});

test('an acknowledgement observed after remaining budget expires never starts evaluation', async () => {
  const methods = []; let clock = 0;
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); methods.push(message.method);
      if (message.method === 'Runtime.enable') clock = 31;
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: {} }) }));
    }
    close() { this.readyState = 3; }
  }
  const result = await observe(config, { now: () => clock, WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, false); assert.equal(result.stage, 'runtime');
  assert.equal(methods.filter(method => method === 'Runtime.enable').length, 1);
  assert.equal(methods.includes('Runtime.evaluate'), false);
});

test('initial setup exhausting remaining budget cannot send navigation or evaluate', async () => {
  const methods = []; let clock = 0;
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); methods.push(message.method);
      if (message.method === 'Emulation.setDeviceMetricsOverride') clock = 31;
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: {} }) }));
    }
    close() { this.readyState = 3; }
  }
  const result = await observe(config, { now: () => clock, WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, false); assert.equal(result.stage, 'viewport');
  assert.equal(methods.includes('Page.navigate'), false);
  assert.equal(methods.includes('Runtime.evaluate'), false);
});

test('Runtime setup acknowledgement beyond 500ms shares the existing remaining budget', async () => {
  for (const remaining of [1500, 30]) {
  const methods = []; let acknowledgement;
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); methods.push(message.method);
      const answer = () => this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) });
      if (message.method === 'Runtime.enable') acknowledgement = setTimeout(answer, 650);
      else queueMicrotask(answer);
    }
    close() { this.readyState = 3; clearTimeout(acknowledgement); }
  }
  const result = await observe({ ...config, remaining_ms: remaining }, { now: remaining === 1500 ? undefined : () => 0, WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  if (remaining === 1500) {
    assert.equal(result.ready, true); assert.equal(result.stage, 'ready');
    assert.ok(CHECKS.every(key => result.checks[key]));
    assert.equal(methods.filter(method => method === 'Page.navigate').length, 0);
    assert.equal(result.transport.sent_requests, 5); assert.equal(result.transport.matched_responses, 5);
  } else {
    assert.equal(result.ready, false); assert.equal(result.stage, 'runtime');
    assert.equal(result.code, 'browser_protocol_timeout');
    assert.equal(methods.includes('Page.navigate'), false); assert.equal(methods.includes('Runtime.evaluate'), false);
  }
  }
});
test('unexpected close and error reject owned pending waits at their fixed stage', async () => {
  for (const kind of ['close','error']) for (const when of ['connect','runtime','evaluation-race']) {
    const methods = [];
    class Socket {
      constructor() {
        this.readyState = 0;
        queueMicrotask(() => { if (when === 'connect') this.fail(); else { this.readyState = 1; this.onopen(); } });
      }
      fail() {
        if (kind === 'close') { this.readyState = 3; this.onclose({ code: 1006, reason: 'private close reason' }); }
        else this.onerror({ message: 'private transport error' });
      }
      send(raw) {
        const message = JSON.parse(raw); methods.push(message.method);
        if (when === 'runtime') { queueMicrotask(() => this.fail()); return; }
        queueMicrotask(() => {
          this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) });
          if (message.method === 'Runtime.evaluate') this.fail();
        });
      }
      close() { this.readyState = 3; }
    }
    const result = await observe(config, { now: () => 0, WebSocket: Socket,
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
    assert.equal(result.ready, false);
    assert.equal(result.code, kind === 'close' ? 'browser_transport_closed' : 'browser_transport_error');
    assert.equal(result.stage, when === 'evaluation-race' ? 'evaluation' : when);
    assert.equal(result.transport.pending_calls, 0);
    assert.equal(result.transport.socket_closed, kind === 'close');
    assert.equal(result.transport.socket_error, kind === 'error');
    assert.equal(result.transport.close_code, kind === 'close' ? 1006 : 0);
    if (when !== 'evaluation-race') assert.equal(methods.includes('Page.navigate'), false);
    assert.equal(methods.filter(method => method === 'Page.navigate').length, 0);
    assert.equal(JSON.stringify(result).includes('private'), false);
  }
});
test('invalid transport diagnostics cannot create successful readiness', async () => {
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw);
      queueMicrotask(() => {
        if (message.method === 'Runtime.enable') {
          this.onmessage({ data: new Uint8Array([1]) });
          for (let index = 0; index < 4100; index++) this.onmessage({ data: 'null' });
        }
        this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) });
      });
    }
    close() { this.readyState = 3; }
  }
  const result = await observe(config, { now: () => 0, WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, false); assert.equal(result.code, 'browser_js_exception');
  assert.equal(result.transport.invalid_frames, 4096); assert.equal(result.transport.text_frames, 4096);
  assert.equal(result.transport.counters_saturated, true);
  assert.equal(result.transport.matched_responses, 5); assert.equal(result.checks.no_js_exceptions, false);
});

test('a slow fixed connection shares the same original remaining budget without reconnect', async () => {
  let opens = 0, timer;
  class Socket {
    constructor() { this.readyState = 0; opens++; timer = setTimeout(() => { this.readyState = 1; this.onopen(); }, 650); }
    send(raw) { const message = JSON.parse(raw); queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) })); }
    close() { this.readyState = 3; clearTimeout(timer); }
  }
  const result = await observe({ ...config, remaining_ms: 1500 }, { WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, true); assert.equal(opens, 1);
});

test('first invalid or unmatched text presence is retained while Runtime remains pending', async () => {
  for (const invalid of [false, true]) {
    const progress = [], methods = [];
    class Socket {
      constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
      send(raw) {
        const message = JSON.parse(raw); methods.push(message.method);
        queueMicrotask(() => {
          for (let index = 0; index < 3; index++) this.onmessage({ data: invalid ? new Uint8Array([1,2,3]) : JSON.stringify({ method: 'Unmatched.event', params: { raw: 'private payload URL and ID' } }) });
        });
      }
      close() { this.readyState = 3; }
    }
    const result = await observe(config, { now: () => 0, WebSocket: Socket, onProgress: value => progress.push(value),
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
    const key = invalid ? 'invalid_frames' : 'text_frames';
    const retained = progress.filter(value => value.stage === 'runtime' && value.transport[key] > 0);
    assert.equal(retained.length, 1); // Count increments do not create a heartbeat.
    assert.equal(retained[0].transport[key], 1);
    assert.equal(retained[0].transport.sent_requests, 1);
    assert.equal(retained[0].transport.pending_calls, 1);
    assert.equal(retained[0].transport.matched_responses, 0);
    assert.equal(result.transport[key], 3);
    assert.equal(result.ready, false); assert.equal(result.code, 'browser_protocol_timeout');
    assert.equal(result.stage, 'runtime'); assert.deepEqual(methods, ['Runtime.enable']);
    assert.equal(JSON.stringify(progress).includes('private'), false);
    assert.ok(Buffer.byteLength(progress.map(value => JSON.stringify(value) + '\n').join('')) <= 12288);
  }
});

test('a sole initial blank target may transition once to the exact Tasks target within budget', async () => {
  let discoveries = 0, connections = 0;
  class Socket {
    constructor() { connections++; this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) { const message = JSON.parse(raw); queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) })); }
    close() { this.readyState = 3; }
  }
  const result = await observe({ ...config, remaining_ms: 1000 }, { WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: ++discoveries === 1 ? 'about:blank' : config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, true); assert.equal(discoveries, 2); assert.equal(connections, 1);
});
test('foreign redirected and error targets are rejected without connecting or leaking URLs', async () => {
  for (const [url, category] of [[config.origin + '/sign-in?return=private','auth'], ['chrome-error://chromewebdata/','browser_error'], ['https://private.invalid/tasks','other'], [config.origin + '/tasks?private=1','other']]) {
    let connected = false;
    class Socket { constructor() { connected = true; } }
    const result = await observe(config, { now: () => 0, WebSocket: Socket,
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url, webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
    assert.equal(result.ready, false); assert.equal(result.code, 'browser_target_rejected');
    assert.equal(result.observation.location_category, category); assert.equal(connected, false);
    assert.equal(JSON.stringify(result).includes('private'), false);
  }
});
test('a blank transition cannot expire into a fallback target or additional navigation', async () => {
  let clock = 0, connected = false;
  class Socket { constructor() { connected = true; } }
  const result = await observe({ ...config, remaining_ms: 10 }, { now: () => clock, WebSocket: Socket,
    fetch: async () => { clock = 10; return { ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: 'about:blank' }]))] }; } });
  assert.equal(connected, false); assert.equal(result.ready, false);
  assert.equal(result.observation.location_category, 'blank'); assert.equal(result.stage, 'discovery');
});
test('a live redirect after exact discovery is nonready without navigation or payload disclosure', async () => {
  for (const [changes, category] of [[{ auth: true },'auth'], [{ browserError: true },'browser_error'], [{ foreign: true },'other']]) {
    const methods = [];
    class Socket {
      constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
      send(raw) { const message = JSON.parse(raw); methods.push(message.method); queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot(changes) } } : {} }) })); }
      close() { this.readyState = 3; }
    }
    const result = await observe(config, { now: () => 0, WebSocket: Socket,
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
    assert.equal(result.ready, false); assert.equal(result.code, 'browser_target_rejected');
    assert.equal(result.observation.location_category, category); assert.equal(result.checks.document_complete, false);
    assert.equal(methods.includes('Page.navigate'), false);
  }
});

test('a retained startup exception replayed before Runtime enable ACK prevents readiness', async () => {
  const progress = [], methods = [];
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); methods.push(message.method);
      queueMicrotask(() => {
        if (message.method === 'Runtime.enable') this.onmessage({ data: JSON.stringify({ method: 'Runtime.exceptionThrown', params: { exceptionDetails: { text: 'private startup message URL and ID' } } }) });
        this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? { result: { value: snapshot() } } : {} }) });
      });
    }
    close() { this.readyState = 3; }
  }
  const result = await observe(config, { now: () => 0, WebSocket: Socket, onProgress: value => progress.push(value),
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, false); assert.equal(result.code, 'browser_js_exception');
  assert.equal(result.checks.no_js_exceptions, false);
  assert.ok(CHECKS.filter(key => key !== 'no_js_exceptions').every(key => result.checks[key]));
  assert.equal(result.transport.matched_responses, 5);
  assert.equal(methods.includes('Page.navigate'), false);
  assert.equal(JSON.stringify({ progress, result }).includes('private'), false);
});

test('an absent document root yields valid nonready boolean predicates', () => {
  const value = snapshot({ missingDocumentRoot: true });
  const { diagnostics, observation, ...checks } = value;
  assert.equal(value.document_complete, false);
  assert.equal(value.shell_hydrated, false); assert.equal(value.shell_runtime_ready, false);
  assert.equal(validChecks({ ...checks, no_js_exceptions: true }), true);
  assert.equal(value.project_visible, false); assert.equal(value.task_visible, false);
  assert.equal(observation.ready_state, 'loading');
});
test('a null-root nonready snapshot may become ready within the same original budget', async () => {
  let evaluations = 0; const methods = [];
  class Socket {
    constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
    send(raw) {
      const message = JSON.parse(raw); methods.push(message.method);
      const value = message.method === 'Runtime.evaluate' ? snapshot({ missingDocumentRoot: ++evaluations === 1 }) : undefined;
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: value ? { result: { value } } : {} }) }));
    }
    close() { this.readyState = 3; }
  }
  const result = await observe({ ...config, remaining_ms: 1000 }, { WebSocket: Socket,
    fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
  assert.equal(result.ready, true); assert.equal(evaluations, 2);
  assert.ok(CHECKS.every(key => result.checks[key])); assert.equal(methods.includes('Page.navigate'), false);
});
test('evaluation exceptions and malformed values fail closed with distinct fixed codes', async () => {
  const cases = [
    [{ exceptionDetails: { text: 'private evaluation message URL and ID' } }, 'browser_evaluation_exception'],
    [{ result: { value: snapshot() }, exceptionDetails: { text: 'private otherwise ready exception' } }, 'browser_evaluation_exception'],
    [{ result: { value: snapshot() }, exceptionDetails: null }, 'browser_evaluation_exception'],
    [{}, 'browser_readiness_invalid'],
    [{ result: { type: 'undefined' } }, 'browser_readiness_invalid'],
    [{ result: { value: null } }, 'browser_readiness_invalid'],
    [{ result: { value: { raw: 'private malformed payload' } } }, 'browser_readiness_invalid'],
  ];
  for (const [reply, code] of cases) {
    const progress = [], methods = [];
    class Socket {
      constructor() { this.readyState = 0; queueMicrotask(() => { this.readyState = 1; this.onopen(); }); }
      send(raw) { const message = JSON.parse(raw); methods.push(message.method); queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: message.id, result: message.method === 'Runtime.evaluate' ? reply : {} }) })); }
      close() { this.readyState = 3; }
    }
    const result = await observe(config, { now: () => 0, WebSocket: Socket, onProgress: value => progress.push(value),
      fetch: async () => ({ ok: true, body: [Buffer.from(JSON.stringify([{ type: 'page', url: config.origin + '/tasks', webSocketDebuggerUrl: `ws://127.0.0.1:${config.debug_port}/devtools/page/owned` }]))] }) });
    assert.equal(result.ready, false); assert.equal(result.code, code); assert.equal(result.stage, 'evaluation');
    if (code === 'browser_evaluation_exception') assert.equal(result.checks.no_js_exceptions, false);
    assert.equal(methods.filter(method => method === 'Runtime.evaluate').length, 1);
    assert.equal(methods.includes('Page.navigate'), false);
    assert.equal(JSON.stringify({ progress, result }).includes('private'), false);
  }
});
