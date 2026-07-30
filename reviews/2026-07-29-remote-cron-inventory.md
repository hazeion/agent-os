# Feature Slice Review: Remote Hermes cron inventory

Status: Ready for publication
Slice: `remote-cron-inventory`
Date: `2026-07-29`
Review log: `reviews/2026-07-29-remote-cron-inventory.md`

## Slice contract

### Goal

Show cron jobs from the selected remote Hermes connection in Mentat's Home
view, overview count, and Cron Monitor without exposing job instructions,
delivery settings, credentials, filesystem details, or a remote mutation path.

### In scope

- Add an explicit, versioned, bearer-authenticated, read-only job-inventory
  capability and exact `GET /v1/jobs` endpoint advertisement to Hermes.
- Let Mentat request that exact endpoint only after the capability contract
  validates.
- Request enabled and disabled jobs so Mentat can present the complete inventory.
- Normalize only the fields Mentat displays: opaque job ID and ID-based label,
  schedule, enabled state, last and next run timestamps, fixed status, and an
  opaque revision.
- Keep local Hermes cron-file behavior unchanged.
- Use the selected remote inventory for `/api/hermes/crons` and the Home overview
  count.
- Return a bounded, generic unavailable/unsupported result when capability,
  transport, response size, schema, or privacy validation fails.
- Keep all cron creation, editing, deletion, pause, resume, run, and queue
  operations unavailable from Mentat.

### Out of scope

- Remote cron creation, editing, deletion, pause, resume, immediate run, or
  next-tick queueing.
- Returning prompts, skills, delivery destinations, execution output, arbitrary
  upstream metadata, storage paths, or raw upstream responses to the browser.
- Background polling, caching, execution history, or a new cron administration
  interface.
- Reading a remote cron file or accepting an endpoint supplied by browser text.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Hermes advertises a versioned, API-key-required read-only jobs inventory at the exact `GET /v1/jobs` path. | Capability, authentication, safe-snapshot, and endpoint tests. | Pass |
| AC-2 | A selected remote connection returns active and disabled jobs through `/api/hermes/crons`, with correct counts and only browser-safe fields. | Remote client, real Hermes-created job, and server payload tests. | Pass |
| AC-3 | Missing or wrong capabilities and malformed, oversized, duplicate, secret-reflecting, or private-path-shaped responses fail closed before unsafe data reaches the browser. | Adversarial adapter, response-bound, no-follow, and request-call tests. | Pass |
| AC-4 | Local cron inventory behavior and the read-only, queue-disabled contract remain unchanged. | Existing cron trigger tests and explicit local selection coverage. | Pass |
| AC-5 | Home's scheduled-cron count uses the selected remote inventory, while Cron Monitor renders the jobs without a new mutation control. | Overview unit test, rendered browser check, and browser smoke suite. | Pass |
| AC-6 | Documentation describes remote inventory as implemented and mutations as deferred. | Mentat and Hermes documentation diffs plus full regression suites. | Pass |

### Constraints and recovery

- Safety: the remote client has no generic request method; only an advertised
  exact authenticated read is added. Normalize from the raw response into a
  small allowlist and reject the complete snapshot on schema or privacy
  violations.
- Compatibility: older remote Hermes servers degrade to an unsupported empty
  inventory; local mode continues reading the local store.
- Rendered behavior: reuse the existing Home and Cron Monitor components and
  preserve disabled queue controls.
- Rollback or recovery: revert the two feature commits. Older Mentat remains
  compatible with the added Hermes advertisement, and newer Mentat fails closed
  against older Hermes.
- Documentation targets: `ARCHITECTURE.md`, `REMOTE_HERMES.md`, `CHANGELOG.md`,
  and this review log.
- Version-control strategy: isolated Mentat branch
  `codex/remote-cron-inventory` from `origin/main`; isolated Hermes branch
  `codex/cron-inventory-capability` from its `origin/main`; one focused commit
  and PR per repository after verification and review.

### Scope discussion and approval

- Recommendation and rationale: add the smallest read-only contract on both
  sides. Mentat cannot safely infer support from an unadvertised route, and
  Hermes should not grant broader `jobs_admin` authority for inventory.
- Alternatives considered: calling the unadvertised route was rejected because
  it bypasses capability negotiation; reading remote files was rejected because
  it crosses the storage boundary; enabling `jobs_admin` was rejected because
  Mentat does not need mutation authority.
- User decisions: the user asked to fix the missing remote cron inventory and
  previously authorized all implementation slices and questions while keeping
  security and secret protection foremost. This standing instruction is
  recorded as the explicit process exception for contract, test-strategy, and
  publication approvals; no scope beyond read-only inventory is inferred.
