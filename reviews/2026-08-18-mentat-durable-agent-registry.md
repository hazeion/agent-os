# Feature Slice Review: Durable Mentat Agent Registry

Status: Complete
Slice: `mentat-durable-agent-registry`
Date: `2026-08-18`
Review log: `reviews/2026-08-18-mentat-durable-agent-registry.md`

## Slice contract

### Goal

Mentat can create and retrieve persistent Mentat-owned Agents whose identity is
separate from the Hermes runtime/profile binding used to execute work.

### In scope

- Add owner-private SQLite persistence for Mentat Agents and runtime
  configurations.
- Persist Agent identity, display name, declared capabilities, runtime type,
  and a separate adapter-owned runtime binding.
- Support Hermes as the only configurable runtime in this slice.
- Add bounded runtime-neutral create and list API operations.
- Preserve Agents across process restart and the existing private
  backup/restore path.
- Keep `data/agents.json` as heartbeat observations rather than the canonical
  Agent registry.
- Preserve existing Hermes profile, Console, transport, and browser behavior.
- Update architecture, pivot implementation status, changelog, and this review
  record.

### Out of scope

- Next.js/React UI or changes to the legacy frontend.
- Codex/Claude runtimes, concurrent execution, or dynamic routing.
- Generic task dispatch or durable Task/Run/AgentEvent orchestration records.
- Agent editing/deletion, profile auto-import, or Hermes profile mutation.
- Provider credentials, OAuth, arbitrary runtime options, or secret storage.
- Replacing current heartbeat-agent or Managed Agents surfaces.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Mentat Agent identity and adapter-owned runtime configuration are stored separately in owner-private SQLite with additive migration behavior. | Migration/schema and repository tests. | Pending |
| AC-2 | Creating an Agent and Hermes binding is atomic; malformed, duplicate, unsupported, or conflicting input creates no partial rows. | Negative-path and transaction tests. | Pending |
| AC-3 | Created Agents survive a new repository/server instance and the existing private backup/restore round trip. | Restart and backup/restore integration tests. | Pending |
| AC-4 | Public list/create responses expose bounded Mentat identity, runtime type/config identity, and declared capabilities without runtime references, secrets, paths, or arbitrary options. | API and privacy contract tests. | Pending |
| AC-5 | `data/agents.json` remains heartbeat-only; no Hermes profile is auto-imported or mutated, and existing Console/runtime behavior is unchanged. | Regression and architecture tests. | Pending |
| AC-6 | Focused tests, full suite, package/secret checks, browser regression, and two independent adversarial reviews complete with no blocking finding. | Verification and review records below. | Pending |

### Constraints and recovery

- Safety: all state remains project-owned and owner-private; no credential or
  Hermes-core write surface is added.
- Compatibility: migration is additive; existing `agents.json`, Agent Console,
  Hermes profiles, and browser payloads retain their current meaning.
- Rendered behavior: no visible UI change is expected; browser smoke is a
  regression gate only.
- Rollback or recovery: prior binaries continue using the schema-4 Console
  database and ignore the separate Agent registry file. Format-3 backups
  capture both databases as one private consistency unit; restoring format 2
  supplies a canonical empty registry. The feature branch can be removed
  without modifying Hermes state.
