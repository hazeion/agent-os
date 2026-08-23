# Feature Slice Review: Codex runtime adapter

Status: Approved for publication; CI pending

Slice: `3a-codex-runtime-adapter`

Date: `2026-08-22`

## Slice contract

### Goal

Add Codex as a real second backend runtime behind Mentat's existing
runtime-neutral contracts without exposing credentials or Codex-owned
references to the browser.

### In scope

- Discover one trusted local Codex CLI executable and launch its App Server
  through fixed arguments and private stdio JSONL. No shell is involved.
- Reuse the operator's existing Codex CLI sign-in. Keep authentication,
  configuration paths, model/provider defaults, and runtime references inside
  the server-side adapter.
- Support fixed default Codex bindings with `run.start`, `run.status`,
  `run.events`, `run.message`, and `run.stop` when the local CLI is available.
- Normalize one Codex thread/turn into Mentat Run status and bounded events.
- Make generic stop verification reconcile the exact canonical Run after the
  runtime confirms interruption.
- Include the adapter in Python and native packages and accept Codex Agent
  bindings in the private backup/restore consistency unit.

### Out of scope

- Agent/provider sign-in UI, API-key entry, model/provider selection, account
  details, or browser access to Codex configuration.
- Hermes/Codex coexistence controls or runtime picker UI; those belong to 3B.
- Runtime approvals, attachments, arbitrary App Server methods, dynamic
  routing, remote Codex hosts, or Vercel infrastructure.
- Agent Registry database convergence; that remains Slice 3C.

### Acceptance criteria

| ID | Observable criterion | Planned evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A missing, unsafe, unauthenticated, or incompatible Codex CLI fails closed without affecting Hermes or Agent Registry reads. | Discovery, registry, and failure tests | Pass |
| AC-2 | The adapter launches only the fixed local stdio command, completes the required initialize handshake, bounds protocol input, and never forwards Mentat/provider secrets to Codex commands. | Process-client and environment tests | Pass |
| AC-3 | Task submission validates the exact Mentat Agent/Task/Run binding, starts one thread and turn, and reports accepted, rejected, or unknown honestly. | Adapter submission tests | Pass |
| AC-4 | Status and events are deterministic, runtime-neutral, private-reference free, and append-only across repeated reads. | Normalization and reconciliation tests | Pass |
| AC-5 | Active message and stop operations bind the exact Codex thread/turn; stop performs canonical post-action readback before success is claimed. | Control and targeted reconciliation tests | Pass |
| AC-6 | Wheel, sdist, native bundle, and private consistency validation include Codex without adding a second authority or credential file. | Packaging and backup tests | Pass |
| AC-7 | Existing Python, Node, browser, and six-run 100/100/100/100 Lighthouse gates remain green. | Local and CI quality gates | Pass locally; CI pending |

### Constraints and recovery

- The adapter uses the stable local App Server stdio transport documented by
  OpenAI. It does not expose a generic JSON-RPC proxy.
- The first binding is the fixed `default` Codex configuration and Mentat's
  configured local workspace. Browser input cannot choose an executable, cwd,
  provider, token, or App Server method.
- Threads and turns request the documented `workspaceWrite` sandbox with
  approval policy `never`. Permission escalation and approval response are not
  advertised in this slice.
- The App Server child receives an allowlisted host environment. Commands it
  launches use Codex's trimmed core environment with default credential-name
  exclusions enabled.
- Protocol timeouts, malformed or oversized JSONL, process exit, and ambiguous
  submission results fail with bounded codes. Mentat never retries an unknown
  submission automatically.
- Runtime thread/turn IDs are stored only as private adapter references. Public
  Run and event projections continue to use Mentat IDs.
- Rollback removes Codex registration and the adapter module. Hermes and the
  existing SQLite authorities remain unchanged.