- Approved at: `2026-07-29`, by standing user authorization in this task.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Hermes exposes `/api/jobs` but does not advertise a safe inventory contract. | Extend the capability endpoint test. | Exact method/path, version, completeness, read-only semantics, and API-key requirement are explicit. | Does not deploy the remote host. |
| AC-2 | Mentat always reads the local cron file. | Add remote client normalization and selected-transport server tests. | Remote jobs and counts reach the existing payload with an allowlisted shape. | Uses deterministic fake transport data. |
| AC-3 | No remote jobs schema boundary exists. | Cover wrong endpoint/version, missing capability, excessive rows, invalid IDs/timestamps/types, duplicate IDs, secret/path reflection, and transport errors. | Unsafe or incompatible responses fail closed without follow-on reads or reflected data. | Cannot enumerate every possible hostile Unicode string. |
| AC-4 | Only local-mode tests exist. | Preserve existing `test_cron_trigger.py` checks and add explicit local selection coverage. | Local users and fail-closed queue behavior do not regress. | File-permission behavior remains platform-specific. |
| AC-5 | Overview calls the local reader directly. | Add overview selected-inventory unit test plus browser smoke/manual inspection. | Home count and both existing render surfaces use the selected source. | Browser check does not contact the user's live remote server. |
| AC-6 | Docs call remote cron inventory deferred. | Update and inspect focused docs; run project contract tests. | Operator and architecture guidance matches the implementation boundary. | Does not update external Hermes deployment docs unless required by its tests. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest` focused remote and cron tests | Mentat isolated worktree | 35 passed | Existing local and remote transport behavior was green before implementation. |
| Initial focused Hermes test attempt | Hermes isolated worktree | Environment setup required | The isolated worktree did not yet have pytest/aiohttp. A project-local `.venv` was created before implementation testing. |

### Test discussion and approval

- User questions and decisions: no additional question was required because the
  user already authorized all slices and test decisions, with security as the
  primary constraint.
- Accepted coverage gaps: live remote deployment verification requires the
  remote Hermes host to be updated and restarted; deterministic contract tests
  and local rendered checks will precede publication.
- Approved at: `2026-07-29`, by the same standing user authorization.

## Implementation record

### Changes

- Hermes advertises a complete version-one `GET /v1/jobs` contract only when
  API-key authentication, cron support, and a no-follow file-open primitive are
  available.
- Hermes reads `jobs.json` through a strict 2 MiB snapshot reader that never
  creates directories, changes permissions, repairs data, follows links, or
  opens the mutation lock file.
- Hermes projects at most 128 jobs into a 256 KiB response. It publishes only
  safe IDs, `Cron job <id>` labels, normalized schedules, enabled state, run
  timestamps, a fixed status, and an opaque revision.
- Mentat validates the exact capability, limits, endpoint, response envelope,
  counts, labels, IDs, schedules, timestamps, statuses, and revisions before
  using the inventory.
- `server.py` selects the local or remote authority under the existing
  connection lock. The Home count and Cron Monitor use that selected source.
- All cron mutations remain unavailable.

### Deviations and decisions

- The standing authorization is an explicit exception to the workflow's usual
  per-gate pause. All safety, verification, adversarial-review, and evidence
  requirements remain in force.
- The first draft reused Hermes's broad Jobs API response. Review found that it
  could expose prompts and other private fields, so it was replaced with a
  separate public projection.
- Stored Hermes names are not published. Older jobs may have copied prompt text
  into the name field, so the public contract uses an ID-based label.
- Hosts without a race-safe no-follow file-open primitive do not advertise this
  capability. They keep the existing graceful-degradation behavior.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_remote_cron_inventory tests.test_cron_trigger tests.test_remote_hermes -v` | Mentat isolated worktree | 0 | 52 passed | Exact capability, fail-closed schema, connection binding, local behavior, and queue boundary. |
| `.venv/bin/python -m pytest -q tests/cron/test_jobs.py` | Hermes isolated worktree | 0 | 145 passed | Includes missing, legacy, corrupt, symlinked, and missing-`O_NOFOLLOW` snapshot cases. |
| `.venv/bin/python -m pytest -q tests/gateway/test_api_server.py::TestCapabilitiesEndpoint tests/gateway/test_api_server_jobs.py` | Hermes isolated worktree | 0 | 52 passed | Includes real prompt-derived stored name, authentication, capability, bounds, and API regression cases. |
| Python compilation and `git diff --check` | Both isolated worktrees | 0 | Pass | No syntax or whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | Mentat isolated worktree | 0 | 895 passed, 4 skipped | Skips are existing native Windows-only cases. |
| `.venv/bin/python -m pytest -q tests/cron/test_jobs.py tests/gateway/test_api_server.py tests/gateway/test_api_server_jobs.py` | Hermes isolated worktree | 0 | 432 passed | Existing aiohttp `NotAppKeyWarning` warnings only. |

### Rendered or manual behavior

- An isolated remote fixture rendered one active and one paused job on Home and
  in Cron Monitor.
- Home's scheduled-work count matched the two-job inventory.
- Cron Monitor showed no enabled queue controls and kept the read-only notice.
- `scripts/browser_smoke.mjs` passed against the isolated server.

## Adversarial review

### Round 1 packet

