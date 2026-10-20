# Defer worker-scope FFI initialization to actual scope operations

Base: `13a382dd2c2dd8aaa42efac50fff60c3e7840cfc`.
Branch: `codex/worker-scope-lazy-ctypes-import`.

The first retained Linux custody attempt refused before acquisition: its original
baseline had three FIFO descriptors, while the pre-acquisition inventory had the
same three plus one regular descriptor. No custody API or worker started. The
original blocked result, owners and live session remain unchanged.

A separate disposable controller probe confirmed that importing `ctypes` alone
creates one regular descriptor on the selected Python 3.14.4 host, while leaving
stdio unchanged. This reproduces an import side effect; it does not identify the
original descriptor by target or prove cleanup of that retained resource.

`project_worker_scope` previously imported `ctypes` globally, so importing the
scope and helper dependency chain could initialize FFI before any scope operation.
The production change moves that import into both actual consumers:
`LinuxWorkerScope.__init__` and `_require_cgroup2`. The constructor's exact native
long-width/platform/identity checks and the existing `fstatfs` logic remain intact.
No budgets, custody baseline rules, capability checks or cleanup authority change.

The new portable regression launches isolated `-I -B -S` interpreters for the
scope, system-origin, library-origin and custody imports. An audit hook refuses
`ctypes` or `_ctypes` import, and module inventories must remain free of both.
Another regression substitutes the invocation-local FFI module and verifies that
a four-byte native long still refuses before file or process operations. Existing
Linux ordinary-directory `fstatfs` refusal and scope behavior tests are unchanged.

Verification on the reviewed source checkpoint:

- The focused `WorkerScopeContractTests` class passed all six methods in 1.083
  seconds, with no skips and ResourceWarnings treated as errors. Its four isolated
  import subcases and constructor width refusal all passed.
- The exact old-source archive ran only the unchanged new fresh-import method.
  All four module subcases failed specifically at the old global `import ctypes`,
  with process exit 1. All 1,140 original tracked blobs were verified unchanged
  except the intentionally replaced test file; the constructor mock was not run
  against the old implementation.
- The unchanged tracked-secret gate passed with process exit 0 and the existing
  444-entry baseline unchanged.

The initial focused run's log recorded six passing methods, but its tool session
handle and wrapper exit were not retained. That exit remains unverified. After
root independently established that the original process and wrapper were absent,
root authorized one controlled confirmation solely to resolve this evidence gap.
The confirmation recorded its owned Python PID before waiting, persisted exit 0,
and returned authoritative tool exit 0. It was not a timeout or test-failure retry.
The original log, separate confirmation log, old-source failures and scan evidence
remain preserved.

These are portable focused checks, not native Linux qualification. The original
retained session remains blocked before acquisition, with its original uncertainty
and report unchanged. No new custody attempt, host call, reconciliation or staging
overwrite was performed for this change. The qualification tool's fixed source
pins and baseline fingerprints stay at their existing values; a separately
reviewed qualifier repin is still pending. GitHub CI and merge are outstanding.
