# Fixed Google exchange and signing keys

Scope: [Bounded fixed-host Google token exchange](https://github.com/hazeion/agent-os/issues/248).
Draft implementation builds on reviewed verifier PR 247. Final acceptance is
blocked by the verifier's merge and the parent owner's integration gates.

## Contract

Only HTTPS Google token/JWKS endpoints, no redirects/proxies/environment account
discovery, bounded response types/bytes and no code retry. One disposable process
per request, two process-wide slots and a ten-second provider-work deadline;
workers receive only fixed operation input and minimal OS environment. Tokens
never enter argv, environment, files, logs, public errors or browser projections.
The worker discards provider access/refresh tokens and returns only a private ID
token; key snapshots remain bounded and respect cache expiry. An unknown kid may
cause one rate-limited key refresh, never another token exchange.

No session, owner, DB, route or activation authority. The eventual caller must
consume a durable one-use transaction before code exchange and enforce enrollment
and owner binding afterward. Frozen/native execution must fail closed until its
worker launch path is explicitly supported; the first Linux host uses Python.

## Verification plan

Use fake fixed-host HTTP responses and real owned test processes, never live
credentials. Verify body/header bounds, no redirect or POST retry, deadlines,
capacity and process cleanup, minimal environment/argv, key cache expiry and
rotation, and integration with ephemeral RSA-signed assertions. Obtain two
independent reviews and resolve findings before push.

## Evidence

Implemented fixed endpoint workers, shared two-worker capacity, owned process
cleanup and deadline handling, bounded HTTP parsing, conservative cache expiry
and rate-limited unknown-key refresh, and actual verifier integration.

All 63 transport/verifier/owner-auth/packaging contract tests pass in the
hash-locked Python 3.13 environment. Two independent security reviewers found
no actionable issues and independently ran the focused transport suites. Tests
use ephemeral signed assertions, fake HTTP and real owned worker processes;
no live provider or credential calls occurred.

Wheel and sdist exact inventories passed. An isolated installed-wheel worker
launch rejected an unsupported operation and was reaped, without network work.
Windows path-normalized tracked-secret diagnostic found no new candidates;
ordinary Linux CI and process-group cleanup remain required platform gates.

Callback transactions, migration, enrollment, owner/session binding and live
provider acceptance remain open under the parent issue. No login-ready claim.
