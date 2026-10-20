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

Source checkpoint only: no test, native operation, host call, new custody attempt,
original-session reconciliation or staging overwrite has been performed for this
change. The qualification tool's fixed source pins and baseline fingerprints stay
at their existing values; a later reviewed candidate requires explicit repinning.
