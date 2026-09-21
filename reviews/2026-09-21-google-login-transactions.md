# Durable Google login transactions

Scope: [Bind and consume durable Google login transactions exactly once](https://github.com/hazeion/agent-os/issues/251).
Baseline: `b2ab24d`. Implement a five-minute, browser-bound, single-use ordinary
login attempt for an already enrolled Google owner. Keep HTTP routes, enrollment,
session issuance and activation outside this slice. Two independent reviews and
passing verification are required before PR publication.

Schema 26 stores bounded disposable attempts, state/browser digests and private
pending nonce/PKCE material. Consume atomically before invoking the fixed
transport; no code retry after failure, crash or replay. Check the exact current
owner/configuration before consumption and after verified exchange. Return only
a private receipt reference, never session authority or generic identity proof.

Snapshot filtering removes attempts and vacuums the copied database. Restore and
startup discard attempts; historical schema24/25 snapshots remain accepted.
Verify concurrency, expiry/capacity/admission, stale configuration/generation,
wrong subject/browser, ambiguous exchange, secret omission, rollback, migration
and private backup/restore. Source contracts are the previously reviewed Google
OIDC and RFC9700 research.

The issue's refined storage contract keeps nonce/verifier in owner-private
pending rows, then erases them before exchange and filters/vacuums all attempts
from snapshots. This replaces the research proposal's memory-only escrow. It
uses an explicit Google-only 16-pending/64-terminal bound plus the shared
authentication-start rate budget; passkey ceremonies cannot start in Google
mode. Startup discards attempts instead of resuming external work.

Independent review found a rollback race: an invocation that failed before
committing consumption could run failure cleanup against a racing winner.
Cleanup now requires this invocation's successful commit. Both reviewers
rechecked the fix with no remaining findings; a regression asserts no cleanup
on rollback and then verifies a valid callback succeeds.

Final focused verification: 14 transaction tests and 54 existing authentication
and forward-migration tests pass. Migration tests retain real schema-25 snapshot
compatibility and verify rollback. Wheel and sdist build and exact inventories
pass; installed-wheel imports verify schema 26. The Windows path-normalized
tracked-secret diagnostic has no new candidates. The ordinary Linux scan
remains a CI gate. All 83 broad private-state/backup tests passed (three skips).

Status: independent code review clean and local verification complete; ready
for PR publication. CI and merge remain required.
