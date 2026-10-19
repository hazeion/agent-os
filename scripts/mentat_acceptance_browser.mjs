// Source-checkout acceptance only. One fixed owned Tasks navigation; no arbitrary evaluation.
import { writeSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const CHECKS = Object.freeze(['document_complete','shell_hydrated','shell_runtime_ready','bridge_ready','workspace_exists','heading_correct','viewport_correct','project_selected','project_visible','task_visible','no_js_exceptions']);
class ProtocolTimeout extends Error {}
class TransportClosed extends Error {}
class TransportError extends Error {}
const emptyTransport = () => ({ sent_requests: 0, text_frames: 0, invalid_frames: 0, matched_responses: 0, pending_calls: 0, socket_closed: false, socket_error: false, close_code: 0, counters_saturated: false });
export const DIAGNOSTICS = Object.freeze(['project_exists','project_text_matches','project_renderable','project_intersects_viewport','task_exists','task_text_matches','task_renderable','task_intersects_viewport']);
export function configuration(value) {
  if (!value || typeof value !== 'object' || Object.keys(value).sort().join(',') !== 'debug_port,elapsed_offset_ms,origin,project_id,remaining_ms,task_id') throw new Error('browser_configuration_invalid');
  const origin = new URL(value.origin);
  if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.pathname !== '/' || origin.search || origin.hash || origin.username || origin.password
      || !Number.isInteger(value.debug_port) || value.debug_port < 1024 || value.debug_port > 65535
      || typeof value.project_id !== 'string' || !/^[A-Za-z0-9_.:-]{1,80}$/.test(value.project_id)
      || typeof value.task_id !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/.test(value.task_id)
      || !Number.isInteger(value.elapsed_offset_ms) || value.elapsed_offset_ms < 0
      || !Number.isInteger(value.remaining_ms) || value.remaining_ms <= 0
      || value.elapsed_offset_ms + value.remaining_ms > 40000) throw new Error('browser_configuration_invalid');
  return { ...value, origin: origin.origin };
}
export function expression(config) {
  return `(() => {
    const project = [...document.querySelectorAll('main button[data-project-id]')].find(row => row.dataset.projectId === ${JSON.stringify(config.project_id)});
    const task = [...document.querySelectorAll('main li[data-planning-task-id]')].find(row => row.dataset.planningTaskId === ${JSON.stringify(config.task_id)});
    const renderable = node => {
      if (!node) return false;
      const box = node.getBoundingClientRect();
      if (!box.width || !box.height) return false;
      for (let parent = node; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (parent.hidden || parent.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
      }
      return true;
    };
    const intersects = node => {
      if (!node) return false;
      const box = node.getBoundingClientRect();
      return Boolean(box.width && box.height && box.right > 0 && box.bottom > 0 && box.left < innerWidth && box.top < innerHeight);
    };
    const visible = node => renderable(node) && intersects(node);
    const projectText = project?.querySelector('strong');
    const taskText = task?.querySelector('strong');
    return {
      document_complete: document.readyState === 'complete' && location.origin === ${JSON.stringify(config.origin)} && location.pathname === '/tasks',
      shell_hydrated: document.documentElement.dataset.shellHydrated === 'true',
      shell_runtime_ready: document.documentElement.dataset.shellRuntime === 'ready',
      bridge_ready: document.querySelector('[data-bridge-status]')?.dataset.state === 'ready',
      workspace_exists: Boolean(document.querySelector('.projects-tasks-workspace')),
      heading_correct: document.querySelector('#main-content h1')?.textContent.trim() === 'Projects & Tasks',
      viewport_correct: innerWidth === 1440 && innerHeight === 1000,
      project_selected: project?.getAttribute('aria-current') === 'true',
      project_visible: projectText?.textContent.trim() === 'Disposable acceptance Project' && visible(projectText),
      task_visible: taskText?.textContent.trim() === 'Disposable acceptance Task' && visible(taskText),
      observation: {
        ready_state: ['loading','interactive','complete'].includes(document.readyState) ? document.readyState : 'other',
        location_category: location.origin === ${JSON.stringify(config.origin)} && location.pathname === '/tasks' ? 'tasks' : location.href === 'about:blank' ? 'blank' : location.protocol === 'chrome-error:' ? 'browser_error' : location.origin === ${JSON.stringify(config.origin)} && ['/sign-in','/login','/auth','/owner'].includes(location.pathname) ? 'auth' : 'other'
      },
      diagnostics: {
        project_exists: Boolean(project), project_text_matches: projectText?.textContent.trim() === 'Disposable acceptance Project',
        project_renderable: renderable(projectText), project_intersects_viewport: intersects(projectText),
        task_exists: Boolean(task), task_text_matches: taskText?.textContent.trim() === 'Disposable acceptance Task',
        task_renderable: renderable(taskText), task_intersects_viewport: intersects(taskText)
      }
    };
  })()`;
}
export function validChecks(value) {
  return value && typeof value === 'object' && Object.keys(value).sort().join(',') === CHECKS.toSorted().join(',') && CHECKS.every(key => typeof value[key] === 'boolean');
}
export function validDiagnostics(value) {
  return value && typeof value === 'object' && Object.keys(value).sort().join(',') === DIAGNOSTICS.toSorted().join(',') && DIAGNOSTICS.every(key => typeof value[key] === 'boolean');
}
export async function observe(input, dependencies = {}) {
  const config = configuration(input);
  const fetcher = dependencies.fetch || globalThis.fetch;
  const Socket = dependencies.WebSocket || globalThis.WebSocket;
  const now = dependencies.now || (() => performance.now());
  const deadline = now() + config.remaining_ms;
  const remaining = () => Math.max(0, deadline - now());
  const pause = () => new Promise(resolve => setTimeout(resolve, Math.min(100, remaining())));
  const checks = Object.fromEntries(CHECKS.map(key => [key, false]));
  let socket, sequence = 1, exceptions = 0, closing = false, rejectConnection, connectionTimer;
  const pending = new Map();
  const diagnostics = Object.fromEntries(DIAGNOSTICS.map(key => [key, false]));
  const observation = { ready_state: 'unknown', location_category: 'unknown', snapshots: 0, observer_elapsed_ms: 0 };
  const transport = emptyTransport();
  const count = key => { if (transport[key] < 4096) transport[key]++; else transport.counters_saturated = true; };
  const result = { schema_version: 1, ready: false, code: 'browser_readiness_timeout', stage: 'discovery', checks, diagnostics, observation, transport };
  let progressCount = 0, progressBytes = 0, lastProgress;
  const publish = () => {
    const fingerprint = JSON.stringify({ stage: result.stage, text_seen: transport.text_frames > 0, invalid_seen: transport.invalid_frames > 0, response_seen: transport.matched_responses > 0, counters_saturated: transport.counters_saturated, socket_closed: transport.socket_closed, socket_error: transport.socket_error, close_code: transport.close_code, checks, diagnostics, ready_state: observation.ready_state, location_category: observation.location_category });
    if (fingerprint === lastProgress || progressCount >= 16) return;
    const progress = { schema_version: 1, event: 'progress', stage: result.stage, checks: { ...checks }, diagnostics: { ...diagnostics }, observation: { ...observation }, transport: { ...transport } };
    const encoded = JSON.stringify(progress);
    const bytes = Buffer.byteLength(encoded) + 1;
    // Reserve 4KiB for the fixed final record within the parent's 16KiB cap.
    if (progressCount < 16 && progressBytes + bytes <= 12288 && fingerprint !== lastProgress) {
      progressCount++; progressBytes += bytes; lastProgress = fingerprint;
      dependencies.onProgress?.(progress);
    }
  };
  publish();
  const stage = value => { result.stage = value; };
  const rejectPending = error => {
    const items = [...pending.values()]; pending.clear(); transport.pending_calls = 0;
    for (const item of items) { clearTimeout(item.timer); item.reject(error); }
  };
  function call(method, params) {
    if (!['Runtime.enable','Page.enable','Emulation.setFocusEmulationEnabled','Runtime.evaluate','Emulation.setDeviceMetricsOverride','Page.navigate'].includes(method)) throw new Error('browser_protocol_failed');
    if (transport.socket_error) throw new TransportError();
    if (transport.socket_closed || socket.readyState !== 1) throw new TransportClosed();
    const wait = remaining();
    if (wait <= 0) throw new ProtocolTimeout();
    const id = sequence++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); transport.pending_calls = pending.size; reject(new ProtocolTimeout()); }, Math.max(1, wait));
      pending.set(id, { resolve, reject, timer }); transport.pending_calls = pending.size;
      try {
        socket.send(JSON.stringify({ id, method, params })); count('sent_requests');
      } catch {
        clearTimeout(timer); pending.delete(id); transport.pending_calls = pending.size;
        transport.socket_error = true; reject(new TransportError());
      }
      // Fixed stage and transport snapshot are emitted before awaiting this reply.
      publish();
    });
  }
  try {
    let endpoint;
    while (remaining() > 0 && !endpoint) {
      try {
        const response = await fetcher(`http://127.0.0.1:${config.debug_port}/json/list`, { signal: AbortSignal.timeout(Math.max(1, Math.min(500, remaining()))) });
        let size = 0, raw = '';
        if (response.ok) for await (const chunk of response.body) {
          size += chunk.length; if (size > 65536) throw new Error('browser_protocol_failed');
          raw += new TextDecoder().decode(chunk);
        }
        const pages = JSON.parse(raw);
        if (!Array.isArray(pages) || pages.length > 16) throw new Error('browser_protocol_failed');
        const blankPages = pages.filter(page => page.type === 'page' && page.url === 'about:blank');
        if (blankPages.length > 1) { result.code = 'browser_target_ambiguous'; return result; }
        for (const page of blankPages) {
          if (page.type !== 'page' || typeof page.url !== 'string' || typeof page.webSocketDebuggerUrl !== 'string') continue;
          if (page.url !== 'about:blank') continue;
          const ws = new URL(page.webSocketDebuggerUrl);
          if (ws.protocol !== 'ws:' || ws.hostname !== '127.0.0.1' || Number(ws.port) !== config.debug_port || !/^\/devtools\/page\/[A-Za-z0-9-]+$/.test(ws.pathname) || ws.search || ws.hash || ws.username || ws.password) throw new Error('browser_protocol_failed');
          endpoint = ws.href; break;
        }
      } catch { /* Discovery is bounded by the original browser wall deadline. */ }
      if (!endpoint) await pause();
    }
    if (!endpoint) return result;
    stage('connect'); publish();
    if (remaining() <= 0) return result;
    socket = new Socket(endpoint);
    socket.onerror = () => {
      if (closing) return;
      transport.socket_error = true; result.code = 'browser_transport_error';
      const error = new TransportError(); rejectConnection?.(error); rejectPending(error); publish();
    };
    socket.onclose = event => {
      if (closing) return;
      transport.socket_closed = true;
      transport.close_code = Number.isInteger(event?.code) && event.code >= 0 && event.code <= 65535 ? event.code : 0;
      result.code = 'browser_transport_closed';
      const error = new TransportClosed(); rejectConnection?.(error); rejectPending(error); publish();
    };
    socket.onmessage = event => {
      if (closing) return;
      const data = event?.data;
      if (typeof data !== 'string' || Buffer.byteLength(data) > 65536) { count('invalid_frames'); exceptions++; publish(); return; }
      count('text_frames');
      let message;
      try { message = JSON.parse(data); } catch { count('invalid_frames'); exceptions++; publish(); return; }
      if (!message || typeof message !== 'object' || Array.isArray(message)) { count('invalid_frames'); exceptions++; publish(); return; }
      if (pending.has(message.id)) {
        const item = pending.get(message.id); pending.delete(message.id); transport.pending_calls = pending.size;
        clearTimeout(item.timer); count('matched_responses');
        if (remaining() <= 0) item.reject(new ProtocolTimeout());
        else if (message.error) item.reject(new Error('browser_protocol_failed'));
        else item.resolve(message.result || {});
      } else if (message.method === 'Runtime.exceptionThrown') exceptions++;
      publish();
    };
    await new Promise((resolve, reject) => {
      connectionTimer = setTimeout(() => { rejectConnection = undefined; reject(new ProtocolTimeout()); }, Math.max(1, remaining()));
      rejectConnection = error => { clearTimeout(connectionTimer); rejectConnection = undefined; reject(error); };
      socket.onopen = () => { clearTimeout(connectionTimer); rejectConnection = undefined; resolve(); };
    });
    stage('runtime');
    await call('Runtime.enable', {});
    stage('page');
    await call('Page.enable', {});
    stage('focus');
    await call('Emulation.setFocusEmulationEnabled', { enabled: true });
    stage('viewport');
    await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    stage('navigation');
    if (remaining() <= 0) { publish(); return result; }
    const navigation = await call('Page.navigate', { url: config.origin + '/tasks' });
    if (navigation.errorText) { result.code = 'browser_navigation_failed'; return result; }
    if (remaining() <= 0) return result;
    stage('evaluation');
    while (remaining() > 0 && socket.readyState === 1) {
      const snapshot = await call('Runtime.evaluate', { expression: expression(config), returnByValue: true, awaitPromise: false, timeout: 250 });
      if (transport.socket_error) throw new TransportError();
      if (transport.socket_closed) throw new TransportClosed();
      if (remaining() <= 0) throw new ProtocolTimeout();
      const { diagnostics: observedDiagnostics, observation: observedObservation, ...observedChecks } = snapshot.result?.value || {};
      const value = { ...observedChecks, no_js_exceptions: exceptions === 0 && !snapshot.exceptionDetails };
      if (!validChecks(value) || !validDiagnostics(observedDiagnostics) || !observedObservation || Object.keys(observedObservation).sort().join(',') !== 'location_category,ready_state' || !['loading','interactive','complete','other'].includes(observedObservation.ready_state) || !['tasks','blank','browser_error','auth','other'].includes(observedObservation.location_category)) { result.code = 'browser_readiness_invalid'; return result; }
      Object.assign(checks, value);
      Object.assign(diagnostics, observedDiagnostics);
      Object.assign(observation, observedObservation, { snapshots: observation.snapshots + 1, observer_elapsed_ms: Math.max(0, Math.min(40000, Math.floor(config.remaining_ms - remaining()))) });
      publish();
      if (CHECKS.every(key => checks[key])) { result.ready = true; result.code = 'ready'; stage('ready'); publish(); return result; }
      if (exceptions) { result.code = 'browser_js_exception'; return result; }
      await pause();
    }
  } catch (error) { result.code = error instanceof ProtocolTimeout ? 'browser_protocol_timeout' : error instanceof TransportClosed ? 'browser_transport_closed' : error instanceof TransportError ? 'browser_transport_error' : 'browser_protocol_failed'; }
  finally {
    closing = true; clearTimeout(connectionTimer);
    for (const item of pending.values()) clearTimeout(item.timer);
    if (socket && [0,1].includes(socket.readyState)) { try { socket.close(); } catch {} }
  }
  return result;
}
async function main() {
  let raw = '';
  for await (const chunk of process.stdin) {
    if (Buffer.byteLength(raw) + chunk.length > 4096) throw new Error('browser_configuration_invalid');
    raw += chunk.toString('utf8');
  }
  return observe(JSON.parse(raw), { onProgress: value => writeSync(1, JSON.stringify(value) + '\n') });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let result;
  try { result = await main(); }
  catch { result = { schema_version: 1, ready: false, code: 'browser_configuration_invalid', stage: 'discovery', checks: Object.fromEntries(CHECKS.map(key => [key,false])), diagnostics: Object.fromEntries(DIAGNOSTICS.map(key => [key,false])), observation: { ready_state: 'unknown', location_category: 'unknown', snapshots: 0, observer_elapsed_ms: 0 }, transport: emptyTransport() }; }
  // Never wait for a CDP close handshake to release the exact owned helper.
  writeSync(1, JSON.stringify(result) + '\n');
  process.exit(result.ready ? 0 : 1);
}
