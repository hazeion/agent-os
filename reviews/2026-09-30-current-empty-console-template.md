# Current-schema synthetic empty Console template

Base: PR #307, `24c4cbe792aa2e7c216bd50e89d2ed5915947c74`, schema 43.
Scope: replay the reviewed PR #273 synthetic-only construction optimization;
no live-root selection, production migrations, authority, restore protocol,
timeout, test inventory or workflow changes.

## Boundary

The single-entry cache retains only immutable code-generated empty database,
empty history bytes and an empty blob tuple. The exact migration SQL/history,
schema thresholds, limits, platform/SQLite and construction/normalization
callables bind its recipe. A module-only lock prevents concurrent duplicate
construction; each caller validates the whole returned unit outside that lock
and rechecks the recipe. Exceptions never become cache entries. Live roots,
source snapshots, current permissions, nonempty graph and blob checks are fresh.

Schema 28 access and schema 32 review virtual epochs remain canonical zeros.
Owner auth is unbootstrapped; schema 43 generations/calls and proposal receipt
rows are empty. Restores still rotate both epochs independently; no sanitized
restore, owner state, credential, journal authority or scope descriptor is cached.
Existing archival proposal and retained-blob validation remains authoritative.

## Evidence

The eleven cache methods passed on Windows Python 3.11.5: ten pass, one POSIX
permission skip (31.908 seconds). Tests include original exact raw bytes/digest,
recipe changes and refusal, construction/validation faults, single-flight
concurrency, nonempty/changed-root capture, empty schema-43 authority and fresh
restore epochs. The POSIX case now uses an actual existing 0644 SQLite-file
refusal contract; read-only inspection does not promise a 0755-directory refusal.

An identical isolated source-only cProfile startup/refusal test, with installed
runtime/provider subprocesses prohibited, took 18.032 seconds before and
5.230 seconds after, a 71.0% lower local subset wall time. Both runs retain six
startup preparations (three initialized, three refused), twelve registry/root
convergence checks; synthetic construction falls from twelve to one and the
after run still performs 25 full unit validations. An earlier 6.505-second
measurement overlapped another test suite and is not the reported comparison.
This is one local workload; hosted CI/full-group improvement is unverified.

Eleven existing warm-cache Windows boundary methods passed in 12.388 seconds:
empty/known/unknown archival journal restore and refusal, revoked grants/fresh
epochs, retained and missing blob checks, source SQLite sidecar immutability,
and active-server restore refusal. Seven CI inventory/watchdog contracts passed
in 6.699 seconds. All eleven cache methods also passed on actual WSL Linux
Python 3.13.14 in 4.087 seconds, with zero skips; the 0644 file refusal executed.
Independent current-schema reviews A and B are both clear; B independently
reran three synchronization/freshness/epoch methods (all passed). No live owner
service, provider, model, configuration or private files were used.

Wheel and source distribution built with the existing pinned packaging runtime
and passed the exact public artifact verifier. Both archives contain byte-exact
current `private_console_unit.py`. Public Node staging was reused from the
previously qualified parent build after verifying identical Git web source trees;
this Python-only change did not rebuild the browser.

## Separate current CI findings

PR #302's exact current Linux failures concern a missing preflight schema-42
gate before migration 43 and a new archival-domain error escaping the private
unit refusal boundary. Those are unrelated existing production issues, tracked
for a separate correctness change; this optimization does not alter either.
