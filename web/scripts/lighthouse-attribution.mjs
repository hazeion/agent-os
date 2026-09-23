// Public performance diagnostics only. Never retain page text, URLs or headers.
function finite(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null; }
function items(value) { return Array.isArray(value) ? value.slice(0, 256) : []; }
function resourceClass(value) {
  try {
    const url = new URL(value);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) return 'external';
    if (url.pathname === '/') return 'document';
    if (url.pathname.startsWith('/_next/static/') && url.pathname.endsWith('.js')) return 'next_script';
    if (url.pathname.startsWith('/_next/static/') && url.pathname.endsWith('.css')) return 'next_style';
    if (url.pathname === '/shell-runtime.js') return 'shell_runtime';
    if (url.pathname === '/owner-session.js') return 'owner_session';
    if (url.pathname === '/api/bridge/health') return 'bridge_health';
    if (url.pathname === '/api/auth/session') return 'session_check';
    return url.pathname.startsWith('/api/') ? 'other_api' : 'other_resource';
  } catch { return 'unknown'; }
}
export function summarizeAttribution(report) {
  const audits = report?.audits ?? {};
  const breakdown = {}; let element = 'unclassified';
  const allowedParts = new Set(['timeToFirstByte', 'resourceLoadDelay', 'resourceLoadDuration', 'elementRenderDelay']);
  const allowedElements = ['p.console-subtitle', 'h1.console-title', 'h1', 'textarea'];
  for (const detail of items(audits['lcp-breakdown-insight']?.details?.items)) {
    if (detail?.type === 'table') for (const row of items(detail.items)) {
      if (allowedParts.has(row?.subpart) && finite(row.duration) !== null) breakdown[row.subpart] = row.duration;
    }
    if (detail?.type === 'node' && typeof detail.selector === 'string') {
      element = allowedElements.find(selector => detail.selector === selector || detail.selector.endsWith(` > ${selector}`)) ?? 'unclassified';
    }
  }
  const requests = items(audits['network-requests']?.details?.items).flatMap(row => {
    const start = finite(row?.networkRequestTime), end = finite(row?.networkEndTime);
    if (start === null || end === null || end < start) return [];
    return [{ resource: resourceClass(row.url), duration_ms: end - start, transfer_bytes: finite(row.transferSize) }];
  }).sort((left, right) => right.duration_ms - left.duration_ms).slice(0, 12);
  const blocking = items(audits['render-blocking-insight']?.details?.items).slice(0, 12).map(row => ({ resource: resourceClass(row?.url), duration_ms: finite(row?.wastedMs), transfer_bytes: finite(row?.totalBytes) }));
  const mainThread = items(audits['mainthread-work-breakdown']?.details?.items).slice(0, 16).map(row => ({
    group: ['scriptEvaluation', 'scriptParseCompile', 'styleLayout', 'paintCompositeRender', 'parseHTML', 'garbageCollection', 'other'].includes(row?.group) ? row.group : 'unclassified', duration_ms: finite(row?.duration),
  }));
  return { lcp_element: element, lcp_breakdown_ms: breakdown, slow_requests: requests, render_blocking: blocking, main_thread: mainThread };
}
