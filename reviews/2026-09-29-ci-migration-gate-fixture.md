# Exact migration-gate race fixture

The exact PR #290 head `4f82dcd2` fails the schema-12 upgrade race fixture on
Linux, macOS and Windows. Reproduced locally: 30 competing-writer attempts
versus its assumed 29 pre-migration gates. Schema 41 legitimately adds an exact
post-rebuild schema check before committing the Run-table migration receipt.
Every writer was still blocked; the fixture's one-check-per-version count was
stale, not evidence that a competing write succeeded.

Keep production migrations and locking unchanged. Assert the exact gate-version
sequence, including schema 41's post-rebuild gate and the next migration's
independent pre-gate when present. Require one completed competing-writer
attempt per expected gate, every outcome locked, and no raced payload column.
Drain each writer and enforce its liveness assertion inside `finally`, before
the fixture root is removed, including an ordering-assertion failure. Keep the
two-second ordering check; a still-live writer gets bounded diagnostic drain
before failing. An injected ordering failure holds its owned writer past the
first join and verifies actual termination before cleanup, while preserving
the original assertion. Its fallback drain observes first, so the regression
remains detectable without leaking that writer.

The previous assertion fails on the exact base. The corrected race and existing
caller-transaction preservation cases pass. All 16 schema-12 tests (including
the cleanup regression) and 10 proposal-source migration tests pass on Windows.
Two independent reviews are clear after fixing one cleanup finding. Review B
also executed the corrected race case against schema 42 without changing that
branch; its duplicate schema-41 gate sequence passes. Publish this test-only fix to
PR #290 and propagating it to #291/#294. No production code, schema, watchdog,
owner data, server or runtime behavior changes.
