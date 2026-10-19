# Disposable local release acceptance

On macOS or Linux, run `python scripts/mentat_acceptance.py` from a source checkout after installing
its Python requirements and building its own dashboard with
`npm --prefix web ci --ignore-scripts` and `npm --prefix web run build`.
This checks a fresh data installation. Dependency installation and native
packaging qualification are separate gates.

The runner creates a private temporary home, config, Hermes directory, vault,
data root and browser profile. It inherits process essentials only, never owner
credentials or integration settings. It uses the real fixed `mentat` CLI and
loopback Next gateway. No Agent is assigned and no Run or delegation is started.

Required scenarios:

1. Setup an absent data root through the CLI. Start the built dashboard, observe
   both gateway and bridge readiness, and read the real Projects & Tasks page.
2. Create one disposable Project and one unassigned Task through their existing
   fixed HTTP capabilities. Read exact IDs and fields back. Check Runs stay empty.
3. Stop through the CLI. Require the owned launcher to exit and the listener to
   close. The two direct owned gateway/bridge processes must also be gone. Restart, then require the exact Project/Task to survive.
4. Stop again before backup. Create a backup with the CLI and validate it with
   the read-only restore preview. Never confirm a restore or export.
5. Optionally render the original `/tasks` landing with a fresh headless Chrome
   profile at a fixed 1440×1000 desktop viewport. The fixed sibling Node24 helper
   observes only that owned loopback tab. Within the original 40-second wall
   deadline it requires a complete hydrated shell, ready bridge, the selected
   exact created Project and actual visible Project/Task rows bound to their
   canonical IDs and exact titles. Creation remains through fixed HTTP APIs.

Success emits a bounded JSON report containing fixed scenario names and
booleans, capped numeric counters and closed categories/failure codes only. Raw process output, private paths, IDs and restore tokens are
never printed. Failure emits a fixed phase/code and exits nonzero. Temporary
files are removed only after the owned launcher, its private process group and
listening socket have closed. The group is recorded before readiness so early
startup failures cannot hide an orphan bridge. The runner never kills a process found by a port number or PID file.
A failed cleanup preserves temporary state and reports that fact.

This local synthetic journey does not qualify the Linux pidfd boundary, native
artifacts, production Project execution, provider authentication, Google login,
HTTPS remote activation, physical mobile devices, or the real garage journey.

On this branch, a successful CLI stop makes Node exit with status 143. The
launcher forwards that status. The runner accepts 143 only after observing the
launcher alive before the stop, a successful stop result and full owned-process
cleanup. An earlier crash or a different nonzero exit fails acceptance.

Before the reviewed POSIX repair, the non-reusing startup port check could reject
immediate same-port restart while previous HTTP connections remained in TCP TIME_WAIT. After proving
the listener and owned processes stopped, the optional `--diagnostic-port-wait` run waits at most 75 seconds
for that exact port to become bindable, then makes one restart attempt. It does
not silently change ports or retry a failed launch. The default run attempts immediate same-port restart.
A successful diagnostic run explicitly reports `immediate_restart_acceptance: false`
and does not satisfy release restart acceptance.

The reviewed POSIX preflight repair is integrated on this branch. The default
startup/restart phases have passed in recorded local runs; final browser acceptance
remains open. The TIME_WAIT discussion retains the baseline diagnostic distinction.

The browser step uses CDP readiness rather than `--dump-dom`, virtual time or
Chrome's natural CLI exit. A diagnostic instrumented run produced actual rows
and hydration markers before its process-exit timeout; the earlier
uninstrumented failure emitted no DOM, so their underlying causes are not
claimed identical. Readiness never falls back to API responses or hidden text.
The runner stops only its retained Chrome/helper handles after readiness and
requires both process groups and the allocated debug listener absent before
counting browser success or proceeding to offline backup. A failed stop reuses
one original 15-second cleanup window; final cleanup cannot grant another.

