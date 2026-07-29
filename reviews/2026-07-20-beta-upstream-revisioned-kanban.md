# Beta evidence: revision-aware Hermes Kanban contract

Status: upstream draft published; Mentat remains fail-closed.

## Why this exists

Remote Mentat delegation cannot use Hermes dashboard routes, dashboard session
tokens, SSH, or remote database files. The required upstream surface is a
capability-advertised API-server contract protected by the same stable bearer
credential as the rest of `/v1`.

## Required upstream contract

- `GET /v1/capabilities` advertises `kanban_api`, contract version `1`, bearer
  authentication, revision checks, durable idempotency, and every fixed path.
- All `/v1/kanban` paths require the configured API-server bearer credential;
  an unkeyed server must advertise the feature as unavailable and reject it.
- Bounded read paths provide board, profile, task, task-detail, run, comment,
  and event records. No path, claim-lock, worker PID, attachment, raw event
  payload, run metadata, credential, or dashboard/session-token field crosses
  the API boundary.
- A task detail response includes a deterministic `kanbanrev_<sha256>` revision
  over the exact safe task snapshot, including its bounded comments, runs,
  events, and dependency state.
- Every state-changing action except create requires that exact revision and is
  checked atomically with the mutation under the Kanban writer lock. A stale,
  malformed, cross-board, or unknown revision fails before the mutation.
- Create and each fixed action require a bounded idempotency key. Reusing a key
  with different operation material fails; a same-operation retry returns a
  fresh authoritative read-back rather than repeating the mutation.
- Fixed actions are limited to Mentat's existing reviewed operations: create,
  assign, comment/reply, promote, block, retry/unblock, and terminate/reclaim.
  Each successful response is an operation-specific post-mutation read-back.

## Verification and release gate

Mentat may recognize this capability only after it is merged upstream, released
in an official Hermes build, advertised by the installed runtime, and verified
again through the authenticated transport. Until then remote Kanban remains
visible but non-actionable.

The implementation must cover auth-before-enumeration, bounded schemas,
revision stability and staleness, cross-board refusal, idempotency replay and
conflict, concurrent mutation rejection, safe event serialization, exact
post-action read-back, local-mode compatibility, and capability advertisement.

## Upstream implementation evidence

- Draft upstream pull request: [NousResearch/hermes-agent#68200](https://github.com/NousResearch/hermes-agent/pull/68200)
- Fork branch: `hazeion:feat/http-revisioned-kanban` at
  `14491d168` after rebasing onto upstream `main` at
  `67e73ae95899c57b9b9134b4b10a2520dffd0a16`.
- Focused Kanban/database suite: 245 tests passed.
- API-server and multiplex regression suite: 212 tests passed.
- Ruff, Python compilation, and whitespace checks passed.
- The worktree had no installed website dependencies, so the Docusaurus build
  was not run locally. The draft remains subject to upstream review and CI.

This is evidence of a proposed upstream capability, not a declaration that
remote Kanban is available. Mentat must require an official released runtime
that advertises this exact capability and independently verify it over the
authenticated transport before enabling any remote Kanban operation.
