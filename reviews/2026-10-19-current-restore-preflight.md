# Current restore preflight priority

The first complete frozen integration run at13a3e545 completed all12 shards and2636 methods with128 existing platform skips. It failed with15 failure/error events across12 distinct methods and no ResourceWarnings. This record does not claim a full-suite pass. Its unchanged interrupted-restore test exposed a diagnostic ordering error: partial current restore can legitimately lack canonical members, so normal current-database admission must not hide the restore recovery boundary.

Startup now checks the existing read-only restore status before ordinary database/JSON admission, both initially and under the pinned initialization lock. It still refuses every incomplete or invalid restore without mutating source data. It does not resume, upgrade or authorize a restore. Normal missing-current-database and old-database refusal remain unchanged; current CLI recovery still requires its exact preview and confirmation.

The existing Project future-schema refusal test now expects the actual fixed current kernel error type/message instead of an unconstrained Exception containing an obsolete version-specific label. Its feature-era method name now describes current storage. No forward schema becomes accepted.

Five focused methods pass in42.760seconds with ResourceWarnings as errors: exact interrupted restore/no source changes, restore-state change while waiting on the shared lock, missing current database/no recreation, old database/no hardening or initialization, and current future-schema refusal. Existing source-integrity, lock timing and refusal assertions remain. This is selected validation, not qualification of the future combined fix head. Independent source reviews are pending before publication.