The runner and `scripts/mentat_acceptance_browser.mjs` are source-checkout tools,
not installed package commands. Keep the fixed regular helper beside the runner
when copying a source archive. A missing or linked helper refuses before Chrome
launch. The sole initial Tasks navigation is the fixed Chrome startup URL.
CDP methods are fixed Runtime/Page enable, focus emulation, desktop metrics
and read-only evaluation. No CDP navigation method, arbitrary evaluation,
response-body reading, provider or Run control is exposed. Loopback listener ownership uses `lsof` plus
the retained Chrome process group. No raw DOM, URL, debugger token or exception
payload is included in reports.

Browser diagnostics stream bounded, changed-only boolean snapshots so the
original 40-second timeout can retain the last complete observation. Separate
Project/Task existence, exact-text, CSS renderability and viewport-intersection
flags explain a failed visibility check; they never satisfy a success check.
At most 16 progress records use 12 KiB, reserving 4 KiB for one final record.
The parent reads at most 16 KiB without changing the child's stdout offset.
Success still requires the final typed ready result, exit zero, all eleven
checks and receipt before the original parent deadline. Progress or an
incomplete trailing record cannot grant success. Cleanup rules remain unchanged.

Prior failed runs remain recorded in focused reviews and preserved reports.
Their later process absence or a different startup contract does not change
those outcomes. The current direct-startup contract has only mock verification
until a separately authorized actual run is recorded.

Chrome starts once at the configured local origin's exact `/tasks` URL. After
verifying its loopback CDP listener/group, discovery requires one exact owned
Tasks page. A sole initial blank transition may wait within the original
budget; multiple pages, foreign URLs, auth redirects and browser errors fail
closed. There is no fallback target, CDP navigation, reload or retry. Fixed
Runtime/Page/focus/metrics setup now happens after navigation starts, and all
eleven live document, identity, visibility and readiness checks remain required.
Progress includes fixed ready-state/location categories, snapshot count and
observer-relative milliseconds; counters/time do not trigger a heartbeat.
The parent's Chrome-spawn deadline remains authoritative.

The exception predicate covers retained/replayed and subsequently observed
Runtime exception events and evaluation failures. Runtime's retained storage can
be evicted or cleared, so this does not claim exhaustive startup-error history.
A replayed startup exception before the enable acknowledgement is tested to
prevent readiness; raw exception payloads remain omitted.

After waiting for owned browser/helper leaders, cleanup may observe their groups
and the debug listener settling within the same existing 15-second window.
It never grants a fresh window, resends a stop, or signals a discovered PID.
Listener probes use only remaining time and require explicit connection refusal;
an in-progress or unrelated network error does not prove the listener closed.
This does not change any prior failed cleanup result.
A successful bounded closure proof is retained for those exact terminal browser
and helper handles and debug port, so later offline work does not reopen an
expired cleanup window. Replacing a handle/port or observing a live handle
invalidates reuse. Probe errors remain unverified and cannot prevent the owned
app launcher from receiving its existing cleanup.

Reports retain a validated helper failure code and a fixed CDP-stage category.
Stage changes use the same bounded progress envelope and survive a parent
readiness timeout. Protocol-budget expiry is reported separately from protocol rejection,
without exposing methods or error payloads. Success additionally requires the final stage to be `ready`, never
an earlier stage or a progress record.

Fixed CDP connection, setup and response waits share one remaining helper
budget under the original 40-second parent deadline. Metadata fetch sampling
remains capped at 500 ms and evaluation CPU time at 250 ms. Exhausted budget
cannot send a command or proceed to evaluation; there is no reconnect, second
navigation or retry. All eleven checks and final receipt must still fit the
original parent deadline. Unexpected socket close/error rejects pending waits
with a fixed code. Passive transport counts, boolean close/error flags and a
numeric close code are bounded and never substitute for readiness. Raw frames,
response IDs, URLs and close/error reasons are omitted.
