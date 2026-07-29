# Feature Slice Review: Local/Remote Hermes Connection Experience

Status: Awaiting publication approval
Slice: `local-remote-connection-experience`
Date: `2026-07-26`
Review log: `reviews/2026-07-26-local-remote-connection-experience.md`

## Slice contract

### Goal

Let an operator configure one remote Hermes connection during setup and safely
switch between that remembered remote and local Hermes through the Mentat CLI,
without placing an API-key value in command arguments, browser requests, or the
connection record.

### In scope

- Store the active mode, local selection, one remembered remote definition, and
  a credential-source reference.
- Resolve the remote API key from a named process environment variable or an
  owner-only environment file.
- Migrate the existing schema-v1 embedded credential to an owner-only private
  environment file without losing the selected connection.
- Add interactive and non-interactive local/remote selection to
  `scripts/mentat_setup.py`.
- Add `mentat connection status`, `test`, `use`, and `configure-remote`.
- Probe authenticated remote readiness and capabilities before activation.
- Preserve the previous selection on probe, credential, storage, or
  verification failure; never silently fall back.
- Rotate the opaque connection binding after a real mode or remote-definition
  change.
- Refuse out-of-process CLI connection mutations while the dashboard is
  running.
- Remove API-key values from the dashboard connection request contract.

### Out of scope

- Settings-page connection controls.
- More than one remembered remote endpoint.
- Remote provider/model selection or profile-default mutation.
- Arbitrary Hermes slash-command forwarding.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Setup can select local or configure and select one remote without an API-key CLI value. | Setup unit and CLI parser tests. | Verified |
| AC-2 | Local mode retains the remembered remote and switching back retests it without re-entering endpoint metadata. | Connection store and CLI integration tests. | Verified |
| AC-3 | The API key resolves only from a validated environment variable or owner-only environment file; unsafe, missing, linked, or malformed sources fail closed. | Credential negative-path tests. | Verified |
| AC-4 | Existing schema-v1 records migrate without connection loss and no longer retain the key in the connection record. | Migration and file-permission tests. | Verified |
| AC-5 | Failed probes and failed or unverifiable writes preserve the prior active selection; Mentat never silently falls back. | Rollback, partial-failure, and restart tests. | Verified |
| AC-6 | `mentat connection status`, `test`, `use`, and `configure-remote` provide bounded secret-free behavior and refuse mutation while Mentat is running. | Packaging CLI tests and manual CLI checks. | Verified |
| AC-7 | Dashboard connection requests cannot carry API-key values and all public output remains endpoint- and credential-free. | Server contract and serialization tests. | Verified |
| AC-8 | Existing local and remote transport behavior remains compatible and the repository suite passes. | Focused and full-suite verification. | Verified |

### Constraints and recovery

- Safety: one validated HTTPS origin, loopback-only HTTP, strict credential
  source validation, owner-only secret files, no browser secret transport, and
  no silent fallback.
- Compatibility: read and safely migrate schema-v1 records; preserve the
  current local default when no record exists.
- Rendered behavior: no browser UI change in this slice.
- Rollback or recovery: a failed configuration or selection operation retains
  or restores the exact prior record and credential source. Partial failure is
  explicit and blocks startup/selection rather than choosing another transport.
- Documentation targets: `REMOTE_HERMES.md`, setup/CLI guidance, and this
  review log.
- Version-control strategy: branch
  `codex/remote-operator-experience-roadmap` from `origin/main`; ready PR only
  after the publication gate.

### Scope discussion and approval

- Recommendation and rationale: use one shared connection operation for setup,
  CLI, and server callers; retain one remote; store only a credential reference;
  refuse out-of-process mutation while the dashboard is live.
- Alternatives considered: storing the key in schema-v2 was rejected because
  it would not satisfy the requested secret-source boundary; arbitrary command
  passthrough and multi-remote storage were rejected as broader capabilities.
- User decisions: approved the complete slice and directed the agent to assume
  approval for subsequent implementation questions. The skill's publication
  approval remains a separate mandatory gate.
