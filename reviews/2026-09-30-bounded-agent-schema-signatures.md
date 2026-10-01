# Bounded immutable expected Agent schema signatures

Exact failed-head base: PR 290 ea130a97d9495197cbe327f4b971306c7a802b16 (schema 41).

Its completed Windows group 5 run36668650945 / job109773527624 exhausted the
existing 40-minute group budget. The preceding released-schema-12 backup/restore
method consumed roughly 14.5 minutes on that runner. This record diagnoses that
method; it does not blame the final module or claim hosted improvement.

Completed source-only local profiling of the exact method measured64.108 seconds.
The one-entry expected embedded Agent signature cache alternated between retained
schema12 and current41, reconstructing58 synthetic stores in50.462 seconds.

The fix caches at most eight immutable expected SQL-signature tuples. Keys bind
target/current versions, every exact migration script, normalizer identity and
SQLite constructor/version. A module-only mutex makes misses single-flight.
Recipe changes during construction or before return refuse; failures are not
cached. Actual schema signatures, Agent rows, relationships, authority receipts,
private roots, credentials and epochs remain freshly validated and uncached.

The same method passed after the change in14.895 seconds (76.8% local reduction),
with two synthetic expected builds and all52 full private-unit validations and
193 fresh embedded-registry checks retained. This is an isolated Windows3.11
measurement, not a promised hosted result. A fresh-process repeat, complete
registry/migration/private-backup boundaries and two independent reviews are
publication gates. No workflow, timeout, existing assertion or test coverage is
removed. The secondary empty-template cache is not included in this fix.

Qualification: a fresh-process repeat passed in 15.828 seconds, with the same
two expected constructions, 52 full private-unit validations and 193 fresh
embedded-registry inspections. All 37 registry/new-cache methods pass on Windows
(15.300 seconds, one POSIX skip); all 23 migration/CI methods pass (21.777 seconds).
On actual Linux, all 53 registry/cache/schema12 methods pass (11.026 seconds),
and the complete 53-method private backup/restore suite passes (83.601 seconds,
zero skips). The eight new focused cases pass in 2.900 seconds after correcting
the injected receipt fixture to retain SQLite's length constraint while using
invalid hex. All existing corruption, ownership, race, restore-reservation,
blob, rollback and epoch assertions remain. Independent review and hosted
current-head checks are still separate gates.

Both independent implementation reviews are clear. Reviewer B independently ran
all eight new boundary methods (2.898 seconds, Windows 3.11). The optimization
is source-stable and qualified locally. Publication ordering remains separate:
any pending bulk-security proposal must retain its exact approved heads before
this narrow source repair is carried onto a later security head.
