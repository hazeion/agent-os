# Exact synthetic empty Console template reuse

Scope approved after read-only profiling of PR #273 head
`235fb35c697b77a05d006dd33dda1f9160a5d6f8`. Windows Python 3.13 group 2,
run `36675655307` / job `109759927518`, reached the unchanged 1,800-second
watchdog. The newer-schema refusal test passed in 695.289 seconds; a concurrent
required-directory repair test had started earlier and was still running when
the watchdog expired. Earlier backup units took 110.465 and 362.830 seconds.
This is repeated fixture/storage work, not evidence that refusal itself needs
a larger timeout.

The exact newer-schema method creates three fresh roots. Each normal startup
performs four current Agent-registry checks: preflight, locked guard, finalizer
and final readback. An absent Console store makes each check construct the same
synthetic empty private unit in a new on-disk SQLite database. The local profile
therefore observed twelve empty database constructions. No ACL subprocess is
in this path; the expected in-memory schema signature was already cached and
was not the dominant cost.

Cache only one successfully constructed and validated immutable synthetic unit.
The complete key includes the current schema, exact migration scripts, exact
empty history bytes/version, module schema-threshold and MAX normalization
constants, supported versions, registry normalization values, platform/SQLite
engine, and constructor/filter/current-validator/transaction-normalizer callable
identities. Recipe changes select a new entry, and a changed recipe during
construction or retrieval fails closed. Construction and filtering exceptions
are not cached. The cache holds only bytes, `None`, and an empty blob tuple in
the existing frozen value object; its capacity is one.

Independent review identified that `lru_cache` alone could construct the same
recipe twice when two callers missed concurrently. One small module lock now
serializes synthetic lookup/construction only; it acquires no operator/root
lock. Per-caller validation stays outside this lock. A bounded two-thread
barrier regression requires exactly one constructor, both returned values and
both fresh validators running outside the lock. An explicit no-lock
counterfactual fails with two constructors. Fixture cleanup releases and joins
only its owned callers before asserting, including failure paths.

Every retrieval still calls the existing full private-unit byte/relationship
validator. A cached template is not current validation evidence. Both existing
live-root inspection and absent-store selection in `capture_private_console_unit`
remain unchanged, as do nonempty capture, source identity, permission, migration,
backup/restore, hot-store and no-write checks. No operator snapshot, root result,
migration preview, readiness result, credential, task, run or provider setting
enters this cache. Legacy empty construction helpers are unchanged. No SQL,
transaction, serialization, durable digest, timeout or security assertion was
relaxed to obtain this reuse.

Local before/after evidence used the same owned-TemporaryDirectory fixture,
exact method, designated Windows Python 3.11.5 and `cProfile`, in separate fresh
processes. Runtime/provider subprocesses were blocked; only Python's fixed OS
`ver` metadata query was permitted. Configuration/Hermes/vault defaults pointed
to absent fixture-owned paths, with no owner server or installed runtime used.

| Measurement | Exact base | Changed cache | Cache with construction lock |
| --- | ---: | ---: | ---: |
| Passing method wall time | 14.647 s | 4.404 s | 3.871 s |
| Current root/registry checks | 12 | 12 | 12 |
| Synthetic database constructions | 12 | 1 | 1 |
| `executescript` calls | 495 | 132 | 132 |

These changed-source measurements are approximately 70–74% below the local
baseline; the repeat is not evidence that the lock itself made the sequential
case faster. They are not a hosted Python 3.13 or complete group claim. The changed profile still ran full private-unit validation 25
times. Newer-schema refusals remained about 0.00035 seconds and retained the
exact unchanged-tree assertions. The original watchdog remains 30 minutes.

All twenty-one selected cache, schema, default historical backup, changed-target
restore, retained-blob, active-run capture, live-sidecar, source-byte recheck and
registry-migration boundary tests pass in 47.452 seconds on local Windows after the concurrency repair.
The nine new cache methods cover exact original raw bytes and digest, frozen
values, repeated reuse, migration/history/schema/normalization recipe changes,
constructor/filter errors, current validation faults, changed transaction
normalizer faults, current nonempty/changed-store capture and no-write root
refusal. The POSIX owner-only permission method is correctly skipped on this
Windows host; it remains part of ordinary discovery for POSIX CI and is not
claimed locally verified. Both changed Python sources parse and
`git diff --check` passes.

No live CI job was rerun or cancelled, no server/model/provider was called, and
no owner configuration or application was changed. Actual hosted improvement
remains unverified. Hold publication for two independent backup-boundary
reviews; retain every platform/Python leg, discovered execution, migration
assertion and existing timeout.
