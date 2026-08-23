# Feature Slice Review: Optional Vercel capability adapters

Status: Complete

Slice: `4a-vercel-capability-adapters`

Date: `2026-08-23`

Review log: `reviews/2026-08-23-vercel-capability-adapters.md`

## Slice contract

### Goal

Make Vercel a real but optional Mentat infrastructure choice: an operator can
configure one private Vercel connection, create a compatible Agent, run work
through AI Gateway, inspect normalized Mentat Run evidence, safely test the
separate Sandbox and Connect capabilities, and disconnect Vercel without
affecting local, Codex, or Hermes operation.

### In scope

- Add a Mentat-owned provider-connection record to owner-private
  `mentat.sqlite3`; store configuration and credential-source kind, never a
  credential value.
- Add exact preview/confirmation CLI operations to list, configure, test,
  create a compatible Agent for, and disconnect a Vercel connection while the
  server is stopped.
- Add a runtime-neutral Vercel Agent adapter that makes one bounded, fixed-host
  AI Gateway request using the connection's configured model and records only
  normalized Mentat Run/events/usage.
- Add a separate Sandbox adapter whose first allowed operation is a fixed,
  non-persistent Node 24 readiness command with bounded runtime and cleanup.
- Add a separate Connect adapter whose first allowed operation requests one
  configured app-scoped token with an allowlisted scope set, validates it
  server-side, and immediately discards it without returning or persisting it.
- Add a read-only, secret-free Vercel connection projection to the Node Agents
  workspace.
- Preserve backup/restore consistency and the explicit schema-5 compatible-root
  downgrade path.

### Out of scope

- Hosting the local Mentat console or its SQLite database on Vercel.
- Browser credential entry, Vercel sign-in, OAuth consent UI, or returning
  credentials/tokens to Node or the browser.
- Arbitrary Sandbox commands, files, environment variables, network policy,
  persistent workspaces, or browser-selected endpoints.
- Provider-specific Connect actions, arbitrary HTTP passthrough, MCP, durable
  workflows, automatic routing/fallback policy, usage billing reports, or
  shared tool authorization.
- Rebinding or deleting existing Agents when a connection is disconnected.
- A live paid-service smoke test without operator-owned Vercel credentials;
  the shipped explicit test command and deterministic fake-service integration
  tests cover the same bounded adapters.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | With no Vercel connection or credentials, startup, Codex, Hermes, Tasks, Runs, backup, and the Node UI continue to work; Vercel fails closed. | Focused regression suite, full suite, production browser smoke | Pass |
| AC-2 | Configure is an exact preview/confirm operation that stores one validated private connection record without credential values; status exposes only safe fields and capability readiness. | Repository/CLI/secret-canary tests and SQLite inspection | Pass |
| AC-3 | A compatible Vercel Agent can dispatch one exact Task revision through the fixed AI Gateway endpoint and produce a bounded canonical completed/failed/unknown Run with normalized message and usage events, without exposing raw provider payloads. | Adapter, orchestration, repository, bridge, and UI integration tests | Pass |
| AC-4 | Sandbox readiness can run only the fixed Node 24 probe in a non-persistent bounded sandbox and attempts cleanup on every outcome; browser or CLI text cannot become a command. | Fake REST boundary tests for success, timeout, malformed response, and cleanup failure | Pass |
| AC-5 | Connect readiness can request only one configured app-subject connector/scope set; the token is neither returned, persisted, logged, nor included in an exception. | Token-canary tests, response/schema limits, failure-path tests | Pass |
| AC-6 | Disconnect is state-bound, refuses an active Vercel Run, disables only the selected connection, and leaves local/Codex/Hermes Agents and Runs unchanged. | CLI/repository/concurrency regression tests | Pass |
| AC-7 | The Agents workspace renders safe Vercel connection state and declared capabilities with loading, empty, unavailable, and responsive behavior while retaining the Emerald UI and accessibility contracts. | Node contract tests and production browser/computer-use checks at desktop and mobile sizes | Pass |
| AC-8 | Schema migration, format-4 backup/restore, old backup restore, and schema-5 compatible-root export remain validated; an older build never opens schema 9 in place. | Database/private-unit/backup/export tests | Pass |
| AC-9 | Docs explain optional setup and boundaries concisely; Node 24 checks, six Lighthouse audits, and tracked-secret scans pass. | Documentation checks, lint/typecheck/tests, Lighthouse artifacts, secret scan | Pass |