- Documentation targets: `ARCHITECTURE.md`, `AGENTS.md`,
  `MENTAT_MULTI_AGENT_PIVOT.md`, `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, and
  `CHANGELOG.md` where applicable.
- Version-control strategy: branch `codex/mentat-durable-agent-registry` from
  `origin/main`; ready PR targets `main`. The primary dirty working copy is not
  used.

### Scope discussion and approval

- Recommendation and rationale: establish durable Mentat-owned Agent identity
  before task dispatch or React UI so later surfaces consume real
  runtime-neutral state rather than Hermes-profile aliases or mocks.
- Alternatives considered: frontend-first would embed temporary/mock state;
  combining registry and dispatch would enlarge migration, authority, and
  rollback risk.
- User decisions: approved creation of the canonical pivot implementation plan
  and instructed implementation of the documented slices. Work is limited to
  the first proposed slice under the one-slice-at-a-time review process.
- Approved at: 2026-08-18.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The shared schema-4 Console database has no Agent/runtime-config tables. | Separate registry schema initialization from empty and existing schema-4 data roots; foreign-key, exact-schema, and repository tests. | Additive durable separation without invalidating the prior Console reader. | Does not prove a second runtime. |
| AC-2 | No atomic Agent creation operation exists. | Invalid IDs/text/capabilities, unsupported runtime, duplicate IDs/bindings, and rollback tests. | Fail-closed validation and no partial writes. | Concurrent load is bounded to local SQLite behavior. |
| AC-3 | Runtime contracts are in-memory only. | Reopen persistence test and private backup/restore integration. | Durability through supported local recovery paths. | Cross-version downgrade remains table-ignoring compatibility. |
| AC-4 | No runtime-neutral Agent API exists. | HTTP create/list contract and canary privacy assertions. | Public payload remains bounded and secret-free. | No rendered management UI in this slice. |
| AC-5 | Legacy heartbeat agents could be confused with canonical Agents. | Existing heartbeat/dashboard suites plus source/route assertions. | Existing meaning and behavior remain unchanged. | Future UI coexistence is deferred. |
| AC-6 | No slice evidence exists. | Focused suites, full suite, package inventory, secret scan, browser smoke, and independent reviews. | Broad regression and release confidence. | Platform CI runs after publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest tests.test_agent_runtime tests.test_agent_runtime_architecture tests.test_private_console_state -v` | macOS, clean `origin/main` checkout | Pass | 46 tests passed before implementation. |
| Repository inspection | `origin/main` at `53c04b0` | Gap confirmed | `mentat_db.py` schema 4 has no canonical Agent tables; `data/agents.json` remains heartbeat storage. |
| `python -m unittest tests.test_agent_registry -v` | macOS, feature branch before implementation | Expected fail | Test module cannot import missing `agent_registry`; the new behavior does not exist. |

### Test discussion and approval

- User questions and decisions: user approved the documented slice sequence and
  instructed implementation to begin after reviewing the proposed Slice 1B
  contract and test strategy.
- Accepted coverage gaps: no new rendered UI, second runtime, remote/hosted
  database, generic dispatch, or destructive Agent operations.
- Approved at: 2026-08-18.

## Implementation record

### Changes

- Added independently versioned `agent-registry.sqlite3` storage with separate
  `mentat_agents` and `agent_runtime_configs` tables, a one-to-one
  Agent/config relationship, and a unique runtime-type/reference binding while
  retaining shared Console schema 4.
- Added `agent_registry.py` with bounded validation, atomic creation, durable
  reads, private binding lookup, and a browser-safe projection.
- Added `/api/orchestration/agents` create/list operations while preserving
  legacy `/api/agents` and `data/agents.json` heartbeat behavior.
- Serialized Agent API reads/writes with the existing durable recovery lock and
  blocked creation while restore state is reserved.
- Added package inventory, architecture, pivot-plan, changelog, and contributor
  documentation.

### Deviations and decisions

- Round 1 review showed that adding the registry to the shared Console database
  as schema 5 contradicted the approved prior-binary rollback guarantee. The
  registry now uses an independently versioned owner-private
  `agent-registry.sqlite3` inside the same atomically restored Console unit;
  the existing Console database remains schema 4.
- General backup format advances from 2 to 3 to carry that separate registry.
  Format 2 remains accepted and materializes a canonical empty registry because
  it predates canonical Agent state.
