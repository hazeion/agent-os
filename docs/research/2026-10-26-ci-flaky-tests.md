CI flake investigation, 26 October 2026

Work started at fa3634a in the ci-investigate/flaky worktree. All changes are
local. No push, PR mutation, workflow dispatch, or CI rerun was performed.
GitHub access was read-only through gh. Production code and workflow configuration
are unchanged. Correctness assertions were retained or strengthened; the short elapsed-time
assertion was replaced with exact deadline assertions. No skips were added.

Evidence and fixes

- test_competing_reconcilers_claim_one_pending_head_once: reproduced on the local
  Intel Mac with the original five-second join. One test failed after 14.434 s
  because a worker was still alive. CI job 118228459384 shows the same failure
  followed by WinError 32 on mentat.sqlite3. The test confuses completion of real
  SQLite work with a five-second performance requirement. df66bce preserves the
  simultaneous barrier, lease-count, one-dispatch, Turn-attempt, Run-count and
  repository validation assertions. Coordination and join checks now allow 60 s.
  A finally context releases gates and joins every started worker before root
  cleanup, including when a preceding assertion fails.

- test_concurrent_conversation_replay_and_competing_key_call_runtime_once:
  five-second adapter gates could expire while the main thread performs real
  SQLite work for duplicate and competing submissions. Its join also preceded
  root cleanup without a finally. df66bce keeps the duplicate/submitting/pending
  assertions and exactly one runtime call, extends coordination budgets, and
  drains the worker on every exit. The join-liveness assertion is inside the
  drain context, so an over-budget worker still fails the test.

- test_preacceptance_completion_waits_for_finalized_event_before_fifo: CI job
  110191079582 from PR 282 fails the five-second submit-entered wait, then tries
  deleting the live SQLite root. df66bce provides the same gate/release/drain
  ownership. All before-finalization, pending-successor, after-finalization,
  continuation and runtime-call assertions remain.

- test_simultaneous_http_duplicates_accept_exactly_once: the fixture burst eight
  clients against the default small HTTP listen backlog, used five-second client
  deadlines, and closed clients only on success. Daemon request handlers were not
  owned by server_close. 0658d9e adds an eight-client start barrier, backlog 16,
  60-second client watchdogs, finally-closed clients and non-daemon joined request
  handlers. Exactly one 202, seven 204s, one pending refresh and secret-free
  persistence are still required. These are identified fixture risks, not a
  confirmed Windows reproduction: the exact reported HTTP failure log was not
  recovered in the sampled job histories.

- test_raw_upload_rejects_noncanonical_metadata_and_transfer_encoding: invalid
  headers are rejected before reading a body. Sending a separate body write can
  race early connection closure and a Windows TCP reset. f50d29f sends the same
  invalid headers without body bytes and requires all original status/error
  assertions plus no staging call. A server that tries reading the declared body
  cannot complete these requests. This strengthens early-header rejection while
  avoiding an unnecessary TCP race. The reset mechanism is inferred from the
  code and reported platform; it was not reproduced on Windows here. The valid
  upload test still transfers and verifies an exact complete body.

- test_transport_connect_phase_obeys_the_absolute_deadline: the former test used
  a real 50 ms deadline, real SSL setup and a timer thread, then required completion
  within 500 ms. Runner scheduling and certificate setup could fail that bound.
  3ff221d uses a controlled clock and timer at the transport boundary. DNS and
  setup each consume 10 ms; the timer must receive precisely the remaining 30 ms,
  fire at the original 50 ms absolute deadline, close the connection before
  credentials can be sent, be cancelled on exit and return a redacted timeout.
  An in-memory mutation that renews the full 50 ms budget fails the new assertion.
  Neighboring real-timer transport interruption tests remain unchanged.

- Scan follow-up, test_simultaneous_exact_context_send_replays_the_winner in
  test_conversation_attachment_orchestration: the same short join and missing
  finally could remove SQLite underneath attachment-dispatch threads. df66bce
  extends its barrier/join watchdogs and drains both workers. It still requires
  one original, one replay and one runtime call.

- 98bcf49 adds a call-site regression for failed ordering assertions in the replay
  and finalization tests. It deliberately raises while the adapter gate is held
  and observes worker liveness before TemporaryDirectory cleanup. Both cases
  require no live worker. A rescue drain keeps the regression itself safe if the
  fixture breaks. Disabling the drain in memory makes both subtests fail.

