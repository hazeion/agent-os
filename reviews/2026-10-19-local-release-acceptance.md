# Disposable local release acceptance

## Scope and contract

This branch adds a reproducible source-checkout acceptance command. It changes
no production authority, lifecycle, dependency, provider, authentication or CI
behavior. The runner creates its own private temporary home, config, data root,
Hermes directory, vault and browser profile. It never uses owner data or an
active browser profile. Child environments retain process essentials only.
Every lifecycle command names one explicit loopback ephemeral port. The
existing lifecycle `managed_ports` function returns only that configured port;
the live status projection must confirm that exact list.

Only fixed health/read routes, Project creation and unassigned Task creation
are allowed by the runner's HTTP helper. No Agent binding, Run, delegation,
provider or remote activation capability is invoked. Exact Task readback must
retain the created IDs, parent Project, title, unassigned Agent and server-owned
`todo` / `medium` defaults. Runs must remain empty before and after restart.
Offline backup runs only after verified stop. The fixed restore CLI is used
for read-only validation; the runner never submits a confirmation token.

The report is bounded JSON with fixed scenario names, booleans and fixed
failure codes. It omits IDs, paths, logs, backup names and preview tokens.
Temporary state is removed only after the owned launcher, both captured direct
Node/bridge children, listener and optional private Chrome process group have
terminated. Cleanup never signals a discovered PID, port owner or process group.
It only terminates retained Popen handles that it created. Failed cleanup
preserves owned state and reports failure.

## Verification and observations

- This worktree's `npm --prefix web ci --ignore-scripts` completed with zero
  audit vulnerabilities, followed by a successful production standalone build.
- Nine focused tests cover environment isolation, forbidden routes including
  Run control, cleanup timeout, browser failure without stranding the launcher,
  unrelated nonzero exit, pre-stop crash, listener survival, deadline expiry
  and redaction. They pass without real network access.
- A real source-checkout CLI/Next/Chrome run passed fresh setup and creation,
  exact restart durability, isolated browser rendering, stopped-server backup
  and restore-preview validation. Its report confirmed no dispatch, no restore
  confirmation and removed owned state. The follow-up run after process-cleanup hardening also passed all four
  scenarios with owned state removed. It used the TCP-wait diagnostic behavior
  and therefore does not satisfy immediate restart acceptance.
- Browser evidence is a real fresh-profile rendered DOM containing the created
  Project. Creation itself is through real fixed HTTP APIs, not automated
  clicking. The runner does not claim a complete browser interaction journey.
- Successful `mentat stop` terminates Node with status143, which the launcher
  forwards. Only0 or the observed128+SIGTERM convention is accepted, after the
  launcher was verified alive immediately before a successful stop command.
  Arbitrary nonzero exit and an earlier crash fail closed.
- Follow-up runs exposed immediate same-port restart failures from the current
  non-reusing startup bind while prior HTTP connections remain in TIME_WAIT.
  An optional diagnostic mode observes that exact owned port becoming bindable
  for at most 75 seconds before one restart attempt. The default preserves an
  immediate same-port restart attempt and exposes the baseline bug. It does not change ports or retry a
  failed launch. Diagnostic PASS-after-wait cannot satisfy immediate restart acceptance; a
  separately reviewed production fix and exact rerun are required.

This is macOS component acceptance with synthetic public-safe Project/Task
content and existing installed Python requirements. It does not prove a fresh
Python dependency installation, native package installation, Linux pidfd
behavior, production Project provider/work admission, Google/HTTPS owner
activation, physical mobile devices, or actual garage inputs and outputs.
Those gates remain open. This branch must receive two independent reviews
before publication, and must be rerun after integration on its final code.

## Final local checkpoint

Environment: Python3.13.14, Node24.19.0, installed Chrome155.0.8059.80 on
macOS. Nine focused tests pass. The real diagnostic run completed with all
four scenarios passing and owned state removed. Default immediate restart
previously failed with `gateway_port_unavailable`, so this branch retains that
open production gate. No processes from the completed acceptance runs remain
owned by this runner. Independent reviews and an immediate-restart rerun after
the separate production fix are still required.

## Immediate restart integration and cleanup correction

Normal merge head `10f342440acdd20f6d0634df7493bce305a70b51` integrates the
separately twice-reviewed production port fix `7362f851`. On that exact code,
46 focused tests passed and the actual default CLI/Next/Chrome command passed
all four scenarios, with `immediate_restart_acceptance:true`, no dispatch,
no restore confirmation and owned state removed. No diagnostic wait was used.
The bounded report is saved outside the checkout at
`/private/tmp/mentat-local-release-immediate-report.json`.

Independent harness review then found a failure-path gap: children were
captured only after readiness, so an early launcher exit could leave an orphan
bridge unrepresented while cleanup deleted its data. The runner now launches
Mentat in a new private process session and records that owned group
immediately after Popen, before readiness. Stop and cleanup require group
absence, in addition to exact captured child/listener checks. No discovered
PID or group is terminated. A surviving group preserves state and fails the
report even when the launcher is terminal and the public listener closed.
Three new regressions prove early group capture, refusal with a live orphan
group, and preservation of owned files on incomplete cleanup. All 12 focused
harness tests pass. Corrected code `65ed0456d65e425ebb1a0f38a9f41f090735b43e` then passed the
actual default immediate same-port CLI/Next/Chrome journey. All four scenarios
passed with `immediate_restart_acceptance:true`, `owned_state_removed:true`,
`runs_dispatched:false`, `restore_confirmed:false` and
`live_remote_acceptance:false`. There was no diagnostic wait. Its bounded
report is `/private/tmp/mentat-local-release-immediate-corrected-report.json`.
Root and ci_review_two independently cleared the full corrected harness;
ci_review_two also independently ran all 12 harness tests with ResourceWarnings
as errors. This documentation checkpoint changes no tested code.