### Constraints and recovery

- Safety: fixed HTTPS hosts and fixed operations; no browser-selected endpoint,
  command, environment name, credential, or token; bounded request/response
  sizes and deadlines; exact state-bound confirmations; no SQLite lock held
  across external calls.
- Compatibility: Python 3.11-3.13, Node 24.19.x, macOS/Windows/Linux, existing
  Codex and Hermes runtime contracts, released backup formats, and local-only
  loopback hosting remain supported.
- Rendered behavior: reuse the current Emerald tokens and compact card/button
  patterns; reserve stable placeholder space; preserve keyboard, narrow-layout,
  reduced-motion, and high-contrast behavior.
- Rollback or recovery: disconnect Vercel to fail closed without touching other
  runtimes. Restore a validated format-4 backup for same-version recovery. Use
  a new schema-5 compatible sibling root for a pre-cutover build; never
  downgrade the authoritative schema-9 root in place.
- Documentation targets: `README.md`, `ARCHITECTURE.md`, `DATA_LAYOUT.md`,
  `MENTAT_MULTI_AGENT_PIVOT.md`, `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`,
  `CHANGELOG.md`, CLI help, and this review log.
- Version-control strategy: focused branch
  `feature/4a-vercel-capability-adapters`, one reviewed slice, ready PR to
  `main`, merge only after all required CI is green.

### Scope discussion and approval

- Recommendation and rationale: use Mentat-owned provider connection records
  and three narrow adapters. AI Gateway is the runtime; Sandbox and Connect
  remain separately testable capabilities rather than becoming Mentat's data
  model or an arbitrary remote execution surface.
- Alternatives considered: hosting the whole console on Vercel would violate
  local-first storage; a Node-to-Python reverse bridge would add a lifecycle
  cycle; the aggregate Python `vercel==0.10.0` package currently pulls a
  `cbor2` source build that fails on this supported macOS/Python 3.13 host
  without Rust. Fixed documented REST boundaries keep the optional path small
  and cross-platform.
- User decisions: Vercel must be a viable optional agent-infrastructure choice;
  Mentat remains decoupled from Hermes; Node 24 is required; current Emerald UI
  and responsive improvements are preserved. The user explicitly authorized
  this slice, future approvals, publication, merge, and continuation through
  the pivot goal.
- Process exception: the user's standing explicit authorization is applied to
  contract and test-strategy approval instead of pausing for another approval
  prompt. Exact publication contents and evidence will still be recorded
  before staging.
