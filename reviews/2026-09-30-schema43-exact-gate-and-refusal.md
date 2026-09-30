# Compatible correctness carry to PR #303

Exact publication base: `e2fd08ef3db2db30b73a270f835bc1ad808ebde4`.
Only the reviewed schema-43 gate, archival refusal translations, their four
regressions and this record are carried. Runtime origin/library/image/broker
modules, authority, provider defaults, lockfile and workflow remain unchanged.
The original PR #302 validation below is historical; per-PR compatibility
validation and two independent reviews are required before publishing.

# Schema-43 exact migration gate and archival refusal

Base: PR #302, `d92ef35125940e09401931d952deadd44e9995d1`.
Exact hosted CI run 36677558260, Linux Python 3.11/3.12 jobs 109765731678
and 109765731677 completed with two failures: the migration writer regression
expected a schema 42 gate, and the corrupted Run-input blob fixture received a
new archival ProjectContextError rather than PrivateConsoleUnitError.
The printed 2400-second watchdog message comes from a passing contract test;
it is not evidence of a real timeout in these completed jobs.

## Corrections

Migration 43 now joins the existing transaction-bound exact-source gate.
BEGIN IMMEDIATE covers the exact schema 42 signature inspection, journal DDL
and version receipt. An altered source refuses before mutation; existing
rollback restores 42 after an injected failure following 43 DDL.

Only archival entrypoints translate known domain refusal errors. RunRepository
maps ProjectContextError/WorkerJournalError to its existing corrupt error;
the private snapshot projection already maps that to PrivateConsoleUnitError.
The two direct private-unit archival validations translate those exact domain
errors into their existing private_run_attention_invalid refusal. All graph
validation still executes. Direct journal APIs, live proposal guards, capacity,
restore fencing, provider state and raw exception details remain unchanged.
Unexpected programming errors still propagate; no generic exception catch or
success fallback was added.

## Verification

The two original failing test methods remain unchanged and pass locally.
New regressions cover unknown Run column and removed receipt trigger with
unchanged schema 42 dump/no 43 receipt or tables; rollback after actual journal
DDL; a real leased journal refused by Run/archive with byte-identical source;
and both domain error classes plus unexpected RuntimeError at all three owning
validation boundaries. All 46 journal, Run-input and schema12 migration methods passed on Windows
Python 3.11.5 in 46.454 seconds. The four added regression methods passed in
9.658 seconds. Independent final code/fixture reviews A and B are clear; B
independently reran four focused methods. Seven CI contracts passed in 4.896 seconds. The same 46 related methods passed
on actual Linux Python 3.13.14 in 14.392 seconds, with zero skips. No existing assertion was weakened
or coverage removed; watchdog and workflow are unchanged.

Hosted rerun results remain unverified until the exact repaired head completes.
No owner service, model, provider, credential or owner-root operation is involved.
