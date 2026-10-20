# Current admission discards an unstable main-file capture

The frozen QA262 full run found a private-lock admission failure while a broker
submission was already waiting: a main database read changed and raised a generic
error. The original broker test and frozen source/evidence remain unchanged.
This branch implements the independently reviewed proposal on pure302; it does
not retry an adapter, submission, consumer action or archival operation.

Current admission retains real root/private/Console and main resources through
its existing three-attempt loop and current-readonly yield lifetime. POSIX opens
use descriptor-relative no-follow/nonblocking resources. Windows uses the existing
no-reparse/no-delete open policy, with checked acquisition unwind and explicit
CRT ownership transfer. The normal unchecked Windows helper callers retain their
existing behavior; the new checked path attempts all owned closes once and refuses
success after uncertainty. Root permissions remain unchanged; only private and
Console require owner mode 0700 on POSIX, with main owner mode 0600 and one link.

A safely pinned same-inode size/mtime/read-length change discards the capture and
uses the original attempt/pause bounds. Unsafe metadata, replaced or removed
paths/directories, size ceilings and combined quota failures are terminal.
Retained anchors are checked before source discovery so removal during a pause
cannot become fresh initialization. Current-readonly never replays after yield.
Source SQL/SHM is not opened or written by admission. The shared raw file opener
now adds NONBLOCK for safe FIFO refusal; archival content-change errors remain
strict and nonretrying.

Regression source covers a real SQLite checkpoint during the main descriptor
read for all three current entry points, the same checkpoint under strict archival
reading, hostile metadata/directory/identity changes, replacement/removal during
pause, exact exhaustion, combined quota, no after-yield replay, real FIFO swaps,
root permissions, retained-resource close uncertainty and checked Windows partial
acquisition/unwind. A native Windows case exercises no-delete resources; local
POSIX runs cannot qualify that native boundary. No new retry/deadline or source
mutation capability is introduced.

Root and independent peer source reviews cleared exact production/test source
`8d7cd1623e49ede22688174c0caf3085d48dc1d9`. AST syntax and diff checks passed.
The new regression module passed 20 methods with one native Windows-only skip
(21 total) in 1.846 s, with ResourceWarnings as errors and a fresh private Hermes
root. Exact log: `/private/tmp/mentat-current-snapshot-8d-focused.log`.

The identical real-checkpoint method copied unchanged into an isolated pure302
Git archive failed all three entry subcases (validate, connect, current-readonly)
at the original raw reader's "file changed while reading" boundary. It did not
fail on imports or unrelated setup. No original source/test was modified for
that negative control. Log:
`/private/tmp/mentat-current-snapshot-pure302-negative-control.log`.

A later test-only descendant, `41dea93e1d49991c304e605b6c4f2d9f1a766e8f`,
changes only the exhaustion fixture's timestamp increment from 1 ns to a portable
2,000,000,000 ns; no sleep, deadline or production behavior changes. Root and peer
cleared that exact delta. Its affected method passed independently in 0.224 s,
with no skips and ResourceWarnings as errors. Log:
`/private/tmp/mentat-current-snapshot-41d-affected.log`.

The separately frozen integration `77a1c0510f64194e57ee7371813532419212ce7c`
normal-merged the reviewed 8d source. One coordinated batch of private Console
state, backup/restore, data-layout contract, retained Project backup and inference
broker modules passed 102 methods with one existing Linux namespace-only skip
(103 total) in 454.105 s. ResourceWarnings were errors; Hermes roots were private;
HEAD remained unchanged throughout. The original broker concurrency test passed
without modification. Log:
`/private/tmp/mentat-current-snapshot-77a-broader.log`; matching `-owned.json`
records the exact command and terminal result. No broader repeat was performed.

These local results do not qualify native Windows resources, Linux namespace
isolation, a later full aggregate, packaging or actual UI acceptance. The old
QA262 failure remains recorded. No actual app/browser/provider launch is part
of this change. Final full-suite and native-platform gates remain separate.

The later full fc4 inventory also found one pre-existing current-WAL regression
asserting the retired generic immediate-change error. Its mutation remains the
same real source write during each WAL capture. The fixture now expects current
admission to exhaust exactly three captures and the original two pauses, then
refuse with the fixed content-change error. It also requires that an unstable
capture never reaches private-copy materialization. Production code, source
mutation, schema checks and all budgets remain unchanged. Root and independent
peer reviewed exact source `6247d6ac95327871250b308de29276b08307fbf2`.
The complete current-database module passed all 36 methods in 3.682 s with no
skips, ResourceWarnings as errors and a fresh private Hermes root. Exact log:
`/private/tmp/mentat-current-wal-6247-focused.log`; its matching result JSON
records the immutable head and command. This is focused verification, not a
replacement full-suite pass. The failed fc4 run remains recorded.