- Approved at: `2026-07-26`, in this thread.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Setup has no connection mode or remote credential-source inputs. | Setup argument, interaction, and configuration tests. | Setup can perform the intended workflow without secret arguments. | Uses a fake remote client rather than a live host. |
| AC-2 | The schema-v1 record loses remote data when local is selected. | Store and CLI switch round-trip tests. | One remote remains remembered and is probed on reuse. | One remote only by contract. |
| AC-3 | The connection record embeds the API key. | Environment and env-file resolution, ownership, mode, symlink, parsing, and missing-source tests. | Secrets remain server-side and unsafe sources fail closed. | Windows ACL behavior is unit-tested through platform helpers; CI platforms determine live coverage. |
| AC-4 | No schema-v2 migration exists. | Exact v1-to-v2 migration tests with file mode/read-back checks. | Existing operators retain their connection safely. | Does not support records older than v1. |
| AC-5 | Existing rollback covers one record, not a record plus credential source. | Probe/write/verification fault injection. | The prior active selection survives failure and partial failure is explicit. | Power-loss atomicity is bounded by filesystem guarantees. |
| AC-6 | Installed CLI has no connection command. | Parser and command-handler tests plus manual help/status. | Operator commands are present, bounded, and server-liveness aware. | Manual checks do not contact a real remote. |
| AC-7 | Browser routes currently accept `api_key`. | Request allowlist and secret-free response tests. | Browser requests cannot transport a credential. | No Settings UI is added. |
| AC-8 | Current transport assumes `ConnectionSelection.api_key` comes from the record. | Existing focused transport tests and full suite. | Runtime compatibility and regressions are checked. | External Hermes compatibility remains covered by the maintained remote matrix. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest tests.test_remote_hermes tests.test_packaging_cli tests.test_hermes_transport -v` | macOS, Python workspace runtime | Pass | 64 passed, 0 failed, 0 skipped. |

### Test discussion and approval

- User questions and decisions: the user approved the proposed slice contract
  and test strategy without changes.
- Accepted coverage gaps: fake authenticated discovery for focused tests; no
  browser rendering because the slice has no browser UI.
- Approved at: `2026-07-26`, in this thread.

## Implementation record

### Changes

- Replaced the schema-v1 embedded-key record with a schema-v2 connection state
  that retains one remote definition and stores only a credential-source
  reference.
- Added strict environment-variable, external owner-only environment-file, and
  migration-only private environment-file resolution.
- Added automatic schema-v1 migration with an owner-only credential file,
  verified commit, and explicit partial-failure behavior.
- Added shared preview, probe, confirmation, rollback, remembered-remote test,
  and public-safe status operations.
- Added a lifetime server-startup reservation under the shared durable lock so
  offline mutation and schema-v1 migration cannot race a starting/live server.
- Made local connection testing execute a bounded, output-suppressed Hermes CLI
  probe and made public status use one connection snapshot.
- Added `mentat connection status`, `test`, `use`, and `configure-remote`,
  including non-interactive two-step confirmation and live-server mutation
  refusal.
- Extended the setup wizard and setup CLI with local/remote selection and
  credential-source options; no direct key-value argument exists. Every
  changed interactive connection plan requires its own displayed-plan
  confirmation, including when local-file overwrite uses `--force`.
- Removed endpoint, label, and API-key material from browser-side connection
  preview/apply requests.
- Added focused connection, setup, CLI, migration, transport, and documentation
  tests.

### Deviations and decisions

- Kept the existing `remote-hermes-connection-v1.json` filename so installed
  schema-v1 state can be discovered and migrated in place; the document itself
  is versioned as schema 2.
- Retained a trusted internal Python compatibility operation that can accept a
  key from an already-trusted caller and immediately store it in the private
  environment-file boundary. The browser, installed CLI, and setup workflow do
  not expose or call that operation.
- Confirmation tokens intentionally bind the current/proposed connection
  records but not secret bytes. This prevents token output from becoming a
  credential hash oracle; source availability and authenticated capability
  discovery are revalidated when applying.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_remote_hermes tests.test_packaging_cli tests.test_mentat_setup tests.test_hermes_transport tests.test_beta_contract tests.test_data_layout_contract tests.test_trust_support_readiness -v` | macOS, Python workspace runtime | Exit 0 | 107 passed, 0 failed, 0 skipped | Initial implementation and documentation contracts. |
