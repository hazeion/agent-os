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

Remaining high-risk scan findings

- test_orchestration_service: test_preacceptance_partial_completion_blocks_fifo_successor
  and test_concurrent_duplicate_and_competing_dispatches_invoke_runtime_once retain
  five-second gate/join assumptions and lack the new finally drain. The shutdown
  continuation test releases its gate in finally but does not join there.
- test_run_repository: test_concurrent_identical_event_append_commits_once and
  test_concurrent_task_commit_wins_before_claim_and_blocks_stale_attempt use short
  barrier/join budgets and inspect liveness after leaving the temporary root.
- test_link_preview_service.test_cache_clear_linearizes_after_a_final_store_and_removes_it
  has two-second event waits and a clear thread joined only on its success path.
- Five other Vercel transport checks still use 500 ms elapsed assertions; the
  Hermes refresh coordinator also has a 250 ms assertion. Keep their deadline
  properties, but consider controlled clocks or explicit interruption evidence.
- Several namespace HTTP fixtures use two-second sockets/joins. They deserve
  Windows/slow-host scrutiny, though many are platform-gated.
- A search found no remaining plain `with connect(...)` or `with sqlite3.connect(...)`
  test contexts that mistake SQLite transaction exit for closing a connection.
  Sampled inspection connections use closing, finally-close or LIFO addCleanup.
  An AST scan of direct sqlite3.connect assignments found one ownership-returning
  helper, test_project_proposal_source_guards._current_with_runs: callers close
  its returned connection, but an exception during fixture SQL before the return
  has no local close. This is a remaining failure-path cleanup risk.
  This is a targeted scan, not proof that every connection in tests is closed.

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