- Diff reviewed: uncommitted isolated Mentat and Hermes branch diffs.
- Verification evidence: focused Mentat and Hermes suites plus rendered checks.
- Rendered artifacts: isolated Home and Cron Monitor fixture.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| RCI-1 | High | Yes | The broad `/api/jobs` response could expose prompts, paths, delivery data, and prompt-derived names. | Yes | Add a dedicated public projection and prove private data stays out. |
| RCI-2 | Medium | Yes | JSON `true` could pass version checks because Python treats it like `1`. | Yes | Require exact integer types. |
| RCI-3 | Medium | Yes | Status accepted arbitrary prose. | Yes | Use a closed status set. |
| RCI-4 | Low | No | Cron validation accepted a one-field expression. | Yes | Require five or six fields. |
| RCI-5 | High | Yes | Hermes-created jobs can store prompt text as their name. | Yes | Never publish stored names; use `Cron job <id>`. |
| RCI-6 | Medium | Yes | The normal loader could repair or create files during a read-only GET. | Yes | Add a strict zero-write snapshot reader. |
| RCI-7 | Medium | Yes | A zero fallback for missing `O_NOFOLLOW` could follow Windows links. | Yes | Fail closed and suppress the capability without a positive no-follow primitive. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| RCC-1 | Medium | Yes | The first client schema rejected Hermes's supported legacy string schedules. | Yes | Move normalization into the Hermes-owned projection and support string plus structured forms. |
| RCC-2 | Medium | Yes | The review log had not yet recorded implementation evidence. | Yes | Complete this log before publication. |
| RCC-3 | Low | No | A remote health callback change had no effect on remote health output. | Yes | Revert that unrelated callback change. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Broad response and legacy schedule mismatch | Corroborated by both reviewers | Both requested a Hermes-owned projection. | Accepted. Dedicated `/v1/jobs` leaves `/api/jobs` unchanged. | Yes |
| Prompt-derived names | Unique security finding | Reviewer required a real `create_job(name=None)` test. | Accepted. Stored names are never read into the projection. | Yes |
| Read-only GET mutating storage | Unique security finding | Reviewer required zero-write missing/repairable cases. | Accepted. New snapshot reader avoids every repair/write path. | Yes |
| Missing Windows no-follow primitive | Unique security finding | Reviewer required fail-closed behavior or a native safe open. | Accepted. Capability and endpoint fail closed when unsupported. | Yes |
| Type, status, schedule, and count checks | Corroborated schema hardening | Reviewers requested adversarial cases. | Accepted. Exact field and type checks cover these cases. | Yes |
| Unrelated health callback | Unique product finding | Compatibility reviewer marked nonblocking. | Accepted. The callback diff was reverted. | Yes |

### Reverification

- Focused tests: 52 Mentat, 145 Hermes cron, and 52 Hermes API tests passed.
- Full suite: 895 Mentat tests passed with 4 skips; 432 relevant Hermes tests
  passed.
- Final review gate: both independent reviewers reported no remaining
  actionable findings.

## Documentation updates

- Roadmap: remote cron inventory decision recorded in `ROAD_TO_BETA.md`.
- Changelog: implementation and safety boundary recorded in `CHANGELOG.md`.
- Architecture/operator docs: `ARCHITECTURE.md` and `REMOTE_HERMES.md` now
  describe the selected-source and remote projection contract. Hermes's API
  guide documents `/v1/jobs`, limits, authentication, labels, and the separate
  admin endpoint.
- Project/session notes: not part of this bug-fix slice.
- Documentation verification: `git diff --check` and the full suites passed.

## Publication gate

- Proposed files: the reviewed Mentat and Hermes diffs only.
- Branch and base: Mentat `codex/remote-cron-inventory` → `main`; Hermes
  `codex/cron-inventory-capability` → `main`.
- Commit message: `Add safe remote cron inventory` in Mentat and
  `Add read-only cron inventory endpoint` in Hermes.
- PR title: matching focused titles above.
- PR summary: add one exact read-only remote inventory path while keeping
  prompts, stored names, paths, output, credentials, and all mutations out.
- Unresolved risks: the remote Hermes host must install/restart onto the Hermes
  capability commit before Mentat can consume its job inventory.
- User authorization and scope: standing authorization recorded above; limited
  to the reviewed read-only inventory slice.
- Commit hash: recorded by the Git commit that contains this review log.
- Ready PR URL: recorded in the publication handoff after GitHub creates it.

## Outcome review

- Classification: Successful after review-driven hardening.
- Acceptance criteria summary: AC-1 through AC-6 pass.
- Potential bugs or untested paths: no live upgraded remote deployment was
  available; deterministic endpoint, transport, server, and rendered tests
  cover the contract.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: deploy Hermes first, then Mentat.
  Reversing the order is safe but Mentat will show the older host as
  unsupported until Hermes is upgraded. Reverting either focused commit returns
  the prior graceful-degradation behavior.
- User decision: standing authorization covers publication of this reviewed
  read-only slice.
- Next slice authorized: No