| `python -m unittest tests.test_remote_hermes tests.test_local_server_lifecycle tests.test_packaging_cli tests.test_mentat_setup -v` | macOS, Python workspace runtime | Exit 0 | 93 passed, 0 failed, 0 skipped | Final reviewer-fix regression run, including barrier-controlled startup-first and mutation-first interleavings, cleanup failure injection, live migration refusal, local CLI readiness, status consistency, and interactive connection-plan accept/reject behavior. |
| `python -m py_compile private_state.py remote_hermes.py server.py mentat/cli.py scripts/mentat_setup.py` | macOS, Python workspace runtime | Exit 0 | 5 modules compiled | Syntax/import compilation after reviewer fixes. |
| `git diff --check` | Git workspace | Exit 0 | Pass | No whitespace errors. |
| `python scripts/check_tracked_secrets.py` | macOS, Python workspace runtime | Not run to completion | Skipped | The optional `detect_secrets` module is not installed in this environment; the command failed before scanning. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | macOS, Python workspace runtime | Exit 0 | 818 passed, 0 failed, 4 skipped | Final reviewer-fix state; skips are existing platform-specific Windows tests. |

### Rendered or manual behavior

- No browser UI is in scope.
- `python -m mentat connection --help` shows the four approved subcommands and
  no API-key-value argument.
- `python scripts/mentat_setup.py --help` shows local/remote and
  credential-source choices and no API-key-value argument.
- A temporary non-interactive local setup completed successfully, emitted a
  secret-free unchanged plan, and created only the expected local
  configuration/initialization artifacts.
- `mentat connection status` against a temporary data root returned the
  expected secret-free local selection.
- A real temporary server on loopback port `49432` published its startup
  reservation; a separately invoked confirmed `connection use local` was
  rejected with `connection_change_server_running`, and graceful shutdown
  removed the reservation.
- A real `connection test local` returned only normalized
  `platform=hermes-agent` and `readiness.cli=ok` metadata; Hermes version text
  and its executable path were not returned.

## Adversarial review

### Round 1

Both reviewers independently inspected the raw diff and agreed on:

- **High/blocking:** CLI/setup liveness checks were outside the connection
  transaction, allowing server startup to race a later commit.
- **High/blocking:** automatic schema-v1 migration on nominal reads could write
  connection/credential state while an existing server was active.
- **Medium:** `connection test local` treated the saved local selection as a
  successful health test without probing the supported Hermes CLI.
- **Medium:** public connection status loaded state and selection under two
  locks and could expose a mixed-revision summary.

Fixes:

- Added a dedicated process-lifetime server reservation created under the
  private-state durable lock. Offline confirmations recheck it inside the
  locked commit, and schema-v1 migration refuses while it is live. Deterministic
  tests cover server-first and mutation-first ordering.
- Added a bounded, fixed `hermes --version` local probe with stdout/stderr
  discarded and only a normalized readiness result returned.
- Changed public status to obtain state and resolved selection in one locked
  snapshot.

### Round 2

The compatibility/product reviewer found, and the correctness/safety reviewer
agreed:

- **Medium:** a cleanup exception before `release_mentat_server()` could leave
  the lifetime reservation present in a surviving embedded/test caller.
- **Medium evidence gap:** the first regression test covered both states
  sequentially but did not actually interleave an in-flight mutation and server
  reservation, so this log overstated the evidence.

Fixes:

- Nested cleanup so attachment-GC stop, run cleanup, server close, and runtime
  cleanup are attempted while reservation release remains the outermost
  guaranteed action.
- Added failure injection for run cleanup, server close, and runtime-state
  cleanup.