The final cleanup joins deliberately have no short timeout. The tests retain
explicit 60-second liveness checks on the successful path, then drain before
removing the root on failure. A genuine deadlock remains subject to the outer
process watchdog rather than deleting an in-use database or hiding the failure.
No evidence from these runs required a product race fix.

Existing earlier repairs

- PR 244 recovery-flood accounting is already fixed at this tip by dd6051e.
  Crossing a wall-clock minute admitted another ten verifier calls. The test now
  fixes the clock, retains exactly 50 calls, and separately verifies rollover.
  Both current tests passed locally. The default Python lacked argon2; these two
  checks used dependencies installed into ignored data/runtime storage.
- The earlier completion-worker cleanup repair is already present, including
  c122da1 and the inherited ordering-failure/retained-root regressions. It is not
  a reason to suppress Windows cleanup errors. Other workers still needed their
  own explicit ownership, as the reproduced reconciler failure demonstrates.

Round 2 fixes

Round 2 continues in /tmp/aos-ci-flaky on ci-investigate/flaky. All work remains
local. No GitHub requests, pushes, PR edits, Actions triggers or workflow changes
were made in this round. Product code is unchanged.

- Moved the round-1 drain_workers context and THREAD_TIMEOUT into the existing
  tests/sqlite_authority_support.py helper. The partial preacceptance, duplicate
  task dispatch and shutdown continuation fixtures now release their gates and
  join started workers on every exit before temporary-root cleanup. Shutdown
  drains inside the patched runtime/global context before restoring it. The
  ordering-failure regression now covers these three call sites as well as the
  original two, with liveness observed before cleanup and a rescue drain.
- Both concurrent Run repository fixtures use 60-second coordination watchdogs,
  retain their barriers and gate ordering, assert liveness inside the temporary
  root, and unconditionally drain started workers before cleanup. Event commit
  counts, stale-task rejection and stored-state assertions remain.
- The link-preview final-store/cache-clear fixture retains the linearization,
  empty-cache and unavailable-preview assertions. Its coordination watchdogs are
  60 seconds, and finally releases both gates and joins any started clear thread
  before closing the service and removing its root.
- The five remaining Vercel elapsed assertions now inspect deadline budgets and
  interruption. DNS must wait exactly its 20 ms phase budget and return while
  resolution is still blocked, without constructing a connection. Its resolver
  is released and joined on all exits. TLS, write, headers and both body ownership
  variants fix the setup clock and require a real Timer with exactly the original
  50 ms absolute budget. Their blocking operations require verified closure to
  return. The existing timeout, detached-socket and secret-redaction assertions
  remain. The round-1 advancing-clock connect test still verifies budget consumed
  by DNS/setup is subtracted. No deadline is replaced with a longer product budget.
- Hermes refresh shutdown observes an exact join(0.05), requires stop to report
  False while the refresh worker is still blocked, then releases and stops it in
  finally. Restart reconciliation assertions remain. Scheduling delays no longer
  turn a valid 50 ms shutdown request into a failed 250 ms performance assertion.
- _current_with_runs closes its new connection if fixture SQL or commit raises.
  A regression injects both failure modes and requires one close plus propagation
  of the original error.
- The three namespace HTTP fixtures that run on macOS and Windows now own clients
  through ExitStack plus closing, use 60-second socket/fixture watchdogs, retain
  timed liveness assertions and finally drain server/broker workers. The broker
  endpoints are shut down before closing to interrupt blocked socket reads on
  failure. Route rejection, no broker bytes, SSE output, exact request bytes,
  image validation and response assertions remain. LinuxNamespaceTests is already
  class-gated on IS_LINUX; its separate two-second namespace broker join remains
  unchanged. No skips were added.

Round 2 verification

Validation uses /tmp/aos-ci-round2-venv, CPython 3.13.14, with all requirements.txt
dependencies installed, including argon2-cffi. No venv was created in the repo.
Fresh TestCase instances and private roots are created on every stress repetition.
Two stress processes overlap the complete touched-module run, and the extended
cleanup/namespace stress overlaps the slower worker group.

Implementation commits: dccf983, test: harden remaining CI fixture ownership and
deadline checks; 0e086b5, test: assert deadline interruption outside transport
exception handling.

- Worker group: six tests, 30 repetitions each, 180/180 passed in 223.742 s.
- Transport, refresh, HTTP namespace and connection-close group: nine tests,
  30 repetitions each, 270/270 passed in 60.089 s.
