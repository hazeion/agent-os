import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const start = source.indexOf('function schedulePendingHermesProjectionRefresh()');
const end = source.indexOf('function receiveHermesProjectionPayload(payload)');
assert.ok(start >= 0 && end > start, 'Hermes projection scheduler source is present');

let releaseFirst;
const firstRead = new Promise((resolve) => { releaseFirst = resolve; });
const timers = [];
let homeReads = 0;
let dashboardReads = 0;
const context = vm.createContext({
  Set,
  console,
  state: {
    hermesPendingProjections: new Set(),
    hermesProjectionRefreshTimer: null,
    homeDelegationRefreshInFlight: false,
  },
  window: {
    setTimeout(callback) {
      timers.push(callback);
      return timers.length;
    },
  },
  async refreshHomeDelegations() {
    homeReads += 1;
    if (homeReads === 1) await firstRead;
    return { refreshed: 1 };
  },
  async refresh() {
    dashboardReads += 1;
  },
});

vm.runInContext(`
const HERMES_EVENT_PROJECTIONS = new Set(['sessions', 'agents', 'attention', 'kanban']);
${source.slice(start, end)}
this.contract = {
  applyHermesProjectionRefresh,
  scheduleHermesProjectionRefresh,
};`, context);

context.state.hermesPendingProjections.add('kanban');
const first = context.contract.applyHermesProjectionRefresh();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(homeReads, 1);
assert.equal(context.state.homeDelegationRefreshInFlight, true);

context.contract.scheduleHermesProjectionRefresh(['kanban']);
assert.equal(timers.length, 1);
timers.shift()();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(homeReads, 1, 'overlapping hint does not start an unsafe parallel read');
assert.equal(context.state.hermesPendingProjections.has('kanban'), true);

releaseFirst();
await first;
await new Promise((resolve) => setImmediate(resolve));
assert.equal(timers.length, 1, 'finishing the active read schedules the retained hint');
timers.shift()();
await new Promise((resolve) => setImmediate(resolve));
await new Promise((resolve) => setImmediate(resolve));
assert.equal(homeReads, 2, 'retained hint performs a follow-up Kanban readback');
assert.equal(dashboardReads, 2);
assert.equal(context.state.homeDelegationRefreshInFlight, false);
assert.equal(context.state.hermesPendingProjections.size, 0);