- The previously unbounded collection now has a transactional 128-Agent cap.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_agent_registry tests.test_agent_runtime tests.test_agent_runtime_architecture tests.test_private_console_state tests.test_dashboard_behaviors tests.test_data_backup_restore tests.test_request_boundary -v` | macOS, Python 3.13 | `0` | 136 passed | Corrected registry, first-create and existing-file identity changes, main/WAL/SHM safety, bounded SQLite errors, separate-schema rollback, genuine interrupted protocol-2 plus format-2/3 recovery, exact Agent-clear previews, semantic corruption, concurrent capacity, handler-level HTTP, legacy Agent, runtime, and request-boundary coverage. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | macOS host, Python 3.13 | `0` | 1113 passed, 4 skipped | Corrected Round 3 full suite. The earlier sandbox attempt on the initial implementation produced seven loopback-bind `PermissionError` results; exact host runs pass. |
| `node --check public/core.js`; `node --check public/app.js`; `node --check scripts/browser_smoke.mjs`; `python -m py_compile agent_registry.py mentat_db.py server.py`; `git diff --check` | Isolated feature checkout | `0` | All pass | JavaScript/Python syntax and whitespace gates. |
| `uv build --out-dir /private/tmp/mentat-1b-final-dist-20260818`; `python scripts/verify_python_artifacts.py /private/tmp/mentat-1b-final-dist-20260818` | macOS host, uv 0.11-compatible build | `0` | Wheel and sdist verified | Exact final artifacts include `agent_registry.py`; private/runtime/test data remain excluded. No generated `uv.lock` remains on the branch. |
| `uv run --with detect-secrets==1.5.0 python scripts/check_tracked_secrets.py` | macOS host | `0` | 0 unreviewed findings | Pinned tracked-file secret scan passed; the initial sandbox attempt could not access the existing host uv cache. |

### Rendered or manual behavior

- No visible UI change is planned. The corrected Round 2 diff passed the
  complete 46-check repository Chromium smoke matrix against an owner-private
  disposable data root on `http://127.0.0.1:8891`
  (`MENTAT_BROWSER_DEBUG_PORT=9334`). The initial implementation's first valid-
  fixture attempt encountered a non-reproducible page-reload timeout while all
  server responses were HTTP 200; both clean-port runs passed.
- An earlier discarded fixture retained repository-public `0644` JSON modes
  after copying. Mentat correctly rejected those files in an external durable
  root; changing only the disposable copies to the required `0600` mode
  produced the valid fixture used above.

## Adversarial review

### Round 1

- Reviewer A (correctness/safety) requested changes with four blocking
  findings: the schema-5 rollback promise was false; existing format-2 backups
  became unrestorable; restore validation did not validate registry semantics;
  and Agent count/list size were unbounded. Reviewer A also identified the
  generated `uv.lock` as non-blocking publication residue.
- Reviewer B (compatibility/product) independently corroborated the schema
  rollback and unbounded-collection findings, requested handler-level HTTP
  contract evidence, and identified the same generated lockfile residue.
- Peer critique corroborated the HTTP evidence gap and both backup findings.
  The reviewers refined the HTTP gap to this endpoint's composition through
  `Handler`; shared origin, content-type, and JSON machinery already had generic
  tests.
- Disposition: all blocking findings were accepted as in-scope. The registry
  moved to a separate database; backup format 3 plus format-2 compatibility and
  registry semantic validation were added; a transactional capacity ceiling
  was added; and handler-level create/list/privacy/error tests were added. The
  generated `uv.lock` was deleted and is not part of the slice.
- Re-review: pending corrected full verification.

### Round 2

- Both reviewers requested changes because the registry opened SQLite WAL/SHM
  sidecars without first applying the main database's no-link, ownership,
  regular-file, and mode checks. Both also found that raw SQLite failures could
  escape the dedicated GET handler without a bounded response.
- Reviewer A additionally found that tying restore-state protocol versioning to
  archive format versioning made genuine interrupted protocol-2 restores
  unresumable after upgrade, and that format-2 previews did not disclose that a
  populated target Agent registry would be cleared.