- Final expanded ordering-failure regression and final namespace fixtures:
  four tests, 30 repetitions each, 120/120 passed in 239.948 s. Each cleanup
  regression repetition covers five injected call-site failures.
- Final DNS resolver ownership: another 30/30 passed in 1.194 s.
- Final transport review strengthened interruption checks again: each fake
  blocked operation records its wait result, and the test asserts the exact
  successful-interruption list outside product exception handling. An assertion
  raised inside a fake transport could otherwise be caught by production code.
  These three tests passed another 90/90 executions in 8.828 s, followed by the
  full Vercel module, 17/17 passed in 0.410 s.
- Total reported stress executions: 690/690 passed, no errors or skips.
- Complete touched-module run: 248 tests in 259.132 s, 237 passed and 11 existing
  Linux-only namespace checks skipped. The strengthened ordering regression,
  final namespace join assertions and final DNS drain were also stressed after
  that run loaded its modules. Full discovery below loaded dccf983; the extra
  interruption assertions in 0e086b5 were validated separately by the final
  90-execution stress run and complete Vercel module.
- In-memory mutations: increasing the Vercel timer budget fails the TLS,
  write/header and body tests; increasing DNS wait fails its budget assertion;
  doubling refresh shutdown join fails its exact-budget assertion. Removing the
  shared drain fails all five ordering-cleanup subtests. No mutated file was
  written to the repository.
- Compilation of all eight changed Python files and git diff --check passed.

The initial development smoke run had four failures and four errors among
62 tests, with 11 existing skips. Three errors came from using HTTPConnection
as a context manager instead of wrapping it in closing; one came from missing
argon2 in the system Python before the venv was ready. Four failures showed
that real SSL setup could consume the short transport budget before its test
phase. Those fixtures were corrected. A following transport-only development
run had one failed DNS-observation assertion because it observed the wrong
Event; that was corrected to inspect the exact timed wait and its 20 ms phase
budget. These were development/test-environment failures, not pre-existing
product failures. Subsequent venv runs passed.

The requested full discovery was run once:

    /tmp/aos-ci-round2-venv/bin/python -m unittest discover -s tests

It completed 2,793 tests in 1,467.550 s with 16 failures, 19 errors and 131
existing skips. The subprocess wall time, including collection/import, was
1,478.559 s. This was not a green full-suite run.

Every failure/error record was reproduced on the round-1 commit, 1cc4bd2,
using a clean tracked-source snapshot, the same venv, and matching ambient
private-root state. Three baseline runs covered 164 tests and reproduced the
same 16 failure and 19 error records. Comparing the normalized record lists,
including subtest labels, found 35 identical records and no unmatched record.
The breakdown is:

- Eleven failures depended on a zero-byte ignored database at
  data/private/console/mentat.sqlite3. Affected cases were cron inventory;
  four Dashboard Agent Console validation/dispatch cases; profile-creation/run
  exclusion; legacy runtime routing; local-unavailable validation order;
  two Local Bridge startup/lifecycle cases; and remote continuation validation.
  Storage correctly failed closed, changing the response/status these tests
  expected. The same ambient file also caused eleven error records in the
  Hermes refresh server-adapter tests, including their malformed-input subtests.
  The clean baseline refresh module passed 21/21 without the file and reproduced
  all eleven errors after matching the zero-byte file. No private database was
  removed or rewritten in the implementation worktree to hide these results.
- Five failures and seven errors in test_project_runtime_dependencies came from
  missing development tooling: packaging and the fixed pip-audit 2.10.1 auditor
  are not installed by requirements.txt. The same 12 records reproduced on the
  baseline. After installing packaging 26.2 and pip-audit 2.10.1 in the external
  venv, the complete dependency module passed 18/18 in 1.780 s. pip check passed.
  Runtime requirements and repository dependency files were not changed.
- One error was test_run_stop_control.RunStopControlTests.
  test_confirm_reconciles_the_exact_run_when_adapter_does_not_write_sqlite,
  raising run.stop_partial. It reproduced on the baseline under the same
  conditions. Its underlying cause was not isolated further in this round.

The baseline comparisons used the complete refresh module, six modules covering
cron/Dashboard/profile-deletion/skills/transport/Local Bridge, and a final run of
the remaining four exact cases plus the dependency module. Full discovery was
not rerun after these comparisons. The final Vercel assertion-only follow-up is
covered by its separate final stress and complete-module run above.

