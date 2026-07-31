import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../public/core.js', import.meta.url), 'utf8');
const context = vm.createContext({
  Date,
  Intl,
  Map,
  Set,
  URL,
  console,
  document: {
    querySelector: () => null,
    querySelectorAll: () => [],
  },
});
vm.runInContext(`${source}
this.sessionSelectorContract = {
  beginSessionMessageSearch,
  sessionMessageMatchIdsForResponse,
  sessionSearchIncludes,
  sessionSearchMatches,
};`, context);

const {
  beginSessionMessageSearch,
  sessionMessageMatchIdsForResponse,
  sessionSearchIncludes,
  sessionSearchMatches,
} = context.sessionSelectorContract;
const sessions = [
  { id: 'current-message-match', title: 'Untitled session', source: 'Remote Hermes', message_count: 6, tool_call_count: 2 },
  { id: 'current-title-match', title: 'Cronjobs planning', source: 'Remote Hermes', message_count: 2, tool_call_count: 0 },
];

const transition = beginSessionMessageSearch(7);
assert.equal(transition.generation, 8);
assert.deepEqual([...transition.matchIds], []);

const accepted = sessionMessageMatchIdsForResponse(8, 8, {
  results: [
    { session_id: 'current-message-match' },
    { session_id: 'unknown-or-older-session' },
    { session_id: 'current-message-match' },
  ],
}, sessions);
assert.deepEqual([...accepted], ['current-message-match']);
assert.equal(sessionSearchIncludes(sessions[0], 'cronjobs', new Set()), false);
assert.equal(sessionSearchIncludes(sessions[0], 'cronjobs', accepted), true);
assert.equal(sessionSearchIncludes(sessions[1], 'cronjobs', new Set()), true);
assert.deepEqual(
  sessionSearchMatches(sessions, 'cronjobs', accepted).map((session) => session.id),
  ['current-message-match', 'current-title-match'],
);

assert.equal(
  sessionMessageMatchIdsForResponse(7, 8, { results: [{ session_id: 'current-message-match' }] }, sessions),
  null,
);
assert.deepEqual(
  [...sessionMessageMatchIdsForResponse(8, 8, {
    error: 'Search unavailable',
    results: [{ session_id: 'current-message-match' }],
  }, sessions)],
  [],
);