- Reviewer B additionally found the approved recovery clause still described
  the discarded shared-table design.
- Peer critique corroborated all three unique findings. The documentation issue
  was classified low/non-blocking; protocol-2 resume and exact Agent-clear
  previews were confirmed blocking and within the approved compatibility scope.
- Disposition: all findings accepted. Registry database sets now validate main,
  WAL, and SHM identities before and after open; SQLite errors are translated to
  bounded corrupt/unavailable outcomes; archive and restore-state protocol
  versions are separate; protocol-2 receipts use their legacy private digest;
  and restore previews expose source/target Agent counts plus explicit
  `clear`, `replace`, or `unchanged` registry actions bound into confirmation.
- Re-review: pending corrected full verification.

### Round 3

- Reviewer A approved with no findings after inspecting the full corrected diff,
  documentation, migration behavior, and package inventory. Independent checks
  covered the registry suite, format-2 clearing, protocol-2 resume, sidecar
  read-only behavior, and whitespace validation.
- Reviewer B approved with no blocking findings. The sole low/non-blocking
  recommendation was a regression test that distinguishes identity replacement
  during first registry creation from replacement of an existing registry.
- Disposition: the recommendation was accepted. A first-creation-specific
  identity-change test was added and passes alongside the existing-database
  identity test; no production code changed after reviewer approval.
- Final reviewer verdict: two independent approvals; no unresolved blocking
  findings or reviewer dissent.

## Documentation updates

- Roadmap: `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` records Slice 1B as the active
  in-progress slice and keeps later boundaries provisional.
- Changelog: records the durable Agent/runtime-binding capability and its
  deferred surfaces.
- Architecture/operator docs: `ARCHITECTURE.md`, `AGENTS.md`,
  `MENTAT_MULTI_AGENT_PIVOT.md`, and `PIVOT_README.md` document the ownership,
  privacy, compatibility, and roadmap boundaries.
- Project/session notes: this review log is the persistent resume record.
- Documentation verification: architecture contract tests and `git diff
  --check` pass; independent review is pending.

## Publication gate

- Proposed files: 18 slice-owned files covering the registry adapter, private
  consistency unit and backup/restore integration, API/package wiring, focused
  tests, architecture/roadmap/operator docs, and this review record. No runtime
  data, generated package output, or lockfile is included.
- Branch and base: `codex/mentat-durable-agent-registry` -> `main`.
- Commit message: `feat: add durable Mentat agent registry`.
- PR title: `Add durable Mentat Agent registry and runtime bindings`.
- PR summary: add a bounded owner-private canonical Agent registry; preserve
  legacy heartbeat semantics; integrate exact format-2/3 recovery; expose a
  redacted create/list API; and document the first multi-agent pivot slice.
- Unresolved risks: Windows filesystem behavior remains dependent on platform
  CI; older binaries intentionally ignore the registry and cannot read format-3
  backups; UI management, additional runtimes, and dispatch remain deferred.
- User authorization and scope: implementation authorized; staging, commit,
  push, and ready PR still require a fresh explicit publication approval.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: complete and ready for user acceptance/publication approval.
- Acceptance criteria summary: canonical Mentat-owned Agent identity and private
  one-to-one Hermes binding persist across restart and backup/restore, remain
  separate from heartbeat observations, and are exposed only through bounded
  redacted API records.
- Potential bugs or untested paths: native Windows reparse/mode behavior awaits
  CI; no visible UI was introduced in this slice.
- Remaining reviewer dissent: none. Both final reviewers approved; one
  non-blocking test recommendation was implemented.
- Compatibility/migration/rollback concerns: shared Console schema stays at 4;
  format 2 restores an explicit empty registry and genuine protocol-2 restore
  receipts resume after upgrade; prior binaries ignore the separate registry.
- User decision: pending.
- Next slice authorized: No.