No failure in the requested hardened test methods was observed in final
validation, and no product race requiring a production change was established.

Remaining risks

Windows and Linux were not available for this round. Existing Linux-only namespace
checks remain gated and unverified here. The retained Linux two-second join and
other short waits outside the requested scan remain follow-up candidates.
The full-suite results also expose tests that depend on ambient private-root
state, missing development-tool setup when only requirements.txt is installed,
and the baseline run.stop_partial error. These need separate follow-up; the
full suite must not be described as green.
The shared final drain intentionally has no short timeout, so a true deadlock
needs an outer process watchdog rather than deleting in-use fixture resources.
These changes address fixture ownership and deadline measurement; they do not
resolve the independent historical shard/backup runtime issues described below.

CI configuration

The current Windows matrix is 3 Python versions by 12 groups, or 36 jobs. Each
runner executes whole modules serially; only splittable single-test units overlap,
with a ceiling of two. Separate matrix jobs do not contend on one runner. Linux
and Intel macOS run full suites serially on three Python versions each. The
workflow has no max-parallel cap. The group watchdog is 40 minutes and the Windows
job limit is 50 minutes. These do not explain a five-second liveness assertion,
but real filesystem and scheduling latency exposes tight fixture assumptions.

There is also independent historical timeout evidence. Job 109778251824 ran a
single backup/upgrade case for 890.484 s and later exhausted its 2400 s group
budget. Job 107887791110 exhausted the older 1800 s budget. Retired migration
workloads and uneven weights explain some red checks independently of the listed
flakes. Increasing all deadlines or enabling more per-runner concurrency would
not fix the fixture ownership bugs. Prefer measured shard balancing after these
repairs. Raising Actions parallelism also increases simultaneous spending; CI
remains paused and this investigation did not change it.

Backport placement

Read-only `gh pr list --state open --limit 100 --json number,headRefName,baseRefName`
shows the lowest open stack layer is PR 254, codex/google-login-transactions,
based on main. All seven affected original test methods already exist in the
local origin/main snapshot. Recommended placement for df66bce, 0658d9e, f50d29f,
3ff221d and 98bcf49 is that common baseline, or PR 254 if landing only on an open
stack branch. Adapt context drift rather than carrying the tip's schema changes
downward. Apply 98bcf49 after df66bce. Restack descendants only after local review;
no branches were rewritten here. No separate product or workflow fix is proposed.

Local verification

Host: Intel macOS 15.7.7, CPython 3.13.14. Windows was not available locally.
Each repetition loads fresh TestCase instances and creates fresh data roots.
The longer orchestration, attachment and failure-cleanup loops overlap the module
checks, providing filesystem/process contention without sharing fixture roots.

- Three reported orchestration tests: 30 repetitions each, 90/90 passed, 406.8 s.
- HTTP duplicate, invalid upload and connect deadline: 50 repetitions each,
  150/150 passed, 63.8 s.
- Attachment simultaneous replay: 30/30 passed, 105.0 s.
- Four complete neighboring modules: 63 tests passed, 47.096 s.
- Full orchestration module with local dependencies and the added failure-path
  regression: 110/110 tests passed, 149.823 s.
- Python compilation of all five changed test files and git diff --check passed.
- Failure-cleanup regression: 30/30 repetitions passed, covering both injected
  failure subtests on each repetition, 74.8 s.
- Recovery-flood and explicit minute rollover: 2/2 passed, 3.889 s.
- Two in-memory mutation checks passed: removing drain caused both cleanup
  subtests to fail; restarting the connect budget caused the deadline test to fail.

Repeat the targeted checks by constructing a fresh unittest suite in each loop,
for example using `unittest.defaultTestLoader.loadTestsFromNames(names)` and a
fresh `unittest.TestResult`, then requiring `wasSuccessful()` each iteration.
The full neighboring-module command was:

    python3 -m unittest tests.test_conversation_attachment_orchestration tests.test_conversation_file_bridge tests.test_hermes_webhook_routes tests.test_vercel_infrastructure -q

The first full orchestration run completed 109 tests in 263.982 s with two
missing-argon2 import errors and no assertion failures. After adding isolated
local dependencies and the cleanup regression, the rerun command was:

    PYTHONPATH=data/runtime/ci-flaky-deps python3 -m unittest tests.test_orchestration_service -q
