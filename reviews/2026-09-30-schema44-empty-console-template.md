# Schema-44 synthetic empty Console template

Base: PR #313, `1aa741b724484a963b0767dbfe047ad25d834ef0`.
The product stack still used the original uncached constructor; it had never
adopted separate PR #309. The current regression is repeated synthetic
construction, not a schema 44 cache miss or cached operator-state failure.

This focused change replays the independently reviewed immutable synthetic-only
cache. Full exact migration SQL, supported schema set, current schema 44 target,
all imported schema thresholds/limits and code-owned normalizer/construction
identities participate in the hashed LRU recipe. It retains only one immutable
empty unit and serializes only construction/cache lookup; every caller performs
existing full current validation and recipe readback outside that lock. No
operator state, source inspection, scope witness, epoch, readiness, descriptor,
restore result or private root identity is cached. Exceptions are never cached.

Migration 44 adds only empty scope storage/triggers, no new random singleton or
constructor normalizer. Existing virtual 28/32 epochs remain zero; every restore
still rotates them independently. Fresh validation continues through the scope
and shared graph checks, fixed metadata precharge and archival policy. Scope
source gates, claims/revisions, lost-token fences, active/unknown refusal,
closure witnesses, blob pins and production qualification remain unchanged.

## Current evidence

The same isolated Windows 3.11.5 source-only startup/refusal test passed before
and after: 19.190 seconds→4.975 seconds (74.1% lower local subset wall time).
Synthetic initialization fell 12→1; all 6 preparation calls, 12 live-root/registry
checks and 25 post-change full unit validations remain. Runtime/provider
subprocesses were prohibited; only fixed stdlib OS-version queries were allowed.
This is one local workload, not hosted/full-group improvement evidence.

Thirteen Windows cache methods passed in 39.154 seconds (12 pass, 1 POSIX skip).
They cover original exact raw bytes/digest, immutable reuse/single-flight,
migration/history/normalizer recipe changes, constructor/validation failures,
nonempty/changed-root capture, schema 44 empty scope/auth state, independently
fresh restore epochs, scope threshold change, actual supported 43 target bytes,
explicit unsupported 42 refusal/errors not cached, and current scope-validator
faults on warm bytes. Twenty-two warm Windows scope/archive/restore/blob/private-source methods
also passed in 26.267 seconds. Seven unchanged CI inventory/watchdog contracts
passed in 5.325 seconds. Both independent code/backup/recipe reviews are clear;
B independently ran three new 44 epoch/threshold/fault methods successfully.
All 35 cache plus warm-boundary methods also passed on actual supported Linux
Python 3.13.14 in 14.390 seconds with zero skips, including the 0644 file refusal.
Wheel/sdist built with existing pinned setuptools83/wheel0.47 tooling and
passed the exact public artifact verifier. Both contain byte-exact current
private-console source. Previously qualified public Node staging was reused
after verifying identical web source trees; browser code was unchanged.

No model, provider, owner service, credentials or operator root is used. No
watchdog, workflow, existing assertion or security coverage is reduced. The
shared predecessor cache review remains historical on its own PR; this new
uniquely named record avoids stacked documentation conflicts.
