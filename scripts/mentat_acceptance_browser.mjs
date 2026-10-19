// Source-checkout acceptance only. No browser launch, arbitrary eval or navigation.
import { writeSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const CHECKS = Object.freeze(['document_complete','shell_hydrated','shell_runtime_ready','bridge_ready','workspace_exists','heading_correct','viewport_correct','project_selected','project_visible','task_visible','no_js_exceptions']);
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
    const visible = node => {
      if (!node) return false;
      const box = node.getBoundingClientRect();
      if (!box.width || !box.height || box.right <= 0 || box.bottom <= 0 || box.left >= innerWidth || box.top >= innerHeight) return false;
      for (let parent = node; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (parent.hidden || parent.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
      }
      return true;
    };
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
      task_visible: taskText?.textContent.trim() === 'Disposable acceptance Task' && visible(taskText)
    };
  })()`;
}
export function validChecks(value) {
  return value && typeof value === 'object' && Object.keys(value).sort().join(',') === CHECKS.toSorted().join(',') && CHECKS.every(key => typeof value[key] === 'boolean');
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
  let socket, sequence = 1, exceptions = 0;
  const pending = new Map();
  const result = { schema_version: 1, ready: false, code: 'browser_readiness_timeout', checks };
  function call(method, params) {
    if (!['Runtime.enable','Runtime.evaluate','Emulation.setDeviceMetricsOverride'].includes(method)) throw new Error('browser_protocol_failed');
    const id = sequence++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('browser_readiness_timeout')); }, Math.max(1, Math.min(500, remaining())));
      pending.set(id, { resolve, reject, timer });
      socket.send(JSON.stringify({ id, method, params }));
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
        for (const page of pages) {
          if (page.type !== 'page' || typeof page.url !== 'string' || typeof page.webSocketDebuggerUrl !== 'string') continue;
          const url = new URL(page.url);
          if (url.origin !== config.origin || url.pathname !== '/tasks') continue;
          const ws = new URL(page.webSocketDebuggerUrl);
          if (ws.protocol !== 'ws:' || ws.hostname !== '127.0.0.1' || Number(ws.port) !== config.debug_port || !/^\/devtools\/page\/[A-Za-z0-9-]+$/.test(ws.pathname) || ws.search || ws.hash || ws.username || ws.password) throw new Error('browser_protocol_failed');
          endpoint = ws.href; break;
        }
      } catch { /* Discovery is bounded by the original browser wall deadline. */ }
      if (!endpoint) await pause();
    }
    if (!endpoint) return result;
    socket = new Socket(endpoint);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('browser_readiness_timeout')), Math.max(1, Math.min(500, remaining())));
      socket.onopen = () => { clearTimeout(timer); resolve(); };
      socket.onerror = () => { clearTimeout(timer); reject(new Error('browser_protocol_failed')); };
    });
    socket.onmessage = event => {
      if (typeof event.data !== 'string' || Buffer.byteLength(event.data) > 65536) { exceptions++; return; }
      let message;
      try { message = JSON.parse(event.data); } catch { exceptions++; return; }
      if (pending.has(message.id)) {
        const item = pending.get(message.id); pending.delete(message.id); clearTimeout(item.timer);
        if (message.error) item.reject(new Error('browser_protocol_failed')); else item.resolve(message.result || {});
      } else if (message.method === 'Runtime.exceptionThrown') exceptions++;
    };
    await call('Runtime.enable', {});
    await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    while (remaining() > 0 && socket.readyState === 1) {
      const snapshot = await call('Runtime.evaluate', { expression: expression(config), returnByValue: true, awaitPromise: false, timeout: 250 });
      const value = { ...snapshot.result?.value, no_js_exceptions: exceptions === 0 && !snapshot.exceptionDetails };
      if (!validChecks(value)) { result.code = 'browser_readiness_invalid'; return result; }
      Object.assign(checks, value);
      if (CHECKS.every(key => checks[key])) { result.ready = true; result.code = 'ready'; return result; }
      if (exceptions) { result.code = 'browser_js_exception'; return result; }
      await pause();
    }
  } catch { result.code = 'browser_protocol_failed'; }
  finally {
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
  return observe(JSON.parse(raw));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let result;
  try { result = await main(); }
  catch { result = { schema_version: 1, ready: false, code: 'browser_configuration_invalid', checks: Object.fromEntries(CHECKS.map(key => [key,false])) }; }
  // Never wait for a CDP close handshake to release the exact owned helper.
  writeSync(1, JSON.stringify(result) + '\n');
  process.exit(result.ready ? 0 : 1);
}
