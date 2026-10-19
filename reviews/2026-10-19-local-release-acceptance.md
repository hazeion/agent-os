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
