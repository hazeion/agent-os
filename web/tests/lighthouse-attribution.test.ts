import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Runtime-only MJS diagnostics deliberately have no declaration file.
import { summarizeAttribution } from '../scripts/lighthouse-attribution.mjs';

test('Lighthouse attribution retains bounded timing and fixed resource classes only', () => {
  const result = summarizeAttribution({ audits: {
    'lcp-breakdown-insight': { details: { items: [{ type: 'table', items: [{ subpart: 'elementRenderDelay', duration: 1800 }, { subpart: 'private', duration: 1 }] }, { type: 'node', selector: 'section.home-console > p.console-subtitle', nodeLabel: 'private page text' }] } },
    'network-requests': { details: { items: Array.from({ length: 400 }, () => ({ url: 'http://127.0.0.1:8890/api/private?token=secret', networkRequestTime: 1, networkEndTime: 80, transferSize: 200 })) } },
    'render-blocking-insight': { details: { items: [{ url: 'http://localhost:8890/_next/static/chunks/123.css', wastedMs: 300, totalBytes: 14000 }] } },
    'mainthread-work-breakdown': { details: { items: [{ group: 'scriptEvaluation', duration: 95 }] } },
  } });
  assert.equal(result.lcp_element, 'p.console-subtitle');
  assert.deepEqual(result.lcp_breakdown_ms, { elementRenderDelay: 1800 });
  assert.equal(result.slow_requests.length, 12); assert.equal(result.slow_requests[0].resource, 'other_api');
  assert.equal(result.render_blocking[0].resource, 'next_style');
  assert.equal(result.main_thread[0].duration_ms, 95);
  assert.doesNotMatch(JSON.stringify(result), /private|secret|localhost|127\.0\.0\.1/u);
});
test('missing or malformed attribution never changes gate scores', () => {
  assert.equal(summarizeAttribution(null).lcp_element, 'unclassified');
  const value = summarizeAttribution({ audits: { 'network-requests': { details: { items: [null, { networkRequestTime: Infinity }, { networkRequestTime: 2, networkEndTime: 1 }] } } } });
  assert.deepEqual(value.slow_requests, []);
});
