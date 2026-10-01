# Durable Project proposal controller and call journal

Implement the approved controller's durable evidence in schema 43 of the
owner-private Console database. Do not add a sidecar, credential store, generic
network route, Run creator or production dispatch capability. The schema-41
proposal insertion guard remains until qualified admission is implemented.

One immutable controller generation binds one canonical `project_proposal` Run
and its exact schema-42 input manifest, runtime binding and private authority
epoch. It retains the owner-authorized fixed proposal policy and policy digest.
Use a composite SQL Run-ID/source relation restricted to `project_proposal`
plus the schema-42 receipt FK and exact insert postcondition. Console/Task rows
cannot be relabeled as proposal broker authority between audits.
The first proposal operation is one bounded inference completion: no tools,
auto-title, caption fallback or worker-selected call identity. Namespace/bootstrap
and broker/provider qualification remain separate prerequisites; the journal
never turns historical input evidence into execution consent.

Before an inference submission, one guarded transaction creates a host-minted
call identity, exact request digest and irrevocable work debit. The initial
`reserved` state cannot settle or submit; an exact host-held token records
`unknown` before network send, including the commit-before-send crash window.
Only the
first committed reservation returns newly-reserved bookkeeping evidence, not
submission permission. The future broker separately proves exact live admission,
Run state, qualification and Stop/generation fencing. Same-body repeats
return the retained unknown or normalized known result without another provider
call; changed bodies conflict. No restart, SDK retry, failure, interruption or
restore refunds work or allocates a second call for this proposal generation.
A separately approved retry needs a new canonical Run and fresh authorization.
The settlement token is returned only to the first trusted host reservation,
omitted from repr and persisted only as a hash. Recording submission or a
result binds call ID, generation and request digest plus that token; duplicates
cannot reacquire it. This is caller binding, not independent proof a provider
executed. Qualified transport/result attestation remains an integration gate.
Every mutation owns a savepoint, so catching a late validation error and then
committing the caller's outer transaction cannot publish tentative journal rows.
Known failures use fixed `rejected`, `non_text` or `oversized` dispositions with
no raw diagnostics or truncation; repeats return that same failure. Local
metadata probes such as `/api/show` are denied/answered locally and never spend
or forward the sole inference reservation.

Retain only request/result digests and a bounded normalized assistant text
completion (at most 32 KiB), never credentials, paths, raw request messages,
headers, provider request/runtime IDs, reasoning or tool payloads. Freeze the
safe configured provider/model snapshot privately with the policy instead of
consulting mutable current settings for historical provenance. Cached text is broker replay
evidence, not generated-output registration or proposal Apply authority. Validate
the exact Run/input/binding/policy graph, generation/call uniqueness, immutable
debits, result digest and finite timestamps on read/backup. Include the entire
graph in shared private metadata limits, retention and validated backup/restore.
The policy freezes one irrevocable inference work unit, at most 16 MiB request
bytes, 8,192 output tokens, 32 KiB normalized response text and finite
wall/memory/process/CPU ceilings. Enforced values must match its receipt digest;
worker or caller counters cannot choose a different debit.

Use the existing private Project approval epoch as the live capability fence.
Epoch alone is not a live grant check. Before any new provider reservation,
revalidate current Project incarnation/revision/status, lead/Agent/context/grant,
planning-input head, binding and policy in the same guarded private transaction.
That gate is distinct from historical graph validation and later Run admission.
After an already accepted call, trusted exact host reconciliation may retain
its truthful outcome as history without issuing stale-generation authority.
Restore already rotates it and revokes grants. Retain old call outcomes and
spent reservations as history; reject new work, Run finalization or generated-
output authority from a stale generation. Trusted original-token late outcome
accounting is history only. A restored unknown stays unknown, never replayed to a
provider. The future controller must additionally reconcile/fence live kernel
scopes and broker capabilities before admitting new work.

Tests cover exact migration/source drift, no-dispatch guard preservation,
duplicate/changing request and concurrent reservation, crash/reopen unknown,
known-result replay, immutable debit/result tampering, capacity, revocation/
restore epoch fencing, backup/retention graph, and schema-5 compatibility. Use
temporary fixture Runs to exercise historical storage while live admission
remains guarded; do not call a model or reinterpret those fixtures as runtime
qualification. Obtain two independent reviews, repair findings, then full PR.

Private snapshot-only archival validation accepts the exact dormant proposal
Run/input/generation graph, with no leases, capacity/execution claims, events,
attachments, retries, live status or attention item. Canonical Run IDs remain
retained for input/blob evidence; proposal rows remain excluded from the legacy
JSON projection. Default live Run, Inbox and attention validation still reject
proposal state, and SQL insertion guards remain closed. Populated known and
unknown call graphs round-trip through actual private capture, validation,
restore sanitization and materialization with text/debits/token hashes retained,
raw tokens absent and old-epoch work fenced. This private archival allowance
does not establish a producing Run or reopen execution.

Verification: the final migration/attention/journal group passes all 42 tests,
including the 21 journal tests, populated private backup/restore, exact source
guards and worst-case 32 KiB escaped-response accounting. Earlier integration
checks passed 63 forward-migration, deliverable, Run-input and Inbox tests.
The final accounting/reference-inventory delta also passes both independently
run focused tests. Two independent reviewers report no remaining actionable
findings after token binding, savepoint rollback, archival shape, bounded text
validation and precharged terminal accounting corrections. Synthetic fixture
Runs exercise retained storage only; no model or owner credential was used.
All 21 final journal tests also pass on the actual Linux host. Final wheel and
sdist builds pass the exact public-member/RECORD verification, and the installed
wheel imports the schema-43 journal successfully.
