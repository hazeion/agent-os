# Current-schema repository boundary

Status: implementation in progress under the owner's current-only decision.

The owner explicitly chose fresh/current databases and retired older SQLite
upgrades and backup formats. This replaces the earlier historical compatibility
direction. Existing current-schema rows and their authority, capacity, queue,
producer, unknown-outcome and restore-integrity rules remain enforced. An older
or future database must fail closed without migration, deletion or rewriting.

## Scope and interfaces recorded before implementation

Restrict Agent, Conversation, Project, Run, Task and Vercel repository admission
to the current schema. Remove obsolete schema-dependent validation exceptions,
standalone Agent-registry migration helpers and schema-5 compatible-root export.
Keep canonical SQLite-to-JSON Task export with its existing offline exact
preview/confirmation protections. Row-level legacy provenance inside a valid
current database is current data, not a license to weaken row checks or capacity.

Coordinate the current-only SQLite bootstrap and backup units with their owning
workers: the database module exports one current bootstrap recipe and retains
structural receipt history; the private unit has history bytes, database bytes
and blobs only. No direct edits to those workers' files belong here. Report
retired API callers and historical fixtures for root-owned cleanup rather than
deleting unrelated security behavior.

The cache suite becomes twelve current operational tests: immutable reuse,
unowned current state and fresh restore epochs, current recipe invalidation,
future-version refusal, current validation faults, uncached construction errors,
concurrent misses, nonempty source capture, unsafe roots and permissions. Remove
historical positive cache construction and duplicate released-schema threshold
tests. Current row, backup and uncertain-outcome contracts remain covered.

Expected Agent-schema tests cover the current exact DDL recipe, bounded cache,
invalidation, construction failure/closure, live schema drift, and unsupported
version refusal. No old/future request may create a signature database. Final
focused tests must use the composed current bootstrap/private-unit interfaces;
intermediate incompatible signatures are not reported as passing evidence.

## Implemented admission and retired paths

All six repository boundaries require the complete current structural journal
1..46. Existing table fingerprints, foreign-key checks, authority receipts and
row validation remain in force. Expected Agent, Task and Run schema constructors
accept only the current version and retain at most one generated signature.
Current Agent revision and system-role columns are always required. Conversation
submission receipts, attempts and planning associations are always validated.
Current Run identities, attention, retained inputs and unknown-work capacity
guards remain active.

Standalone Agent-registry DDL, capture and cutover helpers are removed. Current
Task JSON export is named `preview_task_export` / `confirm_task_export`; its exact
confirmation purpose, destination binding and offline publication checks remain
unchanged. Schema-5 sibling export and publication helpers are removed. The
current Task preview result is `TaskExportPreview`.

Run initialization no longer imports JSON history. A missing history file or an
empty document with the current history format can establish an empty Run
authority receipt atomically. Old-format and nonempty documents refuse before
locks, writable SQLite or source permission changes. The read-only preflight
checks the canonical no-follow Console directory chain and bounded owner-private
file. Source bytes and identity are rechecked within the receipt transaction.
An established current SQL receipt ignores all stale JSON, including malformed
bytes, and preserves current persisted Run evidence. Existing valid receipt
provenance and row-level truncation metadata remain accepted current data.

## Focused evidence so far

The 13-method expected-Agent-schema suite passes against the actual current
bootstrap module from `a482f623f17abf4713abb63cf7c9141b8a7b73c8`, loaded through a
disposable module overlay. It includes all six repository boundaries accepting
current empty SQLite and refusing older, future and incomplete journals under
`PRAGMA query_only`, with exact serialized bytes and change counts preserved.
Constructor invalidation, one-entry bounds, connection closure, concurrent
misses and fresh live DDL/receipt drift validation also pass.

Owned disposable Run probes pass for missing/current-empty bootstrap, exact
unchanged refusal of current-nonempty and old-empty JSON, and stale hostile JSON
ignored after SQL authority exists. No owner data or Hermes files are read.
Current cache tests still require the coordinated three-field private-unit
implementation before their final result can be recorded.

## Fixture composition

The Run module retains64 test/helper methods. Its shared `prepare_dispatch_root`
and `run_fixture` interfaces remain structurally unchanged. Current unknown,
capacity, expiry, dispatch, rollback, timestamp and event-security methods remain.
Retired JSON import positives are replaced with canonical SQLite setup, preserving
current event-type, retained suffix, media binding and cursor assertions. Three
persistent tests cover current-empty bootstrap, no-write old/nonempty refusal and
authoritative SQL ignoring hostile stale JSON. The event-ID boundary now tests
atomic current SQL rejection rather than obsolete import acceptance.

Task tests remove only obsolete schema4/5 positive-upgrade and sibling-export
paths. Plain export size, exact bytes, confirmation, stale source, source path,
interrupted restore, publication and partial failure checks remain. After
normalizing the renamed symbols, the preview, confirmation, destination validator,
confirmation-token function, private-state lock wrapper and preview dataclass ASTs
are identical to the preserved8c baseline. The Agent suite removes only the
retired standalone-file identity helper test and retains current core sidecar,
concurrency, private binding, capability and HTTP tests.

The actual database dependency is now normally merged at
`e25ca335cf813283cf8333a9d8842e79af529ffe`. The13-method expected-schema suite passes
from the real composed checkout, with ResourceWarnings treated as errors and no
skips, in3.049seconds. Run receipt preflight uses its append-tolerant
`connect_current_readonly` owned-copy context, keeping strict archival snapshot
validation out of live receipt checks. Final cache and domain module results await
the coordinated private-unit and CLI dependency integration.
