# Current Task seed validation

Status: source-only checkpoint, awaiting focused tests and two independent
reviews. No frozen QA files or running checks were changed.

The owner's current-only storage decision retires historical Task JSON
conversion as well as old database upgrades. Packaged seeds already contain
current records. Source preimages task_repository.py, test_task_repository.py
and test_task_delegation.py are identical between pure current-only baseline
302468c47a4f401e7249dfc96ffd2b620086ab05 and frozen QA26228c26.

The only production caller of normalize_legacy_task_collection was
_read_source_snapshot. It now invokes existing normalize_task_collection,
without a fallback, version change or new normalizer. The old normalizer and
its sole _legacy_timestamp helper are removed. The existing strict timestamp,
planning/delegation/extension, byte-limit, authority-receipt, transaction,
source-identity and current recovery-export paths retain their contracts.

Fresh seed and recovery reads refuse sparse core records, naive timestamps,
status/priority aliases and missing delegation profile identity. They do not
invent defaults, append UTC, relabel a status or add an unbound profile. Valid
explicit offsets and Z timestamps remain unchanged. Existing SQLite authority
continues to ignore stale JSON rather than reopening it.

The historical timestamp-conversion positive is retired. Replacement coverage
uses complete current documents with timezone offsets, Z timestamps, planning,
delegation and extension metadata. Negative seed shapes require unchanged
source bytes, exact unchanged current database serialization, zero Task rows
and no Task authority receipt. Delegation fixtures now construct explicit
current records and use the strict validator; all existing behavior assertions
remain. The current missing-connection-binding fixture explicitly retains its
previous legacy-unbound profile metadata, rather than gaining any new authority.
The missing-profile refusal starts from a complete delegation that passes the
current validator, then removes only profile_id; unrelated missing fields
cannot explain the expected rejection.

Caller inspection also found sparse seed fixtures in other test modules;
root assigned those to a separate nonoverlapping fixture workstream. No
non-fixture caller requires a product compatibility decision: startup uses
current seeds and export verifies its own canonical output. No production
compatibility shim is added for tests.

No tests, compilation, package build, security gate or runtime operation has
run on this checkpoint while frozen aggregate inventory26235 is live. Tests
and review will follow in a coordinated quiet window. Unsupported input is
refused; no old data is converted, deleted or silently discarded.