- Approved at: `2026-08-23` (standing explicit user authorization, renewed by
  “let’s finish the goal. monitor the github PR and let’s move forward”).

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No Vercel adapter or connection record exists. | Existing runtime/schema/bridge suites before and after; no-config startup/browser smoke. | Optional integration does not become a startup dependency. | Cannot prove every external host outage shape. |
| AC-2 | No canonical provider-connection repository or CLI exists. | Repository validation, exact-token race, CLI output schema, file/DB secret canaries. | Private authority, exact confirmation, and public projection boundaries. | OS process environments remain operator-owned. |
| AC-3 | Runtime registry supports Hermes and Codex only. | Fake HTTPS transport tests plus full orchestration dispatch and canonical event readback. | One request, identity binding, certainty semantics, normalization, and persistence. | Live paid Gateway call requires operator credentials. |
| AC-4 | No Sandbox operation exists. | Injected fake REST transport covering create/command/stop and every partial failure. | Fixed command, limits, and cleanup behavior. | Does not benchmark real provisioning latency. |
| AC-5 | No Connect operation exists. | Injected fake token endpoint with secret canary and malformed/oversize/error responses. | Scoped request and token non-disclosure. | Does not perform provider-specific OAuth consent. |
| AC-6 | No Vercel connection lifecycle exists. | Active-Run disconnect rejection, state-race token invalidation, unrelated-runtime snapshots. | Disconnect isolation and concurrency behavior. | External in-flight provider requests cannot be recalled. |
| AC-7 | UI has canonical Agents but no provider connections. | Strict TypeScript bridge tests, shell-runtime DOM/browser checks at desktop/mobile/high contrast. | Safe response contract and usable rendering. | Pixel identity is not required. |
| AC-8 | Current private DB is schema 8. | Fresh/upgrade/corruption, format-2/3/4 restore, and compatible-root tests. | Forward migration and explicit downgrade remain safe. | No direct schema-9-to-8 downgrade is supported. |
| AC-9 | Docs and performance evidence predate 4A. | Python artifact verification, Node 24 check, lint/typecheck/tests, full suite, six Lighthouse runs, tracked-secret scan. | Packaging, docs, quality, and performance contracts remain intact. | Lighthouse is local deterministic evidence, not WAN latency. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository/worktree inspection | macOS, branch `feature/4a-vercel-capability-adapters` | Pass | User changes remain limited to `data/projects.json`, `data/tasks.json`, `design/mockups/`, `tmp/`, `uv.lock`, `videos/`, and `web/.npmrc`; all are excluded from the slice. |
| Official Vercel documentation review | [AI Gateway](https://vercel.com/docs/ai-gateway), [Sandbox](https://github.com/vercel/sandbox), and [Connect](https://vercel.com/kb/guide/vercel-connect), current through 2026-08-23 | Pass | Fixed Gateway endpoint/authentication, explicit Node 24/non-persistent Sandbox lifecycle, and short-lived app-scoped Connect tokens confirmed. |
| Credential presence check | local process environment | Pass | No Vercel/Gateway credential or Vercel CLI is present; live paid-service validation is unavailable and no secret was read. |
| Focused Python baseline | Python 3.13 on macOS | Pass | 139 tests: 113 passed in the sandbox; the 26 loopback-binding cases were rerun with host permission and all passed (27 bridge tests including bridge process cleanup). |
| Node 24 baseline | `/usr/local/bin/node` 24.19.0 | Pass | `npm run check`: lint, typecheck, and 39/39 Node tests passed. |

### Test discussion and approval

- User questions and decisions: the user wants a viable Vercel path without
  making Vercel mandatory or coupling Mentat back to Hermes, and has authorized
  responsive improvements that preserve the current Emerald design.
- Accepted coverage gaps: no live paid Vercel call can run on this host because
  no credential/project binding is present. The explicit operator test command
  is shipped; deterministic injected-transport integration tests and a public
  model-inventory check provide repeatable CI evidence without billing or
  secrets.
- Approved at: `2026-08-23` under the user's explicit standing authorization.

## Implementation record

### Changes

- Advanced `mentat.sqlite3` to schema 9 with one validated private Vercel
  connection record and no stored credential value.
- Added exact preview/confirm CLI flows for configure, Gateway/Sandbox/Connect
  readiness tests, compatible Agent creation, and disconnect.
- Added a runtime-neutral, one-request AI Gateway adapter with normalized
  message and token-usage events and no automatic retry of ambiguous outcomes.
- Added fixed REST adapters for a non-persistent Node 24 Sandbox probe and one
  app-scoped Connect token canary that is discarded immediately.
- Added the fixed Python/Node provider bridge, safe same-origin route, and
  responsive Emerald connection status cards.
- Extended format-4 backup/restore and schema-5 compatible-root export so
  provider settings move with current Agents while unsupported Vercel state is
  omitted from downgrade artifacts.
- Updated source packaging, schema fixtures, CLI help, operator docs, roadmap,
  repository rules, and changelog.

### Deviations and decisions

- A live provider request remains deliberately unverified because this host
  has no operator-owned Vercel credential or project binding. Injected fixed-
  transport integration tests cover each success and failure contract without
  billing or secret disclosure.
- The aggregate Python Vercel package was not added. Its transitive native
  build failed on the supported Python 3.13/macOS host; the documented fixed
  REST operations are smaller and keep provider schemas inside the adapters.
- Read-only status and preview paths were corrected during self-review so they
  never create or migrate a missing database.
- Inconsistent provider token totals now fail closed instead of becoming
  canonical cost evidence.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| Focused Vercel, coexistence, bridge, migration, and downgrade suites | Python 3.13, deterministic injected transports | Pass | 27 passed | Connection authority, fixed Gateway/Sandbox/Connect requests, cleanup, recovery, secret canaries, three-runtime coexistence, schema 9, and schema-5 downgrade behavior. |
| `/usr/local/bin/npm run check` | Node 24.19.0 | Pass | 44 passed | ESLint, TypeScript, provider bridge, message projection, shell, capability-control, and static-route contracts passed. |
| `/usr/local/bin/npm run build` | Node 24.19.0, Next.js 16.3.2 | Pass | Production build | Default Turbopack build generated all four static routes and fixed API routes. |
| `/usr/local/bin/node scripts/run-next.mjs build --webpack` plus `scripts/prepare-standalone.mjs` | Node 24.19.0, final working tree | Pass | Production fallback build | Final standalone output was rebuilt with the documented webpack fallback because this execution environment blocks Turbopack's local helper process. The repository default remains Turbopack. |
| `uv build` plus `scripts/verify_python_artifacts.py` | Host uv cache, temporary artifact directory | Pass | Wheel and sdist verified | Exact public inventories include the three Vercel modules and provider bridge; private/runtime content remains excluded. |
| `git diff --check` and changed-module `py_compile` | macOS | Pass | No errors | Patch formatting and Python syntax are clean. |
| Vercel focused suite | Python 3.11.15 and 3.13.14 | Pass | 36 passed under each version | The supported oldest and newest Python versions both accept the delegated SSL context and pass every connection, transport, runtime, and secret-containment test. CI supplies Python 3.12. |
| Detached-body and blocked-TLS deadline regressions | Four concurrent Python processes | Pass | 8 passed | Socket publication and direct close remain deterministic under scheduling pressure. |
| `scripts/check_tracked_secrets.py` | `detect-secrets` 1.5.0 | Pass | No unreviewed candidates | Synthetic credential canaries carry only the repository's narrow inline review annotation. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13, disposable clean mirror of the final working tree | Pass | 1,503 passed; 5 skipped | The mirror used committed fixture data and excluded all user-owned worktree edits. Every Slice 4A, bridge, schema, backup, downgrade, packaging, runtime, UI, lifecycle, and platform contract passed. |
| Targeted rerun of configuration tests affected by an earlier environment override | macOS, normal config resolution | Pass | 2 passed | Confirms those transient failures were test-launch configuration, not product regressions. |
| Closure documentation contract tests | macOS, Python 3.11 | Pass | 13 passed | Roadmap and data-layout completion updates satisfy their repository contracts. |
| GitHub Actions runs `32639115496`, `32639115499`, and `32639115500` | Linux, macOS, and Windows; Python 3.11-3.13; Node 24 | Pass | Native artifact smoke, quality gates, and full CI green | Two unrelated Windows test flakes passed on isolated rerun. The corrected Windows TLS deadline regression also passed in the full matrix. |

### Rendered or manual behavior

- Production Chromium smoke passed all four routes, seven responsive sizes,
  loading/empty/error states, current 15-Task and 50-visible-Run projections,
  and Hermes/Codex/Vercel control isolation.
- A final in-app browser walkthrough exercised both refresh controls, current
  Tasks, current Runs, a live timeline open/close, high contrast, the mobile
  drawer, and route navigation. It reported no console warnings or errors and
  no horizontal overflow.
- The walkthrough found and corrected stale Home migration copy. The rebuilt
  Home now reports the operational Agents, Tasks, Runs, and provider bridge.
- Three desktop and three mobile Lighthouse 13.4.1 audits under Chromium
  152.0.7923.0 each scored 100 for performance, accessibility, best practices,
  and SEO. Final desktop LCP was 222-234 ms; mobile LCP was 1.12-1.22 s; TBT was
  0 ms in every run.
- Current machine data was migrated through Mentat's validated schema and Agent
  convergence workflows into the platform data root. A format-4 backup passed,
  and the final private authority retained 15 Tasks, 83 Runs, 0 Agents, and 4
  blobs with SQLite integrity `ok`. Runtime/browser scratch was not copied.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: complete Slice 4A working-tree diff against merged
  Slice 3C on `feature/4a-vercel-capability-adapters`.
- Verification evidence: focused Python/Node suites, production build, schema
  and backup tests, and source inspection.
- Rendered artifacts: Agents provider card and Run-event projection contracts.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-01 | High | Yes | Sandbox used the wrong versioned REST route for a Node 24 runtime. | Yes | Match the official current Sandbox API. |
| A-02 | High | Yes | Existing schema-9 roots were not accepted by Agent-registry migration validation. | Yes | Teach the migration reader the additive schema. |
| A-03 | High | Yes | Stopped-server checks could race a server start before a provider mutation. | Yes | Recheck while holding the shared mutation lock. |
| A-04 | High | Yes | A successful Gateway result was durable but not safely visible in the Run timeline. | Yes | Project one bounded message event only. |
| A-05 | High | Yes | An ambiguous one-shot dispatch had no operator recovery path, permanently blocking disconnect. | Yes | Add state-bound no-retry recovery. |
| A-06 | High | Yes | Sandbox cleanup did not prove the exact created session was stopped, and cleanup failure could be hidden by an earlier probe error. | Yes | Verify exact stopped state and make cleanup failure authoritative. |
| A-07 | Medium | Yes | Per-step HTTP timeouts did not enforce one total wall-clock deadline. | Yes | Carry one absolute deadline across connect/write/read. |
| A-08 | Medium | Yes | Provider exceptions were transformed inside handlers, weakening recursive secret-graph assertions. | Yes | Raise bounded exceptions outside the handling frame and test the full graph. |
| A-09 | Medium | Yes | Persistent status could be read as cached live readiness. | Yes | Expose only configuration/credential presence; reserve `ready` for explicit tests. |
| A-10 | Medium | Yes | Confirmation tokens did not bind the selected data-root identity. | Yes | Include a canonical root digest in every provider confirmation. |
| A-11 | High | Yes | A schema-5 compatible export could retain a Task assigned to an omitted Vercel Agent. | Yes | Reject the incompatible projection instead of creating a dangling assignment. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-01 | Medium | Yes | Provider loading and final states could shift the Agents layout. | Yes | Reserve one stable responsive card area for loading, empty, ready, and errors. |
| B-02 | High | Yes | Coexistence evidence did not exercise Hermes, Codex, and Vercel concurrently through dispatch, reconciliation, bridge projection, and controls. | Yes | Add one explicit three-runtime integration contract. |
| B-03 | Medium | Yes | Known Vercel Agents inherited unsupported message/approval/stop controls from the generic Run card. | Yes | Gate controls by the known canonical Agent's declared capabilities while preserving fail-closed fallback for unknown Agents. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Sandbox contract and cleanup | Corroborated across A-01/A-06 | Approved after correction | Accepted. Official `@vercel/sandbox` behavior and fixed fake-transport tests prove the versioned route, exact session identity, stopped cleanup, and failure precedence. | Corrected route, lifecycle, and tests. |
| Schema, confirmation, and downgrade safety | Corroborated across A-02/A-03/A-10/A-11 | Approved after correction | Accepted. Schema-9 convergence, root-bound confirmations, lock-adjacent stopped checks, and dangling-assignment rejection are covered by deterministic tests. | Updated migration, connection boundary, locks, export, and tests. |
| Gateway certainty, visibility, and recovery | Corroborated across A-04/A-05 | Approved after correction | Accepted. Only a bounded message crosses the bridge; unknown delivery is never retried and requires exact stopped-server recovery. | Added event projection and `vercel recover-run`. |
| Deadline and secret failures | Corroborated across A-07/A-08 | Approved after correction | Accepted. One absolute deadline now bounds HTTPS; recursive exception-graph canaries remain absent. | Reworked transport and failure tests. |
| Honest provider status | Unique A-09 | Approved after correction | Accepted. Read-only state reports `configured` and `credential_present`; only an explicit confirmed test reports `ready`. | Updated repository, CLI, browser projection, UI, tests, and docs. |
| Responsive provider surface | Unique B-01 | Approved after correction | Accepted. A fixed 188px region now covers all provider states at desktop and phone widths without overflow. | Updated CSS, loading markup, and browser smoke. |
| Three-runtime coexistence and controls | Corroborated across B-02/B-03 | Approved after correction | Accepted. Concurrent dispatch/reconciliation and Node/browser fixtures prove isolated identities and capability-scoped controls. | Expanded Python integration, shell runtime, Node tests, and browser smoke. |

### Later review rounds

| Round | Reviewer | Blocking findings | Correction and disposition |
| --- | --- | --- | --- |
| 2 | Correctness and safety | Reject non-string provider IDs; contain provider parsing so exception tracebacks cannot retain credentials or raw responses; use the exact persistence redaction for byte-budget preflight; prevent timed-out DNS work from starting TCP/TLS; require the exact deterministic Vercel result-message provenance at repository and both bridge boundaries. | All five were corrected with adversarial tests. The reviewer continued to the final round. |
| 2 | Compatibility and product | The coexistence fake accepted a Vercel dispatch without the result message required by the real adapter contract. | The integration now emits exactly one deterministic Vercel result while Hermes and Codex retain their independent event behavior. Reviewer response: `APPROVED`. |
| 3 | Correctness and safety | An HTTP/1.1 `Connection: close` response can own the socket after `HTTPSConnection.sock` is cleared, allowing a stalled body read to outlive a timer that closes only the connection. | The transport retains the connected socket, applies the remaining timeout to it, and directly shuts it down on expiry. A detached-socket stalled-body test passes. Reviewer response: `APPROVED`. |
| Final | Compatibility and product | Rechecked the final transport-only correction and complete diff. | Reviewer response: `APPROVED`. |
| 4 | Release gate | Under scheduling pressure, the deadline could expire after connection construction but before the active socket was published to the timer callback. | Cleanup now closes the retained socket, a published TLS socket, or the connection's current socket in that order. Four concurrent regressions pass. |
| 4 | Correctness and safety | Python can detach the raw TCP socket into an `SSLSocket` while a blocking handshake is still hidden from `HTTPSConnection.sock`. | A delegated SSL context disables automatic handshake, publishes the `SSLSocket`, then performs the handshake under the remaining absolute deadline. A detached-raw-socket regression proves only direct TLS-socket closure unblocks it. Reviewer response after correction: `APPROVED`. |
| 4 | Compatibility and product | Python 3.11 reads and writes SSL-context attributes during `HTTPSConnection` construction; the first deadline wrapper did not delegate them. | Non-private reads and writes now delegate to the verified real context. An unmocked constructor regression and the full 36-test Vercel suite pass under Python 3.11.15 and 3.13.14. Reviewer response after correction: `APPROVED`. |
| 5 | GitHub CI | Windows Python 3.12 could observe the timer-closed TLS socket's `OSError` one clock tick before `monotonic()` compared at the deadline, classifying the safe timeout as `unknown`. | The explicit timer-expired event is now authoritative before accepting a connect failure code. A deterministic immediate-timer test covers the Windows ordering. Both reviewers rechecked the correction and responded `APPROVED`. |
| Final | Both independent reviewers | Rechecked the complete final TLS, compatibility, Windows timing, test-canary, and transport delta. | Both reviewer responses: `APPROVED`. |
| Closure | Both independent reviewers | Checked the completion labels, CI rerun evidence, outcome, live-account gap, rollback wording, and 4B+ deferral. | The roadmap's explicit feature-branch exception permits the intended post-merge `Complete` status. Both reviewers responded `APPROVED`. |

### Reverification

- Focused tests: 111 Python adapter/orchestration/repository/coexistence tests,
  30 Python local-bridge tests, and 44 Node tests passed. The final transport
  delta additionally passed all 36 Vercel tests under Python 3.11 and 3.13.
- Full suite: 1,503 passed and 5 expected platform skips in a disposable clean
  mirror of the final working tree.
- Package/render gates: wheel/sdist verification, production build, production
  browser smoke, computer-use walkthrough, and all six perfect Lighthouse
  audits passed.
- Final review: both original independent reviewers returned `APPROVED` on the
  corrected implementation and the docs-only closure diff.

## Documentation updates

- Roadmap: Slice 4A scope and working optional Vercel completion bar are
  recorded; later shared policy/tooling remains deferred as 4B+.
- Changelog: schema 9, connection lifecycle, runtime, readiness, recovery, UI,
  backup, and safety changes are recorded under 2026-08-23.
- Architecture/operator docs: README, architecture, data layout, and repository
  guide explain the optional connection, stopped-server CLI flow, credential
  boundary, explicit readiness, no-retry recovery, and schema-5 downgrade.
- Project/session notes: this review log is the durable Slice 4A evidence.
- Documentation verification: README/config/packaging contract tests passed;
  CLI help was checked against the published commands and credential sources.

## Publication gate

- Proposed files: the Slice 4A implementation, tests, provider Node route and
  bridge, Home status copy, operator/architecture docs, roadmap/changelog, and
  this review log. User-owned `data/projects.json`, `data/tasks.json`,
  `design/mockups/`, `tmp/`, `uv.lock`, `videos/`, and `web/.npmrc` are
  explicitly excluded.
- Branch and base: `feature/4a-vercel-capability-adapters` to `main`.
- Commit message: `feat: add optional Vercel capability adapters`.
- PR title: `Add optional Vercel capability adapters`.
- PR summary: add one private Vercel connection, fixed AI Gateway/Sandbox/
  Connect boundaries, canonical Vercel Runs and recovery, safe provider UI,
  schema-9 recovery/downgrade compatibility, and complete verification.
- Unresolved risks: no live account smoke without operator credentials.
- User authorization and scope: standing explicit authorization recorded above;
  the exact packet above is approved under that standing authorization.
- Implementation commit: `351cc96582377ce37dfbb3731d787de9fa571a73`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/127

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-9 pass.
- Potential bugs or untested paths: no live paid Vercel account request was run
  because this host has no operator-owned Vercel credentials. The explicit
  readiness command and deterministic transport tests cover the bounded path.
- Remaining reviewer dissent: none. Both independent reviewers approved the
  final correction and complete diff.
- Compatibility/migration/rollback concerns: schema 9 requires the current
  build. Disconnect, format-4 restore, and schema-5 compatible-root export are
  verified recovery paths.
- User decision: accepted and authorized for publication and merge.
- Next slice authorized: no concrete 4B slice is defined. The 4B+ roadmap entry
  remains deferred until its own contract is written.
