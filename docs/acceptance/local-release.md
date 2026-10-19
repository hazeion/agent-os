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
booleans and fixed failure codes only. Raw process output, private paths, IDs and restore tokens are
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

The current non-reusing startup port check can reject immediate same-port
restart while previous HTTP connections remain in TCP TIME_WAIT. After proving
the listener and owned processes stopped, the optional `--diagnostic-port-wait` run waits at most 75 seconds
for that exact port to become bindable, then makes one restart attempt. It does
not silently change ports or retry a failed launch. The default run attempts immediate same-port restart and exposes this failure.
A successful diagnostic run explicitly reports `immediate_restart_acceptance: false`
and does not satisfy release restart acceptance.

The reviewed POSIX preflight repair is integrated on this branch. The default
immediate same-port restart journey now passes; the TIME_WAIT discussion above
retains the baseline failure and diagnostic distinction.

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
launch. CDP methods are fixed Runtime/Page enable, focus emulation, desktop metrics,
one initial local Tasks navigation and read-only evaluation; no arbitrary
evaluation/navigation, response bodies, provider or Run control is exposed. Loopback listener ownership uses `lsof` plus
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

The current348442 end-to-end attempt failed at browser readiness and retained
its disposable state because browser-group absence was false at cleanup.
Later group absence does not change that result. Its final-only output lost the
predicate state at timeout; the progress reporting change has only mock-test
verification until a separately authorized actual run is recorded.

The browser starts at owned `about:blank`. After verifying its exact loopback
CDP listener/group, the fixed helper enables Runtime and Page, enables focus
emulation, sets the fixed desktop metrics, then performs one initial navigation
to the configured local origin's `/tasks`. It never reloads, retries navigation
or accepts another target URL. A navigation error yields a fixed failure code.
Progress includes fixed ready-state/location categories, snapshot count and
observer-relative elapsed milliseconds; counters/time do not trigger progress
emission. The parent's Chrome-spawn deadline remains authoritative.

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
readiness timeout. Existing connect/call timer expiry is reported separately
from protocol rejection, without exposing methods or errors. The timers remain
unchanged. Success additionally requires the final stage to be `ready`, never
an earlier stage or a progress record.