- Official interface references:
  [Codex App Server](https://learn.chatgpt.com/docs/app-server),
  [shell environment policy](https://learn.chatgpt.com/docs/config-file/config-advanced#shell-environment-policy).

### Scope discussion and approval

- App Server is the documented interface for deep product integration and
  directly supports the runtime operations Mentat needs.
- The active pivot goal provides standing approval for this scope, tests,
  publication, merge, and continuation.

## Test strategy

| Acceptance criterion | Planned evidence | What it proves | Limitation |
| --- | --- | --- | --- |
| AC-1 | Safe executable resolution plus unavailable/auth failure fixtures. | Optional Codex cannot corrupt or block Hermes. | Does not intentionally invalidate the user's real login. |
| AC-2 | Cross-platform fake App Server subprocess exercising handshake, notifications, malformed/oversized lines, timeout, shutdown, and environment capture. | The real process boundary is fixed and bounded. | Uses a deterministic fake protocol peer. |
| AC-3 | Fake-client tests for binding, request order, response validation, and ambiguity. | Exactly one external submission attempt and honest disposition. | No billable live task is required. |
| AC-4 | Repeated thread snapshots with active, completed, interrupted, failed, and incomplete items. | Stable status and append-only normalized events. | Raw Codex content is deliberately omitted. |
| AC-5 | Expected-turn message/interrupt tests plus exact-run lease/readback tests. | Controls cannot cross Run identity and stop is durable. | Approval responses remain unadvertised. |
| AC-6 | Existing artifact verifier and private unit suites with Codex fixtures. | Installed builds and backups understand the runtime. | Codex CLI itself remains an optional host dependency. |
| AC-7 | Focused/full suites, web check, production browser smoke, and Lighthouse CI. | Regression and UI performance protection. | Clean CI is authoritative where local seed data differs. |

### Test discussion and approval

- Standing authorization accepts this strategy.
- Accepted live-test boundary: verify the installed CLI version and login status
  read-only, but do not launch a billable Codex task merely to test plumbing.

## Implementation record

- Added `codex_runtime.py` with trusted executable discovery, a fixed direct
  App Server command, allowlisted child environment, synchronized bounded JSONL
  client, required initialize handshake, server-request denial, and bounded
  process-tree shutdown.
- Added a bounded `account/read` readiness check. Codex capabilities and Agent
  creation fail closed when the CLI is incompatible or the selected provider
  requires authentication and no account is present.
- Added fixed `default` Codex Agent bindings plus start, status, normalized
  events, expected-turn messages, expected-turn interruption, and terminal
  capability reduction. Raw Codex content and runtime references remain
  private.
- Added exact task-dispatch Run leasing and a shared reconciliation path.
  Preview-confirm Stop can page the exact Run through all bounded Codex events
  before it reports a durable result.
- Registered Codex alongside Hermes without changing Hermes transport or data
  authority. Existing Codex Agent records remain readable when the CLI is
  unavailable, while new unavailable bindings fail closed.
- Added private bridge/server runtime shutdown, private backup validation for
  Codex bindings, and Python artifact inventories.

## Verification

- Baseline: `.venv/bin/python -m unittest tests.test_codex_runtime -v` fails
  because `codex_runtime` does not exist. This is the expected pre-implementation
  failure for the approved slice.
- Initial focused run: `.venv/bin/python -W error::ResourceWarning -m unittest
  tests.test_codex_runtime tests.test_run_stop_control
  tests.test_orchestration_service tests.test_agent_registry
  tests.test_private_console_state tests.test_packaging_cli -v`: 156 passed.
- Post-review focused run covering the adapter, stop control, orchestration,
  registry, private state, packaging, runtime contract, architecture, and
  bridge shutdown: 181 passed with `ResourceWarning` promoted to an error.
- Complete discovery run: 1,432 tests ran; 1,426 passed and 5 platform-specific
  tests skipped. The only failure is the known local fixture check because the
  operator's uncommitted `data/projects.json` contains two personal projects
  in addition to the tracked Mentat seed. That user file was not changed or
  staged; clean CI remains authoritative for this fixture.
- Real host probe: Codex CLI 0.144.6 completed the fixed App Server initialize
  handshake; a read-only `account/read` returned an existing account. The probe
  printed booleans only and did not launch a task or expose account details.
- `npm --prefix web run check`: lint, typecheck, and 39 Node tests passed.
- Wheel and sdist built from the staged web runtime and passed the exact Python
  artifact inventory check.
- Production browser smoke passed all routes, responsive layouts, focus/drawer
  behavior, canonical Agent projection, and live SQLite Task/Run projections.
- Lighthouse 13.4.1 with Chromium 152.0.7923.0: all three desktop and all three
  mobile runs scored 100/100/100/100. Desktop LCP ranged from 206 to 254 ms;
  mobile LCP ranged from 1,114 to 1,209 ms; TBT was 0 ms in every run.
- `python -m py_compile` for all touched Python modules and `git diff --check`:
  pass.
- The first PR CI pass found two test-infrastructure issues: fake Codex paths
  were POSIX-only in three Agent Registry tests, and deliberately fake
  credential fixtures lacked the repository secret-scanner annotation. The
  fixtures are now platform-neutral and explicitly allowlisted. The corrected
  Codex and Agent Registry suites passed 53 tests with one expected
  Windows-only skip on macOS.

## Adversarial review

The first adversarial pass requested changes in five areas:

- use the documented `workspaceWrite` request spelling and documented
  thread-only response shape;
- reject any optional response that reports a sandbox downgrade;
- verify protocol and account readiness before capability advertisement or
  Agent creation;
- make runtime closure permanent under concurrent requests; and
- terminate the App Server's owned process tree, not only its parent PID.

All five findings were fixed with regression tests. One reviewer approved the
corrected implementation. The other found three additional boundary issues:
routine registry reads could still trigger a live probe, Windows process-tree
cleanup used a reusable PID, and private backups accepted unusable Codex
bindings. Those paths now use static runtime-type inventory, an exact Windows
Job Object handle, and static Codex binding validation.

Final independent decisions:

- Reviewer 1: Approve. The App Server contract and exact canonical stop
  reconciliation have no remaining scoped blocker.
- Reviewer 2: Approve. Static inventory, exact process ownership, and backup
  validation resolve the remaining findings. Its independent focused run
  passed 81 tests; the Windows-only integration test was correctly skipped on
  macOS.

## Documentation updates

Updated `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `SUPPORT.md`,
`SECURITY.md`, `PRIVACY.md`, `CHANGELOG.md`, and the pivot implementation plan.

## Publication gate

Standing authorization and both final reviewer approvals are recorded. The
slice is published; the corrected CI run will be monitored before merge.

## Outcome review

Pending.
