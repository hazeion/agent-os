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

## Composed fixture verification

After the frozen inventory became terminal, both reviewed fixture histories
were normally merged without conflicts: business fixtures f0d1297 and remote
artifact fixtures d358854. The exact merged head was
3a63adf8629d141a770f1e66b8478eb4d6c0eec1; all original commits remain ancestors.

The authorized twelve-module batch used ResourceWarnings as errors and a fresh
private HERMES_HOME. It ran 185 methods in 74.933 seconds: 182 passed, one existing
native-Windows reparse skip and two errors. No ResourceWarning occurred.
The original result/log remain in /private/tmp/mentat-task-seed-focused-result.json
and /private/tmp/mentat-task-seed-focused.log; this run is not claimed all green.

Both errors were missed sparse replacement fixtures in two delegation home
refresh methods, before their business operation. Five records now use the
existing explicit current fixture builder and explicit legacy-unbound profile.
Their connection bindings, remote identities, state/retry fields and all
business assertions are unchanged. Production code is unchanged. The affected
delegation module was rerun separately at
c8245c333c31bd9524f47715885edc82787c0e10: all 24 methods passed in 7.917 seconds,
with ResourceWarnings as errors, no skips and another fresh private HERMES_HOME.
Log: /private/tmp/mentat-task-seed-delegation-correction.log. Across both runs,
184 distinct methods passed and the one existing native-Windows method remained
skipped. This is not a claim that the original 185-method batch passed in one
run. Unrelated passing modules did not receive a broad repeat for this
literal-only fixture correction. No package/security gate or publication has
been performed for this component yet.

The later frozen fc4 full inventory exposed another incomplete positive seed
outside that twelve-module batch: signed local Kanban webhook synchronization.
Only its pre-authority Task literal is ported here: explicit assignee/due_date/
completed_at nulls and the canonical todo spelling preserve its old normalized
values. Exact IDs, delegation/binding/state, signed-event behavior and all
authentication negatives/assertions remain unchanged. Frozen fc4 is untouched
and its full run remains live; no test has run for this source-only fixture
follow-up yet. The Task production validator and previous commits are unchanged.