- Replaced the sequential ordering claim with barrier-controlled thread tests:
  server-first holds the durable lock after publishing its reservation while a
  confirmation waits; mutation-first holds the lock at the in-transaction
  liveness check while startup waits. The observed outcomes are respectively
  blocked mutation, and completed mutation followed by successful reservation.

### Round 3

The correctness/safety reviewer found, and the compatibility/product reviewer
agreed:

- **Medium:** interactive setup displayed the exact Hermes connection plan but
  immediately consumed its confirmation token without asking the operator to
  accept that displayed plan.

Fixes and closure:

- Added a plan-specific interactive confirmation after the liveness check.
  Rejection cancels without calling the confirm operation or creating
  connection state.
- Preserved the non-interactive two-step `--force` gate.
- During closure verification, the compatibility reviewer found that
  interactive `--force` still bypassed the new prompt. Both reviewers agreed
  this was a connection-authority confirmation gap, so interactive changed
  plans now always prompt regardless of local-file overwrite mode.
- Added accept, reject, and interactive-`--force` rejection tests.
- Both independent reviewers verified the final fix and reported no remaining
  fix-specific findings. All blocking, high, medium, and low findings are
  resolved.

## Documentation updates

- Roadmap/operator contract: `REMOTE_HERMES.md` now documents the implemented
  setup, CLI, storage, migration, confirmation, rollback, and no-fallback
  behavior while leaving remote runtime model selection planned.
- Changelog: a dated operator-experience entry records the new workflow and
  migration.
- Architecture/operator docs: `ARCHITECTURE.md`, `DATA_LAYOUT.md`,
  `PRIVACY.md`, `SECURITY.md`, and the first-time-user `README.md` describe the
  relevant boundaries at their appropriate level.
- Project/session notes: this review log.
- Documentation verification: included in the 107-test focused documentation
  contract run and the complete suite.

## Publication gate

- Proposed files:
  `ARCHITECTURE.md`, `CHANGELOG.md`, `DATA_LAYOUT.md`, `PRIVACY.md`,
  `README.md`, `REMOTE_HERMES.md`, `SECURITY.md`, `mentat/cli.py`,
  `private_state.py`, `remote_hermes.py`, `scripts/mentat_setup.py`,
  `server.py`, `tests/test_hermes_transport.py`,
  `tests/test_local_server_lifecycle.py`, `tests/test_packaging_cli.py`,
  `tests/test_remote_hermes.py`, `tests/test_mentat_setup.py`, and this review
  log.
- Branch and base: `codex/remote-operator-experience-roadmap` onto
  `origin/main`.
- Commit message: `feat: add safe local and remote Hermes connection setup`.
- PR title: `Add safe local and remote Hermes connection setup`.
- PR summary: add the setup wizard and installed connection CLI; keep one
  remembered remote with secret-source references; migrate embedded keys;
  probe, confirm, and atomically switch without silent fallback; serialize
  offline changes against server startup; document and test the operator
  workflow.
- Unresolved risks: optional tracked-secret scan unavailable because
  `detect_secrets` is not installed; no live remote host in focused tests;
  Windows ACL behavior remains platform-dependent; power-loss guarantees remain
  bounded by filesystem atomicity; PID reuse can conservatively leave startup
  or mutation blocked until the stale reservation is removed.
- User authorization and scope: implementation is approved; explicit
  publication approval has not yet been requested and remains separate.
- Commit hash: none.
- Ready PR URL: none.

## Outcome review

- Classification: Awaiting publication approval.
- Acceptance criteria summary: AC-1 through AC-8 are verified.
- Potential bugs or untested paths: no live remote-host interoperability run;
  optional tracked-secret scanner unavailable; Windows permission behavior is
  covered by helpers rather than this macOS runtime.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: schema-v1 migration, failed probe,
  failed verification, startup/mutation ordering, and cleanup failure paths are
  covered. Filesystem power-loss behavior and conservative PID-reuse blocking
  remain documented residual risks.
- User decision: explicit stage/commit/push/ready-PR authorization pending.
- Next slice authorized: No
