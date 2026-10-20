# Run admission error boundary on the full current graph

Contract recorded before implementation: preserve the shared kernel’s earlier
read-only refusal of unsafe, unsupported or nonempty unclaimed history. Negative
Run fixtures must invoke the actual Run initializer, not first establish Task
authority through a test helper. Require the existing fixed Run unavailable
error and unchanged storage, no SQLite/authority creation and unchanged external
inodes/modes. A kernel admission failure that races after the first history read
may be wrapped by private_state_lock; map only that typed cause into the Run
domain without retry, fallback or a broader control-error translation.

The frozen13a full run remains untouched and running. Fixes are isolated in a
new branch from13a3e5458e4cec5ac81d2d0f690047cdbf814863. No kernel, Task,
Conversation, backup or deadline changes belong to this patch.

## Diagnosis and bounded fix

The frozen run’s seven reported Run errors represent three unsafe-source cases
using a Task-first fixture helper and four retired/nonempty payload subcases
whose expected inner parser exception no longer matches earlier kernel refusal.
The refusal is correct. These fixtures now call the actual Run initializer and
require its exact existing `RunRepositoryUnavailable` code. They no longer open
rejected storage afterward just to inspect empty tables: unchanged snapshots and
absence of SQLite prove no authoritative empty fallback or receipt was created.
Original external inode bytes/modes and platform decorators remain enforced.
The normal Task-before-Run test setup helper remains unchanged for positive uses.

One genuine API leak is also fixed. If a previously accepted empty history is
changed after the first read but before the shared lock, that lock wraps the
kernel refusal as PrivateStateError. Four production lines now translate only
a MentatDatabaseError/OSError-caused private-state failure into the existing
fixed Run unavailable error. Unrelated private control errors are rethrown.
No admission check, write ordering, retry, capacity, receipt, queue, unknown
outcome or privacy rule changes.

The deterministic new regression changes owned empty history to malformed bytes
after the read. It requires typed refusal before writable open, unchanged
post-injection directory/file identities, modes, links, bytes and timestamps,
and no SQLite file. The same test was independently run against the exact
original13a function in a temporary in-process binding: it reproduced the raw
PrivateStateError. The fixed function passes. No original source file, frozen
checkout, test deadline or expected authority behavior was changed for that probe.

## Verification

All four existing affected methods plus the new race method pass, covering the
seven original error subcases. The complete actual-checkout Run module passes
all63 methods with no skips in22.808seconds and ResourceWarnings as errors:

```sh
/private/tmp/mentat-ci-recovery-venv/bin/python -W error::ResourceWarning -m unittest tests.test_run_repository -v
```

Raw log: /private/tmp/mentat-run-admission-full-module.log. Of62 original methods,
58 retain identical ASTs; four negative fixtures are corrected, none removed,
and one race regression added. RunRepository and every source function other
than the four-line initializer error mapping remain unchanged. The full13a
run and its failure evidence are not stopped, altered or reported as passing.
No broader CI, release, Linux or live-runtime qualification is claimed.
